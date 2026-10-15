"""History of the text of a line: in-app edits, fixes, replacements, undo and changes made outside the app."""
import json
import unittest

from helpers import TempCase, dialog

from prehled import texthistory
from prehled.app import AppError


class HistoryTests(TempCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("a.rpy", dialog("a1", "mc", "Hello there.", "Ahoj tam.", 5)
                               + dialog("a2", "mc", "Fine.", "Dobře.", 9))
        self.app = self.new_app()
        self.line = next(e.line for e in self.app.project.entries("a.rpy") if e.target == "Ahoj tam.")

    def versions(self, line=None):
        return self.app.entry_history("a.rpy", line or self.line)["versions"]

    def test_a_line_without_changes_has_no_history(self):
        self.assertEqual(self.versions(), [])

    def test_edits_build_a_list_newest_first_with_the_original_text_at_the_end(self):
        self.app.entry_save("a.rpy", self.line, "Čau tam.")
        self.app.entry_save("a.rpy", self.line, "Čau všem.")
        v = self.versions()
        self.assertEqual([x["text"] for x in v], ["Čau všem.", "Čau tam.", "Ahoj tam."])
        self.assertEqual([x["current"] for x in v], [True, False, False])
        self.assertEqual(v[0]["via"], "úprava v aplikaci")
        self.assertIn("původní", v[-1]["via"])
        self.assertEqual(self.app.entry_history("a.rpy", self.line)["count"], 2)

    def test_history_survives_a_restart_and_follows_the_line(self):
        self.app.entry_save("a.rpy", self.line, "Čau tam.")
        app2 = self.new_app()
        self.assertEqual([x["text"] for x in app2.entry_history("a.rpy", self.line)["versions"]], ["Čau tam.", "Ahoj tam."])
        self.assertTrue((self.root / "_progress_data" / texthistory.FILE_NAME).is_file())

    def test_fix_replace_and_unify_are_logged_with_their_origin(self):
        self.app.entry_save("a.rpy", self.line, "Ahoj  tam.")                       # a double space to fix
        sel = [{"file": "a.rpy", "line": self.line, "kind": "spaces"}]
        self.app.fix_apply(selections=sel)
        self.app.replace_apply([{"file": "a.rpy", "line": self.line}], "tam", "všem", "word")
        vias = [x["via"] for x in self.versions()]
        self.assertEqual(vias[:2], ["nahrazení", "oprava"])

    def test_undo_is_logged_too(self):
        self.app.entry_save("a.rpy", self.line, "Čau tam.")
        self.app.fix_undo()
        v = self.versions()
        self.assertEqual(v[0]["text"], "Ahoj tam.")
        self.assertEqual(v[0]["via"], "vrácení změny")

    def test_changes_made_outside_the_app_are_noticed_at_the_next_refresh(self):
        self.path.write_text(dialog("a1", "mc", "Hello there.", "Ahoj všichni.", 5) + dialog("a2", "mc", "Fine.", "Dobře.", 9),
                             encoding="utf-8")
        self.app.refresh(force=True)
        v = self.versions()
        self.assertEqual([(x["text"], x["via"]) for x in v][:2], [("Ahoj všichni.", "změna mimo aplikaci"), ("Ahoj tam.", "původní text před první zaznamenanou změnou")])
        self.app.refresh(force=True)                                                # nothing new: no duplicate entry
        self.assertEqual(len(self.versions()), 2)

    def test_our_own_writes_are_not_logged_a_second_time_as_external(self):
        self.app.entry_save("a.rpy", self.line, "Čau tam.")
        self.app.refresh(force=True)
        self.assertEqual(len(self.versions()), 2)

    def test_a_damaged_history_file_does_not_break_anything(self):
        f = self.root / "_progress_data" / texthistory.FILE_NAME
        f.write_text('not json\n{"t": "x"}\n' + json.dumps({"t": "2026-01-01T00:00:00", "f": "a.rpy", "k": ["translate czech a1", "Hello there."],
                                                              "o": "Ahoj tam.", "n": "Čau.", "v": "edit"}) + "\n", encoding="utf-8")
        app = self.new_app()
        self.assertEqual(app.texthist.total, 1)

    def test_unknown_line_is_an_error(self):
        with self.assertRaises(AppError):
            self.app.entry_history("a.rpy", 9999)

    def test_the_file_is_trimmed_when_it_grows_too_large(self):
        f = self.root / "_progress_data" / texthistory.FILE_NAME
        row = json.dumps({"t": "2026-01-01T00:00:00", "f": "a.rpy", "k": ["b", "s"], "o": "x", "n": "y", "v": "edit"})
        f.write_text((row + "\n") * (texthistory.MAX_LINES + 10), encoding="utf-8")
        h = texthistory.TextHistory(f).load()
        self.assertEqual(h.total, texthistory.KEEP_LINES)


class DiffTests(unittest.TestCase):
    def test_duplicates_with_the_same_key_are_matched_in_order(self):
        class E:
            def __init__(self, key, target):
                self.key, self.target, self.block, self.source = key, target, key[0], key[1]
        k = ("strings", "ok")
        old = [E(k, "a"), E(k, "b")]
        new = [E(k, "a"), E(k, "c")]
        self.assertEqual([(c["old"], c["new"]) for c in texthistory.diff_files(old, new)], [("b", "c")])


if __name__ == "__main__":
    unittest.main()
