"""Bulk categorization, global approval, validation, estimates and the progress export."""
import json
import unittest
from datetime import date, datetime, timedelta

from helpers import TempCase, dialog, rel, strings

from prehled import bulk, export, history as hist, rpy, validator
from prehled.seasons import ACTIVE_EPISODES, SEASONS, season_of
from prehled.store import Store


def issues(src, tgt):
    return {(i.severity, i.code) for i in validator.check_text(src, tgt)}


class SeasonModelTests(unittest.TestCase):
    def test_mapping_matches_the_project_definition(self):
        self.assertEqual([season_of(n) for n in range(1, 9)], [1, 1, 1, 1, 2, 2, 2, 2])
        self.assertIsNone(season_of(9))
        self.assertEqual(ACTIVE_EPISODES, tuple(range(1, 9)))
        s3 = [s for s in SEASONS if s["n"] == 3][0]
        self.assertEqual((s3["status"], s3["episodes"]), ("planned", ()))

    def test_planned_season_not_in_active_scope(self):
        self.assertTrue(all(season_of(e) in (1, 2) for e in ACTIVE_EPISODES))


class SuggestTests(unittest.TestCase):
    def one(self, name, current=None, known=None):
        cur = current or {}
        return bulk.suggest([name], cur, known_assign=known if known is not None else cur)[0]

    def test_episode_in_file_or_folder_name(self):
        for name, ep in [(rel("scripts", "freeroam", "episode3", "ep3_x.rpy"), "ep:3"),
                         (rel("season2", "scripts", "madame_ep7.rpy"), "ep:7"),
                         (rel("scripts", "episode4", "bella.rpy"), "ep:4")]:
            s = self.one(name)
            self.assertEqual((s["suggested"], s["state"]), (ep, "new"), name)

    def test_no_false_match_inside_words(self):
        self.assertEqual(self.one("step5_map.rpy")["suggested"], "")
        self.assertEqual(self.one("deep2.rpy")["suggested"], "")

    def test_update_files_follow_project_convention(self):
        s = self.one(rel("season2", "scripts", "update6.rpy"))
        self.assertEqual((s["suggested"], s["confidence"]), ("ep:6", "medium"))

    def test_ambiguous_when_several_episodes(self):
        s = self.one("ep2_ep3_mix.rpy")
        self.assertEqual((s["state"], s["suggested"]), ("ambiguous", ""))
        self.assertEqual(s["candidates"], ["ep:2", "ep:3"])

    def test_season_folder_resolves_ambiguity(self):
        s = self.one(rel("season2", "ep3_ep6.rpy"))
        self.assertEqual(s["suggested"], "ep:6")

    def test_conflict_between_season_folder_and_episode(self):
        s = self.one(rel("season2", "scripts", "ep3_oops.rpy"))
        self.assertEqual(s["state"], "conflict")
        self.assertEqual(s["confidence"], "low")

    def test_unknown_episode_number_not_suggested(self):
        s = self.one("ep12_future.rpy")
        self.assertEqual((s["suggested"], s["state"]), ("", "unknown"))
        self.assertIn("1–8", s["reason"])

    def test_manual_assignment_protected(self):
        s = self.one("ep4_x.rpy", current={"ep4_x.rpy": "ep:2"})
        self.assertEqual((s["suggested"], s["state"], s["overwrite"]), ("ep:4", "conflict", True))
        same = self.one("ep4_x.rpy", current={"ep4_x.rpy": "ep:4"})
        self.assertEqual(same["state"], "same")

    def test_learns_from_siblings_and_shared_names(self):
        known = {rel("scripts", "misc", "a.rpy"): "gen"}
        s = self.one(rel("scripts", "misc", "b.rpy"), known=known)
        self.assertEqual((s["suggested"], s["confidence"]), ("gen", "medium"))
        self.assertEqual(self.one("screens.rpy")["suggested"], "gen")

    def test_season_folder_without_episode_is_explained(self):
        s = self.one(rel("season2", "scripts", "laptop", "laptop.rpy"))
        self.assertEqual(s["suggested"], "")
        self.assertIn("sezóny 2", s["reason"])


