"""Weekly goals derived from the pace, or set by hand."""
import unittest
from datetime import date, datetime

from helpers import TempCase, dialog

from prehled import history as hist
from prehled.app import AppError

TODAY = date(2026, 10, 14)            # a Wednesday; the week started Monday 2026-10-12


def pts(rows):
    """rows: [(iso date, translated, proofread)] -> history points with a fixed total."""
    return [(datetime.fromisoformat(d + "T12:00:00"), t, 1000, c) for d, t, c in rows]


def steady(weeks=4, per_week=100, start=0):
    """One record per Sunday: `per_week` more lines every week, ending on Sunday 2026-10-11."""
    rows = []
    for i in range(weeks + 1):
        d = date(2026, 10, 11).toordinal() - 7 * (weeks - i)
        rows.append((date.fromordinal(d).isoformat(), start + per_week * i, per_week // 2 * i))
    return rows


class GoalMathTests(unittest.TestCase):
    def test_week_start_is_monday(self):
        self.assertEqual(hist.week_start(TODAY), date(2026, 10, 12))
        self.assertEqual(hist.week_start(date(2026, 10, 18)), date(2026, 10, 12))

    def test_auto_goal_is_a_bit_above_the_recent_pace(self):
        rows = steady() + [("2026-10-13", 440, 220)]
        g = hist.goals(pts(rows), 500, 600, None, TODAY)
        t = g["translate"]
        self.assertEqual((t["done"], t["goal"], t["auto"], t["pace_per_week"]), (40, 110, True, 100))
        self.assertEqual(t["status"], "behind")                       # 40 of 110 after 3 of 7 days
        self.assertEqual(t["needed_per_day"], 14)                      # (110 - 40) / 5 days left
        self.assertEqual(g["translate"]["percent"], 36.4)
        self.assertEqual(g["proofread"]["goal"], 60)

    def test_a_manual_goal_wins_and_status_follows_progress(self):
        rows = steady() + [("2026-10-13", 440, 220)]
        t = hist.goals(pts(rows), 500, 600, {"translate_per_week": 50}, TODAY)["translate"]
        self.assertEqual((t["goal"], t["auto"], t["status"]), (50, False, "on_track"))
        t = hist.goals(pts(rows), 500, 600, {"translate_per_week": 30}, TODAY)["translate"]
        self.assertEqual((t["status"], t["left"], t["percent"]), ("met", 0, 100.0))

    def test_not_enough_history_means_no_automatic_goal(self):
        g = hist.goals(pts([("2026-10-13", 40, 0)]), 500, 600, None, TODAY)
        self.assertEqual((g["translate"]["goal"], g["translate"]["status"]), (None, "no_goal"))
        g = hist.goals(pts(steady(weeks=1)), 500, 600, None, TODAY)           # a single full week is too little
        self.assertIsNone(g["translate"]["goal"])
        self.assertEqual(hist.goals([], 10, 10, {"translate_per_week": 20}, TODAY)["translate"]["goal"], 20)

    def test_the_goal_never_exceeds_what_is_left(self):
        g = hist.goals(pts(steady()), 25, 600, None, TODAY)["translate"]
        self.assertEqual(g["goal"], 25)
        self.assertIsNone(hist.goals(pts(steady()), 0, 600, None, TODAY)["translate"]["goal"])

    def test_a_week_without_progress_is_not_a_goal(self):
        rows = steady(per_week=0)
        self.assertIsNone(hist.goals(pts(rows), 500, 600, None, TODAY)["translate"]["goal"])


class GoalsInAppTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "Hello.", "Ahoj.", 5) + dialog("a2", "mc", "Fine.", None, 9))
        self.app = self.new_app()

    def test_overview_carries_goals_and_episode_etas(self):
        o = self.app.overview()
        self.assertIn("goals", o)
        self.assertEqual(set(o["goals"]), {"week_start", "translate", "proofread"})
        self.assertTrue(all("eta_days" in e for e in o["episodes"]))

    def test_settings_validate_and_apply_goals(self):
        self.app.update_settings({"goals": {"translate_per_week": 250, "proofread_per_week": "120"}})
        g = self.app.overview()["goals"]
        self.assertEqual((g["translate"]["goal"], g["proofread"]["goal"]), (250, 120))     # a manual goal is never changed
        self.assertEqual(self.app.settings()["goals"], {"translate_per_week": 250, "proofread_per_week": 120})
        for bad in ({"translate_per_week": -1}, {"translate_per_week": "x"}, {"proofread_per_week": 10 ** 7}):
            with self.assertRaises(AppError):
                self.app.update_settings({"goals": bad})


if __name__ == "__main__":
    unittest.main()
