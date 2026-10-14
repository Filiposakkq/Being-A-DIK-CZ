"""Application state and operations (no HTTP, no UI) — everything the server exposes lives here."""
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from . import bulk, editor, export, history as hist, publish as pub, rpy, validator
from .config import Config, migrate_web_json
from .project import (DATA_DIR_NAME, STATUS_LABELS, STATUS_ORDER, Project, ProjectUnavailable,
                      check_project_dir, file_status, totals_of)
from .seasons import ACTIVE_EPISODES, SEASONS
from .store import EP_STATES, Store, parse_value, valid_assign
from .util import WriteFailed, norm_ws, write_csv

# Files the legacy tool left next to the script; moved into _progress_data on first open.
LEGACY_FILES = ("web.json", "progress.csv", "historie.csv", "korekce.csv", "epizody.csv",
                "prirazeni.csv", "schvaleno.csv", "progress.json")
PAGE_LIMIT = 500
UI_PREF_MAX = 20000


class AppError(Exception):
    """An operation failed for a reason the user should read."""


class App:
    def __init__(self, config=None):
        self.config = config or Config().load()
        self.lock = threading.RLock()
        self.project = None
        self.store = None
        self.history = None
        self.data_dir = None
        self.notices = []          # one-off messages for the UI (migration, load problems...)
        self._val_cache = {}       # rel -> (digest, cfg signature, [(line, Issue, entry)])
        self.last_save_error = ""

    # ------------------------------------------------------------ project lifecycle
    def open_project(self, path):
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

    def _issues(self, rel):
        fi = self.project.files[rel]
        sig = json.dumps(self._length_cfg(), sort_keys=True)
        hit = self._val_cache.get(rel)
        if hit and hit[0] is fi.parsed and hit[1] == sig:
            return hit[2]
        res = validator.check_parsed(fi.parsed, self._length_cfg())
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
                            "who": e.who if e else "", "extra": iss.extra})
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
        stats = export.stats_for(rows, self.store)
        vcounts, _ = self.validation_summary()
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
                       "proofread": c_done, "proofread_percent": round(cpct, 1), "approved": approved},
            "file_counts": counts,
            "seasons": stats["seasons"], "episodes": stats["episodes"],
            "general": stats["general"], "unassigned": stats["unassigned"],
            "validation": vcounts,
            "estimate": self.estimate(),
            "recent": recent[-8:][::-1],
            "undo": [s["label"] for s in self.store.undo_stack][-5:][::-1],
            "unsaved": sorted(self.store.unsaved),
            "last_save_error": self.last_save_error,
            "last_refresh": self.project.last_report.to_dict() if self.project.last_report else None,
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
            out.append({"name": r.name, "assign": self.store.assign.get(r.name, ""), "total": r.total,
                        "done": r.done, "auto": r.auto, "todo": r.todo, "corr": r.corr, "approved": appr,
                        "status": st, "order": STATUS_ORDER[st], "errors": v["error"], "warnings": v["warning"]})
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

    def entries(self, file="", status="all", kind="", q="", issues="", sort="line", offset=0, limit=200, around=0):
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
                kinds = rpy.KIND_CODE.get(e.category, "")
                if kind and kinds != kind:
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
                        and ql not in e.who.lower() and ql not in rel.lower():
                    continue
                rows.append((rel, e, st, shown))
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
            "kind": rpy.KIND_CODE.get(e.category, ""),
            "issues": [{"severity": i.severity, "code": i.code} for i in shown],
        } for rel, e, st, shown in page]}

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
                    "status": self._entry_row(rel, x)}
        return {"file": rel, "path": str(self.project.root / rel), "line": e.line, "src_line": e.src_line,
                "block": e.block, "who": e.who, "unit": e.unit, "source": e.source, "target": e.target,
                "src_raw": e.src_raw, "cur_raw": e.cur_raw,
                "status": self._entry_row(rel, e), "kind": rpy.KIND_CODE.get(e.category, ""),
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

            def go():
                self.store.corr[name] = {"c": "" if not c_n else str(c_n), "t": "" if t_n is None else str(t_n)}
            self.store.change(f"Úprava počtů v {Path(name).name}", ("corr",), go)
            return self._changed("save")

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
