"""Parsing, counting, storage, atomic writes and project refresh."""
import os
import unittest
from unittest import mock

from helpers import TempCase, dialog, rel, strings

from prehled import rpy, util
from prehled.project import Project, check_project_dir, file_status
from prehled.store import Store, assign_from_text, parse_value, valid_assign


class ParserTests(unittest.TestCase):
    def test_counts_dialogue_and_strings(self):
        text = (dialog("a", "mc", "Hello there, friend.", "Ahoj, příteli.")
                + dialog("b", "mc", "I do not know what this is.")        # identical -> untranslated
                + dialog("c", "mc", "Hmm...")                              # identical, no English words
                + strings(("Start", "Začít"), ("Quit", "Quit"), ("Empty", "")))
        p = rpy.parse_text(text)
        self.assertEqual(len(p.entries), 6)
        self.assertEqual(rpy.count(p.entries), (2, 4, 0))
        cats = {e.source: e.category for e in p.entries if e.pending}
        self.assertEqual(cats["I do not know what this is."], rpy.K_ENGLISH)
        self.assertEqual(cats["Hmm..."], rpy.K_SAME)
        self.assertEqual(cats["Empty"], rpy.K_EMPTY)

    def test_manual_approval_counts_as_translated(self):
        p = rpy.parse_text(dialog("b", "mc", "I do not know what this is."))
        key = p.entries[0].key
        self.assertEqual(rpy.count(p.entries, {key}), (1, 0, 1))

    def test_symbols_only_policy(self):
        p = rpy.parse_text(dialog("s", "mc", "..."))
        self.assertEqual(rpy.count(p.entries, symbols_as_done=False), (0, 1, 0))
        self.assertEqual(rpy.count(p.entries, symbols_as_done=True), (1, 0, 0))

    def test_non_dialogue_lines_are_not_counted(self):
        text = 'translate czech x:\n\n    # voice "a.ogg"\n    voice "a.ogg"\n    # mc "Hi"\n    mc "Ahoj"\n    $ x = "y"\n'
        p = rpy.parse_text(text)
        self.assertEqual(len(p.entries), 1)

    def test_line_numbers_point_at_translated_line(self):
        text = "\n\n" + dialog("a", "mc", "Hello", "Ahoj")
        p = rpy.parse_text(text)
        lines = text.split("\n")
        self.assertIn('mc "Ahoj"', lines[p.entries[0].line - 1])
        self.assertIn('mc "Hello"', lines[p.entries[0].src_line - 1])

    def test_crlf_and_bom(self):
        text = "\ufeff" + dialog("a", "mc", "Hello", "Ahoj").replace("\n", "\r\n")
        p = rpy.parse_text(text)
        self.assertEqual(p.entries[0].target, "Ahoj")
        self.assertEqual(p.block_ids, [("czech", "a", 2)])

    def test_old_without_new_reported(self):
        p = rpy.parse_text('translate czech strings:\n\n    old "A"\n    old "B"\n    new "B2"\n')
        self.assertTrue(any(code == "old-without-new" for _l, code, _m in p.structure))

    def test_pairing_by_speaker_when_counts_differ(self):
        text = 'translate czech x:\n\n    # mc "One"\n    # de "Two"\n    de "Dvě"\n'
        e = rpy.parse_text(text).entries[0]
        self.assertEqual(e.source, "Two")


class AtomicWriteTests(TempCase):
    def test_atomic_write_and_backup(self):
        target = self.tmp / "d" / "f.csv"
        util.atomic_write_text(target, "one")
        util.atomic_write_text(target, "two", backup_dir=self.tmp / "bk")
        self.assertEqual(target.read_text(), "two")
        self.assertEqual(len(list((self.tmp / "bk").glob("f.csv.*.bak"))), 1)
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_backup_rotation(self):
        f = self.tmp / "a.csv"
        f.write_text("x")
        for _ in range(5):
            util.make_backup(f, self.tmp / "bk", keep=3, min_interval=0)
        self.assertEqual(len(list((self.tmp / "bk").glob("a.csv.*.bak"))), 3)

    def test_locked_file_reports_friendly_error_and_keeps_original(self):
        target = self.tmp / "korekce.csv"
        target.write_text("original")
        with mock.patch("os.replace", side_effect=PermissionError):
            with self.assertRaises(util.WriteFailed) as cm:
                util.atomic_write_text(target, "new", )
        self.assertIn("zamčený", cm.exception.reason)
        self.assertEqual(target.read_text(), "original")
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_csv_roundtrip_excel_format(self):
        p = self.tmp / "x.csv"
        util.write_csv(p, [["soubor", "hodnota"], ["a;b", "č"]])
        raw = p.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(util.read_rows(p), [["soubor", "hodnota"], ["a;b", "č"]])


