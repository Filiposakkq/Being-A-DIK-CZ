"""Typo hints, textbox check, rule approvals, term occurrences, script context, worst files, stale proofreading."""
import unittest

from helpers import TempCase, dialog, strings

from prehled import bulk, validator
from prehled.app import App, AppError
from prehled.config import Config


def codes(app, severity=""):
    return [i["code"] for i in app.validation_list(severity=severity)["items"]]


class TypoTests(TempCase):
    def project(self, bad):
        text = "".join(dialog(f"a{i}", "mc", "I will come.", "Já přijdu zítra, takový je plán.", 10 + i) for i in range(6))
        text += dialog("z1", "mc", "Weird.", bad, 90)
        self.write("script.rpy", text)
        return self.new_app()

    def test_missing_diacritics_is_reported(self):
        app = self.project("Já prijdu zítra.")
        items = app.validation_list(severity="warning")["items"]
        self.assertEqual([i["code"] for i in items], ["typo-suspect"])
        self.assertIn("přijdu", items[0]["message"])

    def test_swapped_letters_and_doubled_letters(self):
        self.assertEqual(codes(self.project("To je tkaový den.")), ["typo-suspect"])
        self.assertEqual(codes(self.project("Já přiijdu zítra.")), ["typo-suspect"])

    def test_names_and_source_words_are_left_alone(self):
        app = self.project("Prijdu k Dr PinkCake.")
        app.glossary_set([{"code": "pc", "name": "Prijdu", "type": "term"}])       # known word: never flagged
        self.assertNotIn("typo-suspect", codes(app, "warning") + codes(app, "info"))

    def test_can_be_switched_off(self):
        app = self.project("Já prijdu zítra.")
        app.update_settings({"validation": {"spelling": False}})
        self.assertNotIn("typo-suspect", codes(app, "warning"))


class TextboxTests(unittest.TestCase):
    def test_lines_needed_wraps_words_and_counts_explicit_breaks(self):
        self.assertEqual(validator.lines_needed("slovo " * 20, 65), 2)
        self.assertEqual(validator.lines_needed("a\\nb\\nc", 65), 3)
        self.assertEqual(validator.lines_needed("{i}tag{/i} [name]", 65), 1)

    def test_plain_text_turns_the_escaped_line_break_into_a_space(self):
        self.assertEqual(validator.plain_text("Ahoj\\nsvěte {i}ty{/i} [x]"), "Ahoj světe ty  ")

    def test_long_translation_that_the_original_does_not_need_is_reported(self):
        tgt = "slovo " * 60
        iss = validator.check_textbox("Short.", tgt)
        self.assertEqual([i.code for i in iss], ["textbox-overflow"])
        self.assertEqual(iss[0].category, "length")
        self.assertEqual(validator.check_textbox("slovo " * 60, tgt), [])         # the original overflows as well
        self.assertEqual(validator.check_textbox("Short.", tgt, {"enabled": False}), [])
        self.assertEqual(validator.check_textbox("Short.", tgt, {"max_lines": 10}), [])


class TextboxSettingsTests(TempCase):
    def test_settings_are_validated_and_applied(self):
        self.write("script.rpy", dialog("a1", "mc", "Short.", "slovo " * 60, 5))
        app = self.new_app()
        self.assertIn("textbox-overflow", codes(app, "warning"))
        app.update_settings({"validation": {"textbox": {"max_lines": 12}}})
        self.assertNotIn("textbox-overflow", codes(app, "warning"))
        with self.assertRaises(AppError):
            app.update_settings({"validation": {"textbox": {"max_lines": 0}}})


class RuleApprovalTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("script.rpy", dialog("a1", "mc", "Hmm...", None, 5) + dialog("a2", "mc", "...", None, 9)
                   + dialog("a3", "mc", "Derek", None, 14) + dialog("a4", "mc", "Where are you going today?", None, 20)
                   + dialog("a5", "mc", "Fine.", "Dobře.", 30))
        self.app = self.new_app()
        self.app.glossary_set([{"code": "de", "name": "Derek", "type": "speaker"}])

    def test_each_rule_finds_only_its_lines(self):
        by = {i["text"]: i["rule"] for i in self.app.rule_preview(["symbols", "interjections", "names"])["items"]}
        self.assertEqual(by, {"Hmm...": "interjections", "...": "symbols", "Derek": "names"})
        self.assertEqual([i["text"] for i in self.app.rule_preview(["symbols"])["items"]], ["..."])
        self.assertEqual(self.app.rule_preview([])["items"], [])

    def test_applying_goes_through_the_normal_undoable_approval(self):
        before = self.app.overview()["totals"]["done"]
        items = self.app.rule_preview(["symbols", "interjections", "names"])["items"]
        res = self.app.approval_apply([{"file": i["file"], "key": i["key"]} for i in items], True)
        self.assertEqual(res["changed"], 3)
        self.assertEqual(self.app.overview()["totals"]["done"], before + 3)
        self.assertEqual(self.app.rule_preview(["symbols"])["items"][0]["selectable"], False)    # already approved
        self.app.undo()
        self.assertEqual(self.app.overview()["totals"]["done"], before)

    def test_untranslated_english_sentences_never_match(self):
        self.assertNotIn("Where are you going today?", [i["text"] for i in
                         bulk.rule_candidates(self.app.project, self.app.store.glossary, list(bulk.RULES))["items"]])


