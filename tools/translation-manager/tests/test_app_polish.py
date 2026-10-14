"""Original script references, choice/dialogue type, 'V korekci' episode status, safe external links."""
import http.client
import json
from unittest import mock

from helpers import TempCase, dialog

from prehled import __version__, export, rpy, server
from prehled.app import LINKS, AppError

SAMPLE = """# game/script.rpy:2155
translate czech ep1_a_28018a1b:

    # mc "Well, hello."
    mc "No, ahoj."

# game/script.rpy:2160
translate czech ep1_b_d562ece9:

    # de "I do not know."
    de "I do not know."

translate czech strings:

    # game/screens.rpy:357
    old "Go left"
    new "Jít doleva"

    # game/screens.rpy:360
    old "Go right"
    new "Go right"
"""


class ScriptReferenceTests(TempCase):
    def test_parser_records_the_original_game_position(self):
        p = rpy.parse_text(SAMPLE)
        refs = {e.target: (e.unit, e.ref) for e in p.entries}
        self.assertEqual(refs["No, ahoj."], ("dialogue", "game/script.rpy:2155"))
        self.assertEqual(refs["I do not know."], ("dialogue", "game/script.rpy:2160"))
        self.assertEqual(refs["Jít doleva"], ("string", "game/screens.rpy:357"))
        self.assertEqual(refs["Go right"], ("string", "game/screens.rpy:360"))

    def test_block_without_reference_has_none_and_does_not_inherit(self):
        p = rpy.parse_text('translate czech a:\n\n    # mc "Hi"\n    mc "Ahoj"\n')
        self.assertEqual(p.entries[0].ref, "")

    def test_counts_are_unchanged_by_the_new_field(self):
        p = rpy.parse_text(SAMPLE)
        self.assertEqual(rpy.count(p.entries), (2, 2, 0))

    def test_api_exposes_ref_and_unit_and_filters_by_unit(self):
        self.write("a.rpy", SAMPLE)
        app = self.new_app()
        items = app.entries(file="a.rpy", status="all")["items"]
        self.assertEqual({(i["unit"], i["ref"]) for i in items},
                         {("dialogue", "game/script.rpy:2155"), ("dialogue", "game/script.rpy:2160"),
                          ("string", "game/screens.rpy:357"), ("string", "game/screens.rpy:360")})
        self.assertEqual(app.entries(file="a.rpy", status="all", unit="string")["total"], 2)
        self.assertEqual(app.entries(file="a.rpy", status="all", unit="dialogue")["total"], 2)
        line = items[0]["line"]
        self.assertEqual(app.entry_detail("a.rpy", line)["ref"], "game/script.rpy:2155")


class EpisodeProofStatusTests(TempCase):
    def test_new_status_is_stored_exported_and_valid(self):
        self.basic_project()
        app = self.new_app()
        app.set_assign("script.rpy", "ep:1")
        app.set_episode_state(1, "proof")
        self.assertIn("proof", [s["key"] for s in app.overview()["episode_states"]])
        d = app.build_export()
        self.assertEqual(d["episodes"][0]["status"], "proof")
        self.assertEqual(export.validate_progress(d), [])
        again = self.new_app()                                       # persisted in epizody.csv
        self.assertEqual(again.store.episodes[1], "proof")
        self.assertIn("V korekci", (again.data_dir / "epizody.csv").read_text(encoding="utf-8-sig"))

    def test_old_files_with_four_states_still_load(self):
        self.basic_project()
        data = self.root / "_progress_data"
        data.mkdir()
        (data / "epizody.csv").write_text("epizoda;stav\n1;Přeloženo\n2;Hotovo\n", encoding="utf-8")
        app = self.new_app()
        self.assertEqual((app.store.episodes[1], app.store.episodes[2]), ("tr", "done"))


class LinkTests(TempCase):
    def setUp(self):
        super().setUp()
        self.basic_project()
        self.app = self.new_app()

    def test_only_fixed_addresses_can_be_opened(self):
        opened = []
        for link_id, url in LINKS.items():
            self.assertTrue(url.startswith("https://"))
            self.assertEqual(self.app.open_link(link_id, opener=opened.append)["url"], url)
        self.assertEqual(opened, list(LINKS.values()))
        with self.assertRaises(AppError):
            self.app.open_link("http://evil.example", opener=opened.append)
        self.assertEqual(len(opened), len(LINKS))

    def test_the_project_links_are_the_authors(self):
        self.assertEqual(LINKS["kofi"], "https://ko-fi.com/filiposakkq")
        self.assertEqual(LINKS["github"], "https://github.com/Filiposakkq")
        self.assertEqual(LINKS["repo"], "https://github.com/Filiposakkq/Being-A-DIK-CZ")
        self.assertEqual(LINKS["web"], "https://badik.filiposakkq.dev/")

    def test_http_endpoint_needs_token_and_takes_ids_not_urls(self):
        srv, sess, _ = server.start_server(self.app)
        self.addCleanup(srv.shutdown)

        def post(body, token=True):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("POST", "/api/open-url", json.dumps(body), {"X-Token": sess.token} if token else {})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        with mock.patch("webbrowser.open") as wb:
            self.assertEqual(post({"id": "kofi"}, token=False)[0], 403)
            self.assertEqual(post({"url": "https://evil.example"})[0], 400)
            self.assertEqual(post({"id": "https://evil.example"})[0], 400)
            st, r = post({"id": "kofi"})
            self.assertEqual((st, r["url"]), (200, "https://ko-fi.com/filiposakkq"))
            wb.assert_called_once_with("https://ko-fi.com/filiposakkq")

    def test_state_reports_the_version(self):
        srv, sess, _ = server.start_server(self.app)
        self.addCleanup(srv.shutdown)
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("GET", "/api/state")
        self.assertEqual(json.loads(c.getresponse().read())["version"], __version__)
