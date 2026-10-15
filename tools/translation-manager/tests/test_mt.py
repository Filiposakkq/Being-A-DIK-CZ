"""Optional machine translation: placeholder protection, providers (fake HTTP), consent, key privacy."""
import json
import unittest
import urllib.parse

from helpers import TempCase, dialog

from prehled import mt
from prehled.app import AppError


class FakeHttp:
    def __init__(self, status=200, reply=None):
        self.status, self.reply, self.calls = status, reply, []

    def __call__(self, url, headers, data):
        self.calls.append((url, headers, data))
        body = self.reply(url, headers, data) if callable(self.reply) else self.reply
        return self.status, body if isinstance(body, str) else json.dumps(body)


CFG = {"provider": "deepl", "api_key": "secret:fx", "consent": True, "source_lang": "EN", "target_lang": "CS"}


class PlaceholderTests(unittest.TestCase):
    def test_tags_variables_and_escapes_are_protected_and_restored(self):
        text = "{i}Hello{/i} [name]!\\nBye."
        protected, tokens = mt.protect(text)
        self.assertEqual(tokens, ["{i}", "{/i}", "[name]", "\\n"])
        self.assertNotIn("[name]", protected)
        back, warnings = mt.restore(protected, tokens)
        self.assertEqual((back, warnings), (text, []))

    def test_markup_is_escaped_for_xml_services_and_restored(self):
        protected, tokens = mt.protect("a < b & c [x]", escape=True)
        self.assertIn("&lt;", protected)
        back, _w = mt.restore(protected, tokens, unescape=True)
        self.assertEqual(back, "a < b & c [x]")

    def test_lost_and_duplicated_placeholders_are_reported(self):
        _p, tokens = mt.protect("Hi [a] and [b]")
        back, warnings = mt.restore('Ahoj <x id="1"/> <x id="1"/>', tokens)
        self.assertEqual(len(warnings), 2)
        self.assertIn("[b]", warnings[0])
        self.assertIn("[a]", warnings[1])
        self.assertEqual(back, "Ahoj [a] [a]")

    def test_tolerates_spacing_and_quotes_in_the_returned_tag(self):
        back, w = mt.restore("Ahoj < x id='1' / > a <X ID=\"2\"/>", ["[a]", "[b]"])
        self.assertEqual((back, w), ("Ahoj [a] a [b]", []))


class ProviderTests(unittest.TestCase):
    def test_deepl_request_and_response(self):
        http = FakeHttp(reply={"translations": [{"text": 'Ahoj <x id="1"/>!'}]})
        res = mt.translate(CFG, "Hello [name]!", http=http)
        self.assertEqual((res["text"], res["warnings"], res["provider"]), ("Ahoj [name]!", [], "deepl"))
        url, headers, data = http.calls[0]
        self.assertEqual(url, "https://api-free.deepl.com/v2/translate")                      # a :fx key = the free API
        self.assertEqual(headers["Authorization"], "DeepL-Auth-Key secret:fx")
        form = urllib.parse.parse_qs(data.decode("utf-8"))
        self.assertEqual((form["target_lang"], form["tag_handling"]), (["CS"], ["xml"]))
        self.assertNotIn("[name]", form["text"][0])                                          # the variable never leaves the app

    def test_deepl_paid_key_uses_the_paid_host(self):
        http = FakeHttp(reply={"translations": [{"text": "x"}]})
        mt.translate(dict(CFG, api_key="abc"), "Hi", http=http)
        self.assertEqual(http.calls[0][0], "https://api.deepl.com/v2/translate")

    def test_openai_compatible_gets_context_glossary_and_a_cleaned_answer(self):
        http = FakeHttp(reply={"choices": [{"message": {"content": '"Vezmi si <x id="1"/>."'}}]})
        cfg = {"provider": "openai", "api_key": "k", "consent": True, "model": "m1", "base_url": "http://localhost:1234/v1/"}
        res = mt.translate(cfg, "Take [item].", {"Dik Coins": "dikmince"}, ["Previous line."], http=http)
        self.assertEqual(res["text"], "Vezmi si [item].")
        url, headers, data = http.calls[0]
        body = json.loads(data)
        self.assertEqual(url, "http://localhost:1234/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer k")
        self.assertEqual(body["model"], "m1")
        self.assertIn("Dik Coins = dikmince", body["messages"][0]["content"])
        self.assertIn("Previous line.", body["messages"][1]["content"])

    def test_libretranslate(self):
        http = FakeHttp(reply={"translatedText": 'Ahoj &amp; ahoj <x id="1"/>'})
        res = mt.translate({"provider": "libretranslate", "consent": True, "base_url": "https://lt.example"}, "Hi & hi [a]", http=http)
        self.assertEqual(res["text"], "Ahoj & ahoj [a]")
        self.assertEqual(http.calls[0][0], "https://lt.example/translate")
        self.assertEqual(json.loads(http.calls[0][2])["target"], "cs")

    def test_gates_and_errors_are_readable_and_never_contain_the_key(self):
        for cfg, text in ((dict(CFG, provider=""), "Hi"), (dict(CFG, consent=False), "Hi"), (dict(CFG, api_key=""), "Hi"), (CFG, "   ")):
            with self.assertRaises(mt.MTError):
                mt.translate(cfg, text, http=FakeHttp(reply={}))
        for status, word in ((403, "klíč"), (429, "limit"), (456, "kvóta")):
            with self.assertRaises(mt.MTError) as cm:
                mt.translate(CFG, "Hi", http=FakeHttp(status, "nope"))
            self.assertIn(word, str(cm.exception))
            self.assertNotIn("secret", str(cm.exception))
        with self.assertRaises(mt.MTError):
            mt.translate(CFG, "Hi", http=FakeHttp(reply="not json"))
        with self.assertRaises(mt.MTError):
            mt.translate(CFG, "Hi", http=FakeHttp(reply={"unexpected": 1}))
        with self.assertRaises(mt.MTError):
            mt.translate(dict(CFG, base_url="ftp://x"), "Hi", http=FakeHttp(reply={}))


class MTInAppTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "Before.", "Předtím.", 5) + dialog("a2", "mc", "Take the Dik Coins [name].", None, 9))
        self.app = self.new_app()
        self.line = next(e.line for e in self.app.project.entries("a.rpy") if e.pending)

    def configure(self, **kw):
        patch = {"provider": "deepl", "api_key": "secret:fx", "consent": True}
        patch.update(kw)
        self.app.update_settings({"mt": patch})

    def test_off_by_default_and_the_key_is_never_returned(self):
        with self.assertRaises(AppError):
            self.app.mt_suggest("a.rpy", self.line)
        self.configure()
        s = self.app.settings()["mt"]
        self.assertEqual((s["api_key"], s["has_key"], s["provider"], s["consent"]), ("", True, "deepl", True))
        self.assertNotIn("secret", json.dumps(self.app.settings()))

    def test_a_suggestion_carries_validator_findings_and_is_not_saved(self):
        self.configure()
        http = FakeHttp(reply={"translations": [{"text": "Vezmi si dikmince."}]})                   # the variable was lost
        self.app._mt_http = http
        res = self.app.mt_suggest("a.rpy", self.line)
        self.assertEqual(res["suggestion"], "Vezmi si dikmince.")
        self.assertTrue(any(i["code"] == "variable-missing" for i in res["issues"]) or res["warnings"])
        self.assertEqual([e.target for e in self.app.project.entries("a.rpy") if e.pending], ["Take the Dik Coins [name]."])

    def test_empty_key_field_keeps_the_stored_key_and_clear_removes_it(self):
        self.configure()
        self.app.update_settings({"mt": {"api_key": "", "model": "x"}})
        self.assertTrue(self.app.settings()["mt"]["has_key"])
        self.app.update_settings({"mt": {"clear_key": True}})
        self.assertFalse(self.app.settings()["mt"]["has_key"])

    def test_settings_are_validated(self):
        with self.assertRaises(AppError):
            self.app.update_settings({"mt": {"provider": "evil"}})
        with self.assertRaises(AppError):
            self.app.update_settings({"mt": {"base_url": "file:///etc/passwd"}})
        self.assertEqual(self.app.settings()["mt"]["provider"], "")

    def test_service_errors_become_readable_messages(self):
        self.configure()
        self.app._mt_http = FakeHttp(403, "forbidden")
        with self.assertRaises(AppError) as cm:
            self.app.mt_suggest("a.rpy", self.line)
        self.assertIn("klíč", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
