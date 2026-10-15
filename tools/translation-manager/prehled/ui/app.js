"use strict";
/* BaDIK Translation Manager – UI. Vanilla JS, no build step. All data is inserted with textContent
   (the h() helper), never innerHTML, so file contents can never inject markup. */

const TOKEN = document.querySelector('meta[name=token]').content;
const $ = (s, r = document) => r.querySelector(s);

/* append()/replaceChildren() turn null into the text "null"; conditional children are common here,
   so skip null / undefined / false everywhere. */
for (const m of ['append', 'prepend', 'replaceChildren']) {
  const native = Element.prototype[m];
  Element.prototype[m] = function (...kids) {
    return native.apply(this, kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  };
}

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (['checked', 'disabled', 'selected', 'readOnly', 'multiple'].includes(k)) el[k] = v;
      else if (k === 'value') el.value = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  if (props && props.value !== undefined && tag === 'select') el.value = props.value;
  return el;
}

const nf = new Intl.NumberFormat('cs-CZ');
const plural = (n, one, few, many) => (n === 1 ? one : n >= 2 && n <= 4 ? few : many);     // Czech: 1 řádek, 2–4 řádky, 5 řádků
const fmtN = (n) => nf.format(n ?? 0);
const fmtPct = (p) => (p === null || p === undefined ? '–' : p.toFixed(1).replace('.', ',') + ' %');
const clamp01 = (v) => Math.max(0, Math.min(100, v || 0));
const dateCz = (iso) => iso ? new Date(iso + 'T12:00:00').toLocaleDateString('cs-CZ', { day: 'numeric', month: 'long', year: 'numeric' }) : '';

/* ---------------------------------------------------------------- api */
async function request(method, path, body) {
  const opts = { method, headers: {} };
  let url = '/api/' + path;
  if (method === 'POST') {
    opts.headers['X-Token'] = TOKEN;
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body || {});
  } else if (body) {
    url += '?' + new URLSearchParams(Object.entries(body).filter(([, v]) => v !== '' && v !== undefined && v !== null));
  }
  let res;
  try { res = await fetch(url, opts); }
  catch { throw new Error('Spojení s aplikací se přerušilo – běží ještě program?'); }
  let data;
  try { data = await res.json(); } catch { throw new Error('Neplatná odpověď aplikace.'); }
  if (!data.ok) { const err = new Error(data.error || 'Operace selhala.'); err.data = data; throw err; }
  return data;
}
const get = (p, q) => request('GET', p, q);
const post = (p, b) => request('POST', p, b);

/* ---------------------------------------------------------------- state & prefs */
const S = {
  ready: false, view: 'overview', prefs: {}, notices: [], projectDir: '',
  overview: null, files: null,
  fl: { sel: null, picked: new Set(), lastPick: null },
  ent: { items: [], total: 0, start: 0, sel: -1, loading: false, detail: null, pendingLine: 0 },
  val: { items: [], total: 0 },
  lastRefresh: null,
  gl: {},   // glossary: speaker code -> full name
};

/* Speaker display: the character code ("mc"), the glossary's full name, or both. Attributes
   ("mc happy" -> "happy") are kept. The mode is a persisted preference. */
const speakerMode = () => pref('display.speaker', 'both');   // both = two columns (code, name)
function speakerLabel(who) {
  if (!who) return '';
  const [code, ...attrs] = who.trim().split(/\s+/);
  const name = S.gl[code];
  const rest = attrs.length ? ' ' + attrs.join(' ') : '';
  const mode = speakerMode();
  if (!name || mode === 'code') return who;
  return mode === 'name' ? name + (attrs.length ? ` (${attrs.join(' ')})` : '') : `${name} · ${code}${rest}`;
}
/* "mc happy" -> the glossary name of "mc" */
const speakerName = (who) => S.gl[(who || '').trim().split(/\s+/)[0]] || '';
/* detail pane: code and name always both, as "mc – Name" */
function speakerFull(who) {
  const n = speakerName(who);
  return n ? `${who} – ${n}` : who;
}
async function loadGlossary() {
  try { S.gl = (await get('glossary')).names || {}; } catch { S.gl = {}; }
}
function speakerModeSelect(onchange) {
  return h('select', { title: 'Jak zobrazovat mluvčí', onchange: (ev) => { setPref('display.speaker', ev.target.value); onchange?.(); } },
    ...[['both', 'Mluvčí: kód i jméno (2 sloupce)'], ['code', 'Mluvčí: jen kód'], ['name', 'Mluvčí: jen jméno']].map(([v, l]) => h('option', { value: v, selected: speakerMode() === v }, l)));
}
let prefTimer = null;
const pref = (path, def) => path.split('.').reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), S.prefs) ?? def;
function setPref(path, value) {
  const parts = path.split('.');
  let o = S.prefs;
  for (const k of parts.slice(0, -1)) o = o[k] = o[k] || {};
  o[parts.at(-1)] = value;
  clearTimeout(prefTimer);
  prefTimer = setTimeout(() => post('prefs', S.prefs).catch(() => {}), 500);
}

/* ---------------------------------------------------------------- feedback */
function status(msg, kind) {
  const el = $('#statusText');
  el.textContent = msg;
  el.className = kind || '';
}
function toast(msg, kind = 'ok', ms = 4500) {
  const t = h('div', { class: 'toast ' + kind }, h('span', null, msg), h('button', { class: 'x', title: 'Zavřít', onclick: () => t.remove() }, '✕'));
  $('#toasts').append(t);
  if (ms) setTimeout(() => t.remove(), kind === 'bad' ? ms * 2 : ms);
  status(msg, kind === 'bad' ? 'bad' : 'ok');
}
const fail = (e) => toast(e.message || String(e), 'bad');

function dialog({ title, body, buttons = [], narrow = false, onclose }) {
  const dlg = $('#dlg');
  dlg.className = narrow ? 'narrow' : '';
  dlg.replaceChildren(h('div', { class: 'dlg' },
    h('div', { class: 'dlg-head' }, title),
    h('div', { class: 'dlg-body' }, body),
    h('div', { class: 'dlg-foot' }, ...buttons.map((b) => b.node || h('button', {
      class: 'btn ' + (b.kind || ''), disabled: b.disabled,
      onclick: async () => { const keep = await b.onclick?.(); if (keep !== false) close(); },
    }, b.label)))));
  const close = () => { if (dlg.open) dlg.close(); };
  dlg.onclose = () => { S.dlgDirty = false; onclose?.(); };
  dlg.showModal();
  return close;
}
const dialogOpen = () => $('#dlg').open;
function confirmDialog(title, text, okLabel = 'Pokračovat') {
  return new Promise((resolve) => {
    let answered = false;
    dialog({ title, narrow: true, body: h('p', null, text),
      buttons: [{ label: 'Zrušit', onclick: () => { answered = true; resolve(false); } },
                { label: okLabel, kind: 'primary', onclick: () => { answered = true; resolve(true); } }],
      onclose: () => { if (!answered) resolve(false); } });
  });
}

