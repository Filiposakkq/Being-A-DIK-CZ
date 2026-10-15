"""Run `renpy lint` of the game from the Ren'Py SDK and show what it reports.

Ren'Py's own lint knows things this manager's checks do not (missing images, unknown labels, broken translations).
It needs the SDK folder (the one with renpy.py / renpy.sh); that path is a setting. The game must be run from the SDK, so
this only works when the game's .rpy sources are next to the translation (game/…). The command is built as an argument
list (no shell). A run can take a minute, so it runs in a background thread and the UI polls for the result.
"""
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

NOWIN = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
TIMEOUT = 300
MAX_OUTPUT = 200_000
ISSUE_RE = re.compile(r"^(?P<file>[^\s:][^:]*?\.rpym?):(?P<line>\d+)\s+(?P<msg>.+?)\s*$")


class LintError(Exception):
    pass


def find_python(sdk):
    """The Python that ships with the SDK: lib/py3-*/ (Ren'Py 8), lib/py2-*/ or lib/<platform>-<arch>/ (Ren'Py 7 and older)."""
    sdk = Path(sdk)
    lib = sdk / "lib"
    if not lib.is_dir():
        return None
    plat = "windows" if sys.platform.startswith("win") else "mac" if sys.platform == "darwin" else "linux"
    dirs = sorted(lib.glob("py3-*")) + sorted(lib.glob("py2-*")) + sorted(lib.glob(plat + "-*"), key=lambda d: ("x86_64" not in d.name, d.name))
    for d in dirs:
        for name in ("python.exe", "python"):
            if (d / name).is_file():
                return d / name
    return None


def build_command(sdk, base):
    """(argv, cwd) that runs `lint` for the game folder `base` (the folder that contains game/)."""
    sdk = Path(sdk)
    if not sdk.is_dir():
        raise LintError(f"Složka Ren'Py SDK neexistuje: {sdk}")
    py, entry = find_python(sdk), sdk / "renpy.py"
    if py and entry.is_file():
        return [str(py), "-EO", str(entry), str(base), "lint"], sdk
    sh = sdk / "renpy.sh"
    if sh.is_file() and not sys.platform.startswith("win"):
        return [str(sh), str(base), "lint"], sdk
    raise LintError("V SDK jsem nenašel renpy.py a vestavěný Python (lib/py3-…, lib/windows-x86_64 …) ani renpy.sh. Je to složka rozbaleného Ren'Py SDK?")


def parse(output):
    """Lines like `game/script.rpy:123 text` -> [{file, line, message}]; everything is also kept raw."""
    issues = []
    for ln in output.splitlines():
        m = ISSUE_RE.match(ln.strip())
        if m:
            issues.append({"file": m.group("file").replace("\\", "/"), "line": int(m.group("line")), "message": m.group("msg")})
    return issues


def run(sdk, base, runner=None):
    """Run lint synchronously. Returns {ok, exit_code, issues, raw, seconds}. `runner(argv, cwd)` -> (code, text) for tests."""
    argv, cwd = build_command(sdk, base)
    t0 = time.time()
    if runner is None:
        def runner(a, c):
            try:
                p = subprocess.run(a, cwd=str(c), capture_output=True, timeout=TIMEOUT, **NOWIN)
            except subprocess.TimeoutExpired as e:
                raise LintError(f"Lint trval déle než {TIMEOUT} s a byl přerušen.") from e
            except OSError as e:
                raise LintError(f"Lint se nepodařilo spustit: {e.strerror or e}") from e
            return p.returncode, (p.stdout or b"").decode("utf-8", errors="replace") + (p.stderr or b"").decode("utf-8", errors="replace")
    code, text = runner(argv, cwd)
    text = text[:MAX_OUTPUT]
    return {"ok": code == 0, "exit_code": code, "issues": parse(text), "raw": text, "seconds": round(time.time() - t0, 1)}


class Linter:
    """One background run at a time; `status()` is polled by the UI."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"state": "idle"}

    def start(self, sdk, base, runner=None):
        with self.lock:
            if self.state.get("state") == "running":
                raise LintError("Lint už běží.")
            build_command(sdk, base)                                   # fail early with a readable message
            self.state = {"state": "running", "started": time.time()}

        def work():
            try:
                res = run(sdk, base, runner)
                new = {"state": "done", **res}
            except LintError as e:
                new = {"state": "error", "error": str(e)}
            except Exception as e:                                      # noqa: BLE001
                new = {"state": "error", "error": f"Neočekávaná chyba: {e}"}
            with self.lock:
                self.state = new
        threading.Thread(target=work, daemon=True).start()

    def status(self):
        with self.lock:
            st = dict(self.state)
        if st.get("state") == "running":
            st["elapsed"] = round(time.time() - st["started"], 1)
        return st
