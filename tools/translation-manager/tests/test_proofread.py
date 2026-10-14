"""Per-line proofreading marks: counting, stale detection, flags, undo, persistence, export."""
import json

from helpers import TempCase, dialog, rel

from prehled.app import AppError
from prehled.store import Store


class ProofreadTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("a.rpy", dialog("a1", "mc", "One line here.", "Jedna řádka.")
                   + dialog("a2", "mc", "Two lines here.", "Dvě řádky.")
                   + dialog("a3", "mc", "Three lines here.", "Tři řádky.")
                   + dialog("a4", "mc", "Not translated yet, sorry.", None))
        self.app = self.new_app()
        self.ents = {e.block.split()[-1]: e for e in self.app.project.entries("a.rpy")}

    def item(self, ident):
        return {"file": "a.rpy", "key": list(self.ents[ident].key)}

    def corr(self):
        return self.app.project.row("a.rpy").corr

    def test_marking_counts_and_shows_in_every_total(self):
        self.assertEqual(self.corr(), 0)
        r = self.app.proof_set([self.item("a1"), self.item("a2")], "ok")
        self.assertEqual(r["changed"], 2)
        self.assertEqual(self.corr(), 2)
        self.assertEqual(self.app.overview()["totals"]["proofread"], 2)
        self.assertEqual(self.app.overview()["totals"]["proof_marked"], 2)
        self.assertEqual(self.app.build_export()["proofreading"]["done"], 2)
        f = self.app.files_payload()[0]
        self.assertEqual((f["corr"], f["proof_marked"], f["proof_fix"]), (2, 2, 0))

    def test_untranslated_lines_cannot_be_proofread(self):
        r = self.app.proof_set([self.item("a4")], "ok")
        self.assertEqual(r["changed"], 0)
        self.assertIn("ještě není přeložený", r["skipped"][0][1])
        self.assertEqual(self.corr(), 0)

    def test_approved_untranslated_line_can_be_proofread(self):
        self.app.approval_apply([self.item("a4")])
        self.assertEqual(self.app.proof_set([self.item("a4")], "ok")["changed"], 1)

    def test_changed_translation_makes_the_mark_stale(self):
        self.app.proof_set([self.item("a1")], "ok")
        self.write("a.rpy", dialog("a1", "mc", "One line here.", "Jedna větička.")
                   + dialog("a2", "mc", "Two lines here.", "Dvě řádky.")
                   + dialog("a3", "mc", "Three lines here.", "Tři řádky.")
                   + dialog("a4", "mc", "Not translated yet, sorry.", None))
        self.app.refresh()
        self.assertEqual(self.corr(), 0)
        e = next(x for x in self.app.project.entries("a.rpy") if x.block.endswith(" a1"))
        self.assertEqual(self.app.project.proof_state("a.rpy", e), "stale")
        det = self.app.entry_detail("a.rpy", e.line)
        self.assertEqual(det["proof"], "stale")
        self.assertEqual(self.app.proof_next("a.rpy")["line"], e.line)          # needs a second look
        self.app.proof_set([{"file": "a.rpy", "key": list(e.key)}], "ok")
        self.assertEqual(self.corr(), 1)

    def test_fix_flag_with_note_is_not_counted(self):
        self.app.proof_set([self.item("a2")], "fix", note="překlep v 'řádky'")
        self.assertEqual(self.corr(), 0)
        e = self.ents["a2"]
        det = self.app.entry_detail("a.rpy", e.line)
        self.assertEqual((det["proof"], det["proof_note"]), ("fix", "překlep v 'řádky'"))
        self.assertEqual(self.app.overview()["totals"]["proof_fix"], 1)
        self.assertEqual(self.app.entries(file="a.rpy", status="fix")["total"], 1)
        self.app.proof_set([self.item("a2")], "ok")                    # fixed and checked
        self.assertEqual(self.corr(), 1)
        self.assertEqual(self.app.entry_detail("a.rpy", e.line)["proof_note"], "překlep v 'řádky'")

    def test_entry_filters(self):
        self.app.proof_set([self.item("a1")], "ok")
        self.app.proof_set([self.item("a2")], "fix")
        q = lambda s: {i["block"].split()[-1] for i in self.app.entries(file="a.rpy", status=s)["items"]}
        self.assertEqual(q("review"), {"a3"})            # translated, not yet checked, not flagged
        self.assertEqual(q("proofed"), {"a1"})
        self.assertEqual(q("fix"), {"a2"})
        proofs = {i["block"].split()[-1]: i["proof"] for i in self.app.entries(file="a.rpy", status="all")["items"]}
        self.assertEqual(proofs, {"a1": "ok", "a2": "fix", "a3": "", "a4": ""})

    def test_mark_everything_up_to_a_line(self):
        r = self.app.proof_upto("a.rpy", self.ents["a2"].line)
        self.assertEqual(r["changed"], 2)
        self.assertEqual(self.corr(), 2)
        self.assertEqual(self.app.proof_upto("a.rpy", self.ents["a2"].line)["changed"], 0)   # idempotent
        self.app.proof_set([self.item("a3")], "fix")
        self.app.proof_upto("a.rpy", 9999)
        self.assertEqual(self.corr(), 2)                                 # flagged line is not silently ok'd
        self.assertEqual(self.app.proof_set([self.item("a1")], "")["changed"], 1)
        self.assertEqual(self.corr(), 1)

    def test_next_line_to_proofread_skips_checked_flagged_and_untranslated(self):
        self.assertEqual(self.app.proof_next("a.rpy")["line"], self.ents["a1"].line)
        self.app.proof_set([self.item("a1")], "ok")
        self.app.proof_set([self.item("a2")], "fix")
        self.assertEqual(self.app.proof_next("a.rpy")["line"], self.ents["a3"].line)
        self.assertEqual(self.app.proof_next("a.rpy", after=self.ents["a3"].line), {"found": False})
        self.assertEqual(self.app.proof_next("")["file"], "a.rpy")                 # whole project

    def test_baseline_number_and_marks_add_up(self):
        self.app.save_file("a.rpy", "2", "")                 # typed by hand: first two lines were checked earlier
        self.assertEqual(self.corr(), 2)
        self.app.proof_set([self.item("a3")], "ok")
        self.assertEqual(self.corr(), 3)
        self.app.save_file("a.rpy", "ano", "")                # whole file = every line of it
        self.assertEqual(self.corr(), 4)
        self.app.save_file("a.rpy", "2", "")                  # typing less cannot drop below the marked lines
        self.assertEqual(self.app.store.corr["a.rpy"]["c"], "1")
        self.assertEqual(self.corr(), 2)

    def test_undo_and_persistence_and_file_format(self):
        self.app.proof_set([self.item("a1")], "ok")
        self.app.proof_set([self.item("a2")], "fix", note="x")
        self.app.undo()
        self.assertEqual(self.app.entries(file="a.rpy", status="fix")["total"], 0)
        self.assertEqual(self.corr(), 1)
        stored = Store(self.app.data_dir).load().proof["a.rpy"]
        self.assertEqual(len(stored), 1)
        raw = (self.app.data_dir / "korektura_radky.csv").read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(raw[0], "soubor;blok;original;stav;hash;poznamka;datum")
        self.assertIn(";ok;", raw[1])
        app2 = self.new_app()                                  # next launch
        self.assertEqual(app2.project.row("a.rpy").corr, 1)

    def test_multiline_note_survives_a_restart(self):
        note = "první řádek\ndruhý; řádek"
        self.app.proof_set([self.item("a2")], "fix", note=note)
        again = self.new_app()
        e = next(x for x in again.project.entries("a.rpy") if x.block.endswith(" a2"))
        self.assertEqual(again.entry_detail("a.rpy", e.line)["proof_note"], note)
        self.assertEqual(again.project.row("a.rpy").total, 4)               # neighbouring rows are not damaged

    def test_clear_file(self):
        self.app.proof_set([self.item("a1"), self.item("a2")], "ok")
        self.assertEqual(self.app.proof_clear_file("a.rpy")["changed"], 2)
        self.assertEqual(self.corr(), 0)
        self.app.undo()
        self.assertEqual(self.corr(), 2)

    def test_marks_survive_refresh_rename_and_removal(self):
        self.app.proof_set([self.item("a1")], "ok")
        import os
        os.rename(self.root / "a.rpy", self.root / "b.rpy")
        rep = self.app.refresh()
        self.assertEqual(rep["renamed"], [{"from": "a.rpy", "to": "b.rpy"}])
        self.assertEqual(self.app.project.row("b.rpy").corr, 1)
        (self.root / "b.rpy").unlink()
        self.app.refresh()
        self.assertIn("b.rpy", self.app.store.proof)             # kept while the file is away

    def test_validation_of_requests(self):
        with self.assertRaises(AppError):
            self.app.proof_set([self.item("a1")], "maybe")
        r = self.app.proof_set([{"file": "nope.rpy", "key": ["x", "y"]}, {"file": "a.rpy", "key": ["x", "y"]}], "ok")
        self.assertEqual(r["changed"], 0)
        self.assertEqual(len(r["skipped"]), 2)
        with self.assertRaises(AppError):
            self.app.proof_upto("nope.rpy", 5)

    def test_season_statistics_use_proofread_marks(self):
        self.app.set_assign("a.rpy", "ep:1")
        self.app.proof_set([self.item("a1"), self.item("a2")], "ok")
        d = self.app.build_export()
        self.assertEqual(d["episodes"][0]["proofreading"]["done"], 2)
        self.assertEqual(d["seasons"][0]["proofreading"]["done"], 2)
        self.assertEqual(d["proofreading"]["done"], 2)
        self.assertNotIn(".rpy", json.dumps(d))

    def test_http_api_roundtrip(self):
        import http.client
        from prehled import server
        srv, sess, _ = server.start_server(self.app)
        self.addCleanup(srv.shutdown)

        def call(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request(method, path, json.dumps(body) if body is not None else None,
                      {"X-Token": sess.token, "Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        st, r = call("POST", "/api/proof/set", {"items": [self.item("a1")], "state": "ok"})
        self.assertEqual((st, r["changed"]), (200, 1))
        st, r = call("GET", "/api/proof/next?file=a.rpy")
        self.assertEqual(r["line"], self.ents["a2"].line)
        st, r = call("POST", "/api/proof/upto", {"file": "a.rpy", "line": self.ents["a3"].line})
        self.assertEqual(r["changed"], 2)
        st, r = call("GET", "/api/entries?file=a.rpy&status=proofed")
        self.assertEqual(r["total"], 3)
        st, r = call("POST", "/api/proof/clear-file", {"file": "a.rpy"})
        self.assertEqual(r["changed"], 3)
