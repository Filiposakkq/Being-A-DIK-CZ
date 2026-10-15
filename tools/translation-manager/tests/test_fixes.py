"""Auto-fix of speaker / attribute / trailing-code differences (the only .rpy-writing feature)."""
import unittest

from helpers import TempCase, dialog
from prehled.app import AppError


def block(ident, src_who, tgt_who, src, tgt, src_suffix="", tgt_suffix=""):
    return (f"# game/x.rpy:1\ntranslate czech {ident}:\n\n"
            f'    # {src_who} "{src}"{src_suffix}\n    {tgt_who} "{tgt}"{tgt_suffix}\n\n')


class FixTests(TempCase):
    def setUp(self):
        super().setUp()
        self.text = (block("a1", "mc happy", "mc sad", "Hello there.", "Ahoj tam.")
                     + block("a2", "de", "de", "Fine.", "Dobře.")
                     + block("a3", "mc", "mc", "Bang!", "Bum!", " with vpunch", "")
                     + block("a4", "mc", "de", "Same words", "Same words"))
        self.path = self.write("script.rpy", self.text)
        self.app = self.new_app()

    def codes(self):
        return [r["code"] for r in self.app.validation_list(severity="error")["items"]]

    def test_issue_is_marked_fixable(self):
        items = self.app.validation_list(severity="error")["items"]
        self.assertTrue(items)
        self.assertTrue(all(i["extra"].get("fixable") for i in items if i["code"] in ("speaker-changed", "suffix-changed")))

    def test_preview_writes_nothing(self):
        before = self.path.read_bytes()
        pv = self.app.fix_preview()
        self.assertEqual(self.path.read_bytes(), before)
        afters = {p["line"]: p["after"] for p in pv["items"]}
        self.assertIn('mc happy "Ahoj tam."', afters.values())

    def test_fix_all_copies_speaker_and_suffix_but_keeps_text(self):
        res = self.app.fix_apply()
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('    mc happy "Ahoj tam."', text)
        self.assertIn('    mc "Bum!" with vpunch', text)
        self.assertNotIn("mc sad", text)
        self.assertEqual(res["fixed"], 2)
        self.assertTrue(res["backups"])
        self.assertEqual(self.codes(), ["speaker-changed"])   # only the skipped line (see next test) remains

    def test_untranslated_line_with_other_speaker_is_skipped(self):
        res = self.app.fix_apply()
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('    de "Same words"', text)     # would become identical to the original: left alone
        self.assertEqual(len(res["skipped"]), 1)

    def test_single_item_only_touches_that_line(self):
        line = next(i["line"] for i in self.app.validation_list(severity="error")["items"] if i["code"] == "speaker-changed")
        self.app.fix_apply(items=[{"file": "script.rpy", "line": line}])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('mc happy "Ahoj tam."', text)
        self.assertNotIn('mc "Bum!" with vpunch', text)

    def test_refuses_when_file_changed_on_disk(self):
        self.app.fix_preview()
        self.path.write_text(self.text + "\n# edited elsewhere\n", encoding="utf-8")
        with self.assertRaises(AppError):
            self.app.fix_apply()
        self.assertNotIn("mc happy \"Ahoj tam.\"", self.path.read_text(encoding="utf-8"))

    def test_keeps_crlf_and_bom(self):
        raw = ("﻿" + self.text).replace("\n", "\r\n").encode("utf-8")
        self.path.write_bytes(raw)
        app = self.new_app()
        app.fix_apply()
        out = self.path.read_bytes()
        self.assertTrue(out.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", out.replace(b"\r\n", b""))
        self.assertIn(b'mc happy "Ahoj tam."', out)

    def test_nothing_to_fix(self):
        self.write("script.rpy", dialog("a1", "mc", "Hello.", "Ahoj."))
        app = self.new_app()
        with self.assertRaises(AppError):
            app.fix_apply()


if __name__ == "__main__":
    unittest.main()