class StoreTests(TempCase):
    def test_reads_legacy_files_and_preserves_them(self):
        d = self.tmp / "data"
        d.mkdir()
        (d / "prirazeni.csv").write_text("\ufeffsoubor;zarazeni\nscript.rpy;Epizoda 1\nheader.rpy;Obecné\n", encoding="utf-8")
        (d / "schvaleno.csv").write_text("\ufeffsoubor;blok;original\nscript.rpy;strings;Quit\n", encoding="utf-8")
        (d / "korekce.csv").write_text("\ufeffsoubor;zkontrolovano;prelozeno_rucne\nscript.rpy;5;\n", encoding="utf-8")
        (d / "epizody.csv").write_text("\ufeffepizoda;stav\n1;Rozpracováno\n", encoding="utf-8")
        s = Store(d).load()
        self.assertEqual(s.assign, {"script.rpy": "ep:1", "header.rpy": "gen"})
        self.assertEqual(s.approved["script.rpy"], {("strings", "Quit")})
        self.assertEqual(s.corr["script.rpy"], {"c": "5", "t": ""})
        self.assertEqual(s.episodes, {1: "wip"})
        s.save("assign")
        self.assertEqual(Store(d).load().assign, s.assign)

    def test_invalid_assignment_is_ignored_with_warning(self):
        d = self.tmp / "data"
        d.mkdir()
        (d / "prirazeni.csv").write_text("soubor;zarazeni\na.rpy;Epizoda 9\n", encoding="utf-8")
        s = Store(d).load()
        self.assertEqual(s.assign, {})
        self.assertTrue(s.warnings)

    def test_assignment_validity_follows_season_model(self):
        for n in range(1, 9):
            self.assertTrue(valid_assign(f"ep:{n}"))
        self.assertFalse(valid_assign("ep:9"))
        self.assertFalse(valid_assign("ep:0"))
        self.assertTrue(valid_assign("gen") and valid_assign(""))
        self.assertEqual(assign_from_text("Epizoda 7"), "ep:7")

    def test_undo_restores_previous_state_and_disk(self):
        s = Store(self.tmp / "data")
        s.change("a", ("assign",), lambda: s.assign.update({"x.rpy": "ep:1"}))
        s.change("b", ("assign",), lambda: s.assign.update({"x.rpy": "ep:2", "y.rpy": "gen"}))
        self.assertEqual(s.undo(), "b")
        self.assertEqual(s.assign, {"x.rpy": "ep:1"})
        self.assertEqual(Store(self.tmp / "data").load().assign, {"x.rpy": "ep:1"})
        self.assertEqual(s.undo(), "a")
        self.assertIsNone(s.undo())

    def test_failed_save_rolls_memory_back(self):
        s = Store(self.tmp / "data")
        s.assign["a.rpy"] = "gen"
        with mock.patch.object(Store, "save", side_effect=util.WriteFailed("x", "locked")):
            with self.assertRaises(util.WriteFailed):
                s.change("x", ("assign",), lambda: s.assign.update({"b.rpy": "ep:1"}))
        self.assertEqual(s.assign, {"a.rpy": "gen"})

    def test_parse_value(self):
        self.assertEqual(parse_value("50%", 200), 100)
        self.assertEqual(parse_value("ano", 7), 7)
        self.assertEqual(parse_value("12", 7), 7)
        self.assertIsNone(parse_value("abc", 7))
        self.assertIsNone(parse_value("", 7))


