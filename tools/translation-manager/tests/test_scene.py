"""The scene around a line: original and translation of the neighbouring lines."""
import unittest

from helpers import TempCase, dialog

from prehled.app import AppError


class SceneTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", "".join(dialog(f"a{i}", "mc" if i % 2 else "de", f"Line {i}.", f"Řádek {i}." if i != 4 else None, 10 + 5 * i)
                                    for i in range(1, 10)))
        self.app = self.new_app()
        self.lines = [e.line for e in self.app.project.entries("a.rpy")]

    def test_radius_and_current_marker(self):
        res = self.app.entry_scene("a.rpy", self.lines[4], 2)
        self.assertEqual([i["line"] for i in res["items"]], self.lines[2:7])
        self.assertEqual([i["current"] for i in res["items"]], [False, False, True, False, False])
        self.assertEqual(res["items"][2]["source"], "Line 5.")
        self.assertEqual(res["items"][2]["target"], "Řádek 5.")

    def test_edges_and_statuses(self):
        res = self.app.entry_scene("a.rpy", self.lines[0], 3)
        self.assertEqual(len(res["items"]), 4)
        self.assertEqual({i["line"]: i["status"] for i in self.app.entry_scene("a.rpy", self.lines[3], 1)["items"]}[self.lines[3]], "todo")
        self.assertEqual(len(self.app.entry_scene("a.rpy", self.lines[4], 999)["items"]), 9)       # radius is clamped

    def test_errors(self):
        with self.assertRaises(AppError):
            self.app.entry_scene("nope.rpy", 1)
        with self.assertRaises(AppError):
            self.app.entry_scene("a.rpy", 9999)


if __name__ == "__main__":
    unittest.main()
