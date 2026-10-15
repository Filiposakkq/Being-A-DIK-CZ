"""Zip snapshots of the translation folder (with restore) and the Ren'Py lint wrapper."""
import time
import unittest
import zipfile
from pathlib import Path

from helpers import TempCase, dialog

from prehled import lint, snapshots
from prehled.app import App, AppError
from prehled.config import Config


class SnapshotTests(TempCase):
    def setUp(self):
        super().setUp()
        self.p1 = self.write("a.rpy", dialog("a1", "mc", "Hello.", "Ahoj.", 5) + dialog("a2", "mc", "Fine.", "Dobře.", 9))
        self.p2 = self.write("sub/b.rpy", dialog("b1", "de", "Hello.", "Ahoj.", 5))
        self.app = self.new_app()

    def names(self):
        return [s["name"] for s in self.app.snapshot_list()["items"]]

    def test_manual_snapshot_contains_every_rpy_file(self):
        snap = self.app.snapshot_create()["snapshot"]
        self.assertEqual((snap["files"], snap["reason"]), (2, "manual"))
        item = self.app.snapshot_list()["items"][0]
        self.assertEqual((item["name"], item["reason_label"]), (snap["name"], "ručně vytvořená"))
        with zipfile.ZipFile(self.root / "_progress_data" / "snapshots" / snap["name"]) as z:
            self.assertEqual(sorted(n for n in z.namelist() if n.startswith("files/")), ["files/a.rpy", "files/sub/b.rpy"])

    def test_compare_tells_changed_same_and_missing(self):
        name = self.app.snapshot_create()["snapshot"]["name"]
        self.p1.write_text(self.p1.read_text(encoding="utf-8") + "\n# x\n", encoding="utf-8")
        self.p2.unlink()
        states = {f["file"]: f["state"] for f in self.app.snapshot_files(name)["files"]}
        self.assertEqual(states, {"a.rpy": "changed", "sub/b.rpy": "missing"})

    def test_restore_all_or_chosen_and_it_saves_the_current_state_first(self):
        name = self.app.snapshot_create()["snapshot"]["name"]
        original = self.p1.read_text(encoding="utf-8")
        e = self.app.project.entries("a.rpy")[0]
        self.app.entry_save("a.rpy", e.line, "Čau.")
        self.p2.write_text("# broken\n", encoding="utf-8")
        res = self.app.snapshot_restore(name, ["a.rpy"])
        self.assertEqual(res["restored"], ["a.rpy"])
        self.assertEqual(self.p1.read_text(encoding="utf-8"), original)
        self.assertEqual(self.p2.read_text(encoding="utf-8"), "# broken\n")               # not chosen: untouched
        self.assertTrue(res["safety"].endswith("-restore.zip"))
        self.app.snapshot_restore(name)
        self.assertIn("Ahoj.", self.p2.read_text(encoding="utf-8"))
        v = self.app.entry_history("a.rpy", e.line)["versions"]
        self.assertEqual(v[0]["via"], "obnovení ze zálohy")

    def test_the_restore_snapshot_lets_you_undo_a_restore(self):
        name = self.app.snapshot_create()["snapshot"]["name"]
        e = self.app.project.entries("a.rpy")[0]
        self.app.entry_save("a.rpy", e.line, "Čau.")
        edited = self.p1.read_text(encoding="utf-8")
        res = self.app.snapshot_restore(name)
        self.app.snapshot_restore(res["safety"])
        self.assertEqual(self.p1.read_text(encoding="utf-8"), edited)

    def test_names_are_validated_and_a_zip_cannot_write_outside_the_folder(self):
        for bad in ("../x.zip", "snap-1.zip", "snap-20260101-000000-auto.zip.exe", ""):
            with self.assertRaises(AppError):
                self.app.snapshot_restore(bad)
        d = self.root / "_progress_data" / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        evil = d / "snap-20260101-000000-manual.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("manifest.json", '{"time": "2026-01-01T00:00:00", "reason": "manual", "files": 1, "bytes": 1}')
            z.writestr("files/../../evil.rpy", "pwned")
        with self.assertRaises(AppError):
            self.app.snapshot_restore(evil.name)
        self.assertFalse((self.root.parent / "evil.rpy").exists())

    def test_prune_keeps_the_newest_and_the_manual_ones_longest(self):
        d = self.root / "_progress_data"
        for i in range(4):
            snapshots.create(self.root, d, "auto")
            time.sleep(1.05)
        snapshots.create(self.root, d, "manual")
        removed = snapshots.prune(d, 3)
        left = snapshots.list_snapshots(d)
        self.assertEqual((removed, len(left)), (2, 3))
        self.assertIn("manual", [s["reason"] for s in left])

    def test_delete(self):
        name = self.app.snapshot_create()["snapshot"]["name"]
        self.app.snapshot_delete(name)
        self.assertEqual(self.names(), [])
        with self.assertRaises(AppError):
            self.app.snapshot_delete(name)

    def test_bulk_changes_make_one_snapshot_and_it_can_be_switched_off(self):
        self.write("c.rpy", dialog("c1", "mc", "Hello.", "Ahoj.", 5))
        self.app.refresh(force=True)
        sel = [{"file": i["file"], "line": i["line"]} for i in self.app.replace_preview("Ahoj", "Čau")["items"]]
        self.app.replace_apply(sel, "Ahoj", "Čau")
        self.assertEqual([s["reason"] for s in self.app.snapshot_list()["items"]], ["bulk"])
        sel = [{"file": i["file"], "line": i["line"]} for i in self.app.replace_preview("Čau", "Nazdar")["items"]]
        self.app.replace_apply(sel, "Čau", "Nazdar")                                     # within 10 minutes: no second one
        self.assertEqual(len(self.app.snapshot_list()["items"]), 1)

    def test_switched_off_means_no_automatic_snapshots(self):
        self.app.update_settings({"snapshots": {"enabled": False}})
        self.write("c.rpy", dialog("c1", "mc", "Hello.", "Ahoj.", 5))
        self.app.refresh(force=True)
        sel = [{"file": i["file"], "line": i["line"]} for i in self.app.replace_preview("Ahoj", "Čau")["items"]]
        self.app.replace_apply(sel, "Ahoj", "Čau")
        self.app.maybe_auto_snapshot()
        time.sleep(0.3)
        self.assertEqual(self.names(), [])
        self.assertIn("snapshot_create", dir(self.app))
        self.app.snapshot_create()                                                         # manual still works
        self.assertEqual(len(self.names()), 1)

    def test_auto_snapshot_at_start_only_when_due(self):
        self.app.maybe_auto_snapshot()
        for _ in range(40):
            if self.names():
                break
            time.sleep(0.1)
        self.assertEqual([s["reason"] for s in self.app.snapshot_list()["items"]], ["auto"])
        self.app.maybe_auto_snapshot()
        time.sleep(0.3)
        self.assertEqual(len(self.names()), 1)

    def test_settings_are_validated(self):
        self.app.update_settings({"snapshots": {"interval_hours": 6, "keep": 5}})
        self.assertEqual(self.app.settings()["snapshots"], {"enabled": True, "interval_hours": 6, "keep": 5})
        for bad in ({"keep": 1}, {"interval_hours": 0}, {"keep": "x"}):
            with self.assertRaises(AppError):
                self.app.update_settings({"snapshots": bad})


