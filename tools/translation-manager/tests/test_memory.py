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
                               + dialog("a3", "mc", "Yes.", "Ano.", 14) + dialog("a4", "mc", "No.", "Ne.", 20)
                               + dialog("a5", "mc", "No.", "Ne.", 25) + dialog("a6", "mc", "Hmm", None, 30))
        self.app = self.new_app()

    def key(self):
        return self.app.consistency()["groups"][0]["key"]

    def test_only_originals_with_different_translations_are_listed(self):
        res = self.app.consistency()
        self.assertEqual(res["total"], 1)
        g = res["groups"][0]
        self.assertEqual((g["source"], g["total"]), ("Yes.", 3))
        self.assertEqual([(v["target"], v["count"]) for v in g["variants"]], [("Ano.", 2), ("Jo.", 1)])
        self.assertEqual({l["who"] for v in g["variants"] for l in v["lines"]}, {"mc", "de"})

    def test_unify_rewrites_only_the_other_variants_as_one_undo_step(self):
        res = self.app.consistency_unify(self.key(), "Ano.")
        self.assertEqual(res["changed"], 1)
        self.assertEqual(self.path.read_text(encoding="utf-8").count('"Ano."'), 3)
        self.assertEqual(self.app.consistency()["total"], 0)
        self.app.fix_undo()
        self.assertIn('"Jo."', self.path.read_text(encoding="utf-8"))

    def test_unify_changes_only_the_lines_the_user_ticked(self):
        g = self.app.consistency()["groups"][0]
        ano = [l for v in g["variants"] for l in v["lines"] if v["target"] == "Ano."]
        res = self.app.consistency_unify(self.key(), "Jo.", [{"file": ano[0]["file"], "line": ano[0]["line"]}])
        self.assertEqual(res["changed"], 1)
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual((text.count('"Jo."'), text.count('"Ano."')), (2, 1))          # the other "Ano." line was not ticked

    def test_unknown_group_and_invalid_text_are_errors(self):
        with self.assertRaises(AppError):
            self.app.consistency_unify("nothing here", "x")
        with self.assertRaises(AppError):
            self.app.consistency_unify(self.key(), 'bad "quote"')


class ConsistencyCaseAndPunctuationTests(TempCase):
    """"Yeah." / "Yeah!" / "YEAH!!!" are different originals with rightly different translations."""

    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "Yeah.", "Jo.", 5) + dialog("a2", "mc", "Yeah!", "Jo!", 9)
                   + dialog("a3", "mc", "YEAH!!!", "JOOOO!", 14) + dialog("a4", "de", "Yeah.", "Jo.", 20)
                   + dialog("a5", "de", "Yeah.", "Jasně.", 25))
        self.app = self.new_app()

    def test_different_case_or_punctuation_is_never_one_group(self):
        res = self.app.consistency()
        self.assertEqual([(g["source"], g["total"]) for g in res["groups"]], [("Yeah.", 3)])       # only the three "Yeah."
        self.assertEqual({v["target"] for v in res["groups"][0]["variants"]}, {"Jo.", "Jasně."})

    def test_loose_mode_finds_near_duplicates_but_lists_every_original_text(self):
        res = self.app.consistency(loose=True)
        self.assertEqual(res["groups"][0]["total"], 5)
        self.assertEqual(res["groups"][0]["sources"], ["YEAH!!!", "Yeah!", "Yeah."])

    def test_unify_in_strict_mode_cannot_touch_the_shouting_line(self):
        key = self.app.consistency()["groups"][0]["key"]
        self.app.consistency_unify(key, "Jo.")
        targets = [e.target for e in self.app.project.entries("a.rpy")]
        self.assertEqual(targets, ["Jo.", "Jo!", "JOOOO!", "Jo.", "Jo."])

    def test_by_speaker_keeps_speakers_apart(self):
        strict = self.app.consistency(by_speaker=True)
        self.assertEqual([(g["total"], {l["who"] for v in g["variants"] for l in v["lines"]}) for g in strict["groups"]],
                         [(2, {"de"})])                                                   # mc has one "Yeah." only
        loose = self.app.consistency(by_speaker=True, loose=True)
        self.assertEqual(sorted(g["total"] for g in loose["groups"]), [2, 3])             # mc: 3 spellings, de: 2 lines


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
