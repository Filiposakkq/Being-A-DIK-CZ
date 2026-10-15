"""The only place where the manager changes a translation .rpy file.

Two operations: (1) editing the translated text of one line in the app (edit_translation), and (2) fixing
one narrow class of mistakes: a dialogue line whose speaker / attributes (`mc happy`) or trailing
code (`with vpunch`) differ from the original comment above it. The correct form is copied from the
original, the quoted text is never touched.

Safety: a plan is built first (nothing written); applying re-reads the file and refuses when it changed
on disk since it was parsed; a backup of the file is always made; the write is atomic; the file is
parsed again afterwards and the result is verified.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from . import rpy, validator
from .util import WriteFailed, atomic_write_bytes, make_backup, norm_ws

SPLIT_RE = re.compile(r"(\r\n|\r|\n)")
BOM = b"\xef\xbb\xbf"


LAST_FILE = "last_fix.json"


class FixError(Exception):
    pass


def fixed_line(entry, raw_line):
    """The code line with speaker and trailing code taken from the original, or None when not applicable."""
    m = rpy.STR_RE.search(raw_line)
    if not m:
        return None
    indent = raw_line[:len(raw_line) - len(raw_line.lstrip())]
    who = entry.src_who.strip()
    suffix = entry.src_suffix.strip()
    return indent + (who + " " if who else "") + raw_line[m.start():m.end()] + (" " + suffix if suffix else "")


def needs_fix(entry):
    """True when check_entry would report speaker-changed / suffix-changed for this entry."""
    return any(i.code in ("speaker-changed", "suffix-changed") for i in validator.check_entry(entry))


def plan(project, items=None, file=""):
    """[{file, line, code, before, after, skip}] for every fixable line.

    `items` = [{file, line}] limits the plan to those lines; otherwise all fixable lines of `file`
    (or of the whole project) are planned."""
    wanted = None
    if items:
        wanted = {(str(i["file"]), int(i["line"])) for i in items}
    out = []
    for rel in sorted(project.files, key=str.lower):
        if file and rel != file:
            continue
        for e in project.entries(rel):
            if wanted is not None and (rel, e.line) not in wanted:
                continue
            if e.unit != "dialogue" or e.source is None or (e.pending and e.category):
                continue
            codes = [i.code for i in validator.check_entry(e) if i.code in ("speaker-changed", "suffix-changed")]
            if not codes:
                continue
            after = fixed_line(e, e.cur_raw)
            skip = ""
            if after is None:
                skip = "Řádek neobsahuje text v uvozovkách."
            elif norm_ws(after) == norm_ws(e.src_raw):
                skip = "Po opravě by byl řádek shodný s originálem (počítal by se jako nepřeložený) – oprav ručně."
            out.append({"file": rel, "line": e.line, "code": codes[0], "before": e.cur_raw, "after": after or "",
                        "skip": skip, "source_line": e.src_raw})
    return out


def apply(project, data_dir, planned):
    """Write the planned fixes. Returns {fixed, skipped: [(file, line, reason)], backups}."""
    by_file = {}
    skipped = []
    for p in planned:
        if p["skip"]:
            skipped.append((p["file"], p["line"], p["skip"]))
        else:
            by_file.setdefault(p["file"], []).append(p)
    fixed, backups, record = 0, [], []
    for rel, items in by_file.items():
        full = project.path_of(rel)
        fi = project.files.get(rel)
        try:
            data = full.read_bytes()
        except OSError as e:
            raise FixError(f"{rel}: soubor nelze přečíst ({e.strerror or e}).") from e
        if fi is None or rpy.parse_bytes(data).digest != fi.parsed.digest:
            raise FixError(f"{rel}: soubor se na disku změnil od načtení. Obnov soubory a zkus to znovu.")
        had_bom = data.startswith(BOM)
        text = data[len(BOM):].decode("utf-8", errors="strict") if had_bom else data.decode("utf-8", errors="strict")
        parts = SPLIT_RE.split(text)       # text, eol, text, eol ... — line N is parts[2 * (N - 1)]
        for p in items:
            idx = 2 * (p["line"] - 1)
            if idx >= len(parts) or parts[idx].strip() != p["before"]:
                raise FixError(f"{rel}:{p['line']}: řádek už neodpovídá načtenému stavu. Obnov soubory.")
            lead = parts[idx][:len(parts[idx]) - len(parts[idx].lstrip())]
            parts[idx] = lead + p["after"].lstrip() + parts[idx][len(parts[idx].rstrip()):]
        new_bytes = ("".join(parts)).encode("utf-8")
        if had_bom:
            new_bytes = BOM + new_bytes
        backup = make_backup(full, data_dir / "backups", min_interval=0, keep=50)
        if backup:
            backups.append(str(backup))
        try:
            atomic_write_bytes(full, new_bytes)
        except WriteFailed as e:
            raise FixError(f"Nelze zapsat: {e.reason} ({full.name})") from e
        check = rpy.parse_bytes(full.read_bytes())
        old_entries = fi.parsed.entries
        if len(check.entries) != len(old_entries) or any(
                a.target != b.target for a, b in zip(old_entries, check.entries)):
            atomic_write_bytes(full, data)
            raise FixError(f"{rel}: kontrola po zápisu selhala, soubor byl vrácen do původního stavu.")
        fixed += len(items)
        if backup:
            record.append({"file": rel, "backup": str(backup), "after": hashlib.sha1(new_bytes).hexdigest(),
                           "lines": len(items)})
    if record:
        _push(data_dir, {"time": datetime.now().isoformat(timespec="seconds"), "label": "Oprava mluvčích podle originálu",
                         "files": record})
    return {"fixed": fixed, "skipped": skipped, "backups": backups}


STACK_MAX = 30


def _stack(data_dir):
    try:
        data = json.loads((data_dir / LAST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):                  # older format: a single record
        data = [data]
    return [r for r in data if isinstance(r, dict) and r.get("files")]


def _push(data_dir, rec):
    stack = (_stack(data_dir) + [rec])[-STACK_MAX:]
    atomic_write_bytes(data_dir / LAST_FILE, json.dumps(stack, ensure_ascii=False, indent=1).encode("utf-8"))


def last(data_dir):
    """The newest change that can still be undone: {time, label, files, lines} or None."""
    stack = _stack(data_dir)
    if not stack:
        return None
    rec = dict(stack[-1])
    rec["lines"] = sum(f.get("lines", 0) for f in rec["files"])
    rec["depth"] = len(stack)
    return rec


def undo(project, data_dir):
    """Put the files of the newest change back from their backups. Refuses when a file was edited since
    (the backup would silently throw those edits away). Returns {restored: [rel...], lines, label}."""
    stack = _stack(data_dir)
    if not stack:
        raise FixError("Není co vracet.")
    rec = stack[-1]
    checked = []
    for f in rec["files"]:
        full = project.path_of(f["file"])
        bak = Path(f["backup"])
        try:
            now = hashlib.sha1(full.read_bytes()).hexdigest()
            before = bak.read_bytes()
        except OSError as e:
            raise FixError(f"{f['file']}: nelze číst soubor nebo zálohu ({e.strerror or e}).") from e
        if now != f["after"]:
            raise FixError(f"{f['file']}: soubor se od poslední změny změnil jinde (např. v editoru). Vrácení by smazalo "
                           f"pozdější úpravy – zálohu najdeš v {bak.parent}.")
        checked.append((full, before, f["file"]))
    for full, before, _rel in checked:
        try:
            atomic_write_bytes(full, before)
        except WriteFailed as e:
            raise FixError(f"Nelze zapsat: {e.reason} ({full.name})") from e
    rest = stack[:-1]
    try:
        if rest:
            atomic_write_bytes(data_dir / LAST_FILE, json.dumps(rest, ensure_ascii=False, indent=1).encode("utf-8"))
        else:
            (data_dir / LAST_FILE).unlink()
    except OSError:
        pass
    return {"restored": [c[2] for c in checked], "lines": sum(f.get("lines", 0) for f in rec["files"]),
            "label": rec.get("label", "")}


# ---------------------------------------------------------------- editing one translated text

def check_literal(text):
    """The raw text that goes between the quotes of a Ren'Py string must stay one valid string literal."""
    if "\n" in text or "\r" in text:
        raise FixError("Text nesmí obsahovat skutečné zalomení řádku. Nový řádek zapiš jako \\n.")
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            if i + 1 >= len(text):
                raise FixError("Text nesmí končit samotným zpětným lomítkem „\\“ (zapiš \\\\ nebo \\n).")
            i += 2
            continue
        if ch == '"':
            raise FixError('Uvozovku v textu zapiš jako \\" – holá uvozovka by ukončila řetězec.')
        i += 1