class BulkApplyTests(TempCase):
    def test_apply_respects_overwrite_flag_and_is_undoable(self):
        s = Store(self.root / "_progress_data")
        s.assign.update({"a.rpy": "ep:1"})
        res = bulk.apply_assignments(s, [{"name": "a.rpy", "value": "ep:2"}, {"name": "b.rpy", "value": "ep:3"},
                                         {"name": "c.rpy", "value": "ep:9"}])
        self.assertEqual(res["applied"], ["b.rpy"])
        self.assertEqual({n for n, _r in res["skipped"]}, {"a.rpy", "c.rpy"})
        self.assertEqual(s.assign, {"a.rpy": "ep:1", "b.rpy": "ep:3"})
        res = bulk.apply_assignments(s, [{"name": "a.rpy", "value": "ep:2", "overwrite": True}])
        self.assertEqual(s.assign["a.rpy"], "ep:2")
        s.undo()
        self.assertEqual(s.assign["a.rpy"], "ep:1")
        s.undo()
        self.assertEqual(s.assign, {"a.rpy": "ep:1"})


class GlobalApprovalTests(TempCase):
    def make(self):
        self.basic_project()
        self.write("more.rpy", dialog("m1", "mc", "Hmm...", None, 5) + dialog("m2", "de", "Hmm...", None, 9)
                   + dialog("m3", "mc", "Hmm...", "Hmm...", 14) + dialog("m4", "mc", "", None, 20))
        app = self.new_app()
        return app

    def ref(self, app, f="script.rpy"):
        e = next(e for e in app.project.entries(f) if e.source == "Hmm...")
        return f, e.line

    def test_scopes(self):
        app = self.make()
        f, line = self.ref(app)
        occ = bulk.approval_candidates(app.project, f, line, "occurrence")
        self.assertEqual(occ["counts"]["total"], 1)
        fil = bulk.approval_candidates(app.project, f, line, "file")
        self.assertEqual(fil["counts"]["total"], 1)
        proj = bulk.approval_candidates(app.project, f, line, "project")
        self.assertEqual(proj["counts"]["files"], 4)
        self.assertEqual(proj["counts"]["total"], 6)

    def test_context_decides_default_selection(self):
        app = self.make()
        f, line = self.ref(app)
        proj = bulk.approval_candidates(app.project, f, line, "project")
        by = {(i["file"], i["line"]): i for i in proj["items"]}
        other_speaker = [i for i in proj["items"] if i["who"] == "de" and i["text"] == "Hmm..."][0]
        self.assertFalse(other_speaker["selected"])
        self.assertTrue(other_speaker["selectable"])
        self.assertIn("jiný mluvčí", other_speaker["notes"][0])
        same_speaker = [i for i in proj["items"] if i["who"] == "mc" and i["file"] != f][0]
        self.assertTrue(same_speaker["selected"])
        self.assertTrue(by[(f, line)]["is_reference"])
        loose = bulk.approval_candidates(app.project, f, line, "project", same_speaker=False)
        self.assertTrue(all(i["selected"] for i in loose["items"]))

    def test_texts_must_match_exactly(self):
        app = self.make()
        f, line = self.ref(app)
        proj = bulk.approval_candidates(app.project, f, line, "project")
        self.assertTrue(all(i["text"] == "Hmm..." for i in proj["items"]))
        self.assertNotIn("I really do not know what to say.", [i["text"] for i in proj["items"]])

    def test_empty_translation_can_never_be_approved(self):
        app = self.make()
        e = next(e for e in app.project.entries("more.rpy") if e.category == rpy.K_EMPTY)
        res = bulk.apply_approvals(app.project, [{"file": "more.rpy", "key": list(e.key)}])
        self.assertEqual(res["changed"], 0)
        self.assertTrue(res["skipped"])

    def test_apply_updates_counts_and_preserves_existing_approvals(self):
        app = self.make()
        f, line = self.ref(app)
        before = app.project.counts("script.rpy")
        first = next(e for e in app.project.entries("more.rpy") if e.block.endswith(" m3"))
        app.approval_apply([{"file": "more.rpy", "key": list(first.key)}])
        proj = bulk.approval_candidates(app.project, f, line, "project")
        already = [i for i in proj["items"] if i["approved"]]
        self.assertEqual(len(already), 1)
        self.assertFalse(already[0]["selectable"])
        sels = [{"file": i["file"], "key": i["key"]} for i in proj["items"] if i["selected"]]
        res = app.approval_apply(sels)
        self.assertEqual(res["changed"], len(sels))
        self.assertEqual(app.project.counts("script.rpy")[0], before[0] + 1)
        self.assertIn(first.key, app.store.approved["more.rpy"])

    def test_undo_reverts_bulk_approval(self):
        app = self.make()
        f, line = self.ref(app)
        base = app.overview()["totals"]["done"]
        proj = bulk.approval_candidates(app.project, f, line, "project")
        app.approval_apply([{"file": i["file"], "key": i["key"]} for i in proj["items"] if i["selected"]])
        self.assertGreater(app.overview()["totals"]["done"], base)
        app.undo()
        self.assertEqual(app.overview()["totals"]["done"], base)
        self.assertEqual(Store(app.data_dir).load().approved, {})

    def test_stale_selection_is_refused(self):
        app = self.make()
        f, line = self.ref(app)
        proj = bulk.approval_candidates(app.project, f, line, "file")
        self.write("script.rpy", dialog("a1", "mc", "Hmm...", "Hmm... ano.", 10))   # translated meanwhile
        app.refresh()
        res = app.approval_apply([{"file": i["file"], "key": i["key"]} for i in proj["items"]])
        self.assertEqual(res["changed"], 0)
        self.assertTrue(res["skipped"])

    def test_non_pending_line_has_no_candidates(self):
        app = self.make()
        e = next(e for e in app.project.entries("script.rpy") if not e.pending)
        with self.assertRaises(ValueError):
            bulk.approval_candidates(app.project, "script.rpy", e.line, "project")


