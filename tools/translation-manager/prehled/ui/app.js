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
  if (!data.ok) throw new Error(data.error || 'Operace selhala.');
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
const speakerMode = () => pref('display.speaker', 'code');
function speakerLabel(who) {
  if (!who) return '';
  const [code, ...attrs] = who.trim().split(/\s+/);
  const name = S.gl[code];
  const rest = attrs.length ? ' ' + attrs.join(' ') : '';
  const mode = speakerMode();
  if (!name || mode === 'code') return who;
  return mode === 'name' ? name + (attrs.length ? ` (${attrs.join(' ')})` : '') : `${name} · ${code}${rest}`;
}
async function loadGlossary() {
  try { S.gl = (await get('glossary')).names || {}; } catch { S.gl = {}; }
}
function speakerModeSelect(onchange) {
  return h('select', { title: 'Jak zobrazovat mluvčí', onchange: (ev) => { setPref('display.speaker', ev.target.value); onchange?.(); } },
    ...[['code', 'Mluvčí: kód'], ['name', 'Mluvčí: celé jméno'], ['both', 'Mluvčí: jméno i kód']].map(([v, l]) => h('option', { value: v, selected: speakerMode() === v }, l)));
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

/* ---------------------------------------------------------------- tabs */
const TABS = [['overview', 'Přehled'], ['files', 'Soubory'], ['entries', 'Řádky'], ['validation', 'Kontrola'], ['glossary', 'Slovník'], ['publish', 'Publikace'], ['settings', 'Nastavení']];
function renderTabs() {
  const nav = $('#tabs');
  nav.replaceChildren(...TABS.map(([k, label], i) => {
    const bad = k === 'validation' && S.overview ? S.overview.validation.error : 0;
    return h('button', { class: 'tab', role: 'tab', 'aria-selected': String(S.view === k), title: `Alt+${i + 1}`, onclick: () => go(k) },
      label, bad ? h('span', { class: 'badge' }, fmtN(bad)) : null);
  }));
}
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
async function openProject(path) {
  if (!path.trim()) return toast('Zadej cestu ke složce.', 'bad');
  try { status('Otevírám projekt…'); await post('project/set', { path }); await afterProjectChange(); } catch (e) { fail(e); }
}
async function pickProject() {
  try {
    const r = await post('project/pick', {});
    if (r.cancelled) return status('Výběr složky zrušen.');
    await afterProjectChange();
  } catch (e) { fail(e); }
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
      h('div', { class: 'row', style: { marginTop: '8px' } },
        h('button', { class: 'btn small primary', onclick: () => go('entries', { file: '', status: 'review', select: true }) }, 'Pokračovat v korektuře'))),
    h('div', { class: 'panel stat', style: { cursor: 'pointer' }, onclick: () => go('validation') }, h('div', { class: 'label' }, 'Kontrola překladu'),
      h('div', { class: 'value' }, fmtN(v.error), h('small', null, v.error === 1 ? 'chyba' : 'chyb')),
      h('div', { class: 'sub' }, `${fmtN(v.warning)} varování (z toho ${fmtN(v.length)} k délce textu)`))));
  root.append(estimatePanel(o.estimate));

  const left = h('div'), right = h('div');
  for (const s of o.seasons) left.append(seasonPanel(s, o.episodes));
  const ug = (label, g) => g.translation.total ? h('li', null, h('span', null, label, h('span', { class: 'muted' }, ` · ${g.files} souborů`)), h('span', { class: 'num' }, `${fmtN(g.translation.done)} / ${fmtN(g.translation.total)} (${fmtPct(g.translation.percent)})`)) : null;
  left.append(h('div', { class: 'panel' }, h('h3', null, 'Mimo epizody'),
    h('ul', { class: 'list' }, ug('Obecné (celá hra)', o.general), ug('Nezařazené soubory', o.unassigned),
      !o.general.translation.total && !o.unassigned.translation.total ? h('li', { class: 'muted' }, 'Všechny soubory jsou zařazené k epizodám.') : null),
    h('div', { class: 'panel-body muted' }, 'Celkový překlad výše zahrnuje i tyto soubory. Procenta epizod a sezón počítají jen soubory zařazené k epizodě.')));

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
      h('span', { class: 'meta' }, e.files ? `${fmtN(e.translation.done)} / ${fmtN(e.translation.total)} řádků · ${e.files} souborů (${e.files_done} hotových)` : 'bez souborů'),
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
  main.append(h('div', { class: 'pane-head' }, h('div', { class: 'toolbar' }, search, seg, asel,
    h('button', { class: 'btn', onclick: () => bulkAssignDialog(null) }, 'Navrhnout zařazení…'), pickBtn, h('span', { class: 'spacer' }), counter)));
  const wrap = h('div', { class: 'pane-body' });
  main.append(wrap);
  root.append(main, detail);

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
        h('td', null, fname(r.name, { link: true, onclick: (e) => { if (e.detail === 2) go('entries', { file: r.name }); } })),
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
  { k: 'who', w: 90, label: 'Mluvčí' }, { k: 'source', w: 420, label: 'Originál' }, { k: 'target', w: 420, label: 'Překlad' }, { k: 'issues', w: 90, label: 'Kontrola', sortable: true },
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
  const root = h('div', { class: 'split rows', style: { '--detail-h': pref('entries.detailh', 300) + 'px' } });
  const main = h('div', { class: 'pane' });
  const detail = h('div', { class: 'detail', id: 'entryDetail' });
  const counter = h('span', { class: 'muted' });
  const search = h('input', { type: 'search', class: 'search', id: 'search', placeholder: 'Hledat v textu… (Ctrl+F)', value: e.q || '',
    oninput: (ev) => { setPref('entries.q', ev.target.value); debounceLoad(); } });
  const sel = (key, def, opts, title) => h('select', { title, value: e[key] || def, onchange: (ev) => { setPref('entries.' + key, ev.target.value); load(true); } }, opts.map(([v, l]) => h('option', { value: v }, l)));
  const fileSel = h('select', { title: 'Soubor', onchange: (ev) => { setPref('entries.file', ev.target.value); load(true); } }, h('option', { value: '' }, 'Všechny soubory'), files.map((f) => h('option', { value: f.name }, f.name)));
  fileSel.value = e.file || '';
  fileSel.style.maxWidth = '340px';
  main.append(h('div', { class: 'pane-head' }, h('div', { class: 'toolbar' }, fileSel,
    sel('status', 'todo', [['todo', 'K přeložení'], ['review', 'Ke korektuře'], ['fix', 'K opravě (korektura)'], ['proofed', 'Zkontrolované'], ['all', 'Vše'], ['translated', 'Přeložené'], ['approved', 'Schválené']], 'Stav'),
    sel('unit', '', [['', 'Dialogy i volby'], ['dialogue', 'Jen dialogy'], ['string', 'Jen volby (strings)']], 'Typ řádku'),
    sel('kind', '', [['', 'Všechny druhy'], ['english', 'Anglicky'], ['same', 'Shodné, možná OK'], ['symbols', 'Jen znaky'], ['empty', 'Prázdné']], 'Druh nepřeloženého řádku'),
    sel('issues', '', [['', 'Kontrola: vše'], ['any', 'S problémem'], ['error', 'S chybou'], ['warning', 'S varováním']], 'Filtr podle kontroly'),
    sel('sort', 'line', [['line', 'Řadit: řádek'], ['file', 'Řadit: soubor'], ['kind', 'Řadit: druh'], ['issues', 'Řadit: problémy']], 'Řazení'),
    speakerModeSelect(() => repaintRows()), search, h('span', { class: 'spacer' }), counter)));
  const wrap = h('div', { class: 'pane-body' });
  main.append(wrap);
  root.append(main, detail);
  let timer;
  const debounceLoad = () => { clearTimeout(timer); timer = setTimeout(() => load(true), 250); };
  let tbody;

  function skeleton() {
    const showFile = !pref('entries.file', '');
    const cols = EN_COLS.filter((c) => showFile || c.k !== 'file');
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
      h('td', { class: 'who', title: it.who }, speakerLabel(it.who)), h('td', { class: 'txt entry-source' }, fmtText(it.source ?? '')), h('td', { class: 'txt entry-target' }, fmtText(it.target)),
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
      S.ent.total = r.total;
      r.items.forEach((it, k) => tbody.append(rowFor(it, base + k)));
      counter.textContent = `${fmtN(r.total)} řádků`;
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
      d.status !== 'todo' ? h('div', { class: 'proofbox' },
        h('div', { class: 'row' }, h('h4', { style: { margin: 0 } }, 'Korektura'), proofChip(d.proof) || h('span', { class: 'muted' }, 'zatím nezkontrolováno'),
          d.proof_date && d.proof === 'ok' ? h('span', { class: 'muted' }, d.proof_date) : null),
        h('div', { class: 'actions' },
          h('button', { class: 'btn small ' + (d.proof === 'ok' ? '' : 'primary'), onclick: () => toggleProof() }, d.proof === 'ok' ? 'Zrušit označení (P)' : '✓ Zkontrolováno (P)'),
          h('button', { class: 'btn small', onclick: () => flagFix() }, d.proof === 'fix' ? 'Zrušit „k opravě“ (F)' : '⚑ K opravě (F)'),
          h('button', { class: 'btn small', title: 'Označí jako zkontrolované všechny přeložené řádky tohoto souboru až po tento řádek (lze vrátit Ctrl+Z)', onclick: () => proofUpto() }, 'Zkontrolováno vše až sem (Shift+P)')),
        h('textarea', { id: 'proofNote', rows: 2, placeholder: 'Poznámka ke korektuře (co opravit)…', value: d.proof_note || '', style: { width: '100%' },
          onchange: (ev) => saveNote(ev.target.value) })) : null,
      h('div', { class: 'ctx' }, 'Blok: ', h('b', { class: 'mono' }, d.block), d.who ? ['  ·  mluvčí: ', h('b', { class: 'mono' }, speakerLabel(d.who))] : null, d.src_line ? `  ·  originál na řádku ${d.src_line}` : null),
      h('h4', { style: { marginTop: '10px' } }, 'Originál'), h('div', { class: 'textbox' }, fmtText(d.source ?? '(zdroj nenalezen)')),
      h('h4', null, 'Překlad'), h('div', { class: 'textbox' }, fmtText(d.target)),
      d.issues.length ? h('div', null, h('h4', null, 'Kontrola'), d.issues.map((x) => h('div', { class: 'issue ' + x.severity }, chip(x.severity, SEV_LABEL[x.severity]), ' ', x.message,
        x.ratio ? h('div', { class: 'muted' }, `Délka: originál ${x.source_len}, překlad ${x.target_len} znaků (poměr ${String(x.ratio).replace('.', ',')}). Rozhodni sám, jestli je to záměr.`) : null))) : null,
      (d.before.length || d.after.length) ? h('div', null, h('h4', { style: { marginTop: '10px' } }, 'Okolí v souboru'),
        d.before.map((x) => ctxLine(x)), h('div', { class: 'ctx' }, h('b', null, `▶ ${d.line}`)), d.after.map((x) => ctxLine(x))) : null);
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
  async function proofUpto() {
    const d = S.ent.detail; if (!d) return;
    try {
      const r = await post('proof/upto', { file: d.file, line: d.line });
      S.ent.items.forEach((x, i) => { if (x.file === d.file && x.line <= d.line && x.status !== 'todo' && ['', 'stale'].includes(x.proof)) { x.proof = 'ok'; refreshRow(i); } });
      S.files = null; await refreshHeader(); await select(S.ent.sel);
      toast(r.changed ? `Zkontrolováno ${r.changed} řádků ✓  (Ctrl+Z vrátí)` : 'Nebylo co označit.', 'ok', 3000);
    } catch (err) { fail(err); }
  }
  async function globalApprove() {
    const d = S.ent.detail; if (!d || d.status === 'translated') return;
    await globalApproveDialog(d, async () => { S.files = null; await refreshHeader(); load(true); });
  }
  S.ent.api = { select, toggleApprove, toggleProof, flagFix, proofUpto, globalApprove, load, tbody: () => tbody, reload: () => load(true) };
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

