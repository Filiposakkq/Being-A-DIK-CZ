// Turns the raw progress.json into a safe, uniform model for the page. No DOM here, so it can be
// tested in isolation (tests/web/model.test.html). It never invents numbers: anything missing or
// invalid becomes null and the page shows "no data" for it.
//
// Source of truth: progress.json written by the Translation Manager (tools/translation-manager),
// schema 2 has `seasons` and per-episode line counts; schema 1 (older) only has episodes[n, status,
// percent, files]. Season membership is decided by the manager and sent in the data; the table
// below is only the fallback for old files and must stay equal to prehled/seasons.py (a unit test
// compares them).
(function (root) {
  "use strict";

  const FALLBACK_SEASONS = { 1: [1, 2, 3, 4], 2: [5, 6, 7, 8], 3: [] };
  const PLANNED_SEASONS = [3];
  const STATUSES = ["none", "wip", "tr", "proof", "done"];
  const STALE_DAYS = 45;

  const isNum = (v) => typeof v === "number" && Number.isFinite(v);
  const nonNeg = (v) => (isNum(v) && v >= 0 ? v : null);
  const asObj = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : {});

  function pct(done, total, given) {
    if (isNum(done) && isNum(total) && total > 0 && done <= total) return Math.round((done / total) * 1000) / 10;
    if (isNum(given) && given >= 0 && given <= 100) return given;
    return null;
  }

  function block(raw) {
    const b = asObj(raw);
    const done = nonNeg(b.done), total = nonNeg(b.total);
    const ok = done !== null && total !== null && done <= total;
    return { done: ok ? done : null, total: ok ? total : null, percent: ok ? pct(done, total, b.percent) : pct(null, null, b.percent) };
  }

  function seasonOfFallback(n) {
    for (const [s, eps] of Object.entries(FALLBACK_SEASONS)) if (eps.includes(n)) return Number(s);
    return null;
  }

  function normalizeEpisode(raw) {
    const e = asObj(raw);
    if (!Number.isInteger(e.n) || e.n < 1) return null;
    const hasLines = e.translation !== undefined;
    const translation = hasLines ? block(e.translation) : { done: null, total: null, percent: pct(null, null, e.percent) };
    const proofreading = e.proofreading !== undefined ? block(e.proofreading) : { done: null, total: null, percent: null };
    const files = nonNeg(e.files_total ?? e.files);
    return {
      n: e.n,
      season: Number.isInteger(e.season) ? e.season : seasonOfFallback(e.n),
      status: STATUSES.includes(e.status) ? e.status : "none",
      translation, proofreading,
      files: files === null ? 0 : files,
      filesDone: nonNeg(e.files_done),
      hasData: translation.percent !== null,
    };
  }

  function normalizeEstimate(raw, remaining) {
    const e = asObj(raw);
    const date = (s) => {
      const p = typeof s === "string" && /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
      if (!p) return null;
      const d = new Date(Date.UTC(+p[1], +p[2] - 1, +p[3]));      // rejects 2027-13-45, 2027-02-31 ...
      return d.getUTCFullYear() === +p[1] && d.getUTCMonth() === +p[2] - 1 && d.getUTCDate() === +p[3] ? s : null;
    };
    const eta = date(e.eta);
    const ok = e.status === "ok" && eta !== null;
    return {
      status: ok ? "ok" : (typeof e.status === "string" && e.status !== "ok" ? e.status : "unknown"),
      eta: ok ? eta : null,
      etaEarly: ok ? date(e.eta_early) : null,
      etaLate: ok ? date(e.eta_late) : null,
      confidence: ok && ["low", "medium", "high"].includes(e.confidence) ? e.confidence : null,
      pacePerDay: ok && isNum(e.pace_per_day) && e.pace_per_day > 0 ? e.pace_per_day : null,
      remaining,
    };
  }

  function normalize(raw, now) {
    const d = asObj(raw);
    const warnings = [];
    const translation = block(d.translation);
    const proofreading = block(d.proofreading);
    const f = asObj(d.files);
    const files = {
      none: nonNeg(f.none) ?? 0, wip: nonNeg(f.wip) ?? 0, tr: nonNeg(f.tr) ?? 0, rev: nonNeg(f.rev) ?? 0, done: nonNeg(f.done) ?? 0,
      total: nonNeg(f.total),
    };
    files.translated = files.tr + files.rev + files.done;

    const rawEps = Array.isArray(d.episodes) ? d.episodes : [];
    const episodes = rawEps.map(normalizeEpisode).filter(Boolean).sort((a, b) => a.n - b.n);
    if (rawEps.length && episodes.length !== rawEps.length) warnings.push("some-episodes-ignored");
    const schema = Number.isInteger(d.schema) ? d.schema : 1;
    if (schema < 2) warnings.push("old-schema");

    // seasons: from the data when present, otherwise derived with the fallback table
    const rawSeasons = Array.isArray(d.seasons) ? d.seasons : null;
    const seasonNums = rawSeasons ? rawSeasons.map((s) => asObj(s).n).filter(Number.isInteger)
      : Object.keys(FALLBACK_SEASONS).map(Number);
    const seasons = [];
    for (const n of [...new Set(seasonNums)].sort((a, b) => a - b)) {
      const rs = rawSeasons ? asObj(rawSeasons.find((s) => asObj(s).n === n)) : {};
      const planned = rs.status ? rs.status === "planned" : PLANNED_SEASONS.includes(n);
      if (planned) { seasons.push({ n, status: "planned", episodes: [] }); continue; }
      const eps = episodes.filter((e) => e.season === n);
      let tr = rs.translation ? block(rs.translation) : null;
      let pr = rs.proofreading ? block(rs.proofreading) : null;
      if (!tr) {
        const withLines = eps.filter((e) => e.translation.total !== null);
        tr = withLines.length === eps.length && eps.length ? block({
          done: withLines.reduce((s, e) => s + e.translation.done, 0), total: withLines.reduce((s, e) => s + e.translation.total, 0) }) : { done: null, total: null, percent: null };
      }
      pr = pr || { done: null, total: null, percent: null };
      seasons.push({
        n, status: "active", episodes: eps, translation: tr, proofreading: pr,
        files: eps.reduce((s, e) => s + e.files, 0),
        episodesDone: eps.filter((e) => e.status === "done").length,
        episodesTotal: eps.length,
      });
    }

    const remaining = translation.total !== null ? translation.total - translation.done : null;
    const updated = typeof d.updated === "string" && !Number.isNaN(Date.parse(d.updated)) ? d.updated : null;
    const ageDays = updated ? Math.floor(((now ?? Date.now()) - Date.parse(updated)) / 86400000) : null;
    if (ageDays !== null && ageDays > STALE_DAYS) warnings.push("stale");

    const completed = episodes.filter((e) => e.status === "done").length;
    return {
      schema, updated, ageDays, title: typeof d.title === "string" ? d.title : "",
      translation, proofreading, files, remaining, seasons, episodes,
      completedEpisodes: completed, totalEpisodes: episodes.length,
      estimate: normalizeEstimate(d.estimate, remaining),
      history: (Array.isArray(d.history) ? d.history : []).filter((h) => asObj(h).date && isNum(h.translation)),
      warnings,
    };
  }

  const api = { normalize, FALLBACK_SEASONS, PLANNED_SEASONS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ProgressModel = api;
})(typeof window !== "undefined" ? window : globalThis);
