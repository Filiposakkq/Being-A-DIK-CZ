"""Open a translation file at an exact line in VS Code or Notepad++.

Commands are always built as an argument list (never a shell string) and the file must be a
.rpy file inside the project, so a hostile file name cannot inject anything.
  VS Code:    Code.exe -g "<file>:<line>"         (the `code -g` form)
  Notepad++:  notepad++.exe -n<line> "<file>"
When the preferred editor is missing the other known editor is tried, then the system default
(which cannot jump to a line — the message says so). A failure is always reported.
"""
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

NOWIN = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
SHELL_UNSAFE = set('&|<>^%"\r\n')


def _first_existing(paths):
    for p in paths:
        if p and Path(p).is_file():
            return str(p)
    return None


def find_vscode(which=shutil.which, env=os.environ):
    """Path of Code.exe (preferred: runs without cmd.exe) or the `code` launcher."""
    launcher = which("code")
    if launcher:
        lp = Path(launcher)
        if lp.suffix.lower() in (".cmd", ".bat"):
            exe = _first_existing([lp.resolve().parent.parent / "Code.exe"])
            return exe or launcher
        return launcher
    if sys.platform.startswith("win"):
        return _first_existing([
            Path(env.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/Code.exe",
            Path(env.get("ProgramFiles", "")) / "Microsoft VS Code/Code.exe",
            Path(env.get("ProgramFiles(x86)", "")) / "Microsoft VS Code/Code.exe"])
    return which("codium")


def find_notepadpp(which=shutil.which, env=os.environ):
    found = which("notepad++")
    if found:
        return found
    return _first_existing([Path(env.get("ProgramFiles", "")) / "Notepad++/notepad++.exe",
                            Path(env.get("ProgramFiles(x86)", "")) / "Notepad++/notepad++.exe",
                            Path(env.get("LOCALAPPDATA", "")) / "Programs/Notepad++/notepad++.exe"])


def build_command(kind, exe, path, line):
    if kind == "vscode":
        return [exe, "-g", f"{path}:{line}"]
    if kind == "notepadpp":
        return [exe, f"-n{line}", str(path)]
    raise ValueError(kind)


def custom_command(template, path, line):
    """Expand a user template like: "C:\\Tools\\ed.exe" --line {line} {file}  into an argv list."""
    argv = shlex.split(template, posix=not sys.platform.startswith("win"))
    argv = [a.strip('"') for a in argv]
    if not argv:
        raise ValueError("Vlastní příkaz je prázdný.")
    if not any("{file}" in a for a in argv):
        argv.append("{file}")
    return [a.replace("{file}", str(path)).replace("{line}", str(line)) for a in argv]


def _validate_target(path, root):
    p = Path(path).resolve()
    if not p.is_file():
        raise ValueError(f"Soubor neexistuje: {p}")
    if p.suffix.lower() != ".rpy":
        raise ValueError("Otevřít lze jen soubory .rpy.")
    if root is not None:
        r = Path(root).resolve()
        if r != p and r not in p.parents:
            raise ValueError("Soubor není uvnitř složky projektu.")
    return p


def default_finder(kind):
    """Path of the editor executable for 'vscode' / 'notepadpp', or None when not installed."""
    return {"vscode": find_vscode, "notepadpp": find_notepadpp}[kind]()


def system_open(path):
    """Open with the OS default program (cannot jump to a line)."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_in_editor(path, line, editor_cfg=None, root=None, runner=None, finder=None, opener=None):
    """Open `path` at `line`. Returns {ok, editor, command, message, jumped}.

    `runner(argv)`, `finder(kind)` and `opener(path)` can be replaced in tests.
    """
    cfg = {"preferred": "auto", "custom": ""}
    cfg.update(editor_cfg or {})
    runner = runner or (lambda argv: subprocess.Popen(argv, close_fds=True, **NOWIN))
    finder = finder or default_finder
    opener = opener or system_open
    try:
        p = _validate_target(path, root)
        line = max(1, int(line or 1))
    except (ValueError, OSError) as e:
        return {"ok": False, "editor": "", "command": [], "message": str(e), "jumped": False}

    pref = cfg["preferred"]
    order = {"vscode": ["vscode", "notepadpp"], "notepadpp": ["notepadpp", "vscode"],
             "auto": ["vscode", "notepadpp"], "custom": ["custom", "vscode", "notepadpp"],
             "system": []}.get(pref, ["vscode", "notepadpp"])
    tried = []
    for kind in order:
        try:
            if kind == "custom":
                if not cfg["custom"].strip():
                    tried.append("vlastní příkaz není nastaven")
                    continue
                argv = custom_command(cfg["custom"], p, line)
                exe = argv[0]
                if not (Path(exe).is_file() or shutil.which(exe)):
                    tried.append(f"vlastní příkaz: {exe} nenalezen")
                    continue
            else:
                exe = finder(kind) if callable(finder) else None
                label = "VS Code" if kind == "vscode" else "Notepad++"
                if not exe:
                    tried.append(f"{label} nenalezen")
                    continue
                if Path(exe).suffix.lower() in (".cmd", ".bat") and (set(str(p)) & SHELL_UNSAFE):
                    tried.append(f"{label}: cesta obsahuje znaky nebezpečné pro cmd.exe")
                    continue
                argv = build_command(kind, exe, p, line)
            runner(argv)
            name = {"vscode": "VS Code", "notepadpp": "Notepad++", "custom": "vlastní editor"}[kind]
            return {"ok": True, "editor": kind, "command": argv, "jumped": True,
                    "message": f"Otevřeno v {name} na řádku {line}."}
        except (OSError, ValueError) as e:
            tried.append(f"{kind}: {e}")
    # fallback: system default, no line number possible
    try:
        opener(p)
        return {"ok": True, "editor": "system", "command": [str(p)], "jumped": False,
                "message": "VS Code ani Notepad++ se nepodařilo spustit (" + "; ".join(tried or ["nenastaveno"]) +
                           "). Soubor je otevřený ve výchozím programu, ale bez skoku na řádek "
                           f"{line} – nastav editor v Nastavení."}
    except OSError as e:
        tried.append(f"výchozí program: {e}")
    return {"ok": False, "editor": "", "command": [], "jumped": False,
            "message": "Soubor se nepodařilo otevřít: " + "; ".join(tried)}
