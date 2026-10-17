"""Texts that Ren'Py's generator does not extract (show text, input prompts, titles, dialogue without a block)."""
import http.client
import json
import unittest

from helpers import TempCase
from prehled import missed, server
from prehled.app import AppError

SCRIPT = '''label start:
    show text "{i}Mini-games are optional.\\nYou can skip them.{/i}"
    $ renpy.pause()
    hide text
    mc "Hello there, friend."
    mc "A line the generator forgot."
    $ player = renpy.input("What is your name?", length=15)
    $ episode_title_name = "Maggot Brothers"
    $ image_name = "bg/room.png"
    $ speed = 12
    menu:
        "Play mini-games":
            pass
        "Skip":
            pass

screen hud():
    text "Money" size 20
    $ tip = "Click to continue"

image eileen happy:
    "eileen_happy.png"
    "a blink"

define build.name = "MyGame"
define mc = Character("Mike", color="#fff")
'''

TRANSLATION = '''# game/script.rpy:5
translate czech start_1:

    # mc "Hello there, friend."
    mc "Hello there, friend."

translate czech strings:

    old "Skip"
    new "Skip"
'''


class MissedTests(TempCase):
    def setUp(self):
        super().setUp()
        self.game = self.tmp / "game"
        (self.game / "tl" / "czech").mkdir(parents=True)
        (self.game / "script.rpy").write_text(SCRIPT, encoding="utf-8")
        (self.game / "tl" / "czech" / "script.rpy").write_text(TRANSLATION, encoding="utf-8")
        self.tl = self.game / "tl" / "czech"

    def scan(self, **kw):
        strings, dialogue, places = missed.known_texts(self.tl)
        res = missed.find_missed(self.game, strings, dialogue, places, **kw)
        return {i["text"]: i for i in res["items"]}

    def test_known_texts_read_strings_dialogue_and_places(self):
        strings, dialogue, places = missed.known_texts(self.tl)
        self.assertEqual((strings, dialogue, places), ({"Skip"}, {"Hello there, friend."}, {("script.rpy", 5)}))

    def test_show_text_input_and_titles_are_found_as_likely(self):
        found = self.scan()
        for text in ("{i}Mini-games are optional.\\nYou can skip them.{/i}", "What is your name?", "Maggot Brothers"):
            self.assertEqual(found[text]["level"], "likely", text)
            self.assertEqual(found[text]["kind"], "text")
        self.assertEqual(found["Maggot Brothers"]["line"], 8)

    def test_dialogue_without_a_block_is_found_by_its_place(self):
        found = self.scan()
        self.assertEqual((found["A line the generator forgot."]["kind"], found["A line the generator forgot."]["level"]), ("dialogue", "likely"))
        self.assertNotIn("Hello there, friend.", found)                     # it has a block at the place the translation points to

    def test_what_ren_py_handles_or_what_is_no_text_is_left_out(self):
        found = self.scan()
        for text in ("Play mini-games", "Skip", "Money", "bg/room.png", "eileen_happy.png", "a blink", "MyGame", "Mike", "12"):
            self.assertNotIn(text, found, text)

    def test_python_lines_inside_a_screen_still_count(self):
        self.assertEqual(self.scan()["Click to continue"]["level"], "likely")

    def test_a_string_already_in_the_table_is_not_reported(self):
        (self.tl / "script.rpy").write_text(TRANSLATION + '\n    old "Maggot Brothers"\n    new "Bratři"\n', encoding="utf-8")
        self.assertNotIn("Maggot Brothers", self.scan())

    def test_looks_like_text(self):
        for yes in ("Hello there", "Congratulations!", "Episode [n]", "{i}Hi you{/i}"):
            self.assertTrue(missed.looks_like_text(yes), yes)
        for no in ("#ff0000", "bg/room.png", "my_variable", "ab", "12", "button_idle", "x.rpy"):
            self.assertFalse(missed.looks_like_text(no), no)

    def test_write_strings_appends_once_and_skips_known(self):
        items = [{"text": "Maggot Brothers", "file": "script.rpy", "line": 8}, {"text": "Skip", "file": "script.rpy", "line": 12}]
        first = missed.write_strings(self.tl, "czech", items)
        self.assertEqual((first["added"], first["skipped"], first["files"]), (1, 1, {"extra_strings.rpy": 1}))
        text = (self.tl / missed.FILE_NAME).read_text(encoding="utf-8")                  # by default everything is in one tidy file
        self.assertIn('translate czech strings:\n\n    # game/script.rpy:8\n    old "Maggot Brothers"\n    new "Maggot Brothers"', text)
        self.assertEqual((self.tl / "script.rpy").read_text(encoding="utf-8"), TRANSLATION)       # the translation files stay as they were
        again = missed.write_strings(self.tl, "czech", items)
        self.assertEqual(again["added"], 0)
        self.assertEqual((self.tl / missed.FILE_NAME).read_text(encoding="utf-8"), text)

    def test_into_files_puts_a_text_into_the_translation_file_of_its_script(self):
        res = missed.write_strings(self.tl, "czech", [{"text": "Maggot Brothers", "file": "script.rpy", "line": 8}], into_files=True)
        self.assertEqual(res["files"], {"script.rpy": 1})
        text = (self.tl / "script.rpy").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(TRANSLATION.rstrip("\n")))
        self.assertIn('translate czech strings:\n\n    # game/script.rpy:8\n    old "Maggot Brothers"', text)
        self.assertFalse((self.tl / missed.FILE_NAME).exists())

    def test_texts_go_to_the_file_of_their_own_script_and_the_rest_to_the_extra_file(self):
        (self.game / "script2.rpy").write_text('label b:\n    show text "Second file text"\n', encoding="utf-8")
        (self.tl / "script2.rpy").write_text("translate czech strings:\n\n    old \"Zzz\"\n    new \"Zzz\"\n", encoding="utf-8")
        items = [{"text": "Second file text", "file": "script2.rpy", "line": 2}, {"text": "First file text", "file": "script.rpy", "line": 3},
                 {"text": "No translation file", "file": "other/none.rpy", "line": 1}, {"text": "Escape", "file": "../../outside.rpy", "line": 1}]
        res = missed.write_strings(self.tl, "czech", items, into_files=True)
        self.assertEqual(res["files"], {"script2.rpy": 1, "script.rpy": 1, "extra_strings.rpy": 2})
        self.assertIn('old "Second file text"', (self.tl / "script2.rpy").read_text(encoding="utf-8"))
        self.assertIn('old "Zzz"', (self.tl / "script2.rpy").read_text(encoding="utf-8"))          # what was there stays
        extra = (self.tl / missed.FILE_NAME).read_text(encoding="utf-8")
        self.assertIn('old "No translation file"', extra)
        self.assertIn('old "Escape"', extra)                                                      # a path outside the folder is never followed
        self.assertFalse((self.tl.parent.parent / "outside.rpy").exists())

    def test_the_line_endings_of_a_file_are_kept(self):
        path = self.tl / "script.rpy"
        path.write_bytes(TRANSLATION.replace("\n", "\r\n").encode("utf-8"))
        missed.write_strings(self.tl, "czech", [{"text": "Crlf text here", "file": "script.rpy", "line": 1}], into_files=True)
        raw = path.read_bytes()
        self.assertIn(b"old \"Crlf text here\"", raw)
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))

    def test_own_functions_make_their_texts_likely(self):
        (self.game / "extra.rpy").write_text('label x:\n    $ notify("Item added to the bag")\n    $ other("Not shown to anyone")\n', encoding="utf-8")
        self.assertEqual(self.scan()["Item added to the bag"]["level"], "maybe")
        strings, dialogue, places = missed.known_texts(self.tl)
        res = missed.find_missed(self.game, strings, dialogue, places, functions=["notify"])
        by = {i["text"]: i for i in res["items"]}
        self.assertEqual((by["Item added to the bag"]["level"], by["Not shown to anyone"]["level"]), ("likely", "maybe"))

    def test_ignored_texts_are_left_out(self):
        strings, dialogue, places = missed.known_texts(self.tl)
        res = missed.find_missed(self.game, strings, dialogue, places, ignored=["Maggot Brothers", "A line the generator forgot."])
        texts = {i["text"] for i in res["items"]}
        self.assertNotIn("Maggot Brothers", texts)
        self.assertNotIn("A line the generator forgot.", texts)
        self.assertIn("What is your name?", texts)

    def test_functions_called_again_and_again_with_a_text_are_suggested(self):
        lines = "label x:\n" + "".join(f'    $ popup("Something happened number {n}")\n' for n in range(4))
        lines += '    $ x.append("Some text appended")\n    $ raise ValueError("A problem with the data here")\n    $ rare("Only once is not a pattern")\n'
        (self.game / "popups.rpy").write_text(lines, encoding="utf-8")
        known = missed.known_strings(self.tl)
        names = {f["name"]: f for f in missed.suggest_functions(self.game, known)}
        self.assertEqual(names["popup"]["calls"], 4)
        for noise in ("ValueError", "rare", "x.append"):
            self.assertNotIn(noise, names)
        self.assertNotIn("popup", {f["name"] for f in missed.suggest_functions(self.game, known, functions=["popup"])})

    def test_settings_file_round_trip_and_damage(self):
        saved = missed.save_settings(self.tl, ["notify", "bad name", "ui.popup", "notify"], ["b", "a", "a"])
        self.assertEqual(saved, {"functions": ["notify", "ui.popup"], "ignored": ["a", "b"]})
        self.assertEqual(missed.load_settings(self.tl), saved)
        (self.tl / missed.SETTINGS_FILE).write_text("{not json", encoding="utf-8")
        self.assertEqual(missed.load_settings(self.tl), {"functions": [], "ignored": []})

    def test_a_script_with_a_space_in_its_name_is_matched_to_its_blocks(self):
        (self.game / "fight spirit.rpy").write_text('label a:\n    ds "hello again, friend."\n', encoding="utf-8")
        (self.tl / "fight spirit.rpy").write_text(
            '# game/fight spirit.rpy:2\ntranslate czech a_1:\n\n    # ds "hello again, friend."\n    ds "hello again, friend."\n', encoding="utf-8")
        self.assertNotIn("hello again, friend.", self.scan())

    def test_strings_in_a_list_or_a_python_block_are_not_dialogue(self):
        (self.game / "data.rpy").write_text('default sprites = [\n    "isa bet titsuck 6",\n    "isa bet titsuck 7"\n]\n'
                                            'init python:\n    names = [\n        "bg office day empty 1"\n    ]\n', encoding="utf-8")
        texts = self.scan()
        for t in ("isa bet titsuck 6", "isa bet titsuck 7", "bg office day empty 1"):
            self.assertNotEqual(texts.get(t, {}).get("kind"), "dialogue", t)                 # at most a weak guess, never a spoken line
            self.assertNotEqual(texts.get(t, {}).get("level"), "likely", t)


