"""A translation project folder: discovery, incremental refresh, per-file counts."""
import os
import time
from collections import namedtuple
from dataclasses import dataclass, field
from pathlib import Path

from . import rpy
from .store import parse_corr, parse_value, text_hash

DATA_DIR_NAME = "_progress_data"
IGNORED_DIRS = {DATA_DIR_NAME, ".git", "__pycache__", "node_modules"}

# name, translated (incl. manual override), remaining, total, proofread, automatic translated count
Row = namedtuple("Row", "name done todo total corr auto")

EPISODE_STATUS_LABELS = {"none": "Nezačato", "wip": "Rozpracováno", "tr": "Přeloženo", "proof": "V korekci", "done": "Hotovo"}
STATUS_LABELS = {"done": "Hotovo", "rev": "Korektura", "tr": "Přeloženo", "wip": "Rozpracováno", "none": "Nezačato"}
STATUS_ORDER = {"none": 0, "wip": 1, "tr": 2, "rev": 3, "done": 4}


class ProjectUnavailable(Exception):
    """The project folder is missing or cannot be read."""


def file_status(done, todo, total, corr):
    if corr >= total:
        return "done"
    if todo == 0:
        return "rev" if corr > 0 else "tr"
    return "wip" if done > 0 else "none"


@dataclass
class FileInfo:
    rel: str
    sig: tuple
    parsed: rpy.ParsedFile
    error: str = ""


@dataclass
class RefreshReport:
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    renamed: list = field(default_factory=list)      # (old, new)
    unchanged: int = 0
    errors: list = field(default_factory=list)
    empty: list = field(default_factory=list)        # no translatable lines
    prev: dict = field(default_factory=dict)         # rel -> FileInfo before the change (for the text history)
    seconds: float = 0.0

    @property
    def changed(self):
        return bool(self.added or self.removed or self.modified or self.renamed)

    def summary(self):
        if not self.changed and not self.errors:
            return "Beze změn."
        parts = []
        for label, items in (("přidáno", self.added), ("změněno", self.modified),
                             ("přejmenováno", self.renamed), ("odebráno", self.removed)):
            if items:
                parts.append(f"{label} {len(items)}")
        if self.errors:
            parts.append(f"problémy {len(self.errors)}")
        return ", ".join(parts) + "."

    def to_dict(self):
        return {"added": self.added, "removed": self.removed, "modified": self.modified,
                "renamed": [{"from": a, "to": b} for a, b in self.renamed],
                "unchanged": self.unchanged, "errors": self.errors, "empty": self.empty,
                "seconds": round(self.seconds, 3), "changed": self.changed, "summary": self.summary()}


def check_project_dir(path):
    """(ok, message). A usable project folder exists, is readable and contains .rpy files."""
    try:
        p = Path(path)
        if not str(path).strip():
            return False, "Není vybraná žádná složka."
        if not p.exists():
            return False, f"Složka neexistuje: {p}"
        if not p.is_dir():
            return False, f"Není to složka: {p}"
        if not os.access(p, os.R_OK):
            return False, f"Ke složce nemám přístup pro čtení: {p}"
        for _dirpath, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            if any(f.lower().endswith(".rpy") for f in files):
                return True, ""
        return False, f"Ve složce nejsou žádné soubory .rpy: {p}"
    except OSError as e:
        return False, f"Složku nelze číst: {e}"