/* ---------------------------------------------------------------- shared renderers */
function fname(rel, { link = false, onclick } = {}) {
  const p = String(rel);
  const i = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'));
  const wrapBreaks = (s) => s.split(/([\\/_])/).map((t) => (/[\\/_]/.test(t) ? [t, h('wbr')] : t));
  const el = h('div', { class: 'fname' + (link ? ' clickable' : ''), onclick },
    i >= 0 ? [h('span', { class: 'dir' }, wrapBreaks(p.slice(0, i + 1))), wrapBreaks(p.slice(i + 1))] : wrapBreaks(p));
  return el;
}
const TOKEN_RE = /(\{\{|\[\[|\{[^}]*\}|\[[^\]]*\]|\\n|\\")/g;
function fmtText(text) {
  const frag = document.createDocumentFragment();
  for (const part of String(text ?? '').split(TOKEN_RE)) {
    if (!part) continue;
    if (part.startsWith('{') && part !== '{{') frag.append(h('span', { class: 'tok-tag' }, part));
    else if (part.startsWith('[') && part !== '[[') frag.append(h('span', { class: 'tok-var' }, part));
    else if (part === '\\n' || part === '\\"') frag.append(h('span', { class: 'tok-esc' }, part));
    else frag.append(part);
  }
  return frag;
}
/* Renders Ren'Py text markup as it would read in the game: {i}{b}{u}{s}{color=..}, \n and {p} as line breaks, [variables] as XXXXX;
   waits and other tags are dropped. Only text nodes and a few styled elements are created, so nothing from the text is ever run as HTML. */
function gameText(text) {
  const root = document.createElement('span');
  const stack = [root];
  const top = () => stack[stack.length - 1];
  const open = (tag, color) => { const el = document.createElement(tag); if (color) el.style.color = color; el.dataset.tag = tag; top().append(el); stack.push(el); };
  const close = (tag) => { for (let i = stack.length - 1; i > 0; i--) if (stack[i].dataset.tag === tag) { stack.length = i; return; } };
  const re = /\{\{|\[\[|\{(\/?)(i|b|u|s)\}|\{color=([^}]*)\}|\{\/color\}|\{p(?:=[^}]*)?\}|\{[^}]*\}|\[[^\]]*\]|\\n|\\"|\\\\|\\./g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) top().append(text.slice(last, m.index));
    const t = m[0];
    if (t === '{{') top().append('{');
    else if (t === '[[') top().append('[');
    else if (m[2]) { if (m[1]) close(m[2]); else open(m[2]); }
    else if (m[3] !== undefined) { const c = m[3].trim(); open('span', /^#?[0-9a-fA-F]{3,8}$/.test(c) ? (c[0] === '#' ? c : '#' + c) : /^[a-z]+$/i.test(c) ? c : ''); }
    else if (t === '{/color}') close('span');
    else if (t === '\\n' || t.startsWith('{p')) top().append(document.createElement('br'));
    else if (t === '\\"') top().append('"');
    else if (t === '\\\\') top().append('\\');
    else if (t[0] === '[') top().append('XXXXX');
    else if (t[0] === '\\') top().append(t[1]);
    /* any other {tag}: waits, speed, comments ... are invisible */
    last = re.lastIndex;
  }
  if (last < text.length) top().append(text.slice(last));
  return root;
}
const STATUS_LABEL = { done: 'Hotovo', rev: 'Korektura', proof: 'V korekci', tr: 'Přeloženo', wip: 'Rozpracováno', none: 'Nezačato', planned: 'Plánováno' };
const ENTRY_LABEL = { translated: 'Přeloženo', approved: 'Schváleno', todo: 'Nepřeloženo' };
const KIND_LABEL = { empty: 'prázdný', english: 'anglicky', same: 'shodné', symbols: 'jen znaky' };
const SEV_LABEL = { error: 'Chyba', warning: 'Varování', info: 'Info' };
const proofChip = (p) => (p === 'ok' ? chip('proof', '✓ zkontrolováno') : p === 'fix' ? chip('warning', '⚑ k opravě')
  : p === 'stale' ? chip('info', '↻ změněno po korektuře') : null);
const chip = (cls, text) => h('span', { class: 'chip ' + cls }, text);
function bar(pct, cls = '') { return h('div', { class: 'bar ' + cls }, h('i', { style: { width: clamp01(pct) + '%' } })); }
function empty(title, text) { return h('div', { class: 'empty' }, h('b', null, title), text); }
function loading(text = 'Načítám…') { return h('div', { class: 'loading' }, h('span', { class: 'spin' }), ' ' + text); }
const isTyping = (t) => t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable);

/* resizable, sortable table with a persisted column layout */
/* Draggable divider between a list and its detail pane. axis 'v': detail below (height), 'h': detail on the right
   (width). The size is clamped (min px, max share of the area), saved as a preference, double-click resets it,
   arrow keys resize it when it has focus. */
function makeSplitter(root, axis, { key, def, min, maxFrac }) {
  const vertical = axis === 'v';
  const prop = vertical ? '--detail-h' : '--detail-w';
  const bar = h('div', { class: 'splitter ' + (vertical ? 'sp-v' : 'sp-h'), role: 'separator', tabindex: '0',
    'aria-orientation': vertical ? 'horizontal' : 'vertical', title: 'Tažením změníš velikost detailu, dvojklik ji vrátí. S fokusem fungují šipky.' });
  const clampTo = (v) => {
    const total = vertical ? root.clientHeight : root.clientWidth;
    const max = Math.max(min, Math.floor(total * maxFrac));
    return Math.round(Math.max(min, Math.min(max, v)));
  };
  const apply = (v, save) => { const c = clampTo(v); root.style.setProperty(prop, c + 'px'); if (save) setPref(key, c); return c; };
  const current = () => parseInt(root.style.getPropertyValue(prop), 10) || def;
  const fromPointer = (ev) => { const r = root.getBoundingClientRect(); return vertical ? r.bottom - ev.clientY : r.right - ev.clientX; };
  bar.addEventListener('pointerdown', (e) => {
    e.preventDefault(); bar.setPointerCapture(e.pointerId); bar.classList.add('drag');
    const move = (ev) => apply(fromPointer(ev), false);
    const up = (ev) => { bar.classList.remove('drag'); bar.removeEventListener('pointermove', move); bar.removeEventListener('pointerup', up); apply(fromPointer(ev), true); };
    bar.addEventListener('pointermove', move); bar.addEventListener('pointerup', up);
  });
  bar.addEventListener('dblclick', () => apply(def, true));
  bar.addEventListener('keydown', (e) => {
    const step = e.shiftKey ? 80 : 20;
    const grow = e.key === (vertical ? 'ArrowUp' : 'ArrowLeft'), shrink = e.key === (vertical ? 'ArrowDown' : 'ArrowRight');
    if (grow || shrink) { e.preventDefault(); apply(current() + (grow ? step : -step), true); }
    else if (e.key === 'Home') { e.preventDefault(); apply(def, true); }
  });
  bar.sync = () => apply(pref(key, def), false);      // re-clamp after the window changed size
  S.splitSync = () => bar.sync();
  return bar;
}
window.addEventListener('resize', () => S.splitSync?.());

function buildTable({ key, cols, sort, onSort, className = '' }) {
  const saved = pref(key + '.colw', {});
  const colgroup = h('colgroup', null, cols.map((c) => h('col', { style: { width: (saved[c.k] || c.w) + 'px' } })));
  const total = () => cols.reduce((s, c, i) => s + parseInt(colgroup.children[i].style.width, 10), 0);
  const table = h('table', { class: 'data ' + className });
  const fit = () => { table.style.width = Math.max(total(), 0) + 'px'; };
  const head = h('tr', null, cols.map((c, i) => {
    const th = h('th', { class: (c.sortable ? 'sortable ' : '') + (c.center ? 'center' : ''), title: c.title || '',
      onclick: c.sortable ? () => onSort?.(c.k) : undefined, style: { position: 'sticky' } },
      c.node || c.label, sort && sort.k === c.k ? h('span', { class: 'arrow' }, sort.dir > 0 ? ' ▲' : ' ▼') : null);
    if (c.resize !== false) {
      const rz = h('span', { class: 'rz', title: 'Tažením změníš šířku sloupce' });
      rz.addEventListener('click', (e) => e.stopPropagation());
      rz.addEventListener('mousedown', (e) => {
        e.preventDefault(); e.stopPropagation();
        const x0 = e.clientX, w0 = parseInt(colgroup.children[i].style.width, 10);
        rz.classList.add('drag');
        const move = (ev) => { colgroup.children[i].style.width = Math.max(40, w0 + ev.clientX - x0) + 'px'; fit(); };
        const up = () => {
          rz.classList.remove('drag');
          removeEventListener('mousemove', move); removeEventListener('mouseup', up);
          const w = {}; cols.forEach((cc, j) => { w[cc.k] = parseInt(colgroup.children[j].style.width, 10); });
          setPref(key + '.colw', w);
        };
        addEventListener('mousemove', move); addEventListener('mouseup', up);
      });
      th.append(rz);
    }
    return th;
  }));
  const tbody = h('tbody'); const tfoot = h('tfoot');
  table.append(colgroup, h('thead', null, head), tbody, tfoot);
  fit();
  return { table, tbody, tfoot };
}

/* ---------------------------------------------------------------- filter bar pieces (shared by all tabs) */
const filterGroup = (label, ...controls) => h('label', { class: 'fgroup' }, h('span', { class: 'flabel' }, label), ...controls);
/* A row of "pills" (one per option, with a count) – the main filter of a list. */
function pillRow(options, current, counts, onPick) {
  return options.map(([k, label]) => {
    const n = counts ? counts[k] : undefined;
    return h('button', { class: 'pill' + (current === k ? ' on' : '') + (n === 0 && current !== k ? ' zero' : ''), 'aria-pressed': String(current === k), onclick: () => onPick(k) },
      label, n !== undefined && n !== null ? h('span', { class: 'pc' }, fmtN(n)) : null);
  });
}
/* "Active filters" row: one removable chip per narrowing filter plus a reset. items: [[text, clearFn]] */
function activeChips(items, resetAll) {
  if (!items.length) return [];
  return [h('span', { class: 'flabel' }, 'Aktivní filtry:'),
    ...items.map(([text, clear]) => h('span', { class: 'fchip' }, text, h('button', { title: 'Zrušit tento filtr', 'aria-label': 'Zrušit filtr: ' + text, onclick: clear }, '✕'))),
    h('button', { class: 'btn small ghost', onclick: resetAll }, 'Zrušit všechny filtry')];
}

/* ---------------------------------------------------------------- tabs */
const TABS = [['overview', 'Přehled'], ['files', 'Soubory'], ['entries', 'Řádky'], ['validation', 'Kontrola'], ['glossary', 'Slovník'], ['publish', 'Publikace'], ['settings', 'Nastavení']];
/* Small stroke icons for the tabs (24x24, drawn here so no icon font or file is needed). */
const TAB_ICONS = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  files: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  entries: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
  validation: '<path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  glossary: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
  publish: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
};
function tabIcon(k) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('viewBox', '0 0 24 24'); el.setAttribute('fill', 'none'); el.setAttribute('stroke', 'currentColor');
  el.setAttribute('stroke-width', '1.8'); el.setAttribute('stroke-linecap', 'round'); el.setAttribute('stroke-linejoin', 'round'); el.setAttribute('aria-hidden', 'true');
  el.innerHTML = TAB_ICONS[k] || '';
  return el;
}
function renderTabs() {
  const nav = $('#tabs');
  nav.replaceChildren(...TABS.map(([k, label], i) => {
    const bad = k === 'validation' && S.overview ? S.overview.validation.error : 0;
    return h('button', { class: 'tab', role: 'tab', 'aria-selected': String(S.view === k), title: `Alt+${i + 1}`, onclick: () => go(k) },
      tabIcon(k), label, bad ? h('span', { class: 'badge' }, fmtN(bad)) : null);
  }));
}

/* Look: automatic (follows the system) / dark / light. Stored as a preference, applied through the data-theme attribute. */
const DENSITY_LABEL = { comfortable: 'pohodlná', compact: 'kompaktní' };
function applyDensity() {
  const dn = pref('ui.density', 'comfortable') === 'compact' ? 'compact' : 'comfortable';
  document.documentElement.dataset.density = dn;
  const b = $('#densityBtn');
  if (b) { b.textContent = dn === 'compact' ? '☰' : '≡'; b.title = `Hustota tabulek: ${DENSITY_LABEL[dn]} (klik přepne)`; }
}
function toggleDensity() {
  setPref('ui.density', pref('ui.density', 'comfortable') === 'compact' ? 'comfortable' : 'compact');
  applyDensity();
  toast(`Hustota tabulek: ${DENSITY_LABEL[pref('ui.density', 'comfortable')]}`, 'ok', 1400);
}
const THEME_ICON = { auto: '◐', dark: '☾', light: '☀' };
const THEME_LABEL = { auto: 'automaticky podle systému', dark: 'tmavý', light: 'světlý' };
function applyTheme() {
  const t = ['auto', 'dark', 'light'].includes(pref('ui.theme', 'auto')) ? pref('ui.theme', 'auto') : 'auto';
  const light = t === 'light' || (t === 'auto' && window.matchMedia?.('(prefers-color-scheme: light)').matches);
  document.documentElement.dataset.theme = light ? 'light' : 'dark';
  const b = $('#themeBtn');
  if (b) { b.textContent = THEME_ICON[t]; b.title = `Vzhled: ${THEME_LABEL[t]} (klik přepne)`; }
}
function cycleTheme() {
  const order = ['auto', 'dark', 'light'];
  setPref('ui.theme', order[(order.indexOf(pref('ui.theme', 'auto')) + 1) % 3]);
  applyTheme();
  toast(`Vzhled: ${THEME_LABEL[pref('ui.theme', 'auto')]}`, 'ok', 1600);
}
window.matchMedia?.('(prefers-color-scheme: light)').addEventListener?.('change', () => applyTheme());
function go(view, opts) {
  S.view = view; setPref('view', view);
  S.goOpts = opts || null;
  renderTabs(); render();
}

async function render() {
  const view = $('#view');
  view.className = ['entries', 'files'].includes(S.view) && S.ready ? 'flush' : '';
  if (!S.ready) return renderWelcome();
  const token = (S.renderToken = (S.renderToken || 0) + 1);
  view.replaceChildren(loading());
  try {
    const fn = { overview: viewOverview, files: viewFiles, entries: viewEntries, validation: viewValidation, glossary: viewGlossary, publish: viewPublish, settings: viewSettings }[S.view];
    const node = await fn();
    if (token !== S.renderToken) return;
    view.replaceChildren(node);
    node.afterMount?.();
  } catch (e) {
    view.replaceChildren(h('div', { class: 'notice bad' }, e.message));
  }
}

/* ---------------------------------------------------------------- welcome / project */
function renderWelcome() {
  const view = $('#view');
  view.className = '';
  const input = h('input', { type: 'text', id: 'welPath', placeholder: 'D:\\Hra\\game\\tl\\czech', value: S.projectDir || '' });
  const notes = S.notices.map((n) => h('div', { class: 'notice warn' }, n));
  view.replaceChildren(h('div', { class: 'panel welcome' },
    h('h1', null, 'Vyber složku s překladem'),
    h('p', { class: 'muted' }, 'Složka s přeloženými soubory .rpy, typicky ', h('span', { class: 'mono' }, 'game/tl/czech'),
      '. Aplikace si ji pamatuje a příště ji otevře sama.'),
    ...notes,
    h('div', { class: 'row' }, input,
      h('button', { class: 'btn', onclick: pickProject }, 'Procházet…'),
      h('button', { class: 'btn primary', onclick: () => openProject(input.value) }, 'Otevřít')),
    h('p', { class: 'muted', style: { marginTop: '12px' } }, 'Cestu můžeš také vložit ručně. Data aplikace se ukládají do podsložky ', h('span', { class: 'mono' }, '_progress_data'), '.')));
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') openProject(input.value); });
}
/* Another running copy of the app owns the project: offer to take it over (the other copy then shows a warning). */
async function offerTakeover(e) {
  if (!e.data?.locked) return false;
  const ok = await confirmDialog('Projekt používá jiná kopie aplikace', `${e.message} Převzít projekt jen když víš, že druhá kopie už neběží nebo ji zavřeš.`, 'Převzít projekt');
  if (ok) await openProject(e.data.path, true);
  return true;
}
async function openProject(path, force = false) {
  if (!path.trim()) return toast('Zadej cestu ke složce.', 'bad');
  try { status('Otevírám projekt…'); await post('project/set', { path, force }); await afterProjectChange(); } catch (e) { if (!await offerTakeover(e)) fail(e); }
}
async function pickProject() {
  try {
    const r = await post('project/pick', {});
    if (r.cancelled) return status('Výběr složky zrušen.');
    await afterProjectChange();
  } catch (e) { if (!await offerTakeover(e)) fail(e); }
}
async function afterProjectChange() {
  const st = await get('state');
  S.ready = st.ready; S.notices = st.notices; S.projectDir = st.project_dir;
  S.files = null; S.overview = null; S.ent.items = []; S.ent.sel = -1; S.fl.picked.clear();
  await refreshHeader();
  if (S.ready) await loadGlossary();
  render();
  if (S.ready) toast('Projekt otevřen.');
}
async function refreshHeader() {
  $('#projectPath').textContent = S.ready ? S.projectDir : 'žádný projekt';
  $('#undoBtn').disabled = true;
  $('#refreshBtn').disabled = !S.ready;
  if (S.ready) {
    try { S.overview = await get('overview'); $('#undoBtn').disabled = !S.overview.undo.length; $('#undoBtn').title = S.overview.undo.length ? `Vrátit: ${S.overview.undo[0]} (Ctrl+Z)` : 'Není co vracet'; } catch { /* shown by the view */ }
  }
  renderTabs(); renderStatusRight();
}
function renderStatusRight() {
  const o = S.overview;
  $('#statusRight').textContent = o ? `${o.project.files} souborů · ${fmtN(o.totals.done)} / ${fmtN(o.totals.total)} řádků · ${fmtPct(o.totals.percent)}` +
    (S.lastRefresh ? ` · obnoveno ${S.lastRefresh}` : '') : '';
}

/* ---------------------------------------------------------------- refresh / undo */
const isDirty = () => !!document.querySelector('.ed[data-dirty="1"]') || !!S.dlgDirty;
async function doRefresh(force = false) {
  if (!S.ready) return;
  const btn = $('#refreshBtn');
  btn.disabled = true; btn.replaceChildren(h('span', { class: 'spin' }), ' Obnovuji…');
  status('Obnovuji soubory…');
  try {
    let r = await post('refresh', { force, dirty: isDirty() });
    if (r.needs_confirm) {
      if (!(await confirmDialog('Neuložené změny', r.message, 'Obnovit přesto'))) { status('Obnovení zrušeno.'); return; }
      r = await post('refresh', { force, discard: true });
    }
    S.lastRefresh = new Date().toLocaleTimeString('cs-CZ');
    const msg = r.changed ? `Obnoveno – ${r.summary}` : 'Obnoveno – beze změn.';
    toast(msg + (r.moved_metadata ? ` Údaje ${r.moved_metadata} přejmenovaných souborů byly přeneseny.` : ''), r.errors.length ? 'bad' : 'ok');
    if (r.changed || r.errors.length) showRefreshReport(r);
    S.files = null; S.ent.items = [];
    await refreshHeader(); render();
  } catch (e) { fail(e); }
  finally { btn.disabled = false; btn.replaceChildren('⟳ Obnovit soubory'); }
}
function showRefreshReport(r) {
  const sec = (title, items) => items.length ? h('div', null, h('h4', null, `${title} (${items.length})`), h('ul', null, items.map((x) => h('li', { class: 'fname' }, typeof x === 'string' ? x : `${x.from}  →  ${x.to}`)))) : null;
  dialog({ title: 'Výsledek obnovení', body: h('div', null,
    sec('Přidané soubory', r.added), sec('Změněné soubory', r.modified), sec('Přejmenované soubory', r.renamed),
    sec('Odebrané soubory (údaje o nich zůstávají uložené)', r.removed),
    r.errors.length ? h('div', { class: 'notice bad' }, h('b', null, 'Problémy: '), r.errors.join(' | ')) : null,
    r.save_problems?.length ? h('div', { class: 'notice warn' }, r.save_problems.join(' | ')) : null),
    buttons: [{ label: 'Zavřít', kind: 'primary' }] });
}
async function doUndo() {
  if (!S.ready) return;
  try {
    const r = await post('undo');
    toast(`Vráceno: ${r.undone}`);
    S.files = null; S.ent.items = [];
    await refreshHeader(); render();
  } catch (e) { fail(e); }
}

/* ================================================================ OVERVIEW */
async function viewOverview() {
  const o = (S.overview = await get('overview'));
  renderStatusRight();
  const t = o.totals;
  const v = o.validation;
  const root = h('div');
  for (const n of S.notices) root.append(h('div', { class: 'notice' }, n));
  if (o.unsaved.length) root.append(h('div', { class: 'notice warn' }, `Nepodařilo se uložit: ${o.unsaved.join(', ')} (soubor je možná otevřený v Excelu). Zavři ho a klikni na Obnovit soubory.`));
  if (o.last_save_error) root.append(h('div', { class: 'notice warn' }, o.last_save_error));
  if (o.lock_lost) root.append(h('div', { class: 'notice warn' }, 'Projekt mezitím převzala jiná kopie aplikace. Neukládej tady další změny: zavři tuto kopii, nebo projekt otevři znovu (Změnit složku).'));
  root.append(h('div', { class: 'grid cards' },
    h('div', { class: 'panel stat' }, h('div', { class: 'label' }, 'Překlad'),
      h('div', { class: 'value' }, fmtPct(t.percent)), bar(t.percent),
      h('div', { class: 'sub' }, `${fmtN(t.done)} / ${fmtN(t.total)} řádků · z toho ručně schváleno ${fmtN(t.approved)}`)),
    h('div', { class: 'panel stat' }, h('div', { class: 'label' }, 'Zbývá přeložit'),
      h('div', { class: 'value' }, fmtN(t.remaining), h('small', null, 'řádků')),
      h('div', { class: 'sub' }, `${o.file_counts.none + o.file_counts.wip} z ${o.project.files} souborů nedokončeno`)),
    h('div', { class: 'panel stat' }, h('div', { class: 'label' }, 'Korektura'),
      h('div', { class: 'value' }, fmtPct(t.proofread_percent)), bar(t.proofread_percent, 'alt'),
      h('div', { class: 'sub' }, `${fmtN(t.proofread)} / ${fmtN(t.total)} řádků zkontrolováno`),
      h('div', { class: 'sub' }, `řádek po řádku označeno ${fmtN(t.proof_marked)}`, t.proof_fix ? [' · ', h('a', { href: '#', onclick: (ev) => { ev.preventDefault(); go('entries', { file: '', status: 'fix' }); } }, `k opravě ${fmtN(t.proof_fix)}`)] : null),
      t.proof_stale ? h('div', { class: 'sub' }, h('a', { href: '#', onclick: (ev) => { ev.preventDefault(); go('entries', { file: '', status: 'stale' }); } }, `↻ změněno po korektuře ${fmtN(t.proof_stale)}`), ' – překlad se po označení změnil') : null,
      h('div', { class: 'row', style: { marginTop: '8px' } },
        h('button', { class: 'btn small primary', onclick: () => go('entries', { file: '', status: 'review', select: true }) }, 'Pokračovat v korektuře'))),
    h('div', { class: 'panel stat', style: { cursor: 'pointer' }, onclick: () => go('validation') }, h('div', { class: 'label' }, 'Kontrola překladu'),
      h('div', { class: 'value' }, fmtN(v.error), h('small', null, v.error === 1 ? 'chyba' : 'chyb')),
      h('div', { class: 'sub' }, `${fmtN(v.warning)} varování (z toho ${fmtN(v.length)} k délce textu)`),
      v.ignored ? h('div', { class: 'sub' }, h('a', { href: '#', onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); go('validation', { ignored: 'only' }); } }, `ignorováno ${fmtN(v.ignored)}`)) : null)));
  if (o.goals) root.append(goalsPanel(o.goals));
  root.append(estimatePanel(o.estimate));

  const left = h('div'), right = h('div');
  for (const s of o.seasons) left.append(seasonPanel(s, o.episodes));
  const ug = (label, g) => g.translation.total ? h('li', null, h('span', null, label, h('span', { class: 'muted' }, ` · ${g.files} souborů`)), h('span', { class: 'num' }, `${fmtN(g.translation.done)} / ${fmtN(g.translation.total)} (${fmtPct(g.translation.percent)})`)) : null;
  left.append(h('div', { class: 'panel' }, h('h3', null, 'Mimo epizody'),
    h('ul', { class: 'list' }, ug('Obecné (celá hra)', o.general), ug('Nezařazené soubory', o.unassigned),
      !o.general.translation.total && !o.unassigned.translation.total ? h('li', { class: 'muted' }, 'Všechny soubory jsou zařazené k epizodám.') : null),
    h('div', { class: 'panel-body muted' }, 'Celkový překlad výše zahrnuje i tyto soubory. Procenta epizod a sezón počítají jen soubory zařazené k epizodě.')));

  if (o.worst_files?.length) right.append(h('div', { class: 'panel', style: { marginBottom: '12px' } }, h('h3', null, 'Nejproblémovější soubory'),
    h('ul', { class: 'list' }, o.worst_files.map((w) => h('li', null,
      h('a', { href: '#', title: `${w.errors} chyb, ${w.warnings} varování na ${fmtN(w.lines)} řádků`, onclick: (ev) => { ev.preventDefault(); go('validation', { file: w.name }); } }, w.name.split(/[\\/]/).pop()),
      h('span', { class: 'num' }, `${w.errors ? w.errors + ' ch · ' : ''}${w.warnings} var · ${String(w.score).replace('.', ',')} / 100 řádků`)))),
    h('div', { class: 'panel-body muted' }, 'Řazeno podle počtu problémů na 100 řádků (chyba se počítá třikrát). Klik otevře Kontrolu souboru.')));
  right.append(h('div', { class: 'panel', style: { marginBottom: '12px' } }, h('h3', null, 'Soubory podle stavu'),
    h('ul', { class: 'list' }, ['done', 'rev', 'tr', 'wip', 'none'].map((k) => h('li', null, chip(k, STATUS_LABEL[k]), h('b', { class: 'num' }, o.file_counts[k]))))));
  right.append(h('div', { class: 'panel', style: { marginBottom: '12px' } }, h('h3', null, 'Poslední aktivita'),
    o.recent.length ? h('ul', { class: 'list' }, o.recent.map((r) => h('li', null, h('span', { class: 'muted' }, r.at),
      h('span', { class: 'num' }, `${r.translated >= 0 ? '+' : ''}${fmtN(r.translated)} přeloženo` + (r.proofread ? ` · ${r.proofread >= 0 ? '+' : ''}${fmtN(r.proofread)} korektura` : '')))))
      : empty('Zatím žádná aktivita', 'Záznamy se objeví, jakmile se počty změní.')));
  right.append(h('div', { class: 'panel', style: { marginBottom: '12px' } }, h('h3', null, 'Poslední změny (lze vrátit)'),
    o.undo.length ? h('ul', { class: 'list' }, o.undo.map((u, i) => h('li', null, u, i === 0 ? h('span', { class: 'muted' }, 'Ctrl+Z') : null))) : empty('Nic k vrácení', '')));
  if (o.last_refresh) {
    const r = o.last_refresh;
    right.append(h('div', { class: 'panel' }, h('h3', null, 'Poslední načtení souborů'),
      h('div', { class: 'panel-body' }, h('dl', { class: 'kv' },
        h('dt', null, 'Souborů'), h('dd', null, o.project.files), h('dt', null, 'Trvalo'), h('dd', null, r.seconds + ' s'),
        h('dt', null, 'Přeskočené soubory'), h('dd', null, o.project.skipped.join(', ') || '—')))));
  }
  root.append(h('div', { class: 'two-col' }, left, right));
  return root;
}
/* This week's goal for translating and proofreading. Automatic goals come from the recent weekly pace (+10 %); a goal set in Nastavení wins. */
function goalsPanel(g) {
  const row = (label, p, cls) => {
    if (!p.goal) return h('div', { class: 'goalrow' }, h('b', null, label), h('span', { class: 'muted' }, `tento týden ${fmtN(p.done)} ${plural(p.done, 'řádek', 'řádky', 'řádků')} · cíl zatím nejde odvodit z tempa (málo historie) – nastav ho v Nastavení`));
    const msg = { met: ['Splněno', 'done'], on_track: ['Jdeš podle plánu', 'tr'], behind: [`Zbývá ${fmtN(p.left)}, to je asi ${fmtN(p.needed_per_day)} za den`, 'warning'] }[p.status];
    return h('div', { class: 'goalrow' }, h('b', null, label), bar(p.percent, cls),
      h('span', { class: 'num' }, `${fmtN(p.done)} / ${fmtN(p.goal)}`), chip(msg[1], msg[0]),
      h('span', { class: 'muted' }, p.auto ? `cíl automaticky z tvého tempa${p.pace_per_week ? ` (≈ ${fmtN(p.pace_per_week)} / týden)` : ''}` : 'cíl nastavený ručně'));
  };
  return h('div', { class: 'panel', style: { marginBottom: '12px' } }, h('div', { class: 'panel-body' },
    h('div', { class: 'row', style: { justifyContent: 'space-between', marginBottom: '8px' } }, h('b', null, 'Cíl na tento týden'), h('span', { class: 'muted' }, `od pondělí ${dateCz(g.week_start)} · cíle jde změnit v `, h('a', { href: '#', onclick: (ev) => { ev.preventDefault(); go('settings'); } }, 'Nastavení'))),
    row('Překlad', g.translate), row('Korektura', g.proofread, 'alt')));
}
function estimatePanel(e) {
  let body;
  if (e.status === 'ok') {
    const range = e.eta_early && e.eta_late ? ` (rozmezí ${dateCz(e.eta_early)} – ${dateCz(e.eta_late)})` : '';
    body = h('div', null, h('b', null, 'Odhad dokončení překladu: ', dateCz(e.eta)), h('span', { class: 'muted' }, range),
      h('div', { class: 'muted' }, `${e.reason} Spolehlivost: ${{ low: 'nízká', medium: 'střední', high: 'vysoká' }[e.confidence] || '—'}. Zbývá ${fmtN(e.remaining)} řádků.`));
  } else if (e.status === 'complete') body = h('b', null, 'Vše je přeloženo.');
  else body = h('div', null, h('b', null, 'Odhad dokončení zatím nelze spočítat. '), h('span', { class: 'muted' }, e.reason));
  return h('div', { class: 'panel', style: { marginBottom: '12px' } }, h('div', { class: 'panel-body' }, body));
}
function seasonPanel(s, episodes) {
  if (s.status === 'planned') {
    return h('div', { class: 'panel season planned' }, h('div', { class: 'season-head' }, h('h3', null, `Sezóna ${s.n}`), chip('planned', 'Plánováno'), h('span', { class: 'grow' })),
      h('div', { class: 'panel-body muted' }, 'Sezóna je plánovaná do budoucna a zatím se nepřekládá. Nezapočítává se do žádných procent ani do odhadu dokončení.'));
  }
  const eps = episodes.filter((e) => e.season === s.n);
  const head = h('div', { class: 'season-head' }, h('h3', null, `Sezóna ${s.n}`), h('span', { class: 'muted' }, `epizody ${s.episodes[0]}–${s.episodes.at(-1)}`),
    h('span', { class: 'grow' }),
    h('div', { class: 'season-stats' },
      h('div', { class: 'st' }, h('span', { class: 'lbl' }, 'Překlad'), h('b', null, fmtPct(s.translation.percent)), h('div', { class: 'muted num' }, `${fmtN(s.translation.done)} / ${fmtN(s.translation.total)}`)),
      h('div', { class: 'st pr' }, h('span', { class: 'lbl' }, 'Korektura'), h('b', null, fmtPct(s.proofreading.percent)), h('div', { class: 'muted num' }, `${fmtN(s.proofreading.done)} / ${fmtN(s.proofreading.total)}`))));
  const panel = h('div', { class: 'panel season' }, head,
    h('div', { class: 'seasonbars' }, bar(s.translation.percent), bar(s.proofreading.percent, 'alt')));
  for (const e of eps) {
    const sel = h('select', { class: 'sel', value: e.status, 'aria-label': `Stav epizody ${e.n}`, onchange: async () => {
      try { await post('episode', { ep: e.n, state: sel.value }); toast(`Epizoda ${e.n}: ${STATUS_LABEL[sel.value]}`); await refreshHeader(); } catch (err) { fail(err); }
    } }, ['none', 'wip', 'tr', 'proof', 'done'].map((k) => h('option', { value: k }, STATUS_LABEL[k])));
    sel.value = e.status;
    panel.append(h('div', { class: 'ep-row' }, h('span', { class: 'nm' }, `Epizoda ${e.n}`),
      e.translation.total ? h('div', { class: 'bars' }, bar(e.translation.percent), bar(e.proofreading.percent, 'alt')) : h('span', { class: 'muted' }, 'žádné zařazené soubory'),
      h('div', { class: 'pcts' }, h('span', null, 'Překlad ', h('b', null, fmtPct(e.translation.percent))), h('span', { class: 'pr' }, 'Korektura ', h('b', null, fmtPct(e.proofreading.percent)))),
      h('span', { class: 'meta' }, e.files ? `${fmtN(e.translation.done)} / ${fmtN(e.translation.total)} řádků · ${e.files} souborů (${e.files_done} hotových)` : 'bez souborů',
        e.eta_days ? h('div', { title: 'Podle tvého současného tempa (řádků za den)' }, `při tvém tempu ≈ ${fmtN(e.eta_days)} ${plural(e.eta_days, 'den', 'dny', 'dní')}`) : null),
      h('span', { class: 'sel' }, sel)));
  }
  return panel;
}