def _stage_file(project, rel, changes):
    """Prepare the new bytes of one file for {line: new_text}. Nothing is written. Returns a dict."""
    fi = project.files.get(rel)
    if fi is None:
        raise FixError(f"{rel}: neznámý soubor.")
    ents = {e.line: e for e in project.entries(rel)}
    full = project.path_of(rel)
    try:
        data = full.read_bytes()
    except OSError as e:
        raise FixError(f"{rel}: soubor nelze přečíst ({e.strerror or e}).") from e
    if rpy.parse_bytes(data).digest != fi.parsed.digest:
        raise FixError(f"{rel}: soubor se na disku změnil od načtení (třeba v editoru). Obnov soubory a zkus to znovu.")
    had_bom = data.startswith(BOM)
    try:
        text = (data[len(BOM):] if had_bom else data).decode("utf-8")
    except UnicodeDecodeError as e:
        raise FixError(f"{rel}: soubor není platné UTF-8, úpravu raději neprovádím.") from e
    parts = SPLIT_RE.split(text)
    for line, new_text in changes.items():
        ent = ents.get(line)
        if ent is None:
            raise FixError(f"{rel}:{line}: řádek už v souboru není – obnov soubory.")
        check_literal(new_text)
        idx = 2 * (line - 1)
        if idx >= len(parts) or parts[idx].strip() != ent.cur_raw:
            raise FixError(f"{rel}:{line}: řádek už neodpovídá načtenému stavu. Obnov soubory.")
        raw = parts[idx]
        m = rpy.STR_RE.search(raw)
        if not m:
            raise FixError(f"{rel}:{line}: na řádku není text v uvozovkách.")
        parts[idx] = raw[:m.start()] + '"' + new_text + '"' + raw[m.end():]
    new_bytes = "".join(parts).encode("utf-8")
    if had_bom:
        new_bytes = BOM + new_bytes
    return {"rel": rel, "full": full, "data": data, "new": new_bytes, "changes": changes, "old": fi.parsed.entries}


