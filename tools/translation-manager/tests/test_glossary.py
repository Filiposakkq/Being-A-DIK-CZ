"""Glossary of speaker names (slovnik.csv)."""
import http.client
import json

from helpers import TempCase, dialog

from prehled import server
from prehled.app import AppError
from prehled.store import Store


class GlossaryTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "Hello there.", "Ahoj.", 1)
                   + dialog("a2", "de", "Yo.", "Čau.", 2)
                   + dialog("a3", "mc happy", "Great!", "Skvělé!", 3)
                   + dialog("a4", "de", "Bye.", "Měj se.", 4)
                   + dialog("a5", "ji", "Hm.", "Hm.", 5))
        self.write("o.rpy", 'translate czech strings:\n\n    old "Start"\n    new "Začít"\n')
        self.app = self.new_app()

    def by_code(self, payload):
        return {i["code"]: i for i in payload["items"]}

    def test_detects_speakers_with_counts_and_ignores_attributes_and_strings(self):
        g = self.app.glossary_payload()
        items = self.by_code(g)
        self.assertEqual(set(items), {"mc", "de", "ji"})                    # 'mc happy' counts as 'mc'
        self.assertEqual((items["mc"]["count"], items["de"]["count"], items["ji"]["count"]), (2, 2, 1))
        self.assertTrue(items["mc"]["example"])
        self.assertEqual(g["unnamed"], 3)
        self.assertEqual([i["code"] for i in g["items"]][0] in ("mc", "de"), True)   # most frequent first

    def test_nothing_is_invented(self):
        self.assertEqual(self.app.glossary_payload()["names"], {})
        self.assertFalse((self.app.data_dir / "slovnik.csv").exists())

    def test_set_names_persist_in_the_csv_and_come_back(self):
        r = self.app.glossary_set([{"code": "mc", "name": "Hlavní hrdina"}, {"code": "de", "name": "Dee Test", "note": "kamarád"}])
        self.assertEqual(r["names"], {"mc": "Hlavní hrdina", "de": "Dee Test"})
        self.assertEqual(r["unnamed"], 1)
        raw = (self.app.data_dir / "slovnik.csv").read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(raw[0], "kod;jmeno;typ;poznamka")
        self.assertIn("de;Dee Test;speaker;kamarád", raw)
        again = self.new_app()
        self.assertEqual(again.glossary_payload()["names"]["de"], "Dee Test")
        self.assertEqual(Store(self.app.data_dir).load().glossary["mc"]["n"], "Hlavní hrdina")

    def test_empty_entry_removes_it_and_undo_restores(self):
        self.app.glossary_set([{"code": "mc", "name": "Hrdina"}])
        self.app.glossary_set([{"code": "mc", "name": "", "note": ""}])
        self.assertNotIn("mc", self.app.store.glossary)
        self.app.undo()
        self.assertEqual(self.app.store.glossary["mc"]["n"], "Hrdina")

    def test_terms_for_later_are_kept_even_when_not_in_the_project(self):
        r = self.app.glossary_set([{"code": "Delta Iota Kappa", "name": "Bratrstvo DIK", "type": "term", "note": "spolek"}])
        row = self.by_code(r)["Delta Iota Kappa"]
        self.assertEqual((row["type"], row["in_project"], row["count"]), ("term", False, 0))
        self.assertNotIn("Delta Iota Kappa", r["names"])                    # only speakers feed the speaker display
        self.assertEqual(r["unnamed"], 3)                                  # terms never count as unnamed speakers

    def test_validation_of_input(self):
        for bad in ({"code": ""}, {"code": "x" * 61}, {"code": "a\nb"}, {"code": "mc", "type": "weird"},
                    {"code": "mc", "name": "x" * 201}, {"code": "mc", "note": "x" * 501}):
            with self.assertRaises(AppError, msg=str(bad)):
                self.app.glossary_set([bad])
        self.assertEqual(self.app.store.glossary, {})

    def test_semicolons_and_unicode_survive_the_csv(self):
        self.app.glossary_set([{"code": "mc", "name": "Jan; „Honza“ Novák", "note": "řádek 1\nřádek 2"}])
        self.assertEqual(Store(self.app.data_dir).load().glossary["mc"],
                         {"n": "Jan; „Honza“ Novák", "t": "speaker", "c": "řádek 1\nřádek 2"})

    def test_delete(self):
        self.app.glossary_set([{"code": "mc", "name": "A"}, {"code": "de", "name": "B"}])
        r = self.app.glossary_delete(["mc"])
        self.assertEqual(r["names"], {"de": "B"})

    def test_existing_installations_without_the_file_still_load(self):
        self.assertEqual(Store(self.app.data_dir).load().glossary, {})

    def test_http_api(self):
        srv, sess, _ = server.start_server(self.app)
        self.addCleanup(srv.shutdown)

        def call(method, path, body=None, token=True):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request(method, path, json.dumps(body) if body is not None else None,
                      {"X-Token": sess.token} if token else {})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        st, r = call("GET", "/api/glossary")
        self.assertEqual((st, len(r["items"])), (200, 3))
        self.assertEqual(call("POST", "/api/glossary/set", {"items": [{"code": "mc", "name": "X"}]}, token=False)[0], 403)
        st, r = call("POST", "/api/glossary/set", {"items": [{"code": "mc", "name": "Hrdina"}]})
        self.assertEqual(r["names"], {"mc": "Hrdina"})
        self.assertEqual(call("POST", "/api/glossary/set", {"items": [{"code": ""}]})[0], 400)
        st, r = call("POST", "/api/glossary/delete", {"codes": ["mc"]})
        self.assertEqual(r["names"], {})
