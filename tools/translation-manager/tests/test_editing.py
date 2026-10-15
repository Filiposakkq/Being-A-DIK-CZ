"""Editing a translation directly in the app: safe write, validation, undo stack."""
import unittest

from helpers import TempCase, dialog, strings

from prehled.app import AppError


class EditTests(TempCase):
    def setUp(self):
        super().setUp()
        self.text = (dialog("a1", "mc happy", "Hello [name].", "Ahoj [name].", 5, suffix=" with vpunch")
                     + dialog("a2", "de", "Fine.", None, 9)
                     + strings(("Start", "Začít"), ("Quit", "Quit")))
        self.path = self.write("script.rpy", self.text)
        self.app = self.new_app()

    def line_of(self, who_or_new, contains):
        for ln, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if raw.strip().startswith(who_or_new) and contains in raw and not raw.strip().startswith("#"):
                return ln
        raise AssertionError((who_or_new, contains))

    def test_only_the_text_between_the_quotes_changes(self):
        ln = self.line_of("mc happy", "Ahoj")
        res = self.app.entry_save("script.rpy", ln, "Čau [name], jak se máš?")
        self.assertTrue(res["changed"])
        new = self.path.read_text(encoding="utf-8")
        self.assertEqual(new, self.text.replace('"Ahoj [name]."', '"Čau [name], jak se máš?"'))
        self.assertIn('mc happy "Čau [name], jak se máš?" with vpunch', new)      # speaker and suffix untouched
        self.assertTrue(res["backup"])

    def test_an_untranslated_line_becomes_translated(self):
        before = self.app.overview()["totals"]["done"]
        ln = self.line_of("de", "Fine.")
        self.app.entry_save("script.rpy", ln, "Dobře.")
        self.assertEqual(self.app.overview()["totals"]["done"], before + 1)

    def test_string_pairs_can_be_edited(self):
        ln = self.line_of("new", "Quit")
        self.app.entry_save("script.rpy", ln, "Konec")
        self.assertIn('new "Konec"', self.path.read_text(encoding="utf-8"))

    def test_invalid_literals_are_refused_and_nothing_is_written(self):
        ln = self.line_of("mc happy", "Ahoj")
        for bad in ('Řekl "ahoj"', "konec\\", "dva\nřádky"):
            with self.assertRaises(AppError):
                self.app.entry_save("script.rpy", ln, bad)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.app.entry_save("script.rpy", ln, 'Řekl \\"ahoj\\"\\nznovu')           # escaped forms are fine
        self.assertIn('Řekl \\"ahoj\\"\\nznovu', self.path.read_text(encoding="utf-8"))

    def test_same_text_is_a_no_op(self):
        ln = self.line_of("mc happy", "Ahoj")
        res = self.app.entry_save("script.rpy", ln, "Ahoj [name].")
        self.assertFalse(res["changed"])
        self.assertIsNone(self.app.fix_last()["last"])

    def test_refuses_when_the_file_changed_on_disk(self):
        ln = self.line_of("mc happy", "Ahoj")
        edited = self.text + "\n# edited in vs code\n"
        self.path.write_text(edited, encoding="utf-8")
        with self.assertRaises(AppError):
            self.app.entry_save("script.rpy", ln, "Čau")
        self.assertEqual(self.path.read_text(encoding="utf-8"), edited)

    def test_crlf_and_bom_are_kept(self):
        self.path.write_bytes(("﻿" + self.text).replace("\n", "\r\n").encode("utf-8"))
        app = self.new_app()
        ln = next(e.line for e in app.project.entries("script.rpy") if e.target == "Ahoj [name].")
        app.entry_save("script.rpy", ln, "Čau")
        out = self.path.read_bytes()
        self.assertTrue(out.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", out.replace(b"\r\n", b""))
        self.assertIn('"Čau"'.encode("utf-8"), out)

    def test_edits_can_be_undone_one_after_another(self):
        ln = self.line_of("mc happy", "Ahoj")
        ln2 = self.line_of("de", "Fine.")
        self.app.entry_save("script.rpy", ln, "Čau")
        self.app.entry_save("script.rpy", ln2, "Dobře.")
        self.assertEqual(self.app.fix_last()["last"]["depth"], 2)
        self.app.fix_undo()
        self.assertIn('de "Fine."', self.path.read_text(encoding="utf-8"))
        self.assertIn('"Čau"', self.path.read_text(encoding="utf-8"))
        self.app.fix_undo()
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.assertIsNone(self.app.fix_last()["last"])

    def test_a_proofread_mark_becomes_stale_after_an_edit(self):
        ln = self.line_of("mc happy", "Ahoj")
        e = next(x for x in self.app.project.entries("script.rpy") if x.line == ln)
        self.app.proof_set([{"file": "script.rpy", "key": list(e.key)}], "ok", None)
        self.app.entry_save("script.rpy", ln, "Čau [name]")
        self.assertEqual(self.app.overview()["totals"]["proof_stale"], 1)

    def test_check_reports_problems_of_the_text_being_typed(self):
        ln = self.line_of("mc happy", "Ahoj")
        res = self.app.entry_check("script.rpy", ln, "Ahoj [jmeno].")
        self.assertEqual(res["literal_error"], "")
        self.assertIn("variable-unknown", [i["code"] for i in res["issues"]])
        self.assertTrue(self.app.entry_check("script.rpy", ln, 'špatně "x"')["literal_error"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)           # checking never writes


if __name__ == "__main__":
    unittest.main()
