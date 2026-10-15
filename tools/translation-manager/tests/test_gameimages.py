"""RPA archives (read-only), image names of a game, and the picture behind a script line."""
import http.client
import json
import pickle
import struct
import unittest
import zlib
from pathlib import Path

from helpers import TempCase, dialog

from prehled import gameimages, rpa, server
from prehled.app import App, AppError
from prehled.config import Config

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-data" * 4
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-data" * 4


def make_rpa(path, files, key=0x42424242, version=3, prefix=""):
    """Write a small valid archive: header line, data, zlib(pickle(index))."""
    header_len = 34 if version == 3 else 25
    body, index = b"", {}
    for name, data in files.items():
        off = header_len + len(body)
        body += data
        index[name] = [((off ^ key, len(data) ^ key, prefix) if version == 3 else (off, len(data)))]
    idx_off = header_len + len(body)
    blob = zlib.compress(pickle.dumps(index, protocol=2))
    head = (f"RPA-3.0 {idx_off:016x} {key:08x}\n" if version == 3 else f"RPA-2.0 {idx_off:016x}\n").encode("latin-1")
    assert len(head) == header_len, len(head)
    Path(path).write_bytes(head + body + blob)


class RpaTests(TempCase):
    def test_roundtrip_of_both_versions(self):
        for version in (3, 2):
            p = self.tmp / f"v{version}.rpa"
            make_rpa(p, {"images/a/one.jpg": JPEG, "images/two.png": PNG}, version=version)
            ver, idx = rpa.read_index(p)
            self.assertEqual((ver, sorted(idx)), (f"RPA-{version}.0", ["images/a/one.jpg", "images/two.png"]))
            self.assertEqual(rpa.read_entry(p, idx["images/a/one.jpg"]), JPEG)
            self.assertEqual(rpa.read_entry(p, idx["images/two.png"]), PNG)

    def test_prefix_is_put_back(self):
        p = self.tmp / "p.rpa"
        make_rpa(p, {"x.jpg": JPEG[4:]}, prefix=JPEG[:4].decode("latin-1"))
        # with a prefix the stored length includes it: simulate by storing len(data)+len(prefix)
        _ver, idx = rpa.read_index(p)
        off, length, pre = idx["x.jpg"]
        self.assertEqual(pre, JPEG[:4])
        self.assertEqual(rpa.read_entry(p, (off, length + len(pre), pre)), JPEG)

    def test_a_hostile_index_cannot_run_code(self):
        marker = self.tmp / "pwned.txt"

        class Evil:
            def __reduce__(self):
                return (Path.write_text, (marker, "pwned"))
        blob = zlib.compress(pickle.dumps({"x.jpg": [(0, 1, Evil())]}, protocol=2))
        head = f"RPA-3.0 {34:016x} {0:08x}\n".encode("latin-1")
        (self.tmp / "evil.rpa").write_bytes(head + blob)
        with self.assertRaises(rpa.RpaError):
            rpa.read_index(self.tmp / "evil.rpa")
        self.assertFalse(marker.exists())

    def test_garbage_and_decompression_bombs_are_refused(self):
        (self.tmp / "g.rpa").write_bytes(b"not an archive\n")
        with self.assertRaises(rpa.RpaError):
            rpa.read_index(self.tmp / "g.rpa")
        bomb = zlib.compress(b"\x00" * (rpa.MAX_INDEX + 1024), 9)
        (self.tmp / "b.rpa").write_bytes(f"RPA-3.0 {34:016x} {0:08x}\n".encode("latin-1") + bomb)
        with self.assertRaises(rpa.RpaError):
            rpa.read_index(self.tmp / "b.rpa")
        with self.assertRaises(rpa.RpaError):
            rpa.read_index(self.tmp / "missing.rpa")


SCRIPT = """label start:
    scene ep1_room with fade
    show screen phone_screen
    mc "Hello."
    scene ep1_cafe_maya1 with dissolve
    show text "Title"
    show missing_thing at left
    mc "At the cafe."
    scene black
    mc "Dark."
"""
DEFS = """image ep1_cafe_maya1:
    "ep1_cafe_maya1_blink0" with Dissolve(0.2)
    pause 0.2
    "ep1_cafe_maya1_blink1" with Dissolve(0.2)
image bg_hall = "images/halls/hall_main.png"
image ep2_alias = "ep1_room"
image broken = "does_not_exist"
define mc = DynamicCharacter("name", color="#ffaf05")
define js = Character("Josy", color = "#ff1c63", what_color="#fff")
define nar = Character(None)
"""


