"""Findings grouped by line, and the status counts that the filter pills show."""
import unittest

from helpers import TempCase, dialog


class GroupedFindingsTests(TempCase):
    def setUp(self):
        super().setUp()
        # line 1 has three findings (unknown variable, missing variable, changed number); line 2 one; line 3 none
        self.write("script.rpy", dialog("a1", "mc", "I need 14 people [name].", "Potřebuju 15 lidí [jmeno].", 5)
                   + dialog("a2", "de", "Hello [name].", "Ahoj [jmeno].", 9)
                   + dialog("a3", "mc", "Fine.", "Dobře.", 14))
        self.app = self.new_app()

    def test_one_item_per_line_with_all_its_findings(self):
        flat = self.app.validation_list()
        grouped = self.app.validation_list(group="line")
        self.assertGreater(flat["total"], grouped["total"])
        self.assertEqual(grouped["total"], 2)
        self.assertEqual(grouped["findings"], flat["total"])
        first = grouped["items"][0]
        self.assertGreaterEqual(len(first["issues"]), 3)
        self.assertEqual(first["severity"], "error")                        # the worst finding of the line
        self.assertEqual([i["severity"] for i in first["issues"]], sorted((i["severity"] for i in first["issues"]),
                                                                          key=["error", "warning", "info"].index))
        self.assertTrue(first["source"] and first["target"])

    def test_filters_apply_to_the_findings_and_lines_follow(self):
        errors = self.app.validation_list(severity="warning", group="line")
        self.assertTrue(all(i["severity"] == "warning" for g in errors["items"] for i in g["issues"]))
        none = self.app.validation_list(q="no such text", group="line")
        self.assertEqual((none["total"], none["items"]), (0, []))

    def test_paging_counts_lines_not_findings(self):
        page = self.app.validation_list(group="line", limit=1)
        self.assertEqual((page["total"], len(page["items"])), (2, 1))
        rest = self.app.validation_list(group="line", offset=1, limit=1)
        self.assertNotEqual(page["items"][0]["line"], rest["items"][0]["line"])

    def test_ignored_findings_are_grouped_separately(self):
        g = self.app.validation_list(group="line")["items"][0]
        first = g["issues"][0]
        self.app.ignore_set([{"file": g["file"], "line": g["line"], "code": first["code"]}], True)
        again = self.app.validation_list(group="line")
        self.assertEqual(len(again["items"][0]["issues"]), len(g["issues"]) - 1)
        only = self.app.validation_list(group="line", ignored="only")
        self.assertEqual([i["code"] for i in only["items"][0]["issues"]], [first["code"]])


class StatusCountsTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "Hello there.", "Ahoj tam.", 5) + dialog("a2", "mc", "Fine.", None, 9)
                   + dialog("a3", "de", "Welcome back.", "Vítej zpět.", 14))
        self.write("b.rpy", dialog("b1", "mc", "Hmm...", None, 5))
        self.app = self.new_app()

    def test_counts_match_the_lists(self):
        c = self.app.entries()["counts"]
        self.assertEqual(c["all"], 4)
        for status in ("todo", "translated", "review", "approved", "proofed", "fix", "stale"):
            self.assertEqual(c[status], self.app.entries(status=status)["total"], status)
        self.assertEqual((c["todo"], c["translated"]), (2, 2))

    def test_counts_honour_the_other_filters_but_not_the_status(self):
        c = self.app.entries(file="a.rpy", status="todo")["counts"]
        self.assertEqual((c["all"], c["todo"], c["translated"]), (3, 1, 2))     # status filter does not shrink the pills
        c = self.app.entries(q="vítej")["counts"]
        self.assertEqual((c["all"], c["translated"], c["todo"]), (1, 1, 0))

    def test_counts_follow_proofreading(self):
        e = next(x for x in self.app.project.entries("a.rpy") if x.target == "Ahoj tam.")
        self.assertEqual(self.app.entries()["counts"]["review"], 2)
        self.app.proof_set([{"file": "a.rpy", "key": list(e.key)}], "ok", None)
        c = self.app.entries()["counts"]
        self.assertEqual((c["review"], c["proofed"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
