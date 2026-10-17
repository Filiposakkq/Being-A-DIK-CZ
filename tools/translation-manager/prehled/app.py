"""Application state and operations (no HTTP, no UI) — everything the server exposes lives here."""
import json
import os
import bisect
import re
import shutil
import textwrap
import threading
import urllib.parse
import webbrowser
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from . import (__version__, bulk, editor, export, fixes, fontmetrics, gameimages, history as hist, lint, memory, menus, missed, mt, publish as pub, rpy,
               snapshots, spelling, textedit, texthistory, validator)
from .config import Config, migrate_web_json
from .lock import ProjectLock, ProjectLocked
from .project import (DATA_DIR_NAME, STATUS_LABELS, STATUS_ORDER, Project, ProjectUnavailable,
                      check_project_dir, file_status, totals_of)
from .seasons import ACTIVE_EPISODES, SEASONS
from .store import EP_STATES, GLOSSARY_TYPES, Store, parse_value, text_hash, valid_assign
from .util import WriteFailed, norm_ws, text_matcher, write_csv

# Files the legacy tool left next to the script; moved into _progress_data on first open.
LEGACY_FILES = ("web.json", "progress.csv", "historie.csv", "korekce.csv", "epizody.csv",
                "prirazeni.csv", "schvaleno.csv", "progress.json")
