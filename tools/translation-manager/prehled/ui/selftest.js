/* UI self-test. Open the app with ?selftest=1 (see tests/ui/serve_selftest.py or run_ui_selftest.bat).
   It walks through every tab and the main dialogs, fails on any JavaScript error and shows a PASS / FAIL panel.
   It only READS, except when the open project is the synthetic one made by serve_selftest.py (folder name contains
   ".badik-selftest"): there it also saves a translation, undoes it, and ignores / restores a finding. */
(async function selftest() {
  const results = [];
  const errors = [];
  window.addEventListener('error', (e) => errors.push(`error: ${e.message}`));
  window.addEventListener('unhandledrejection', (e) => errors.push(`promise: ${e.reason?.message || e.reason}`));
  const origErr = console.error;
  console.error = (...a) => { errors.push('console.error: ' + a.map(String).join(' ')); origErr.apply(console, a); };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(fn, ms = 8000) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { const v = fn(); if (v) return v; } catch { /* keep waiting */ } await sleep(60); }
    return null;
  }
  const ok = (name, cond, detail = '') => results.push({ name, pass: !!cond, detail: cond ? '' : detail });
  async function step(name, fn) {
    const before = errors.length;
    try { await fn(); } catch (e) { ok(name, false, e.message || String(e)); return; }
    if (errors.length > before) ok(name + ' – bez chyb v konzoli', false, errors.slice(before).join(' | '));
  }
  const clickText = (sel, test) => [...document.querySelectorAll(sel)].find((b) => (typeof test === 'string' ? b.textContent.includes(test) : test.test(b.textContent)));
  async function openTool(name) {              // tools live in the "Nástroje" menu of the Řádky filter bar
    const menuBtn = clickText('#view button', 'Nástroje');
    if (!menuBtn) return null;
    menuBtn.click();
    const item = await waitFor(() => clickText('#view .menu .menuitem', name), 2000);
    return item || null;
  }
  async function openDetailTab(name) {
    const t = await waitFor(() => clickText('#entryDetail .dtab', name), 4000);
    t?.click();
    await sleep(150);
    return t;
  }
  const closeDialog = () => { const d = document.querySelector('#dlg'); if (d.open) d.close(); };
  async function openView(name, opts) {
    go(name, opts);
    const loaded = await waitFor(() => !document.querySelector('#view .loading') && document.querySelector('#view').children.length, 10000);
    ok(`záložka ${name} se vykreslí`, loaded, 'view zůstal ve stavu načítání');
    ok(`záložka ${name} bez chybové hlášky`, !document.querySelector('#view .notice.bad'), document.querySelector('#view .notice.bad')?.innerText);
  }

  await waitFor(() => typeof S !== 'undefined' && S.version !== undefined && document.querySelector('#tabs .tab'), 10000);   // boot() sets S.version when the state arrived
  const origPrefs = JSON.stringify(S.prefs);
  const synthetic = (S.projectDir || '').includes('.badik-selftest');
  ok('aplikace nastartovala', S.ready, 'není otevřený žádný projekt – otevři projekt a spusť test znovu');
  if (!S.ready) return finish();

  ok('hlavička ukazuje verzi', /\d+\.\d+\.\d+/.test(document.querySelector('#brandText').textContent), document.querySelector('#brandText').textContent);

  await step('Přehled', async () => {
    await openView('overview');
    ok('Přehled ukazuje týdenní cíl', document.querySelector('#view .goalrow'), 'chybí panel cíle');
    ok('Přehled má karty', document.querySelectorAll('#view .stat').length >= 4, `karet: ${document.querySelectorAll('#view .stat').length}`);
    ok('Přehled má hlavní panel s kruhovým grafem a tlačítky', !!document.querySelector('#view .hero svg circle') && [...document.querySelectorAll('#view .hero button')].length >= 2, 'chybí panel');
  });
  await step('Soubory', async () => {
    await openView('files');
    ok('Soubory mají řádky tabulky', document.querySelectorAll('#view table.data tbody tr').length >= 1, 'prázdná tabulka');
  });
  await step('Řádky + editor překladu', async () => {
    await openView('entries', { file: '', status: 'all' });
    await waitFor(() => document.querySelector('#view table.data tbody tr'));
    const rows = document.querySelectorAll('#view table.data tbody tr');
    ok('Řádky mají tabulku', rows.length >= 1, 'žádné řádky');
    if (rows.length) {
      S.ent.api.select(0);
      const ta = await waitFor(() => document.querySelector('#editTarget'));
      ok('detail řádku má editor překladu', ta, 'chybí #editTarget');
      if (ta) {
        ok('editor má tlačítka značek', document.querySelectorAll('#entryDetail .snip').length >= 5, 'chybí tlačítka pro vkládání');
        const keep = ta.value;
        ta.value = keep + ' [selftest]';
        ta.dispatchEvent(new Event('input'));
        const live = await waitFor(() => document.querySelector('#entryDetail .editmsg')?.children.length, 4000);
        ok('živá kontrola reaguje na psaní', live, 'kontrola nic nevypsala');
        ta.value = keep; ta.dispatchEvent(new Event('input'));
        await sleep(450);
        ok('po vrácení textu není editor „špinavý“', ta.dataset.dirty !== '1', 'zůstal data-dirty');
      }
    }
    const pills = document.querySelectorAll('#view .pills .pill');
    ok('Řádky mají pilulky stavů s počty', pills.length >= 6 && [...pills].every((b) => b.querySelector('.pc')), `pilulek: ${pills.length}`);
    const todoPill = [...pills].find((b) => b.textContent.startsWith('K přeložení'));
    if (todoPill) {
      todoPill.click();
      const chip1 = await waitFor(() => [...document.querySelectorAll('#view .fchip')].some((c) => c.textContent.includes('K přeložení')), 4000);
      ok('výběr stavu přidá čip aktivního filtru', chip1, 'čip se neobjevil');
      const reset = [...document.querySelectorAll('#view .fchips button')].find((b) => b.textContent.includes('Zrušit všechny filtry'));
      ok('je tlačítko „Zrušit všechny filtry“', reset, 'chybí');
      reset?.click();
      await waitFor(() => !document.querySelector('#view .fchip'), 4000);
      ok('reset filtrů odstraní čipy', !document.querySelector('#view .fchip'), 'čipy zůstaly');
    }
    const moreBtn = [...document.querySelectorAll('#view .filterbar button')].find((b) => b.textContent.includes('Další filtry'));
    ok('tlačítko „Další filtry“ existuje', moreBtn, 'chybí');
    setPref('display.speaker', 'both');
    const btn = await openTool('Schválit podle pravidla');
    ok('menu Nástroje obsahuje „Schválit podle pravidla“', btn, 'chybí');
    if (btn) {
      btn.click();
      const dlg = await waitFor(() => document.querySelector('#dlg[open] .dlg-head')?.textContent.includes('pravidla') && document.querySelector('#dlg .check, #dlg .empty'), 6000);
      ok('dialog pravidel se otevře a načte náhled', dlg, 'dialog se nenačetl');
      const seg = [...document.querySelectorAll('#dlg .seg button')].find((b) => b.textContent.includes('Jen vybrané'));
      ok('dialog pravidel nabízí výběr souborů', seg, 'chybí volba „Jen vybrané soubory“');
      if (seg) { seg.click(); await sleep(300); ok('seznam souborů se zobrazí', document.querySelector('#dlg .filepick'), 'chybí seznam souborů'); }
      closeDialog();
    }
  });
  await step('Najít a nahradit', async () => {
    await openView('entries', { file: '', status: 'all' });
    const btn = await waitFor(() => openTool('Najít a nahradit'));
    ok('menu Nástroje obsahuje „Najít a nahradit“', btn, 'chybí');
    if (btn) {
      btn.click();
      const inputs = await waitFor(() => { const i = document.querySelectorAll('#dlg[open] input[type=text]'); return i.length >= 2 ? i : null; }, 4000);
      ok('dialog hledání se otevře', inputs, 'dialog se neotevřel');
      if (inputs) {
        ok('dialog nabízí režimy hledání', document.querySelectorAll('#dlg .seg button').length >= 4, 'chybí režimy');
        inputs[0].value = 'a'; inputs[0].dispatchEvent(new Event('input'));
        const shown = await waitFor(() => document.querySelector('#dlg .tablewrap, #dlg .empty, #dlg .notice.bad'), 5000);
        ok('náhled hledání se vykreslí', shown && !document.querySelector('#dlg .notice.bad'), 'náhled selhal');
        inputs[0].value = '('; inputs[0].dispatchEvent(new Event('input'));
        [...document.querySelectorAll('#dlg .seg button')].find((b) => b.textContent.includes('Regulární'))?.click();
        ok('špatný regulární výraz se ohlásí chybou, ne výjimkou', await waitFor(() => document.querySelector('#dlg .notice.bad'), 5000), 'chyba se nezobrazila');
      }
      closeDialog();
    }
  });
  await step('Opravit (bezpečné opravy)', async () => {
    const pv = await post('fix/preview', { kinds: ['speaker', 'spaces', 'typo'] });
    ok('náhled oprav vrací položky s výchozím zaškrtnutím', Array.isArray(pv.items) && pv.items.every((i) => 'default' in i && 'kind' in i), 'špatný tvar odpovědi');
  });
  await step('Paměť překladů, náhled okna hry, konzistence', async () => {
    const html = (t) => gameText(t).innerHTML;
    ok('náhled hry vykreslí {i} a proměnné', html('{i}a{/i} [x]') === '<i data-tag="i">a</i> XXXXX', html('{i}a{/i} [x]'));
    ok('náhled hry převede \\n na zalomení a skryje {w}', html('a\\nb{w}c') === 'a<br>bc', html('a\\nb{w}c'));
    ok('náhled hry nevytvoří HTML z textu', !html('<img src=x onerror=1>').includes('<img'), html('<img src=x onerror=1>'));
    await openView('entries', { file: '', status: 'all' });
    await waitFor(() => document.querySelector('#view table.data tbody tr'));
    const dialogue = S.ent.items.findIndex((x) => x.unit === 'dialogue');
    if (dialogue >= 0) {
      S.ent.api.select(dialogue);
      await waitFor(() => document.querySelector('#editTarget'));
      ok('detail má záložky', document.querySelectorAll('#entryDetail .dtab').length >= 5, 'chybí záložky');
      await openDetailTab('Paměť');
      ok('záložka Paměť ukáže panel paměti překladů', await waitFor(() => document.querySelector('#entryDetail details.memory summary'), 4000), 'chybí');
        ok('editor má tlačítko „Návrh strojem“ (skryté, dokud se nenastaví)', [...document.querySelectorAll('#entryDetail button')].some((b) => b.textContent === 'Návrh strojem'), 'chybí');
      await openDetailTab('Historie');
      ok('záložka Historie ukáže panel historie textu', await waitFor(() => document.querySelector('#entryDetail details.texthistory summary'), 4000), 'chybí');
      await openDetailTab('Scéna');
      const gp = await waitFor(() => document.querySelector('#entryDetail details.gamepreview'), 4000);
      ok('editor má náhled v okně hry', gp, 'chybí');
      if (gp) { gp.open = true; gp.dispatchEvent(new Event('toggle')); ok('náhled hry spočítá řádky', await waitFor(() => /řádek|řádky|řádků/.test(gp.querySelector('summary').textContent), 4000), gp.querySelector('summary').textContent); ok('náhled kreslí okno hry s textem a jménem', await waitFor(() => gp.querySelector('.gstage .gtextbox .gbox')?.textContent.length > 0, 4000), 'chybí .gstage'); const sc = await get('game/scene', { file: S.ent.items[dialogue].file, line: S.ent.items[dialogue].line }); ok('API scény vrací stav a rozměry okna', typeof sc.available === 'boolean' && sc.gui.screen_width > 0 && sc.gui.textbox_height > 0, JSON.stringify(sc).slice(0, 100)); gp.open = false; gp.dispatchEvent(new Event('toggle')); }
    }
    const fo = await post('focus', { file: S.ent.items[0]?.file || 'x', line: S.ent.items[0]?.line || 1 });
    ok('hlavní okno sdílí vybraný řádek s doprovodným oknem', (await get('focus')).seq === fo.seq && fo.seq > 0, JSON.stringify(fo));
    const pickLayout = async (label) => { clickText('#view .frow button', 'Rozložení')?.click(); await sleep(80); const it = clickText('#view .menu .menuitem', label); it?.click(); await sleep(700); return !!it; };
    ok('seznam řádků má nabídku rozložení', !!clickText('#view .frow button', 'Rozložení'), 'chybí');
    ok('rozložení „Detail vpravo“ dá detail vedle seznamu', (await pickLayout('Detail vpravo')) && !!document.querySelector('#view .split.ecols'), 'beze změny');
    ok('rozložení „Scéna a filmový pás“ ukáže pás řádků a skryje tabulku', (await pickLayout('Scéna a filmový pás')) && !!document.querySelector('#view .split.film') && !!(await waitFor(() => document.querySelector('#entryDetail .filmstrip .fcard'), 4000)), 'chybí pás nebo rozložení');
    ok('filmový pás ukazuje aktuální řádek', !!document.querySelector('#entryDetail .filmstrip .fcard.cur'), 'chybí zvýrazněná karta');
    setFocus(true);
    ok('režim soustředění skryje horní lištu a ukáže plovoucí lištu', getComputedStyle(document.querySelector('.topbar')).display === 'none' && !!document.getElementById('focusbar'), 'lišta zůstala');
    setFocus(false);
    ok('konec soustředění vrátí lištu a smaže plovoucí lištu', getComputedStyle(document.querySelector('.topbar')).display !== 'none' && !document.getElementById('focusbar'), 'lišta se nevrátila');
    ok('odznak mluvčího má iniciálu a barvu', (() => { const b = speakerBadge('mc'); return b && b.textContent.length === 1 && !!b.style.background; })(), 'chybí odznak');
    ok('čitelná barva textu na odznaku', readableOn('#ffffff') === '#111' && readableOn('#000000') === '#fff' && readableOn('hsl(10 50% 50%)') === '#fff', 'špatný kontrast');
    setPref('entries.layout', 'rows'); await openView('entries', { file: '', status: 'all' }); await sleep(300);
    const tg = await post('mt/targets', { file: '' });
    ok('API strojového překladu vrací cíle a počet znaků', Array.isArray(tg.items) && tg.total === tg.items.length && tg.chars >= 0, JSON.stringify(tg).slice(0, 80));
    mtDialog({ picked: [], anchor: null, file: '' }, null);
    ok('dialog strojového překladu bez nastavení vysvětlí, co chybí', await waitFor(() => /Strojový překlad není nastavený/.test(document.querySelector('#dlg .dlg-head')?.textContent || ''), 4000), 'dialog se neukázal');
    closeDialog();
    const cons = await get('consistency');
    ok('API konzistence vrací skupiny', Array.isArray(cons.groups), JSON.stringify(cons).slice(0, 80));
    setPref('validation.consistency', false); setPref('validation.ignored', 'hide');      // do not depend on saved view modes
    await openView('validation');
    const b = await waitFor(() => [...document.querySelectorAll('#view button')].find((x) => x.textContent === 'Rozdílné překlady'));
    ok('Kontrola má režim „Rozdílné překlady“', b, 'chybí tlačítko');
    b?.click();
    ok('režim konzistence se vykreslí', await waitFor(() => document.querySelector('#view .tablewrap, #view .empty'), 5000) && !document.querySelector('#view .notice.bad'), 'chyba při načtení');
    [...document.querySelectorAll('#view .seg button')].find((x) => x.textContent === 'Nálezy')?.click();
    await sleep(300);
  });
  await step('Zálohy a lint', async () => {
    const snaps = await get('snapshots');
    ok('API záloh vrací seznam', Array.isArray(snaps.items), JSON.stringify(snaps).slice(0, 80));
    if (synthetic) {
      const made = await post('snapshots/create');
      ok('ruční záloha se vytvoří', made.snapshot?.files >= 1, JSON.stringify(made).slice(0, 80));
      const files = await get('snapshots/files', { name: made.snapshot.name });
      ok('porovnání zálohy vrací soubory', files.files.length >= 1 && files.files.every((f) => f.state), 'prázdný výsledek');
      await post('snapshots/delete', { name: made.snapshot.name });
    }
    setPref('validation.consistency', false); setPref('validation.ignored', 'hide'); setPref('validation.lint', false);
    await openView('validation');
    const b = await waitFor(() => [...document.querySelectorAll('#view button')].find((x) => x.textContent === 'Lint hry'));
    ok('Kontrola má režim „Lint hry“', b, 'chybí tlačítko');
    b?.click();
    ok('režim lintu se vykreslí a nabízí cestu k SDK', await waitFor(() => document.querySelector('#view input[type=text]') && /Lint/.test(document.querySelector('#view').innerText), 5000) && !document.querySelector('#view .notice.bad'), 'chybí');
    [...document.querySelectorAll('#view .seg button')].find((x) => x.textContent === 'Nálezy')?.click();
    setPref('validation.lint', false);
    await sleep(300);
  });
  await step('Zkratky, paleta, scéna', async () => {
    const ev = (key, mods = {}) => ({ key, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, ...mods });
    ok('comboOf: písmeno velké a s Shift', comboOf(ev('a')) === 'A' && comboOf(ev('A', { shiftKey: true })) === 'Shift+A', comboOf(ev('a')) + ' / ' + comboOf(ev('A', { shiftKey: true })));
    ok('comboOf: Ctrl, Alt, symboly a názvy kláves', comboOf(ev('k', { ctrlKey: true })) === 'Ctrl+K' && comboOf(ev('1', { altKey: true })) === 'Alt+1' && comboOf(ev('?', { shiftKey: true })) === '?' && comboOf(ev('ArrowDown')) === 'ArrowDown' && comboOf(ev('Shift', { shiftKey: true })) === '', 'špatný zápis');
    ok('v záhlaví je tlačítko druhého okna', document.getElementById('newWinBtn') && !SECONDARY, 'chybí tlačítko nebo je to druhé okno');
    ok('v záhlaví je tlačítko celé obrazovky a zkratka F11', document.getElementById('fullBtn') && ACTIONS.some((a) => a.id === 'fullscreen' && a.keys.includes('F11')), 'chybí');
    let wo;
    try { wo = await post('window/open', { view: 'entries', file: 'x.rpy', line: 3 }); } catch (e) { wo = e.data; }      // no opener in the test server: the page must be told to fall back
    ok('server při nedostupném okně vrátí náhradní postup, ne chybu', wo && wo.ok === false && wo.fallback === true, JSON.stringify(wo));
    ok('každá akce má jedinečné id bez tečky', new Set(ACTIONS.map((a) => a.id)).size === ACTIONS.length && ACTIONS.every((a) => !a.id.includes('.')), 'duplicitní nebo špatné id');
    const keys = ACTIONS.flatMap((a) => (a.entries ? [] : keysOf(a))), dup = keys.filter((k, i) => keys.indexOf(k) !== i);
    ok('výchozí zkratky se nepřekrývají', dup.length === 0, dup.join(','));
    ok('výchozí zkratky: Ctrl+K a Alt+1 existují', findAction('Ctrl+K', true)?.id === 'palette' && findAction('Alt+1', false)?.id === 'tab_overview', 'chybí');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    const pal = await waitFor(() => document.querySelector('#dlg[open] .palette .palrow'), 4000);
    ok('Ctrl+K otevře paletu s akcemi', pal, 'paleta se neotevřela');
    if (pal) {
      const input = document.querySelector('#dlg input[type=search]');
      input.value = 'nastaveni'; input.dispatchEvent(new Event('input'));
      ok('paleta hledá bez diakritiky', [...document.querySelectorAll('#dlg .palrow')].some((r) => r.textContent.includes('Nastavení')), 'nenašla Nastavení');
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      ok('Enter v paletě provede akci', await waitFor(() => S.view === 'settings', 3000), 'zůstalo ' + S.view);
    }
    closeDialog();
    await openView('settings');
    ok('Nastavení má panel zkratek', document.querySelectorAll('#view fieldset').length && [...document.querySelectorAll('#view legend')].some((l) => /zkratky/i.test(l.textContent)), 'chybí');
    helpDialog();
    ok('nápověda je vytvořená z registru akcí', await waitFor(() => document.querySelectorAll('#dlg[open] kbd').length > 15, 3000), 'málo zkratek');
    closeDialog();
    await openView('entries', { file: '', status: 'all' });
    await waitFor(() => document.querySelector('#view table.data tbody tr'));
    const dialogue = S.ent.items.findIndex((x) => x.unit === 'dialogue');
    if (dialogue >= 0) {
      S.ent.api.select(dialogue);
      await waitFor(() => document.querySelector('#entryDetail .dtab'));
      await openDetailTab('Scéna');
      ok('detail má scénu kolem řádku', await waitFor(() => document.querySelector('#entryDetail details.scene table.scene-table tbody tr.cur'), 5000), 'chybí scéna');
    }
  });
  await step('Kontrola', async () => {
    setPref('validation.consistency', false); setPref('validation.ignored', 'hide');      // do not depend on saved view modes
    await openView('validation');
    await waitFor(() => document.querySelector('#view .tablewrap, #view .empty'));
    const api = await get('validation', { group: 'line' });
    const shown = document.querySelectorAll('#view table.data tbody tr').length;
    ok('Kontrola ukazuje jeden řádek tabulky na řádek překladu', shown === Math.min(api.total, 200), `řádků v tabulce: ${shown}, řádků s nálezem: ${api.total}`);
    ok('Kontrola má pilulky závažnosti s počty', document.querySelectorAll('#view .pills .pill .pc').length >= 3, 'chybí');
    ok('Kontrola má přepínač ignorovaných', [...document.querySelectorAll('#view button')].some((b) => /Ignorované/.test(b.textContent)), 'chybí tlačítko Ignorované');
    const b = [...document.querySelectorAll('#view button')].find((x) => /Ignorované/.test(x.textContent));
    b?.click();
    await waitFor(() => document.querySelector('#view .tablewrap, #view .empty'));
    ok('seznam ignorovaných se vykreslí', !document.querySelector('#view .notice.bad'), 'chyba při načtení ignorovaných');
    [...document.querySelectorAll('#view .seg button')].find((x) => x.textContent === 'Nálezy')?.click();
    await sleep(300);
  });
  await step('Slovník', async () => {
    await openView('glossary');
    ok('Slovník má tabulku nebo prázdný stav', document.querySelector('#view table.data, #view .empty'), 'prázdný view');
  });
  await step('Publikace', async () => { await openView('publish'); });
  await step('Nastavení', async () => {
    await openView('settings');
    for (const id of ['set_val', 'set_spell', 'set_tb', 'set_tbcpl', 'set_tblines', 'set_snap_on', 'set_snap_h', 'set_snap_keep', 'set_sdk', 'set_goal_t', 'set_mt_provider', 'set_mt_key', 'set_mt_consent']) ok(`nastavení má pole ${id}`, document.getElementById(id), 'chybí');
  });
  await step('Vzhled a hustota', async () => {
    const t0 = pref('ui.theme', 'auto'), d0 = pref('ui.density', 'comfortable');
    const seen = new Set();
    for (let i = 0; i < 3; i++) { cycleTheme(); seen.add(pref('ui.theme', 'auto')); }
    ok('přepínač vzhledu projde auto/tmavý/světlý', seen.size === 3, [...seen].join(','));
    toggleDensity(); ok('hustota se přepne', document.documentElement.dataset.density === 'compact', document.documentElement.dataset.density);
    toggleDensity();
    setPref('ui.theme', t0); setPref('ui.density', d0); applyTheme(); applyDensity();
  });
  await step('Nápověda', async () => {
    helpDialog();
    ok('nápověda se otevře', await waitFor(() => document.querySelector('#dlg[open] kbd')), 'dialog se neotevřel');
    closeDialog();
  });

  if (synthetic) {
    await step('zápis do souboru (syntetický projekt)', async () => {
      const list = await get('entries', { status: 'translated', file: '' });
      const it = list.items.find((x) => x.unit === 'dialogue');
      ok('v syntetickém projektu je přeložený dialog', it, 'nic k úpravě');
      if (it) {
        const text = it.target + ' (test)';
        await post('entry/save', { file: it.file, line: it.line, text });
        const after = await get('entry', { file: it.file, line: it.line });
        ok('uložený text je ve čteném detailu', after.target === text, after.target);
        const undo = await post('fix/undo');
        const back = await get('entry', { file: it.file, line: it.line });
        ok('„Vrátit poslední změnu“ vrátí původní text', back.target === it.target && undo.restored.length === 1, back.target);
      }
      const v = await get('validation');
      const f = v.items.find((x) => x.line && x.code !== 'duplicate-id');
      ok('syntetický projekt má aspoň jeden nález', f, 'žádný nález');
      if (f) {
        const n0 = (await get('overview')).validation.ignored || 0;
        await post('ignore/set', { items: [{ file: f.file, line: f.line, code: f.code }], on: true, note: 'selftest' });
        const o1 = await get('overview');
        ok('ignorovaný nález se spočítá', (o1.validation.ignored || 0) === n0 + 1, JSON.stringify(o1.validation));
        const only = await get('validation', { ignored: 'only' });
        ok('ignorovaný nález je v seznamu ignorovaných', only.items.some((x) => x.line === f.line && x.code === f.code), 'chybí');
        await post('ignore/set', { items: [{ file: f.file, line: f.line, code: f.code }], on: false });
        ok('nález jde vrátit', ((await get('overview')).validation.ignored || 0) === n0, 'zůstal ignorovaný');
      }
    });
  }

  await step('úklid', async () => {
    S.prefs = JSON.parse(origPrefs); applyTheme(); applyDensity();
    await post('prefs', S.prefs);
    go('overview');
  });
  finish();

  function finish() {
    const failed = results.filter((r) => !r.pass);
    window.__selftest = { done: true, passed: results.length - failed.length, failed: failed.length, results, errors, synthetic };
    document.title = failed.length ? `SELFTEST FAIL (${failed.length})` : `SELFTEST PASS (${results.length})`;
    const panel = document.createElement('div');
    panel.id = 'selftestPanel';
    panel.style.cssText = 'position:fixed;left:16px;bottom:44px;z-index:99;width:min(560px,92vw);max-height:70vh;overflow:auto;padding:12px 14px;border-radius:12px;background:var(--panel);border:2px solid ' +
      (failed.length ? 'var(--bad)' : 'var(--good)') + ';box-shadow:var(--shadow-lg);font-size:13px';
    panel.innerHTML = `<b style="font-size:15px">${failed.length ? '✗ UI self-test: ' + failed.length + ' selhalo' : '✓ UI self-test prošel'}</b> <span class="muted">(${results.length} kontrol${synthetic ? ', včetně zápisů v syntetickém projektu' : ', jen čtení'})</span>` +
      '<ul style="margin:8px 0 0;padding-left:18px">' + results.map((r) => `<li style="color:${r.pass ? 'var(--good)' : 'var(--bad)'}">${r.pass ? '✓' : '✗'} ${r.name.replace(/</g, '&lt;')}${r.detail ? ' – <span class="muted">' + String(r.detail).replace(/</g, '&lt;') + '</span>' : ''}</li>`).join('') + '</ul>' +
      (errors.length ? '<p style="color:var(--bad)">Chyby v konzoli:<br>' + errors.map((e) => e.replace(/</g, '&lt;')).join('<br>') + '</p>' : '');
    document.body.append(panel);
    console.log('SELFTEST', failed.length ? 'FAIL' : 'PASS', JSON.stringify({ passed: results.length - failed.length, failed: failed.length }));
  }
})();
