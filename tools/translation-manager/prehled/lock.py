"""Project lock: keeps two copies of the app from editing one project (and its _progress_data) at the same time.

`lock.json` in the data folder names the owner (pid, computer, random token) and is touched every few seconds
while the app runs. Another copy that finds a *fresh* lock of a different process refuses to open the project
unless the user takes it over. A lock that was not refreshed for `STALE_AFTER` seconds (crash, power loss)
is treated as free. The same process may always re-open its own project.
"""
import json
import os
import secrets
import socket
import threading
import time

from .util import atomic_write_bytes

LOCK_NAME = "lock.json"
STALE_AFTER = 60.0
BEAT_EVERY = 15.0


class ProjectLocked(Exception):
    """Another running copy of the app owns the project. `holder` is what lock.json says."""

    def __init__(self, holder):
        self.holder = holder
        age = max(0, int(time.time() - holder.get("time", 0)))
        super().__init__(f"Projekt právě používá jiná kopie aplikace (počítač {holder.get('host', '?')}, "
                         f"proces {holder.get('pid', '?')}, naposledy aktivní před {age} s). "
                         f"Dvě kopie najednou by si přepisovaly data.")


def _read(path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


class ProjectLock:
    def __init__(self, data_dir):
        self.path = data_dir / LOCK_NAME
        self.token = secrets.token_hex(8)
        self.held = False
        self.lost = False
        self._stop = threading.Event()
        self._thread = None

    def _payload(self):
        return {"pid": os.getpid(), "host": socket.gethostname(), "token": self.token, "time": time.time()}

    def acquire(self, force=False):
        """Take the lock. Raises ProjectLocked when a live foreign owner holds it (and `force` is False)."""
        cur = _read(self.path)
        if cur and not force and cur.get("token") != self.token:
            foreign = not (cur.get("pid") == os.getpid() and cur.get("host") == socket.gethostname())
            if foreign and time.time() - float(cur.get("time", 0)) < STALE_AFTER:
                raise ProjectLocked(cur)
        self._write()
        self.held, self.lost = True, False
        self._stop.clear()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def _write(self):
        try:
            atomic_write_bytes(self.path, json.dumps(self._payload()).encode("utf-8"))
        except OSError:
            pass            # a read-only folder must not stop the app; the lock is only a safety net

    def _beat(self):
        while not self._stop.wait(BEAT_EVERY):
            cur = _read(self.path)
            if cur and cur.get("token") != self.token:
                self.lost = True        # somebody took the project over
                return
            self._write()

    def check(self):
        """True while we still own the lock (re-reads the file, so it also notices a takeover immediately)."""
        if not self.held:
            return True
        cur = _read(self.path)
        if cur and cur.get("token") != self.token:
            self.lost = True
        return not self.lost

    def release(self):
        self._stop.set()
        if self.held and not self.lost:
            cur = _read(self.path)
            if cur and cur.get("token") == self.token:
                try:
                    self.path.unlink()
                except OSError:
                    pass
        self.held = False
