"""Website content and project assets: links, licenses, logo / icon files."""
import re
import struct
import unittest
import xml.dom.minidom
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
KOFI = "https://ko-fi.com/filiposakkq"
REPO_URL = "https://github.com/Filiposakkq/Being-A-DIK-CZ"


class SiteContentTests(unittest.TestCase):
    def setUp(self):
        self.html = (REPO / "web" / "index.html").read_text(encoding="utf-8")

    def test_links_to_kofi_and_repo(self):
        self.assertIn(f'href="{KOFI}"', self.html)
        self.assertIn(f'href="{REPO_URL}"', self.html)
        self.assertGreaterEqual(self.html.count(KOFI), 3)            # header, support box, contact/footer

    def test_every_new_tab_link_is_noopener(self):
        for tag in re.findall(r"<a [^>]*target=\"_blank\"[^>]*>", self.html):
            self.assertIn("noopener", tag, tag)

    def test_accuracy_note_is_bilingual(self):
        self.assertIn("Procenta jsou orientační", self.html)
        self.assertIn("Percentages are approximate", self.html)

    def test_license_and_contact_section(self):
        for needle in ("CC BY-NC 4.0", "MIT", "BaDIK Translation Manager", "@filiposakkq", "TRANSLATION-LICENSE.md",
                       "tools/translation-manager/LICENSE", "/issues"):
            self.assertIn(needle, self.html, needle)

    ALLOWED_GAME_IMAGES = {"hero-party.jpg", "title-art.jpg", "scene-guitar.jpg", "scene-bench.jpg", "scene-dinner.jpg"}

    def test_only_the_approved_press_kit_images_are_on_the_site(self):
        """Game images are limited to the reviewed press-kit set in web/assets/game, with credit and a removal promise."""
        game = {p.name for p in (REPO / "web" / "assets" / "game").iterdir() if p.suffix == ".jpg"}
        self.assertEqual(game, self.ALLOWED_GAME_IMAGES)
        self.assertEqual({p.name for p in (REPO / "web" / "assets").iterdir() if p.is_file()}, {"crest.svg"})
        used = set(re.findall(r'(?:src|href)="([^"]+\.(?:png|jpe?g|webp|gif))"', self.html))
        self.assertEqual({u.split("/")[-1] for u in used}, self.ALLOWED_GAME_IMAGES)
        self.assertTrue(all(u.startswith("assets/game/") for u in used), used)
        self.assertIn("© DrPinkCake", self.html)
        self.assertIn("ihned odstraním", self.html)
        self.assertIn("will remove them immediately", self.html)
        self.assertIn("igdb.com/games/being-a-dik/presskit", self.html)
        self.assertTrue((REPO / "web" / "assets" / "game" / "README.md").is_file())

    def test_disclaimer_no_longer_claims_there_are_no_game_images(self):
        self.assertNotIn("žádné z nich nenajdeš", self.html)
        self.assertNotIn("None of them are on this site", self.html)

    def test_game_images_are_small_enough_for_a_fast_page(self):
        total = sum(p.stat().st_size for p in (REPO / "web" / "assets" / "game").glob("*.jpg"))
        self.assertLess(total, 600 * 1024)


class LicenseTests(unittest.TestCase):
    def test_manager_has_its_own_restrictive_license(self):
        text = (REPO / "tools" / "translation-manager" / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("WRITTEN PERMISSION", text)
        self.assertIn("non-commercial", text)
        self.assertIn("Filiposakkq", text)

    def test_root_mit_license_excludes_the_manager(self):
        text = (REPO / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("does NOT apply to tools/translation-manager/", text)
        self.assertNotIn("(web/, tools/)", text)

    def test_translation_license_is_final_not_a_draft(self):
        text = (REPO / "TRANSLATION-LICENSE.md").read_text(encoding="utf-8")
        self.assertNotIn("DRAFT", text.upper())
        self.assertIn("CC BY-NC 4.0", text)

    def test_readme_lists_all_three_licenses(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        for needle in ("CC BY-NC 4.0", "MIT", "vlastní licence", "ko-fi.com/filiposakkq", "web/assets/game"):
            self.assertIn(needle, text)

    def test_licenses_say_the_game_images_are_not_covered(self):
        self.assertIn("web/assets/game", (REPO / "LICENSE").read_text(encoding="utf-8"))


class LogoTests(unittest.TestCase):
    def test_svgs_are_valid_xml(self):
        for f in ("web/assets/crest.svg", "web/favicon.svg",
                  "tools/translation-manager/prehled/ui/crest.svg", "tools/translation-manager/prehled/ui/favicon.svg"):
            xml.dom.minidom.parse(str(REPO / f))

    def test_app_logo_is_the_website_logo(self):
        ui = REPO / "tools" / "translation-manager" / "prehled" / "ui"
        self.assertEqual((ui / "crest.svg").read_bytes(), (REPO / "web" / "assets" / "crest.svg").read_bytes())
        self.assertEqual((ui / "favicon.svg").read_bytes(), (REPO / "web" / "favicon.svg").read_bytes())

    def test_exe_icon_is_a_multi_size_ico_of_pngs(self):
        data = (REPO / "tools" / "translation-manager" / "assets" / "icon.ico").read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        self.assertGreaterEqual(count, 6)
        sizes = set()
        for i in range(count):
            w, h, _c, _r, _planes, bpp, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(w, h)
            sizes.add(w or 256)
        self.assertTrue({16, 32, 48, 256} <= sizes, sizes)

    def test_spec_uses_the_icon(self):
        spec = (REPO / "tools" / "translation-manager" / "BaDIKTranslationManager.spec").read_text(encoding="utf-8")
        self.assertIn("icon.ico", spec)


if __name__ == "__main__":
    unittest.main()
