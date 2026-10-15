"""Text quality checks: numbers, double spaces, repeated words, leftover English, glossary terms, encoding."""
import unittest

from helpers import TempCase, dialog

from prehled import rpy, validator


def codes(src, tgt):
    return [i.code for i in validator.check_quality(src, tgt)]


class QualityTests(unittest.TestCase):
    def test_changed_number_is_a_warning(self):
        iss = validator.check_quality("I need 14 people.", "Potřebuju 15 lidí.")
        self.assertEqual([(i.code, i.severity) for i in iss], [("numbers-differ", "warning")])

    def test_number_written_in_words_is_only_info(self):
        iss = validator.check_quality("I need 14 people.", "Potřebuju čtrnáct lidí.")
        self.assertEqual([(i.code, i.severity) for i in iss], [("numbers-differ", "info")])

    def test_same_numbers_and_tags_are_fine(self):
        self.assertEqual(codes("At {b}5{/b} p.m. [name]", "V {b}5{/b} odpoledne. [name]"), [])

    def test_double_space_only_when_source_has_none(self):
        self.assertEqual(codes("Hello there.", "Ahoj  tam."), ["double-space"])
        self.assertEqual(codes("Hello  there.", "Ahoj  tam."), [])

    def test_repeated_word(self):
        self.assertEqual(codes("So so.", "Tak tak."), [])          # in the allow-list
        self.assertEqual(codes("She is here.", "Ona je je tady."), ["repeated-word"])
        self.assertEqual(codes("Danger danger!", "Danger danger!"), [])              # source repeats too

    def test_leftover_english(self):
        self.assertEqual(codes("I really do not know.", "Já don't know what to say."), ["english-left"])
        self.assertEqual(codes("Hello, my friend!", "Hello, příteli!"), [])           # one interjection is fine

    def test_term_consistency_allows_czech_endings(self):
        terms = {"Dik Coins": "dikmince"}
        self.assertEqual(validator.check_terms("Take the Dik Coins.", "Vezmi si ty dikmince.", terms), [])
        self.assertEqual(validator.check_terms("Take the Dik Coins.", "Vezmi si dikminci.", terms), [])
        bad = validator.check_terms("Take the Dik Coins.", "Vezmi si ty peníze.", terms)
        self.assertEqual([(i.code, i.severity) for i in bad], [("term-inconsistent", "info")])
        self.assertEqual(validator.check_terms("Nothing here.", "Nic tu není.", terms), [])

    def test_non_utf8_file_is_reported(self):
        data = 'translate czech a1:\n\n    # mc "Hi"\n    mc "Ahoj"\n'.encode("utf-8") + b"\n# \xe9\n"
        parsed = rpy.parse_bytes(data)
        self.assertIn("bad-encoding", [c for _l, c, _m in parsed.structure])
        self.assertNotIn("bad-encoding", [c for _l, c, _m in rpy.parse_bytes(b"# ok\n").structure])


class TermsInAppTests(TempCase):
    def test_glossary_term_is_checked_and_follows_edits(self):
        self.write("script.rpy", dialog("a1", "mc", "Take the Dik Coins.", "Vezmi si peníze.", 5))
        app = self.new_app()
        app.glossary_set([{"code": "Dik Coins", "name": "dikmince", "type": "term"}])
        res = app.validation_list(severity="info")
        self.assertEqual([i["code"] for i in res["items"]], ["term-inconsistent"])
        app.glossary_set([{"code": "Dik Coins", "name": "peníze", "type": "term"}])
        self.assertEqual(app.validation_list(severity="info")["total"], 0)


if __name__ == "__main__":
    unittest.main()
