"""Several app windows: the app quits only when the last one is gone; opening one more window is validated."""
import http.client
import json
import time
import unittest
from urllib.parse import parse_qs, urlparse

from helpers import TempCase, dialog

from prehled import server


class WindowTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "Hello.", "Ahoj.", 5))
        self.app = self.new_app()
        self.srv, self.sess, self.url = server.start_server(self.app)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.app.close)
        self.host, self.port = self.srv.server_address

    def call(self, method, path, body=None, token=True):
        c = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Token"] = self.sess.token
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        text = r.read().decode("utf-8")
        c.close()
        try:
            return r.status, json.loads(text)
        except ValueError:
            return r.status, text

    def bye(self, wid):
        c = http.client.HTTPConnection(self.host, self.port, timeout=10)
        c.request("POST", f"/api/bye?t={self.sess.token}&w={wid}")
        c.getresponse().read()
        c.close()

    def test_pings_register_windows_and_closing_one_does_not_quit_the_app(self):
        self.call("GET", "/api/ping?w=first")
        self.call("GET", "/api/ping?w=second")
        self.assertEqual(set(self.sess.windows), {"first", "second"})
        self.bye("second")
        self.assertIsNone(self.sess.bye_at)                          # the first window is still there
        self.bye("first")
        self.assertIsNotNone(self.sess.bye_at)                       # now the watchdog may quit
        self.call("GET", "/api/ping?w=again")                        # a reload / new window cancels it
        self.assertIsNone(self.sess.bye_at)

    def test_a_bye_with_a_wrong_token_is_ignored(self):
        self.call("GET", "/api/ping?w=a")
        c = http.client.HTTPConnection(self.host, self.port, timeout=10)
        c.request("POST", "/api/bye?t=wrong&w=a")
        c.getresponse().read()
        c.close()
        self.assertEqual(set(self.sess.windows), {"a"})
        self.assertIsNone(self.sess.bye_at)

    def test_windows_that_stopped_pinging_do_not_keep_the_app_alive(self):
        self.sess.windows["ghost"] = time.time() - 120
        self.call("GET", "/api/ping?w=real")
        self.bye("real")
        self.assertIsNotNone(self.sess.bye_at)

    def test_opening_a_window_builds_a_sanitized_address(self):
        opened = []
        self.sess.open_window = opened.append
        status, res = self.call("POST", "/api/window/open", {"view": "entries", "file": "sub dir/a.rpy", "line": 12, "status": "todo"})
        self.assertEqual((status, res["ok"]), (200, True))
        q = parse_qs(urlparse(opened[0]).query)
        self.assertEqual((q["win"], q["view"], q["file"], q["line"], q["status"]), (["2"], ["entries"], ["sub dir/a.rpy"], ["12"], ["todo"]))
        self.assertTrue(opened[0].startswith(self.url + "?"))
        self.call("POST", "/api/window/open", {"view": "evil", "line": "x; drop", "status": "<script>"})
        q = parse_qs(urlparse(opened[1]).query)
        self.assertEqual(q, {"win": ["2"]})                          # unknown values are dropped, never passed on

    def test_a_companion_window_is_opened_with_a_tab_and_follows_the_shared_focus(self):
        opened = []
        self.sess.open_window = opened.append
        self.call("POST", "/api/window/open", {"view": "entries", "companion": "1", "tab": "scene", "file": "a.rpy", "line": 5})
        q = parse_qs(urlparse(opened[0]).query)
        self.assertEqual((q["companion"], q["tab"]), (["1"], ["scene"]))
        self.call("POST", "/api/window/open", {"companion": "yes", "tab": "<x>"})
        self.assertEqual(parse_qs(urlparse(opened[1]).query), {"win": ["2"]})
        status, f0 = self.call("GET", "/api/focus")
        self.assertEqual((status, f0["seq"], f0["file"]), (200, 0, ""))
        status, f1 = self.call("POST", "/api/focus", {"file": "a.rpy", "line": 5})
        self.assertEqual((f1["seq"], f1["file"], f1["line"]), (1, "a.rpy", 5))
        self.call("POST", "/api/focus", {"file": "a.rpy", "line": "x"})
        self.assertEqual(self.call("GET", "/api/focus")[1], {"ok": True, "seq": 2, "file": "a.rpy", "line": 0, "text": None})
        self.assertEqual(self.call("POST", "/api/focus", {"file": "a.rpy"}, token=False)[0], 403)

    def test_the_main_window_learns_that_a_detail_window_is_open_and_gets_the_typed_text(self):
        self.assertEqual(self.call("GET", "/api/ping?w=main")[1]["companions"], 0)
        self.assertEqual(self.call("GET", "/api/ping?w=detail&k=1")[1]["companions"], 1)
        self.assertEqual(self.call("GET", "/api/ping?w=main")[1]["companions"], 1)
        self.bye("detail")
        self.assertEqual(self.call("GET", "/api/ping?w=main")[1]["companions"], 0)
        self.sess.companions["ghost"] = time.time() - 60                # stopped pinging
        self.assertEqual(self.call("GET", "/api/ping?w=main")[1]["companions"], 0)
        res = self.call("POST", "/api/focus", {"file": "a.rpy", "line": 5, "text": "Ahoj světe"})[1]
        self.assertEqual((res["text"], res["line"]), ("Ahoj světe", 5))
        self.assertIsNone(self.call("POST", "/api/focus", {"file": "a.rpy", "line": 5, "text": 7})[1]["text"])

    def test_the_focus_can_be_waited_for_so_the_companion_follows_at_once(self):
        import threading
        got = {}

        def waiter():
            t0 = time.time()
            got["res"] = self.call("GET", "/api/focus?after=0&wait=1")[1]
            got["took"] = time.time() - t0
        th = threading.Thread(target=waiter)
        th.start()
        time.sleep(0.3)
        self.call("POST", "/api/focus", {"file": "a.rpy", "line": 5})
        th.join(10)
        self.assertEqual((got["res"]["seq"], got["res"]["line"]), (1, 5))
        self.assertLess(got["took"], 5)                               # answered by the change, not by the 20 s timeout
        t0 = time.time()
        self.call("GET", "/api/focus?after=-1&wait=1")                # already newer than "-1": no waiting
        self.assertLess(time.time() - t0, 2)

    def test_without_an_opener_the_page_is_told_to_fall_back(self):
        status, res = self.call("POST", "/api/window/open", {"view": "entries"})
        self.assertEqual((res["ok"], res["fallback"]), (False, True))

    def test_a_failing_opener_is_reported_not_raised(self):
        def boom(url):
            raise RuntimeError("no display")
        self.sess.open_window = boom
        status, res = self.call("POST", "/api/window/open", {})
        self.assertEqual((status, res["ok"], res["fallback"]), (200, False, True))
        self.assertIn("no display", res["error"])

    def test_the_request_needs_the_token(self):
        status, _res = self.call("POST", "/api/window/open", {}, token=False)
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