def _verify(staged, written):
    """The file on disk must differ from the old one in exactly the planned lines and nowhere else."""
    old, changes = staged["old"], staged["changes"]
    if len(written.entries) != len(old):
        return False
    for a, b in zip(old, written.entries):
        want = changes.get(a.line, a.target)
        if b.line != a.line or b.target != want or b.who != a.who or b.suffix != a.suffix:
            return False
    return True


def apply_edits(project, data_dir, edits, label):
    """Replace the translated text of several lines (possibly in several files) as ONE undoable step.

    edits = [(rel, line, new_text)]. Everything else in the files stays byte for byte as it was. Every file is
    backed up, written atomically and verified; if anything fails the files already written are restored.
    Returns {changed, files, backups}."""
    by_file = {}
    for rel, line, new_text in edits:
        ent = next((e for e in project.entries(rel) if e.line == line), None) if rel in project.files else None
        if ent is not None and ent.target == new_text:
            continue                                         # nothing to do for this line
        by_file.setdefault(rel, {})[int(line)] = new_text
    if not by_file:
        return {"changed": 0, "files": 0, "backups": []}
    staged = [_stage_file(project, rel, ch) for rel, ch in sorted(by_file.items())]   # validates everything first
    written, record, backups = [], [], []
    try:
        for st in staged:
            backup = make_backup(st["full"], data_dir / "backups", min_interval=0, keep=50)
            atomic_write_bytes(st["full"], st["new"])
            written.append(st)
            if not _verify(st, rpy.parse_bytes(st["full"].read_bytes())):
                raise FixError(f"{st['rel']}: kontrola po zápisu selhala, změny byly vráceny do původního stavu.")
            if backup:
                backups.append(str(backup))
                record.append({"file": st["rel"], "backup": str(backup), "after": hashlib.sha1(st["new"]).hexdigest(),
                               "lines": len(st["changes"])})
    except (FixError, WriteFailed, OSError) as e:
        for st in written:                                   # roll back what was already written
            try:
                atomic_write_bytes(st["full"], st["data"])
            except (WriteFailed, OSError):
                pass
        if isinstance(e, WriteFailed):
            raise FixError(f"Nelze zapsat: {e.reason} ({e.path.name})") from e
        if isinstance(e, FixError):
            raise
        raise FixError(f"Zápis selhal: {e}") from e
    if record:
        _push(data_dir, {"time": datetime.now().isoformat(timespec="seconds"), "label": label, "files": record})
    return {"changed": sum(len(st["changes"]) for st in staged), "files": len(staged), "backups": backups}


def edit_translation(project, data_dir, rel, line, new_text):
    """Replace the translated text of one unit. Returns {changed, backup}."""
    ent = next((e for e in project.entries(rel) if e.line == line), None)
    if ent is None:
        raise FixError("Řádek už v souboru není – obnov soubory.")
    check_literal(new_text)
    if new_text == ent.target:
        return {"changed": False}
    res = apply_edits(project, data_dir, [(rel, line, new_text)], f"Úprava řádku {line} v {Path(rel).name}")
    return {"changed": True, "backup": res["backups"][0] if res["backups"] else ""}