class ValidatorTests(unittest.TestCase):
    def test_clean_translation_has_no_findings(self):
        self.assertEqual(issues("{i}Hello{/i} [name], come here{w} now.", "{i}Ahoj{/i} [name], pojď sem{w} hned."), set())

    def test_swapped_word_order_and_czech_longer_is_fine(self):
        self.assertEqual(issues("Where is [name]?", "Kde se, u všech všech svatých, nachází [name]?"), set())

    def test_missing_formatting_tag(self):
        self.assertIn(("warning", "tag-missing"), issues("{i}Hello{/i}", "Ahoj"))
        self.assertIn(("warning", "close-missing"), issues("{i}A{/i} {i}B{/i}", "{i}A{/i} {i}B"))

    def test_stray_and_misnested_close_tags_are_errors(self):
        self.assertIn(("error", "stray-close"), issues("Hello", "Ahoj{/i}"))
        self.assertIn(("error", "mismatched-close"), issues("{b}{i}Hi{/i}{/b}", "{b}{i}Ahoj{/b}{/i}"))

    def test_unclosed_in_source_is_not_blamed_on_translator(self):
        self.assertEqual(issues("{i}Hello", "{i}Ahoj"), set())
        self.assertIn(("warning", "unclosed"), issues("{i}Hello{/i}", "{i}Ahoj"))

    def test_unknown_variable_is_error_missing_is_warning(self):
        self.assertIn(("error", "variable-unknown"), issues("Hi [name]", "Ahoj [jmeno]"))
        self.assertIn(("warning", "variable-missing"), issues("Hi [name]", "Ahoj"))
        self.assertIn(("warning", "variable-changed"), issues("Hi [name]", "Ahoj [name!u]"))

    def test_unterminated_syntax(self):
        self.assertIn(("error", "unterminated-variable"), issues("Hi", "Ahoj [name"))
        self.assertIn(("error", "unterminated-tag"), issues("Hi", "Ahoj {i"))

    def test_escaped_braces_and_brackets_are_not_tags(self):
        self.assertEqual(issues("Use {{i}} and [[x]", "Použij {{i}} a [[x]"), set())

    def test_nested_variable_expression(self):
        self.assertEqual(issues("Bar [epN_bar_menu[3]]", "Bar [epN_bar_menu[3]]!"), set())

    def test_positional_placeholders_and_percent_formats(self):
        self.assertEqual(issues("Page {}", "Strana {}"), set())
        self.assertIn(("error", "placeholder"), issues("Page {}", "Strana"))
        self.assertIn(("error", "percent-format"), issues("Page %s", "Strana"))
        self.assertEqual(issues("100%% sure", "Na 100%% jistě"), set())
        self.assertEqual(issues("Hello", "Sleva 50% navíc"), set())

    def test_pause_count_is_info_flow_tags_warn(self):
        self.assertEqual({s for s, _c in issues("Wait{w} here{p}", "Počkej tady")}, {"info"})
        self.assertIn(("warning", "single-tag"), issues("Go{nw}", "Jdi"))

    def test_tag_arguments(self):
        self.assertIn(("warning", "tag-arg"), issues("{color=#fff}Hi{/color}", "{color=#f00}Ahoj{/color}"))
        self.assertEqual(issues("{color=#fff}Hi{/color}", "{color=#fff}Ahoj{/color}"), set())

    def test_newline_escape_count(self):
        self.assertIn(("warning", "newline-count"), issues("A\\nB", "AB"))
        self.assertIn(("error", "bad-escape"), issues("A", "A\\"))

    def test_comment_tag_difference_is_info(self):
        self.assertEqual({s for s, _ in issues("{#month}May", "Květen")}, {"info"})

    def test_length_is_review_aid_with_thresholds(self):
        src = "This is a normal sentence of average length."
        self.assertEqual(validator.check_length(src, "Toto je běžná věta o průměrné délce, trochu delší."), [])
        long = validator.check_length(src, "x" * 130)
        self.assertEqual((long[0].severity, long[0].code, long[0].category), ("warning", "length-long", "length"))
        self.assertIn("ratio", long[0].extra)
        self.assertEqual(validator.check_length(src, "Ano.")[0].code, "length-short")
        self.assertEqual(validator.check_length("Hi.", "x" * 80), [])                 # tiny source: ignored
        self.assertEqual(validator.check_length(src, "x" * 130, {"enabled": False}), [])
        self.assertEqual(validator.check_length(src, "x" * 130, {"max_ratio": 4.0}), [])

    def test_tags_and_variables_do_not_count_as_length(self):
        src = "{color=#ffffff}{size=+3}Hello there my friend{/size}{/color}"
        self.assertEqual(validator.visible_length(src), len("Hello there my friend"))
        self.assertEqual(validator.visible_length("Hi [name]!"), len("Hi XXXXX!"))

    def test_entry_level_structure_checks(self):
        text = ('translate czech a:\n\n    # mc "Hello"\n    de "Ahoj"\n\n'
                'translate czech b:\n\n    # mc "Hello" with vpunch\n    mc "Ahoj"\n\n')
        p = rpy.parse_text(text)
        codes = {(i.code) for _l, i, _e in validator.check_parsed(p)}
        self.assertEqual(codes, {"speaker-changed", "suffix-changed"})

    def test_untranslated_and_empty_lines_are_not_validated(self):
        p = rpy.parse_text(dialog("a", "mc", "{i}Hello{/i}") + dialog("b", "mc", "Hi [name]", ""))
        self.assertEqual(validator.check_parsed(p), [])

    def test_validator_never_modifies_text(self):
        p = rpy.parse_text(dialog("a", "mc", "{i}Hello", "Ahoj{/i}"))
        before = [e.target for e in p.entries]
        validator.check_parsed(p)
        self.assertEqual(before, [e.target for e in p.entries])


