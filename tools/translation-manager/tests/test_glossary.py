"""Glossary of speaker names (slovnik.csv)."""
import http.client
import json
from pathlib import Path

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


CHARACTERS = '''define mc = DynamicCharacter("name", color="#ffaf05")

define js = Character("Josy", color="#ff1c63")
define de = Character("Derek", color = "#0066ff")
define bu = Character('Professor Burke', color="bc9360")
define kid = Character("Kid")
define esc = Character("Say \\"hi\\"")
define empty = Character("")
# Decompiled by unrpyc: https://github.com/CensoredUsername/unrpyc
define de = Character("Duplicate Derek")
'''


class GlossaryImportTests(TempCase):
    def setUp(self):
        super().setUp()
        # real layout: <game>/game/characters.rpy and <game>/game/tl/czech/*.rpy
        self.game = self.tmp / "game"
        self.root = self.game / "tl" / "czech"
        self.root.mkdir(parents=True)
        self.write("a.rpy", dialog("a1", "mc", "Hi.", "Ahoj.") + dialog("a2", "de", "Yo.", "Čau.") + dialog("a3", "xx", "Hey.", "Hej."))
        (self.game / "characters.rpy").write_text(CHARACTERS, encoding="utf-8")
        self.app = self.new_app()

    def test_preview_parses_names_and_states_and_writes_nothing(self):
        pv = self.app.glossary_import_preview()
        self.assertEqual([str(Path(f).resolve()) for f in pv["files"]],
                         [str((self.game / "characters.rpy").resolve())])      # found automatically
        items = {i["code"]: i for i in pv["items"]}
        self.assertEqual(items["js"]["name"], "Josy")
        self.assertEqual(items["de"]["name"], "Duplicate Derek")                # Ren'Py: the last definition wins
        self.assertEqual(pv["duplicates"], [{"code": "de", "names": ["Derek", "Duplicate Derek"], "used": "Duplicate Derek"}])
        self.assertIn("víckrát", items["de"]["note"])
        self.assertEqual(items["bu"]["name"], "Professor Burke")                # single quotes
        self.assertEqual(items["kid"]["name"], "Kid")
        self.assertEqual(items["mc"]["state"], "dynamic")
        self.assertNotIn("empty", items)                                        # empty names are skipped
        self.assertEqual(items["esc"]["name"], 'Say "hi"')
        self.assertEqual(items["js"]["state"], "new")
        self.assertEqual(pv["missing"], ["xx"])                                 # used in the translation, not defined
        self.assertFalse((self.app.data_dir / "slovnik.csv").exists())

    def test_apply_stores_names_keeps_notes_and_is_undoable(self):
        self.app.glossary_set([{"code": "de", "name": "", "note": "kamarád"}])
        self.app.glossary_import_apply([{"code": "de", "name": "Derek"}, {"code": "js", "name": "Josy"}])
        g = self.app.store.glossary
        self.assertEqual((g["de"]["n"], g["de"]["c"], g["js"]["n"]), ("Derek", "kamarád", "Josy"))
        self.app.undo()
        self.assertNotIn("js", self.app.store.glossary)

    def test_existing_manual_name_is_a_conflict_not_overwritten_by_preview(self):
        self.app.glossary_set([{"code": "de", "name": "Dereček"}])
        items = {i["code"]: i for i in self.app.glossary_import_preview()["items"]}
        self.assertEqual((items["de"]["state"], items["de"]["current"]), ("conflict", "Dereček"))
        self.assertEqual(self.app.store.glossary["de"]["n"], "Dereček")
        self.app.glossary_set([{"code": "js", "name": "Josy"}])
        self.assertEqual({i["code"]: i for i in self.app.glossary_import_preview()["items"]}["js"]["state"], "same")

    def test_bad_paths_are_refused_with_a_message(self):
        with self.assertRaises(AppError):
            self.app.glossary_import_preview(str(self.game / "nope.rpy"))
        other = self.tmp / "notes.txt"
        other.write_text("define a = Character('A')", encoding="utf-8")
        with self.assertRaises(AppError):
            self.app.glossary_import_preview(str(other))
        big = self.tmp / "big.rpy"
        big.write_bytes(b"#" * (3 * 1024 * 1024))
        with self.assertRaises(AppError):
            self.app.glossary_import_preview(str(big))

    def test_not_found_automatically_gives_a_hint_not_an_error(self):
        (self.game / "characters.rpy").unlink()
        pv = self.app.glossary_import_preview()
        self.assertEqual(pv["items"], [])
        self.assertIn("nebyly nalezeny", pv["message"])

    def test_http_api(self):
        srv, sess, _ = server.start_server(self.app)
        self.addCleanup(srv.shutdown)

        def post(path, body):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("POST", path, json.dumps(body), {"X-Token": sess.token})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        st, r = post("/api/glossary/import-preview", {"path": ""})
        self.assertEqual(st, 200)
        self.assertTrue(any(i["code"] == "js" for i in r["items"]))
        st, r = post("/api/glossary/import-apply", {"items": [{"code": "js", "name": "Josy"}]})
        self.assertEqual(r["names"], {"js": "Josy"})
        self.assertEqual(post("/api/glossary/import-preview", {"path": "C:\\nope\\x.rpy"})[0], 400)