/* ================================================================ FILES */
const FL_COLS = [
  { k: 'pick', w: 38, label: '', resize: false }, { k: 'name', w: 430, label: 'Soubor', sortable: true },
  { k: 'assign', w: 140, label: 'Zařazení', sortable: true }, { k: 'tp', w: 250, label: 'Překlad', sortable: true },
  { k: 'cp', w: 230, label: 'Korektura', sortable: true }, { k: 'todo', w: 80, label: 'Zbývá', sortable: true },
  { k: 'order', w: 112, label: 'Stav', sortable: true }, { k: 'warn', w: 84, label: 'Kontrola', sortable: true },
];
const assignKey = (a) => (!a ? 1000 : a === 'gen' ? 900 : parseInt(a.slice(3), 10));
function fileView() {
  const f = pref('files', {});
  const q = (f.q || '').toLowerCase();
  let rows = S.files.filter((r) => (!q || r.name.toLowerCase().includes(q)) &&
    (f.assign === undefined || f.assign === '*' || f.assign === r.assign) &&
    ((f.filter || 'all') === 'all' || (f.filter === 'open' && r.todo > 0) || (f.filter === 'rev' && r.todo === 0 && r.corr < r.total) || (f.filter === 'done' && r.corr >= r.total)));
  const sk = f.sortk || 'name', dir = f.sortdir || 1;
  const val = { name: (r) => r.name.toLowerCase(), assign: (r) => assignKey(r.assign), tp: (r) => r.done / r.total, cp: (r) => r.corr / r.total,
    todo: (r) => r.todo, order: (r) => r.order, warn: (r) => r.errors * 1000 + r.warnings };
  rows = rows.slice().sort((a, b) => { const x = val[sk](a), y = val[sk](b); return (x < y ? -1 : x > y ? 1 : a.name.localeCompare(b.name, 'cs', { numeric: true })) * dir; });
  return rows;
}
async function viewFiles() {
  S.files = await get('files').then((r) => r.files);
  S.overview = S.overview || await get('overview');
  const f = pref('files', {});
  const root = h('div', { class: 'split cols', style: { '--detail-w': pref('files.detailw', 350) + 'px' } });
  const main = h('div', { class: 'pane' });
  const detail = h('div', { class: 'detail' });
  const counter = h('span', { class: 'muted' });
  const pickBtn = h('button', { class: 'btn', onclick: () => bulkAssignDialog([...S.fl.picked]) }, 'Zařadit vybrané…');
  const search = h('input', { type: 'search', class: 'search', id: 'search', placeholder: 'Hledat soubor… (Ctrl+F)', value: f.q || '',
    oninput: (e) => { setPref('files.q', e.target.value); draw(); } });
  const seg = h('div', { class: 'seg' }, [['all', 'Vše'], ['open', 'Nedokončené'], ['rev', 'K korektuře'], ['done', 'Hotové']].map(([k, l]) =>
    h('button', { class: (f.filter || 'all') === k ? 'on' : '', onclick: () => { setPref('files.filter', k); seg.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === event.currentTarget)); draw(); } }, l)));
  const asel = h('select', { title: 'Filtr podle zařazení', onchange: (e) => { setPref('files.assign', e.target.value); draw(); } },
    h('option', { value: '*' }, 'Zařazení: vše'), h('option', { value: '' }, 'Nepřiřazeno'), h('option', { value: 'gen' }, 'Obecné'),
    ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => h('option', { value: 'ep:' + n }, `Epizoda ${n}`)));
  asel.value = f.assign === undefined ? '*' : f.assign;
  main.append(h('div', { class: 'pane-head' }, h('div', { class: 'toolbar filterbar' }, search, filterGroup('Stav', seg), filterGroup('Zařazení', asel),
    h('button', { class: 'btn', onclick: () => bulkAssignDialog(null) }, 'Navrhnout zařazení…'), pickBtn, h('span', { class: 'spacer' }), counter)));
  const wrap = h('div', { class: 'pane-body' });
  main.append(wrap);
  root.append(main, makeSplitter(root, 'h', { key: 'files.detailw', def: 350, min: 260, maxFrac: 0.6 }), detail);

  function draw() {
    const rows = fileView();
    const sk = pref('files.sortk', 'name'), dir = pref('files.sortdir', 1);
    const cols = FL_COLS.map((c) => c.k === 'pick' ? { ...c, node: h('input', { type: 'checkbox', title: 'Vybrat všechny zobrazené', checked: rows.length && rows.every((r) => S.fl.picked.has(r.name)),
      onchange: (e) => { rows.forEach((r) => e.target.checked ? S.fl.picked.add(r.name) : S.fl.picked.delete(r.name)); draw(); } }) } : c);
    const t = buildTable({ key: 'files', cols, sort: { k: sk, dir }, onSort: (k) => { setPref('files.sortdir', k === sk ? -dir : 1); setPref('files.sortk', k); draw(); } });
    const tw = h('div', { class: 'tablewrap' }, t.table);
    if (!rows.length) tw.append(empty('Žádné soubory', 'Změň filtr nebo hledaný text.'));
    let d = 0, tot = 0, c = 0, rem = 0;
    rows.forEach((r, idx) => {
      d += r.done; tot += r.total; c += r.corr; rem += r.todo;
      const picked = S.fl.picked.has(r.name);
      const tr = h('tr', { class: (S.fl.sel === r.name ? 'sel ' : '') + (picked ? 'picked' : ''), onclick: () => { S.fl.sel = r.name; draw(); drawDetail(); } },
        h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: picked, 'aria-label': 'Vybrat ' + r.name, onclick: (e) => {
          e.stopPropagation();
          if (e.shiftKey && S.fl.lastPick !== null) { const [a, b] = [S.fl.lastPick, idx].sort((x, y) => x - y); rows.slice(a, b + 1).forEach((x) => S.fl.picked.add(x.name)); }
          else if (e.target.checked) S.fl.picked.add(r.name); else S.fl.picked.delete(r.name);
          S.fl.lastPick = idx; draw();
        } })),
        h('td', null, fname(r.name, { link: true, onclick: (e) => { if (e.detail === 2) go('entries', { file: r.name }); } }), r.proof_stale ? chip('info', `↻ ${r.proof_stale}`) : null),
        h('td', null, h('select', { class: 'asg', value: r.assign, onclick: (e) => e.stopPropagation(), onchange: async (e) => {
          try { await post('assign', { name: r.name, v: e.target.value }); r.assign = e.target.value; toast(`Zařazení: ${r.name.split(/[\\/]/).pop()} → ${e.target.selectedOptions[0].text}`); refreshHeader(); draw(); drawDetail(); } catch (err) { fail(err); e.target.value = r.assign; }
        } }, h('option', { value: '' }, 'Nepřiřazeno'), h('option', { value: 'gen' }, 'Obecné'), [1, 2, 3, 4, 5, 6, 7, 8].map((n) => h('option', { value: 'ep:' + n }, `Epizoda ${n}`)))),
        h('td', null, numCell(r, 't')), h('td', null, numCell(r, 'c')),
        h('td', { class: 'num' }, fmtN(r.todo)), h('td', null, chip(r.status, STATUS_LABEL[r.status])),
        h('td', null, r.errors ? h('span', { class: 'badge', title: 'Chyby' }, r.errors) : null, ' ', r.warnings ? h('span', { class: 'badge warn', title: 'Varování' }, r.warnings) : null));
      t.tbody.append(tr);
    });
    t.tfoot.append(h('tr', null, h('td'), h('td', null, `Celkem (zobrazeno ${rows.length})`), h('td'),
      h('td', { class: 'num' }, `${fmtN(d)} / ${fmtN(tot)}  (${fmtPct(tot ? d / tot * 100 : 0)})`), h('td', { class: 'num' }, `${fmtN(c)} (${fmtPct(tot ? c / tot * 100 : 0)})`), h('td', { class: 'num' }, fmtN(rem)), h('td'), h('td')));
    const keep = wrap.scrollTop;
    wrap.replaceChildren(tw); wrap.scrollTop = keep;
    counter.textContent = `Zobrazeno ${rows.length} z ${S.files.length} souborů`;
    pickBtn.disabled = !S.fl.picked.size;
    pickBtn.textContent = S.fl.picked.size ? `Zařadit vybrané (${S.fl.picked.size})…` : 'Zařadit vybrané…';
  }
  function numCell(r, which) {
    const isT = which === 't';
    const val = isT ? r.done : r.corr;
    const inp = h('input', { type: 'text', class: 'ed' + (isT && r.done !== r.auto ? ' ov' : ''), value: String(val), inputmode: 'numeric',
      title: isT ? `Ručně přepsat počet přeložených řádků (automaticky: ${r.auto}). Číslo, % nebo „ano“.` : 'Počet zkontrolovaných řádků (číslo, % nebo „ano“)',
      onclick: (e) => e.stopPropagation(), onfocus: (e) => e.target.select(),
      oninput: (e) => { e.target.dataset.dirty = '1'; },
      onkeydown: (e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') { e.target.value = String(val); delete e.target.dataset.dirty; e.target.blur(); } },
      onchange: async (e) => {
        delete e.target.dataset.dirty;
        const c = isT ? String(r.corr) : e.target.value, t = isT ? e.target.value.trim() : (r.done !== r.auto ? String(r.done) : '');
        try { await post('file/save', { name: r.name, c, t: isT && e.target.value.trim() === '' ? '' : t }); toast('Uloženo ✓'); await reloadFiles(); } catch (err) { fail(err); }
      } });
    const pct = r.total ? (val / r.total) * 100 : 0;
    return h('div', { class: 'cell-num' }, inp, bar(pct, isT ? '' : 'alt'), h('span', { class: 'pct' }, pct.toFixed(1).replace('.', ',') + ' %'),
      h('span', { class: 'ico-slot' },
        isT && r.done !== r.auto ? h('button', { class: 'ico', title: `Vrátit automatickou hodnotu (${r.auto})`, onclick: async (e) => { e.stopPropagation(); try { await post('file/save', { name: r.name, c: String(r.corr), t: '' }); await reloadFiles(); } catch (err) { fail(err); } } }, '↺') : null,
        !isT && r.corr < r.total ? h('button', { class: 'ico', title: 'Označit celý soubor jako zkontrolovaný', onclick: async (e) => { e.stopPropagation(); try { await post('file/save', { name: r.name, c: 'ano', t: r.done !== r.auto ? String(r.done) : '' }); await reloadFiles(); } catch (err) { fail(err); } } }, '✓') : null));
  }
  async function reloadFiles() { S.files = (await get('files')).files; await refreshHeader(); draw(); drawDetail(); }
  function drawDetail() {
    const r = S.files.find((x) => x.name === S.fl.sel);
    if (!r) return detail.replaceChildren(h('h4', null, 'Detail souboru'), h('p', { class: 'muted' }, 'Vyber soubor v tabulce. Dvojklik otevře jeho řádky.'));
    const total = r.total;
    detail.replaceChildren(h('h4', null, 'Soubor'), h('div', { class: 'path' }, r.name),
      h('div', { class: 'actions' },
        h('button', { class: 'btn small primary', onclick: () => go('entries', { file: r.name }) }, 'Zobrazit řádky'),
        h('button', { class: 'btn small', onclick: () => go('entries', { file: r.name, status: 'todo' }) }, 'Jen nepřeložené'),
        r.proof_stale ? h('button', { class: 'btn small', title: 'Řádky, které se po korektuře změnily', onclick: () => go('entries', { file: r.name, status: 'stale' }) }, `Změněno po korektuře (${r.proof_stale})`) : null,
        h('button', { class: 'btn small primary', onclick: () => go('entries', { file: r.name, status: 'review', select: true }) }, 'Pokračovat v korektuře'),
        h('button', { class: 'btn small', onclick: () => openEditor(r.name, 1) }, 'Otevřít v editoru'),
        h('button', { class: 'btn small', onclick: () => copy(r.name) }, 'Kopírovat cestu')),
      h('dl', { class: 'kv' },
        h('dt', null, 'Zařazení'), h('dd', null, r.assign === '' ? 'Nepřiřazeno' : r.assign === 'gen' ? 'Obecné' : 'Epizoda ' + r.assign.slice(3)),
        h('dt', null, 'Řádků celkem'), h('dd', null, fmtN(total)),
        h('dt', null, 'Přeloženo'), h('dd', null, `${fmtN(r.done)} (${fmtPct(total ? r.done / total * 100 : 0)})`),
        h('dt', null, 'z toho ručně schváleno'), h('dd', null, fmtN(r.approved)),
        h('dt', null, 'Automaticky napočteno'), h('dd', null, fmtN(r.auto)),
        h('dt', null, 'Zbývá'), h('dd', null, fmtN(r.todo)),
        h('dt', null, 'Zkontrolováno'), h('dd', null, `${fmtN(r.corr)} (${fmtPct(total ? r.corr / total * 100 : 0)})`),
        h('dt', null, 'z toho řádek po řádku'), h('dd', null, fmtN(r.proof_marked)),
        h('dt', null, 'K opravě'), h('dd', null, r.proof_fix ? h('button', { class: 'btn small', onclick: () => go('entries', { file: r.name, status: 'fix' }) }, fmtN(r.proof_fix)) : '0'),
        h('dt', null, 'Chyby / varování'), h('dd', null, `${r.errors} / ${r.warnings}`)),
      r.errors + r.warnings ? h('div', { class: 'actions' }, h('button', { class: 'btn small', onclick: () => go('validation', { file: r.name }) }, 'Zobrazit problémy')) : null);
  }
  root.afterMount = () => {
    if (S.goOpts?.file) { S.fl.sel = S.goOpts.file; }
    draw(); drawDetail();
  };
  return root;
}
async function bulkAssignDialog(names) {
  let data;
  try { data = await post('assign/suggest', { names: names || [] }); } catch (e) { return fail(e); }
  const items = names ? data.items : data.items.filter((i) => !i.current || i.state !== 'keep');
  if (!items.length) return toast('Nemám co navrhnout.', 'bad');
  const rows = items.map((i) => ({ ...i, value: i.suggested || i.current || '', apply: i.state === 'new' || i.state === 'same' ? i.state === 'new' : false, overwrite: false }));
  S.dlgDirty = true;
  const STATE = { new: ['Nové', 'tr'], same: ['Beze změny', 'none'], conflict: ['Konflikt', 'error'], ambiguous: ['Nejednoznačné', 'warning'], unknown: ['Neznámé', 'none'], keep: ['Ponecháno', 'none'] };
  const CONF = { high: 'vysoká', medium: 'střední', low: 'nízká', none: '—' };
  const summary = h('span');
  const upd = () => { const n = rows.filter((r) => r.apply && r.value !== r.current).length; summary.textContent = `K zapsání: ${n} souborů`; applyBtn.disabled = !n; };
  const filterSel = h('select', { onchange: () => paint() }, h('option', { value: 'all' }, 'Zobrazit vše'), h('option', { value: 'change' }, 'Jen změny'), h('option', { value: 'problem' }, 'Jen konflikty a nejasné'));
  const tbody = h('tbody');
  const table = h('table', { class: 'data' }, h('colgroup', null, [40, 400, 130, 190, 90, 120, 330].map((w) => h('col', { style: { width: w + 'px' } }))),
    h('thead', null, h('tr', null, ['', 'Soubor', 'Dosud', 'Navržené zařazení', 'Jistota', 'Stav', 'Důvod'].map((t, i) => h('th', { class: i === 0 ? 'center' : '' }, t)))), tbody);
  table.style.width = '1300px';
  function paint() {
    tbody.replaceChildren();
    for (const r of rows) {
      const kind = filterSel.value;
      if ((kind === 'change' && r.value === r.current) || (kind === 'problem' && !['conflict', 'ambiguous', 'unknown'].includes(r.state))) continue;
      const needsOw = r.current && r.value !== r.current;
      tbody.append(h('tr', null,
        h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: r.apply, title: needsOw ? 'Přepíše ručně nastavené zařazení – zaškrtnutím potvrzuješ přepsání' : 'Použít', onchange: (e) => { r.apply = e.target.checked; r.overwrite = e.target.checked && !!needsOw; upd(); } })),
        h('td', null, fname(r.name)), h('td', null, r.current ? optLabel(data.options, r.current) : h('span', { class: 'muted' }, 'nepřiřazeno')),
        h('td', null, h('select', { value: r.value, onchange: (e) => { r.value = e.target.value; r.apply = r.value !== r.current; r.overwrite = !!(r.current && r.apply); paint(); upd(); } },
          data.options.map((o) => h('option', { value: o.value }, o.label)))),
        h('td', null, CONF[r.confidence]), h('td', null, chip(STATE[r.state][1], STATE[r.state][0]), needsOw ? h('div', { class: 'sugg-state muted' }, 'přepíše ruční hodnotu') : null),
        h('td', null, h('span', { class: 'reason' }, r.reason))));
    }
  }
  const applyBtn = h('button', { class: 'btn primary', onclick: async () => {
    const send = rows.filter((r) => r.apply && r.value !== r.current).map((r) => ({ name: r.name, value: r.value, overwrite: r.overwrite }));
    try {
      const res = await post('assign/apply', { items: send });
      toast(`Zařazeno ${res.applied.length} souborů` + (res.skipped.length ? `, přeskočeno ${res.skipped.length}` : '') + '. Zpět: Ctrl+Z', res.skipped.length ? 'bad' : 'ok');
      S.files = null; S.fl.picked.clear(); await refreshHeader(); render(); closeFn();
    } catch (e) { fail(e); }
  } }, 'Zapsat zařazení');
  let closeFn = () => {};
  paint(); upd();
  closeFn = dialog({ title: names ? `Zařazení ${rows.length} vybraných souborů` : 'Navržené zařazení souborů k epizodám',
    body: h('div', null, h('p', { class: 'muted' }, 'Návrh vychází z názvů souborů a složek (epN, updateN, složka seasonN) a ze zařazení ostatních souborů ve stejné složce. Nic se nezapíše, dokud nepotvrdíš. Ručně nastavené zařazení se přepíše jen u řádků, které sám zaškrtneš.'),
      h('div', { class: 'toolbar' }, filterSel, summary), h('div', { class: 'tablewrap', style: { maxHeight: '55vh' } }, table)),
    buttons: [{ label: 'Zrušit' }, { node: applyBtn }] });
}
const optLabel = (opts, v) => (opts.find((o) => o.value === v) || { label: v }).label;
async function openEditor(file, line) {
  try { const r = await post('open-editor', { file, line }); toast(r.message, r.ok ? 'ok' : 'bad', 7000); } catch (e) { fail(e); }
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast('Zkopírováno.'); } catch { toast('Kopírování se nepodařilo.', 'bad'); }
}