/* ================================================================ VALIDATION */
async function viewValidation() {
  const o = S.goOpts; S.goOpts = null;
  if (o?.file !== undefined) setPref('validation.file', o.file);
  const v = pref('validation', {});
  const settings = await get('settings');
  const root = h('div');
  const list = h('div'), counter = h('span', { class: 'muted' });
  const files = S.files || (S.files = (await get('files')).files);
  const sev = h('div', { class: 'seg' }, [['', 'Chyby + varování'], ['error', 'Jen chyby'], ['warning', 'Jen varování'], ['info', 'Jen info']].map(([k, l]) =>
    h('button', { class: (v.severity || '') === k ? 'on' : '', onclick: (ev) => { setPref('validation.severity', k); sev.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === ev.currentTarget)); load(true); } }, l)));
  const cat = h('select', { onchange: (ev) => { setPref('validation.category', ev.target.value); load(true); } }, [['', 'Všechny druhy'], ['syntax', 'Značky a proměnné'], ['structure', 'Struktura (mluvčí, bloky)'], ['length', 'Délka textu']].map(([k, l]) => h('option', { value: k }, l)));
  cat.value = v.category || '';
  const fsel = h('select', { style: { maxWidth: '320px' }, onchange: (ev) => { setPref('validation.file', ev.target.value); load(true); } }, h('option', { value: '' }, 'Všechny soubory'), files.map((f) => h('option', { value: f.name }, f.name)));
  fsel.value = v.file || '';
  const search = h('input', { type: 'search', class: 'search', id: 'search', placeholder: 'Hledat… (Ctrl+F)', value: v.q || '', oninput: (ev) => { setPref('validation.q', ev.target.value); clearTimeout(S.valTimer); S.valTimer = setTimeout(() => load(true), 250); } });
  const info = h('label', { class: 'check', title: 'Například jiný počet pauz {w} / {p}' }, h('input', { type: 'checkbox', checked: !!settings.validation.show_info, onchange: async (ev) => { try { await post('settings', { validation: { show_info: ev.target.checked } }); load(true); } catch (e) { fail(e); } } }), 'Zobrazit i drobnosti');
  root.append(h('div', { class: 'toolbar' }, sev, cat, fsel, search, info, h('span', { class: 'spacer' }), counter),
    h('p', { class: 'muted' }, 'Kontrola nikdy nic nepřepisuje. ', h('b', null, 'Chyba'), ' = Ren\'Py by pravděpodobně spadl nebo je rozbitá struktura skriptu. ', h('b', null, 'Varování'), ' = podezřelé, ale může být záměr (např. češtině chybí značka, text je výrazně delší). Porovnává se vždy s originálem, ne s pevnými pravidly.'), list);
  S.val.items = [];
  async function load(reset) {
    if (reset) { S.val.items = []; list.replaceChildren(loading()); }
    try {
      const q = { severity: pref('validation.severity', ''), category: pref('validation.category', ''), file: pref('validation.file', ''), q: pref('validation.q', ''), offset: S.val.items.length, limit: 200 };
      const r = await get('validation', q);
      S.val.items.push(...r.items); S.val.total = r.total;
      counter.textContent = `${fmtN(r.total)} nálezů`;
      paintList();
    } catch (e) { list.replaceChildren(h('div', { class: 'notice bad' }, e.message)); }
  }
  function paintList() {
    if (!S.val.items.length) return list.replaceChildren(empty('Žádné nálezy', 'Pro tento filtr nebyl nalezen žádný problém.'));
    const t = buildTable({ key: 'validation', cols: [{ k: 'sev', w: 100, label: 'Závažnost' }, { k: 'loc', w: 380, label: 'Soubor : řádek' }, { k: 'msg', w: 420, label: 'Zpráva' }, { k: 'src', w: 340, label: 'Originál' }, { k: 'tgt', w: 340, label: 'Překlad' }, { k: 'act', w: 130, label: '', resize: false }] });
    for (const it of S.val.items) {
      t.tbody.append(h('tr', null, h('td', null, chip(it.severity, SEV_LABEL[it.severity])),
        h('td', null, fname(it.file), h('span', { class: 'mono muted' }, `řádek ${it.line}`)), h('td', null, it.message),
        h('td', { class: 'txt' }, fmtText(it.source)), h('td', { class: 'txt' }, fmtText(it.target)),
        h('td', null, h('button', { class: 'btn small', title: 'Zobrazit v seznamu řádků', onclick: () => go('entries', { file: it.file, line: it.line, status: 'all' }) }, 'Zobrazit'), ' ',
          h('button', { class: 'btn small ghost', title: 'Otevřít v editoru', onclick: () => openEditor(it.file, it.line) }, 'Editor'))));
    }
    list.replaceChildren(h('div', { class: 'tablewrap' }, t.table), S.val.items.length < S.val.total ? h('div', { class: 'more' }, h('button', { class: 'btn', onclick: () => load(false) }, `Načíst další (${fmtN(S.val.items.length)} z ${fmtN(S.val.total)})`)) : null);
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
    h('div', { class: 'toolbar' }, seg, search, speakerModeSelect(() => toast('Zobrazení mluvčích změněno.', 'ok', 1500)),
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
          it.count ? h('button', { class: 'btn small', title: 'Zobrazit řádky tohoto mluvčího', onclick: () => go('entries', { file: '', q: it.code, status: 'all' }) }, 'Řádky') : null, ' ',
          (it.name || it.note) ? h('button', { class: 'btn small ghost', title: 'Smazat záznam ze slovníku', onclick: async () => {
            try { data = await post('glossary/delete', { codes: [it.code] }); S.gl = data.names; draw(); toast('Záznam smazán. Zpět: Ctrl+Z'); } catch (e) { fail(e); } } }, 'Smazat') : null)));
    }
    body.replaceChildren(h('div', { class: 'tablewrap' }, t.table));
  }
  async function importDialog() {
    let pv;
    try { pv = await post('glossary/import-preview', { path: '' }); } catch (e) { return fail(e); }
    const pathIn = h('input', { type: 'text', value: pv.path, placeholder: 'D:\\Hra\\game\\characters.rpy', style: { flex: 1 } });
    const holder = h('div');
    let rows = [];
    const apply = h('button', { class: 'btn primary', disabled: true }, 'Zapsat do slovníku');
    const upd = () => { const n = rows.filter((r) => r.on).length; apply.disabled = !n; apply.textContent = n ? `Zapsat do slovníku (${n})` : 'Zapsat do slovníku'; };
    const STATE = { new: ['Nové', 'tr'], same: ['Shodné', 'none'], conflict: ['Jiné než ve slovníku', 'error'], dynamic: ['Zadává hráč', 'none'] };
    function paint(data) {
      rows = data.items.map((i) => ({ ...i, on: i.state === 'new' }));
      if (!rows.length) { holder.replaceChildren(empty('Nic k importu', data.message || 'V souboru nejsou žádné řádky define … = Character("…").')); return upd(); }
      const t = buildTable({ key: 'glimport', cols: [{ k: 'on', w: 44, label: '', resize: false }, { k: 'code', w: 110, label: 'Kód' }, { k: 'name', w: 240, label: 'Jméno v characters.rpy' },
        { k: 'cur', w: 220, label: 'Dosud ve slovníku' }, { k: 'st', w: 190, label: 'Stav' }] });
      for (const r of rows) {
        t.tbody.append(h('tr', null, h('td', { class: 'center' }, h('input', { type: 'checkbox', checked: r.on, disabled: r.state === 'dynamic' || r.state === 'same',
          title: r.state === 'conflict' ? 'Přepíše jméno, které máš ve slovníku' : '', onchange: (e) => { r.on = e.target.checked; upd(); } })),
          h('td', { class: 'mono' }, r.code), h('td', null, r.name || h('span', { class: 'muted' }, r.note)), h('td', { class: 'muted' }, r.current || '–'),
          h('td', null, chip(STATE[r.state][1], STATE[r.state][0]), r.in_project ? null : h('span', { class: 'muted' }, '  (není v překladu)'))));
      }
      holder.replaceChildren(
        data.missing?.length ? h('div', { class: 'notice warn' }, `V překladu je ${data.missing.length} kódů mluvčích, které characters.rpy nedefinuje (mohou být definované jinde, nebo jde o překlep): `, h('span', { class: 'mono' }, data.missing.slice(0, 25).join(', ') + (data.missing.length > 25 ? ' …' : ''))) : null,
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
      h('p', { class: 'muted' }, 'Soubor hry se jen čte. Zaškrtnuté řádky se zapíšou do slovníku; jména, která už ve slovníku máš a liší se, se přepíšou jen když je sám zaškrtneš.'),
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
      ...field('Min. rozdíl – kratší (znaků)', h('input', { type: 'text', id: 'set_missing', value: String(ln.min_missing_chars) })))),
    h('fieldset', null, h('legend', null, 'Web (publikování)'), h('div', { class: 'form' },
      ...field('Repozitář', h('input', { type: 'text', id: 'set_repo', value: s.web.repo, placeholder: 'Filiposakkq/Being-A-DIK-CZ' }), 'Složka s klonem, adresa nebo uživatel/repozitář. Přihlášení řeší tvůj git (Credential Manager) – žádné tokeny se tu neukládají.'),
      ...field('Soubor v repozitáři', h('input', { type: 'text', id: 'set_path', value: s.web.path }), 'Výchozí web/progress.json.'),
      ...field('Název hry na webu', h('input', { type: 'text', id: 'set_title', value: s.web.title })),
      s.web.migrated_from ? h('div', { class: 'hint' }, `Převzato z ${s.web.migrated_from}. Samostatný web.json už aplikace nepotřebuje.`) : null)),
    h('fieldset', null, h('legend', null, 'O aplikaci'), h('p', null, h('b', null, `BaDIK Translation Manager ${S.version || ''}`),
      ' – nástroj pro český překlad hry Being a DIK. Licence: viz soubor ', h('span', { class: 'mono' }, 'tools/translation-manager/LICENSE'),
      ' (osobní nekomerční použití; další šíření, úpravy a komerční použití jen s mým souhlasem).'),
      h('div', { class: 'row' }, ...[['kofi', 'Podpořit na Ko-fi'], ['github', 'GitHub'], ['repo', 'Repozitář překladu'], ['web', 'Web překladu']].map(([id, l]) =>
        h('button', { class: 'btn small', onclick: () => post('open-url', { id }).catch(fail) }, l)))),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: save }, 'Uložit nastavení'),
      h('span', { class: 'muted' }, 'Nastavení: ', h('span', { class: 'mono' }, 'config.json'), ' v %APPDATA%\\BaDIKTranslationManager')));
  async function save() {
    try {
      await post('settings', {
        skip_files: val('set_skip').value.split(',').map((x) => x.trim()).filter(Boolean),
        editor: { preferred: val('set_editor').value, custom: val('set_custom').value },
        validation: { enabled: val('set_val').checked, length: { enabled: val('set_len').checked, max_ratio: num(val('set_max').value), min_ratio: num(val('set_min').value),
          min_source_chars: num(val('set_minsrc').value), min_extra_chars: num(val('set_extra').value), min_missing_chars: num(val('set_missing').value) } },
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
  const rows = [['Ctrl+F nebo /', 'Hledat v aktuální sekci'], ['↑ ↓  (J K)', 'Předchozí / další řádek'], ['PgUp PgDn', 'Skok o stránku'], ['A', 'Schválit / zrušit schválení řádku'], ['Shift+A', 'Schválit všechny shodné… (s náhledem)'], ['P', 'Korektura: zkontrolováno (a skok na další)'], ['F', 'Korektura: označit k opravě + poznámka'], ['Shift+P', 'Korektura: zkontrolováno vše až po tento řádek'],
    ['E nebo Enter', 'Otevřít řádek v editoru'], ['Ctrl+Z', 'Vrátit poslední změnu (mimo textová pole)'], ['F5 nebo Ctrl+R', 'Obnovit soubory'], ['Alt+1 … Alt+7', 'Přepnout sekci'], ['?', 'Tato nápověda']];
  dialog({ title: 'Klávesové zkratky', narrow: true, body: h('dl', { class: 'kv' }, rows.flatMap(([k, d]) => [h('dt', null, h('kbd', null, k)), h('dd', { style: { textAlign: 'left' } }, d)])), buttons: [{ label: 'Zavřít', kind: 'primary' }] });
}
document.addEventListener('keydown', (e) => {
  if (dialogOpen()) return;
  const typing = isTyping(e.target);
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === 'f') { const s = $('#search'); if (s) { e.preventDefault(); s.focus(); s.select(); } return; }
  if (e.key === 'F5' || (mod && e.key.toLowerCase() === 'r')) { e.preventDefault(); doRefresh(); return; }
  if (e.altKey && /^[1-7]$/.test(e.key)) { e.preventDefault(); go(TABS[+e.key - 1][0]); return; }
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
    case 'f': e.preventDefault(); api.flagFix(); break;
    case 'e': case 'Enter': { const it = S.ent.items[i]; if (it) { e.preventDefault(); openEditor(it.file, it.line); } break; }
    default:
  }
});

/* ================================================================ boot */
$('#refreshBtn').addEventListener('click', () => doRefresh());
$('#undoBtn').addEventListener('click', doUndo);
$('#changeProject').addEventListener('click', pickProject);
document.querySelectorAll('[data-link]').forEach((b) => b.addEventListener('click', () => post('open-url', { id: b.dataset.link }).catch(fail)));

(async function boot() {
  renderTabs();
  try {
    const st = await get('state');
    S.ready = st.ready; S.version = st.version; S.prefs = st.prefs || {}; S.notices = st.notices || []; S.projectDir = st.project_dir || '';
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
