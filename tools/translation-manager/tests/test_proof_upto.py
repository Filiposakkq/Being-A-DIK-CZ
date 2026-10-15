"""Mark proofread up to a line, and take it away again."""
import unittest

from helpers import TempCase, dialog

from prehled.app import AppError


class ProofUptoTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", "".join(dialog(f"a{i}", "mc", f"Line number {i}.", f"Řádek číslo {i}.", 10 + 5 * i) for i in range(1, 6)))
        self.app = self.new_app()
        self.lines = [e.line for e in self.app.project.entries("a.rpy")]

    def states(self):
        return [self.app.project.proof_state("a.rpy", e) for e in self.app.project.entries("a.rpy")]

    def test_mark_then_unmark_up_to_a_line(self):
        self.app.proof_upto("a.rpy", self.lines[2])
        self.assertEqual(self.states(), ["ok", "ok", "ok", "", ""])
        res = self.app.proof_upto("a.rpy", self.lines[1], "")
        self.assertEqual(res["changed"], 2)
        self.assertEqual(self.states(), ["", "", "ok", "", ""])           # only up to the chosen line

    def test_lines_flagged_to_fix_are_never_touched(self):
        e = self.app.project.entries("a.rpy")[1]
        self.app.proof_set([{"file": "a.rpy", "key": list(e.key)}], "fix", "oprav")
        self.app.proof_upto("a.rpy", self.lines[4])
        self.assertEqual(self.states(), ["ok", "fix", "ok", "ok", "ok"])
        self.app.proof_upto("a.rpy", self.lines[4], "")
        self.assertEqual(self.states(), ["", "fix", "", "", ""])

    def test_unmarking_is_one_undo_step(self):
        self.app.proof_upto("a.rpy", self.lines[4])
        self.app.proof_upto("a.rpy", self.lines[4], "")
        self.assertEqual(self.states(), [""] * 5)
        self.app.undo()
        self.assertEqual(self.states(), ["ok"] * 5)

    def test_stale_marks_are_removed_too_and_nothing_to_do_is_not_an_error(self):
        self.assertEqual(self.app.proof_upto("a.rpy", self.lines[4], "")["changed"], 0)
        self.app.proof_upto("a.rpy", self.lines[0])
        e = self.app.project.entries("a.rpy")[0]
        self.app.store.proof["a.rpy"][e.key]["h"] = "changed"             # the translation "changed" since
        self.assertEqual(self.states()[0], "stale")
        self.app.proof_upto("a.rpy", self.lines[0], "")
        self.assertEqual(self.states()[0], "")

    def test_bad_state_and_file_are_rejected(self):
        with self.assertRaises(AppError):
            self.app.proof_upto("a.rpy", 10, "fix")
        with self.assertRaises(AppError):
            self.app.proof_upto("nope.rpy", 10, "")


if __name__ == "__main__":
    unittest.main()