class OccurrencesTests(TempCase):
    def test_lists_lines_with_the_term_and_whether_the_czech_form_is_used(self):
        self.write("script.rpy",
                   dialog("a1", "mc", "Take the Dik Coins.", "Vezmi si ty dikmince.", 5)
                   + dialog("a2", "mc", "More Dik Coins!", "Další peníze!", 9)
                   + dialog("a3", "mc", "Dik Coins later.", None, 14)
                   + dialog("a4", "mc", "Unrelated.", "Nesouvisí.", 20))
        app = self.new_app()
        app.glossary_set([{"code": "Dik Coins", "name": "dikmince", "type": "term"}])
        res = app.glossary_occurrences("Dik Coins")
        self.assertEqual((res["found"], res["missing"], res["untranslated"]), (1, 1, 1))
        self.assertEqual(len(res["items"]), 3)
        only = app.glossary_occurrences("Dik Coins", only_missing=True)
        self.assertEqual([i["target"] for i in only["items"]], ["Další peníze!"])
        with self.assertRaises(AppError):
            app.glossary_occurrences("nope")


class ContextTests(TempCase):
    def make(self, with_script=True):
        base = self.tmp / "gamebase"
        proj = base / "game" / "tl" / "czech"
        proj.mkdir(parents=True)
        if with_script:
            (base / "game" / "x.rpy").write_text("\n".join(f"line {i}" for i in range(1, 31)), encoding="utf-8")
        (proj / "tl.rpy").write_text(dialog("a1", "mc", "Hello.", "Ahoj.", 10), encoding="utf-8")
        app = App(Config().load())
        app.open_project(proj)
        return app

    def test_shows_the_script_lines_around_the_reference(self):
        app = self.make()
        ctx = app.entry_context("tl.rpy", next(e.line for e in app.project.entries("tl.rpy")))
        self.assertTrue(ctx["available"])
        hit = [x for x in ctx["lines"] if x["hit"]]
        self.assertEqual([(x["n"], x["text"]) for x in hit], [(10, "line 10")])
        self.assertEqual(len(ctx["lines"]), 13)

    def test_missing_script_is_explained_not_an_error(self):
        app = self.make(with_script=False)
        ctx = app.entry_context("tl.rpy", next(e.line for e in app.project.entries("tl.rpy")))
        self.assertFalse(ctx["available"])
        self.assertIn("nebyl nalezen", ctx["reason"])

    def test_references_cannot_escape_the_game_folder(self):
        app = self.make()
        e = app.project.entries("tl.rpy")[0]
        e.ref = "game/../../secret.rpy:3"
        ctx = app.entry_context("tl.rpy", e.line)
        self.assertFalse(ctx["available"])


class WorstFilesAndStaleTests(TempCase):
    def test_files_are_ranked_by_problems_per_line(self):
        self.write("good.rpy", dialog("g1", "mc", "Hello.", "Ahoj.", 5) * 1)
        self.write("bad.rpy", dialog("b1", "mc", "Hello [name].", "Ahoj [jmeno].", 5)
                   + dialog("b2", "mc", "Fine.", "Dobře.", 9))
        app = self.new_app()
        worst = app.overview()["worst_files"]
        self.assertEqual([w["name"] for w in worst], ["bad.rpy"])
        self.assertGreater(worst[0]["score"], 0)

    def test_stale_proofreading_is_counted(self):
        path = self.write("script.rpy", dialog("a1", "mc", "Hello there.", "Ahoj tam.", 5))
        app = self.new_app()
        e = app.project.entries("script.rpy")[0]
        app.proof_set([{"file": "script.rpy", "key": list(e.key)}], "ok", None)
        self.assertEqual(app.overview()["totals"]["proof_stale"], 0)
        path.write_text(dialog("a1", "mc", "Hello there.", "Ahoj tamhle.", 5), encoding="utf-8")
        app.refresh(force=True)
        self.assertEqual(app.overview()["totals"]["proof_stale"], 1)
        self.assertEqual(app.files_payload()[0]["proof_stale"], 1)
        self.assertEqual(app.entries(status="stale")["total"], 1)


if __name__ == "__main__":
    unittest.main()