/* ================================================================ ENTRIES */
const EN_COLS = [
  { k: 'file', w: 360, label: 'Soubor' }, { k: 'line', w: 66, label: 'Řádek', sortable: true, title: 'Řádek v překladovém souboru' },
  { k: 'ref', w: 150, label: 'Skript', title: 'Původní řádek ve skriptu hry (game/…:číslo), jak ho zapsal Ren\'Py' },
  { k: 'type', w: 84, label: 'Typ', title: 'Dialog, nebo Volba (text z „translate strings“ – většinou volba v menu nebo text rozhraní)' },
  { k: 'status', w: 120, label: 'Stav' }, { k: 'proof', w: 150, label: 'Korektura' },
  { k: 'who', w: 90, label: 'Kód', title: 'Zkratka mluvčího (a atributy obrázku)' }, { k: 'whoname', w: 170, label: 'Jméno', title: 'Celé jméno ze Slovníku' }, { k: 'source', w: 420, label: 'Originál' }, { k: 'target', w: 420, label: 'Překlad' }, { k: 'issues', w: 90, label: 'Kontrola', sortable: true },
];
function entQuery(extra = {}) {
  const e = pref('entries', {});
  return { file: e.file || '', status: e.status || 'todo', unit: e.unit || '', kind: e.kind || '', issues: e.issues || '', q: e.q || '', sort: e.sort || 'line', limit: 200, ...extra };
}
async function viewEntries() {
  if (S.goOpts) {
    const o = S.goOpts;
    if (o.file !== undefined) setPref('entries.file', o.file);
    setPref('entries.status', o.status || 'all');
    if (o.q !== undefined) setPref('entries.q', o.q);
    setPref('entries.kind', ''); setPref('entries.issues', '');
    S.ent.pendingLine = o.line || 0;
    S.ent.autoSelect = !!o.select;
    S.goOpts = null;
  }
  const files = S.files || (S.files = (await get('files')).files);
  const e = pref('entries', {});
  const root = h('div', { class: 'split rows', style: { '--detail-h': pref('entries.detailh', 380) + 'px' } });
  const main = h('div', { class: 'pane' });
  const detail = h('div', { class: 'detail', id: 'entryDetail' });
  const counter = h('span', { class: 'muted' });
  const search = h('input', { type: 'search', class: 'search', id: 'search', placeholder: 'Hledat v textu… (Ctrl+F)', value: e.q || '',
    oninput: (ev) => { setPref('entries.q', ev.target.value); debounceLoad(); } });
  const sel = (key, def, opts, title) => h('select', { title, value: e[key] || def, onchange: (ev) => { setPref('entries.' + key, ev.target.value); load(true); } }, opts.map(([v, l]) => h('option', { value: v }, l)));
  const fileSel = h('select', { title: 'Soubor', onchange: (ev) => { setPref('entries.file', ev.target.value); load(true); } }, h('option', { value: '' }, 'Všechny soubory'), files.map((f) => h('option', { value: f.name }, f.name)));
  fileSel.value = e.file || '';
  fileSel.style.maxWidth = '340px';
  const STATUS_OPTS = [['all', 'Vše'], ['todo', 'K přeložení'], ['translated', 'Přeložené'], ['approved', 'Schválené'], ['review', 'Ke korektuře'], ['fix', 'K opravě'], ['stale', 'Změněno po korektuře'], ['proofed', 'Zkontrolované']];
  const OPTS = {
    unit: [['', 'Dialogy i volby'], ['dialogue', 'Jen dialogy'], ['string', 'Jen volby (strings)']],
    kind: [['', 'Všechny druhy'], ['english', 'Anglicky'], ['same', 'Shodné, možná OK'], ['symbols', 'Jen znaky'], ['empty', 'Prázdné']],
    issues: [['', 'Vše'], ['any', 'S problémem'], ['error', 'S chybou'], ['warning', 'S varováním']],
    sort: [['line', 'Řádek'], ['file', 'Soubor'], ['kind', 'Druh'], ['issues', 'Problémy']],
  };
  const FILTER_NAMES = { unit: 'Typ', kind: 'Druh', issues: 'Kontrola' };
  const selects = {
    unit: sel('unit', '', OPTS.unit, 'Typ řádku'), kind: sel('kind', '', OPTS.kind, 'Druh nepřeloženého řádku'),
    issues: sel('issues', '', OPTS.issues, 'Filtr podle kontroly'), sort: sel('sort', 'line', OPTS.sort, 'Řazení'),
  };
  const moreBox = h('div', { class: 'frow fmore' }, filterGroup('Typ řádku', selects.unit), filterGroup('Druh nepřeloženého', selects.kind), filterGroup('Kontrola', selects.issues),
    filterGroup('Řadit podle', selects.sort), filterGroup('Mluvčí', speakerModeSelect(() => render())));
  const pillsBox = h('div', { class: 'frow pills', role: 'group', 'aria-label': 'Stav řádků' }), chipsBox = h('div', { class: 'frow fchips' });
  const extraCount = () => ['unit', 'kind', 'issues'].filter((k) => pref('entries.' + k, '')).length;
  const moreOpen = () => { const v = pref('entries.more', null); return v === null ? extraCount() > 0 : !!v; };
  const moreBtn = h('button', { class: 'btn small', title: 'Typ řádku, druh, kontrola, řazení, zobrazení mluvčích', onclick: () => { setPref('entries.more', !moreOpen()); paintFilters(); } });
  function resetFilters() {
    for (const k of ['file', 'unit', 'kind', 'issues', 'q']) setPref('entries.' + k, '');
    setPref('entries.status', 'all');
    search.value = ''; fileSel.value = ''; selects.unit.value = ''; selects.kind.value = ''; selects.issues.value = '';
    load(true);
  }
  function paintFilters() {
    const st = pref('entries.status', 'todo');
    pillsBox.replaceChildren(...pillRow(STATUS_OPTS, st, S.ent.counts, (k) => { setPref('entries.status', k); load(true); }));
    const active = [];
    const lab = (list, v) => (list.find(([k]) => k === v) || [v, v])[1];
    const file = pref('entries.file', '');
    if (file) active.push(['Soubor: ' + file.split(/[\\/]/).pop(), () => { setPref('entries.file', ''); fileSel.value = ''; load(true); }]);
    if (st !== 'all') active.push(['Stav: ' + lab(STATUS_OPTS, st), () => { setPref('entries.status', 'all'); load(true); }]);
    for (const k of ['unit', 'kind', 'issues']) if (pref('entries.' + k, '')) active.push([`${FILTER_NAMES[k]}: ${lab(OPTS[k], pref('entries.' + k, ''))}`, () => { setPref('entries.' + k, ''); selects[k].value = ''; load(true); }]);
    if (pref('entries.q', '')) active.push([`Hledání: „${pref('entries.q', '')}“`, () => { setPref('entries.q', ''); search.value = ''; load(true); }]);
    chipsBox.replaceChildren(...activeChips(active, resetFilters));
    const open = moreOpen();
    moreBtn.textContent = `${open ? '▾' : '▸'} Další filtry${extraCount() ? ` (${extraCount()})` : ''}`;
    moreBox.style.display = open ? '' : 'none';
  }
  main.append(h('div', { class: 'pane-head' }, h('div', { class: 'filterbar' },
    h('div', { class: 'frow' }, search, filterGroup('Soubor', fileSel), moreBtn,
      h('button', { class: 'btn small', title: 'Hledat a nahrazovat v přeloženém textu (celý projekt nebo vybrané soubory)', onclick: () => replaceDialog(async () => { S.files = null; await refreshHeader(); load(true); }, S.fl.picked.size ? [...S.fl.picked] : (pref('entries.file', '') ? [pref('entries.file', '')] : [])) }, 'Najít a nahradit…'),
      h('button', { class: 'btn small', title: 'Hromadně schválí řádky, které se překládat nemusí (jen znaky, citoslovce, jména)', onclick: () => ruleApproveDialog(async () => { S.files = null; await refreshHeader(); load(true); }, S.fl.picked.size ? [...S.fl.picked] : (pref('entries.file', '') ? [pref('entries.file', '')] : [])) }, 'Schválit podle pravidla…'),
      h('span', { class: 'spacer' }), counter),
    pillsBox, moreBox, chipsBox)));
  paintFilters();
  const wrap = h('div', { class: 'pane-body' });
  main.append(wrap);
  root.append(main, makeSplitter(root, 'v', { key: 'entries.detailh', def: 380, min: 140, maxFrac: 0.7 }), detail);
  let timer;
  const debounceLoad = () => { clearTimeout(timer); timer = setTimeout(() => load(true), 250); };
  let tbody;

  function skeleton() {
    const showFile = !pref('entries.file', '');
    const mode = speakerMode();
    const cols = EN_COLS.filter((c) => (showFile || c.k !== 'file') && !(c.k === 'who' && mode === 'name') && !(c.k === 'whoname' && mode === 'code'));
    const t = buildTable({ key: 'entries' + (showFile ? '' : '1'), cols, className: 'entries' });
    tbody = t.tbody;
    const more = h('div', { class: 'more' });
    wrap.replaceChildren(h('div', { class: 'tablewrap' }, t.table), more);
    S.ent.more = more; S.ent.showFile = showFile;
  }
  function rowFor(it, i) {
    const hasErr = it.issues.some((x) => x.severity === 'error');
    const sev = hasErr ? 'error' : it.issues.length ? 'warning' : '';
    return h('tr', { class: `status-${it.status} ${hasErr ? 'has-error' : ''} ${S.ent.sel === i ? 'sel' : ''}`, dataset: { i }, onclick: () => select(i), ondblclick: () => openEditor(it.file, it.line) },
      S.ent.showFile ? h('td', null, fname(it.file)) : null,
      h('td', { class: 'num' }, it.line), h('td', { class: 'mono muted', style: { fontSize: '12px' } }, it.ref ? it.ref.replace(/^game\//, '') : '–'),
      h('td', null, it.unit === 'string' ? h('span', { class: 'chip choice', title: 'Text z „translate strings“ – většinou volba v menu nebo text rozhraní' }, 'Volba') : h('span', { class: 'muted' }, 'Dialog')),
      h('td', null, chip(it.status, ENTRY_LABEL[it.status]), it.kind && it.status !== 'translated' ? h('div', { class: 'muted', style: { fontSize: '11.5px' } }, KIND_LABEL[it.kind]) : null),
      h('td', null, it.status === 'todo' ? h('span', { class: 'muted' }, '–') : (proofChip(it.proof) || h('span', { class: 'muted' }, 'nezkontrolováno'))),
      speakerMode() !== 'name' ? h('td', { class: 'who' }, it.who) : null,
      speakerMode() !== 'code' ? h('td', { class: 'whoname' }, speakerName(it.who) || h('span', { class: 'muted' }, it.who ? '–' : '')) : null,
      h('td', { class: 'txt entry-source' }, fmtText(it.source ?? '')), h('td', { class: 'txt entry-target' }, fmtText(it.target)),
      h('td', null, sev ? chip(sev, `${it.issues.length}×`) : null));
  }
  async function load(reset) {
    if (S.ent.loading) return;
    S.ent.loading = true;
    try {
      if (reset) { S.ent.items = []; S.ent.sel = -1; S.ent.start = 0; skeleton(); tbody.replaceChildren(); S.ent.more.replaceChildren(loading()); }
      const around = reset && S.ent.pendingLine ? S.ent.pendingLine : 0;
      const q = entQuery(reset ? { offset: 0, around } : { offset: S.ent.start + S.ent.items.length });
      if (around) q.status = 'all';
      const r = await get('entries', q);
      if (reset) S.ent.start = r.offset;
      const base = S.ent.items.length;
      S.ent.items.push(...r.items);
      S.ent.total = r.total; S.ent.counts = r.counts; paintFilters();
      r.items.forEach((it, k) => tbody.append(rowFor(it, base + k)));
      counter.textContent = `${fmtN(r.total)} ${plural(r.total, 'řádek', 'řádky', 'řádků')}`;
      const shown = S.ent.start + S.ent.items.length;
      S.ent.more.replaceChildren(shown < r.total ? h('button', { class: 'btn', onclick: () => load(false) }, `Načíst dalších ${Math.min(200, r.total - shown)} (zobrazeno ${fmtN(shown)} z ${fmtN(r.total)})`) : null);
      if (!r.total) S.ent.more.replaceChildren(empty('Nic nenalezeno', pref('entries.status', 'todo') === 'todo' ? 'Tady už není nic k přeložení – nebo změň filtry.' : 'Zkus změnit filtry nebo hledaný text.'));
      if (reset && around) { const i = S.ent.items.findIndex((x) => x.line === around); S.ent.pendingLine = 0; if (i >= 0) select(i); }
      else if (reset && S.ent.items.length) { if (S.ent.autoSelect) { S.ent.autoSelect = false; select(0); } else drawDetail(null); }
      else if (reset) drawDetail(null);
    } catch (err) { fail(err); S.ent.more?.replaceChildren(h('div', { class: 'notice bad' }, err.message)); }
    finally { S.ent.loading = false; }
  }
  async function select(i) {
    if (i < 0 || i >= S.ent.items.length) return;
    const open = $('#editTarget');
    if (open?.dataset.dirty === '1' && !(await confirmDialog('Neuložený překlad', 'Text tohoto řádku jsi změnil a neuložil. Zahodit změny?', 'Zahodit změny'))) return;
    tbody.querySelector('tr.sel')?.classList.remove('sel');
    S.ent.sel = i;
    const tr = tbody.children[i];
    tr?.classList.add('sel');
    tr?.scrollIntoView({ block: 'nearest' });
    const it = S.ent.items[i];
    try { S.ent.detail = await get('entry', { file: it.file, line: it.line }); } catch (err) { S.ent.detail = null; drawDetail(null, err.message); return; }
    if (S.ent.sel === i) drawDetail(S.ent.detail);
    if (i >= S.ent.items.length - 15 && S.ent.start + S.ent.items.length < S.ent.total) load(false);
  }
  function drawDetail(d, err) {
    if (!d) return detail.replaceChildren(h('h4', null, 'Detail řádku'), err ? h('div', { class: 'notice bad' }, err) : h('p', { class: 'muted' }, 'Vyber řádek. Šipky ↑ ↓ procházejí řádky, ', h('kbd', null, 'A'), ' schválí, ', h('kbd', null, 'E'), ' otevře editor, ', h('kbd', null, '?'), ' ukáže všechny zkratky.'));
    const canApprove = d.status !== 'translated' && d.kind !== 'empty';
    detail.replaceChildren(h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h4', null, 'Detail řádku'), chip(d.status, ENTRY_LABEL[d.status] + (d.kind_label && d.status !== 'translated' ? ` · ${d.kind_label}` : ''))),
      h('div', { class: 'path' }, `${d.file}:${d.line}`),
      h('div', { class: 'ctx' }, d.unit === 'string' ? chip('choice', 'Volba / řetězec') : chip('none', 'Dialog'), d.ref ? ['  původní skript: ', h('b', { class: 'mono' }, d.ref)] : null),
      h('div', { class: 'actions' },
        canApprove ? h('button', { class: 'btn small primary', onclick: () => toggleApprove() }, d.status === 'approved' ? 'Zrušit schválení (A)' : 'Schválit řádek (A)') : null,
        canApprove ? h('button', { class: 'btn small', onclick: () => globalApprove() }, 'Schválit všechny shodné… (Shift+A)') : null,
        h('button', { class: 'btn small', onclick: () => openEditor(d.file, d.line) }, 'Otevřít v editoru (E)'),
        h('button', { class: 'btn small ghost', onclick: () => copy(`${d.path}:${d.line}`) }, 'Kopírovat cestu')),
      h('div', { class: 'pair' },
        h('div', null, h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h4', { style: { margin: 0 } }, 'Originál'),
          h('span', { class: 'row' }, h('button', { class: 'btn small ghost', title: 'Zkopíruje text originálu do schránky', onclick: () => copy(d.source ?? '') }, '⧉ Originál'),
            h('button', { class: 'btn small ghost', title: 'Zkopíruje originál a překlad pod sebe', onclick: () => copy(`${d.source ?? ''}\n${$('#editTarget') ? $('#editTarget').value : d.target}`) }, '⧉ Oboje'))),
          h('div', { class: 'textbox', style: { marginTop: '6px' } }, fmtText(d.source ?? '(zdroj nenalezen)'))),
        translationEditor(d)),
      d.issues.length ? h('div', null, h('h4', null, 'Kontrola'), d.issues.map((x) => h('div', { class: 'issue ' + x.severity + (x.ignored ? ' ignored' : '') }, x.ignored ? chip('none', 'ignorováno') : chip(x.severity, SEV_LABEL[x.severity]), ' ', x.message,
        x.ignored ? h('span', { class: 'muted' }, x.ignore_note ? ` – ${x.ignore_note}` : '') : null,
        h('div', null, x.ignored ? h('button', { class: 'btn small ghost', onclick: () => unignore([{ file: d.file, line: d.line, code: x.code }], () => { S.ent.api.reload(); }) }, 'Přestat ignorovat')
          : h('button', { class: 'btn small ghost', title: 'Schová tenhle nález u tohoto řádku (jde vrátit)', onclick: () => ignoreDialog(d.issues.filter((y) => !y.ignored).map((y) => ({ file: d.file, line: d.line, code: y.code, severity: y.severity, message: y.message })).sort((a, b) => (a.code === x.code ? -1 : b.code === x.code ? 1 : 0)), () => { S.ent.api.reload(); }) }, 'Ignorovat…')),
        x.fixable ? h('div', null, h('button', { class: 'btn small primary', onclick: () => fixDialog({ items: [{ file: d.file, line: d.line }], kinds: [x.kind || 'speaker'] }, () => { load(true); }) }, x.kind === 'speaker' || !x.kind ? 'Opravit podle originálu' : 'Opravit…')) : null,
        x.ratio ? h('div', { class: 'muted' }, `Délka: originál ${x.source_len}, překlad ${x.target_len} znaků (poměr ${String(x.ratio).replace('.', ',')}). Rozhodni sám, jestli je to záměr.`) : null))) : null,
      d.status !== 'todo' ? h('div', { class: 'proofbox' },
        h('div', { class: 'row' }, h('h4', { style: { margin: 0 } }, 'Korektura'), proofChip(d.proof) || h('span', { class: 'muted' }, 'zatím nezkontrolováno'),
          d.proof_date && d.proof === 'ok' ? h('span', { class: 'muted' }, d.proof_date) : null),
        h('div', { class: 'actions' },
          h('button', { class: 'btn small ' + (d.proof === 'ok' ? '' : 'primary'), onclick: () => toggleProof() }, d.proof === 'ok' ? 'Zrušit označení (P)' : '✓ Zkontrolováno (P)'),
          h('button', { class: 'btn small', onclick: () => flagFix() }, d.proof === 'fix' ? 'Zrušit „k opravě“ (F)' : '⚑ K opravě (F)'),
          h('button', { class: 'btn small', title: 'Označí jako zkontrolované všechny přeložené řádky tohoto souboru od začátku až po tento řádek. Řádky označené „k opravě“ se nemění. Jde vrátit (Ctrl+Z).', onclick: () => proofUpto('ok') }, '✓ Zkontrolovat vše až sem (Shift+P)'),
          h('button', { class: 'btn small', title: 'Odebere značku „zkontrolováno“ všem řádkům tohoto souboru od začátku až po tento řádek. Řádky označené „k opravě“ zůstanou. Jde vrátit (Ctrl+Z).', onclick: () => proofUpto('') }, '↺ Zrušit zkontrolování až sem (Shift+U)')),
        h('textarea', { id: 'proofNote', rows: 2, placeholder: 'Poznámka ke korektuře (co opravit)…', value: d.proof_note || '', style: { width: '100%' },
          onchange: (ev) => saveNote(ev.target.value) })) : null,
      h('div', { class: 'ctx' }, 'Blok: ', h('b', { class: 'mono' }, d.block), d.who ? ['  ·  mluvčí: ', h('b', { class: 'mono' }, speakerFull(d.who))] : null, d.src_line ? `  ·  originál na řádku ${d.src_line}` : null),
      scriptContext(d),
      (d.before.length || d.after.length) ? h('div', null, h('h4', { style: { marginTop: '10px' } }, 'Okolí v souboru'),
        d.before.map((x) => ctxLine(x)), h('div', { class: 'ctx' }, h('b', null, `▶ ${d.line}`)), d.after.map((x) => ctxLine(x))) : null);
  }
  function translationEditor(d) {
    const ta = h('textarea', { id: 'editTarget', class: 'ed editbox', rows: 3, spellcheck: 'true', lang: 'cs', 'aria-label': 'Překlad' });
    ta.value = d.target;
    const msg = h('div', { class: 'editmsg' });
    const save = h('button', { class: 'btn small primary', disabled: true, title: 'Zapíše text do souboru .rpy (před zápisem se udělá záloha)' }, 'Uložit do souboru (Ctrl+Enter)');
    let timer, seq = 0;
    const dirty = () => ta.value !== d.target;
    const sync = () => { if (dirty()) ta.dataset.dirty = '1'; else delete ta.dataset.dirty; save.disabled = !dirty(); };
    async function check() {
      const my = ++seq;
      if (!dirty()) { msg.replaceChildren(); return; }
      try {
        const r = await post('entry/check', { file: d.file, line: d.line, text: ta.value });
        if (my !== seq) return;
        msg.replaceChildren(h('h4', null, 'Kontrola upraveného textu'),
          r.literal_error ? h('div', { class: 'issue error' }, chip('error', 'Nelze uložit'), ' ', r.literal_error) : null,
          ...r.issues.map((x) => h('div', { class: 'issue ' + x.severity }, chip(x.severity, SEV_LABEL[x.severity]), ' ', x.message)),
          !r.literal_error && !r.issues.length ? h('div', { class: 'muted' }, 'Bez nálezů.') : null);
        save.disabled = !dirty() || !!r.literal_error;
      } catch { /* the live check is only a hint */ }
    }
    async function doSave(advance) {
      if (!dirty() || save.disabled) return;
      save.disabled = true;
      try { await post('entry/save', { file: d.file, line: d.line, text: ta.value }); }
      catch (err) { save.disabled = false; return fail(err); }
      delete ta.dataset.dirty;
      S.files = null; refreshHeader();
      const i = S.ent.sel, it = S.ent.items[i];
      try {
        const nd = await get('entry', { file: d.file, line: d.line });
        if (it) { Object.assign(it, { target: nd.target, status: nd.status, proof: nd.proof, kind: nd.kind, issues: nd.issues.filter((x) => x.severity !== 'info').map((x) => ({ severity: x.severity, code: x.code })) }); refreshRow(i); }
        toast('Uloženo do souboru ✓', 'ok', 1800);
        if (advance) {
          let k = i + 1;
          while (k < S.ent.items.length && S.ent.items[k].status !== 'todo') k++;
          S.ent.focusEdit = true;
          select(k < S.ent.items.length ? k : Math.min(i + 1, S.ent.items.length - 1));
        } else select(i);
      } catch (err) { fail(err); }
    }
    ta.addEventListener('input', () => { sync(); clearTimeout(timer); timer = setTimeout(check, 300); });
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSave(true); }
      else if (e.key === 'Escape') { ta.value = d.target; sync(); check(); ta.blur(); }
    });
    save.onclick = () => doSave(false);
    /* snippets: insert at the cursor, or wrap the selection for paired tags */
    const insert = (text) => { const a = ta.selectionStart, b = ta.selectionEnd; ta.setRangeText(text, a, b, 'end'); ta.focus(); ta.dispatchEvent(new Event('input')); };
    const wrap = (open, close) => { const a = ta.selectionStart, b = ta.selectionEnd; ta.setRangeText(open + ta.value.slice(a, b) + close, a, b, 'end'); if (a === b) { ta.selectionStart = ta.selectionEnd = a + open.length; } ta.focus(); ta.dispatchEvent(new Event('input')); };
    const snip = (label, fn, title) => h('button', { class: 'btn small snip', title: title || '', onclick: (e) => { e.preventDefault(); fn(); } }, label);
    const tagBar = h('div', { class: 'snips' }, h('span', { class: 'muted' }, 'Vložit:'),
      snip('{i}…', () => wrap('{i}', '{/i}'), 'Kurzíva – obalí vybraný text'), snip('{b}…', () => wrap('{b}', '{/b}'), 'Tučně'), snip('{u}…', () => wrap('{u}', '{/u}'), 'Podtržené'),
      snip('{w}', () => insert('{w}'), 'Pauza, čeká na klik'), snip('{p}', () => insert('{p}'), 'Nový odstavec s pauzou'), snip('{nw}', () => insert('{nw}'), 'Bez čekání na klik'),
      snip('\\n', () => insert('\\n'), 'Zalomení řádku (v textu hry se zapisuje jako \\n)'), snip('…', () => insert('…'), 'Tři tečky jako jeden znak'), snip('„ “', () => wrap('„', '“'), 'České uvozovky – obalí vybraný text'));
    const tokenRe = /\{[^}]*\}|\[[^\]]*\]/g;
    const missing = h('div', { class: 'snips' });
    const terms = h('div', { class: 'snips' });
    const paintMissing = () => {
      const have = {}; (ta.value.match(tokenRe) || []).forEach((t) => { have[t] = (have[t] || 0) + 1; });
      const need = {}; ((d.source || '').match(tokenRe) || []).forEach((t) => { need[t] = (need[t] || 0) + 1; });
      const miss = Object.keys(need).filter((t) => !t.startsWith('{#') && (have[t] || 0) < need[t]);
      missing.replaceChildren(...(miss.length ? [h('span', { class: 'muted' }, 'Chybí z originálu:'), ...miss.map((t) => snip(t, () => insert(t), 'Vloží značku nebo proměnnou z originálu na místo kurzoru')),
        miss.length > 1 ? snip('všechny', () => insert(miss.join('')), 'Vloží všechny chybějící na místo kurzoru') : null] : []));
    };
    const paintTerms = () => {
      terms.replaceChildren(...((d.terms || []).length ? [h('span', { class: 'muted' }, 'Slovník:'), ...d.terms.map((t) => {
        const used = ta.value.toLowerCase().includes(t.cz.toLowerCase().slice(0, Math.max(3, t.cz.length - 2)));
        return snip(`${used ? '✓ ' : ''}${t.en} → ${t.cz}`, () => insert(t.cz), 'Vloží český termín ze Slovníku na místo kurzoru');
      })] : []));
    };
    ta.addEventListener('input', () => { paintMissing(); paintTerms(); });
    paintMissing(); paintTerms();
    const reset = h('button', { class: 'btn small', onclick: () => { ta.value = d.target; sync(); check(); } }, 'Vrátit text');
    const copyTgt = h('button', { class: 'btn small ghost', title: 'Zkopíruje text z pole překladu do schránky', onclick: () => copy(ta.value) }, '⧉ Překlad');
    const copySrc = h('button', { class: 'btn small', title: 'Vloží text originálu do pole (hodí se jako základ s už správnými značkami)', onclick: () => { ta.value = d.source ?? ''; sync(); check(); ta.focus(); } }, 'Originál do pole');
    const undoLast = h('button', { class: 'btn small ghost', title: 'Vrátí poslední změnu souboru .rpy provedenou touto aplikací (úprava textu nebo oprava mluvčích) ze zálohy', onclick: async () => {
      try { const r = await post('fix/undo'); toast(`Vráceno: ${r.label || 'poslední změna'}`, 'ok'); S.files = null; refreshHeader(); load(true); } catch (err) { fail(err); }
    } }, '↶ Vrátit poslední změnu souboru');
    if (S.ent.focusEdit) { S.ent.focusEdit = false; setTimeout(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }, 0); }
    return h('div', { class: 'editor' }, h('h4', null, 'Překlad ', h('span', { class: 'muted', style: { textTransform: 'none', letterSpacing: 0 } }, '– upravuje se přímo v souboru')), ta,
      tagBar, missing, terms,
      h('div', { class: 'actions' }, save, reset, copySrc, copyTgt, undoLast),
      h('div', { class: 'muted editnote' }, 'Nový řádek zapiš jako \\n, uvozovku jako \\". Značky {i}…{/i} a [proměnné] nech jako v originálu.'), msg,
      gamePreview(d, ta), memoryPanel(d, ta, insert), historyPanel(d, ta));
  }
  /* "Translation memory": the same / a similar original that was already translated. The match is made on the English original,
     so Czech endings do not matter for finding it – but they do for reusing it, hence the reminder. */
  function memoryPanel(d, ta, insert) {
    const box = h('details', { class: 'memory' });
    const sum = h('summary', null, 'Paměť překladů ', h('span', { class: 'muted' }, 'načítám…'));
    box.append(sum);
    const use = (text) => { ta.value = text; ta.dispatchEvent(new Event('input')); ta.focus(); };
    const card = (title, item, extra) => h('div', { class: 'memitem' },
      h('div', { class: 'memhead' }, title, extra || null),
      h('div', { class: 'txt memtext' }, fmtText(item.target)),
      h('div', { class: 'actions' },
        h('button', { class: 'btn small', title: 'Nahradí celý text v poli', onclick: () => use(item.target) }, 'Použít'),
        h('button', { class: 'btn small', title: 'Vloží text na místo kurzoru', onclick: () => insert(item.target) }, 'Vložit'),
        item.file ? h('button', { class: 'btn small ghost', onclick: () => go('entries', { file: item.file, line: item.line, status: 'all' }) }, 'Zobrazit řádek') : null));
    get('entry/memory', { file: d.file, line: d.line }).then((m) => {
      const n = m.exact.length + m.similar.length;
      sum.replaceChildren('Paměť překladů ', h('span', { class: 'muted' }, n ? `(${n})` : '(nic podobného)'));
      if (!n) return box.append(h('div', { class: 'muted' }, 'Tenhle ani podobný originál zatím není přeložený.'));
      box.append(h('div', { class: 'muted', style: { fontSize: '12px', margin: '4px 0' } }, 'Pozor na pád, rod a číslo: text se vkládá tak, jak byl dřív přeložený – do nové věty ho uprav.'));
      m.exact.forEach((g) => box.append(card(h('span', null, chip('proof', 'stejný originál'), ` ×${g.count}`, g.lines.length ? h('span', { class: 'muted' }, `  (${[...new Set(g.lines.map((l) => l.who || '–'))].join(', ')})`) : null), { ...g, file: g.lines[0]?.file, line: g.lines[0]?.line }, g.vars_differ ? chip('warning', '⚠ jiné proměnné') : null)));
      m.similar.forEach((x) => { const df = diffSpans(d.source || '', x.source); box.append(card(h('span', null, chip('info', `${Math.round(x.ratio * 100)} % podobné`)), x, h('span', null, ' ', x.vars_differ ? chip('warning', '⚠ jiné proměnné') : null, h('div', { class: 'muted memsrc' }, 'Originál tam: ', df.after)))); });
      if (n && pref('ui.memoryOpen', true)) box.open = true;
    }).catch(() => sum.replaceChildren('Paměť překladů ', h('span', { class: 'muted' }, '(nedostupná)')));
    box.addEventListener('toggle', () => setPref('ui.memoryOpen', box.open));
    return box;
  }
  /* Every text this line has had (edits in the app, fixes, replacements, undo and changes made elsewhere that were noticed at a refresh).
     Restoring puts the old text into the box; it is only written when you save. */
  function historyPanel(d, ta) {
    const box = h('details', { class: 'texthistory' });
    const sum = h('summary', null, 'Historie textu ', h('span', { class: 'muted' }, 'načítám…'));
    box.append(sum);
    get('entry/history', { file: d.file, line: d.line }).then((r) => {
      sum.replaceChildren('Historie textu ', h('span', { class: 'muted' }, r.count ? `(${r.count} ${plural(r.count, 'změna', 'změny', 'změn')})` : '(žádná zaznamenaná změna)'));
      if (!r.versions.length) return box.append(h('div', { class: 'muted' }, 'U tohoto řádku zatím nebyla zaznamenaná žádná změna. Zaznamenává se každá úprava v aplikaci i změna mimo ni, kterou aplikace zjistí při obnovení souborů (F5).'));
      for (const v of r.versions) {
        const df = diffSpans(d.target, v.text);
        box.append(h('div', { class: 'memitem' },
          h('div', { class: 'memhead' }, v.current ? chip('done', 'aktuální') : null, h('span', { class: 'muted' }, [v.time ? v.time.replace('T', ' ') : '', v.via].filter(Boolean).join(' · '))),
          h('div', { class: 'txt memtext' }, v.current ? fmtText(v.text) : df.after),
          v.current ? null : h('div', { class: 'actions' },
            h('button', { class: 'btn small', title: 'Vloží tuhle verzi do pole. Zapíše se až po uložení.', onclick: () => { ta.value = v.text; ta.dispatchEvent(new Event('input')); ta.focus(); } }, 'Obnovit do pole'),
            h('button', { class: 'btn small ghost', onclick: () => copy(v.text) }, '⧉ Kopírovat'))));
      }
    }).catch(() => sum.replaceChildren('Historie textu ', h('span', { class: 'muted' }, '(nedostupná)')));
    return box;
  }
  /* Approximate look of the line in the game's dialogue box: the game's own text size and text width (from gui.rpy), so
     you can see where it wraps and how many lines it needs. The real font is not used, so it is an estimate. */
  function gamePreview(d, ta) {
    const box = h('details', { class: 'gamepreview' });
    const sum = h('summary', null, 'Náhled v okně hry ', h('span', { class: 'muted' }, ''));
    const outer = h('div', { class: 'gwin' }), info = h('div', { class: 'muted ginfo' });
    box.append(sum, outer, info);
    box.open = !!pref('ui.gamepreview', false);
    box.addEventListener('toggle', () => { setPref('ui.gamepreview', box.open); if (box.open) draw(); });
    let gui = S.gui;
    async function draw() {
      if (!box.open) return;
      if (!gui) { try { const st = await get('settings'); gui = S.gui = { ...st.game_gui, max_lines: st.validation.textbox.max_lines }; } catch { gui = { text_size: 33, dialogue_width: 1116, textbox_height: 278, max_lines: 4, source: 'výchozí hodnoty' }; } }
      const inner = h('div', { class: 'gbox', style: { width: gui.dialogue_width + 'px', fontSize: gui.text_size + 'px' } });
      inner.append(gameText(ta.value));
      outer.replaceChildren(inner);
      const k = Math.min(1, (outer.clientWidth || gui.dialogue_width) / gui.dialogue_width);
      inner.style.transform = `scale(${k})`;
      outer.style.height = Math.ceil(inner.offsetHeight * k) + 'px';
      const lines = Math.max(1, Math.round(inner.offsetHeight / (gui.text_size * 1.3)));
      const over = lines > gui.max_lines;
      sum.lastChild.textContent = `(≈ ${lines} ${plural(lines, 'řádek', 'řádky', 'řádků')}${over ? ' – moc!' : ''})`;
      outer.classList.toggle('over', over);
      info.textContent = `Okno ${gui.dialogue_width} px, písmo ${gui.text_size} px (${gui.source}); limit ${gui.max_lines} ${plural(gui.max_lines, 'řádek', 'řádky', 'řádků')}. Odhad bez písma hry.`;
    }
    ta.addEventListener('input', () => { clearTimeout(box._t); box._t = setTimeout(draw, 150); });
    setTimeout(draw, 0);
    return box;
  }
  function scriptContext(d) {
    if (!d.ref) return null;
    const box = h('div', { class: 'scriptctx' });
    const show = async () => {
      box.replaceChildren(loading());
      try {
        const r = await get('entry/context', { file: d.file, line: d.line });
        if (!r.available) return box.replaceChildren(h('div', { class: 'muted' }, r.reason));
        box.replaceChildren(h('div', { class: 'muted mono', style: { fontSize: '12px' } }, 'Skript hry: ', r.ref),
          h('pre', { class: 'ctxcode' }, r.lines.map((x) => h('div', { class: x.hit ? 'hit' : '' }, `${String(x.n).padStart(5)}  ${x.text}`))));
      } catch (e) { box.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
    };
    if (d.unit === 'string') show();      // a choice / UI string has no dialogue around it: show where the game uses it
    else box.append(h('button', { class: 'btn small ghost', onclick: show }, 'Ukázat kontext ve skriptu hry'));
    return box;
  }
  const ctxLine = (x) => h('div', { class: 'ctx' }, `${x.line}  `, x.who ? h('span', { class: 'mono' }, speakerLabel(x.who) + ' ') : null, fmtText(x.target));

  async function toggleApprove() {
    const d = S.ent.detail; if (!d) return;
    const on = d.status !== 'approved';
    try {
      await post('approve/apply', { selections: [{ file: d.file, key: d.key }], on });
      toast(on ? 'Řádek schválen. Zpět: Ctrl+Z' : 'Schválení zrušeno.');
      const it = S.ent.items[S.ent.sel];
      it.status = on ? 'approved' : 'todo';
      tbody.replaceChild(rowFor(it, S.ent.sel), tbody.children[S.ent.sel]);
      S.files = null; await refreshHeader();
      if (on && pref('entries.status', 'todo') === 'todo') select(Math.min(S.ent.sel + 1, S.ent.items.length - 1));
      else select(S.ent.sel);
    } catch (err) { fail(err); }
  }
  function repaintRows() {
    if (!tbody) return;
    tbody.replaceChildren(...S.ent.items.map((it, i) => rowFor(it, i)));
    if (S.ent.detail) drawDetail(S.ent.detail);
  }
  function refreshRow(i) { tbody.replaceChild(rowFor(S.ent.items[i], i), tbody.children[i]); }
  async function setProof(state, note) {
    const d = S.ent.detail; if (!d || d.status === 'todo') return false;
    try {
      const r = await post('proof/set', { items: [{ file: d.file, key: d.key }], state, note });
      if (r.skipped.length) { toast(r.skipped[0][1], 'bad'); return false; }
      S.ent.items[S.ent.sel].proof = state;
      refreshRow(S.ent.sel); S.files = null; await refreshHeader();
      return true;
    } catch (err) { fail(err); return false; }
  }
  function nextToReview(from) {
    for (let k = from + 1; k < S.ent.items.length; k++) { const x = S.ent.items[k]; if (x.status !== 'todo' && !['ok', 'fix'].includes(x.proof)) return k; }
    return Math.min(from + 1, S.ent.items.length - 1);
  }
  async function toggleProof() {
    const d = S.ent.detail; if (!d) return;
    const on = d.proof !== 'ok';
    if (await setProof(on ? 'ok' : '')) {
      toast(on ? 'Zkontrolováno ✓  (Ctrl+Z vrátí)' : 'Označení zrušeno.', 'ok', 1800);
      select(on ? nextToReview(S.ent.sel) : S.ent.sel);
    }
  }
  async function flagFix() {
    const d = S.ent.detail; if (!d) return;
    const on = d.proof !== 'fix';
    if (await setProof(on ? 'fix' : '')) {
      await select(S.ent.sel);
      if (on) { const n = $('#proofNote'); n?.focus(); toast('Označeno k opravě – napiš poznámku.', 'ok', 2500); }
    }
  }
  async function saveNote(text) {
    const d = S.ent.detail; if (!d) return;
    const state = d.proof === 'fix' ? 'fix' : d.proof === 'ok' ? 'ok' : (text.trim() ? 'fix' : '');
    if (!state) return;
    if (await setProof(state, text)) { toast('Poznámka uložena ✓', 'ok', 1500); await select(S.ent.sel); }
  }
  async function proofUpto(state = 'ok') {
    const d = S.ent.detail; if (!d) return;
    const undo = state === '';
    if (undo && !await confirmDialog('Zrušit zkontrolování až sem?', `U všech řádků souboru ${d.file.split(/[\\/]/).pop()} od začátku po řádek ${d.line} se zruší označení „zkontrolováno“. Řádky označené „k opravě“ zůstanou. Jde to vrátit přes Ctrl+Z.`, 'Zrušit zkontrolování')) return;
    try {
      const r = await post('proof/upto', { file: d.file, line: d.line, state });
      S.ent.items.forEach((x, i) => {
        if (x.file !== d.file || x.line > d.line || x.status === 'todo') return;
        if (!undo && ['', 'stale'].includes(x.proof)) { x.proof = 'ok'; refreshRow(i); }
        if (undo && ['ok', 'stale'].includes(x.proof)) { x.proof = ''; refreshRow(i); }
      });
      S.files = null; await refreshHeader(); await select(S.ent.sel);
      toast(r.changed ? (undo ? `Zkontrolování zrušeno u ${r.changed} řádků  (Ctrl+Z vrátí)` : `Zkontrolováno ${r.changed} řádků ✓  (Ctrl+Z vrátí)`) : (undo ? 'Nebylo co rušit.' : 'Nebylo co označit.'), 'ok', 3000);
    } catch (err) { fail(err); }
  }
  async function globalApprove() {
    const d = S.ent.detail; if (!d || d.status === 'translated') return;
    await globalApproveDialog(d, async () => { S.files = null; await refreshHeader(); load(true); });
  }
  S.ent.api = { select, toggleApprove, toggleProof, flagFix, proofUpto, unproofUpto: () => proofUpto(''), globalApprove, load, tbody: () => tbody, reload: () => load(true) };
  root.afterMount = () => { load(true); drawDetail(null); };
  return root;
}
async function globalApproveDialog(d, done) {
  let scope = 'file', sameSpeaker = true, data = null, armed = false;
  const body = h('div');
  const foot = h('button', { class: 'btn primary', disabled: true });
  const info = h('span', { class: 'grow' });
  const sel = new Set();
  async function loadPreview() {
    body.replaceChildren(loading());
    try { data = await post('approve/preview', { file: d.file, line: d.line, scope, same_speaker: sameSpeaker }); }
    catch (e) { body.replaceChildren(h('div', { class: 'notice bad' }, e.message)); return; }
    sel.clear(); data.items.forEach((it, i) => { if (it.selected) sel.add(i); });
    armed = false; paint();
  }
  function paint() {
    const files = new Set([...sel].map((i) => data.items[i].file));
    const segBtn = (k, l) => h('button', { class: scope === k ? 'on' : '', onclick: () => { scope = k; loadPreview(); } }, l);
    const rows = data.items.map((it, i) => h('tr', null,
      h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: sel.has(i), disabled: !it.selectable, onchange: (e) => { e.target.checked ? sel.add(i) : sel.delete(i); armed = false; paint2(); } })),
      h('td', null, fname(it.file)), h('td', { class: 'num' }, it.line), h('td', { class: 'who' }, speakerLabel(it.who) || '—'),
      h('td', null, fmtText(it.text)), h('td', null, it.is_reference ? chip('rev', 'vybraný řádek') : null, it.approved ? chip('approved', 'schváleno') : null, h('span', { class: 'muted' }, it.notes.join('; ')))));
    const t = h('table', { class: 'data' }, h('colgroup', null, [40, 420, 70, 90, 260, 300].map((w) => h('col', { style: { width: w + 'px' } }))),
      h('thead', null, h('tr', null, ['', 'Soubor', 'Řádek', 'Mluvčí', 'Text', 'Poznámka'].map((x, i) => h('th', { class: i === 0 ? 'center' : '' }, x)))), h('tbody', null, rows));
    t.style.width = '1240px';
    body.replaceChildren(
      h('p', { class: 'muted' }, 'Schválí se pouze řádky, jejichž originál i překlad jsou stejné jako u vybraného řádku. Řádky s jiným mluvčím nebo vypadající jako nepřeložená angličtina jsou ve výchozím stavu nezaškrtnuté. Každý schválený řádek se zapíše zvlášť (podle bloku), takže jde vrátit přes Ctrl+Z.'),
      h('div', { class: 'toolbar' }, h('div', { class: 'seg' }, segBtn('occurrence', 'Jen tento řádek'), segBtn('file', 'Celý tento soubor'), segBtn('project', 'Celý projekt')),
        h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: sameSpeaker, onchange: (e) => { sameSpeaker = e.target.checked; loadPreview(); } }), 'Předvybrat jen stejného mluvčího')),
      h('div', { class: 'ctx' }, 'Vybraný text: ', h('b', null, fmtText(data.reference.text))),
      h('div', { class: 'tablewrap', style: { maxHeight: '48vh', marginTop: '8px' } }, t));
    paint2(files);
  }
  function paint2(files) {
    files = files || new Set([...sel].map((i) => data.items[i].file));
    const n = sel.size;
    const broad = n > 1;
    foot.disabled = !n;
    foot.textContent = armed ? `Potvrdit: schválit ${n} řádků v ${files.size} souborech` : `Schválit vybrané (${n})`;
    foot.classList.toggle('danger', armed);
    info.textContent = `Nalezeno ${data.counts.total} shodných · vybráno ${n} v ${files.size} souborech` + (broad ? ' · hromadná změna se musí potvrdit dvakrát' : '');
    foot.onclick = async () => {
      if (broad && !armed) { armed = true; paint2(files); setTimeout(() => { armed = false; paint2(); }, 8000); return false; }
      try {
        const res = await post('approve/apply', { selections: [...sel].map((i) => ({ file: data.items[i].file, key: data.items[i].key })), on: true });
        toast(`Schváleno ${res.changed} řádků` + (res.skipped.length ? `, přeskočeno ${res.skipped.length}` : '') + '. Zpět: Ctrl+Z', res.skipped.length ? 'bad' : 'ok');
        close(); done?.();
      } catch (e) { fail(e); }
      return false;
    };
  }
  S.dlgDirty = true;
  const close = dialog({ title: 'Schválit shodné řádky', body, buttons: [{ label: 'Zrušit' }, { node: h('span', { style: { display: 'contents' } }, info, foot) }] });
  loadPreview();
}