# The only addresses the app will open in the browser (the UI sends just the id).
LINKS = {
    "kofi": "https://ko-fi.com/filiposakkq",
    "github": "https://github.com/Filiposakkq",
    "repo": "https://github.com/Filiposakkq/Being-A-DIK-CZ",
    "web": "https://badik.filiposakkq.dev/",
}
# define de = Character("Derek", color="#0066ff")      /      define mc = DynamicCharacter("name", ...)
CHARACTER_RE = re.compile(r"""^\s*define\s+(\w+)\s*=\s*(Dynamic)?Character\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
CHARACTERS_MAX_BYTES = 2 * 1024 * 1024
# First words of Ren'Py screen statements that appear in translated UI blocks; they look like speakers but are not.
SCREEN_KEYWORDS = {"text", "textbutton", "label", "tooltip", "hover", "idle", "insensitive", "timer", "key", "add",
                   "bar", "vbar", "image", "imagebutton", "use", "frame", "window", "vbox", "hbox", "fixed", "grid",
                   "mousearea", "input", "button", "action", "style"}
PAGE_LIMIT = 500
UI_PREF_MAX = 20000


class AppError(Exception):
    """An operation failed for a reason the user should read."""


class ProjectBusy(AppError):
    """The project is open in another running copy of the app (see lock.py)."""

    def __init__(self, message, path):
        super().__init__(message)
        self.path = str(path)


class App:
    def __init__(self, config=None):
        self.config = config or Config().load()
        self.lock = threading.RLock()
        self.project = None
        self.store = None
        self.history = None
        self.data_dir = None
        self.notices = []          # one-off messages for the UI (migration, load problems...)
        self._spell_cache = None
        self._memory_cache = None
        self.texthist = None       # TextHistory of the open project
        self.linter = lint.Linter()
        self._mt_http = None       # replaced in tests
        self._gi = None            # (game folder, GameImages)
        self._val_cache = {}       # rel -> (digest, cfg signature, [(line, Issue, entry)])
        self.last_save_error = ""
        self.plock = None          # ProjectLock of the open project

    # ------------------------------------------------------------ project lifecycle
    def close(self):
        """Release the project lock (called on exit)."""
        if self.plock:
            self.plock.release()
            self.plock = None

    def open_project(self, path, force=False):
        ok, msg = check_project_dir(path)
        if not ok:
            raise AppError(msg)
        root = Path(path).resolve()
        data_dir = root / DATA_DIR_NAME
        try:
            data_dir.mkdir(exist_ok=True)
        except OSError as e:
            raise AppError(f"Ve složce projektu nelze vytvořit {DATA_DIR_NAME} ({e.strerror or e}).") from e
        for name in LEGACY_FILES:                       # data of older versions lying next to the .rpy files
            src, dst = root / name, data_dir / name
            if src.is_file() and not dst.exists():
                try:
                    shutil.move(str(src), str(dst))
                    self.notices.append(f"Soubor {name} byl přesunut do {DATA_DIR_NAME}.")
                except OSError:
                    pass
        with self.lock:
            new_lock = ProjectLock(data_dir)
            try:
                new_lock.acquire(force=force)
            except ProjectLocked as e:
                raise ProjectBusy(str(e), root) from e
            if self.plock:
                self.plock.release()
            self.plock = new_lock
            self.notices = [n for n in self.notices if n]
            msg = migrate_web_json(self.config, data_dir)
            if msg:
                self.notices.append(msg)
            self.data_dir = data_dir
            self.store = Store(data_dir).load()
            self.notices += self.store.warnings
            self.project = Project(root, self.store, skip=self.config.get("skip_files", []),
                                   symbols_as_done=self.config.get("count_symbol_only_as_done"))
            self.history = hist.History(data_dir / "historie.csv", data_dir / "backups")
            self.texthist = texthistory.TextHistory(data_dir / texthistory.FILE_NAME).load()
            self._val_cache.clear()
            report = self.project.refresh(force=True)
            self.store.ensure_files([r.name for r in self.project.rows()])
            self.config.set("project_dir", str(root))
            try:
                self.config.save()
            except WriteFailed as e:
                self.notices.append(f"Nastavení se nepodařilo uložit: {e.reason}")
            self.persist()
            return report

    @property
    def ready(self):
        return self.project is not None

    def _need_project(self):
        if not self.project:
            raise AppError("Není otevřený žádný projekt.")

    # ------------------------------------------------------------ persistence of derived files
    def persist(self):
        """Write progress.csv, the history row and the local progress.json. Returns a list of problems."""
        self._need_project()
        problems = []
        rows = self.project.rows()
        try:
            write_csv(self.data_dir / "progress.csv",
                      [["soubor", "prelozeno", "zbyva", "celkem", "zkontrolovano", "preklad_%", "korektura_%"]]
                      + [[r.name, r.done, r.todo, r.total, r.corr, f"{r.done / r.total * 100:.1f}",
                          f"{r.corr / r.total * 100:.1f}"] for r in rows])
        except WriteFailed as e:
            problems.append(str(e))
        t_done, total, c_done, tpct, cpct = totals_of(rows)
        try:
            self.history.record(datetime.now().strftime(hist.STAMP_FORMAT), t_done, total, tpct, c_done, cpct)
        except WriteFailed as e:
            problems.append(str(e))
        try:
            export.write_local(self.data_dir / "progress.json", self.build_export())
        except (WriteFailed, ValueError) as e:
            problems.append(str(e))
        self.last_save_error = "; ".join(problems)
        return problems

    def build_export(self):
        return export.build_progress(self.project.rows(), self.store, self.history,
                                     title=self.config.get("web.title", ""))

    # ------------------------------------------------------------ refresh
    def refresh(self, force=False, client_dirty=False, discard=False):
        """Rescan the project folder without restarting. Returns a dict for the UI.

        Nothing the translator typed is dropped by a refresh, but if there is something not yet
        saved (a failed save, or an edit still open in the UI) the caller must confirm first."""
        self._need_project()
        with self.lock:
            retried = []
            for kind in sorted(self.store.unsaved):
                try:
                    self.store.save(kind)
                    retried.append(kind)
                except WriteFailed:
                    pass
            if (self.store.unsaved or client_dirty) and not discard:
                return {"needs_confirm": True,
                        "message": ("Máš neuložené změny" + (f" ({', '.join(sorted(self.store.unsaved))} se nepodařilo zapsat)"
                                                              if self.store.unsaved else " (rozeditované pole)")
                                    + ". Obnovení souborů je nezahodí z paměti, ale rozeditovaná pole se přepíšou. Pokračovat?")}
            try:
                rep = self.project.refresh(force=force)
            except ProjectUnavailable as e:
                raise AppError(str(e)) from e
            self._log_external(rep.prev)
            moved = self.project.migrate_metadata(rep.renamed) if rep.renamed else 0
            self.store.ensure_files([r.name for r in self.project.rows()])
            problems = self.persist() if rep.changed else []
            out = rep.to_dict()
            out.update(moved_metadata=moved, save_problems=problems, retried=retried, needs_confirm=False)
            return out

    # ------------------------------------------------------------ validation
    def _length_cfg(self):
        return self.config.get("validation.length", {})

    def _terms(self):
        """Glossary terms {English: Czech} used by the term-consistency check."""
        return {c: g["n"] for c, g in self.store.glossary.items() if g["t"] == "term" and g["n"]}

    def _spell(self):
        """Spelling hints built from the whole project's translated text; rebuilt when any file or the glossary changes."""
        if not self.config.get("validation.spelling", True):
            return None
        key = (tuple(sorted((rel, id(fi.parsed)) for rel, fi in self.project.files.items())),
               tuple(sorted((c, g["n"]) for c, g in self.store.glossary.items())))
        if self._spell_cache and self._spell_cache[0] == key:
            return self._spell_cache[1]
        known = set()
        for c, g in self.store.glossary.items():
            known.update(spelling.words_of(c))
            known.update(spelling.words_of(g["n"]))
        targets = (e.target for fi in self.project.files.values() for e in fi.parsed.entries if not e.pending)
        obj = spelling.Spelling.build(targets, known)
        self._spell_cache = (key, obj)
        return obj

    def _raw_issues(self, rel):
        fi = self.project.files[rel]
        terms = self._terms()
        spell = self._spell()
        tb = self.config.get("validation.textbox", {})
        sig = json.dumps([self._length_cfg(), terms, tb, spell.sig if spell else ""], sort_keys=True)
        hit = self._val_cache.get(rel)
        if hit and hit[0] is fi.parsed and hit[1] == sig:
            return hit[2]
        res = validator.check_parsed(fi.parsed, self._length_cfg(), terms, spell, tb)
        self._val_cache[rel] = (fi.parsed, sig, res)
        return res

    # ------------------------------------------------------------ ignored findings
    def _ignored_mark(self, rel, e, iss):
        """The stored ignore of this finding if it still applies (same code, same translation text), else None."""
        if e is None:
            return None
        marks = self.store.ignored.get(rel)
        if not marks:
            return None
        m = marks.get((e.block, norm_ws(e.source if e.source is not None else e.target), iss.code))
        return m if m and m["h"] == text_hash(e.target) else None

    def _issues(self, rel, ignored=False):
        """Findings of a file; by default without the ones the translator ignored (ignored=True: only those)."""
        raw = self._raw_issues(rel)
        if not self.store.ignored.get(rel):
            return [] if ignored else raw
        return [r for r in raw if bool(self._ignored_mark(rel, r[2], r[1])) == ignored]

    def ignore_set(self, items, on=True, note=""):
        """Ignore (on=True) or stop ignoring findings. Items: [{file, line, code}] (or {file, key, code} to stop ignoring
        a finding whose line no longer exists). An ignore is bound to the current translation text: when the text
        changes the finding shows up again. One undo step. Returns {changed, skipped}."""
        self._need_project()
        with self.lock:
            plan, skipped = [], []
            for it in items:
                rel, code = it.get("file"), str(it.get("code", ""))
                if rel not in self.project.files:
                    skipped.append((rel, "neznámý soubor"))
                    continue
                ents = self.project.entries(rel)
                e = None
                if it.get("line"):
                    e = next((x for x in ents if x.line == int(it["line"])), None)
                    key = None if e is None else (e.block, norm_ws(e.source if e.source is not None else e.target), code)
                else:
                    k = it.get("key") or ["", ""]
                    key = (str(k[0]), norm_ws(str(k[1])), code)
                    e = next((x for x in ents if (x.block, norm_ws(x.source if x.source is not None else x.target)) == key[:2]), None)
                if key is None:
                    skipped.append((rel, "řádek se v souboru změnil – obnov soubory"))
                elif on and not any(r[2] is e and r[1].code == code for r in self._raw_issues(rel)):
                    skipped.append((rel, "tenhle nález už neexistuje"))
                else:
                    plan.append((rel, key, e))
            changed = 0
            clean_note = str(note or "").strip()[:300]

            def go():
                nonlocal changed
                today = date.today().isoformat()
                for rel, key, e in plan:
                    marks = self.store.ignored.setdefault(rel, {})
                    if on:
                        new = {"h": text_hash(e.target), "n": clean_note, "d": today}
                        if marks.get(key) != new:
                            marks[key] = new
                            changed += 1
                    elif marks.pop(key, None) is not None:
                        changed += 1
                    if not marks:
                        self.store.ignored.pop(rel, None)
            self.store.change("Ignorování nálezů" if on else "Zrušení ignorování", ("ignored",), go)
            out = self._changed("ignore")
            out.update(changed=changed, skipped=skipped)
            return out

    def ignored_list(self):
        """Everything the translator chose to ignore, with its current state:
        active (still hidden), expired (the translation changed, the finding is shown again),
        resolved (the finding no longer occurs) or gone (the line no longer exists)."""
        self._need_project()
        out = []
        for rel in sorted(self.store.ignored, key=str.lower):
            if rel not in self.project.files:
                for (blk, src, code), m in sorted(self.store.ignored[rel].items()):
                    out.append({"file": rel, "line": 0, "key": [blk, src], "code": code, "note": m["n"], "date": m["d"],
                                "state": "gone", "message": "", "severity": "", "source": src, "target": ""})
                continue
            ents = self.project.entries(rel)
            raw = self._raw_issues(rel)
            for (blk, src, code), m in sorted(self.store.ignored[rel].items()):
                e = next((x for x in ents if (x.block, norm_ws(x.source if x.source is not None else x.target)) == (blk, src)), None)
                rec = {"file": rel, "line": e.line if e else 0, "key": [blk, src], "code": code, "note": m["n"], "date": m["d"],
                       "message": "", "severity": "", "source": (e.source if e and e.source is not None else src),
                       "target": e.target if e else ""}
                if e is None:
                    rec["state"] = "gone"
                elif m["h"] != text_hash(e.target):
                    rec["state"] = "expired"
                else:
                    hit = next((r[1] for r in raw if r[2] is e and r[1].code == code), None)
                    rec["state"] = "active" if hit else "resolved"
                    if hit:
                        rec["message"], rec["severity"] = hit.message, hit.severity
                out.append(rec)
        return {"items": out, "counts": {s: sum(1 for r in out if r["state"] == s)
                                         for s in ("active", "expired", "resolved", "gone")}}

    def _all_issues(self):
        if not self.config.get("validation.enabled", True):
            return {}
        return {rel: self._issues(rel) for rel in self.project.files}

    def _duplicate_ids(self):
        """Duplicate `translate <lang> <id>` blocks across the project (Ren'Py rejects them)."""
        seen, dup = {}, []
        for rel in sorted(self.project.files):
            for lang, ident, line in self.project.files[rel].parsed.block_ids:
                k = (lang, ident)
                if k in seen:
                    dup.append((rel, line, seen[k]))
                else:
                    seen[k] = f"{rel}:{line}"
        return dup

    def validation_summary(self):
        counts = {"error": 0, "warning": 0, "info": 0, "length": 0}
        per_file = {}
        for rel, items in self._all_issues().items():
            c = {"error": 0, "warning": 0, "info": 0}
            for _line, iss, _e in items:
                if iss.category == "length":
                    counts["length"] += 1
                counts[iss.severity] += 1
                c[iss.severity] += 1
            per_file[rel] = c
        show_info = self.config.get("validation.show_info", False)
        counts["ignored"] = sum(1 for rel in self.project.files for _l, i, _e in self._issues(rel, True)
                               if i.severity != "info" or show_info) if self.config.get("validation.enabled", True) else 0
        dups = self._duplicate_ids() if self.config.get("validation.enabled", True) else []
        counts["error"] += len(dups)
        for rel, _l, _w in dups:
            per_file.setdefault(rel, {"error": 0, "warning": 0, "info": 0})["error"] += 1
        return counts, per_file

    def validation_list(self, severity="", category="", file="", q="", offset=0, limit=200, ignored="hide", group="", word=False):
        """Findings. ignored: "hide" (default) | "only" (just the ignored ones) | "all".
        group="line": one item per line with all its (matching) findings in `issues`; total counts lines."""
        self._need_project()
        out = []
        match = text_matcher(q, word)
        show_info = self.config.get("validation.show_info", False)
        enabled = self.config.get("validation.enabled", True)
        sev_counts = {"error": 0, "warning": 0, "info": 0}     # for the filter pills: every filter except the severity
        for rel in sorted(self.project.files) if enabled else []:
            if file and rel != file:
                continue
            rows = []
            if ignored in ("hide", "all"):
                rows += [(r, False) for r in self._issues(rel)]
            if ignored in ("only", "all"):
                rows += [(r, True) for r in self._issues(rel, True)]
            for (line, iss, e), is_ign in rows:
                if category and iss.category != category:
                    continue
                if match and not match(iss.message + " " + rel + " " + (e.target if e else "")):
                    continue
                sev_counts[iss.severity] += 1
                if severity and iss.severity != severity:
                    continue
                if not severity and iss.severity == "info" and not show_info:
                    continue
                out.append({"file": rel, "line": line, "severity": iss.severity, "code": iss.code,
                            "category": iss.category, "message": iss.message,
                            "source": e.source if e else "", "target": e.target if e else "",
                            "who": e.who if e else "", "extra": iss.extra,
                            "src_who": e.src_who if e else "", "ignored": is_ign,
                            "ignore_note": (self._ignored_mark(rel, e, iss) or {}).get("n", "") if is_ign else ""})
        if not category and not q and ignored != "only":
            for rel, line, first in self._duplicate_ids():
                if not file or rel == file:
                    sev_counts["error"] += 1
                    if severity and severity != "error":
                        continue
                    out.append({"file": rel, "line": line, "severity": "error", "code": "duplicate-id",
                                "category": "structure", "message": f"Blok translate se stejným identifikátorem už existuje ({first}); Ren'Py ho odmítne.",
                                "source": "", "target": "", "who": "", "extra": {}})
        order = {"error": 0, "warning": 1, "info": 2}
        out.sort(key=lambda r: (order[r["severity"]], r["file"].lower(), r["line"]))
        if group == "line":
            lines = {}
            for r in out:                                   # `out` is sorted by severity, so the first finding is the worst
                g = lines.get((r["file"], r["line"]))
                if g is None:
                    g = lines[(r["file"], r["line"])] = {"file": r["file"], "line": r["line"], "severity": r["severity"],
                                                          "source": r["source"], "target": r["target"], "who": r["who"],
                                                          "src_who": r.get("src_who", ""), "issues": []}
                g["issues"].append({k: r[k] for k in ("severity", "code", "category", "message", "extra", "ignored", "ignore_note")
                                    if k in r})
            grouped = sorted(lines.values(), key=lambda g: (order[g["severity"]], g["file"].lower(), g["line"]))
            return {"total": len(grouped), "findings": len(out), "sev_counts": sev_counts, "items": grouped[offset:offset + limit]}
        return {"total": len(out), "sev_counts": sev_counts, "items": out[offset:offset + limit]}

    # ------------------------------------------------------------ overview / files
    def estimate(self):
        rows = self.project.rows()
        t_done, total, *_ = totals_of(rows)
        est = hist.estimate(self.history.points(), t_done, total)
        for k in ("eta", "eta_early", "eta_late"):
            est[k] = est[k].isoformat() if est[k] else None
        return est

    def goals(self):
        """Weekly goals and this week's progress (see history.goals)."""
        rows = self.project.rows()
        t_done, total, c_done, *_ = totals_of(rows)
        return hist.goals(self.history.points(), max(0, total - t_done), max(0, total - c_done), self.config.get("goals", {}))

    def overview(self):
        self._need_project()
        rows = self.project.rows()
        t_done, total, c_done, tpct, cpct = totals_of(rows)
        counts = {k: 0 for k in STATUS_LABELS}
        for r in rows:
            counts[file_status(r.done, r.todo, r.total, r.corr)] += 1
        approved = sum(len(v) for v in self.store.approved.values())
        marked = flagged = stale = 0
        for rel in self.store.proof:
            if rel in self.project.files:
                ok, fix = self.project.proof_counts(rel)
                marked, flagged = marked + ok, flagged + fix
                stale += self.project.proof_stale(rel)
        stats = export.stats_for(rows, self.store)
        est_now = self.estimate()
        pace = est_now.get("pace_per_day")
        for e in stats["episodes"]:                       # how long an episode would take at the current pace
            left = e["translation"]["total"] - e["translation"]["done"]
            e["eta_days"] = int(-(-left // pace)) if pace and left > 0 else None
        vcounts, per_file = self.validation_summary()
        pts = self.history.points()
        recent = []
        prev = None
        for ts, done, tot, corr in pts[-40:]:
            if prev is not None and (done != prev[1] or corr != prev[3]):
                recent.append({"at": ts.strftime(hist.STAMP_FORMAT), "translated": done - prev[1],
                               "proofread": corr - prev[3], "total_translated": done})
            prev = (ts, done, tot, corr)
        return {
            "project": {"path": str(self.project.root), "data_dir": str(self.data_dir),
                        "files": len(rows), "skipped": sorted(self.project.skip)},
            "totals": {"done": t_done, "total": total, "remaining": total - t_done, "percent": round(tpct, 1),
                       "proofread": c_done, "proofread_percent": round(cpct, 1), "approved": approved,
                       "proof_marked": marked, "proof_fix": flagged, "proof_stale": stale},
            "file_counts": counts,
            "seasons": stats["seasons"], "episodes": stats["episodes"],
            "general": stats["general"], "unassigned": stats["unassigned"],
            "validation": vcounts, "worst_files": self._worst_files(per_file), "goals": self.goals(),
            "estimate": est_now,
            "recent": recent[-8:][::-1],
            "undo": [s["label"] for s in self.store.undo_stack][-5:][::-1],
            "unsaved": sorted(self.store.unsaved),
            "last_save_error": self.last_save_error,
            "last_refresh": self.project.last_report.to_dict() if self.project.last_report else None,
            "lock_lost": bool(self.plock and not self.plock.check()),
            "loaded_at": self.project.loaded_at,
            "episode_states": [{"key": k, "label": l} for k, l in EP_STATES],
        }

    def files_payload(self):
        self._need_project()
        _, per_file = self.validation_summary()
        out = []
        for r in self.project.rows():
            appr = self.project.counts(r.name)[2]
            st = file_status(r.done, r.todo, r.total, r.corr)
            v = per_file.get(r.name, {"error": 0, "warning": 0, "info": 0})
            p_ok, p_fix = self.project.proof_counts(r.name)
            out.append({"name": r.name, "proof_marked": p_ok, "proof_fix": p_fix, "assign": self.store.assign.get(r.name, ""), "total": r.total,
                        "done": r.done, "auto": r.auto, "todo": r.todo, "corr": r.corr, "approved": appr,
                        "status": st, "order": STATUS_ORDER[st], "errors": v["error"], "warnings": v["warning"],
                        "proof_stale": self.project.proof_stale(r.name)})
        return out

    # ------------------------------------------------------------ entries
    def _entry_row(self, rel, e):
        approved = self.store.approved.get(rel, ())
        if not e.pending:
            status = "translated"
        elif e.key in approved:
            status = "approved"
        else:
            status = "todo"
        return status

    def entries(self, file="", status="all", kind="", q="", issues="", sort="line", offset=0, limit=200, around=0,
                unit="", word=False):
        """Paged, filtered list of translation units (server side, so 45k lines stay fast)."""
        self._need_project()
        limit = max(1, min(int(limit), PAGE_LIMIT))
        match = text_matcher(q, word)
        files = [file] if file else sorted(self.project.files, key=str.lower)
        if file and file not in self.project.files:
            raise AppError("Neznámý soubor.")
        iss_by = {}
        if self.config.get("validation.enabled", True):
            for rel in files:
                for line, iss, _e in self._issues(rel):
                    iss_by.setdefault((rel, line), []).append(iss)
        rows = []
        counts = {k: 0 for k in ("all", "todo", "approved", "translated", "review", "proofed", "fix", "stale")}
        for rel in files:
            for e in self.project.entries(rel):
                st = self._entry_row(rel, e)
                pf = self.project.proof_state(rel, e) if st != "todo" else ""
                member = {"all": True, "todo": st == "todo", "approved": st == "approved", "translated": st == "translated",
                          "review": st != "todo" and pf not in ("ok", "fix"), "proofed": pf == "ok", "fix": pf == "fix",
                          "stale": pf == "stale"}
                kinds = rpy.KIND_CODE.get(e.category, "")
                if kind and kinds != kind:
                    continue
                if unit and e.unit != unit:
                    continue
                iss = iss_by.get((rel, e.line), [])
                shown = [i for i in iss if i.severity != "info" or self.config.get("validation.show_info", False)]
                if issues == "any" and not shown:
                    continue
                if issues == "error" and not any(i.severity == "error" for i in shown):
                    continue
                if issues == "warning" and not any(i.severity == "warning" for i in shown):
                    continue
                if issues == "overflow" and not any(i.code == "textbox-overflow" for i in iss):
                    continue
                if match and not (match(e.target) or match(e.source) or match(e.who) or match(rel)
                                  or match(self.store.glossary.get(self.speaker_code(e.who), {}).get("n", ""))):
                    continue
                for k, v in member.items():            # counts for the status pills: every filter except the status itself
                    if v:
                        counts[k] += 1
                if status in member and not member[status]:
                    continue
                rows.append((rel, e, st, shown, pf))
        if sort == "kind":
            rows.sort(key=lambda r: (rpy.KIND_RANK.get(r[1].category, 9), r[0].lower(), r[1].line))
        elif sort == "issues":
            rows.sort(key=lambda r: (-sum(3 if i.severity == "error" else 1 for i in r[3]), r[0].lower(), r[1].line))
        elif sort == "file":
            rows.sort(key=lambda r: (r[0].lower(), r[1].line))
        total = len(rows)
        if around:
            idx = next((i for i, r in enumerate(rows) if r[1].line == around and (not file or r[0] == file)), None)
            if idx is not None:
                offset = max(0, idx - 30)
        page = rows[offset:offset + limit]
        return {"total": total, "offset": offset, "counts": counts, "items": [{
            "file": rel, "line": e.line, "src_line": e.src_line, "block": e.block, "who": e.who,
            "source": e.source, "target": e.target, "status": st,
            "kind": rpy.KIND_CODE.get(e.category, ""), "proof": pf, "unit": e.unit, "ref": e.ref,
            "issues": [{"severity": i.severity, "code": i.code} for i in shown],
        } for rel, e, st, shown, pf in page]}

    def entry_detail(self, rel, line):
        self._need_project()
        if rel not in self.project.files:
            raise AppError("Neznámý soubor.")
        ents = self.project.entries(rel)
        idx = next((i for i, e in enumerate(ents) if e.line == line), None)
        if idx is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        e = ents[idx]
        on = self.config.get("validation.enabled", True)
        iss = [i for ln, i, _e in self._issues(rel) if ln == line] if on else []
        ign = [(i, self._ignored_mark(rel, e, i)) for ln, i, _e in self._issues(rel, True) if ln == line] if on else []

        def brief(x):
            return {"line": x.line, "who": x.who, "source": x.source, "target": x.target,
                    "status": self._entry_row(rel, x),
                    "proof": self.project.proof_state(rel, x) if self.project.is_translated(rel, x) else ""}
        return {"file": rel, "path": str(self.project.root / rel), "line": e.line, "src_line": e.src_line,
                "block": e.block, "who": e.who, "unit": e.unit, "ref": e.ref, "source": e.source, "target": e.target,
                "src_raw": e.src_raw, "cur_raw": e.cur_raw,
                "status": self._entry_row(rel, e), "kind": rpy.KIND_CODE.get(e.category, ""),
                "proof": self.project.proof_state(rel, e) if self.project.is_translated(rel, e) else "",
                "proof_note": self.store.proof.get(rel, {}).get(e.key, {}).get("n", ""),
                "proof_date": self.store.proof.get(rel, {}).get(e.key, {}).get("d", ""),
                "kind_label": e.category, "key": [e.block, norm_ws(e.source if e.source is not None else e.target)],
                "terms": [{"en": en, "cz": cz, "used": validator.term_used(e.target, cz)} for en, cz in self._terms().items()
                          if e.source is not None and validator.term_in_text(e.source, en)],
                "issues": [dict(i.to_dict(), ignored=False) for i in iss]
                          + [dict(i.to_dict(), ignored=True, ignore_note=(m or {}).get("n", "")) for i, m in ign],
                "before": [brief(x) for x in ents[max(0, idx - 2):idx]],
                "after": [brief(x) for x in ents[idx + 1:idx + 3]]}

    # ------------------------------------------------------------ mutations
    def _changed(self, label):
        """After a store change: derived files + a result the UI can show."""
        problems = self.persist()
        return {"ok": True, "problems": problems, "label": label}

    def save_file(self, name, c, t):
        self._need_project()
        with self.lock:
            if name not in self.project.files:
                raise AppError("Neznámý soubor.")
            row = self.project.row(name)
            total, auto = row.total, row.auto
            c_n, t_n = parse_value(c, total), parse_value(t, total)
            if t_n is not None and t_n == auto:
                t_n = None
            # the number shown = hand-typed baseline + lines marked one by one; keep the marks, store the rest
            c_n = max(0, c_n - self.project.proof_counts(name)[0]) if c_n else c_n

            def go():
                self.store.corr[name] = {"c": "" if not c_n else str(c_n), "t": "" if t_n is None else str(t_n)}
            self.store.change(f"Úprava počtů v {Path(name).name}", ("corr",), go)
            return self._changed("save")

    # ------------------------------------------------------------ glossary
    @staticmethod
    def speaker_code(who):
        """'mc happy' -> 'mc': the character code is the first word, the rest are image attributes."""
        parts = (who or "").split()
        return parts[0] if parts else ""

    def glossary_payload(self):
        """Glossary rows: every speaker code found in the project (with its line count and an example)
        merged with the saved names, plus saved entries that are not speakers (terms)."""
        self._need_project()
        found = {}
        for rel in sorted(self.project.files, key=str.lower):
            for e in self.project.entries(rel):
                code = self.speaker_code(e.who)
                if e.unit == "dialogue" and code and code not in SCREEN_KEYWORDS:
                    f = found.setdefault(code, {"count": 0, "example": "", "file": rel, "line": e.line})
                    f["count"] += 1
                    if not f["example"] and e.source:
                        f["example"] = e.source[:90]
        items = []
        for code, f in found.items():
            g = self.store.glossary.get(code, {})
            items.append({"code": code, "name": g.get("n", ""), "type": g.get("t", "speaker"), "note": g.get("c", ""),
                          "count": f["count"], "example": f["example"], "file": f["file"], "line": f["line"],
                          "in_project": True})
        for code, g in self.store.glossary.items():
            if code not in found:
                items.append({"code": code, "name": g["n"], "type": g["t"], "note": g["c"], "count": 0,
                              "example": "", "file": "", "line": 0, "in_project": False})
        items.sort(key=lambda i: (-i["count"], i["code"].lower()))
        names = {c: g["n"] for c, g in self.store.glossary.items() if g["n"] and g["t"] == "speaker"}
        return {"items": items, "names": names, "types": list(GLOSSARY_TYPES),
                "unnamed": sum(1 for i in items if i["type"] == "speaker" and i["in_project"] and not i["name"])}

    def glossary_set(self, items):
        """Create / update entries. An entry with neither name nor note is removed. One undo step."""
        self._need_project()
        clean = []
        for it in items:
            code = str(it.get("code", "")).strip()
            if not code or len(code) > 60 or any(ch in code for ch in "\r\n"):
                raise AppError(f"Neplatný kód: {code!r}")
            typ = it.get("type", "speaker")
            if typ not in GLOSSARY_TYPES:
                raise AppError("Neplatný typ položky slovníku.")
            name, note = str(it.get("name", "")).strip(), str(it.get("note", "")).strip()
            if len(name) > 200 or len(note) > 500:
                raise AppError("Jméno nebo poznámka je příliš dlouhá.")
            clean.append((code, name, typ, note))
        with self.lock:
            def go():
                for code, name, typ, note in clean:
                    if name or note:
                        self.store.glossary[code] = {"n": name, "t": typ, "c": note}
                    else:
                        self.store.glossary.pop(code, None)
            self.store.change(f"Slovník ({len(clean)})", ("glossary",), go)
            return {"ok": True, **self.glossary_payload()}

    def find_characters_files(self):
        """All character definition files of the game: characters.rpy, season2/scripts/characters_season2.rpy ...
        The translation folder is usually <game>/game/tl/<lang>, so the game folder is searched upwards."""
        root = self.project.root
        for base in (root.parent.parent, root.parent, root, root.parent.parent.parent):
            if not base.is_dir():
                continue
            found = []
            for dirpath, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d.lower() not in ("tl", "cache", "saves", "_progress_data", ".git")]
                found += [Path(dirpath) / f for f in files if f.lower().startswith("characters") and f.lower().endswith(".rpy")]
            if found:
                return sorted(found, key=lambda x: str(x).lower())      # Ren'Py loads files in path order
        return []

    def glossary_import_preview(self, path=""):
        """Read `define xx = Character("Name", ...)` lines of the game's character files and compare with the
        glossary. Nothing is written. `path` may be a file, a folder (all characters*.rpy below it) or empty
        (found automatically). Ren'Py rule: a later definition of the same code replaces an earlier one, so the
        last one wins; codes defined several times with different names are reported in `duplicates`.
        states: new | same | conflict (another name is already stored) | dynamic (name comes from a variable)."""
        self._need_project()
        given = str(path).strip()
        if given:
            target = Path(given).expanduser()
            if target.is_dir():
                files = sorted((p for p in target.rglob("characters*.rpy") if "tl" not in p.relative_to(target).parts),
                               key=lambda x: str(x).lower())
            else:
                files = [target]
        else:
            files = self.find_characters_files()
        if not files:
            return {"path": given, "files": [], "items": [], "missing": [], "duplicates": [],
                    "message": "Soubory characters*.rpy nebyly nalezeny – zadej cestu k souboru nebo ke složce hry."}
        defs = {}          # code -> list of (name, dynamic, file)
        for f in files:
            if f.suffix.lower() != ".rpy":
                raise AppError("Importovat lze jen soubory .rpy (characters.rpy).")
            try:
                if not f.is_file():
                    raise AppError(f"Soubor neexistuje: {f}")
                if f.stat().st_size > CHARACTERS_MAX_BYTES:
                    raise AppError(f"Soubor je příliš velký na seznam postav: {f.name}")
                text = f.read_text(encoding="utf-8-sig", errors="replace")
            except OSError as e:
                raise AppError(f"Soubor nelze přečíst: {e.strerror or e}") from e
            for line in text.splitlines():
                m = CHARACTER_RE.match(line)
                if m:
                    name = (m.group(3) if m.group(3) is not None else m.group(4) or "").replace('\\"', '"').strip()
                    defs.setdefault(m.group(1), []).append((name, bool(m.group(2)), f))
        in_project = {self.speaker_code(e.who) for rel in self.project.files for e in self.project.entries(rel)
                      if e.unit == "dialogue"} - SCREEN_KEYWORDS
        game_dir = None
        try:
            game_dir = Path(os.path.commonpath([str(f.parent) for f in files]))
        except ValueError:
            pass
        items, duplicates = [], []
        for code, versions in defs.items():
            name, dynamic, src = versions[-1]
            names = []
            for n, _d, _f in versions:
                if n and n not in names:
                    names.append(n)
            if len(names) > 1:
                duplicates.append({"code": code, "names": names, "used": name})
            cur = self.store.glossary.get(code, {}).get("n", "")
            if dynamic:
                state, name = "dynamic", ""
            elif not name:
                continue
            elif not cur:
                state = "new"
            elif cur == name:
                state = "same"
            else:
                state = "conflict"
            try:
                shown = str(src.relative_to(game_dir)) if game_dir else src.name
            except ValueError:
                shown = src.name
            note = "jméno zadává hráč (DynamicCharacter)" if dynamic else (
                f"definováno víckrát ({' / '.join(names)}), platí poslední" if len(names) > 1 else "")
            items.append({"code": code, "name": name, "current": cur, "state": state, "in_project": code in in_project,
                          "note": note, "source": shown})
        missing = sorted(c for c in in_project - set(defs) if c)
        return {"path": given or str(game_dir or files[0].parent), "files": [str(f) for f in files], "items": items,
                "missing": missing, "duplicates": duplicates, "message": ""}

    def glossary_import_apply(self, items):
        """Store the reviewed names (a stored note is kept). One undo step."""
        self._need_project()
        out = []
        for it in items:
            code = str(it.get("code", "")).strip()
            cur = self.store.glossary.get(code, {})
            out.append({"code": code, "name": str(it.get("name", "")).strip(), "type": "speaker",
                        "note": cur.get("c", "") or str(it.get("note", ""))})
        return self.glossary_set(out)

    def glossary_delete(self, codes):
        self._need_project()
        with self.lock:
            self.store.change(f"Slovník: smazáno ({len(codes)})", ("glossary",),
                              lambda: [self.store.glossary.pop(str(c), None) for c in codes])
            return {"ok": True, **self.glossary_payload()}

    # ------------------------------------------------------------ proofreading
    def _proof_entry(self, rel, key):
        key = (str(key[0]), norm_ws(str(key[1])))
        e = next((x for x in self.project.entries(rel) if x.key == key), None)
        return key, e

    def proof_set(self, items, state, note=None):
        """Mark lines proofread ('ok'), flagged for fixing ('fix', optional note) or clear the mark ('').
        Only translated lines can be proofread. One undo step. Returns {changed, skipped}."""
        self._need_project()
        if state not in ("ok", "fix", ""):
            raise AppError("Neplatný stav korektury.")
        with self.lock:
            plan, skipped = [], []
            for it in items:
                rel = it.get("file")
                if rel not in self.project.files:
                    skipped.append((rel, "neznámý soubor"))
                    continue
                key, e = self._proof_entry(rel, it.get("key") or ["", ""])
                if e is None:
                    skipped.append((rel, "řádek se v souboru změnil – obnov soubory"))
                elif state and not self.project.is_translated(rel, e):
                    skipped.append((rel, "řádek ještě není přeložený"))
                else:
                    plan.append((rel, key, e))
            changed = 0

            def go():
                nonlocal changed
                today = date.today().isoformat()
                for rel, key, e in plan:
                    marks = self.store.proof.setdefault(rel, {})
                    old = marks.get(key)
                    if not state:
                        if marks.pop(key, None) is not None:
                            changed += 1
                    else:
                        keep = (old or {}).get("n", "")
                        new = {"s": state, "h": text_hash(e.target), "d": today,
                               "n": note if note is not None else keep}
                        if old != new:
                            marks[key] = new
                            changed += 1
                    if not marks:
                        self.store.proof.pop(rel, None)
            label = {"ok": "Korektura: zkontrolováno", "fix": "Korektura: k opravě", "": "Korektura: zrušeno"}[state]
            self.store.change(f"{label} ({len(plan)})", ("proof",), go)
            out = self._changed("proof")
            out.update(changed=changed, skipped=skipped)
            return out

    def proof_upto(self, rel, line, state="ok"):
        """Every line of a file up to `line` (inclusive):
        state "ok"  - mark translated lines that are not yet proofread (or whose proofreading went stale) as proofread;
        state ""    - take the "proofread" mark away again (also stale ones). Lines flagged "to fix" are left alone."""
        self._need_project()
        if state not in ("ok", ""):
            raise AppError("Neplatný stav korektury.")
        with self.lock:
            if rel not in self.project.files:
                raise AppError("Neznámý soubor.")
            wanted = ("", "stale") if state == "ok" else ("ok", "stale")
            items = [{"file": rel, "key": list(e.key)} for e in self.project.entries(rel)
                     if e.line <= line and self.project.is_translated(rel, e)
                     and self.project.proof_state(rel, e) in wanted]
            if not items:
                return {"ok": True, "changed": 0, "skipped": [], "problems": []}
            return self.proof_set(items, state)

    def proof_clear_file(self, rel):
        """Remove all per-line proofread marks of a file (one undo step)."""
        self._need_project()
        with self.lock:
            if rel not in self.project.files:
                raise AppError("Neznámý soubor.")
            n = len(self.store.proof.get(rel, {}))
            self.store.change(f"Korektura: smazány značky v {Path(rel).name}", ("proof",),
                              lambda: self.store.proof.pop(rel, None))
            out = self._changed("proof")
            out["changed"] = n
            return out

    def proof_next(self, file="", after=0):
        """First translated line (after `after`, in file order) that still needs proofreading, or None."""
        self._need_project()
        files = [file] if file else sorted(self.project.files, key=str.lower)
        for rel in files:
            if rel not in self.project.files:
                raise AppError("Neznámý soubor.")
            for e in self.project.entries(rel):
                if (not file or e.line > after) and self.project.is_translated(rel, e) \
                        and self.project.proof_state(rel, e) in ("", "stale"):
                    return {"found": True, "file": rel, "line": e.line}
        return {"found": False}

    def set_assign(self, name, v):
        self._need_project()
        with self.lock:
            if name not in self.project.files or not valid_assign(v):
                raise AppError("Neplatná hodnota.")

            def go():
                if v:
                    self.store.assign[name] = v
                else:
                    self.store.assign.pop(name, None)
            self.store.change(f"Zařazení {Path(name).name}", ("assign",), go)
            return self._changed("assign")

    def set_episode_state(self, n, state):
        self._need_project()
        with self.lock:
            if n not in ACTIVE_EPISODES or state not in dict(EP_STATES):
                raise AppError("Neplatná hodnota.")
            self.store.change(f"Stav epizody {n}", ("episodes",), lambda: self.store.episodes.__setitem__(n, state))
            return self._changed("episode")

    def assign_suggest(self, names=None):
        self._need_project()
        names = names or sorted(self.project.files, key=str.lower)
        unknown = [n for n in names if n not in self.project.files]
        if unknown:
            raise AppError(f"Neznámé soubory: {', '.join(unknown[:3])}")
        sugg = bulk.suggest(names, self.store.assign, known_assign=self.store.assign)
        return {"items": sugg, "options": [{"value": "", "label": "Nepřiřazeno"}, {"value": "gen", "label": "Obecné (celá hra)"}]
                + [{"value": f"ep:{n}", "label": f"Epizoda {n} (sezóna {next(s['n'] for s in SEASONS if n in s['episodes'])})"}
                   for n in ACTIVE_EPISODES]}

    def assign_apply(self, items):
        self._need_project()
        with self.lock:
            for it in items:
                if it.get("name") not in self.project.files:
                    raise AppError(f"Neznámý soubor: {it.get('name')}")
            res = bulk.apply_assignments(self.store, items)
            out = self._changed("bulk-assign")
            out.update(res)
            return out

    def approval_preview(self, file, line, scope="project", same_speaker=True):
        self._need_project()
        try:
            return bulk.approval_candidates(self.project, file, int(line), scope, same_speaker)
        except ValueError as e:
            raise AppError(str(e)) from e

    def rule_preview(self, rules, files=None):
        self._need_project()
        files = [str(f) for f in (files or [])]
        unknown = [f for f in files if f not in self.project.files]
        if unknown:
            raise AppError("Neznámý soubor: " + unknown[0])
        return bulk.rule_candidates(self.project, self.store.glossary, list(rules or []), files or None)

    def glossary_occurrences(self, code, only_missing=False, limit=400):
        """Every line whose original contains the glossary term `code`, with whether the Czech form is used."""
        self._need_project()
        g = self.store.glossary.get(code)
        if g is None:
            raise AppError("Záznam ve slovníku neexistuje.")
        czech = g.get("n", "")
        rows, found, missing, untranslated = [], 0, 0, 0
        for rel in sorted(self.project.files, key=str.lower):
            for e in self.project.entries(rel):
                if e.source is None or not validator.term_in_text(e.source, code):
                    continue
                translated = self.project.is_translated(rel, e)
                used = (validator.term_used(e.target, czech) if czech and translated else None)
                if used:
                    found += 1
                elif used is False:
                    missing += 1
                else:
                    untranslated += 1
                if only_missing and used is not False:
                    continue
                rows.append({"file": rel, "line": e.line, "who": e.who, "source": e.source, "target": e.target,
                             "translated": translated, "used": used})
        return {"code": code, "czech": czech, "found": found, "missing": missing, "untranslated": untranslated,
                "items": rows[:limit], "truncated": len(rows) > limit}

    def _game_root(self):
        """Folder that contains `game/` (references look like game/script.rpy:123), found above the translation folder."""
        for parent in self.project.root.parents:
            if parent.name.lower() == "game":
                return parent.parent
        return None

    def entry_menu(self, rel, line):
        """Menu, do kterého volba (nebo řádek dialogu kolem menu) patří: otázka nebo řádky před menu, všechny volby s překladem a co po volbě
        následuje (čte se ze skriptu hry). {available: False, reason} když to není součást menu, které umíme přečíst."""
        self._need_project()
        if rel not in self.project.files:
            raise AppError("Neznámý soubor.")
        ent = next((e for e in self.project.entries(rel) if e.line == line), None)
        if ent is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        m = re.match(r"^(game/.+?):(\d+)$", ent.ref or "")
        base = self._game_root()
        if not m or base is None:
            return {"available": False, "reason": "Řádek nemá zaznamenanou pozici ve skriptu hry."}
        path = (base / m.group(1)).resolve()
        if base.resolve() not in path.parents or path.suffix.lower() not in (".rpy", ".rpym"):
            return {"available": False, "reason": "Neplatná cesta ke skriptu."}
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                return {"available": False, "reason": "Skript je příliš velký."}
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return {"available": False, "reason": f"Skript {m.group(1)} se nenašel (jsou po ruce jen soubory .rpyc?)."}
        found = menus.menu_around(lines, int(m.group(2)), ent.source if ent.unit == "string" else None)
        if found is None:
            return {"available": False, "reason": "Tento řádek není součástí menu ve skriptu hry."}
        by_ref, by_text = {}, {}
        for r, fi in self.project.files.items():
            for e in fi.parsed.entries:
                if e.unit == "string":
                    if e.source is not None:
                        by_text.setdefault(norm_ws(e.source), (r, e))
                elif e.ref:
                    by_ref[e.ref] = (r, e)

        def row(r, e):
            return {"file": r, "line": e.line, "who": e.who, "source": e.source, "target": e.target, "status": self._entry_row(r, e)}

        def say(n):
            hit = by_ref.get(f"{m.group(1)}:{n}")
            return {"n": n, "entry": row(*hit) if hit else None, "script": "" if hit else lines[n - 1].strip(),
                    "here": n == int(m.group(2)) and ent.unit != "string"}

        opts = []
        for k, o in enumerate(found["options"]):
            hit = by_text.get(norm_ws(o["text"]))
            here = {f"{m.group(1)}:{found['menu_line']}", f"{m.group(1)}:{o['n']}"}
            where = hit[1].ref if hit and hit[1].ref and hit[1].ref not in here else ""      # stejný text je v dřívějším menu: Ren'Py ho uvádí jen tam
            opts.append({"n": o["n"], "text": o["text"], "cond": o["cond"], "current": k == found["current"], "where": where,
                         "entry": row(*hit) if hit else None, "after": [say(n) for n in o["after"]],
                         "body": [] if o["after"] else textwrap.dedent(chr(10).join(o["body"])).splitlines()})
        return {"available": True, "script": f"{m.group(1)}:{found['menu_line']}", "question": [say(n) for n in found["question"]],
                "before": [say(n) for n in found["before"]], "options": opts}

    # ------------------------------------------------------------ texts the generator missed (see missed.py)
    def _script_folder(self):
        """Složka se skripty hry (.rpy mimo tl): <game>/ pro překlad v <game>/tl/<jazyk>."""
        base = self._game_root()
        game = base / "game" if base is not None else None
        return game if game is not None and game.is_dir() and missed.has_scripts(game) else None

    def missed_scan(self, level="likely"):
        """Hledá ve skriptech hry texty, které překlad nemá. Nic nemění. level: 'likely' (výchozí) nebo 'all' (přidá slabší tipy)."""
        self._need_project()
        settings = missed.load_settings(self.data_dir)
        folder = self._script_folder()
        if folder is None:
            return {"items": [], "truncated": False, "folder": "", "counts": {"likely": 0, "maybe": 0}, "settings": settings,
                    "message": "Skripty hry (.rpy) se vedle překladu nenašly. Hru nejdřív rozbal a dekompiluj."}
        strings, dialogue, places = missed.known_texts(self.project.root)
        res = missed.find_missed(folder, strings, dialogue, places, limit=2000 if level == "all" else 100000,
                                 functions=settings["functions"], ignored=settings["ignored"])
        items = res["items"]
        counts = {"likely": sum(1 for i in items if i["level"] == "likely"), "maybe": sum(1 for i in items if i["level"] != "likely")}
        if level != "all":
            items = [i for i in items if i["level"] == "likely"]
        return {"items": items, "truncated": res["truncated"], "folder": str(folder), "counts": counts, "settings": settings, "message": ""}

    def missed_functions(self):
        """Funkce hry volané stále dokola s textem (kandidáti na seznam funkcí, které ukazují text)."""
        self._need_project()
        folder = self._script_folder()
        settings = missed.load_settings(self.data_dir)
        if folder is None:
            return {"suggested": [], "settings": settings}
        strings = missed.known_strings(self.project.root)
        return {"suggested": missed.suggest_functions(folder, strings, settings["functions"], settings["ignored"]), "settings": settings}

    def _save_missed_settings(self, functions, ignored):
        try:
            return missed.save_settings(self.data_dir, functions, ignored)
        except (WriteFailed, OSError) as e:
            raise AppError(f"Nastavení hledání se nepodařilo uložit: {getattr(e, 'reason', e)}") from e

    def missed_settings(self, functions):
        """Nastaví vlastní funkce projektu, které ukazují text (třeba `notify` nebo `ui.popup`); ignorované texty zůstanou."""
        self._need_project()
        cur = missed.load_settings(self.data_dir)
        names = [str(f).strip() for f in (functions or []) if str(f).strip()]
        return self._save_missed_settings(names, cur["ignored"])

    def missed_ignore(self, texts, clear=False):
        """Vynechá tyto texty ze seznamu natrvalo (projekt si je pamatuje v missed.json); `clear` zapomene všechny."""
        self._need_project()
        cur = missed.load_settings(self.data_dir)
        if clear:
            return self._save_missed_settings(cur["functions"], [])
        new = [str(t) for t in (texts or []) if str(t).strip()]
        if not new:
            raise AppError("Nic nebylo vybráno.")
        return self._save_missed_settings(cur["functions"], list(cur["ignored"]) + new)

    def missed_add(self, items, into_files=False):
        """Zapíše vybrané texty do <složka překladu>/extra_strings.rpy (nepřeložené, takže se objeví jako řádky k překladu) a načte soubory znovu.
        `into_files` (experimentální): každý text dá do překladového souboru jeho vlastního skriptu."""
        self._need_project()
        chosen = [{"text": str(i.get("text", "")), "file": str(i.get("file", "")), "line": int(i.get("line", 0) or 0)}
                  for i in (items or []) if isinstance(i, dict) and str(i.get("text", "")).strip()]
        if not chosen:
            raise AppError("Nic nebylo vybráno.")
        with self.lock:
            self._snapshot("bulk")
            try:
                res = missed.write_strings(self.project.root, Path(self.project.root).name, chosen, self.data_dir / "backups", bool(into_files))
            except WriteFailed as e:
                raise AppError(f"Soubor s řetězci se nepodařilo zapsat: {e.reason}") from e
            self.refresh(force=True)
            n = res["added"]
            res["message"] = f"Do překladových souborů {'byl přidán' if n == 1 else 'byly přidány'} {n} {'text' if n == 1 else 'texty' if 2 <= n <= 4 else 'textů'}."
            return res

    def entry_context(self, rel, line, radius=6):
        """The original game script around the line this translation unit comes from (read-only)."""
        self._need_project()
        if rel not in self.project.files:
            raise AppError("Neznámý soubor.")
        e = next((x for x in self.project.entries(rel) if x.line == line), None)
        if e is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        m = re.match(r"^(game/.+?):(\d+)$", e.ref or "")
        if not m:
            return {"available": False, "reason": "U řádku není zaznamenaná pozice ve skriptu hry."}
        base = self._game_root()
        if base is None:
            return {"available": False, "ref": e.ref, "reason": "Složka hry (game) nad překladem nebyla nalezena."}
        path = (base / m.group(1)).resolve()
        if base.resolve() not in path.parents or path.suffix.lower() not in (".rpy", ".rpym"):
            return {"available": False, "ref": e.ref, "reason": "Neplatná cesta ke skriptu."}
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                return {"available": False, "ref": e.ref, "reason": "Skript je příliš velký."}
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return {"available": False, "ref": e.ref,
                    "reason": f"Skript {m.group(1)} nebyl nalezen (originální .rpy soubory hry nejsou po ruce, možná jen .rpyc)."}
        n = int(m.group(2))
        a, b = max(1, n - radius), min(len(lines), n + radius)
        return {"available": True, "ref": e.ref, "path": str(path),
                "lines": [{"n": i, "text": lines[i - 1], "hit": i == n} for i in range(a, b + 1)]}

    def _worst_files(self, counts_by_file, limit=10):
        totals = {r.name: r.total for r in self.project.rows()}
        out = []
        for rel, c in counts_by_file.items():
            problems = c["error"] * 3 + c["warning"]
            if not problems or rel not in totals:
                continue
            out.append({"name": rel, "errors": c["error"], "warnings": c["warning"], "lines": totals[rel],
                        "score": round(problems / max(1, totals[rel]) * 100, 1)})
        out.sort(key=lambda r: (-r["score"], -r["errors"], r["name"].lower()))
        return out[:limit]

    def approval_apply(self, selections, on=True):
        self._need_project()
        with self.lock:
            res = bulk.apply_approvals(self.project, selections, on)
            out = self._changed("approve")
            out.update(res)
            return out

    def undo(self):
        self._need_project()
        with self.lock:
            label = self.store.undo()
            if label is None:
                raise AppError("Není co vrátit.")
            self._val_cache.clear()
            out = self._changed("undo")
            out["undone"] = label
            return out

    # ------------------------------------------------------------ fixing structure errors in the .rpy files
    # ------------------------------------------------------------ translation memory / consistency / game window
    def _memory(self):
        """Index of everything already translated (looked up by the English original). Rebuilt when a file changes."""
        key = tuple(sorted((rel, id(fi.parsed)) for rel, fi in self.project.files.items()))
        if self._memory_cache and self._memory_cache[0] == key:
            return self._memory_cache[1]
        rows = ((rel, e.line, e.who, e.source, e.target) for rel, fi in self.project.files.items() for e in fi.parsed.entries
                if e.source is not None and self.project.is_translated(rel, e))
        mem = memory.Memory(rows)
        self._memory_cache = (key, mem)
        return mem

    def entry_memory(self, rel, line):
        """Suggestions for one line from the project's own translations: the same original translated before, and
        originals that differ by a few words. Reuse needs a human eye (case, gender, a different variable)."""
        self._need_project()
        ent = next((e for e in self.project.entries(rel) if e.line == line), None) if rel in self.project.files else None
        if ent is None or ent.source is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        mem, skip = self._memory(), (rel, line)
        mine = memory.tags_of(ent.source)

        def mark(item, src):
            item["vars_differ"] = memory.tags_of(src) != mine
            return item
        exact = []
        for g in mem.exact_matches(ent.source, skip):
            row = next((r for r in mem.rows if r["file"] == g["lines"][0]["file"] and r["line"] == g["lines"][0]["line"]), None)
            exact.append(mark(g, row["source"] if row else ent.source))
        similar = [mark(x, x["source"]) for x in mem.similar(ent.source, skip)]
        return {"exact": exact, "similar": similar}

    def consistency(self, loose=False, by_speaker=False):
        """Originals translated in several different ways (exactly the same original text; see Memory.groups)."""
        self._need_project()
        groups = self._memory().groups(loose=bool(loose), by_speaker=bool(by_speaker))
        return {"groups": groups, "total": len(groups), "lines": sum(g["total"] for g in groups)}

    def consistency_unify(self, key, target, lines=None, loose=False, by_speaker=False):
        """Give the chosen lines of one original the same chosen translation (one undoable step).
        `lines` = [{file, line}] picks exactly which lines change; without it every line of the group does."""
        self._need_project()
        with self.lock:
            group = next((g for g in self._memory().groups(10 ** 6, bool(loose), bool(by_speaker)) if g["key"] == str(key)), None)
            if group is None:
                raise AppError("Skupina se mezitím změnila – obnov soubory a zkus to znovu.")
            target = str(target)
            chosen = {(str(x["file"]), int(x["line"])) for x in lines} if lines else None
            edits = [(l["file"], l["line"], target) for v in group["variants"] for l in v["lines"]
                     if (chosen is None or (l["file"], l["line"]) in chosen)]
            if not edits:
                raise AppError("Není co sjednocovat.")
            self._snapshot_for_bulk(len(edits), len({e[0] for e in edits}))
            try:
                res = fixes.apply_edits(self.project, self.data_dir, edits, f"Sjednocení překladu: {group['source'][:40]}")
                self._log_text(res["details"], "unify")
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            self.store.ensure_files([r.name for r in self.project.rows()])
            out = self._changed("unify")
            out.update(changed=res["changed"], files=res["files"], backups=res["backups"])
            return out

    GUI_DEFAULTS = {"text_size": 33, "dialogue_width": 1116, "textbox_height": 278, "dialogue_ypos": 125, "dialogue_xpos": 402,
                    "name_xpos": 360, "name_ypos": 50, "name_text_size": 56, "screen_width": 1920, "screen_height": 1080}

    def game_gui(self):
        """Dialogue box metrics of the game (gui.rpy: screen size, text size and width, box height, name position), for the scene
        preview. Falls back to the values of Being a DIK when the game sources are not next to the translation."""
        out = dict(self.GUI_DEFAULTS, source="výchozí hodnoty")
        base = self._game_root() if self.project else None
        if base is None:
            return out
        try:
            text = (base / "game" / "gui.rpy").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return out
        found = {}
        for m in re.finditer(r"^\s*define\s+gui\.(\w+)\s*=\s*(\d+)\b", text, re.MULTILINE):
            found.setdefault(m.group(1), int(m.group(2)))
        m = re.search(r"gui\.init\(\s*(\d+)\s*,\s*(\d+)", text)
        if m:
            found["screen_width"], found["screen_height"] = int(m.group(1)), int(m.group(2))
        for k in self.GUI_DEFAULTS:
            if k in found:
                out[k] = found[k]
        out["source"] = "gui.rpy hry" if any(k in found for k in self.GUI_DEFAULTS) else "výchozí hodnoty"
        return out

    # ------------------------------------------------------------ fonts of the game (with the translation's overrides)
    _TL_FONT_PY = re.compile(r"^\s*gui\.(text_font|name_text_font)\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
    _TL_FONT_STYLE = re.compile(r"^translate\s+\w+\s+style\s+(\w+)\s*:\s*\n(?:[ \t]+[^\n]*\n)*?[ \t]+font\s+[\"']([^\"']+)[\"']", re.MULTILINE)

    def game_fonts(self):
        """Font files for the dialogue text and the speaker name: gui.rpy, overridden by the translation folder (`translate <lang> python:
        gui.text_font = ...`, `translate <lang> style say_dialogue: font ...`), which is how Czech diacritics are usually added."""
        out = {"text": "", "name": "", "source": ""}
        base = self._game_root()
        if base is None:
            return out
        try:
            gui = (base / "game" / "gui.rpy").read_text(encoding="utf-8", errors="replace")
        except OSError:
            gui = ""
        for m in re.finditer(r"^\s*define\s+gui\.(text_font|name_text_font)\s*=\s*[\"']([^\"']+)[\"']", gui, re.MULTILINE):
            out["text" if m.group(1) == "text_font" else "name"] = m.group(2)
        found = bool(out["text"] or out["name"])
        styles = {}
        for f in sorted(self.project.root.rglob("*.rpy")):
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "font" not in txt:
                continue
            for m in self._TL_FONT_PY.finditer(txt):
                out["text" if m.group(1) == "text_font" else "name"] = m.group(2)
                found = True
            for m in self._TL_FONT_STYLE.finditer(txt):
                styles.setdefault(m.group(1), m.group(2))
        if styles.get("say_dialogue"):
            out["text"] = styles["say_dialogue"]
        elif styles.get("default") and not out["text"]:
            out["text"] = styles["default"]
        if styles.get("say_label"):
            out["name"] = styles["say_label"]
        out["source"] = "gui.rpy a překlad" if (found or styles) else ""
        return out

    # ------------------------------------------------------------ the picture a line is shown on
    def _game_images(self):
        """Index of the game's pictures (archives + loose files + `image` statements); built once per game folder."""
        base = self._game_root()
        if base is None or not (base / "game").is_dir():
            return None
        if self._gi is None or self._gi[0] != base:
            self._gi = (base, gameimages.GameImages(base / "game").build())
        return self._gi[1]

    def scene_info(self, rel, line):
        """Which picture is behind a line (the last `scene` / `show` before its place in the game script), plus the textbox metrics
        needed to draw the line over it. Read-only; an approximation that follows the script text upwards."""
        self._need_project()
        ent = next((e for e in self.project.entries(rel) if e.line == line), None) if rel in self.project.files else None
        if ent is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        gui = self.game_gui()
        out = {"available": False, "gui": gui, "who": ent.who, "reason": ""}
        gi = self._game_images()
        if gi is None:
            out["reason"] = "Složka hry (game) nad překladem nebyla nalezena, obrázky scén proto nejdou ukázat."
            return out
        m = re.match(r"^(game/.+?):(\d+)$", ent.ref or "")
        if not m:
            out["reason"] = "U řádku není zaznamenaná pozice ve skriptu hry."
            return out
        script = (self._game_root() / m.group(1)).resolve()
        if self._game_root().resolve() not in script.parents or script.suffix.lower() not in (".rpy", ".rpym"):
            out["reason"] = "Neplatná cesta ke skriptu."
            return out
        try:
            sc = gi.scene_for(script, int(m.group(2)))
        except OSError:
            out["reason"] = f"Skript {m.group(1)} nebyl nalezen (jsou po ruce jen .rpyc?)."
            return out
        fonts = self.game_fonts()
        for kind in ("text", "name"):
            fn = Path(fonts[kind]).name.lower() if fonts[kind] else ""
            out["fonts_" + kind] = {"file": fn, "url": "/api/game/font?k=" + urllib.parse.quote(fn, safe="")} if fn in gi.fonts else None
        ch = gi.characters.get(ent.who or "")
        out["speaker"] = ch
        out.update(available=True, found=sc["found"], image=sc["image"], missing=sc["missing"], script=f"{m.group(1)}:{sc['script_line']}",
                   flat=sc.get("flat", ""), index_errors=gi.errors[:3], images=len(gi.stems))
        if sc["found"] and sc["key"]:
            out["url"] = "/api/game/image?k=" + urllib.parse.quote(sc["key"], safe="")
        elif not sc["found"]:
            out["reason"] = "Před tímto řádkem jsem v blízkosti nenašel obrázek (scene / show), který jde dohledat v archivech hry."
        return out

    def game_font(self, name):
        """(bytes, mime) of a font file of the game, by file name (only fonts the index knows)."""
        self._need_project()
        gi = self._game_images()
        if gi is None:
            raise AppError("Písma hry nejsou k dispozici.")
        try:
            return gi.font_bytes(name)
        except (gameimages.rpa.RpaError, OSError) as e:
            raise AppError(str(e)) from e

    def game_characters(self):
        """{speaker code: {name, color}} from the game's `define x = Character(...)` lines (empty without the game sources)."""
        self._need_project()
        gi = self._game_images()
        return {"characters": dict(gi.characters) if gi is not None else {}}

    def game_font_metrics(self, name):
        """Advance widths (from hmtx) of a game font, so the scene preview can place characters like Ren'Py does."""
        data, _mime = self.game_font(name)
        m = fontmetrics.advances(data)
        if m is None:
            raise AppError("Z písma nejdou přečíst šířky znaků.")
        return {"upm": m["upm"], "adv": {str(k): v for k, v in m["adv"].items()}}

    def game_image(self, key):
        """(bytes, mime) of a picture the index knows by its stem key (never an arbitrary path)."""
        self._need_project()
        gi = self._game_images()
        if gi is None:
            raise AppError("Obrázky hry nejsou k dispozici.")
        try:
            return gi.image_bytes(key)
        except (gameimages.rpa.RpaError, OSError) as e:
            raise AppError(str(e)) from e

    # ------------------------------------------------------------ snapshots of the translation folder
    def _snapshot(self, reason, force=False):
        """Zip of all .rpy files (see snapshots.py). Never raises; problems become a notice."""
        cfg = self.config.get("snapshots", {})
        if not force and not cfg.get("enabled", True):
            return None
        if reason == "bulk" and snapshots.recent(self.data_dir, 10):
            return None
        try:
            snap = snapshots.create(self.project.root, self.data_dir, reason, __version__)
            if snap:
                snapshots.prune(self.data_dir, cfg.get("keep", 20))
            return snap
        except (snapshots.SnapshotError, OSError) as e:
            self.notices.append(f"Záloha se nevytvořila: {e}")
            return None

    def _snapshot_for_bulk(self, lines, files):
        if lines >= 20 or files >= 2:
            self._snapshot("bulk")

    def maybe_auto_snapshot(self):
        """At start: a snapshot in the background when the last one is older than the interval (called by the UI server)."""
        if not self.project or not self.config.get("snapshots.enabled", True):
            return
        interval = self.config.get("snapshots.interval_hours", 12)
        if not snapshots.due(self.data_dir, interval):
            return
        threading.Thread(target=lambda: self._snapshot("auto"), daemon=True).start()

    def snapshot_list(self):
        self._need_project()
        cfg = self.config.get("snapshots", {})
        return {"items": snapshots.list_snapshots(self.data_dir), "enabled": cfg.get("enabled", True),
                "interval_hours": cfg.get("interval_hours", 12), "keep": cfg.get("keep", 20)}

    def snapshot_create(self):
        self._need_project()
        with self.lock:
            try:
                snap = snapshots.create(self.project.root, self.data_dir, "manual", __version__)
            except snapshots.SnapshotError as e:
                raise AppError(str(e)) from e
            if snap is None:
                raise AppError("Ve složce nejsou žádné soubory .rpy.")
            snapshots.prune(self.data_dir, self.config.get("snapshots.keep", 20))
            return {"ok": True, "snapshot": snap}

    def snapshot_files(self, name):
        self._need_project()
        try:
            return {"files": snapshots.compare(self.project.root, self.data_dir, name)}
        except (snapshots.SnapshotError, OSError) as e:
            raise AppError(str(e)) from e

    def snapshot_restore(self, name, files=None):
        """Put files of a snapshot back. The current state is saved first, so the restore can be undone the same way."""
        self._need_project()
        with self.lock:
            before = {rel: list(self.project.entries(rel)) for rel in self.project.files}
            try:
                res = snapshots.restore(self.project.root, self.data_dir, name, files, __version__)
            except snapshots.SnapshotError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            for rel in self.project.files:
                if rel in before:
                    ch = texthistory.diff_files(before[rel], self.project.entries(rel))
                    self._log_text([{"file": rel, "key": c["key"], "old": c["old"], "new": c["new"]} for c in ch], "restore")
            self.store.ensure_files([r.name for r in self.project.rows()])
            out = self._changed("restore")
            out.update(restored=res["restored"], safety=(res["safety"] or {}).get("name", ""))
            return out

    def snapshot_delete(self, name):
        self._need_project()
        try:
            snapshots.delete(self.data_dir, name)
        except snapshots.SnapshotError as e:
            raise AppError(str(e)) from e
        return {"ok": True}

    # ------------------------------------------------------------ Ren'Py lint of the whole game
    def lint_start(self):
        self._need_project()
        sdk = str(self.config.get("lint.sdk", "")).strip()
        if not sdk:
            raise AppError("Nastav nejdřív složku Ren'Py SDK (tam, kde je renpy.py).")
        base = self._game_root()
        if base is None:
            raise AppError("Složka hry (game) nad překladem nebyla nalezena – lint potřebuje zdrojové soubory hry.")
        try:
            self.linter.start(sdk, base)
        except lint.LintError as e:
            raise AppError(str(e)) from e
        return {"ok": True}

    def lint_status(self):
        self._need_project()
        st = self.linter.status()
        base = self._game_root()
        for it in st.get("issues", []):
            it["rel"] = ""
            if base is not None:
                try:
                    p = (base / it["file"]).resolve()
                    it["rel"] = p.relative_to(self.project.root.resolve()).as_posix()
                    it["rel"] = next((r for r in self.project.files if r.replace("\\", "/") == it["rel"]), "")
                except (ValueError, OSError):
                    it["rel"] = ""
        return st

    FIX_KINDS = ("speaker", "spaces", "typo")
    FIX_LABELS = {"speaker": "mluvčí / atributy", "spaces": "dvojité mezery", "typo": "překlepy"}

    def fix_preview(self, items=None, file="", kinds=None):
        """Every safe fix that could be applied. Nothing is written.

        kinds: "speaker" (copy speaker / attributes / trailing code from the original), "spaces" (collapse double spaces),
        "typo" (apply the spelling hints). Variables and tags are never touched – their order may differ legitimately.
        Each item has `default` (the checkbox state a UI should start with; doubtful ones are off) and `skip` (reason when
        it cannot be applied)."""
        self._need_project()
        kinds = [k for k in (kinds or ["speaker"]) if k in self.FIX_KINDS]
        wanted = {(str(i["file"]), int(i["line"])) for i in items} if items else None
        with self.lock:
            out = []
            if "speaker" in kinds:
                for p in fixes.plan(self.project, items, file):
                    out.append({"file": p["file"], "line": p["line"], "kind": "speaker", "before": p["before"],
                                "after": p["after"], "skip": p["skip"], "default": not p["skip"], "code": True,
                                "note": "mluvčí / atributy podle originálu"})
            for p in textedit.plan_text_fixes(self.project, self._spell(), kinds, wanted, file):
                out.append(dict(p, skip="", code=False))
            out.sort(key=lambda r: (r["file"].lower(), r["line"], r["kind"]))
            counts = {k: sum(1 for r in out if r["kind"] == k) for k in kinds}
            return {"items": out, "total": len(out), "fixable": sum(1 for r in out if not r["skip"]), "counts": counts}

    def fix_apply(self, items=None, file="", kinds=None, selections=None):
        """Apply fixes. `selections` = [{file, line, kind}] picks exactly what the user ticked in the preview;
        without it every applicable fix of `kinds` (default: speaker) is applied (older callers)."""
        self._need_project()
        with self.lock:
            if selections is not None:
                chosen = {(str(x["file"]), int(x["line"]), str(x["kind"])) for x in selections}
                kinds = sorted({k for _f, _l, k in chosen})
                items = [{"file": f, "line": l} for f, l, _k in chosen] or None
                if not chosen:
                    raise AppError("Není vybrané nic k opravě.")
            else:
                chosen = None
            plan = self.fix_preview(items, file, kinds)["items"]
            todo = [p for p in plan if not p["skip"] and (chosen is None or (p["file"], p["line"], p["kind"]) in chosen)]
            skipped = [(p["file"], p["line"], p["skip"]) for p in plan if p["skip"]]
            if not todo:
                raise AppError("Není co opravovat.")
            fixed, backups = 0, []
            self._snapshot_for_bulk(len(todo), len({p["file"] for p in todo}))
            try:
                speaker = {(p["file"], p["line"]) for p in todo if p["kind"] == "speaker"}
                if speaker:
                    res = fixes.apply(self.project, self.data_dir, [p for p in fixes.plan(self.project, None, "")
                                                                    if (p["file"], p["line"]) in speaker and not p["skip"]])
                    fixed += res["fixed"]
                    backups += res["backups"]
                    skipped += res["skipped"]
                    self.project.refresh(force=True)
                    self._val_cache.clear()
                texts = {(p["file"], p["line"], p["kind"]) for p in todo if p["kind"] != "speaker"}
                if texts:
                    by_line = {}
                    for f, l, k in texts:
                        by_line.setdefault((f, l), set()).add(k)
                    pick = {}
                    for (f, l), ks in by_line.items():                       # one line can carry several kinds: chain them
                        e = next((x for x in self.project.entries(f) if x.line == l), None)
                        if e is not None and e.source is not None:
                            pick[(f, l)] = textedit.chain_fixes(self._spell(), e.source, e.target, ks)
                    kinds_txt = ", ".join(self.FIX_LABELS[k] for k in sorted({k for _f, _l, k in texts}))
                    res = fixes.apply_edits(self.project, self.data_dir, [(f, l, t) for (f, l), t in pick.items()],
                                            f"Opravy textu ({kinds_txt})")
                    self._log_text(res["details"], "fix")
                    fixed += res["changed"]
                    backups += res["backups"]
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            self.store.ensure_files([r.name for r in self.project.rows()])
            out = self._changed("fix")
            out.update(fixed=fixed, skipped=skipped, backups=backups)
            return out

    # ------------------------------------------------------------ find and replace in translations
    def _replace_plan(self, find, replace, mode, case, files, protect, limit):
        try:
            rep = textedit.make_replacer(str(find), str(replace), mode, bool(case))
        except ValueError as e:
            raise AppError(str(e)) from e
        files = [str(f) for f in (files or [])]
        unknown = [f for f in files if f not in self.project.files]
        if unknown:
            raise AppError("Neznámý soubor: " + unknown[0])
        items, matches, truncated = [], 0, False
        for rel in sorted(files or self.project.files, key=str.lower):
            for e in self.project.entries(rel):
                if not e.target or (e.pending and e.category and not self.project.is_translated(rel, e)):
                    continue
                try:
                    new, n = rep(e.target, bool(protect))
                except ValueError as err:
                    raise AppError(str(err)) from err
                if not n or new == e.target:
                    continue
                skip = ""
                try:
                    fixes.check_literal(new)
                except fixes.FixError as err:
                    skip = str(err)
                if len(items) >= limit:
                    truncated = True
                    break
                matches += n
                items.append({"file": rel, "line": e.line, "who": e.who, "source": e.source, "before": e.target,
                              "after": new, "count": n, "skip": skip})
            if truncated:
                break
        return items, matches, truncated

    def replace_preview(self, find, replace, mode="plain", case=False, files=None, protect=True, limit=2000):
        """Lines of already translated text that the search would change, with the new text. Nothing is written."""
        self._need_project()
        with self.lock:
            items, matches, truncated = self._replace_plan(find, replace, mode, case, files, protect, max(1, min(int(limit), 20000)))
            return {"items": items, "total": len(items), "matches": matches, "truncated": truncated,
                    "applicable": sum(1 for i in items if not i["skip"])}

    def replace_apply(self, selections, find, replace, mode="plain", case=False, files=None, protect=True):
        """Write the replacement into the ticked lines (one undoable step, backup of every touched file)."""
        self._need_project()
        with self.lock:
            chosen = {(str(x["file"]), int(x["line"])) for x in (selections or [])}
            if not chosen:
                raise AppError("Není vybraný žádný řádek.")
            items, _m, _t = self._replace_plan(find, replace, mode, case, files, protect, 20000)
            edits = [(i["file"], i["line"], i["after"]) for i in items if not i["skip"] and (i["file"], i["line"]) in chosen]
            if not edits:
                raise AppError("Vybrané řádky se mezitím změnily – zobraz náhled znovu.")
            label = f"Nahrazení „{str(find)[:30]}“ → „{str(replace)[:30]}“"
            self._snapshot_for_bulk(len(edits), len({e[0] for e in edits}))
            try:
                res = fixes.apply_edits(self.project, self.data_dir, edits, label)
                self._log_text(res["details"], "replace")
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            self.store.ensure_files([r.name for r in self.project.rows()])
            out = self._changed("replace")
            out.update(changed=res["changed"], files=res["files"], backups=res["backups"])
            return out

    def _mt_one(self, rel, ents, idx, cfg, terms):
        """Machine translation suggestion for ents[idx] (with the two lines before it as context) + what the validator says."""
        ent = ents[idx]
        context = [e.source for e in ents[max(0, idx - 2):idx] if e.source]
        local = {en: cz for en, cz in terms.items() if validator.term_in_text(ent.source, en)}
        try:
            res = mt.translate(cfg, ent.source, local, context, http=self._mt_http)
        except mt.MTError as e:
            raise AppError(str(e)) from e
        probe = replace(ent, target=res["text"], category="")
        issues = [i.to_dict() for i in validator.check_entry(probe, self._length_cfg(), self._terms(), None,
                                                             self.config.get("validation.textbox", {})) if i.severity != "info"]
        return {"suggestion": res["text"], "warnings": res["warnings"], "issues": issues, "provider": res["provider"]}

    def mt_suggest(self, rel, line):
        """A machine translation SUGGESTION for one line (only after consent and a key in the settings; never saved)."""
        self._need_project()
        ents = self.project.entries(rel) if rel in self.project.files else []
        idx = next((i for i, e in enumerate(ents) if e.line == line and e.source is not None), None)
        if idx is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        return self._mt_one(rel, ents, idx, dict(self.config.get("mt", {})), self._terms())

    MT_BATCH = 10            # lines per request: the UI loops, so it can show progress and stop

    def mt_targets(self, file="", lines=None, only_todo=True):
        """Which lines a batch would translate: the given lines, or every line of a file (all files when empty).
        Only not yet translated lines by default. Returns the count and the characters that would be sent to the service."""
        self._need_project()
        out, chars = [], 0
        if lines:
            want = {(str(x["file"]), int(x["line"])) for x in lines}
            files = sorted({f for f, _l in want})
        else:
            want = None
            files = [file] if file else list(self.project.files)
        for rel in files:
            if rel not in self.project.files:
                raise AppError("Neznámý soubor.")
            for e in self.project.entries(rel):
                if e.source is None or not e.source.strip() or (want is not None and (rel, e.line) not in want):
                    continue
                if only_todo and self._entry_row(rel, e) != "todo":
                    continue
                out.append({"file": rel, "line": e.line})
                chars += len(e.source)
        return {"items": out, "total": len(out), "chars": chars}

    def mt_batch(self, items):
        """Suggestions for up to MT_BATCH lines. Nothing is written. A failed line carries its own error; a rejected key,
        missing consent or a broken connection stops the batch (the same message for every line would be useless)."""
        self._need_project()
        items = list(items or [])[: self.MT_BATCH]
        cfg, terms, results = dict(self.config.get("mt", {})), self._terms(), []
        for it in items:
            rel, line = str(it["file"]), int(it["line"])
            ents = self.project.entries(rel) if rel in self.project.files else []
            idx = next((i for i, e in enumerate(ents) if e.line == line and e.source is not None), None)
            if idx is None:
                results.append({"file": rel, "line": line, "error": "Řádek už v souboru není."})
                continue
            try:
                r = self._mt_one(rel, ents, idx, cfg, terms)
            except AppError as e:
                results.append({"file": rel, "line": line, "error": str(e)})
                if not str(e).startswith("Řádek nemá"):
                    return {"results": results, "stopped": str(e)}
                continue
            results.append({"file": rel, "line": line, "key": ents[idx].key, "who": ents[idx].who, "source": ents[idx].source,
                            "current": ents[idx].target, **r})
        return {"results": results, "stopped": ""}

    def mt_apply(self, selections):
        """Write the ticked suggestions as one undoable step. Approved lines are never overwritten."""
        self._need_project()
        with self.lock:
            edits, skipped = [], 0
            for x in selections or []:
                rel, line, text = str(x["file"]), int(x["line"]), str(x.get("text", ""))
                ent = next((e for e in self.project.entries(rel) if e.line == line), None) if rel in self.project.files else None
                if ent is None or not text.strip() or self._entry_row(rel, ent) == "approved":
                    skipped += 1
                    continue
                edits.append((rel, line, text))
            if not edits:
                raise AppError("Není co zapsat (řádky se změnily nebo jsou schválené).")
            self._snapshot_for_bulk(len(edits), len({e[0] for e in edits}))
            try:
                res = fixes.apply_edits(self.project, self.data_dir, edits, f"Strojový překlad ({len(edits)} ř.)")
                self._log_text(res["details"], "mt")
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            self.store.ensure_files([r.name for r in self.project.rows()])
            out = self._changed("mt")
            out.update(changed=res["changed"], files=res["files"], skipped=skipped, backups=res["backups"])
            return out

    def _overflows(self, e):
        """True when the translation needs more room than the game's dialogue box has (and the original did not)."""
        if not e.source or not e.target or e.unit == "string":
            return False
        return any(i.code == "textbox-overflow" for i in validator.check_textbox(e.source, e.target, self.config.get("validation.textbox", {})))

    def entry_next(self, rel, line, kind):
        """The next line (after `line`, wrapping round the file) that is untranslated (todo), still to be checked (review), marked
        for a fix (fix) or does not fit the dialogue box (over). {line: 0} when there is none."""
        self._need_project()
        if rel not in self.project.files:
            raise AppError("Neznámý soubor.")
        if kind not in ("todo", "review", "fix", "over"):
            raise AppError("Neznámý druh řádku.")
        ents = self.project.entries(rel)

        def match(e):
            st = self._entry_row(rel, e)
            if kind == "todo":
                return st == "todo"
            if st == "todo":
                return False
            if kind == "over":
                return self._overflows(e)
            pf = self.project.proof_state(rel, e)
            return pf not in ("ok", "fix") if kind == "review" else pf == "fix"
        idx = next((i for i, e in enumerate(ents) if e.line == line), -1)
        for i in list(range(idx + 1, len(ents))) + list(range(0, idx + 1)):
            if match(ents[i]):
                return {"line": ents[i].line, "wrapped": i <= idx}
        return {"line": 0, "wrapped": False}

    def scene_list(self, rel, line=0):
        """The scenes of a file (runs of lines that follow the same `scene` statement of the game script) with their progress, and
        the one that holds `line`. Needs the game sources; without them {available: False}."""
        self._need_project()
        if rel not in self.project.files:
            raise AppError("Neznámý soubor.")
        gi, base = self._game_images(), self._game_root()
        if gi is None or base is None:
            return {"available": False, "items": [], "cur": -1, "reason": "Složka hry (game) nad překladem nebyla nalezena."}
        root = base.resolve()
        items, key, cur, starts = [], None, -1, {}
        for e in self.project.entries(rel):
            m = re.match(r"^(game/.+?):(\d+)$", e.ref or "")
            name = None
            if m:
                script = (base / m.group(1)).resolve()
                if root in script.parents and script.suffix.lower() in (".rpy", ".rpym"):
                    if script not in starts:
                        st = gi.scene_starts(script)
                        starts[script] = (st, [s[0] for s in st])
                    st, nums = starts[script]
                    pos = bisect.bisect_right(nums, int(m.group(2))) - 1
                    k = (m.group(1), st[pos][0] if pos >= 0 else 0)
                    name = st[pos][1] if pos >= 0 else ""
                else:
                    k = key
            else:
                k = key
            if not items or k != key:
                items.append({"line": e.line, "count": 0, "done": 0, "proofed": 0, "name": name or "", "script": f"{k[0]}:{k[1]}" if k else ""})
                key = k
            it = items[-1]
            it["count"] += 1
            if self._entry_row(rel, e) != "todo":
                it["done"] += 1
                if self.project.proof_state(rel, e) == "ok":
                    it["proofed"] += 1
            if e.line <= line:
                cur = len(items) - 1
        return {"available": True, "items": items, "cur": cur}

    def entry_scene(self, rel, line, radius=6):
        """The lines around one line (original and translation), i.e. the scene it belongs to."""
        self._need_project()
        if rel not in self.project.files:
            raise AppError("Neznámý soubor.")
        ents = self.project.entries(rel)
        idx = next((i for i, e in enumerate(ents) if e.line == line), None)
        if idx is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        r = max(1, min(int(radius), 30))
        a, b = max(0, idx - r), min(len(ents), idx + r + 1)
        return {"file": rel, "items": [{"line": e.line, "who": e.who, "source": e.source, "target": e.target,
                                       "status": self._entry_row(rel, e), "current": e.line == line, "unit": e.unit,
                                       "over": self._overflows(e),
                                       "proof": self.project.proof_state(rel, e) if self.project.is_translated(rel, e) else ""}
                                      for e in ents[a:b]]}

    def entry_check(self, rel, line, text):
        """Validator result for a text the translator is typing (nothing is written)."""
        self._need_project()
        with self.lock:
            ent = next((e for e in self.project.entries(rel) if e.line == line), None) if rel in self.project.files else None
            if ent is None:
                raise AppError("Řádek už v souboru není – obnov soubory.")
            try:
                fixes.check_literal(text)
                literal = ""
            except fixes.FixError as e:
                literal = str(e)
            probe = replace(ent, target=text, category="")
            issues = [i.to_dict() for i in validator.check_entry(
                probe, self._length_cfg(), self._terms(), self._spell(), self.config.get("validation.textbox", {}))
                if i.severity != "info" or self.config.get("validation.show_info", False)]
            return {"literal_error": literal, "issues": issues}

    def entry_save(self, rel, line, text):
        """Write a new translation of one line into the .rpy file (backup, atomic, verified, undoable)."""
        self._need_project()
        with self.lock:
            try:
                res = fixes.edit_translation(self.project, self.data_dir, rel, int(line), str(text))
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            self.store.ensure_files([r.name for r in self.project.rows()])
            self._log_text(res.get("details", []), "edit")
            out = self._changed("edit")
            out.update({k: v for k, v in res.items() if k != "details"})
            return out

    # ------------------------------------------------------------ history of the text of a line
    def _log_text(self, details, via):
        """Record changed texts (from apply_edits) in the line history. Never lets a logging problem break an edit."""
        try:
            self.texthist.record([{"file": d["file"], "key": d["key"], "old": d["old"], "new": d["new"]} for d in details], via)
        except Exception:                                  # noqa: BLE001 - history is a convenience, not part of the edit
            pass

    def _log_external(self, prev):
        """Changes noticed at a refresh that this app did not make itself (VS Code, another program)."""
        for rel, old in (prev or {}).items():
            fi = self.project.files.get(rel)
            if fi is None:
                continue
            ch = texthistory.diff_files(old.parsed.entries, fi.parsed.entries)
            try:
                self.texthist.record([{"file": rel, "key": c["key"], "old": c["old"], "new": c["new"]} for c in ch], "external")
            except Exception:                              # noqa: BLE001
                pass

    def entry_history(self, rel, line):
        """All texts this line has had, newest first (see texthistory)."""
        self._need_project()
        ent = next((e for e in self.project.entries(rel) if e.line == line), None) if rel in self.project.files else None
        if ent is None:
            raise AppError("Řádek už v souboru není – obnov soubory.")
        versions = self.texthist.versions(rel, ent.key, ent.target)
        return {"versions": versions, "count": max(0, len(versions) - 1)}

    def fix_last(self):
        self._need_project()
        return {"last": fixes.last(self.data_dir)}

    def fix_undo(self):
        """Restore the files changed by the last Opravit from their backups."""
        self._need_project()
        with self.lock:
            before = {rel: list(self.project.entries(rel)) for rel in self.project.files}
            try:
                res = fixes.undo(self.project, self.data_dir)
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            for rel in res.get("restored", []):
                if rel in before and rel in self.project.files:
                    ch = texthistory.diff_files(before[rel], self.project.entries(rel))
                    self._log_text([{"file": rel, "key": c["key"], "old": c["old"], "new": c["new"]} for c in ch], "undo")
            out = self._changed("fix-undo")
            out.update(res)
            return out

    def open_link(self, link_id, opener=None):
        """Open one of the fixed project links in the default browser."""
        url = LINKS.get(link_id)
        if url is None:
            raise AppError("Neznámý odkaz.")
        (opener or webbrowser.open)(url)
        return {"ok": True, "url": url}

    # ------------------------------------------------------------ editor
    def open_editor(self, rel, line):
        self._need_project()
        try:
            path = self.project.path_of(rel)
        except ValueError as e:
            return {"ok": False, "message": str(e)}
        if rel not in self.project.files:
            return {"ok": False, "message": "Neznámý soubor."}
        return editor.open_in_editor(path, line, self.config.get("editor", {}), root=self.project.root)

    # ------------------------------------------------------------ settings / prefs
    def settings(self):
        d = self.config.public()
        d["ui"] = {}
        d["game_gui"] = self.game_gui()
        return d

    def update_settings(self, patch):
        """Validate and store a settings patch. Only known keys are accepted."""
        clean = {}
        ed = patch.get("editor")
        if isinstance(ed, dict):
            pref = str(ed.get("preferred", "auto"))
            if pref not in ("auto", "vscode", "notepadpp", "custom", "system"):
                raise AppError("Neplatná volba editoru.")
            clean["editor"] = {"preferred": pref, "custom": str(ed.get("custom", ""))[:500]}
        va = patch.get("validation")
        if isinstance(va, dict):
            out = {}
            if "enabled" in va:
                out["enabled"] = bool(va["enabled"])
            if "show_info" in va:
                out["show_info"] = bool(va["show_info"])
            if "spelling" in va:
                out["spelling"] = bool(va["spelling"])
            tbx = va.get("textbox")
            if isinstance(tbx, dict):
                to = {}
                if "enabled" in tbx:
                    to["enabled"] = bool(tbx["enabled"])
                for k, lo_, hi in (("chars_per_line", 20, 400), ("max_lines", 1, 30)):
                    if k in tbx:
                        try:
                            val = int(float(tbx[k]))
                        except (TypeError, ValueError):
                            raise AppError(f"Neplatná hodnota: {k}") from None
                        if not lo_ <= val <= hi:
                            raise AppError(f"{k} musí být v rozmezí {lo_}–{hi}.")
                        to[k] = val
                out["textbox"] = to
            ln = va.get("length")
            if isinstance(ln, dict):
                lo = {}
                for k, lo_, hi in (("min_source_chars", 0, 500), ("max_ratio", 1.0, 20.0), ("min_ratio", 0.0, 1.0),
                                   ("min_extra_chars", 0, 1000), ("min_missing_chars", 0, 1000)):
                    if k in ln:
                        try:
                            val = float(ln[k])
                        except (TypeError, ValueError):
                            raise AppError(f"Neplatná hodnota: {k}") from None
                        if not lo_ <= val <= hi:
                            raise AppError(f"{k} musí být v rozmezí {lo_}–{hi}.")
                        lo[k] = int(val) if k in ("min_source_chars", "min_extra_chars", "min_missing_chars") else val
                if "enabled" in ln:
                    lo["enabled"] = bool(ln["enabled"])
                out["length"] = lo
            clean["validation"] = out
        sn = patch.get("snapshots")
        if isinstance(sn, dict):
            o = {}
            if "enabled" in sn:
                o["enabled"] = bool(sn["enabled"])
            for k, lo, hi in (("interval_hours", 1, 168), ("keep", 3, 100)):
                if k in sn:
                    try:
                        val = int(float(sn[k]))
                    except (TypeError, ValueError):
                        raise AppError(f"Neplatná hodnota: {k}") from None
                    if not lo <= val <= hi:
                        raise AppError(f"{k} musí být v rozmezí {lo}–{hi}.")
                    o[k] = val
            clean["snapshots"] = o
        m = patch.get("mt")
        if isinstance(m, dict):
            cur = dict(self.config.get("mt", {}))
            o = {}
            if "provider" in m:
                if m["provider"] not in ("",) + mt.PROVIDERS:
                    raise AppError("Neznámý poskytovatel strojového překladu.")
                o["provider"] = m["provider"]
            for k, n in (("base_url", 300), ("model", 100), ("source_lang", 10), ("target_lang", 10)):
                if k in m:
                    o[k] = str(m[k]).strip()[:n]
            if o.get("base_url"):
                try:
                    mt._check_url(o["base_url"])
                except mt.MTError as e:
                    raise AppError(str(e)) from e
            if "consent" in m:
                o["consent"] = bool(m["consent"])
            if m.get("clear_key"):
                o["api_key"] = ""
            elif str(m.get("api_key", "")).strip():
                o["api_key"] = str(m["api_key"]).strip()[:300]          # an empty field keeps the stored key
            clean["mt"] = {**cur, **o}
        li = patch.get("lint")
        if isinstance(li, dict) and "sdk" in li:
            clean["lint"] = {"sdk": str(li["sdk"]).strip().strip('"')[:500]}
        gl = patch.get("goals")
        if isinstance(gl, dict):
            g = {}
            for k in ("translate_per_week", "proofread_per_week"):
                if k in gl:
                    try:
                        val = int(float(gl[k] or 0))
                    except (TypeError, ValueError):
                        raise AppError(f"Neplatný cíl: {k}") from None
                    if not 0 <= val <= 100000:
                        raise AppError("Cíl musí být v rozmezí 0–100 000 řádků týdně (0 = automaticky).")
                    g[k] = val
            clean["goals"] = g
        web = patch.get("web")
        if isinstance(web, dict):
            w = {}
            for k in ("repo", "path", "title"):
                if k in web:
                    w[k] = str(web[k]).strip()[:300]
            if "path" in w:
                try:
                    w["path"] = pub.clean_target(w["path"])
                except pub.PublishError as e:
                    raise AppError(str(e)) from e
            clean["web"] = w
        if "skip_files" in patch:
            clean["skip_files"] = [str(x).strip() for x in patch["skip_files"] if str(x).strip()][:200]
        with self.lock:
            try:
                self.config.update(clean)
            except WriteFailed as e:
                raise AppError(f"Nastavení nelze uložit: {e.reason}") from e
            self._val_cache.clear()
            if "skip_files" in clean and self.project:
                self.project.skip = {s.lower() for s in clean["skip_files"]}
        return self.settings()

    def ui_prefs(self):
        return self.config.get("ui", {})

    def set_ui_prefs(self, prefs):
        if not isinstance(prefs, dict) or len(json.dumps(prefs)) > UI_PREF_MAX:
            raise AppError("Neplatné předvolby.")
        with self.lock:
            self.config.set("ui", prefs)
            try:
                self.config.save()
            except WriteFailed:
                pass
        return {"ok": True}

    # ------------------------------------------------------------ export / publish
    def export_preview(self):
        """Generate the public data and its checks; writes the local progress.json only."""
        self._need_project()
        with self.lock:
            data = self.build_export()
            problems = export.validate_progress(data)
            return {"data": data, "problems": problems, "path": str(self.data_dir / "progress.json")}

    def publish_plan(self):
        self._need_project()
        with self.lock:
            data = self.build_export()
            problems = export.validate_progress(data)
            if problems:
                raise AppError("Export neprošel kontrolou: " + "; ".join(problems))
            try:
                info = pub.plan(self.config.get("web", {}), data, export.render(data))
            except pub.PublishError as e:
                raise AppError(str(e)) from e
            info["summary"] = {"episodes": len(data["episodes"]), "files": data["files"]["total"],
                               "estimate": data["estimate"]["status"]}
            return info

    def publish_confirm(self, token, branch):
        self._need_project()
        with self.lock:
            data = self.build_export()
            problems = export.validate_progress(data)
            if problems:
                raise AppError("Export neprošel kontrolou: " + "; ".join(problems))
            try:
                return pub.publish(self.config.get("web", {}), data, export.render(data), token, branch)
            except pub.PublishError as e:
                raise AppError(str(e)) from e
