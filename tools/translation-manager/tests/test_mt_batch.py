"""Machine translation of several lines (chosen lines, a file): targets, batches with fake HTTP, and one undoable write."""
import json
import unittest
from pathlib import Path
import urllib.parse

from helpers import TempCase, dialog
from test_mt import FakeHttp

from prehled.app import AppError


def echo(url, headers, data):
    text = urllib.parse.parse_qs(data.decode("utf-8"))["text"][0]
    return {"translations": [{"text": "CZ " + text}]}


class MtBatchTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "One [name].", None, 3) + dialog("a2", "mc", "Two.", None, 7)
                   + dialog("a3", "mc", "Three.", "Tři.", 11) + dialog("a4", "mc", "Four.", None, 15))
        self.write("b.rpy", dialog("b1", "mc", "Five.", None, 3))
        self.app = self.new_app()
        self.app.update_settings({"mt": {"provider": "deepl", "api_key": "secret:fx", "consent": True}})
        self.http = FakeHttp(reply=echo)
        self.app._mt_http = self.http
        self.todo = [e.line for e in self.app.project.entries("a.rpy") if e.pending]

    def items(self, rel="a.rpy"):
        return [{"file": rel, "line": ln} for ln in self.todo]

    def test_targets_are_the_untranslated_lines_of_a_file_or_of_everything(self):
        t = self.app.mt_targets("a.rpy")
        self.assertEqual((t["total"], [i["line"] for i in t["items"]]), (3, self.todo))
        self.assertEqual(t["chars"], len("One [name].") + len("Two.") + len("Four."))
        self.assertEqual(self.app.mt_targets("")["total"], 4)
        self.assertEqual(self.app.mt_targets("a.rpy", only_todo=False)["total"], 4)
        with self.assertRaises(AppError):
            self.app.mt_targets("nope.rpy")

    def test_chosen_lines_limit_the_targets(self):
        t = self.app.mt_targets("", [{"file": "a.rpy", "line": self.todo[1]}, {"file": "a.rpy", "line": self.todo[0]}])
        self.assertEqual([i["line"] for i in t["items"]], self.todo[:2])

    def test_a_batch_suggests_for_every_line_and_writes_nothing(self):
        before = (self.root / "a.rpy").read_bytes()
        res = self.app.mt_batch(self.items())
        self.assertEqual(res["stopped"], "")
        self.assertEqual([r["suggestion"] for r in res["results"]], ["CZ One [name].", "CZ Two.", "CZ Four."])
        self.assertEqual((self.root / "a.rpy").read_bytes(), before)
        self.assertEqual(len(self.http.calls), 3)

    def test_a_batch_is_capped_so_the_ui_can_show_progress(self):
        big = [{"file": "a.rpy", "line": self.todo[0]}] * (self.app.MT_BATCH + 5)
        self.assertEqual(len(self.app.mt_batch(big)["results"]), self.app.MT_BATCH)

    def test_a_rejected_key_stops_the_batch_after_the_first_line(self):
        self.app._mt_http = FakeHttp(403, "forbidden")
        res = self.app.mt_batch(self.items())
        self.assertIn("klíč", res["stopped"])
        self.assertEqual(len(res["results"]), 1)

    def test_a_vanished_line_is_reported_for_that_line_only(self):
        res = self.app.mt_batch([{"file": "a.rpy", "line": 9999}] + self.items()[:1])
        self.assertIn("error", res["results"][0])
        self.assertEqual(res["results"][1]["suggestion"], "CZ One [name].")

    def test_apply_writes_the_ticked_lines_as_one_undoable_step(self):
        res = self.app.mt_batch(self.items())["results"]
        sel = [{"file": r["file"], "line": r["line"], "text": r["suggestion"]} for r in res[:2]]
        out = self.app.mt_apply(sel)
        self.assertEqual((out["changed"], out["skipped"]), (2, 0))
        targets = {e.line: e.target for e in self.app.project.entries("a.rpy")}
        self.assertEqual([targets[ln] for ln in self.todo[:2]], ["CZ One [name].", "CZ Two."])
        self.assertEqual([e.pending for e in self.app.project.entries("a.rpy")].count(True), 1)
        self.app.fix_undo()
        self.assertEqual([e.pending for e in self.app.project.entries("a.rpy")].count(True), 3)

    def test_approved_and_vanished_lines_are_never_overwritten(self):
        ln = self.todo[0]
        self.app.approval_apply([{"file": "a.rpy", "key": next(e.key for e in self.app.project.entries("a.rpy") if e.line == ln)}], True)
        sel = [{"file": "a.rpy", "line": ln, "text": "X"}, {"file": "a.rpy", "line": 9999, "text": "Y"}, {"file": "a.rpy", "line": self.todo[1], "text": "  "}]
        with self.assertRaises(AppError):
            self.app.mt_apply(sel)
        self.assertNotIn("X", (self.root / "a.rpy").read_text(encoding="utf-8"))

    def test_the_route_is_wired(self):
        from prehled import server
        src = Path(server.__file__).read_text(encoding="utf-8")
        for name in ("mt/targets", "mt/batch", "mt/apply"):
            self.assertIn(f'"{name}"', src)
        json.dumps(self.app.mt_targets("a.rpy"))


if __name__ == "__main__":
    unittest.main()