/* Fix speaker / attributes / trailing code from the original (the only operation that edits the .rpy files). */
/* Shows what changed between two texts: common start / end stay plain, the middle is marked. */
function diffSpans(before, after) {
  const n = Math.min(before.length, after.length);
  let i = 0;
  while (i < n && before[i] === after[i]) i++;
  let j = 0;
  while (j < n - i && before[before.length - 1 - j] === after[after.length - 1 - j]) j++;
  const part = (str, cls) => h('span', null, str.slice(0, i), h('mark', { class: cls }, str.slice(i, str.length - j) || '∅'), str.slice(str.length - j));
  return { before: part(before, 'diff-del'), after: part(after, 'diff-add') };
}

/* Safe fixes: speaker / attributes from the original, double spaces, typo hints. Every line is ticked or unticked
   by the user; doubtful ones start unticked. Variables and tags are never offered (their order may legitimately differ). */
const FIX_KIND_LABEL = { speaker: 'Mluvčí / atributy', spaces: 'Dvojité mezery', typo: 'Překlepy' };
const FIX_KIND_HELP = {
  speaker: 'Mluvčí, atributy a kód za textem se zkopírují z originálu (řádek s #). Text překladu se nemění.',
  spaces: 'Několik mezer za sebou mezi slovy se změní na jednu (jen když je originál nemá taky).',
  typo: 'Návrhy podle slovníku z tvého vlastního překladu. Krátká a nejistá slova jsou odškrtnutá, protože může jít o falešný poplach (byt / být). Zaškrtni jen to, co opravdu chceš.',
};
async function fixDialog({ items = [], file = '', kinds = ['speaker', 'spaces', 'typo'] }, done) {
  let data;
  try { data = await post('fix/preview', { items, file, kinds }); } catch (e) { return fail(e); }
  if (!data.total) return toast('Není co opravovat.', 'ok');
  const key = (it) => `${it.file}|${it.line}|${it.kind}`;
  const sel = new Set(data.items.filter((it) => it.default && !it.skip).map(key));
  let only = kinds.length === 1 ? kinds[0] : '';
  const head = h('div'), listBox = h('div'), info = h('span', { class: 'grow' });
  const go = h('button', { class: 'btn primary', disabled: true });
  const visible = () => data.items.filter((it) => !only || it.kind === only).slice(0, 600);
  function paint() {
    const seg = h('div', { class: 'seg' }, h('button', { class: only === '' ? 'on' : '', onclick: () => { only = ''; paint(); } }, `Vše (${data.total})`),
      ...Object.keys(data.counts).filter((k) => data.counts[k]).map((k) => h('button', { class: only === k ? 'on' : '', onclick: () => { only = k; paint(); } }, `${FIX_KIND_LABEL[k]} (${data.counts[k]})`)));
    const vis = visible();
    head.replaceChildren(
      only ? h('p', null, FIX_KIND_HELP[only]) : h('p', { class: 'muted' }, 'Vyber, co se má opravit. Před zápisem se vytvoří záloha souboru ve složce ', h('b', null, '_progress_data/backups'), '; změnu jde vrátit tlačítkem „Vrátit poslední změnu souboru“. Soubory musí být uložené v editoru.'),
      h('div', { class: 'toolbar' }, seg, h('span', { class: 'spacer' }),
        h('button', { class: 'btn small', onclick: () => { vis.forEach((it) => { if (!it.skip) sel.add(key(it)); }); paint(); } }, 'Vybrat vše'),
        h('button', { class: 'btn small', onclick: () => { vis.forEach((it) => sel.delete(key(it))); paint(); } }, 'Nic'),
        h('button', { class: 'btn small', title: 'Jen to, co je bezpečné (nejisté návrhy zůstanou odškrtnuté)', onclick: () => { vis.forEach((it) => { if (it.default && !it.skip) sel.add(key(it)); else sel.delete(key(it)); }); paint(); } }, 'Jen doporučené')));
    const rows = vis.map((it) => {
      const d = it.code ? null : diffSpans(it.before, it.after);
      return h('tr', null,
        h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: sel.has(key(it)), disabled: !!it.skip, onchange: (e) => { e.target.checked ? sel.add(key(it)) : sel.delete(key(it)); paint2(); } })),
        h('td', null, fname(it.file), h('span', { class: 'mono muted' }, `řádek ${it.line}`), only ? null : h('div', null, chip('none', FIX_KIND_LABEL[it.kind]))),
        h('td', { class: it.code ? 'mono txt' : 'txt' }, d ? d.before : it.before),
        h('td', { class: it.code ? 'mono txt' : 'txt' }, it.skip ? h('span', { class: 'muted' }, it.skip) : (d ? d.after : it.after), !it.code && it.note ? h('div', { class: 'muted', style: { fontSize: '12px' } }, it.note) : null));
    });
    const t = h('table', { class: 'data' }, h('colgroup', null, [44, 190, 340, 340].map((w) => h('col', { style: { width: w + 'px' } }))),
      h('thead', null, h('tr', null, ['', 'Kde', 'Teď', 'Po opravě'].map((x) => h('th', null, x)))), h('tbody', null, rows));
    t.style.width = '914px';
    listBox.replaceChildren(vis.length < data.items.filter((it) => !only || it.kind === only).length ? h('p', { class: 'muted' }, 'Zobrazeno prvních 600 řádků.') : null, h('div', { class: 'tablewrap', style: { maxHeight: '46vh' } }, t));
    paint2();
  }
  function paint2() {
    const n = sel.size;
    go.disabled = !n;
    go.textContent = `Opravit ${n} ${plural(n, 'řádek', 'řádky', 'řádků')}`;
    info.textContent = `Vybráno ${n} z ${data.fixable} použitelných`;
  }
  go.onclick = async () => {
    const selections = data.items.filter((it) => sel.has(key(it))).map((it) => ({ file: it.file, line: it.line, kind: it.kind }));
    try {
      const r = await post('fix/apply', { selections });
      toast(`Opraveno ${r.fixed} ${plural(r.fixed, 'řádek', 'řádky', 'řádků')}` + (r.skipped.length ? `, přeskočeno ${r.skipped.length}` : '') + '. Zpět: „Vrátit poslední změnu souboru“.', r.skipped.length ? 'bad' : 'ok', 8000);
      S.files = null; await refreshHeader(); done?.();
    } catch (e) { fail(e); return false; }
  };
  const body = h('div', null, head, listBox);
  paint();
  dialog({ title: 'Opravit', body, buttons: [{ label: 'Zrušit' }, { node: h('span', { style: { display: 'contents' } }, info, go) }] });
}

