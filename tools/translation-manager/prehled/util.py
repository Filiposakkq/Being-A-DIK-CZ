"""Safe file helpers: atomic writes, rotating backups, tolerant CSV reading."""
import csv
import io
import os
import re
import shutil
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path


class WriteFailed(OSError):
    """A write did not happen. `reason` is a short, user-presentable explanation."""

    def __init__(self, path, reason):
        super().__init__(f"{Path(path).name}: {reason}")
        self.path = Path(path)
        self.reason = reason


def norm_ws(text):
    return re.sub(r"\s+", " ", text).strip()


def fold(text):
    """Lower-case, diacritics stripped (for forgiving comparisons of user-typed words)."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if unicodedata.category(c) != "Mn").strip()


def make_backup(path, backup_dir, keep=20, min_interval=300):
    """Copy `path` into `backup_dir` as <name>.<timestamp>.bak.

    Skips when the newest backup of this file is younger than `min_interval` seconds, so
    a burst of edits does not produce a burst of backups. Returns the backup path or None.
    """
    path, backup_dir = Path(path), Path(backup_dir)
    if not path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(backup_dir.glob(path.name + ".*.bak"))
    if existing and min_interval and time.time() - existing[-1].stat().st_mtime < min_interval:
        return None
    dest = backup_dir / f"{path.name}.{datetime.now():%Y%m%d-%H%M%S-%f}.bak"
    shutil.copy2(path, dest)
    existing = sorted(backup_dir.glob(path.name + ".*.bak"))
    for old in existing[:-keep] if keep else []:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def atomic_write_bytes(path, data, backup_dir=None, retries=3):
    """Write via a temp file in the same folder + os.replace, so an interruption can never
    leave a half-written file. Raises WriteFailed with a readable reason."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup_dir is not None and path.exists():
            make_backup(path, backup_dir)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    except PermissionError as e:
        raise WriteFailed(path, "nemám oprávnění zapisovat do složky") from e
    except OSError as e:
        raise WriteFailed(path, f"složku nelze použít ({e.strerror or e})") from e
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(retries):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == retries - 1:
                    raise WriteFailed(path, "soubor je zamčený (otevřený v Excelu nebo jiném programu?)") from None
                time.sleep(0.15 * (attempt + 1))
    except WriteFailed:
        raise
    except OSError as e:
        raise WriteFailed(path, e.strerror or str(e)) from e
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return path


def atomic_write_text(path, text, encoding="utf-8", backup_dir=None, newline=None):
    if newline is not None:
        text = text.replace("\r\n", "\n").replace("\n", newline)
    return atomic_write_bytes(path, text.encode(encoding), backup_dir=backup_dir)


def csv_text(rows, delimiter=";"):
    buf = io.StringIO()
    wr = csv.writer(buf, delimiter=delimiter)
    wr.writerows(rows)
    return buf.getvalue()


def write_csv(path, rows, backup_dir=None):
    """Excel-friendly CSV: UTF-8 with BOM, ';' delimiter, CRLF — the format the old tool wrote."""
    return atomic_write_bytes(path, csv_text(rows).encode("utf-8-sig"), backup_dir=backup_dir)


def read_rows(path):
    """Read a CSV (',' or ';', with or without BOM). Missing file -> []. Raises OSError otherwise."""
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    # parse the whole text (not line by line) so quoted fields may contain line breaks (notes)
    return [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=delim) if r]