class GameImagesTests(TempCase):
    def setUp(self):
        super().setUp()
        self.game = self.tmp / "game"
        (self.game / "images").mkdir(parents=True)
        make_rpa(self.game / "ep1_images.rpa", {"images/ep1/ep1_room.jpg": JPEG, "images/ep1/ep1_cafe_maya1_blink0.jpg": JPEG + b"1",
                                                "images/ep1/ep1_cafe_maya1_blink1.jpg": JPEG + b"2", "images/ep1/readme.txt": b"x", "fonts/Arch-Bold.ttf": b"TTF-in-archive"})
        (self.game / "Loose-CZ.otf").write_bytes(b"OTTO-loose")
        (self.game / "images" / "hall_main.png").write_bytes(PNG)
        (self.game / "script.rpy").write_text(SCRIPT, encoding="utf-8")
        (self.game / "defs.rpy").write_text(DEFS, encoding="utf-8")
        self.gi = gameimages.GameImages(self.game).build()

    def key(self, name):
        hit = self.gi.resolve(name)
        return hit[0] if hit else None

    def test_indexes_archives_and_loose_images_but_not_other_files(self):
        self.assertEqual(sorted(self.gi.stems), ["ep1_cafe_maya1_blink0", "ep1_cafe_maya1_blink1", "ep1_room", "hall_main"])

    def test_names_resolve_directly_through_statements_paths_and_frames(self):
        self.assertEqual(self.key("ep1_room"), "ep1_room")
        self.assertEqual(self.key("EP1_Room"), "ep1_room")                       # case does not matter
        self.assertEqual(self.key("ep1_cafe_maya1"), "ep1_cafe_maya1_blink0")      # an animation: its first frame
        self.assertEqual(self.key("bg_hall"), "hall_main")                          # image x = "path/with/dirs.png"
        self.assertEqual(self.key("ep2_alias"), "ep1_room")                         # image x = "another_image"
        self.assertIsNone(self.key("broken"))
        self.assertIsNone(self.key("nothing_like_it"))

    def test_frames_without_a_statement_are_found_by_their_prefix(self):
        self.assertEqual(self.key("ep1_cafe_maya1_blink"), "ep1_cafe_maya1_blink0")

    def test_the_picture_behind_a_line_is_the_last_resolvable_scene_before_it(self):
        sc = self.gi.scene_for(self.game / "script.rpy", 8)                        # after "At the cafe."
        self.assertEqual((sc["found"], sc["image"], sc["key"], sc["script_line"]), (True, "ep1_cafe_maya1", "ep1_cafe_maya1_blink0", 5))
        self.assertEqual(sc["missing"], ["missing_thing at left".replace(" at left", "")])      # looked at, not found, skipped
        sc = self.gi.scene_for(self.game / "script.rpy", 4)                        # screens and text are never pictures
        self.assertEqual((sc["image"], sc["script_line"]), ("ep1_room", 2))

    def test_black_is_a_flat_colour_and_nothing_before_the_start_is_reported(self):
        sc = self.gi.scene_for(self.game / "script.rpy", 10)
        self.assertEqual((sc["found"], sc["flat"], sc["key"]), (True, "#000000", ""))
        sc = self.gi.scene_for(self.game / "script.rpy", 1)
        self.assertEqual(sc["found"], False)

    def test_bytes_and_mime_come_from_the_content(self):
        data, mime = self.gi.image_bytes("ep1_room")
        self.assertEqual((data, mime), (JPEG, "image/jpeg"))
        data, mime = self.gi.image_bytes("hall_main")
        self.assertEqual((data[:4], mime), (PNG[:4], "image/png"))
        with self.assertRaises(rpa.RpaError):
            self.gi.image_bytes("../../secret")
        with self.assertRaises(rpa.RpaError):
            self.gi.image_bytes("nope")

    def test_fonts_are_indexed_by_file_name_from_folder_and_archives(self):
        self.assertEqual(sorted(self.gi.fonts), ["arch-bold.ttf", "loose-cz.otf"])
        self.assertEqual(self.gi.font_bytes("Loose-CZ.otf"), (b"OTTO-loose", "font/otf"))
        self.assertEqual(self.gi.font_bytes("arch-bold.ttf"), (b"TTF-in-archive", "font/ttf"))
        for bad in ("../Loose-CZ.otf", "sub/Loose-CZ.otf", "nope.ttf", ""):
            with self.assertRaises(rpa.RpaError):
                self.gi.font_bytes(bad)

    def test_character_definitions_give_the_name_the_game_shows(self):
        self.assertEqual(self.gi.characters["js"], {"name": "Josy", "color": "#ff1c63", "dynamic": False})
        self.assertEqual(self.gi.characters["mc"], {"name": "[name]", "color": "#ffaf05", "dynamic": True})
        self.assertEqual(self.gi.characters["nar"]["name"], "")

    def test_a_broken_archive_is_reported_and_skipped(self):
        (self.game / "bad.rpa").write_bytes(b"garbage")
        gi = gameimages.GameImages(self.game).build()
        self.assertIn("ep1_room", gi.stems)
        self.assertTrue(any("bad.rpa" in e for e in gi.errors))


