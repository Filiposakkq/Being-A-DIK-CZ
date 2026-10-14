"""Website tests.

* The two *Rules* tests always run: the website's fallback season table must equal the manager's
  season model, and the browser-test fixtures must satisfy the exporter's own validation.
* tests/web/*.test.html are real browser tests (progress model + page rendering at desktop and
  phone widths). Open them through any static server (`py -m http.server` in the repo root, then
  /tests/web/model.test.html and /site.test.html); each page prints "N passed, 0 failed".
  They can also be run headless by this module when PREHLED_BROWSER_TESTS=1 and a Chromium-based
  browser (Edge / Chrome) is installed; the pages report their result in <div id="result">.
"""
import functools
import http.server
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def find_browser():
    cands = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
        base = os.environ.get(env)
        if base:
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        w = shutil.which(n)
        if w:
            cands.append(Path(w))
    return next((c for c in cands if c.is_file()), None)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


@unittest.skipUnless(os.environ.get("PREHLED_BROWSER_TESTS") == "1" and find_browser(),
                     "set PREHLED_BROWSER_TESTS=1 with Edge/Chrome installed to run the HTML tests headless")
class WebsiteBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietHandler, directory=str(REPO))
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_page(self, name):
        prof = tempfile.mkdtemp(prefix="prehled-browser-")
        self.addCleanup(shutil.rmtree, prof, True)
        r = subprocess.run([str(find_browser()), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                            f"--user-data-dir={prof}", "--virtual-time-budget=30000", "--dump-dom",
                            f"http://127.0.0.1:{self.port}/tests/web/{name}"],
                           capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        dom = r.stdout
        m = re.search(r'<div id="result" data-pass="(\d+)" data-fail="(\d+)"', dom)
        self.assertIsNotNone(m, "test page did not report a result:\n" + dom[-1500:] + r.stderr[-500:])
        fails = re.findall(r"<li[^>]*>(FAIL[^<]*)</li>", dom)
        self.assertEqual(int(m.group(2)), 0, "\n".join(fails))
        self.assertGreater(int(m.group(1)), 5)

    def test_progress_model(self):
        self.run_page("model.test.html")

    def test_site_rendering(self):
        self.run_page("site.test.html")


class WebsiteRulesTests(unittest.TestCase):
    def test_fallback_season_table_matches_the_manager(self):
        from prehled.seasons import SEASONS
        js = (REPO / "web" / "progress-model.js").read_text(encoding="utf-8")
        m = re.search(r"FALLBACK_SEASONS = (\{[^;]*\});", js)
        table = {int(k): [int(x) for x in v.split(",") if x.strip()] for k, v in re.findall(r"(\d+): \[([^\]]*)\]", m.group(1))}
        self.assertEqual(table, {s["n"]: list(s["episodes"]) for s in SEASONS})
        planned = re.search(r"PLANNED_SEASONS = \[([^\]]*)\]", js).group(1)
        self.assertEqual([int(x) for x in planned.split(",")], [s["n"] for s in SEASONS if s["status"] == "planned"])
    def test_episode_statuses_match_between_manager_and_website(self):
        from prehled.store import EP_STATES
        js = (REPO / "web" / "progress-model.js").read_text(encoding="utf-8")
        listed = re.search(r"const STATUSES = \[([^\]]*)\]", js).group(1)
        self.assertEqual(re.findall(r'"(\w+)"', listed), [k for k, _l in EP_STATES])
        app = (REPO / "web" / "app.js").read_text(encoding="utf-8")
        for key, _label in EP_STATES:
            self.assertRegex(app, rf"\b{key}: \"", key)             # a label exists in both languages

    def test_fixtures_agree_with_the_exporter_rules(self):
        import json
        from prehled import export
        for name in ("v2-real-copy.json", "v2-synthetic-estimate.json"):
            data = json.loads((REPO / "tests/web/fixtures" / name).read_text(encoding="utf-8"))
            data.pop("_fixture_note", None)
            self.assertEqual(export.validate_progress(data), [], name)



if __name__ == "__main__":
    unittest.main()
