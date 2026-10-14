// Language switch (CZ/EN) and progress rendering. Reads progress.json; renders with textContent only.
const T = {
  cs: {
    locale: "cs-CZ", title: "Being a DIK – český překlad (fan project)",
    lines: "řádků", checked: "řádků zkontrolováno", noData: "Zatím bez dat",
    status: { none: "Nezačato", wip: "Rozpracováno", tr: "Přeloženo", done: "Hotovo" },
    files: [["none", "Nezačato"], ["wip", "Rozpracováno"], ["tr", "Přeloženo"], ["rev", "Korektura"], ["done", "Hotovo"]],
    ago: (n) => (n <= 0 ? "dnes" : n === 1 ? "včera" : `před ${n} dny`),
    updated: (full, ago) => `Aktualizováno ${full} (${ago})`,
    noUpdate: "Zatím bez aktualizace",
    epDone: (d, t) => `${d} / ${t} hotovo`,
    days: (n) => `${n} ${n === 1 ? "den" : n < 5 ? "dny" : "dní"}`,
    chartAria: (a, b) => `Vývoj v čase: překlad ${a} procent, korektura ${b} procent`,
    ep: "EP",
  },
  en: {
    locale: "en-GB", title: "Being a DIK – Czech translation (fan project)",
    lines: "lines", checked: "lines checked", noData: "No data yet",
    status: { none: "Not started", wip: "In progress", tr: "Translated", done: "Done" },
    files: [["none", "Not started"], ["wip", "In progress"], ["tr", "Translated"], ["rev", "Proofreading"], ["done", "Done"]],
    ago: (n) => (n <= 0 ? "today" : n === 1 ? "yesterday" : `${n} days ago`),
    updated: (full, ago) => `Updated ${full} (${ago})`,
    noUpdate: "No update yet",
    epDone: (d, t) => `${d} / ${t} done`,
    days: (n) => `${n} ${n === 1 ? "day" : "days"}`,
    chartAria: (a, b) => `Progress over time: translation ${a} percent, proofreading ${b} percent`,
    ep: "EP",
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

function fillCard(card, block, noun) {
  const percent = Math.max(0, Math.min(100, Number(block.percent) || 0));
  $("[data-pct]", card).textContent = percent.toFixed(1).replace(".", lang === "cs" ? "," : ".");
  $("[data-meta]", card).textContent = block.total ? `${num(block.done)} / ${num(block.total)} ${noun}` : T[lang].noData;
  const bar = $(".bar", card);
  bar.setAttribute("aria-valuenow", String(Math.round(percent)));
  bar.setAttribute("aria-label", $(".label", card).textContent);
  requestAnimationFrame(() => { $("i", bar).style.transform = `scaleX(${percent / 100})`; });
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

function renderEpisodes(episodes) {
  const list = $("#episodesList");
  list.replaceChildren();
  let done = 0;
  for (const ep of episodes) {
    const status = Object.hasOwn(T.cs.status, ep.status) ? ep.status : "none";
    if (status === "done") done += 1;
    const li = el("li", "ep");
    li.dataset.status = status;
    const shape = svg("svg", { viewBox: "0 0 220 96", preserveAspectRatio: "none", "aria-hidden": "true" });
    shape.append(svg("polygon", { points: "2,2 218,2 196,48 218,94 2,94" }));
    li.append(shape, el("span", "ep-n", `${T[lang].ep} ${String(ep.n).padStart(2, "0")}`), el("span", "ep-s", T[lang].status[status]));
    list.append(li);
  }
  $("#epCount").textContent = episodes.length ? T[lang].epDone(done, episodes.length) : "";
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
  for (const f of [0, 0.5, 1]) {
    const gy = H - PAD - f * (H - PAD * 2);
    chart.append(svg("line", { x1: PAD, x2: W - PAD, y1: gy, y2: gy, stroke: "rgba(245,236,214,0.16)", "stroke-dasharray": f === 0 ? "0" : "4 5" }));
  }
  chart.append(
    svg("polygon", { points: `${x(t0)},${y(0)} ${line("a")} ${x(last.t)},${y(0)}`, fill: "rgba(226,176,74,0.13)" }),
    svg("polyline", { points: line("a"), fill: "none", stroke: "#e2b04a", "stroke-width": 2.4, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }),
    svg("polyline", { points: line("b"), fill: "none", stroke: "#f5ecd6", "stroke-width": 2.4, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }),
    svg("circle", { cx: x(last.t), cy: y(last.a), r: 3.8, fill: "#e2b04a" }),
  );
  const fmt = (ms) => new Intl.DateTimeFormat(T[lang].locale, { day: "numeric", month: "short", year: "numeric" }).format(ms);
  const axis = el("div", "chart-axis");
  axis.append(el("span", "", fmt(t0)), el("span", "", `0–${top} %`), el("span", "", fmt(last.t)));
  box.replaceChildren(chart, axis);
  $("#histRange").textContent = T[lang].days(Math.max(1, Math.round(span / 86400000)));
}

function renderUpdated(iso) {
  const when = iso ? new Date(iso) : null;
  if (!when || Number.isNaN(when.getTime())) { $("#updated").textContent = T[lang].noUpdate; return; }
  const days = Math.floor((Date.now() - when.getTime()) / 86400000);
  const full = new Intl.DateTimeFormat(T[lang].locale, { dateStyle: "long", timeStyle: "short" }).format(when);
  $("#updated").textContent = T[lang].updated(full, T[lang].ago(days));
}

function render(d) {
  fillCard($("#cardTr"), d.translation || {}, T[lang].lines);
  fillCard($("#cardPr"), d.proofreading || {}, T[lang].checked);
  renderFiles(d.files || {});
  renderEpisodes(Array.isArray(d.episodes) ? d.episodes : []);
  renderChart(Array.isArray(d.history) ? d.history : []);
  renderUpdated(d.updated);
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
