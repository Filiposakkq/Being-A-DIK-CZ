// Language switch (CZ/EN) and progress rendering. Reads progress.json, normalizes it with
// progress-model.js and renders with textContent only (no innerHTML, so data can never inject markup).
const T = {
  cs: {
    locale: "cs-CZ", title: "Being a DIK – český překlad (fan project)",
    lines: "řádků", checked: "řádků zkontrolováno", noData: "Zatím bez dat",
    status: { none: "Nezačato", wip: "Rozpracováno", tr: "Přeloženo", proof: "V korekci", done: "Hotovo" },
    files: [["none", "Nezačato"], ["wip", "Rozpracováno"], ["tr", "Přeloženo"], ["rev", "Korektura"], ["done", "Hotovo"]],
    ago: (n) => (n <= 0 ? "dnes" : n === 1 ? "včera" : `před ${n} dny`),
    updated: (full, ago) => `Aktualizováno ${full} (${ago})`,
    noUpdate: "Zatím bez aktualizace",
    epDone: (d, t) => `${d} / ${t} epizod hotovo`,
    days: (n) => `${n} ${n === 1 ? "den" : n < 5 ? "dny" : "dní"}`,
    chartAria: (a, b) => `Vývoj v čase: překlad ${a} procent, korektura ${b} procent`,
    ep: "EP", tr: "Překlad", pr: "Korektura",
    season: (n) => `Sezóna ${n}`, seasonKicker: (n) => `Sezóna ${n}`,
    range: (a, b) => `Epizody ${a}–${b}`,
    planned: "Plánováno",
    plannedText: "Plánováno do budoucna. Zatím se nepřekládá a nezapočítává se do žádných procent ani do odhadu dokončení.",
    noEpData: "Bez dat", noEpMeta: "Zatím žádné soubory u této epizody",
    seasonLines: (d, t) => `${d} / ${t} řádků`, seasonEps: (d, t) => `${d} z ${t} epizod hotovo`,
    nFiles: (n) => `${n} ${n === 1 ? "soubor" : n < 5 ? "soubory" : "souborů"}`,
    lineCount: (d, t) => `${d} / ${t} řádků`,
    filesOf: (a, b) => `z ${b} souborů celkem`, linesWord: "řádků",
    etaNone: "Zatím málo dat", etaNoneSub: "Odhad se objeví, až bude záznamů z několika týdnů.",
    etaSub: "podle tempa posledních týdnů, může se změnit", etaRange: (a, b) => `rozmezí ${a} – ${b}`,
    etaConf: { low: "nízká jistota", medium: "střední jistota", high: "vysoká jistota" },
    stale: (n) => `Data nebyla aktualizována ${n} dní – mohou být zastaralá.`,
  },
  en: {
    locale: "en-GB", title: "Being a DIK – Czech translation (fan project)",
    lines: "lines", checked: "lines checked", noData: "No data yet",
    status: { none: "Not started", wip: "In progress", tr: "Translated", proof: "Proofreading", done: "Done" },
    files: [["none", "Not started"], ["wip", "In progress"], ["tr", "Translated"], ["rev", "Proofreading"], ["done", "Done"]],
    ago: (n) => (n <= 0 ? "today" : n === 1 ? "yesterday" : `${n} days ago`),
    updated: (full, ago) => `Updated ${full} (${ago})`,
    noUpdate: "No update yet",
    epDone: (d, t) => `${d} / ${t} episodes done`,
    days: (n) => `${n} ${n === 1 ? "day" : "days"}`,
    chartAria: (a, b) => `Progress over time: translation ${a} percent, proofreading ${b} percent`,
    ep: "EP", tr: "Translation", pr: "Proofreading",
    season: (n) => `Season ${n}`, seasonKicker: (n) => `Season ${n}`,
    range: (a, b) => `Episodes ${a}–${b}`,
    planned: "Planned",
    plannedText: "Planned for the future. Not being translated yet, and not counted in any percentage or finish estimate.",
    noEpData: "No data", noEpMeta: "No files assigned to this episode yet",
    seasonLines: (d, t) => `${d} / ${t} lines`, seasonEps: (d, t) => `${d} of ${t} episodes done`,
    nFiles: (n) => `${n} ${n === 1 ? "file" : "files"}`,
    lineCount: (d, t) => `${d} / ${t} lines`,
    filesOf: (a, b) => `of ${b} files in total`, linesWord: "lines",
    etaNone: "Not enough data yet", etaNoneSub: "An estimate appears once there are records from a few weeks.",
    etaSub: "based on the pace of recent weeks, may change", etaRange: (a, b) => `range ${a} – ${b}`,
    etaConf: { low: "low confidence", medium: "medium confidence", high: "high confidence" },
    stale: (n) => `Data has not been updated for ${n} days – it may be outdated.`,
  },
};

