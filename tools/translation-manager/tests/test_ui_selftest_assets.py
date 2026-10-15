"""The browser self-test (prehled/ui/selftest.js) needs its assets; these tests keep it from silently rotting."""
import http.client
import importlib.util
import unittest
from pathlib import Path

from helpers import TempCase

from prehled import server
from prehled.app import App
from prehled.config import Config

UI = Path(__file__).resolve().parent.parent / "prehled" / "ui"
SERVE = Path(__file__).resolve().parent / "ui" / "serve_selftest.py"


def load_serve_module():
    spec = importlib.util.spec_from_file_location("serve_selftest", SERVE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SelfTestAssets(TempCase):
    def test_synthetic_project_is_not_vacuous(self):
        proj = load_serve_module().make_project()
        try:
            self.assertIn(".badik-selftest", str(proj))
            app = App(Config().load())
            app.open_project(proj)
            ents = [e for rel in app.project.files for e in app.project.entries(rel)]
            self.assertTrue(any(e.unit == "dialogue" and not e.pending for e in ents), "needs a translated dialogue")
            self.assertTrue(any(e.unit == "string" for e in ents), "needs a strings pair")
            self.assertTrue(app.validation_list()["items"], "needs at least one validator finding")
            ctx = app.entry_context("script.rpy", next(e.line for e in app.project.entries("script.rpy") if e.ref))
            self.assertTrue(ctx["available"], "needs the game script next to the translation")
            app.close()
        finally:
            import shutil
            shutil.rmtree(proj.parents[2].parent, ignore_errors=True)

    def test_selftest_script_is_served_and_hooked_into_the_app(self):
        self.write("script.rpy", 'translate czech a1:\n\n    # mc "Hi"\n    mc "Ahoj"\n')
        app = self.new_app()
        srv, _sess, _url = server.start_server(app)
        try:
            host, port = srv.server_address
            c = http.client.HTTPConnection(host, port, timeout=10)
            c.request("GET", "/selftest.js")
            r = c.getresponse()
            body = r.read().decode("utf-8")
            self.assertEqual(r.status, 200)
            self.assertIn("SELFTEST", body)
        finally:
            srv.shutdown()
            srv.server_close()
            app.close()
        self.assertIn("selftest", (UI / "app.js").read_text(encoding="utf-8"))

    def test_selftest_only_writes_in_the_synthetic_project(self):
        js = (UI / "selftest.js").read_text(encoding="utf-8")
        self.assertIn(".badik-selftest", js)
        self.assertLess(js.index("const synthetic"), js.index("if (synthetic)"))


if __name__ == "__main__":
    unittest.main()
