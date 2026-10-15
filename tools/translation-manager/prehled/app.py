"""Application state and operations (no HTTP, no UI) — everything the server exposes lives here."""
import json
import os
import re
import shutil
import threading
import webbrowser
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from . import bulk, editor, export, fixes, history as hist, publish as pub, rpy, spelling, validator
from .config import Config, migrate_web_json
from .lock import ProjectLock, ProjectLocked
from .project import (DATA_DIR_NAME, STATUS_LABELS, STATUS_ORDER, Project, ProjectUnavailable,
                      check_project_dir, file_status, totals_of)
from .seasons import ACTIVE_EPISODES, SEASONS
from .store import EP_STATES, GLOSSARY_TYPES, Store, parse_value, text_hash, valid_assign
from .util import WriteFailed, norm_ws, write_csv

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

    def _issues(self, rel):
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
        dups = self._duplicate_ids() if self.config.get("validation.enabled", True) else []
        counts["error"] += len(dups)
        for rel, _l, _w in dups:
            per_file.setdefault(rel, {"error": 0, "warning": 0, "info": 0})["error"] += 1
        return counts, per_file

    def validation_list(self, severity="", category="", file="", q="", offset=0, limit=200):
        self._need_project()
        out = []
        show_info = self.config.get("validation.show_info", False)
        for rel, items in self._all_issues().items():
            if file and rel != file:
                continue
            for line, iss, e in items:
                if severity and iss.severity != severity:
                    continue
                if not severity and iss.severity == "info" and not show_info:
                    continue
                if category and iss.category != category:
                    continue
                if q and q.lower() not in (iss.message + " " + rel + " " + (e.target if e else "")).lower():
                    continue
                out.append({"file": rel, "line": line, "severity": iss.severity, "code": iss.code,
                            "category": iss.category, "message": iss.message,
                            "source": e.source if e else "", "target": e.target if e else "",
                            "who": e.who if e else "", "extra": iss.extra,
                            "src_who": e.src_who if e else ""})
        if (not severity or severity == "error") and not category and not q:
            for rel, line, first in self._duplicate_ids():
                if not file or rel == file:
                    out.append({"file": rel, "line": line, "severity": "error", "code": "duplicate-id",
                                "category": "structure", "message": f"Blok translate se stejným identifikátorem už existuje ({first}); Ren'Py ho odmítne.",
                                "source": "", "target": "", "who": "", "extra": {}})
        order = {"error": 0, "warning": 1, "info": 2}
        out.sort(key=lambda r: (order[r["severity"]], r["file"].lower(), r["line"]))
        return {"total": len(out), "items": out[offset:offset + limit]}

    # ------------------------------------------------------------ overview / files
    def estimate(self):
        rows = self.project.rows()
        t_done, total, *_ = totals_of(rows)
        est = hist.estimate(self.history.points(), t_done, total)
        for k in ("eta", "eta_early", "eta_late"):
            est[k] = est[k].isoformat() if est[k] else None
        return est

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
            "validation": vcounts, "worst_files": self._worst_files(per_file),
            "estimate": self.estimate(),
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
                unit=""):
        """Paged, filtered list of translation units (server side, so 45k lines stay fast)."""
        self._need_project()
        limit = max(1, min(int(limit), PAGE_LIMIT))
        ql = q.strip().lower()
        files = [file] if file else sorted(self.project.files, key=str.lower)
        if file and file not in self.project.files:
            raise AppError("Neznámý soubor.")
        iss_by = {}
        if self.config.get("validation.enabled", True):
            for rel in files:
                for line, iss, _e in self._issues(rel):
                    iss_by.setdefault((rel, line), []).append(iss)
        rows = []
        for rel in files:
            for e in self.project.entries(rel):
                st = self._entry_row(rel, e)
                if status == "todo" and st != "todo":
                    continue
                if status == "approved" and st != "approved":
                    continue
                if status == "translated" and st != "translated":
                    continue
                pf = self.project.proof_state(rel, e) if st != "todo" else ""
                if status == "review" and (st == "todo" or pf in ("ok", "fix")):
                    continue
                if status == "proofed" and pf != "ok":
                    continue
                if status == "fix" and pf != "fix":
                    continue
                if status == "stale" and pf != "stale":
                    continue
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
                if ql and ql not in (e.target or "").lower() and ql not in (e.source or "").lower() \
                        and ql not in e.who.lower() and ql not in rel.lower() \
                        and ql not in self.store.glossary.get(self.speaker_code(e.who), {}).get("n", "").lower():
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
        return {"total": total, "offset": offset, "items": [{
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
        iss = [i for ln, i, _e in self._issues(rel) if ln == line] if self.config.get("validation.enabled", True) else []

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
                "issues": [i.to_dict() for i in iss],
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
        """Mark every translated, not yet proofread / flagged line of a file up to `line` (inclusive)."""
        self._need_project()
        with self.lock:
            if rel not in self.project.files:
                raise AppError("Neznámý soubor.")
            items = [{"file": rel, "key": list(e.key)} for e in self.project.entries(rel)
                     if e.line <= line and self.project.is_translated(rel, e)
                     and self.project.proof_state(rel, e) in ("", "stale")]
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
    def fix_preview(self, items=None, file=""):
        self._need_project()
        with self.lock:
            planned = fixes.plan(self.project, items, file)
            return {"items": planned, "total": len(planned), "fixable": sum(1 for p in planned if not p["skip"])}

    def fix_apply(self, items=None, file=""):
        """Copy speaker / attributes / trailing code from the original into the translation lines."""
        self._need_project()
        with self.lock:
            planned = fixes.plan(self.project, items, file)
            if not planned:
                raise AppError("Není co opravovat.")
            try:
                res = fixes.apply(self.project, self.data_dir, planned)
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
            self.store.ensure_files([r.name for r in self.project.rows()])
            out = self._changed("fix")
            out.update(res)
            return out

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
            out = self._changed("edit")
            out.update(res)
            return out

    def fix_last(self):
        self._need_project()
        return {"last": fixes.last(self.data_dir)}

    def fix_undo(self):
        """Restore the files changed by the last Opravit from their backups."""
        self._need_project()
        with self.lock:
            try:
                res = fixes.undo(self.project, self.data_dir)
            except fixes.FixError as e:
                raise AppError(str(e)) from e
            finally:
                self.project.refresh(force=True)
                self._val_cache.clear()
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