class ProjectTests(TempCase):
    def project(self):
        s = Store(self.root / "_progress_data").load()
        p = Project(self.root, s, skip={"common.rpy"})
        return p, s

    def test_discovery_skips_data_dir_and_skip_list(self):
        self.basic_project()
        self.write("common.rpy", dialog("z", "mc", "Skip me"))
        self.write(rel("_progress_data", "x.rpy"), dialog("z", "mc", "Never"))
        p, _ = self.project()
        rep = p.refresh()
        self.assertEqual(sorted(p.files), sorted(["script.rpy", rel("scripts", "episode2", "ep2_party.rpy"),
                                                  rel("season2", "scripts", "update5.rpy"), "options.rpy"]))
        self.assertEqual(len(rep.added), 4)

    def test_files_without_translatable_lines_are_ignored(self):
        self.write("empty.rpy", "# nothing here\n")
        self.write("a.rpy", dialog("a", "mc", "Hello", "Ahoj"))
        p, _ = self.project()
        rep = p.refresh()
        self.assertEqual(list(p.files), ["a.rpy"])
        self.assertIn("empty.rpy", rep.empty)

    def test_refresh_detects_added_modified_removed(self):
        self.basic_project()
        p, _ = self.project()
        p.refresh()
        self.assertEqual(p.refresh().unchanged, 4)
        self.assertFalse(p.last_report.changed)
        self.write("new.rpy", dialog("n", "mc", "Hello", "Ahoj"))
        self.write("script.rpy", dialog("a1", "mc", "Hello there, friend.", "Ahoj tam, příteli."))
        (self.root / "options.rpy").unlink()
        rep = p.refresh()
        self.assertEqual(rep.added, ["new.rpy"])
        self.assertEqual(rep.modified, ["script.rpy"])
        self.assertEqual(rep.removed, ["options.rpy"])
        self.assertNotIn("options.rpy", p.files)
        self.assertEqual(p.counts("script.rpy"), (1, 0, 0))

    def test_refresh_only_reparses_changed_files(self):
        self.basic_project()
        p, _ = self.project()
        p.refresh()
        before = {k: id(v.parsed) for k, v in p.files.items()}
        self.write("script.rpy", dialog("a1", "mc", "Hello", "Ahoj"))
        p.refresh()
        after = {k: id(v.parsed) for k, v in p.files.items()}
        self.assertNotEqual(before["script.rpy"], after["script.rpy"])
        self.assertEqual(before["options.rpy"], after["options.rpy"])

    def test_rename_detected_and_metadata_migrated(self):
        self.basic_project()
        p, s = self.project()
        p.refresh()
        s.corr["options.rpy"] = {"c": "1", "t": ""}
        s.assign["options.rpy"] = "gen"
        s.approved["options.rpy"] = {("strings", "Quit")}
        os.rename(self.root / "options.rpy", self.root / "gui_options.rpy")
        rep = p.refresh()
        self.assertEqual(rep.renamed, [("options.rpy", "gui_options.rpy")])
        self.assertEqual(rep.added, [])
        self.assertEqual(p.migrate_metadata(rep.renamed), 1)
        self.assertEqual(s.assign["gui_options.rpy"], "gen")
        self.assertNotIn("options.rpy", s.assign)
        self.assertEqual(s.corr["gui_options.rpy"]["c"], "1")
        self.assertEqual(s.approved["gui_options.rpy"], {("strings", "Quit")})
        self.assertEqual(Store(self.root / "_progress_data").load().assign["gui_options.rpy"], "gen")

    def test_metadata_of_removed_file_survives(self):
        self.basic_project()
        p, s = self.project()
        p.refresh()
        s.assign["options.rpy"] = "gen"
        s.save("assign")
        (self.root / "options.rpy").unlink()
        p.refresh()
        self.assertEqual(s.assign["options.rpy"], "gen")
        self.write("options.rpy", strings(("Start", "Začít")))
        p.refresh()
        self.assertIn("options.rpy", p.files)
        self.assertEqual(s.assign["options.rpy"], "gen")

    def test_unreadable_file_keeps_last_known_state(self):
        self.basic_project()
        p, _ = self.project()
        p.refresh()
        self.write("script.rpy", dialog("a1", "mc", "Hello", "Ahoj"))
        real = type(self.root / "x").read_bytes

        def boom(self_, *a, **k):
            if self_.name == "script.rpy":
                raise PermissionError("locked")
            return real(self_, *a, **k)
        with mock.patch("pathlib.Path.read_bytes", boom):
            rep = p.refresh()
        self.assertTrue(rep.errors)
        self.assertIn("script.rpy", p.files)
        self.assertEqual(p.counts("script.rpy")[0] + p.counts("script.rpy")[1], 3)

    def test_missing_project_dir_raises(self):
        p, _ = self.project()
        p.root = self.tmp / "gone"
        from prehled.project import ProjectUnavailable
        with self.assertRaises(ProjectUnavailable):
            p.refresh()

    def test_path_of_rejects_escape(self):
        self.basic_project()
        p, _ = self.project()
        p.refresh()
        with self.assertRaises(ValueError):
            p.path_of(rel("..", "outside.rpy"))

    def test_rows_with_manual_override(self):
        self.basic_project()
        p, s = self.project()
        p.refresh()
        s.corr["script.rpy"] = {"c": "2", "t": "3"}
        row = p.row("script.rpy")
        self.assertEqual((row.done, row.corr, row.auto, row.total), (3, 2, 1, 3))
        self.assertEqual(file_status(row.done, row.todo, row.total, row.corr), "rev")   # all translated, some proofread

    def test_check_project_dir(self):
        ok, msg = check_project_dir(self.tmp / "nope")
        self.assertFalse(ok)
        self.assertIn("neexistuje", msg)
        ok, msg = check_project_dir(self.root)
        self.assertFalse(ok)
        self.assertIn("žádné soubory .rpy", msg)
        self.write("a.rpy", dialog("a", "mc", "A", "B"))
        self.assertEqual(check_project_dir(self.root), (True, ""))
        self.assertFalse(check_project_dir("")[0])


if __name__ == "__main__":
    unittest.main()
