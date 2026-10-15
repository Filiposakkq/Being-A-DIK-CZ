"""Command line / launcher.

  BaDIKTranslationManager.exe                      open the window with the remembered project folder
  progress.py "<game>\\game\\tl\\czech"      open that folder (and remember it)
  ... --nogui                              print the summary only (writes the csv / json files)
  ... --todo                               with --nogui: only unfinished files
  ... --find=script.rpy                    list lines identical to the original
  ... --skip=common.rpy,screens.rpy        files to ignore (saved in the settings)
  ... --publish                            show the publish preview and ask for confirmation
  ... --browser                            use a browser window instead of pywebview
"""
import atexit
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .app import App, AppError
from .config import Config, config_dir
from .project import check_project_dir, totals_of
from .server import log_exception, start_server

NOWIN = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}


def app_dir():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- windows

def pick_folder(initial=""):
    """Native folder dialog: the pywebview window if there is one, else tkinter."""
    try:
        import webview
        if webview.windows:
            kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
            res = webview.windows[0].create_file_dialog(kind, directory=initial or "")
            return str(res[0]) if res else None
    except Exception:  # noqa: BLE001 - fall through to tkinter
        pass
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        d = filedialog.askdirectory(title="Vyber složku s překladem (game/tl/czech)", initialdir=initial or None)
        r.destroy()
        return d or None
    except Exception:  # noqa: BLE001
        return None


def run_desktop(url):
    """Own window (pywebview). True once a window was shown and closed; False -> use the browser."""
    try:
        import webview
    except ImportError:
        print("(pywebview není nainstalovaný: py -m pip install pywebview)")
        return False
    try:
        webview.create_window("BaDIK Translation Manager 1.0", url, width=1560, height=940, min_size=(1000, 620),
                              background_color="#0f1319")
        if sys.platform.startswith("win"):
            webview.start(gui="edgechromium")
        else:
            webview.start()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"! Okno aplikace nelze spustit ({e})")
        return False


def open_app_window(url):
    cands = []
    if sys.platform.startswith("win"):
        for env in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
            base = os.environ.get(env)
            if base:
                cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                          Path(base) / "Google/Chrome/Application/chrome.exe"]
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        w = shutil.which(name)
        if w:
            cands.append(Path(w))
    for exe in cands:
        if exe.is_file():
            try:
                subprocess.Popen([str(exe), f"--app={url}", "--window-size=1500,900"], **NOWIN)
                return
            except OSError:
                continue
    webbrowser.open(url)


def watchdog(sess, stop):
    """Quit when the browser window is gone (page said bye, or stopped sending heartbeats)."""
    while not stop.wait(1.0):
        now = time.time()
        if sess.bye_at is not None and now - sess.bye_at > 5:
            break
        if now - sess.last_ping > 150:
            break
    stop.set()


# ---------------------------------------------------------------- helpers

def parse_args(argv):
    opts = {"folder": None, "flags": set(), "skip": None, "find": None, "debug": None}
    for a in argv:
        if a.startswith("--skip="):
            opts["skip"] = [x.strip() for x in a[7:].split(",") if x.strip()]
        elif a.startswith("--find="):
            opts["find"] = a[7:]
        elif a.startswith("--debug="):
            opts["debug"] = a[8:]
        elif a.startswith("--episodes="):
            print("(--episodes se už nepoužívá: epizody a sezóny jsou pevně dané – sezóna 1 = epizody 1–4, sezóna 2 = 5–8)")
        elif a.startswith("--"):
            opts["flags"].add(a)
        elif opts["folder"] is None:
            opts["folder"] = a
    return opts


def choose_project_dir(cfg, explicit):
    """explicit folder > remembered folder > folder next to the exe. Returns (path or None, message)."""
    if explicit:
        ok, msg = check_project_dir(explicit)
        return (explicit, "") if ok else (None, msg)
    saved = cfg.get("project_dir", "")
    if saved:
        ok, msg = check_project_dir(saved)
        if ok:
            return saved, ""
        note = f"Uložená složka už není použitelná ({msg})"
    else:
        note = ""
    here = app_dir()
    ok, _ = check_project_dir(here)
    if ok:
        return str(here), note
    return None, note


def print_summary(app, only_todo):
    rows = app.project.rows()
    for r in rows:
        if only_todo and r.todo == 0 and r.corr >= r.total:
            continue
        print(f"P {r.done / r.total * 100:5.1f}%  K {r.corr / r.total * 100:5.1f}%  {r.done:>5}/{r.total:<5}  {r.name}")
    s_done, s_total, s_corr, pct, cpct = totals_of(rows)
    print(f"\nPREKLAD:   {s_done}/{s_total} ({pct:.1f} %), hotových souborů: {sum(1 for r in rows if r.todo == 0)}/{len(rows)}")
    print(f"KOREKTURA: {s_corr}/{s_total} ({cpct:.1f} %), hotových souborů: {sum(1 for r in rows if r.corr >= r.total)}/{len(rows)}")


