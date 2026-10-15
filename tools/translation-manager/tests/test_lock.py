"""Project lock: two running copies of the app must not edit one project."""
import json
import os
import time
import unittest

from helpers import TempCase, dialog

from prehled.app import ProjectBusy
from prehled.lock import LOCK_NAME, STALE_AFTER


class LockTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("script.rpy", dialog("a1", "mc", "Hello.", "Ahoj.", 5))
        self.lockfile = self.root / "_progress_data" / LOCK_NAME

    def foreign_lock(self, age=0, pid=None):
        self.lockfile.parent.mkdir(exist_ok=True)
        self.lockfile.write_text(json.dumps({"pid": pid or os.getpid() + 1, "host": "OTHER-PC", "token": "zzz",
                                             "time": time.time() - age}), encoding="utf-8")

    def test_opening_writes_a_lock_and_closing_removes_it(self):
        app = self.new_app()
        self.assertTrue(self.lockfile.is_file())
        app.close()
        self.assertFalse(self.lockfile.exists())

    def test_same_process_can_reopen_its_own_project(self):
        a = self.new_app()
        b = self.new_app()          # e.g. "Změnit složku" back to the same project
        self.assertTrue(b.plock.held)
        a.close()
        b.close()

    def test_fresh_lock_of_another_copy_blocks_opening(self):
        self.foreign_lock(age=5)
        with self.assertRaises(ProjectBusy) as cm:
            self.new_app()
        self.assertEqual(cm.exception.path, str(self.root.resolve()))
        self.assertIn("jiná kopie", str(cm.exception))

    def test_force_takes_the_project_over_and_the_old_owner_notices(self):
        self.foreign_lock(age=5)
        app = self.new_app(open_root=False)
        app.open_project(self.root, force=True)
        self.assertTrue(app.plock.held)
        self.assertFalse(app.overview()["lock_lost"])
        self.foreign_lock(age=0)                       # the other copy takes it back
        self.assertTrue(app.overview()["lock_lost"])
        app.close()
        self.assertTrue(self.lockfile.exists())        # not ours any more: must not be deleted

    def test_stale_lock_is_ignored(self):
        self.foreign_lock(age=STALE_AFTER + 30)
        app = self.new_app()
        self.assertTrue(app.plock.held)
        app.close()

    def test_http_reports_the_lock_and_force_overrides_it(self):
        from prehled import server
        import http.client
        self.foreign_lock(age=1)
        app = self.new_app(open_root=False)
        srv, sess, url = server.start_server(app)
        try:
            host, port = srv.server_address

            def post(body):
                c = http.client.HTTPConnection(host, port, timeout=10)
                c.request("POST", "/api/project/set", json.dumps(body), {"X-Token": sess.token, "Content-Type": "application/json"})
                r = c.getresponse()
                out = json.loads(r.read().decode("utf-8"))
                c.close()
                return r.status, out
            status, out = post({"path": str(self.root)})
            self.assertEqual(status, 409)
            self.assertTrue(out["locked"])
            status, out = post({"path": str(self.root), "force": True})
            self.assertEqual(status, 200)
        finally:
            srv.shutdown()
            srv.server_close()
            app.close()


if __name__ == "__main__":
    unittest.main()
