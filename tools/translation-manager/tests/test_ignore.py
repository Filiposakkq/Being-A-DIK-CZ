"""Ignoring validator findings on single lines: hidden everywhere, listed, reversible, expires when the text changes."""
import unittest

from helpers import TempCase, dialog

from prehled.app import App
from prehled.config import Config


class IgnoreTests(TempCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("script.rpy", dialog("a1", "mc", "Hello.", "Ahoj [jmeno].", 5)
                               + dialog("a2", "mc", "Fine.", "Dobře.", 9))
        self.app = self.new_app()

    def findings(self, **kw):
        return self.app.validation_list(**kw)["items"]

    def first(self):
        return next(i for i in self.findings() if i["code"] == "variable-unknown")

    def ignore(self, note="", on=True):
        f = self.first() if on else None
        return self.app.ignore_set([{"file": "script.rpy", "line": f["line"], "code": "variable-unknown"}], on, note)

    def test_an_ignored_finding_disappears_from_every_count_and_list(self):
        self.assertEqual(self.app.overview()["validation"]["error"], 1)
        self.assertEqual(self.app.entries(issues="error")["total"], 1)
        self.assertEqual(self.app.overview()["worst_files"][0]["name"], "script.rpy")
        res = self.ignore("záměr, proměnná existuje v jiné větvi")
        self.assertEqual(res["changed"], 1)
        v = self.app.overview()
        self.assertEqual((v["validation"]["error"], v["validation"]["ignored"]), (0, 1))
        self.assertEqual(self.app.entries(issues="error")["total"], 0)
        self.assertEqual(v["worst_files"], [])
        self.assertEqual([i["code"] for i in self.findings()], [])
        self.assertEqual(self.app.files_payload()[0]["errors"], 0)

    def test_ignored_findings_can_be_listed_and_restored(self):
        self.ignore("poznámka")
        only = self.findings(ignored="only")
        self.assertEqual([(i["code"], i["ignored"], i["ignore_note"]) for i in only], [("variable-unknown", True, "poznámka")])
        self.assertEqual([i["ignored"] for i in self.findings(ignored="all")], [True])
        lst = self.app.ignored_list()
        self.assertEqual([(r["state"], r["note"]) for r in lst["items"]], [("active", "poznámka")])
        self.assertIn("Ahoj", lst["items"][0]["target"])
        self.assertTrue(lst["items"][0]["message"])
        self.app.ignore_set([{"file": "script.rpy", "line": lst["items"][0]["line"], "code": "variable-unknown"}], False)
        self.assertEqual(self.app.overview()["validation"]["error"], 1)
        self.assertEqual(self.app.ignored_list()["items"], [])

    def test_detail_shows_ignored_findings_with_a_flag(self):
        self.ignore()
        d = self.app.entry_detail("script.rpy", self.app.ignored_list()["items"][0]["line"])
        self.assertEqual([(i["code"], i["ignored"]) for i in d["issues"]], [("variable-unknown", True)])

    def test_it_survives_a_restart_and_follows_the_line(self):
        self.ignore("trvale")
        app2 = self.new_app()
        self.assertEqual(app2.overview()["validation"]["error"], 0)
        self.assertEqual(app2.ignored_list()["items"][0]["note"], "trvale")
        self.assertTrue((self.root / "_progress_data" / "ignorovano.csv").is_file())

    def test_changing_the_translation_brings_the_finding_back(self):
        self.ignore()
        e = self.app.project.entries("script.rpy")[0]
        self.app.entry_save("script.rpy", e.line, "Čau [jmeno].")
        self.assertEqual(self.app.overview()["validation"]["error"], 1)               # shown again
        self.assertEqual(self.app.ignored_list()["items"][0]["state"], "expired")
        self.assertEqual(self.app.overview()["validation"]["ignored"], 0)

    def test_a_fixed_finding_is_reported_as_resolved(self):
        self.ignore()
        e = self.app.project.entries("script.rpy")[0]
        self.app.entry_save("script.rpy", e.line, "Ahoj.")                    # the text changed AND is fine now
        self.assertEqual(self.app.ignored_list()["items"][0]["state"], "expired")

    def test_unknown_findings_and_files_are_skipped(self):
        line = self.first()["line"]
        res = self.app.ignore_set([{"file": "script.rpy", "line": line, "code": "nope"},
                                   {"file": "missing.rpy", "line": 1, "code": "x"}], True)
        self.assertEqual((res["changed"], len(res["skipped"])), (0, 2))

    def test_it_is_one_undo_step(self):
        self.ignore()
        self.assertEqual(self.app.overview()["validation"]["error"], 0)
        self.app.undo()
        self.assertEqual(self.app.overview()["validation"]["error"], 1)

    def test_a_removed_line_leaves_a_gone_record_that_can_still_be_cleared(self):
        self.ignore()
        key = self.app.ignored_list()["items"][0]["key"]
        self.path.write_text(dialog("a2", "mc", "Fine.", "Dobře.", 9), encoding="utf-8")
        self.app.refresh(force=True)
        rec = self.app.ignored_list()["items"][0]
        self.assertEqual(rec["state"], "gone")
        self.app.ignore_set([{"file": "script.rpy", "key": key, "code": "variable-unknown"}], False)
        self.assertEqual(self.app.ignored_list()["items"], [])


class IgnoreOverHttpTests(TempCase):
    def test_routes(self):
        import http.client
        import json
        from prehled import server
        self.write("script.rpy", dialog("a1", "mc", "Hello.", "Ahoj [jmeno].", 5))
        app = self.new_app()
        srv, sess, _url = server.start_server(app)
        host, port = srv.server_address

        def call(method, path, body=None):
            c = http.client.HTTPConnection(host, port, timeout=10)
            c.request(method, path, json.dumps(body) if body is not None else None,
                      {"X-Token": sess.token, "Content-Type": "application/json"})
            r = c.getresponse()
            out = json.loads(r.read().decode("utf-8"))
            c.close()
            return out
        try:
            f = call("GET", "/api/validation")["items"][0]
            res = call("POST", "/api/ignore/set", {"items": [{"file": f["file"], "line": f["line"], "code": f["code"]}], "note": "x"})
            self.assertTrue(res["ok"])
            self.assertEqual(call("GET", "/api/validation")["total"], 0)
            self.assertEqual(call("GET", "/api/validation?ignored=only")["total"], 1)
            self.assertEqual(call("GET", "/api/ignore/list")["counts"]["active"], 1)
        finally:
            srv.shutdown()
            srv.server_close()
            app.close()


if __name__ == "__main__":
    unittest.main()
