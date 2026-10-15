"""Translation memory, similar lines, consistency of repeated originals, and the game's dialogue box metrics."""
import unittest

from helpers import TempCase, dialog

from prehled import memory
from prehled.app import App, AppError
from prehled.config import Config


class TokenTests(unittest.TestCase):
    def test_tokens_ignore_case_punctuation_tags_and_variables(self):
        self.assertEqual(memory.tokens("{i}Okay{/i}, [name]!"), ["okay"])
        self.assertEqual(memory.tokens("I don't know."), ["i", "don't", "know"])


class MemoryTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy",
                   dialog("a1", "mc", "Okay.", "Dobře.", 5) + dialog("a2", "de", "Okay!", "Fajn.", 9)
                   + dialog("a3", "mc", "OKAY", "Dobře!", 14) + dialog("a4", "mc", "Okay.", None, 20)
                   + dialog("a5", "mc", "I do not know what to say.", "Nevím, co říct.", 25)
                   + dialog("a6", "mc", "I really do not know what to say.", None, 30)
                   + dialog("a7", "mc", "Take the [item].", "Vezmi si [item].", 35)
                   + dialog("a8", "mc", "Take the key.", None, 40))
        self.app = self.new_app()

    def line(self, text):
        return next(e.line for e in self.app.project.entries("a.rpy") if e.source == text and e.pending)

    def test_exact_matches_group_translations_and_count_them(self):
        res = self.app.entry_memory("a.rpy", self.line("Okay."))
        targets = {g["target"] for g in res["exact"]}
        self.assertEqual(targets, {"Dobře.", "Fajn.", "Dobře!"})
        self.assertTrue(all(g["lines"] for g in res["exact"]))

    def test_the_line_itself_is_never_suggested(self):
        translated = next(e.line for e in self.app.project.entries("a.rpy") if e.target == "Dobře.")
        targets = {g["target"] for g in self.app.entry_memory("a.rpy", translated)["exact"]}
        self.assertEqual(targets, {"Fajn.", "Dobře!"})

    def test_similar_lines_are_found_by_the_original_with_a_ratio(self):
        res = self.app.entry_memory("a.rpy", self.line("I really do not know what to say."))
        self.assertEqual(res["exact"], [])
        self.assertEqual([s["target"] for s in res["similar"]], ["Nevím, co říct."])
        self.assertGreaterEqual(res["similar"][0]["ratio"], 0.8)

    def test_a_suggestion_with_other_variables_is_flagged(self):
        res = self.app.entry_memory("a.rpy", self.line("Take the key."))
        sim = next(s for s in res["similar"] if s["target"] == "Vezmi si [item].")
        self.assertTrue(sim["vars_differ"])

    def test_nothing_for_very_short_or_unknown_lines(self):
        self.assertEqual(self.app.entry_memory("a.rpy", self.line("Okay."))["similar"], [])
        with self.assertRaises(AppError):
            self.app.entry_memory("a.rpy", 9999)

    def test_index_follows_edits(self):
        e = next(x for x in self.app.project.entries("a.rpy") if x.source == "Take the key." and x.pending)
        self.app.entry_save("a.rpy", e.line, "Vezmi klíč.")
        res = self.app.entry_memory("a.rpy", self.line("Okay."))
        self.assertEqual(len(res["exact"]), 3)
        res2 = self.app.entry_memory("a.rpy", next(x.line for x in self.app.project.entries("a.rpy") if x.target == "Vezmi si [item]."))
        self.assertIn("Vezmi klíč.", [s["target"] for s in res2["similar"]])


class ConsistencyTests(TempCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("a.rpy", dialog("a1", "mc", "Yes.", "Ano.", 5) + dialog("a2", "de", "Yes.", "Jo.", 9)
                               + dialog("a3", "mc", "Yes!", "Ano.", 14) + dialog("a4", "mc", "No.", "Ne.", 20)
                               + dialog("a5", "mc", "No.", "Ne.", 25) + dialog("a6", "mc", "Hmm", None, 30))
        self.app = self.new_app()

    def test_only_originals_with_different_translations_are_listed(self):
        res = self.app.consistency()
        self.assertEqual(res["total"], 1)
        g = res["groups"][0]
        self.assertEqual((g["key"], g["total"]), ("yes", 3))
        self.assertEqual([(v["target"], v["count"]) for v in g["variants"]], [("Ano.", 2), ("Jo.", 1)])
        self.assertEqual({l["who"] for v in g["variants"] for l in v["lines"]}, {"mc", "de"})

    def test_unify_rewrites_only_the_other_variants_as_one_undo_step(self):
        res = self.app.consistency_unify("yes", "Ano.")
        self.assertEqual(res["changed"], 1)
        self.assertEqual(self.path.read_text(encoding="utf-8").count('"Ano."'), 3)
        self.assertEqual(self.app.consistency()["total"], 0)
        self.app.fix_undo()
        self.assertIn('"Jo."', self.path.read_text(encoding="utf-8"))

    def test_unify_can_be_limited_to_chosen_lines(self):
        g = self.app.consistency()["groups"][0]
        jo = g["variants"][1]["lines"][0]
        self.app.consistency_unify("yes", "Ano.", [{"file": jo["file"], "line": jo["line"]}])
        self.assertEqual(self.app.consistency()["total"], 0)

    def test_unknown_group_and_invalid_text_are_errors(self):
        with self.assertRaises(AppError):
            self.app.consistency_unify("nothing here", "x")
        with self.assertRaises(AppError):
            self.app.consistency_unify("yes", 'bad "quote"')


class GameGuiTests(TempCase):
    def make(self, gui_text=None):
        base = self.tmp / "gamebase"
        proj = base / "game" / "tl" / "czech"
        proj.mkdir(parents=True)
        if gui_text is not None:
            (base / "game" / "gui.rpy").write_text(gui_text, encoding="utf-8")
        (proj / "tl.rpy").write_text(dialog("a1", "mc", "Hello.", "Ahoj.", 5), encoding="utf-8")
        app = App(Config().load())
        app.open_project(proj)
        return app

    def test_values_are_read_from_gui_rpy(self):
        app = self.make("define gui.text_size = 28\ndefine gui.dialogue_width = 900\ndefine gui.textbox_height = 200\n")
        g = app.settings()["game_gui"]
        self.assertEqual((g["text_size"], g["dialogue_width"], g["textbox_height"]), (28, 900, 200))
        self.assertEqual(g["source"], "gui.rpy hry")

    def test_defaults_when_the_game_sources_are_missing(self):
        g = self.make(None).settings()["game_gui"]
        self.assertEqual((g["text_size"], g["dialogue_width"]), (33, 1116))
        self.assertEqual(g["source"], "výchozí hodnoty")


if __name__ == "__main__":
    unittest.main()