def print_find(app, name):
    rel = next((r for r in app.project.files if r.lower() == name.lower() or Path(r).name.lower() == name.lower()), None)
    if rel is None:
        print(f"Soubor nenalezen: {name}")
        return
    pend = [e for e in app.project.entries(rel) if e.pending]
    print(f"--- {rel} ---")
    for e in pend:
        print(f"{e.src_line:>6}  orig:    {e.src_raw}\n{e.line:>6}  preklad: {e.cur_raw}   [{e.category}]\n")
    print(f"Celkem: {len(pend)}")


def cli_publish(app):
    """Terminal publish: show the preview, then require the typed word PUBLISH."""
    try:
        info = app.publish_plan()
    except AppError as e:
        print(f"! {e}")
        return 1
    print("\nNÁHLED PUBLIKOVÁNÍ")
    print(f"  Repozitář : {info['repo_path']}  ({info['remote'] or info.get('url') or '?'})")
    print(f"  Větev     : {info['branch'] or '(výchozí po naklonování)'}   upstream: {info['upstream'] or '-'}")
    print(f"  Soubor    : {info['target']}")
    print(f"  Nově      : {info['new']}\n  Dosud     : {info['current']}")
    for c in info["commands"]:
        print(f"    $ {c}")
    for w in info["warnings"]:
        print(f"  ! {w}")
    for b in info["blockers"]:
        print(f"  X {b}")
    if info["blockers"]:
        return 1
    if not sys.stdin or not sys.stdin.isatty():
        print("\nPublikování vyžaduje potvrzení v terminálu (nebo tlačítko Publikovat v okně). Nic se neposlalo.")
        return 1
    if input("\nPro odeslání napiš PUBLISH (cokoli jiného = zrušit): ").strip() != "PUBLISH":
        print("Zrušeno, nic se neposlalo.")
        return 0
    try:
        res = app.publish_confirm(info["token"], info["branch"] or "*clone*")
    except AppError as e:
        print(f"! {e}")
        return 1
    print(res["message"])
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = parse_args(argv)
    flags = opts["flags"]
    cfg = Config().load()
    if cfg.load_error:
        print("! " + cfg.load_error)
    if opts["skip"] is not None:
        cfg.set("skip_files", [s.lower() for s in opts["skip"]])
    app = App(cfg)
    atexit.register(app.close)
    console = bool(opts["folder"]) and "--edit" not in flags or "--nogui" in flags or opts["find"] or opts["debug"]
    path, note = choose_project_dir(cfg, opts["folder"])
    if note:
        app.notices.append(note)
        print(f"! {note}")
    if path:
        try:
            rep = app.open_project(path)
            print(f"Projekt: {path}  ({len(app.project.files)} souborů, {rep.seconds:.1f} s)")
        except AppError as e:
            print(f"! {e}")
            app.notices.append(str(e))
            path = None
    if console:
        if not path:
            print("! Nebyla nalezena použitelná složka s překladem. Zadej ji jako parametr.")
            return 2
        if opts["find"]:
            print_find(app, opts["find"])
            return 0
        if opts["debug"]:
            print_find(app, opts["debug"])
            return 0
        print_summary(app, "--todo" in flags)
        if "--export" in flags:
            print(f"progress.json: {app.data_dir / 'progress.json'}")
        if "--publish" in flags:
            return cli_publish(app)
        return 0

    try:
        server, sess, url = start_server(app, pick_folder)
    except OSError as e:
        print(f"! Nelze spustit okno ({e}).")
        return 1
    print(f"\nOkno aplikace: {url}")
    shown = False
    if "--browser" not in flags:
        shown = run_desktop(url)
    if not shown:
        print("Otevírám v prohlížeči. Program skončí po zavření okna (nebo Enter).")
        stop = threading.Event()
        open_app_window(url)
        threading.Thread(target=watchdog, args=(sess, stop), daemon=True).start()

        def wait_enter():
            try:
                input()
            except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
                return
            stop.set()
        threading.Thread(target=wait_enter, daemon=True).start()
        try:
            while not stop.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
    server.shutdown()
    return 0


def show_fatal(message):
    """The exe has no console: show a crash in a message box (Windows) so it is never silent."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "BaDIK Translation Manager – chyba", 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    print(message, file=sys.stderr)


def run():
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log_exception()
        show_fatal(f"Program skončil chybou:\n{exc}\n\nPodrobnosti jsou v souboru error.log ve složce "
                   f"{config_dir()}.")
        sys.exit(1)
