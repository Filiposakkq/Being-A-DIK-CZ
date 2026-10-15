"""Snapshots of the translation folder: a zip of every .rpy file, kept in `_progress_data/snapshots`.

Made automatically (at start when the last one is older than the configured interval), before bulk changes
(replace, fixes, unify) and on request; restoring first makes a snapshot of the current state, so a restore itself can
be undone. Only .rpy files are saved (the manager's own data have their own backups). Snapshots older than the
configured count are deleted, the manual ones last.
"""
import hashlib
import io
import json
import os
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .util import WriteFailed, atomic_write_bytes

DIR_NAME = "snapshots"
NAME_RE = re.compile(r"^snap-\d{8}-\d{6}(?:-\d+)?-(auto|bulk|manual|restore)\.zip$")
SKIP_DIRS = {"_progress_data", "__pycache__", ".git", "backups"}
MAX_BYTES = 400 * 1024 * 1024
REASONS = {"auto": "automatická", "bulk": "před hromadnou změnou", "manual": "ručně vytvořená", "restore": "před obnovením"}


class SnapshotError(Exception):
    pass


def _dir(data_dir):
    return Path(data_dir) / DIR_NAME


def rpy_files(root):
    """[(relative path with forward slashes, absolute Path)] of every .rpy file below `root`."""
    root = Path(root)
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fn in sorted(files):
            if fn.lower().endswith(".rpy"):
                full = Path(dirpath) / fn
                out.append((full.relative_to(root).as_posix(), full))
    return out


def create(root, data_dir, reason="manual", app_version=""):
    """Zip the .rpy files. Returns the manifest dict (with `name`), or None when there is nothing to save."""
    if reason not in REASONS:
        raise SnapshotError("Neznámý druh zálohy.")
    files = rpy_files(root)
    if not files:
        return None
    total = sum(f.stat().st_size for _r, f in files if f.exists())
    if total > MAX_BYTES:
        raise SnapshotError(f"Soubory .rpy mají {total // (1024 * 1024)} MB – záloha se nevytvoří (limit {MAX_BYTES // (1024 * 1024)} MB).")
    d = _dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    base = f"snap-{now:%Y%m%d-%H%M%S}"
    name, n = f"{base}-{reason}.zip", 0
    while (d / name).exists():
        n += 1
        name = f"{base}-{n}-{reason}.zip"
    manifest = {"time": now.isoformat(timespec="seconds"), "reason": reason, "files": len(files), "bytes": total, "app": app_version}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for rel, full in files:
            try:
                z.write(full, "files/" + rel)
            except OSError:
                manifest["files"] -= 1                       # a file that vanished meanwhile is simply not saved
    try:
        atomic_write_bytes(d / name, buf.getvalue())
    except WriteFailed as e:
        raise SnapshotError(f"Zálohu nelze zapsat: {e.reason}") from e
    return dict(manifest, name=name)


def _manifest(path):
    try:
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read("manifest.json").decode("utf-8"))
        m["name"] = path.name
        m["size"] = path.stat().st_size
        m["reason_label"] = REASONS.get(m.get("reason"), m.get("reason", ""))
        return m
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return None


def list_snapshots(data_dir):
    """Newest first: [{name, time, reason, files, bytes, size}]."""
    d = _dir(data_dir)
    if not d.is_dir():
        return []
    out = [m for m in (_manifest(p) for p in d.iterdir() if NAME_RE.match(p.name)) if m]
    return sorted(out, key=lambda m: m.get("time", ""), reverse=True)


def last_age_hours(data_dir):
    snaps = list_snapshots(data_dir)
    if not snaps:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(snaps[0]["time"])).total_seconds() / 3600
    except ValueError:
        return None


def prune(data_dir, keep):
    """Delete the oldest snapshots beyond `keep` (manual ones are kept the longest)."""
    snaps = list_snapshots(data_dir)
    extra = len(snaps) - max(1, int(keep))
    if extra <= 0:
        return 0
    order = sorted(snaps, key=lambda m: (m.get("reason") == "manual", m.get("time", "")))
    removed = 0
    for m in order[:extra]:
        try:
            (_dir(data_dir) / m["name"]).unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _path(data_dir, name):
    if not NAME_RE.match(str(name)):
        raise SnapshotError("Neplatný název zálohy.")
    p = _dir(data_dir) / name
    if not p.is_file():
        raise SnapshotError("Záloha neexistuje.")
    return p


def delete(data_dir, name):
    try:
        _path(data_dir, name).unlink()
    except OSError as e:
        raise SnapshotError(f"Zálohu nelze smazat: {e.strerror or e}") from e


def compare(root, data_dir, name):
    """For every file in the snapshot: same | changed | missing (not in the folder any more), against the current state."""
    p = _path(data_dir, name)
    root = Path(root)
    out = []
    with zipfile.ZipFile(p) as z:
        for info in z.infolist():
            if not info.filename.startswith("files/") or info.is_dir():
                continue
            rel = info.filename[len("files/"):]
            cur = root / rel
            if not cur.is_file():
                state = "missing"
            else:
                try:
                    same = hashlib.sha1(cur.read_bytes()).digest() == hashlib.sha1(z.read(info)).digest()
                except OSError:
                    same = False
                state = "same" if same else "changed"
            out.append({"file": rel, "state": state})
    return sorted(out, key=lambda r: ({"changed": 0, "missing": 1, "same": 2}[r["state"]], r["file"].lower()))


def restore(root, data_dir, name, files=None, app_version=""):
    """Put files of a snapshot back (all, or the chosen ones). First saves the current state as a "restore" snapshot.
    Returns {restored: [rel], safety: manifest}."""
    p = _path(data_dir, name)
    root = Path(root).resolve()
    wanted = None if files is None else {str(f).replace("\\", "/") for f in files}
    safety = create(root, data_dir, "restore", app_version)
    restored = []
    with zipfile.ZipFile(p) as z:
        for info in z.infolist():
            if not info.filename.startswith("files/") or info.is_dir():
                continue
            rel = info.filename[len("files/"):]
            if wanted is not None and rel not in wanted:
                continue
            target = (root / rel).resolve()
            if root != target and root not in target.parents:
                raise SnapshotError("Záloha obsahuje cestu mimo složku projektu, obnovení zrušeno.")
            try:
                atomic_write_bytes(target, z.read(info))
            except WriteFailed as e:
                raise SnapshotError(f"Nelze zapsat {rel}: {e.reason}") from e
            restored.append(rel)
    return {"restored": restored, "safety": safety}


def due(data_dir, interval_hours):
    """True when no snapshot exists or the newest one is older than the interval."""
    age = last_age_hours(data_dir)
    return age is None or age >= float(interval_hours)


def recent(data_dir, minutes):
    age = last_age_hours(data_dir)
    return age is not None and age * 60 < minutes
