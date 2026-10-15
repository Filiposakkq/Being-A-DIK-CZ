"""The only place where the manager changes a translation .rpy file.

Fixes one narrow class of mistakes: a dialogue line whose speaker / attributes (`mc happy`) or trailing
code (`with vpunch`) differ from the original comment above it. The correct form is copied from the
original, the quoted text is never touched.

Safety: a plan is built first (nothing written); applying re-reads the file and refuses when it changed
on disk since it was parsed; a backup of the file is always made; the write is atomic; the file is
parsed again afterwards and the result is verified.
"""
import re

from . import rpy, validator
from .util import WriteFailed, atomic_write_bytes, make_backup, norm_ws

SPLIT_RE = re.compile(r"(\r\n|\r|\n)")
BOM = b"\xef\xbb\xbf"


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
    fixed, backups = 0, []
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
    return {"fixed": fixed, "skipped": skipped, "backups": backups}
