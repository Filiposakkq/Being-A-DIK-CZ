"""Start the app on a synthetic project and open it with ?selftest=1, so the UI self-test (prehled/ui/selftest.js) runs in a
real browser. The page ends with a PASS / FAIL panel and a window title "SELFTEST PASS (n)" / "SELFTEST FAIL (n)".

    py tests\\ui\\serve_selftest.py            starts the server, opens your default browser, waits (Ctrl+C or close the tab to stop)
    py tests\\ui\\serve_selftest.py --no-open  only prints the address

The project lives in a temp folder named ".badik-selftest" – the only kind of project in which the self-test also writes
(saves a translation and undoes it). Your real project is never touched; settings go to a temp config folder.
"""
import os
import shutil
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

SCRIPT = '''# game/script.rpy:10
translate czech a1:

    # mc happy "Hello there, [name]."
    mc happy "Ahoj tam, [name]."

# game/script.rpy:20
translate czech a2:

    # mc "Take the Dik Coins."
    mc "Vezmi si peníze."

# game/script.rpy:30
translate czech a3:

    # de "Hello [name]."
    de "Ahoj [jmeno]."

# game/script.rpy:40
translate czech a4:

    # de "Hmm..."
    de "Hmm..."

# game/script.rpy:50
translate czech a5:

    # mc "Where are you going today?"
    mc "Where are you going today?"
'''
STRINGS = '''translate czech strings:

    # game/script.rpy:60
    old "Start"
    new "Začít"

    # game/script.rpy:61
    old "Quit"
    new "Quit"
'''


def make_project():
    """Create the synthetic project; returns the folder to open (…/.badik-selftest/game/tl/czech)."""
    base = Path(tempfile.mkdtemp(prefix="badik-")) / ".badik-selftest"
    proj = base / "game" / "tl" / "czech"
    proj.mkdir(parents=True)
    (base / "game" / "script.rpy").write_text("\n".join(f"label line_{i}:" for i in range(1, 80)), encoding="utf-8")
    (proj / "script.rpy").write_text(SCRIPT, encoding="utf-8")
    (proj / "options.rpy").write_text(STRINGS, encoding="utf-8")
    return proj


def main():
    cfg = tempfile.mkdtemp(prefix="badik-cfg-")
    os.environ["PREHLED_CONFIG_DIR"] = cfg
    from prehled import server
    from prehled.app import App
    from prehled.config import Config

    proj = make_project()
    app = App(Config().load())
    app.open_project(proj)
    app.glossary_set([{"code": "Dik Coins", "name": "dikmince", "type": "term"}])
    srv, _sess, url = server.start_server(app)
    url += "?selftest=1"
    print("UI self-test:", url, flush=True)
    if "--no-open" not in sys.argv:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        app.close()
        shutil.rmtree(proj.parents[2].parent, ignore_errors=True)
        shutil.rmtree(cfg, ignore_errors=True)


if __name__ == "__main__":
    main()