const $ = (s, r = document) => r.querySelector(s);
let lang = "cs";
let data = null;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  return n;
}
const num = (n) => new Intl.NumberFormat(T[lang].locale).format(n);
const fmtPct = (p) => (p === null || p === undefined ? null : p.toFixed(1).replace(".", lang === "cs" ? "," : "."));
const fmtDay = (iso) => new Intl.DateTimeFormat(T[lang].locale, { day: "numeric", month: "long", year: "numeric" }).format(new Date(iso + "T12:00:00"));

function pickLang() {
  const q = new URLSearchParams(location.search).get("lang");
  if (q === "cs" || q === "en") return q;
  try {
    const s = localStorage.getItem("badik-lang");
    if (s === "cs" || s === "en") return s;
  } catch { /* storage may be blocked; fall through */ }
  const nav = (navigator.language || "").toLowerCase();
  return nav.startsWith("cs") || nav.startsWith("sk") ? "cs" : "en";
}

function setLang(next, persist) {
  lang = next;
  document.documentElement.dataset.lang = next;
  document.documentElement.lang = next;
  document.title = T[next].title;
  document.querySelectorAll("[data-set-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setLang === next)));
  if (persist) {
    try { localStorage.setItem("badik-lang", next); } catch { /* ignore */ }
  }
  if (data) render(data);
}

function setBar(bar, percent, label) {
  const p = Math.max(0, Math.min(100, percent || 0));
  bar.setAttribute("aria-valuenow", String(Math.round(p)));
  if (label) bar.setAttribute("aria-label", label);
  requestAnimationFrame(() => { $("i", bar).style.transform = `scaleX(${p / 100})`; });
}

function fillCard(card, block, noun) {
  const p = fmtPct(block.percent);
  $("[data-pct]", card).textContent = p === null ? "–" : p;
  $("[data-meta]", card).textContent = block.total ? `${num(block.done)} / ${num(block.total)} ${noun}` : T[lang].noData;
  setBar($(".bar", card), block.percent, $(".label", card).textContent);
}

function renderFiles(files) {
  const list = $("#fileCounts");
  list.replaceChildren();
  for (const [key, label] of T[lang].files) {
    const li = el("li", "", label);
    li.append(el("b", "", String(Number(files[key]) || 0)));
    list.append(li);
  }
}

// "Translated files", "completed episodes", remaining lines and the finish estimate.
// The estimate is shown only when the manager says the history supports one.
function renderFacts(m) {
  const t = T[lang];
  $("#factFiles").textContent = m.files.total !== null ? `${num(m.files.translated)} / ${num(m.files.total)}` : "–";
  $("#factFilesSub").textContent = m.files.total !== null ? t.filesOf(m.files.translated, m.files.total) : "";
  $("#factEps").textContent = m.totalEpisodes ? `${m.completedEpisodes} / ${m.totalEpisodes}` : "–";
  $("#factEpsSub").textContent = m.totalEpisodes ? t.epDone(m.completedEpisodes, m.totalEpisodes) : "";
  $("#factRemaining").textContent = m.remaining !== null ? num(m.remaining) : "–";
  $("#factRemainingSub").textContent = m.remaining !== null ? t.linesWord : "";
  const eta = $("#factEta"), sub = $("#factEtaSub"), e = m.estimate;
  eta.classList.toggle("dim", e.status !== "ok");
  if (e.status === "ok") {
    eta.textContent = fmtDay(e.eta);
    const bits = [t.etaSub];
    if (e.etaEarly && e.etaLate) bits.unshift(t.etaRange(fmtDay(e.etaEarly), fmtDay(e.etaLate)));
    if (e.confidence) bits.push(t.etaConf[e.confidence]);
    sub.textContent = bits.join(" · ");
  } else if (e.status === "complete") {
    eta.textContent = "✓";
    sub.textContent = "";
  } else {
    eta.textContent = t.etaNone;
    sub.textContent = t.etaNoneSub;
  }
  const note = $("#staleNote");
  const msgs = [];
  if (m.warnings.includes("stale")) msgs.push(t.stale(m.ageDays));
  note.hidden = !msgs.length;
  note.textContent = msgs.join(" ");
}

function progressBar(percent, label, extra) {
  const bar = el("div", "bar" + (extra ? " " + extra : ""));
  bar.setAttribute("role", "progressbar");
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  bar.append(document.createElement("i"));
  setBar(bar, percent, label);
  return bar;
}

// "Translation 96,8 %" / "Proofreading 11,6 %" pair with a thin bar each.
function pctPair(tr, pr, big) {
  const t = T[lang];
  const wrap = el("div", "pair" + (big ? " pair-big" : ""));
  for (const [cls, label, block] of [["pt", t.tr, tr], ["pp", t.pr, pr]]) {
    const row = el("div", "pair-row " + cls);
    const p = fmtPct(block.percent);
    const val = el("b", "pair-val");
    if (p === null) val.textContent = "–";
    else val.append(p, el("span", "unit", "%"));
    row.append(el("span", "pair-lbl", label), val);
    wrap.append(row, progressBar(block.percent, label, cls === "pp" ? "bar-alt" : ""));
    if (!big && block.total !== null) wrap.append(el("span", "pair-sub " + cls, t.lineCount(num(block.done), num(block.total))));
  }
  return wrap;
}

function episodeEl(ep) {
  const t = T[lang];
  const li = el("li", "ep");
  li.dataset.status = ep.status;
  li.dataset.episode = String(ep.n);
  const shape = svg("svg", { viewBox: "0 0 220 170", preserveAspectRatio: "none", "aria-hidden": "true" });
  shape.append(svg("polygon", { points: "2,2 218,2 196,85 218,168 2,168" }));
  const top = el("div", "ep-top");
  top.append(el("span", "ep-n", `${t.ep} ${String(ep.n).padStart(2, "0")}`), el("span", "ep-s", t.status[ep.status]));
  const meta = el("div", "ep-meta");
  meta.textContent = ep.files ? t.nFiles(ep.files) : t.noEpMeta;
  if (ep.translation.percent === null && ep.proofreading.percent === null) {
    li.append(shape, top, el("div", "ep-pct nodata", t.noEpData), meta);
  } else {
    li.append(shape, top, pctPair(ep.translation, ep.proofreading, false), meta);
  }
  return li;
}

function seasonEl(s) {
  const t = T[lang];
  const art = el("article", "season" + (s.status === "planned" ? " season-planned" : ""));
  art.dataset.season = String(s.n);
  const head = el("header", "season-head");
  const title = el("div");
  title.append(el("p", "kicker", t.seasonKicker(s.n)), el("h3", "", t.season(s.n)));
  head.append(title);
  if (s.status === "planned") {
    head.append(el("span", "tag-planned", t.planned));
    art.append(head, el("p", "", t.plannedText));
    return art;
  }
  if (s.episodes.length) title.append(el("span", "range", t.range(s.episodes[0].n, s.episodes[s.episodes.length - 1].n)));
  const stats = el("div", "season-stats");
  for (const [cls, label, block] of [["st-tr", t.tr, s.translation], ["st-pr", t.pr, s.proofreading]]) {
    const st = el("div", "st " + cls);
    const p = fmtPct(block.percent);
    const strong = el("strong");
    if (p === null) strong.textContent = "–";
    else strong.append(p, el("span", "unit", "%"));
    st.append(el("span", "st-lbl", label), strong);
    if (block.total !== null) st.append(el("span", "st-sub", `${num(block.done)} / ${num(block.total)}`));
    stats.append(st);
  }
  head.append(stats);
  const meta = el("p", "season-meta");
  const parts = [];
  parts.push(t.seasonEps(s.episodesDone, s.episodesTotal));
  if (s.files) parts.push(t.nFiles(s.files));
  meta.textContent = parts.join(" · ");
  const list = el("ul", "eps");
  for (const ep of s.episodes) list.append(episodeEl(ep));
  art.append(head, progressBar(s.translation.percent, `${t.season(s.n)} – ${t.tr}`),
    progressBar(s.proofreading.percent, `${t.season(s.n)} – ${t.pr}`, "bar-alt bar-thin"), meta, list);
  return art;
}

function renderSeasons(model) {
  $("#seasons").replaceChildren(...model.seasons.map(seasonEl));
  $("#epCount").textContent = model.totalEpisodes ? T[lang].epDone(model.completedEpisodes, model.totalEpisodes) : "";
}

function renderChart(history) {
  const box = $("#chart");
  const pts = history
    .map((h) => ({ t: Date.parse(`${h.date}T12:00:00`), a: Number(h.translation) || 0, b: Number(h.proofreading) || 0 }))
    .filter((p) => Number.isFinite(p.t));
  if (pts.length < 2) { $("#histRange").textContent = ""; return; }

  const W = 600, H = 170, PAD = 6;
  const t0 = pts[0].t, span = Math.max(pts[pts.length - 1].t - t0, 1);
  const top = Math.min(100, Math.max(10, Math.ceil((Math.max(...pts.map((p) => Math.max(p.a, p.b))) * 1.15) / 10) * 10));
  const x = (t) => PAD + ((t - t0) / span) * (W - PAD * 2);
  const y = (v) => H - PAD - (v / top) * (H - PAD * 2);
  const line = (k) => pts.map((p) => `${x(p.t).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];

  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": T[lang].chartAria(last.a.toFixed(1), last.b.toFixed(1)) });
  const frame = el("div", "chart-frame");
  for (const f of [0, 0.5, 1]) {
    const gy = H - PAD - f * (H - PAD * 2);
    chart.append(svg("line", { x1: PAD, x2: W - PAD, y1: gy, y2: gy, stroke: "rgba(245,236,214,0.16)", "stroke-dasharray": f === 0 ? "0" : "4 5" }));
    const tick = el("span", "chart-tick", `${fmtPct(top * f).replace(/[.,]0$/, "")} %`);
    tick.style.top = `${(gy / H) * 100}%`;
    frame.append(tick);
  }
  chart.append(
    svg("polygon", { points: `${x(t0)},${y(0)} ${line("a")} ${x(last.t)},${y(0)}`, fill: "rgba(226,176,74,0.13)" }),
    svg("polygon", { points: `${x(t0)},${y(0)} ${line("b")} ${x(last.t)},${y(0)}`, fill: "rgba(245,236,214,0.07)" }),
    svg("polyline", { points: line("a"), fill: "none", stroke: "#e2b04a", "stroke-width": 2.4, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }),
    svg("polyline", { points: line("b"), fill: "none", stroke: "#f5ecd6", "stroke-width": 2.4, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }),
  );
  // end-of-line values as HTML (SVG text would stretch with the viewBox)
  for (const [k, cls] of [["a", "chart-end-tr"], ["b", "chart-end-pr"]]) {
    const dot = el("i", `chart-dot ${cls}`);
    dot.style.left = `${(x(last.t) / W) * 100}%`;
    dot.style.top = `${(y(last[k]) / H) * 100}%`;
    const val = el("span", `chart-end ${cls}`, `${fmtPct(last[k])} %`);
    val.style.top = `${(y(last[k]) / H) * 100}%`;
    frame.append(dot, val);
  }
  frame.prepend(chart);
  const fmt = (ms) => new Intl.DateTimeFormat(T[lang].locale, { day: "numeric", month: "short", year: "numeric" }).format(ms);
  const axis = el("div", "chart-axis");
  axis.append(el("span", "", fmt(t0)), el("span", "", fmt(last.t)));
  box.replaceChildren(frame, axis);
  $("#histRange").textContent = T[lang].days(Math.max(1, Math.round(span / 86400000)));
}

function renderUpdated(iso) {
  const when = iso ? new Date(iso) : null;
  if (!when || Number.isNaN(when.getTime())) { $("#updated").textContent = T[lang].noUpdate; return; }
  const days = Math.floor((Date.now() - when.getTime()) / 86400000);
  const full = new Intl.DateTimeFormat(T[lang].locale, { dateStyle: "long", timeStyle: "short" }).format(when);
  $("#updated").textContent = T[lang].updated(full, T[lang].ago(days));
}

function render(raw) {
  const m = ProgressModel.normalize(raw);
  fillCard($("#cardTr"), m.translation, T[lang].lines);
  fillCard($("#cardPr"), m.proofreading, T[lang].checked);
  renderFiles(m.files);
  renderFacts(m);
  renderSeasons(m);
  renderChart(m.history);
  renderUpdated(m.updated);
}

async function load() {
  try {
    const res = await fetch("progress.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
    render(data);
  } catch (err) {
    $("#error").hidden = false;
    console.warn("Could not load progress.json:", err);
  }
}

document.querySelectorAll("[data-set-lang]").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.setLang, true)));
setLang(pickLang(), false);
load();