/* Find and replace in the translated texts of all or chosen files, with a preview you tick line by line. */
async function replaceDialog(done, preselected = []) {
  const allFiles = (S.files || []).map((x) => x.name);
  const chosen = new Set(preselected.filter((n) => allFiles.includes(n)));
  const st = { mode: 'plain', scope: chosen.size ? 'chosen' : 'all', armed: false };
  let data = null, seq = 0, timer;
  const sel = new Set();
  const find = h('input', { type: 'text', placeholder: 'Co hledat', style: { flex: 1 } });
  const repl = h('input', { type: 'text', placeholder: 'Čím nahradit (může být prázdné)', style: { flex: 1 } });
  const caseBox = h('input', { type: 'checkbox' }), protBox = h('input', { type: 'checkbox', checked: true });
  const MODES = [['plain', 'Text'], ['word', 'Celé slovo'], ['stem', 'Podle kmene (pokusné)'], ['regex', 'Regulární výraz']];
  const modeSeg = h('div', { class: 'seg' }), scopeBox = h('div'), results = h('div'), info = h('span', { class: 'grow' });
  const go = h('button', { class: 'btn primary', disabled: true }, 'Nahradit');
  const MODE_HELP = { plain: 'Najde text kdekoli (i uvnitř slov).', word: 'Najde jen celé slovo.', stem: 'Najde i jiné tvary slova podle kmene (dikmince → dikminci) a ponechá jejich koncovku. Funguje dobře jen u slov se stejným skloňováním – vždy zkontroluj náhled.', regex: 'Regulární výraz Pythonu; v náhradě lze použít \\1, \\2…' };
  const hint = h('div', { class: 'muted' });
  function paintMode() {
    modeSeg.replaceChildren(...MODES.map(([k, l]) => h('button', { class: st.mode === k ? 'on' : '', onclick: () => { st.mode = k; paintMode(); schedule(); } }, l)));
    hint.textContent = MODE_HELP[st.mode];
  }
  function paintScope() {
    const segBtn = (k, l) => h('button', { class: st.scope === k ? 'on' : '', onclick: () => { st.scope = k; paintScope(); schedule(); } }, l);
    const list = h('div', { class: 'filepick' });
    const q = h('input', { type: 'search', class: 'search', placeholder: 'Hledat soubor…', style: { maxWidth: '240px' } });
    const count = h('span', { class: 'muted' }, `vybráno ${chosen.size}`);
    const fill = () => { const t = q.value.toLowerCase(); list.replaceChildren(...allFiles.filter((n) => !t || n.toLowerCase().includes(t)).map((n) => h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: chosen.has(n), onchange: (e) => { e.target.checked ? chosen.add(n) : chosen.delete(n); count.textContent = `vybráno ${chosen.size}`; schedule(); } }), ' ', n))); };
    q.oninput = fill;
    scopeBox.replaceChildren(h('div', { class: 'toolbar' }, h('b', null, 'Kde:'), h('div', { class: 'seg' }, segBtn('all', `Všechny soubory (${allFiles.length})`), segBtn('chosen', 'Jen vybrané soubory')),
      st.scope === 'chosen' ? [count, h('button', { class: 'btn small', onclick: () => { allFiles.forEach((n) => chosen.add(n)); fill(); count.textContent = `vybráno ${chosen.size}`; schedule(); } }, 'Vše'), h('button', { class: 'btn small', onclick: () => { chosen.clear(); fill(); count.textContent = 'vybráno 0'; schedule(); } }, 'Nic'), q] : null), st.scope === 'chosen' ? list : null);
    if (st.scope === 'chosen') fill();
  }
  const request = () => ({ find: find.value, replace: repl.value, mode: st.mode, case: caseBox.checked, protect: protBox.checked, files: st.scope === 'chosen' ? [...chosen] : [] });
  function schedule() { clearTimeout(timer); timer = setTimeout(preview, 350); }
  async function preview() {
    const my = ++seq;
    if (!find.value) { data = null; sel.clear(); results.replaceChildren(empty('Zadej hledaný text', 'Náhled se ukáže hned, nic se nezapisuje, dokud nepotvrdíš.')); paint2(); return; }
    if (st.scope === 'chosen' && !chosen.size) { data = null; results.replaceChildren(empty('Vyber soubory', 'Zaškrtni aspoň jeden soubor, nebo přepni na „Všechny soubory“.')); paint2(); return; }
    results.replaceChildren(loading());
    let r;
    try { r = await post('replace/preview', request()); } catch (e) { if (my === seq) { data = null; sel.clear(); results.replaceChildren(h('div', { class: 'notice bad' }, e.message)); paint2(); } return; }
    if (my !== seq) return;
    data = r; sel.clear(); r.items.forEach((it, i) => { if (!it.skip) sel.add(i); }); st.armed = false; paintResults();
  }
  function paintResults() {
    if (!data.items.length) { results.replaceChildren(empty('Nic nenalezeno', 'V přeložených řádcích hledaný text není (nepřeložené řádky se nehledají).')); return paint2(); }
    const shown = data.items.slice(0, 500);
    const rows = shown.map((it, i) => { const d = diffSpans(it.before, it.after); return h('tr', null,
      h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: sel.has(i), disabled: !!it.skip, onchange: (e) => { e.target.checked ? sel.add(i) : sel.delete(i); st.armed = false; paint2(); } })),
      h('td', null, fname(it.file), h('span', { class: 'mono muted' }, `řádek ${it.line}`)), h('td', { class: 'txt' }, d.before),
      h('td', { class: 'txt' }, it.skip ? h('span', { class: 'muted' }, it.skip) : d.after), h('td', { class: 'num' }, it.count)); });
    const t = h('table', { class: 'data' }, h('colgroup', null, [44, 200, 330, 330, 50].map((w) => h('col', { style: { width: w + 'px' } }))),
      h('thead', null, h('tr', null, ['', 'Kde', 'Teď', 'Po nahrazení', '×'].map((x) => h('th', null, x)))), h('tbody', null, rows));
    t.style.width = '954px';
    results.replaceChildren(h('div', { class: 'toolbar' }, h('span', { class: 'muted' }, `${data.total} ${plural(data.total, 'řádek', 'řádky', 'řádků')}, ${data.matches} ${plural(data.matches, 'výskyt', 'výskyty', 'výskytů')}` + (data.truncated ? ' (zobrazeno jen prvních 2000)' : '')), h('span', { class: 'spacer' }),
      h('button', { class: 'btn small', onclick: () => { shown.forEach((it, i) => { if (!it.skip) sel.add(i); }); paintResults(); } }, 'Vybrat vše'), h('button', { class: 'btn small', onclick: () => { sel.clear(); paintResults(); } }, 'Nic')),
      data.items.length > 500 ? h('p', { class: 'muted' }, 'Zobrazeno prvních 500; nahradí se jen zobrazené.') : null, h('div', { class: 'tablewrap', style: { maxHeight: '40vh' } }, t));
    paint2();
  }
  function paint2() {
    const n = sel.size;
    go.disabled = !n;
    go.classList.toggle('danger', st.armed);
    go.textContent = st.armed ? `Potvrdit: nahradit v ${n} ${plural(n, 'řádku', 'řádcích', 'řádcích')}` : `Nahradit (${n})`;
    info.textContent = data ? `Vybráno ${n} z ${data.applicable}` + (n > 1 ? ' · hromadná změna se musí potvrdit dvakrát' : '') : '';
  }
  go.onclick = async () => {
    if (sel.size > 1 && !st.armed) { st.armed = true; paint2(); setTimeout(() => { st.armed = false; paint2(); }, 8000); return false; }
    try {
      const shown = data.items.slice(0, 500);
      const r = await post('replace/apply', { ...request(), selections: [...sel].map((i) => ({ file: shown[i].file, line: shown[i].line })) });
      toast(`Nahrazeno v ${r.changed} ${plural(r.changed, 'řádku', 'řádcích', 'řádcích')} (${r.files} ${plural(r.files, 'soubor', 'soubory', 'souborů')}). Zpět: „Vrátit poslední změnu souboru“.`, 'ok', 8000);
      S.files = null; await refreshHeader(); done?.();
    } catch (e) { fail(e); return false; }
  };
  [find, repl].forEach((i) => i.addEventListener('input', schedule));
  [caseBox, protBox].forEach((i) => i.addEventListener('change', schedule));
  paintMode(); paintScope();
  const body = h('div', null,
    h('p', { class: 'muted' }, 'Hledá a nahrazuje v už přeloženém textu. Značky {i}, proměnné [jméno] a zápisy \\n se ve výchozím nastavení nikdy nemění. Před zápisem se vytvoří záloha; změnu jde vrátit jedním krokem.'),
    h('div', { class: 'row', style: { marginBottom: '8px' } }, find, repl),
    h('div', { class: 'toolbar' }, modeSeg, h('label', { class: 'check' }, caseBox, ' Rozlišovat velikost písmen'), h('label', { class: 'check' }, protBox, ' Nehýbat značky a proměnné')), hint, scopeBox, results);
  S.dlgDirty = true;
  dialog({ title: 'Najít a nahradit', body, buttons: [{ label: 'Zavřít' }, { node: h('span', { style: { display: 'contents' } }, info, go) }] });
  setTimeout(() => find.focus(), 0);
  preview();
}

/* Approve lines by a simple rule (symbols only, interjections, names from the glossary). Goes through the normal approval. */
async function ruleApproveDialog(done, preselected = []) {
  const rules = { symbols: true, interjections: true, names: true };
  const allFiles = (S.files || []).map((x) => x.name);
  const chosen = new Set(preselected.filter((n) => allFiles.includes(n)));
  let scope = chosen.size ? 'chosen' : 'all';
  let data = null, armed = false;
  const sel = new Set();
  const scopeBox = h('div'), results = h('div'), body = h('div', null, scopeBox, results), info = h('span', { class: 'grow' });
  const foot = h('button', { class: 'btn primary', disabled: true });
  const RULE_LABEL = { symbols: 'jen znaky', interjections: 'citoslovce', names: 'jméno' };
  async function load() {
    if (scope === 'chosen' && !chosen.size) { data = null; results.replaceChildren(empty('Vyber soubory', 'Zaškrtni aspoň jeden soubor, nebo přepni na „Všechny soubory“.')); foot.disabled = true; info.textContent = ''; return; }
    results.replaceChildren(loading());
    try { data = await post('approve/rules', { rules: Object.keys(rules).filter((k) => rules[k]), files: scope === 'chosen' ? [...chosen] : [] }); }
    catch (e) { return results.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
    sel.clear(); data.items.forEach((it, i) => { if (it.selected) sel.add(i); });
    armed = false; paint();
  }
  function paint() {
    const checks = Object.entries(data.rules).map(([k, label]) => h('label', { class: 'check', style: { display: 'block' } },
      h('input', { type: 'checkbox', checked: rules[k], onchange: (e) => { rules[k] = e.target.checked; load(); } }), ' ', label, h('span', { class: 'muted' }, `  (${data.counts.by_rule[k] || 0})`)));
    const rows = data.items.slice(0, 500).map((it, i) => h('tr', null,
      h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: sel.has(i), disabled: !it.selectable, onchange: (e) => { e.target.checked ? sel.add(i) : sel.delete(i); armed = false; paint2(); } })),
      h('td', null, chip('none', RULE_LABEL[it.rule])), h('td', null, fname(it.file), h('span', { class: 'mono muted' }, `řádek ${it.line}`)),
      h('td', { class: 'who' }, speakerLabel(it.who) || '—'), h('td', { class: 'txt' }, fmtText(it.text)), h('td', { class: 'muted' }, it.notes.join('; '))));
    const t = h('table', { class: 'data' }, h('colgroup', null, [40, 100, 250, 110, 280, 100].map((w) => h('col', { style: { width: w + 'px' } }))),
      h('thead', null, h('tr', null, ['', 'Pravidlo', 'Kde', 'Mluvčí', 'Text', ''].map((x) => h('th', null, x)))), h('tbody', null, rows));
    t.style.width = '880px';
    results.replaceChildren(
      h('p', { class: 'muted' }, 'Řádky, které se překládat nemusí, protože jsou v češtině stejné. Nic se nemění, dokud nepotvrdíš. Schválení lze vrátit přes Ctrl+Z. Jména se berou ze Slovníku – čím víc jmen tam máš, tím víc řádků pravidlo najde.'),
      h('div', null, checks),
      data.items.length > 500 ? h('p', { class: 'muted' }, `Zobrazeno prvních 500 z ${data.items.length}; schválí se jen zobrazené.`) : null,
      data.items.length ? h('div', { class: 'tablewrap', style: { maxHeight: '44vh', marginTop: '8px' } }, t) : empty('Nic nenalezeno', 'Žádný nepřeložený řádek nevyhovuje vybraným pravidlům.'));
    paint2();
  }
  function paint2() {
    const n = sel.size;
    foot.disabled = !n;
    foot.textContent = armed ? `Potvrdit: schválit ${n} řádků` : `Schválit vybrané (${n})`;
    foot.classList.toggle('danger', armed);
    info.textContent = `Nalezeno ${data.counts.total} · vybráno ${n}` + (n > 1 ? ' · hromadná změna se musí potvrdit dvakrát' : '');
    foot.onclick = async () => {
      if (n > 1 && !armed) { armed = true; paint2(); setTimeout(() => { armed = false; paint2(); }, 8000); return false; }
      try {
        const res = await post('approve/apply', { selections: [...sel].map((i) => ({ file: data.items[i].file, key: data.items[i].key })), on: true });
        toast(`Schváleno ${res.changed} řádků` + (res.skipped.length ? `, přeskočeno ${res.skipped.length}` : '') + '. Zpět: Ctrl+Z', res.skipped.length ? 'bad' : 'ok');
        close(); done?.();
      } catch (e) { fail(e); }
      return false;
    };
  }
  function paintScope() {
    const segBtn = (k, l) => h('button', { class: scope === k ? 'on' : '', onclick: () => { scope = k; paintScope(); load(); } }, l);
    const list = h('div', { class: 'filepick' });
    const q = h('input', { type: 'search', class: 'search', placeholder: 'Hledat soubor…', style: { maxWidth: '260px' } });
    const fill = () => {
      const t = q.value.toLowerCase();
      list.replaceChildren(...allFiles.filter((n) => !t || n.toLowerCase().includes(t)).map((n) => h('label', { class: 'check' },
        h('input', { type: 'checkbox', checked: chosen.has(n), onchange: (e) => { e.target.checked ? chosen.add(n) : chosen.delete(n); count.textContent = `vybráno ${chosen.size}`; clearTimeout(S.ruleTimer); S.ruleTimer = setTimeout(load, 350); } }), ' ', n)));
    };
    const count = h('span', { class: 'muted' }, `vybráno ${chosen.size}`);
    q.oninput = fill;
    const setAll = (on) => { allFiles.filter((n) => !q.value || n.toLowerCase().includes(q.value.toLowerCase())).forEach((n) => (on ? chosen.add(n) : chosen.delete(n))); fill(); count.textContent = `vybráno ${chosen.size}`; load(); };
    scopeBox.replaceChildren(h('div', { class: 'toolbar' }, h('b', null, 'Kde hledat:'), h('div', { class: 'seg' }, segBtn('all', `Všechny soubory (${allFiles.length})`), segBtn('chosen', 'Jen vybrané soubory')),
      scope === 'chosen' ? [count, h('button', { class: 'btn small', onclick: () => setAll(true) }, 'Vše zobrazené'), h('button', { class: 'btn small', onclick: () => setAll(false) }, 'Nic'), q] : null),
      scope === 'chosen' ? list : null);
    if (scope === 'chosen') fill();
  }
  paintScope();
  S.dlgDirty = true;
  const close = dialog({ title: 'Schválit podle pravidla', body, buttons: [{ label: 'Zrušit' }, { node: h('span', { style: { display: 'contents' } }, info, foot) }] });
  load();
}

/* Every line whose original contains a glossary term, and whether the Czech term is used there. */
async function occurrencesDialog(code) {
  let only = false;
  const body = h('div');
  async function load() {
    body.replaceChildren(loading());
    let r;
    try { r = await get('glossary/occurrences', { code, missing: only ? '1' : '' }); } catch (e) { return body.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
    const state = (it) => (it.used === true ? chip('proof', 'použito') : it.used === false ? chip('warning', 'chybí') : chip('none', it.translated ? '—' : 'nepřeloženo'));
    const rows = r.items.map((it) => h('tr', null, h('td', null, state(it)), h('td', null, fname(it.file), h('span', { class: 'mono muted' }, `řádek ${it.line}`)),
      h('td', { class: 'txt' }, fmtText(it.source)), h('td', { class: 'txt' }, fmtText(it.target)),
      h('td', null, h('button', { class: 'btn small', onclick: () => { close(); go('entries', { file: it.file, line: it.line, status: 'all' }); } }, 'Zobrazit'))));
    const t = h('table', { class: 'data' }, h('colgroup', null, [90, 230, 300, 300, 90].map((w) => h('col', { style: { width: w + 'px' } }))),
      h('thead', null, h('tr', null, ['Stav', 'Kde', 'Originál', 'Překlad', ''].map((x) => h('th', null, x)))), h('tbody', null, rows));
    t.style.width = '1010px';
    body.replaceChildren(
      h('p', null, h('b', null, code), ' → ', r.czech ? h('b', null, r.czech) : h('span', { class: 'muted' }, '(český překlad není ve Slovníku vyplněný)')),
      h('p', { class: 'muted' }, `Použito ${r.found}× · chybí ${r.missing}× · nepřeloženo ${r.untranslated}×. Porovnává se podle kmene slova, takže koncovky nevadí; krátké nebo hodně ohnuté tvary může hlídat špatně.`),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: only, onchange: (e) => { only = e.target.checked; load(); } }), ' Jen řádky, kde český termín chybí'),
      r.items.length ? h('div', { class: 'tablewrap', style: { maxHeight: '50vh', marginTop: '8px' } }, t) : empty('Žádné výskyty', only ? 'V přeložených řádcích termín nechybí.' : 'V originále se termín nevyskytuje.'),
      r.truncated ? h('p', { class: 'muted' }, 'Zobrazeno prvních 400 výskytů.') : null);
  }
  const close = dialog({ title: 'Výskyty termínu', body, buttons: [{ label: 'Zavřít', kind: 'primary' }] });
  load();
}

/* Ignoring findings on single lines. An ignore is bound to the current translation text: when the text changes, the
   finding shows up again. Ignored findings stay listed (Kontrola -> Ignorované) and can be restored. */
function ignoreDialog(items, done) {
  const note = h('input', { type: 'text', placeholder: 'Proč se to ignoruje? (nepovinné, uvidíš to v seznamu ignorovaných)', style: { width: '100%' } });
  const all = items.length > 1 ? h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: true, id: 'ignAll' }), ` Ignorovat všech ${items.length} nálezů u tohoto řádku`) : null;
  const body = h('div', null,
    h('p', { class: 'muted' }, 'Nález zmizí ze seznamů, počtů a ze zvýraznění řádků. Zůstane v seznamu ',
      h('b', null, 'Kontrola → Ignorované'), ', kde ho jedním klikem vrátíš. Když překlad řádku změníš, nález se znovu zobrazí.'),
    ...items.map((x) => h('div', { class: 'issue ' + (x.severity || 'warning') }, x.severity ? chip(x.severity, SEV_LABEL[x.severity]) : null, ' ', x.message || x.code)),
    all, h('div', { style: { marginTop: '10px' } }, note));
  dialog({ title: 'Ignorovat nález', narrow: true, body, buttons: [{ label: 'Zrušit' }, { label: 'Ignorovat', kind: 'primary', onclick: async () => {
    const chosen = all && !document.getElementById('ignAll').checked ? items.slice(0, 1) : items;
    try {
      const r = await post('ignore/set', { items: chosen.map((x) => ({ file: x.file, line: x.line, code: x.code })), on: true, note: note.value });
      toast(`Ignorováno ${r.changed} nálezů. Zpět: Ctrl+Z nebo Kontrola → Ignorované.`, 'ok');
      S.files = null; await refreshHeader(); done?.();
    } catch (e) { fail(e); }
  } }] });
  setTimeout(() => note.focus(), 0);
}
async function unignore(items, done) {
  try {
    const r = await post('ignore/set', { items: items.map((x) => ({ file: x.file, line: x.line || undefined, key: x.key, code: x.code })), on: false });
    toast(`Nález je znovu aktivní (${r.changed}).`, 'ok');
    S.files = null; await refreshHeader(); done?.();
  } catch (e) { fail(e); }
}
const IGN_STATE = { active: ['Ignorováno', 'none', 'Nález je schovaný.'], expired: ['Text se změnil', 'warning', 'Překlad se od ignorování změnil, takže se nález zobrazuje znovu (ignorování už neplatí).'],
  resolved: ['Už se neděje', 'tr', 'Text je stejný, ale kontrola tenhle nález už nehlásí (třeba po změně nastavení).'], gone: ['Řádek zmizel', 'none', 'Řádek už v souboru není.'] };