class LintParseTests(unittest.TestCase):
    OUTPUT = """Ren'Py 8.1 lint report, generated at: Thu Oct 15 2026

game/script.rpy:120 The image 'eileen happy' is not loaded.
game/tl/czech/script.rpy:55 'Hello' is translated twice.
random line that is not an issue
Statistics:

The game contains 4,123 dialogue blocks, containing 52,311 words.
"""

    def test_parse_extracts_file_line_and_message(self):
        issues = lint.parse(self.OUTPUT)
        self.assertEqual([(i["file"], i["line"]) for i in issues], [("game/script.rpy", 120), ("game/tl/czech/script.rpy", 55)])
        self.assertIn("not loaded", issues[0]["message"])

    def test_run_uses_the_runner_and_reports_failure(self):
        sdk = Path(self._tmp) / "sdk"
        (sdk / "lib" / "py3-x").mkdir(parents=True)
        (sdk / "lib" / "py3-x" / "python").write_text("", encoding="utf-8")
        (sdk / "renpy.py").write_text("", encoding="utf-8")
        calls = []

        def runner(argv, cwd):
            calls.append((argv, cwd))
            return 1, self.OUTPUT
        res = lint.run(sdk, Path(self._tmp) / "game_base", runner)
        self.assertEqual((res["ok"], res["exit_code"], len(res["issues"])), (False, 1, 2))
        argv = calls[0][0]
        self.assertEqual(argv[1:2], ["-O"])
        self.assertEqual((argv[-1], Path(argv[2]).name), ("lint", "renpy.py"))

    def test_a_missing_or_wrong_sdk_gives_a_readable_error(self):
        with self.assertRaises(lint.LintError):
            lint.build_command(Path(self._tmp) / "nope", Path(self._tmp))
        empty = Path(self._tmp) / "empty"
        empty.mkdir()
        with self.assertRaises(lint.LintError):
            lint.build_command(empty, Path(self._tmp))

    def setUp(self):
        import shutil
        import tempfile
        self._tmp = tempfile.mkdtemp(prefix="lint-test-")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)


class LintInAppTests(TempCase):
    def make(self):
        base = self.tmp / "gamebase"
        proj = base / "game" / "tl" / "czech"
        proj.mkdir(parents=True)
        (proj / "tl.rpy").write_text(dialog("a1", "mc", "Hello.", "Ahoj.", 5), encoding="utf-8")
        sdk = self.tmp / "sdk"
        (sdk / "lib" / "py3-x").mkdir(parents=True)
        (sdk / "lib" / "py3-x" / "python").write_text("", encoding="utf-8")
        (sdk / "renpy.py").write_text("", encoding="utf-8")
        app = App(Config().load())
        app.open_project(proj)
        return app, sdk

    def test_start_needs_a_configured_sdk_and_game_sources(self):
        app, sdk = self.make()
        with self.assertRaises(AppError):
            app.lint_start()
        self.write("x.rpy", dialog("a1", "mc", "Hello.", "Ahoj.", 5))
        plain = self.new_app()
        plain.update_settings({"lint": {"sdk": str(sdk)}})
        with self.assertRaises(AppError):
            plain.lint_start()                                                    # no game/ folder above the translation

    def test_background_run_and_mapping_of_issues_to_translation_files(self):
        app, sdk = self.make()
        app.update_settings({"lint": {"sdk": str(sdk)}})
        self.assertEqual(app.settings()["lint"]["sdk"], str(sdk))
        out = "game/tl/czech/tl.rpy:5 something is off\ngame/other.rpy:1 elsewhere\n"
        orig = lint.run
        try:
            lint.run = lambda s, b, runner=None: orig(s, b, lambda a, c: (0, out))
            app.lint_start()
            for _ in range(50):
                st = app.lint_status()
                if st["state"] != "running":
                    break
                time.sleep(0.1)
        finally:
            lint.run = orig
        self.assertEqual(st["state"], "done")
        self.assertEqual([(i["file"], i["rel"]) for i in st["issues"]], [("game/tl/czech/tl.rpy", "tl.rpy"), ("game/other.rpy", "")])


if __name__ == "__main__":
    unittest.main()