class SceneInfoTests(TempCase):
    def make(self, with_game=True):
        base = self.tmp / "gamebase"
        proj = base / "game" / "tl" / "czech"
        proj.mkdir(parents=True)
        if with_game:
            make_rpa(base / "game" / "imgs.rpa", {"images/ep1_cafe.jpg": JPEG})
            (base / "game" / "x.rpy").write_text("label a:\n    scene ep1_cafe with fade\n    mc \"Hi.\"\n    mc \"Bye.\"\n", encoding="utf-8")
        (proj / "tl.rpy").write_text(dialog("a1", "mc", "Hi.", "Ahoj.", 3), encoding="utf-8")
        app = App(Config().load())
        app.open_project(proj)
        return app, base

    def test_scene_info_names_the_picture_and_carries_the_textbox_metrics(self):
        app, _base = self.make()
        info = app.scene_info("tl.rpy", app.project.entries("tl.rpy")[0].line)
        self.assertEqual((info["available"], info["found"], info["image"]), (True, True, "ep1_cafe"))
        self.assertEqual(info["url"], "/api/game/image?k=ep1_cafe")
        self.assertEqual((info["gui"]["screen_width"], info["gui"]["screen_height"]), (1920, 1080))
        self.assertEqual(info["script"], "game/x.rpy:2")

    def test_image_endpoint_serves_bytes_with_a_cache_header_and_nothing_else(self):
        app, _base = self.make()
        srv, sess, _url = server.start_server(app)
        try:
            host, port = srv.server_address

            def get(path):
                c = http.client.HTTPConnection(host, port, timeout=10)
                c.request("GET", path)
                r = c.getresponse()
                out = (r.status, r.getheader("Content-Type"), r.getheader("Cache-Control"), r.read())
                c.close()
                return out
            status, ctype, cache, body = get("/api/game/image?k=ep1_cafe")
            self.assertEqual((status, ctype, body), (200, "image/jpeg", JPEG))
            self.assertIn("max-age", cache)
            for bad in ("/api/game/image?k=..%2F..%2Fsecret", "/api/game/image?k=nope", "/api/game/image", "/api/game/image?k=x.rpy"):
                self.assertEqual(get(bad)[0], 404, bad)
            status, _t, _c, body = get("/api/game/scene?file=tl.rpy&line=" + str(app.project.entries("tl.rpy")[0].line))
            self.assertEqual(json.loads(body)["image"], "ep1_cafe")
        finally:
            srv.shutdown()
            srv.server_close()
            app.close()

    def test_fonts_come_from_gui_rpy_and_the_translation_overrides_them(self):
        app, base = self.make()
        (base / "game" / "gui.rpy").write_text('define gui.text_font = "Plain.otf"\ndefine gui.name_text_font = "Name.ttf"\n', encoding="utf-8")
        for fn in ("Plain.otf", "Name.ttf", "Czech.otf"):
            (base / "game" / fn).write_bytes(b"FONT-" + fn.encode())
        app._gi = None
        self.assertEqual(app.game_fonts()["text"], "Plain.otf")
        (base / "game" / "tl" / "czech" / "fonts.rpy").write_text(
            'translate czech python:\n    gui.text_font = "Czech.otf"\n\ntranslate czech style say_label:\n    font "Name.ttf"\n', encoding="utf-8")
        f = app.game_fonts()
        self.assertEqual((f["text"], f["name"]), ("Czech.otf", "Name.ttf"))
        (base / "game" / "tl" / "czech" / "fonts.rpy").write_text('translate czech style say_dialogue:\n    font "Czech.otf"\n', encoding="utf-8")
        self.assertEqual(app.game_fonts()["text"], "Czech.otf")
        info = app.scene_info("tl.rpy", app.project.entries("tl.rpy")[0].line)
        self.assertEqual(info["fonts_text"]["url"], "/api/game/font?k=czech.otf")
        self.assertEqual(app.game_font("Czech.otf"), (b"FONT-Czech.otf", "font/otf"))

    def test_without_the_game_sources_the_reason_is_explained(self):
        self.write("a.rpy", dialog("a1", "mc", "Hi.", "Ahoj.", 3))
        app = self.new_app()
        info = app.scene_info("a.rpy", app.project.entries("a.rpy")[0].line)
        self.assertEqual(info["available"], False)
        self.assertIn("game", info["reason"])
        with self.assertRaises(AppError):
            app.game_image("whatever")

    def test_unknown_line_is_an_error(self):
        app, _base = self.make()
        with self.assertRaises(AppError):
            app.scene_info("tl.rpy", 9999)


if __name__ == "__main__":
    unittest.main()