/* ================================================================ VALIDATION */
async function viewValidation() {
  const o = S.goOpts; S.goOpts = null;
  if (o?.file !== undefined) setPref('validation.file', o.file);
  if (o?.ignored !== undefined) setPref('validation.ignored', o.ignored);
  const settings = await get('settings');
  const root = h('div');
  const list = h('div'), counter = h('span', { class: 'muted' });
  const files = S.files || (S.files = (await get('files')).files);
  const v = pref('validation', {});
  const SEV_OPTS = [['', 'Chyby + varování'], ['error', 'Chyby'], ['warning', 'Varování'], ['info', 'Drobnosti']];
  const CAT_OPTS = [['', 'Všechny druhy'], ['syntax', 'Značky a proměnné'], ['structure', 'Struktura (mluvčí, bloky)'], ['length', 'Délka textu'], ['text', 'Text (čísla, angličtina, překlepy)']];
  const cat = h('select', { title: 'Druh nálezu', onchange: (ev) => { setPref('validation.category', ev.target.value); load(true); } }, CAT_OPTS.map(([k, l]) => h('option', { value: k }, l)));
  cat.value = v.category || '';
  const fsel = h('select', { title: 'Soubor', style: { maxWidth: '320px' }, onchange: (ev) => { setPref('validation.file', ev.target.value); load(true); } }, h('option', { value: '' }, 'Všechny soubory'), files.map((f) => h('option', { value: f.name }, f.name)));
  fsel.value = v.file || '';
  const search = h('input', { type: 'search', class: 'search', id: 'search', placeholder: 'Hledat ve zprávách a překladu… (Ctrl+F)', value: v.q || '', oninput: (ev) => { setPref('validation.q', ev.target.value); clearTimeout(S.valTimer); S.valTimer = setTimeout(() => load(true), 250); } });
  const info = h('label', { class: 'check', title: 'Například jiný počet pauz {w} / {p}' }, h('input', { type: 'checkbox', checked: !!settings.validation.show_info, onchange: async (ev) => { try { await post('settings', { validation: { show_info: ev.target.checked } }); load(true); } catch (e) { fail(e); } } }), 'Zobrazit i drobnosti');
  const ignBtn = h('button', { class: 'btn small', title: 'Nálezy, které jsi u některých řádků nechal ignorovat' });
  const paintIgnBtn = () => { const n = S.overview?.validation?.ignored || 0; const on = pref('validation.ignored', 'hide') === 'only'; ignBtn.textContent = on ? '← Zpět na nálezy' : `Ignorované (${n})`; ignBtn.classList.toggle('primary', on); };
  ignBtn.onclick = async () => { setPref('validation.ignored', pref('validation.ignored', 'hide') === 'only' ? 'hide' : 'only'); setPref('validation.consistency', false); paintIgnBtn(); paintConsBtn(); load(true); };
  const consBtn = h('button', { class: 'btn small', title: 'Stejný anglický řádek přeložený různě' });
  const consOn = () => !!pref('validation.consistency', false);
  const special = () => consOn() || pref('validation.ignored', 'hide') === 'only';
  const paintConsBtn = () => { consBtn.textContent = consOn() ? '← Zpět na nálezy' : 'Rozdílné překlady'; consBtn.classList.toggle('primary', consOn()); };
  consBtn.onclick = () => { setPref('validation.consistency', !consOn()); setPref('validation.ignored', 'hide'); paintIgnBtn(); paintConsBtn(); load(true); };
  const undoFix = h('button', { class: 'btn small', style: { display: 'none' } });
  async function loadLast() {
    try {
      const r = await get('fix/last');
      undoFix.style.display = r.last ? '' : 'none';
      if (r.last) { undoFix.textContent = `↶ Vrátit: ${r.last.label || 'poslední změnu'}`; undoFix.title = `Provedeno ${r.last.time.replace('T', ' ')}. Soubory se vrátí ze zálohy, ale jen když se od opravy neměnily.`; }
    } catch { undoFix.style.display = 'none'; }
  }
  undoFix.onclick = async () => {
    if (!await confirmDialog('Vrátit poslední změnu souboru?', 'Soubory změněné poslední změnou (oprava mluvčích nebo úprava textu) se vrátí do stavu před ní, ze zálohy. Pokud se od té doby změnily, vrácení se odmítne.', 'Vrátit změnu')) return;
    try { const r = await post('fix/undo'); toast(`Vráceno: ${r.label || 'poslední změna'} (${r.lines} řádků).`); S.files = null; await refreshHeader(); load(true); } catch (e) { fail(e); }
  };
  const fixAll = h('button', { class: 'btn small', title: 'Bezpečné opravy: mluvčí / atributy podle originálu, dvojité mezery, překlepy. Ukáže náhled, kde si každý řádek zaškrtneš.', onclick: () => fixDialog({ file: pref('validation.file', '') }, () => load(true)) }, 'Opravit…');
  const pillsBox = h('div', { class: 'frow pills', role: 'group', 'aria-label': 'Závažnost' }), chipsBox = h('div', { class: 'frow fchips' });
  function resetFilters() {
    for (const k of ['file', 'category', 'q', 'severity']) setPref('validation.' + k, '');
    search.value = ''; fsel.value = ''; cat.value = '';
    load(true);
  }
  function paintFilters() {
    const ignoredMode = special();
    const sc = S.val.sevCounts;
    const showInfo = !!settings.validation.show_info;
    const counts = sc ? { '': sc.error + sc.warning + (showInfo ? sc.info : 0), error: sc.error, warning: sc.warning, info: sc.info } : null;
    pillsBox.replaceChildren(...(ignoredMode ? [] : pillRow(SEV_OPTS, pref('validation.severity', ''), counts, (k) => { setPref('validation.severity', k); load(true); })));
    const active = [];
    const lab = (list, k) => (list.find(([x]) => x === k) || [k, k])[1];
    if (pref('validation.file', '')) active.push(['Soubor: ' + pref('validation.file', '').split(/[\\/]/).pop(), () => { setPref('validation.file', ''); fsel.value = ''; load(true); }]);
    if (pref('validation.category', '')) active.push(['Druh: ' + lab(CAT_OPTS, pref('validation.category', '')), () => { setPref('validation.category', ''); cat.value = ''; load(true); }]);
    if (pref('validation.severity', '')) active.push(['Závažnost: ' + lab(SEV_OPTS, pref('validation.severity', '')), () => { setPref('validation.severity', ''); load(true); }]);
    if (pref('validation.q', '')) active.push([`Hledání: „${pref('validation.q', '')}“`, () => { setPref('validation.q', ''); search.value = ''; load(true); }]);
    chipsBox.replaceChildren(...activeChips(active, resetFilters));
  }
  root.append(h('div', { class: 'filterbar' },
      h('div', { class: 'frow' }, search, filterGroup('Soubor', fsel), filterGroup('Druh', cat), info, h('span', { class: 'spacer' }), consBtn, ignBtn, undoFix, fixAll),
      h('div', { class: 'frow' }, pillsBox, h('span', { class: 'spacer' }), counter), chipsBox),
    h('p', { class: 'muted' }, 'Jeden řádek překladu = jedna položka se všemi nálezy pod sebou. Kontrola nic nepřepisuje sama; jen tlačítko ', h('b', null, 'Opravit'), ' u chyby mluvčího / atributů po tvém potvrzení zapíše opravu podle originálu do souboru (se zálohou). ', h('b', null, 'Chyba'), ' = Ren\'Py by pravděpodobně spadl nebo je rozbitá struktura skriptu. ', h('b', null, 'Varování'), ' = podezřelé, ale může být záměr (např. češtině chybí značka, text je výrazně delší). Porovnává se vždy s originálem, ne s pevnými pravidly.'), list);
  S.val.items = [];
  async function loadConsistency() {
    list.replaceChildren(loading());
    try {
      const r = await get('consistency');
      const hidden = new Set(pref('consistency.hidden', []));
      const showHidden = !!pref('consistency.showHidden', false);
      const groups = r.groups.filter((g) => showHidden || !hidden.has(g.key));
      counter.textContent = `${fmtN(groups.length)} ${plural(groups.length, 'originál', 'originály', 'originálů')} s víc překlady (${fmtN(r.lines)} řádků celkem)`;
      paintFilters();
      const note = h('div', { class: 'notice' }, 'Stejný anglický řádek přeložený různě. Někdy je to správně (jiný mluvčí, rod, kontext), proto se nic nesjednocuje samo: u varianty, kterou chceš všude, klikni ',
        h('b', null, 'Použít všude'), ' (ukáže se potvrzení, jde vrátit). ', h('b', null, 'Nechat jak je'), ' skupinu schová. ',
        h('label', { class: 'check', style: { marginLeft: '8px' } }, h('input', { type: 'checkbox', checked: showHidden, onchange: (e) => { setPref('consistency.showHidden', e.target.checked); loadConsistency(); } }), ` Zobrazit i skryté (${hidden.size})`));
      if (!groups.length) return list.replaceChildren(note, empty('Vše je jednotné', 'Žádný opakovaný originál nemá víc různých překladů.'));
      const t = buildTable({ key: 'consistency', cols: [{ k: 'src', w: 300, label: 'Originál' }, { k: 'var', w: 900, label: 'Varianty překladu' }, { k: 'act', w: 140, label: '', resize: false }] });
      for (const g of groups) {
        const variants = g.variants.map((v) => h('div', { class: 'variant' },
          h('div', { class: 'row' }, h('span', { class: 'chip none' }, `×${v.count}`), h('span', { class: 'txt grow' }, fmtText(v.target)),
            h('button', { class: 'btn small', title: 'Změní ostatní varianty na tuhle', onclick: async () => {
              const others = g.total - v.count;
              if (!await confirmDialog('Sjednotit překlad?', `Všech ${g.total} řádků s originálem „${g.source}“ dostane překlad „${v.target}“ (změní se ${others} ${plural(others, 'řádek', 'řádky', 'řádků')}). Před zápisem se vytvoří záloha, jde to vrátit.`, 'Použít všude')) return;
              try { const res = await post('consistency/unify', { key: g.key, target: v.target }); toast(`Sjednoceno: ${res.changed} řádků. Zpět: „Vrátit poslední změnu souboru“.`); S.files = null; await refreshHeader(); loadConsistency(); } catch (e) { fail(e); }
            } }, 'Použít všude')),
          h('div', { class: 'vlines' }, v.lines.slice(0, 6).map((l) => h('a', { href: '#', class: 'mono', title: l.who ? `mluvčí: ${l.who}` : '', onclick: (ev) => { ev.preventDefault(); go('entries', { file: l.file, line: l.line, status: 'all' }); } }, `${l.file.split(/[\\/]/).pop()}:${l.line}${l.who ? ' (' + l.who.split(' ')[0] + ')' : ''}`)), v.lines.length > 6 ? ` … +${v.lines.length - 6}` : '')));
        t.tbody.append(h('tr', null, h('td', { class: 'txt' }, fmtText(g.source), h('div', { class: 'muted' }, `${g.total}× celkem`)), h('td', null, ...variants),
          h('td', null, h('button', { class: 'btn small ghost', title: 'Tahle skupina je v pořádku, schovat ji ze seznamu', onclick: () => { const hs = new Set(pref('consistency.hidden', [])); hs.has(g.key) ? hs.delete(g.key) : hs.add(g.key); setPref('consistency.hidden', [...hs]); loadConsistency(); } }, hidden.has(g.key) ? 'Zase hlídat' : 'Nechat jak je'))));
      }
      list.replaceChildren(note, h('div', { class: 'tablewrap' }, t.table));
    } catch (e) { list.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
  }
  async function loadIgnored() {
    list.replaceChildren(loading());
    try {
      const r = await get('ignore/list');
      counter.textContent = `${fmtN(r.items.length)} ${plural(r.items.length, 'ignorovaný nález', 'ignorované nálezy', 'ignorovaných nálezů')}`;
      paintFilters();
      if (!r.items.length) return list.replaceChildren(empty('Nic neignoruješ', 'U nálezů v seznamu Kontrola je tlačítko Ignorovat. Ignorované se objeví tady.'));
      const t = buildTable({ key: 'ignored', cols: [{ k: 'st', w: 130, label: 'Stav' }, { k: 'loc', w: 280, label: 'Soubor : řádek' }, { k: 'msg', w: 380, label: 'Nález' }, { k: 'note', w: 260, label: 'Poznámka' }, { k: 'tgt', w: 320, label: 'Překlad' }, { k: 'act', w: 170, label: '', resize: false }] });
      for (const it of r.items) {
        const [lab, cls, tip] = IGN_STATE[it.state];
        t.tbody.append(h('tr', null, h('td', { title: tip }, chip(cls, lab)), h('td', null, fname(it.file), h('span', { class: 'mono muted' }, it.line ? `řádek ${it.line}` : '')),
          h('td', null, it.message || h('span', { class: 'muted' }, it.code)), h('td', null, it.note || h('span', { class: 'muted' }, '—'), it.date ? h('div', { class: 'muted', style: { fontSize: '11.5px' } }, it.date) : null),
          h('td', { class: 'txt' }, fmtText(it.target)), h('td', null,
            it.line ? h('button', { class: 'btn small', onclick: () => go('entries', { file: it.file, line: it.line, status: 'all' }) }, 'Zobrazit') : null, ' ',
            h('button', { class: 'btn small', title: 'Nález se znovu začne hlásit', onclick: () => unignore([it], () => { loadIgnored(); }) }, 'Přestat ignorovat'))));
      }
      list.replaceChildren(h('div', { class: 'tablewrap' }, t.table));
    } catch (e) { list.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
  }
  async function load(reset) {
    paintIgnBtn(); paintConsBtn();
    if (consOn()) return loadConsistency();
    if (pref('validation.ignored', 'hide') === 'only') return loadIgnored();
    if (reset) { S.val.items = []; list.replaceChildren(loading()); loadLast(); }
    try {
      const q = { severity: pref('validation.severity', ''), category: pref('validation.category', ''), file: pref('validation.file', ''), q: pref('validation.q', ''), offset: S.val.items.length, limit: 200, group: 'line' };
      const r = await get('validation', q);
      S.val.items.push(...r.items); S.val.total = r.total; S.val.sevCounts = r.sev_counts;
      const nf = r.findings ?? r.total;
      counter.textContent = `${fmtN(r.total)} ${plural(r.total, 'řádek', 'řádky', 'řádků')} s nálezem · ${fmtN(nf)} ${plural(nf, 'nález', 'nálezy', 'nálezů')}` + (S.val.items.length < r.total ? ` (zobrazeno ${fmtN(S.val.items.length)})` : '');
      paintFilters();
      paintList();
    } catch (e) { list.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
  }
  function findingRow(g, x) {
    return h('div', { class: 'finding ' + x.severity },
      chip(x.severity, SEV_LABEL[x.severity]), h('span', { class: 'fmsg' }, x.message),
      h('span', { class: 'fact' },
        x.extra?.fixable ? h('button', { class: 'btn small primary', title: x.extra.kind === 'speaker' ? `Zkopíruje mluvčího a atributy z originálu („${g.src_who}“)` : 'Ukáže náhled opravy', onclick: () => fixDialog({ items: [{ file: g.file, line: g.line }], kinds: [x.extra.kind || 'speaker'] }, () => load(true)) }, 'Opravit') : null,
        g.line && x.code !== 'duplicate-id' ? h('button', { class: 'btn small ghost', title: 'Schová tenhle nález u tohoto řádku (jde vrátit)', onclick: () => ignoreDialog([{ file: g.file, line: g.line, code: x.code, severity: x.severity, message: x.message }], () => load(true)) }, 'Ignorovat…') : null));
  }
  function paintList() {
    if (!S.val.items.length) return list.replaceChildren(empty('Žádné nálezy', pref('validation.q', '') || pref('validation.file', '') || pref('validation.category', '') || pref('validation.severity', '') ? 'Pro tyhle filtry nebyl nalezen žádný problém. Zkus filtry zrušit.' : 'Překlad nemá žádný problém.'));
    const t = buildTable({ key: 'validation2', cols: [{ k: 'sev', w: 110, label: 'Závažnost' }, { k: 'loc', w: 220, label: 'Soubor : řádek' }, { k: 'msg', w: 560, label: 'Nálezy na řádku' }, { k: 'src', w: 300, label: 'Originál' }, { k: 'tgt', w: 300, label: 'Překlad' }, { k: 'act', w: 150, label: '', resize: false }] });
    for (const g of S.val.items) {
      const ignorable = g.issues.filter((x) => g.line && x.code !== 'duplicate-id');
      t.tbody.append(h('tr', { class: g.severity === 'error' ? 'has-error' : '' },
        h('td', null, chip(g.severity, SEV_LABEL[g.severity]), g.issues.length > 1 ? h('div', { class: 'muted', style: { fontSize: '11.5px', marginTop: '3px' } }, `${g.issues.length} nálezů`) : null),
        h('td', null, fname(g.file), h('span', { class: 'mono muted' }, `řádek ${g.line}`)),
        h('td', null, ...g.issues.map((x) => findingRow(g, x)),
          ignorable.length > 1 ? h('div', { class: 'fall' }, h('button', { class: 'btn small ghost', title: 'Schová všechny nálezy tohoto řádku najednou', onclick: () => ignoreDialog(ignorable.map((x) => ({ file: g.file, line: g.line, code: x.code, severity: x.severity, message: x.message })), () => load(true)) }, `Ignorovat všech ${ignorable.length}…`)) : null),
        h('td', { class: 'txt' }, fmtText(g.source)), h('td', { class: 'txt' }, fmtText(g.target)),
        h('td', null, h('button', { class: 'btn small', title: 'Zobrazit v seznamu řádků (tam jde text rovnou upravit)', onclick: () => go('entries', { file: g.file, line: g.line, status: 'all' }) }, 'Zobrazit'), ' ',
          h('button', { class: 'btn small ghost', title: 'Otevřít v externím editoru', onclick: () => openEditor(g.file, g.line) }, 'Editor'))));
    }
    list.replaceChildren(h('div', { class: 'tablewrap' }, t.table), S.val.items.length < S.val.total ? h('div', { class: 'more' }, h('button', { class: 'btn', onclick: () => load(false) }, `Načíst další (${fmtN(S.val.items.length)} z ${fmtN(S.val.total)} řádků)`)) : null);
  }
  root.afterMount = () => load(true);
  return root;
}

/* ================================================================ GLOSSARY */
async function viewGlossary() {
  let data = await get('glossary');
  S.gl = data.names;
  const f = pref('glossary', {});
  const root = h('div');
  const body = h('div');
  const counter = h('span', { class: 'muted' });
  const search = h('input', { type: 'search', class: 'search', id: 'search', placeholder: 'Hledat kód nebo jméno… (Ctrl+F)', value: f.q || '',
    oninput: (ev) => { setPref('glossary.q', ev.target.value); draw(); } });
  const seg = h('div', { class: 'seg' }, [['all', 'Vše'], ['unnamed', 'Bez jména'], ['speaker', 'Mluvčí'], ['term', 'Termíny']].map(([k, l]) =>
    h('button', { class: (f.filter || 'all') === k ? 'on' : '', onclick: (ev) => { setPref('glossary.filter', k); seg.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === ev.currentTarget)); draw(); } }, l)));
  root.append(
    h('p', { class: 'muted' }, 'Slovník jmen. Mluvčí v souborech jsou jen zkratky (mc, de, ji…); zde jim přiřadíš celé jméno. ',
      'Zobrazení v aplikaci (Řádky, detail, okolí řádku) přepínáš vpravo: kód / celé jméno / obojí. Jméno se zapisuje automaticky po opuštění pole. Zkratky se hledají v souborech samy – nic se nevymýšlí.'),
    h('div', { class: 'toolbar filterbar' }, filterGroup('Typ', seg), search, speakerModeSelect(() => toast('Zobrazení mluvčích změněno.', 'ok', 1500)),
      h('button', { class: 'btn', onclick: () => addDialog() }, '+ Přidat položku (termín / jméno)'),
      h('button', { class: 'btn', title: 'Načte jména postav z characters.rpy hry', onclick: () => importDialog() }, 'Importovat z characters.rpy…'), h('span', { class: 'spacer' }), counter), body);

  async function save(item, quiet) {
    try { data = await post('glossary/set', { items: [item] }); S.gl = data.names; if (!quiet) toast('Uloženo ✓', 'ok', 1500); counter.textContent = stats(); }
    catch (e) { fail(e); }
  }
  const stats = () => `${data.items.length} položek · bez jména: ${data.unnamed}`;
  function draw() {
    const q = (pref('glossary.q', '') || '').toLowerCase(), flt = pref('glossary.filter', 'all');
    const rows = data.items.filter((i) => (!q || i.code.toLowerCase().includes(q) || i.name.toLowerCase().includes(q) || i.note.toLowerCase().includes(q)) &&
      (flt === 'all' || (flt === 'unnamed' && i.type === 'speaker' && i.in_project && !i.name) || (flt === 'speaker' && i.type === 'speaker') || (flt === 'term' && i.type === 'term')));
    counter.textContent = stats();
    if (!rows.length) return body.replaceChildren(empty('Nic k zobrazení', flt === 'all' ? 'V projektu nebyli nalezeni žádní mluvčí.' : 'Změň filtr nebo hledaný text.'));
    const t = buildTable({ key: 'glossary', cols: [{ k: 'type', w: 100, label: 'Typ' }, { k: 'code', w: 150, label: 'Kód / termín' }, { k: 'name', w: 280, label: 'Celé jméno / překlad' },
      { k: 'note', w: 260, label: 'Poznámka' }, { k: 'count', w: 80, label: 'Řádků' }, { k: 'ex', w: 340, label: 'Příklad' }, { k: 'act', w: 190, label: '', resize: false }] });
    for (const it of rows) {
      const name = h('input', { type: 'text', value: it.name, placeholder: it.type === 'speaker' ? 'např. celé jméno postavy' : 'překlad / jméno', style: { width: '100%' },
        onchange: (ev) => { it.name = ev.target.value.trim(); save({ code: it.code, name: it.name, type: it.type, note: it.note }); } });
      const note = h('input', { type: 'text', value: it.note, style: { width: '100%' },
        onchange: (ev) => { it.note = ev.target.value.trim(); save({ code: it.code, name: it.name, type: it.type, note: it.note }); } });
      t.tbody.append(h('tr', null, h('td', null, chip(it.type === 'speaker' ? 'info' : 'none', it.type === 'speaker' ? 'mluvčí' : 'termín')),
        h('td', { class: 'mono' }, it.code), h('td', null, name), h('td', null, note), h('td', { class: 'num' }, it.count || '–'),
        h('td', { class: 'txt muted' }, it.example), h('td', null,
          it.type === 'term' ? h('button', { class: 'btn small', title: 'Kde se termín v originále vyskytuje a jestli je přeložený podle slovníku', onclick: () => occurrencesDialog(it.code) }, 'Výskyty') : null, ' ',
          it.count ? h('button', { class: 'btn small', title: 'Zobrazit řádky tohoto mluvčího', onclick: () => go('entries', { file: '', q: it.code, status: 'all' }) }, 'Řádky') : null, ' ',
          (it.name || it.note) ? h('button', { class: 'btn small ghost', title: 'Smazat záznam ze slovníku', onclick: async () => {
            try { data = await post('glossary/delete', { codes: [it.code] }); S.gl = data.names; draw(); toast('Záznam smazán. Zpět: Ctrl+Z'); } catch (e) { fail(e); } } }, 'Smazat') : null)));
    }
    body.replaceChildren(h('div', { class: 'tablewrap' }, t.table));
  }
  async function importDialog() {
    let pv;
    try { pv = await post('glossary/import-preview', { path: '' }); } catch (e) { return fail(e); }
    const pathIn = h('input', { type: 'text', value: pv.path, placeholder: 'složka hry nebo soubor characters.rpy', style: { flex: 1 } });
    const holder = h('div');
    let rows = [];
    const apply = h('button', { class: 'btn primary', disabled: true }, 'Zapsat do slovníku');
    const upd = () => { const n = rows.filter((r) => r.on).length; apply.disabled = !n; apply.textContent = n ? `Zapsat do slovníku (${n})` : 'Zapsat do slovníku'; };
    const STATE = { new: ['Nové', 'tr'], same: ['Shodné', 'none'], conflict: ['Jiné než ve slovníku', 'error'], dynamic: ['Zadává hráč', 'none'] };
    function paint(data) {
      rows = data.items.map((i) => ({ ...i, on: i.state === 'new' }));
      if (!rows.length) { holder.replaceChildren(empty('Nic k importu', data.message || 'V souboru nejsou žádné řádky define … = Character("…").')); return upd(); }
      const t = buildTable({ key: 'glimport', cols: [{ k: 'on', w: 44, label: '', resize: false }, { k: 'code', w: 110, label: 'Kód' }, { k: 'name', w: 240, label: 'Jméno v characters.rpy' },
        { k: 'cur', w: 200, label: 'Dosud ve slovníku' }, { k: 'src', w: 230, label: 'Soubor' }, { k: 'st', w: 190, label: 'Stav' }] });
      for (const r of rows) {
        t.tbody.append(h('tr', null, h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: r.on, disabled: r.state === 'dynamic' || r.state === 'same',
          title: r.state === 'conflict' ? 'Přepíše jméno, které máš ve slovníku' : '', onchange: (e) => { r.on = e.target.checked; upd(); } })),
          h('td', { class: 'mono' }, r.code), h('td', null, r.name || h('span', { class: 'muted' }, r.note)), h('td', { class: 'muted' }, r.current || '–'), h('td', { class: 'mono muted', style: { fontSize: '12px' } }, r.source),
          h('td', null, chip(STATE[r.state][1], STATE[r.state][0]), r.in_project ? null : h('span', { class: 'muted' }, '  (není v překladu)'))));
      }
      holder.replaceChildren(
        h('div', { class: 'muted', style: { marginBottom: '6px' } }, `Načtené soubory (${data.files.length}): `, h('span', { class: 'mono' }, data.files.map((f) => f.split(/[\\/]/).slice(-3).join('/')).join('  ·  '))),
        data.duplicates?.length ? h('div', { class: 'notice warn' }, 'Víckrát definované kódy (Ren\'Py použije poslední definici): ', h('span', { class: 'mono' }, data.duplicates.map((d) => `${d.code}: ${d.names.join(' → ')}`).join(';  '))) : null,
        data.missing?.length ? h('div', { class: 'notice warn' }, `V překladu je ${data.missing.length} kódů mluvčích, které soubory characters*.rpy nedefinují (mohou být definované jinde, nebo jde o překlep): `, h('span', { class: 'mono' }, data.missing.slice(0, 25).join(', ') + (data.missing.length > 25 ? ' …' : ''))) : null,
        h('div', { class: 'tablewrap', style: { maxHeight: '48vh' } }, t.table));
      upd();
    }
    const load = async () => { try { paint(await post('glossary/import-preview', { path: pathIn.value })); } catch (e) { fail(e); } };
    paint(pv);
    apply.onclick = async () => {
      try {
        data = await post('glossary/import-apply', { items: rows.filter((r) => r.on).map((r) => ({ code: r.code, name: r.name })) });
        S.gl = data.names; draw(); toast('Jména importována ✓  (Ctrl+Z vrátí)');
        $('#dlg').close();
      } catch (e) { fail(e); }
    };
    dialog({ title: 'Import jmen z characters.rpy', body: h('div', null,
      h('p', { class: 'muted' }, 'Soubory hry (characters.rpy i season2/scripts/characters_season2.rpy…) se jen čtou. Zaškrtnuté řádky se zapíšou do slovníku; jména, která už ve slovníku máš a liší se, se přepíšou jen když je sám zaškrtneš.'),
      h('div', { class: 'row nowrap' }, pathIn, h('button', { class: 'btn', onclick: load }, 'Načíst')), holder),
      buttons: [{ label: 'Zavřít' }, { node: apply }] });
  }
  function addDialog() {
    const code = h('input', { type: 'text', placeholder: 'kód nebo termín (např. de, Delta Iota Kappa)' });
    const name = h('input', { type: 'text', placeholder: 'celé jméno / překlad' });
    const type = h('select', null, h('option', { value: 'speaker' }, 'Mluvčí (zkratka postavy)'), h('option', { value: 'term' }, 'Termín / jméno / místo'));
    const note = h('input', { type: 'text', placeholder: 'poznámka (volitelné)' });
    dialog({ title: 'Nová položka slovníku', narrow: true, body: h('div', { class: 'form', style: { gridTemplateColumns: '120px 1fr' } },
      h('label', null, 'Typ'), type, h('label', null, 'Kód / termín'), code, h('label', null, 'Jméno'), name, h('label', null, 'Poznámka'), note),
      buttons: [{ label: 'Zrušit' }, { label: 'Přidat', kind: 'primary', onclick: async () => {
        if (!code.value.trim()) { toast('Vyplň kód nebo termín.', 'bad'); return false; }
        await save({ code: code.value, name: name.value, type: type.value, note: note.value }); draw();
      } }] });
  }
  root.afterMount = draw;
  return root;
}