SEASON2 = '''define vi = Character("Vinny", color="#FF9C43")
define js = Character("Josephine", color="#ff1c63")
define bd = Character("Bardtender", color="#33FF11")
define bd = Character("Buddy", color="#29662e")
'''


class GlossaryMultiFileTests(TempCase):
    def setUp(self):
        super().setUp()
        self.game = self.tmp / "game"
        self.root = self.game / "tl" / "czech"
        self.root.mkdir(parents=True)
        (self.game / "season2" / "scripts").mkdir(parents=True)
        (self.game / "characters.rpy").write_text('define js = Character("Josy")\ndefine my = Character("Maya")\n', encoding="utf-8")
        (self.game / "season2" / "scripts" / "characters_season2.rpy").write_text(SEASON2, encoding="utf-8")
        (self.game / "tl" / "czech" / "characters_fake.rpy").write_text('define zz = Character("In translation folder")\n', encoding="utf-8")
        self.write("a.rpy", dialog("a1", "vi", "Hi.", "Ahoj.") + dialog("a2", "bd", "Yo.", "Čau.") + dialog("a3", "qq", "Hey.", "Hej."))
        self.app = self.new_app()

    def test_all_character_files_are_found_in_load_order_but_not_the_translation_folder(self):
        files = [p.name for p in self.app.find_characters_files()]
        self.assertEqual(files, ["characters.rpy", "characters_season2.rpy"])

    def test_names_from_both_files_are_merged_and_later_files_win(self):
        pv = self.app.glossary_import_preview()
        items = {i["code"]: i for i in pv["items"]}
        self.assertEqual((items["my"]["name"], items["vi"]["name"]), ("Maya", "Vinny"))
        self.assertEqual(items["js"]["name"], "Josephine")                    # season 2 redefines it
        self.assertEqual(items["bd"]["name"], "Buddy")                        # defined twice in one file: last wins
        self.assertNotIn("zz", items)
        self.assertIn("season2", items["vi"]["source"])
        self.assertEqual(items["my"]["source"], "characters.rpy")
        dup = {d["code"]: d for d in pv["duplicates"]}
        self.assertEqual(dup["bd"]["names"], ["Bardtender", "Buddy"])
        self.assertEqual(dup["js"]["names"], ["Josy", "Josephine"])
        self.assertEqual(pv["missing"], ["qq"])

    def test_a_folder_path_reads_every_character_file_below_it(self):
        pv = self.app.glossary_import_preview(str(self.game))
        self.assertEqual(len(pv["files"]), 2)
        self.assertNotIn("zz", {i["code"] for i in pv["items"]})

    def test_a_single_file_path_reads_only_that_file(self):
        pv = self.app.glossary_import_preview(str(self.game / "characters.rpy"))
        self.assertEqual({i["code"] for i in pv["items"]}, {"js", "my"})

    def test_rows_can_be_searched_by_the_speakers_full_name(self):
        self.app.glossary_set([{"code": "vi", "name": "Vinny Testovič"}])
        r = self.app.entries(status="all", q="testovič")
        self.assertEqual([i["who"] for i in r["items"]], ["vi"])


class ScreenKeywordTests(TempCase):
    def test_screen_statements_are_not_listed_as_speakers(self):
        block = "translate czech {id}:\n\n    # {kw} \"A\"\n    {kw} \"B\"\n\n"
        self.write("s.rpy", block.format(id="x", kw="text") + block.format(id="y", kw="timer") + dialog("a1", "mc", "Hi.", "Ahoj."))
        app = self.new_app()
        self.assertEqual({i["code"] for i in app.glossary_payload()["items"]}, {"mc"})