class Project:
    def __init__(self, root, store, skip=(), symbols_as_done=None):
        self.root = Path(root)
        self.store = store
        self.skip = {s.lower() for s in skip}
        self.symbols_as_done = symbols_as_done
        self.files = {}       # rel -> FileInfo (only files with translatable lines)
        self._known = {}      # rel -> sig for every file seen, also empty ones
        self.loaded_at = None
        self.last_report = None

    # ------------------------------------------------------------ discovery
    def _discover(self, errors, failed_dirs):
        if not self.root.is_dir():
            raise ProjectUnavailable(f"Složka projektu není dostupná: {self.root}")
        found = {}

        def onerror(e):
            failed_dirs.append(Path(getattr(e, "filename", "") or self.root))
            errors.append(f"Složku nelze procházet: {getattr(e, 'filename', '')} ({e.strerror or e})")

        for dirpath, dirs, files in os.walk(self.root, onerror=onerror):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
            for fn in sorted(files):
                if not fn.lower().endswith(".rpy") or fn.lower() in self.skip:
                    continue
                full = Path(dirpath) / fn
                try:
                    st = full.stat()
                except OSError as e:
                    failed_dirs.append(full)
                    errors.append(f"{full.relative_to(self.root)}: nelze zjistit stav ({e.strerror or e})")
                    continue
                found[str(full.relative_to(self.root))] = (full, (st.st_size, st.st_mtime_ns))
        return found

    # ------------------------------------------------------------ refresh
    def refresh(self, force=False):
        """Rescan the folder. Only new or changed files are parsed again.

        Reports added / removed / modified / renamed files. Metadata (proofread counts,
        assignments, approvals) of removed files stays in the store, so a file that comes back
        (or a temporarily unavailable network drive) loses nothing. A detected rename is
        returned in `report.renamed`; the caller moves the metadata (see migrate_metadata).
        """
        t0 = time.time()
        report = RefreshReport()
        failed = []
        found = self._discover(report.errors, failed)
        fresh = {}
        for rel, (full, sig) in found.items():
            if self._known.get(rel) == sig and not force:
                continue
            try:
                parsed = rpy.parse_bytes(full.read_bytes())
            except OSError as e:
                report.errors.append(f"{rel}: soubor nelze přečíst ({e.strerror or e}); ponechán poslední známý stav.")
                continue
            fresh[rel] = FileInfo(rel, sig, parsed)

        def unreachable(rel):
            p = self.root / rel
            return any(p == f or f in p.parents for f in failed)

        previously = set(self._known)
        gone = {r for r in previously - set(found) if not unreachable(r)}
        added = [r for r in fresh if r not in previously]
        modified = [r for r in fresh if r in previously]

        renames = []
        for new in list(added):
            nf = fresh[new].parsed
            best = None
            for old in sorted(gone):
                of = self.files.get(old)
                if of is None:
                    continue
                if of.parsed.digest and of.parsed.digest == nf.digest:
                    best = old
                    break
                ids_old = {b[1] for b in of.parsed.block_ids}
                ids_new = {b[1] for b in nf.block_ids}
                if ids_old and ids_new and Path(old).name == Path(new).name                         and len(ids_old & ids_new) / len(ids_old | ids_new) >= 0.8:
                    best = old
                    break
            if best:
                renames.append((best, new))
                gone.discard(best)
                added.remove(new)

        report.prev = {rel: self.files[rel] for rel in fresh if rel in self.files}
        for rel, fi in fresh.items():
            self._known[rel] = fi.sig
            if fi.parsed.entries:
                self.files[rel] = fi
            else:
                self.files.pop(rel, None)
                report.empty.append(rel)
        for old, _new in renames:
            self._known.pop(old, None)
            self.files.pop(old, None)
        for rel in gone:
            self._known.pop(rel, None)
            self.files.pop(rel, None)

        report.added = sorted(r for r in added if r in self.files)
        report.modified = sorted(r for r in modified if r in self.files)
        report.removed = sorted(gone)
        report.renamed = sorted(renames)
        report.unchanged = max(0, len(self.files) - len(report.added) - len(report.modified) - len(report.renamed))
        report.seconds = time.time() - t0
        self.loaded_at = time.time()
        self.last_report = report
        return report

    def migrate_metadata(self, renames):
        """Move proofread counts / assignments / approvals of renamed files to their new names.
        One undoable step. Returns the number of files whose metadata moved."""
        store = self.store
        moved = [(o, n) for o, n in renames
                 if o in store.corr or o in store.assign or o in store.approved or o in store.proof]
        if not moved:
            return 0

        def go():
            for old, new in moved:
                if old in store.corr:
                    store.corr.setdefault(new, store.corr[old])
                if old in store.assign:
                    store.assign.setdefault(new, store.assign.pop(old))
                if old in store.approved:
                    store.approved.setdefault(new, store.approved.pop(old))
                if old in store.proof:
                    store.proof.setdefault(new, store.proof.pop(old))
        store.change("Přejmenované soubory", ("corr", "assign", "approved", "proof"), go)
        store.clear_undo()   # older undo steps refer to the old names
        return len(moved)

    # ------------------------------------------------------------ counts
    def counts(self, rel):
        """(translated, remaining, approved) for a file — approved pending lines count as translated."""
        fi = self.files[rel]
        return rpy.count(fi.parsed.entries, self.store.approved.get(rel, ()), self.symbols_as_done)

    def is_translated(self, rel, e):
        """Translated, or an untranslated-looking line the translator approved."""
        return (not e.pending) or e.key in self.store.approved.get(rel, ())

    def proof_state(self, rel, e):
        """'' (not proofread) | 'ok' | 'fix' (flagged) | 'stale' (was ok, but the translation changed since)."""
        m = self.store.proof.get(rel, {}).get(e.key)
        if not m:
            return ""
        if m["s"] == "fix":
            return "fix"
        return "ok" if m.get("h") == text_hash(e.target) else "stale"

    def proof_counts(self, rel):
        """(lines marked proofread, lines flagged 'to fix') — only valid marks on translated lines."""
        marks = self.store.proof.get(rel)
        if not marks:
            return 0, 0
        ok = fix = 0
        for e in self.files[rel].parsed.entries:
            if e.key in marks and self.is_translated(rel, e):
                st = self.proof_state(rel, e)
                ok += st == "ok"
                fix += st == "fix"
        return ok, fix

    def proof_stale(self, rel):
        """Lines that were marked proofread but whose translation changed since (they need a new look)."""
        marks = self.store.proof.get(rel)
        if not marks:
            return 0
        return sum(1 for e in self.files[rel].parsed.entries
                   if e.key in marks and self.is_translated(rel, e) and self.proof_state(rel, e) == "stale")

    def rows(self):
        """One Row per file. Proofread = the hand-typed baseline (korekce.csv) + lines marked one by one."""
        out = []
        for rel in sorted(self.files, key=lambda r: r.lower()):
            done, todo, _appr = self.counts(rel)
            total = done + todo
            raw = self.store.corr.get(rel, {})
            ov = parse_value(raw.get("t", ""), total)
            shown = done if ov is None else ov
            corr = min(total, parse_corr(raw.get("c", ""), total) + self.proof_counts(rel)[0])
            out.append(Row(rel, shown, total - shown, total, corr, done))
        return out

    def row(self, rel):
        return next((r for r in self.rows() if r.name == rel), None)

    def entries(self, rel):
        return self.files[rel].parsed.entries

    def path_of(self, rel):
        """Absolute path of a project file; raises ValueError for anything outside the project."""
        full = (self.root / rel).resolve()
        root = self.root.resolve()
        if root != full and root not in full.parents:
            raise ValueError("Soubor není uvnitř složky projektu.")
        return full


def totals_of(rows):
    s_done = sum(r.done for r in rows)
    s_total = sum(r.total for r in rows)
    s_corr = sum(r.corr for r in rows)
    pct = (s_done / s_total * 100) if s_total else 0
    cpct = (s_corr / s_total * 100) if s_total else 0
    return s_done, s_total, s_corr, pct, cpct