/* ================================================================ PUBLISH */
async function viewPublish() {
  const settings = await get('settings');
  const root = h('div');
  const out = h('div');
  root.append(h('div', { class: 'notice' }, 'Nic se nepošle na GitHub ani na web, dokud v potvrzovacím okně sám nepotvrdíš „Publikovat“. ',
    'Generování dat a publikování jsou dva oddělené kroky.'),
    h('div', { class: 'panel', style: { marginBottom: '12px' } }, h('h3', null, '1. Vygenerovat a zkontrolovat data pro web'),
      h('div', { class: 'panel-body' }, h('p', { class: 'muted' }, 'Vytvoří ', h('span', { class: 'mono' }, 'progress.json'), ' ve složce ', h('span', { class: 'mono' }, '_progress_data'),
        ' a zkontroluje ho (součty epizod, rozsah procent, žádné názvy souborů). Je to stejný soubor, ze kterého čerpá web.'),
        h('button', { class: 'btn primary', onclick: preview }, 'Vygenerovat náhled'), out)),
    h('div', { class: 'panel' }, h('h3', null, '2. Publikovat na web'),
      h('div', { class: 'panel-body' },
        settings.web.repo ? h('div', null, h('dl', { class: 'kv' }, h('dt', null, 'Repozitář'), h('dd', null, settings.web.repo), h('dt', null, 'Soubor v repozitáři'), h('dd', null, settings.web.path)),
          h('p', { class: 'muted' }, 'Zobrazí se náhled: repozitář, větev, co se změní, přesné příkazy gitu a varování (např. že push do větve main nasadí web na ostro).'),
          h('button', { class: 'btn', onclick: publishPlan }, 'Připravit publikování…'))
          : h('div', null, h('p', null, 'Propojení s webem zatím není nastavené.'), h('button', { class: 'btn', onclick: () => go('settings') }, 'Otevřít Nastavení')))));
  async function preview() {
    out.replaceChildren(loading('Generuji…'));
    try {
      const r = await get('export/preview');
      const d = r.data;
      out.replaceChildren(h('div', { style: { marginTop: '12px' } },
        r.problems.length ? h('div', { class: 'notice bad' }, h('b', null, 'Kontrola neprošla: '), r.problems.join(' | ')) : h('div', { class: 'notice', style: { background: 'var(--good-bg)' } }, '✓ Data prošla kontrolou.'),
        h('dl', { class: 'kv' }, h('dt', null, 'Celkem'), h('dd', null, `${fmtPct(d.translation.percent)} (${fmtN(d.translation.done)} / ${fmtN(d.translation.total)})`),
          h('dt', null, 'Korektura'), h('dd', null, fmtPct(d.proofreading.percent)), h('dt', null, 'Soubory'), h('dd', null, d.files.total),
          h('dt', null, 'Odhad dokončení'), h('dd', null, d.estimate.status === 'ok' ? dateCz(d.estimate.eta) : 'zatím nelze (málo dat)'),
          h('dt', null, 'Místní soubor'), h('dd', { class: 'mono' }, r.path)),
        h('div', { class: 'tablewrap', style: { marginTop: '10px' } }, h('table', { class: 'data' }, h('colgroup', null, [160, 130, 160, 160, 110].map((w) => h('col', { style: { width: w + 'px' } }))),
          h('thead', null, h('tr', null, ['Sezóna / epizoda', 'Stav', 'Řádky', 'Procenta', 'Soubory'].map((t) => h('th', null, t)))),
          h('tbody', null, d.seasons.map((s) => s.status === 'planned'
            ? h('tr', null, h('td', null, `Sezóna ${s.n}`), h('td', null, chip('planned', 'Plánováno')), h('td', { colspan: 3, class: 'muted' }, 'bez čísel, mimo výpočty'))
            : [h('tr', null, h('td', null, h('b', null, `Sezóna ${s.n}`)), h('td'), h('td', { class: 'num' }, `${fmtN(s.translation.done)} / ${fmtN(s.translation.total)}`), h('td', { class: 'num' }, fmtPct(s.translation.percent)), h('td', { class: 'num' }, s.files)),
              ...d.episodes.filter((e) => e.season === s.n).map((e) => h('tr', null, h('td', null, `   Epizoda ${e.n}`), h('td', null, chip(e.status, STATUS_LABEL[e.status])), h('td', { class: 'num' }, `${fmtN(e.translation.done)} / ${fmtN(e.translation.total)}`), h('td', { class: 'num' }, fmtPct(e.translation.percent)), h('td', { class: 'num' }, e.files_total)))]))))));
    } catch (e) { out.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
  }
  async function publishPlan() {
    let info;
    try { info = await post('publish/plan'); } catch (e) { return fail(e); }
    const ack = h('input', { type: 'checkbox' });
    const go_ = h('button', { class: 'btn primary', disabled: true, onclick: async () => {
      go_.disabled = true; go_.textContent = 'Publikuji…';
      try {
        const r = await post('publish/confirm', { token: info.token, branch: info.will_clone ? '*clone*' : info.branch });
        toast(r.message, 'ok', 9000); closeFn();
      } catch (e) { fail(e); go_.disabled = false; go_.textContent = 'Publikovat'; }
      return false;
    } }, 'Publikovat');
    ack.addEventListener('change', () => { go_.disabled = !ack.checked || info.blockers.length > 0; });
    const closeFn = dialog({ title: 'Náhled publikování', body: h('div', null,
      info.blockers.map((b) => h('div', { class: 'notice bad' }, b)), info.warnings.map((w) => h('div', { class: 'notice warn' }, w)),
      h('dl', { class: 'kv' }, h('dt', null, 'Repozitář'), h('dd', null, info.repo_path), h('dt', null, 'Vzdálený'), h('dd', null, info.remote || info.url || '—'),
        h('dt', null, 'Větev'), h('dd', null, info.branch ? `${info.branch} → ${info.upstream || '(bez upstreamu)'}` : '(výchozí po naklonování)'),
        h('dt', null, 'Soubor'), h('dd', { class: 'mono' }, info.target),
        h('dt', null, 'Dosud na webu'), h('dd', null, info.current ? `překlad ${fmtPct(info.current.translation)}, aktualizováno ${info.current.updated || '?'}` : '—'),
        h('dt', null, 'Nově'), h('dd', null, info.new ? `překlad ${fmtPct(info.new.translation)}, korektura ${fmtPct(info.new.proofreading)}` : '—'),
        h('dt', null, 'Změní se'), h('dd', null, info.changed ? 'ano' : 'ne (jen čas)')),
      h('h4', { style: { marginTop: '10px' } }, 'Proběhnou tyto příkazy (jen s tímto jedním souborem)'),
      h('div', { class: 'textbox mono' }, info.commands.join('\n')),
      info.dirty.length ? h('div', { class: 'muted' }, `Jiné neuložené změny v repozitáři (nedotkne se jich): ${info.dirty.slice(0, 5).join(', ')}${info.dirty.length > 5 ? '…' : ''}`) : null,
      h('label', { class: 'check', style: { marginTop: '10px' } }, ack, info.warnings.some((w) => /main|master|ostro/.test(w)) ? 'Rozumím, že se data odešlou na GitHub a web se aktualizuje na ostro.' : 'Rozumím, že se data odešlou na GitHub.')),
      buttons: [{ label: 'Zrušit' }, { node: go_ }] });
  }
  return root;
}

/* ================================================================ SETTINGS */
async function viewSettings() {
  const s = await get('settings');
  const root = h('div', { style: { maxWidth: '900px' } });
  const val = (id) => $('#' + id);
  const field = (label, node, hint) => [h('label', { for: node.id }, label), node, hint ? h('div', { class: 'hint' }, hint) : null];
  const ln = s.validation.length;
  const tb = s.validation.textbox;
  const projectInput = h('input', { type: 'text', id: 'set_project', value: S.projectDir });
  root.append(
    h('fieldset', null, h('legend', null, 'Projekt'), h('div', { class: 'form' },
      ...field('Složka s překladem', h('div', { class: 'row nowrap' }, projectInput, h('button', { class: 'btn', onclick: pickProject }, 'Procházet…'), h('button', { class: 'btn', onclick: () => openProject(projectInput.value) }, 'Otevřít')),
        'Pamatuje se mezi spuštěními. Data (CSV, progress.json, zálohy) leží v podsložce _progress_data.'),
      ...field('Přeskočené soubory', h('input', { type: 'text', id: 'set_skip', value: s.skip_files.join(', ') }), 'Názvy souborů oddělené čárkou (ve všech podsložkách). Změna se projeví po „Obnovit soubory“.'))),
    h('fieldset', null, h('legend', null, 'Editor (otevření souboru na řádku)'), h('div', { class: 'form' },
      ...field('Editor', h('select', { id: 'set_editor', value: s.editor.preferred }, [['auto', 'Automaticky (VS Code, jinak Notepad++)'], ['vscode', 'Visual Studio Code'], ['notepadpp', 'Notepad++'], ['custom', 'Vlastní příkaz'], ['system', 'Výchozí program (bez skoku na řádek)']].map(([k, l]) => h('option', { value: k }, l)))),
      ...field('Vlastní příkaz', h('input', { type: 'text', id: 'set_custom', value: s.editor.custom, placeholder: '"C:\\Tools\\editor.exe" --line {line} {file}' }), 'Zástupné {file} a {line}. Spouští se bez shellu, takže cesty s mezerami a speciálními znaky jsou bezpečné.'))),
    h('fieldset', null, h('legend', null, 'Kontrola překladu'), h('div', { class: 'form' },
      ...field('Kontrola zapnutá', h('input', { type: 'checkbox', id: 'set_val', checked: s.validation.enabled })),
      ...field('Varování na délku textu', h('input', { type: 'checkbox', id: 'set_len', checked: ln.enabled }), 'Jen pomůcka při kontrole, nikdy chyba.'),
      ...field('Delší než (× originál)', h('input', { type: 'text', id: 'set_max', value: String(ln.max_ratio) }), 'Čeština bývá delší než angličtina, výchozí 2,2×.'),
      ...field('Kratší než (× originál)', h('input', { type: 'text', id: 'set_min', value: String(ln.min_ratio) }), 'Výchozí 0,45×.'),
      ...field('Nejmenší originál (znaků)', h('input', { type: 'text', id: 'set_minsrc', value: String(ln.min_source_chars) }), 'Kratší texty se na délku nekontrolují.'),
      ...field('Min. rozdíl – delší (znaků)', h('input', { type: 'text', id: 'set_extra', value: String(ln.min_extra_chars) })),
      ...field('Min. rozdíl – kratší (znaků)', h('input', { type: 'text', id: 'set_missing', value: String(ln.min_missing_chars) })),
      ...field('Hlídat překlepy', h('input', { type: 'checkbox', id: 'set_spell', checked: s.validation.spelling }), 'Chybějící diakritika a prohozená písmena podle slovníku z tvého vlastního překladu. Jen nápověda.'),
      ...field('Kontrola okna dialogu', h('input', { type: 'checkbox', id: 'set_tb', checked: tb.enabled }), 'Varuje, když se překlad nevejde do okna dialogu a originál se vešel.'),
      ...field('Znaků na řádek', h('input', { type: 'text', id: 'set_tbcpl', value: String(tb.chars_per_line) }), 'Výchozí 65 vychází z gui.rpy hry (šířka textu 1116 px, písmo 33 px).'),
      ...field('Nejvíc řádků v okně', h('input', { type: 'text', id: 'set_tblines', value: String(tb.max_lines) }), 'Výchozí 4.'))),
    h('fieldset', null, h('legend', null, 'Týdenní cíle'), h('div', { class: 'form' },
      ...field('Překlad (řádků týdně)', h('input', { type: 'text', id: 'set_goal_t', value: String(s.goals?.translate_per_week ?? 0) }), '0 = automaticky podle tvého tempa za poslední týdny (o 10 % víc).'),
      ...field('Korektura (řádků týdně)', h('input', { type: 'text', id: 'set_goal_p', value: String(s.goals?.proofread_per_week ?? 0) }), '0 = automaticky.'))),
    h('fieldset', null, h('legend', null, 'Web (publikování)'), h('div', { class: 'form' },
      ...field('Repozitář', h('input', { type: 'text', id: 'set_repo', value: s.web.repo, placeholder: 'Filiposakkq/Being-A-DIK-CZ' }), 'Složka s klonem, adresa nebo uživatel/repozitář. Přihlášení řeší tvůj git (Credential Manager) – žádné tokeny se tu neukládají.'),
      ...field('Soubor v repozitáři', h('input', { type: 'text', id: 'set_path', value: s.web.path }), 'Výchozí web/progress.json.'),
      ...field('Název hry na webu', h('input', { type: 'text', id: 'set_title', value: s.web.title })),
      s.web.migrated_from ? h('div', { class: 'hint' }, `Převzato z ${s.web.migrated_from}. Samostatný web.json už aplikace nepotřebuje.`) : null)),
    h('fieldset', null, h('legend', null, 'O aplikaci'), h('p', null, h('b', null, `BaDIK Translation Manager ${S.version || ''}`),
      ' – nástroj pro český překlad hry Being a DIK. Licence: viz soubor ', h('span', { class: 'mono' }, 'tools/translation-manager/LICENSE'),
      ' (osobní nekomerční použití; další šíření, úpravy a komerční použití jen s mým souhlasem).'),
      h('p', { class: 'notice' }, h('b', null, 'Rozsah nástroje: '), 'vzniká hlavně pro mě. Funguje jen pro Being a DIK (1. a 2. sezóna) a má pouze české rozhraní. ',
        'V plánu je nejdřív 3. sezóna, možná později přepracování pro víc Ren\'Py her a angličtinu (bez slibů a termínů).'),
      h('div', { class: 'row' }, ...[['kofi', 'Podpořit na Ko-fi'], ['github', 'GitHub'], ['repo', 'Repozitář překladu'], ['web', 'Web překladu']].map(([id, l]) =>
        h('button', { class: 'btn small', onclick: () => post('open-url', { id }).catch(fail) }, l)))),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: save }, 'Uložit nastavení'),
      h('span', { class: 'muted' }, 'Nastavení: ', h('span', { class: 'mono' }, 'config.json'), ' v %APPDATA%\\BaDIKTranslationManager')));
  async function save() {
    try {
      await post('settings', {
        skip_files: val('set_skip').value.split(',').map((x) => x.trim()).filter(Boolean),
        editor: { preferred: val('set_editor').value, custom: val('set_custom').value },
        validation: { enabled: val('set_val').checked, spelling: val('set_spell').checked,
          textbox: { enabled: val('set_tb').checked, chars_per_line: num(val('set_tbcpl').value), max_lines: num(val('set_tblines').value) }, length: { enabled: val('set_len').checked, max_ratio: num(val('set_max').value), min_ratio: num(val('set_min').value),
          min_source_chars: num(val('set_minsrc').value), min_extra_chars: num(val('set_extra').value), min_missing_chars: num(val('set_missing').value) } },
        goals: { translate_per_week: num(val('set_goal_t').value), proofread_per_week: num(val('set_goal_p').value) },
        web: { repo: val('set_repo').value, path: val('set_path').value, title: val('set_title').value },
      });
      toast('Nastavení uloženo ✓'); refreshHeader();
    } catch (e) { fail(e); }
  }
  const num = (v) => Number(String(v).replace(',', '.'));
  return root;
}

/* ================================================================ keyboard */
function helpDialog() {
  const rows = [['Ctrl+F nebo /', 'Hledat v aktuální sekci'], ['↑ ↓  (J K)', 'Předchozí / další řádek'], ['PgUp PgDn', 'Skok o stránku'], ['A', 'Schválit / zrušit schválení řádku'], ['Shift+A', 'Schválit všechny shodné… (s náhledem)'], ['P', 'Korektura: zkontrolováno (a skok na další)'], ['F', 'Korektura: označit k opravě + poznámka'], ['Shift+P', 'Korektura: zkontrolovat vše až po tento řádek'], ['Shift+U', 'Korektura: zrušit zkontrolování až po tento řádek'],
    ['E nebo Enter', 'Otevřít řádek v externím editoru'], ['Ctrl+Enter', 'V poli překladu: uložit do souboru a přejít na další nepřeložený řádek'], ['Esc', 'V poli překladu: zahodit změny'], ['Ctrl+Z', 'Vrátit poslední změnu (mimo textová pole)'], ['Ctrl+Z', 'Vrátit poslední změnu (mimo textová pole)'], ['F5 nebo Ctrl+R', 'Obnovit soubory'], ['Alt+1 … Alt+7', 'Přepnout sekci'], ['?', 'Tato nápověda']];
  dialog({ title: 'Klávesové zkratky', narrow: true, body: h('dl', { class: 'kv' }, rows.flatMap(([k, d]) => [h('dt', null, h('kbd', null, k)), h('dd', { style: { textAlign: 'left' } }, d)])), buttons: [{ label: 'Zavřít', kind: 'primary' }] });
}
document.addEventListener('keydown', (e) => {
  if (dialogOpen()) return;
  const typing = isTyping(e.target);
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === 'f') { const s = $('#search'); if (s) { e.preventDefault(); s.focus(); s.select(); } return; }
  if (e.key === 'F5' || (mod && e.key.toLowerCase() === 'r')) { e.preventDefault(); doRefresh(); return; }
  if (e.altKey && /^[1-7]$/.test(e.key)) { e.preventDefault(); go(TABS[+e.key - 1][0]); return; }
  if (e.target.closest?.('.splitter')) return;      // the divider uses the arrow keys itself
  if (typing) { if (e.key === 'Escape') e.target.blur(); return; }
  if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); doUndo(); return; }
  if (e.key === '?') { helpDialog(); return; }
  if (e.key === '/') { const s = $('#search'); if (s) { e.preventDefault(); s.focus(); } return; }
  if (S.view !== 'entries' || !S.ent.api || mod || e.altKey) return;
  const api = S.ent.api, i = S.ent.sel, last = S.ent.items.length - 1;
  const move = (n) => { e.preventDefault(); api.select(Math.max(0, Math.min(last, (i < 0 ? 0 : i + n)))); };
  switch (e.key) {
    case 'ArrowDown': case 'j': move(1); break;
    case 'ArrowUp': case 'k': move(-1); break;
    case 'PageDown': move(15); break;
    case 'PageUp': move(-15); break;
    case 'Home': e.preventDefault(); api.select(0); break;
    case 'End': e.preventDefault(); api.select(last); break;
    case 'a': e.preventDefault(); api.toggleApprove(); break;
    case 'A': e.preventDefault(); api.globalApprove(); break;
    case 'p': e.preventDefault(); api.toggleProof(); break;
    case 'P': e.preventDefault(); api.proofUpto(); break;
    case 'U': e.preventDefault(); api.unproofUpto(); break;
    case 'f': e.preventDefault(); api.flagFix(); break;
    case 'e': case 'Enter': { const it = S.ent.items[i]; if (it) { e.preventDefault(); openEditor(it.file, it.line); } break; }
    default:
  }
});

/* ================================================================ boot */
$('#refreshBtn').addEventListener('click', () => doRefresh());
$('#undoBtn').addEventListener('click', doUndo);
$('#themeBtn').addEventListener('click', cycleTheme);
$('#densityBtn').addEventListener('click', toggleDensity);
$('#changeProject').addEventListener('click', pickProject);
document.querySelectorAll('[data-link]').forEach((b) => b.addEventListener('click', () => post('open-url', { id: b.dataset.link }).catch(fail)));

if (new URLSearchParams(location.search).has('selftest')) {      // UI self-test (see tests/ui)
  const st = document.createElement('script'); st.src = '/selftest.js'; document.body.append(st);
}

(async function boot() {
  renderTabs();
  try {
    const st = await get('state');
    S.ready = st.ready; S.version = st.version; S.prefs = st.prefs || {};
    applyTheme(); applyDensity(); $('#brandText').textContent = `BaDIK Translation Manager ${S.version || ''}`.trim(); S.notices = st.notices || []; S.projectDir = st.project_dir || '';
    if (st.config_error) S.notices.push(st.config_error);
    S.view = pref('view', 'overview');
    if (!TABS.some(([k]) => k === S.view)) S.view = 'overview';
    await refreshHeader();
    if (S.ready) await loadGlossary();
    render();
    if (S.ready) S.lastRefresh = new Date().toLocaleTimeString('cs-CZ');
  } catch (e) { $('#view').replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
  let fails = 0;
  setInterval(() => get('ping').then(() => { fails = 0; }).catch(() => {
    if (++fails >= 3) document.body.replaceChildren(h('div', { style: { padding: '3rem', textAlign: 'center' } }, 'Aplikace byla ukončena. Toto okno můžeš zavřít.'));
  }), 4000);
  addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/bye?t=' + TOKEN); } catch { /* ignore */ } });
})();