class EstimateTests(unittest.TestCase):
    def pts(self, days, per_day, start=1000, total=10000, end=date(2026, 10, 14)):
        return [(datetime.combine(end - timedelta(days=days - 1 - i), datetime.min.time()) + timedelta(hours=12),
                 start + per_day * i, total, 0) for i in range(days)]

    def test_single_day_of_data_gives_no_date(self):
        e = hist.estimate([(datetime(2026, 10, 14, 10, 0), 1100, 10000, 0), (datetime(2026, 10, 14, 15, 0), 3000, 10000, 0)],
                          3000, 10000, today=date(2026, 10, 14))
        self.assertEqual((e["status"], e["eta"]), ("insufficient_data", None))
        self.assertIn("málo dat", e["reason"])

    def test_empty_history(self):
        self.assertEqual(hist.estimate([], 0, 100, today=date(2026, 10, 14))["status"], "insufficient_data")

    def test_steady_pace_gives_projection(self):
        pts = self.pts(15, 100)
        done_now = pts[-1][1]
        e = hist.estimate(pts, done_now, 10000, today=date(2026, 10, 14))
        self.assertEqual(e["status"], "ok")
        self.assertAlmostEqual(e["pace_per_day"], 100.0, delta=1)
        self.assertEqual(e["eta"], date(2026, 10, 14) + timedelta(days=round((10000 - done_now) / 100)))
        self.assertIn(e["confidence"], ("medium", "high"))

    def test_short_history_is_refused(self):
        e = hist.estimate(self.pts(5, 100), 1400, 10000, today=date(2026, 10, 14))
        self.assertEqual(e["status"], "insufficient_data")

    def test_two_points_a_month_apart_are_refused(self):
        pts = [(datetime(2026, 9, 10, 12), 1000, 10000, 0), (datetime(2026, 10, 14, 12), 5000, 10000, 0)]
        self.assertEqual(hist.estimate(pts, 5000, 10000, today=date(2026, 10, 14))["status"], "insufficient_data")

    def test_stale_history_is_refused(self):
        pts = self.pts(12, 100, end=date(2026, 7, 1))
        e = hist.estimate(pts, pts[-1][1], 10000, today=date(2026, 10, 14))
        self.assertNotEqual(e["status"], "ok")

    def test_no_progress_and_complete(self):
        pts = self.pts(15, 0, start=2000)
        self.assertEqual(hist.estimate(pts, 2000, 10000, today=date(2026, 10, 14))["status"], "no_progress")
        self.assertEqual(hist.estimate(pts, 10000, 10000, today=date(2026, 10, 14))["status"], "complete")

    def test_absurdly_far_projection_is_not_dated(self):
        pts = self.pts(15, 1)
        e = hist.estimate(pts, pts[-1][1], 10_000_000, today=date(2026, 10, 14))
        self.assertEqual((e["status"], e["eta"]), ("too_far", None))

    def test_projection_follows_current_remaining_work(self):
        pts = self.pts(15, 100)
        a = hist.estimate(pts, 2400, 10000, today=date(2026, 10, 14))
        b = hist.estimate(pts, 2400, 12000, today=date(2026, 10, 14))      # more work was added
        self.assertGreater(b["eta"], a["eta"])

    def test_spread_gives_early_and_late_dates(self):
        done, pts = 1000, []
        for i in range(29):
            done += 50 if (i // 7) % 2 == 0 else 150
            pts.append((datetime(2026, 9, 16, 12) + timedelta(days=i), done, 10000, 0))
        e = hist.estimate(pts, done, 10000, today=date(2026, 10, 14))
        self.assertEqual(e["status"], "ok")
        self.assertLess(e["eta_early"], e["eta"])
        self.assertGreater(e["eta_late"], e["eta"])


class HistoryFileTests(TempCase):
    def test_record_semantics_and_history_is_preserved(self):
        path = self.tmp / "historie.csv"
        path.write_text("\ufeffdatum;prelozeno;celkem;procenta;korekce;korekce_procenta\n2026-10-13 09:00;10;100;10.0;0;0.0\n", encoding="utf-8")
        h = hist.History(path, self.tmp / "bk")
        self.assertFalse(h.record("2026-10-14 10:00", 10, 100, 10.0, 0, 0.0))       # unchanged -> no new row
        self.assertTrue(h.record("2026-10-14 10:05", 20, 100, 20.0, 0, 0.0))        # new session row
        self.assertTrue(h.record("2026-10-14 10:09", 25, 100, 25.0, 0, 0.0))        # same session -> replaced
        rows = h.rows()
        self.assertEqual([r[1] for r in rows], ["10", "25"])
        self.assertEqual(rows[0][0], "2026-10-13 09:00")                               # old record untouched
        h2 = hist.History(path, self.tmp / "bk")                                       # next session
        h2.record("2026-10-15 08:00", 30, 100, 30.0, 0, 0.0)
        self.assertEqual([r[1] for r in h2.rows()], ["10", "25", "30"])

    def test_unparsable_rows_are_kept(self):
        path = self.tmp / "historie.csv"
        path.write_text("datum;prelozeno;celkem;procenta;korekce;korekce_procenta\nbroken;x\n", encoding="utf-8")
        h = hist.History(path)
        h.record("2026-10-14 10:00", 1, 10, 10.0, 0, 0.0)
        self.assertEqual(h.rows()[0][0], "broken")
        self.assertEqual(len(h.points()), 1)


class ExportTests(TempCase):
    def project(self):
        self.basic_project()
        app = self.new_app()
        for name, v in [("script.rpy", "ep:1"), (rel("scripts", "episode2", "ep2_party.rpy"), "ep:2"),
                        (rel("season2", "scripts", "update5.rpy"), "ep:5"), ("options.rpy", "gen")]:
            app.set_assign(name, v)
        return app

    def test_seasons_episodes_and_totals_are_consistent(self):
        app = self.project()
        d = app.build_export()
        self.assertEqual(export.validate_progress(d), [])
        self.assertEqual([e["n"] for e in d["episodes"]], list(range(1, 9)))
        self.assertEqual([e["season"] for e in d["episodes"]], [1, 1, 1, 1, 2, 2, 2, 2])
        s1, s2, s3 = d["seasons"]
        self.assertEqual((s1["n"], s1["episodes"]), (1, [1, 2, 3, 4]))
        self.assertEqual((s2["n"], s2["episodes"]), (2, [5, 6, 7, 8]))
        e = {x["n"]: x for x in d["episodes"]}
        self.assertEqual(s1["translation"]["total"], e[1]["translation"]["total"] + e[2]["translation"]["total"])
        self.assertEqual(s2["translation"]["total"], e[5]["translation"]["total"])
        parts = sum(x["translation"]["total"] for x in d["episodes"]) + d["general"]["translation"]["total"] + d["unassigned"]["translation"]["total"]
        self.assertEqual(parts, d["translation"]["total"])
        self.assertEqual(d["unassigned"]["translation"]["total"], 0)

    def test_season_three_is_planned_and_has_no_numbers(self):
        d = self.project().build_export()
        self.assertEqual(d["seasons"][2], {"n": 3, "status": "planned"})
        self.assertEqual(d["scope"]["planned_seasons"], [3])
        self.assertEqual(d["scope"]["seasons"], [1, 2])
        self.assertFalse(any(e["n"] > 8 for e in d["episodes"]))

    def test_empty_episodes_have_no_invented_numbers(self):
        d = self.project().build_export()
        ep3 = d["episodes"][2]
        self.assertEqual((ep3["translation"]["total"], ep3["translation"]["percent"], ep3["files_total"]), (0, None, 0))
        self.assertNotIn("percent", ep3)             # schema-1 key only present when files exist
        self.assertIn("percent", d["episodes"][0])

    def test_schema_1_keys_remain(self):
        d = self.project().build_export()
        for k in ("title", "updated", "translation", "proofreading", "files", "episodes", "history"):
            self.assertIn(k, d)
        self.assertEqual(set(d["files"]), {"none", "wip", "tr", "rev", "done", "total"})
        self.assertEqual(set(d["episodes"][0]) >= {"n", "status", "percent", "files"}, True)

    def test_public_data_has_no_file_names(self):
        d = self.project().build_export()
        self.assertNotIn(".rpy", json.dumps(d))
        d["title"] = "leak script.rpy"
        self.assertTrue(any("názvy souborů" in p for p in export.validate_progress(d)))

    def test_validation_catches_inconsistent_data(self):
        d = self.project().build_export()
        d["seasons"][0]["translation"]["done"] += 1
        self.assertTrue(export.validate_progress(d))
        d = self.project().build_export()
        d["episodes"][4]["season"] = 1
        self.assertTrue(export.validate_progress(d))
        d = self.project().build_export()
        d["seasons"][2]["translation"] = {"done": 0, "total": 0, "percent": 0}
        self.assertTrue(any("Plánovaná" in p for p in export.validate_progress(d)))
        d = self.project().build_export()
        d["translation"]["percent"] = 140
        self.assertTrue(export.validate_progress(d))

    def test_write_local_refuses_invalid_and_writes_atomically(self):
        app = self.project()
        d = app.build_export()
        out = self.tmp / "progress.json"
        export.write_local(out, d)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["schema"], 2)
        bad = dict(d, translation={"done": 5, "total": 1, "percent": 500})
        with self.assertRaises(ValueError):
            export.write_local(out, bad)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["translation"], d["translation"])

    def test_planned_season_does_not_change_active_percentages(self):
        app = self.project()
        d = app.build_export()
        active = [s for s in d["seasons"] if s["status"] == "active"]
        s_done = sum(s["translation"]["done"] for s in active) + d["general"]["translation"]["done"] + d["unassigned"]["translation"]["done"]
        s_total = sum(s["translation"]["total"] for s in active) + d["general"]["translation"]["total"] + d["unassigned"]["translation"]["total"]
        self.assertEqual((s_done, s_total), (d["translation"]["done"], d["translation"]["total"]))   # nothing from season 3

    def test_estimate_block_when_history_is_short(self):
        d = self.project().build_export()
        self.assertEqual(d["estimate"]["status"], "insufficient_data")
        self.assertIsNone(d["estimate"]["eta"])

    def test_overview_matches_export(self):
        app = self.project()
        o, d = app.overview(), app.build_export()
        self.assertEqual(o["seasons"], d["seasons"])
        self.assertEqual(o["totals"]["total"], d["translation"]["total"])


if __name__ == "__main__":
    unittest.main()