class MissedInTheAppTests(TempCase):
    def setUp(self):
        super().setUp()
        self.game = self.root.parent / "gamefolder" / "game"
        self.tl = self.game / "tl" / "czech"
        self.tl.mkdir(parents=True)
        (self.game / "script.rpy").write_text(SCRIPT, encoding="utf-8")
        (self.tl / "script.rpy").write_text(TRANSLATION, encoding="utf-8")
        self.app = self.new_app(open_root=False)
        self.app.open_project(self.tl)

    def test_scan_and_add(self):
        res = self.app.missed_scan()
        texts = {i["text"] for i in res["items"]}
        self.assertIn("Maggot Brothers", texts)
        self.assertTrue(res["folder"])
        before = self.app.overview()["totals"]["total"]
        out = self.app.missed_add([i for i in res["items"] if i["text"] in ("Maggot Brothers", "What is your name?")])
        self.assertEqual(out["added"], 2)
        self.assertEqual(self.app.overview()["totals"]["total"], before + 2)
        self.assertEqual({i["text"] for i in self.app.missed_scan()["items"]} & {"Maggot Brothers", "What is your name?"}, set())

    def test_settings_and_ignoring_in_the_app(self):
        self.app.missed_settings(["notify"])
        self.app.missed_ignore(["Maggot Brothers"])
        res = self.app.missed_scan()
        self.assertEqual(res["settings"], {"functions": ["notify"], "ignored": ["Maggot Brothers"]})
        self.assertNotIn("Maggot Brothers", {i["text"] for i in res["items"]})
        self.app.missed_ignore([], clear=True)
        self.assertIn("Maggot Brothers", {i["text"] for i in self.app.missed_scan()["items"]})
        self.assertEqual(self.app.missed_settings([])["functions"], [])
        with self.assertRaises(AppError):
            self.app.missed_ignore([])

    def test_function_suggestions_in_the_app(self):
        (self.game / "popups.rpy").write_text("label x:\n" + "".join(f'    $ popup("Something happened number {n}")\n' for n in range(3)), encoding="utf-8")
        self.assertEqual([f["name"] for f in self.app.missed_functions()["suggested"]], ["popup"])

    def test_http_api(self):
        srv, sess, _ = server.start_server(self.app)
        self.addCleanup(srv.shutdown)

        def call(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": sess.token})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        st, r = call("GET", "/api/missed")
        self.assertEqual(st, 200)
        self.assertTrue(any(i["text"] == "Maggot Brothers" for i in r["items"]))
        self.assertEqual(call("POST", "/api/missed/add", {"items": []})[0], 400)
        st, r = call("POST", "/api/missed/add", {"items": [i for i in r["items"] if i["text"] == "Maggot Brothers"]})
        self.assertEqual((st, r["added"]), (200, 1))
        self.assertEqual(call("POST", "/api/missed/settings", {"functions": ["notify"]})[1]["functions"], ["notify"])
        self.assertEqual(call("POST", "/api/missed/ignore", {"texts": ["What is your name?"]})[1]["ignored"], ["What is your name?"])
        self.assertEqual(call("GET", "/api/missed/functions")[0], 200)

    def test_nothing_chosen_is_an_error(self):
        with self.assertRaises(AppError):
            self.app.missed_add([])

    def test_without_scripts_there_is_a_hint(self):
        (self.game / "script.rpy").unlink()
        res = self.app.missed_scan()
        self.assertEqual(res["items"], [])
        self.assertIn("Skripty", str(res["message"]))


if __name__ == "__main__":
    unittest.main()
