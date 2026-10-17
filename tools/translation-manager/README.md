# BaDIK Translation Manager 1.7

Desktop tool for the Czech fan translation of *Being a DIK*. It reads the Ren'Py translation files
(`game/tl/czech/**/*.rpy`), tracks translation and proofreading progress per file, episode and season, checks the
translated text, and produces the `progress.json` that the website shows.

> ### Scope – please read
> **This tool is developed mainly for me (the translator of this project), not as a general product.**
> * It works **only for *Being a DIK*, seasons 1 and 2** (episodes 1–8; the file layout, `epN` names and the
>   `season2/` folder are taken from that game).
> * The **user interface is in Czech only.**
> * **Roadmap:** first support for **season 3** when it comes (the season model lives in one place,
>   [`prehled/seasons.py`](prehled/seasons.py)); **maybe later** a rework so that it works for **other Ren'Py games**
>   and has an **English interface**. No promises or dates.
> * You are welcome to read the code; the [license](LICENSE) does **not** allow redistributing it or shipping modified
>   versions without my written permission.
>
> *CZ:* Nástroj vzniká hlavně pro mě. Funguje jen pro Being a DIK (1. a 2. sezóna) a má pouze české rozhraní. Později
> přibude 3. sezóna a možná i přepracování pro víc Ren'Py her a angličtinu.

## Contents
1. [Start](#start) · 2. [Where data lives](#where-data-lives) · 3. [Seasons and episodes](#seasons-and-episodes) ·
4. [Using it](#using-it) · 5. [Validation](#validation) · 6. [Completion estimate](#completion-estimate) ·
7. [Open in editor](#open-in-editor) · 8. [Publishing](#publishing-progress-to-the-website) ·
9. [Command line](#command-line) · 10. [Build the exe](#build-the-exe) · 11. [Tests](#tests) · 12. [Limitations](#limitations)

## Start

| How | What |
|---|---|
| `BaDIKTranslationManager.exe` | Standalone, no Python needed ([build it yourself](#build-the-exe)). Can live in any folder. |
| `run_manager.bat` | From source (Python 3.9+). Works from any folder. |
| `py progress.py [folder] [options]` | Same, from a terminal. |

On the first start the app asks for the translation folder (`…\game\tl\czech`) and **remembers it** in
`%APPDATA%\BaDIKTranslationManager\config.json`. If the saved folder disappears, the welcome screen asks for a new one;
*Změnit…* (top bar) or *Nastavení* switches project any time. A folder given on the command line wins and is remembered.
The window needs WebView2 (present on current Windows 10/11), otherwise an Edge/Chrome window is used.

The top bar has icon links to Ko-fi, GitHub and the project website; the app only ever opens these fixed addresses.

## Where data lives

Everything for a project is in `<translation folder>\_progress_data\` (CSV, Excel-friendly). The `.rpy` files are modified only by explicit actions: editing a translation in the app ([see Translating in the app](#translating-in-the-app)) and the *Opravit* button for a changed speaker / trailing code ([see Validation](#validation)):

| File | Content |
|---|---|
| `korekce.csv` | hand-typed proofread baseline per file, manual "translated" override |
| `korektura_radky.csv` | per-line proofreading marks and "to fix" notes |
| `prirazeni.csv` | file → `Obecné` / `Epizoda N` |
| `schvaleno.csv` | manually approved "untranslated-looking" lines |
| `epizody.csv` | hand-set episode status (Nezačato / Rozpracováno / Přeloženo / V korekci / Hotovo) |
| `slovnik.csv` | glossary: speaker code → full name (type `speaker`), or other terms (type `term`) |
| `historie.csv` | progress log (basis of the chart and the estimate) |
| `progress.csv`, `progress.json` | per-file overview for Excel; the public data for the website |
| `backups\` | automatic backup of a CSV before it is overwritten (≤ 1 per 5 min per file, last 20 kept) |

All writes are atomic (temp file + replace). If a file is locked (open in Excel) the app says so, keeps the change in memory
and retries on the next *Obnovit soubory*; nothing is lost silently. Settings are in `%APPDATA%\BaDIKTranslationManager`
(`config.json`; a crash is logged to `error.log` there and shown in a message box). Files from older versions lying next to the
program are moved into `_progress_data` once.

## Seasons and episodes

| Season | Episodes | Status |
|---|---|---|
| 1 | 1 – 4 | active |
| 2 | 5 – 8 | active |
| 3 | – | **planned**: no files, no numbers, never part of any percentage or estimate |

The mapping lives only in [`prehled/seasons.py`](prehled/seasons.py); statistics, export, website data and tests use it
(`web/progress-model.js` has a fallback copy for *old* data files, a unit test keeps it identical).

**Definitions** (same in the app, `progress.json` and the website): a *line* is one translation unit (a `translate` dialogue
block or an `old`/`new` pair). *Overall* = every scanned file incl. shared (`Obecné`) and unassigned ones. An *episode/season* =
only files assigned to it, so `overall = Σ episodes + Obecné + nezařazené` (checked before export).

## Using it

**Přehled** – totals, remaining work, proofreading, validation counts, finish estimate, per-season and per-episode progress with
**both** percentages (translation green, proofreading purple), the episode status selector (incl. *V korekci*), recent activity and
what *Zpět* would undo.

**Soubory** – all files with full names (the column wraps, never truncates; drag column borders, scroll sideways; the detail panel
always shows the whole path, and its width is resizable within limits). Edit *Překlad* / *Korektura* numbers (number, `50%`, or `ano`);
`↺` restores the automatic count.
* *Bulk categorization:* tick files (Shift+click = range) and *Zařadit vybrané…*, or *Navrhnout zařazení…* for the project.
  Suggestions come from the path (`ep4`, `episode4`), `updateN` files, season folders (`season2/`) and sibling files; you review
  *Nové / Beze změny / Konflikt / Nejednoznačné / Neznámé*, edit anything, and nothing is written until *Zapsat zařazení*. A manual
  assignment is only replaced for rows whose checkbox you tick. One undo step.

**Řádky** – every translation unit. Columns: file, *Řádek* (line in the translation file), *Skript* (original `game/script.rpy:NNN`
that Ren'Py recorded), *Typ* (**Dialog** or **Volba** = lines from `translate czech strings`, mostly menu choices but also UI text – a
hint), *Stav*, *Korektura* (purple), *Kód* and *Jméno* of the speaker (**two separate columns**; the dropdown *Mluvčí* shows both, only
the code or only the name), source, translation, checks. Filter by file / status / type / kind / validation, sort, search (also by speaker
full name). The detail pane (resizable, 140 px … 70 % of the area, double-click resets) shows full texts, block id, neighbouring lines and
problems.
* *Global approval:* a line that is correct as it is (`Hmm...`, names) can be approved (counts as translated). *Schválit všechny
  shodné…* finds lines with **identical source and translation** and shows them; scope: this line / this file / whole project. Defaults
  are cautious (other speakers and English-looking lines unchecked, empty translations never approvable, already approved shown but
  untouched); broad approvals need a second confirming click; all undoable.

**Proofreading** (in *Řádky*, on translated lines): `P` marks the line proofread (✓) and jumps to the next unchecked one, `F` flags it
*k opravě* (⚑) with a note, `Shift+P` marks everything up to this line, `Shift+U` takes the proofread mark away again up to this line (lines flagged *k opravě* stay; both undoable). Filters *Ke korektuře / K opravě / Zkontrolované*; *Pokračovat v
korektuře* opens the first unchecked line. If a proofread line is edited later its mark becomes **stale** (↻) and it returns to *Ke
korektuře*. The *Korektura* number everywhere (files, overview, `progress.json`, website) = the number you typed by hand + lines marked one
by one. Untranslated lines can't be proofread.

**Slovník** (glossary) – speakers in the files are only codes (`mc`, `de`…). The tab lists every code found, with line count and an
example; type the full name next to it (saved when you leave the field, undoable). **Importovat z characters.rpy…** reads the game's
`define xx = Character("Name", …)` lines from **all `characters*.rpy` files** (`characters.rpy`, `season2/scripts/characters_season2.rpy`;
found automatically next to `game/tl`, or give a file / folder). Ren'Py rule applied: a later definition wins, codes defined several times
with different names are reported; the player-named `mc` is skipped; codes used in the translation but defined nowhere are listed. Only
ticked rows are written, names you typed are never overwritten unless ticked. *Termín* entries can be added for later features.

**Kontrola** – the validator ([below](#validation)). **Publikace** – [publishing](#publishing-progress-to-the-website). **Nastavení** – folder,
editor, thresholds, website, about.

**Refresh without restart:** *Obnovit soubory* (`F5`) rescans the folder, re-reads only changed files and reports added / changed /
renamed / removed ones. A rename is detected by identical content (or the same block ids) and the file's metadata moves with it.
Metadata of removed files is kept; unsaved things (a locked CSV, a half-edited number) are confirmed first; unreadable files keep their last state.

**Keyboard:** `Ctrl+F` or `/` search · `↑ ↓`/`J K` move · `PgUp/PgDn` · `A` approve · `Shift+A` approve identical · `P` / `F` / `Shift+P`
proofreading · `E`/`Enter` open in editor · `Ctrl+Z` undo (metadata) · `Ctrl+Enter` save the translation · `F5` refresh · `Alt+1…7` tabs · `?` help. Shortcuts are ignored while typing in
a field. Filters, sorting, column and pane sizes are remembered (stored by the app, not the browser).

## Validation

Compares each translation with its source; the check itself never rewrites anything. Only known Ren'Py tags count as tags; `{{`, `[[`, `{}` and `{#…}` are
handled as Ren'Py does; comparisons are relative to the source (a tag the English also leaves open is not blamed on the translator; word order
and length may differ freely).

| Severity | Examples |
|---|---|
| **Chyba** | stray / mis-nested closing tag, unterminated `[var` / `{tag`, a `[variable]` the source doesn't have, changed `{}` / `%s`, changed speaker or trailing code (`with vpunch`), lone `\` |
| **Varování** | a source tag or `[variable]` missing, extra tag, changed tag argument, missing `{nw}`/`{fast}`, different `\n` count, unclosed tag the source closes, length far from the source |
| **Varování – Text** | digits that differ from the source, double space, the same word twice in a row, English left in a translated line (≥ 3 English function words) |
| **Varování – Typo / okno** | a probable typo (missing diacritics, swapped or doubled letters – from the project's own vocabulary, see below), a translation that needs more lines than the dialogue box holds |
| **Info** (hidden by default) | different number of `{w}` / `{p}` pauses, dropped `{#…}`, a number written out in words, a glossary *term* whose Czech form is not found in the translation |

Length warnings are a review aid with thresholds in *Nastavení* (default: warn above 2.2× or below 0.45× of the visible length and only if the
absolute difference is large; tags and `[variables]` don't count, very short sources are skipped). A file that is not valid UTF-8 is reported
as an error (Ren'Py reads scripts as UTF-8). Not checked: spelling, grammar, meaning, text overflow. The term check is approximate (Czech endings
are matched by word stem) and therefore only an info.

### Fixing a changed speaker

For *Mluvčí / atributy se liší od originálu* and *Kód za textem se liší* the **Opravit** button (per row, in the line detail, and *Opravit
mluvčí / atributy…* for all of them) copies the speaker, image attributes and trailing code from the original comment above the line.
The quoted text is never touched. Flow: preview of every change (before → after) → confirm → backup of the file in
`_progress_dataackups` (always, up to 50 per file) → atomic write → file parsed again and verified (otherwise restored). Refused when the
file changed on disk since it was loaded (refresh first) or when the fix would make a translated line identical to the original (counted as
untranslated) – those are left for manual fixing. **Vrátit poslední opravu** restores the files of the last fix from their backups, but only if they were not edited since (the file's hash is compared), so later work is never thrown away. Line endings and a BOM are preserved. Save the file in your editor first; unsaved editor
changes would be overwritten.

## Safe fixes and find & replace

**Opravit…** (*Kontrola*, or the *Opravit* button of a finding) shows a preview with **one tick box per line** and fixes three kinds: speaker / attributes /
trailing code copied from the original, double spaces between words, and typo hints (missing diacritics, swapped or doubled letters). Doubtful ones
(short words such as *byt / být*) start unticked; *Jen doporučené* resets to the safe selection. **Variables and tags are never fixed automatically** –
in Czech their order often differs from English, so such findings are frequently false positives; ignore them (*Ignorovat…*) or fix them by hand.

**Najít a nahradit…** (*Řádky*) searches the translated text of all or chosen files: *Text*, *Celé slovo*, *Podle kmene* (finds other forms of a word, e.g.
`dikmince → dikminci`, and keeps their endings; works well only for words that decline the same way, so always check the preview) or a regular
expression. Tags `{i}`, variables `[name]` and `\n` are protected unless you switch that off. Preview with a tick per line and a marked diff, a double
confirmation for bulk changes, a backup of every touched file, and **one undo step** (*Vrátit poslední změnu souboru*). A replacement that would break
the string literal (a bare `"`, a lone `\`) is skipped.

## Translation memory, consistency, game window preview

* **Paměť překladů** (panel under the editor): the same original that was translated before, and originals that differ by a few words (with the
  similarity and a ⚠ when the reused text has other `[variables]`). Matching is done on the **English original**, so Czech declension does not hinder
  finding a match; but a reused phrase may need another case, gender or number, so it is only inserted on request (*Použít* replaces the box,
  *Vložit* inserts at the cursor) and always needs your edit.
* **Kontrola → Rozdílné překlady**: one original translated in several ways (e.g. *Yes.* → *Ano.* / *Jo.*), with the speakers and lines. *Použít všude*
  unifies after a confirmation (one undo step); *Nechat jak je* hides a group that is fine (different speaker, gender, context). Nothing is unified automatically.
* **Náhled scény** (*Scéna* tab of the line detail): the **picture of the scene with the dialogue box drawn over it**, like in the game. The picture is found by
  following the game's script (`game/script.rpy:123`, recorded in the translation file) **upwards to the last `scene` / `show`** whose image can be resolved:
  directly by file name, through an `image x = "path"` / `image x:` statement (an animation shows its first frame), or by a numbered / `_blink` variant. Pictures
  are read **read-only** from the game's `.rpa` archives (versions 2 and 3; the archive index is read with an unpickler that refuses to create any object) or
  from loose files in `game/images`. The box, name and text use the game's own values from `gui.rpy` (screen size, `dialogue_width`, `text_size`,
  `textbox_height`, name position; Being a DIK's values when the sources are not found), the text is the translation **as you type it** (or the original) in **the game's own font** (`gui.text_font` / `gui.name_text_font` from `gui.rpy`, overridden by the translation folder, e.g. `translate czech python: gui.text_font = ...` or `translate czech style say_dialogue: font ...`; the font file is read from the game folder or its archives) and the speaker name and colour come from the game's own `Character(...)` definitions, and
  the frame turns red when the text needs more lines than the limit in *Nastavení* or does not fit the box. It is an approximation: it follows the text
  of the script (no jumps or conditions, no layered sprites), so a scene may be wrong where the game builds it in a complicated way; the line under the preview
  says which picture and which script line it used. Without the game folder next to the translation (or with only `.rpyc` files) you get the box alone.
  Characters are placed by the font's own advance widths (`hmtx`, read by `prehled/fontmetrics.py`), which is what Ren'Py does: some patched fonts (e.g. with added
  Czech letters) have a wrong width in their CFF charstrings, and a browser then leaves a gap after every accented letter. Choosing a new line does not
  flicker: the scene info, the decoded picture, the fonts and their widths are fetched first and the view is swapped in one go (cached per line).
  Without the game's font files the preview uses a fallback font, so wrapping is an estimate.

## Focus mode, layouts, quick translating (1.6)

* **Focus mode** (`Ctrl+Shift+F`, the ◩ button): hides the top bar, the tabs and the status bar so only the list and the detail stay; a small floating bar keeps
  *Zobrazit vše*, the layout menu, full screen (⛶ / F11, done by the app window because F11 does not reach a pywebview window) and undo.
* **Rozložení** (menu in *Řádky*): *Automaticky*, *Detail dole*, *Detail vpravo*, **Scéna a filmový pás**, *Rychlé překládání*, *Dva monitory* (detail window) and
  your own layouts (*Uložit aktuální rozložení…*, stored in the preferences; they remember layout, tab and panel sizes). Changing the layout keeps the open line.
* **Film layout**: a big scene picture with the dialogue box, the editor under it and a horizontal **strip of the neighbouring lines** (cards with the speaker badge, number
  and text; dashed = untranslated; the current one centred; a click jumps there). The list table is hidden, the filters stay.
* **Quick translating** (palette or *Rozložení*): focus mode + film layout, only untranslated lines, the editor is focused on every line, `Ctrl+Enter` saves and moves
  to the next untranslated line, the floating bar shows how many are left. *Zobrazit vše* ends it.
* **Speaker badges and colours**: round badges with the initial in the colour from the game's `Character(...)` lines (`/api/game/characters`; a stable colour from the code
  when the game sources are not found) in the list, the film strip and the bubbles.
* **Bubbles** (*Scéna* tab → *Bubliny*): the lines of the scene as chat bubbles in the speaker's colour, translation large, original small; a click jumps to the line.
* **Overview**: a hero panel with two rings (translation, proofreading), what is left, the pace and the estimated finish, and buttons *Pokračovat* (the last line you
  had open), *Rychle překládat* and *Nejblíž dokončení* (the file with the fewest lines left).
* SVG icons in the top bar, nicer empty states, a short fade when a section changes (off with *reduce motion* in the system), slightly higher contrast of the
  `faint` colour in both themes. The interface size is left to the window's own zoom (`Ctrl` + mouse wheel).

## Scenes, proofreading mode, too-long lines (1.7)

* **File strip** (film layout, above the film strip): the file's progress with **translation and proofreading apart** (percent and what is left of each), and jumps:
  **◀ Scéna / Scéna ▶**, a list of the file's scenes (*Scéna 292 / 1484* → each with translated / lines and ✓ checked), **Další nepřeložený**, **Další nezkontrolovaný**,
  **Další, co se nevejde** (all wrap round the file, `/api/entry/next`). Scenes are the runs of lines that follow the same `scene` statement of the game script
  (`/api/scenes`, needs the game sources; one request per file, kept until something is written).
* **One quick mode, two jobs**: *Rozložení → Rychlý režim* (or the buttons in the overview / the palette) opens focus mode with the film layout, and the floating bar has a
  **Překlad | Korektura** switch. Reading ahead keeps it fast: the next lines' scene info, pictures and fonts are fetched while you work, the counters move at once from what is
  known, the heavy refreshes (overview, files, scenes) wait for a short pause, and **P shows the next line first and writes the mark afterwards** (about 30 ms on a 45 000-line project).
* **Quick proofreading** (the *Korektura* side of the quick mode): focus mode + film layout + only lines still to be
  checked; the floating bar has **✓ Zkontrolováno (P)**, **⚑ K opravě (F)** and ↑ / ↓; P marks the line and moves on. The Korektura panel (with the note) sits under the strip.
* **Too long for the dialogue box**: the film strip marks such cards red (⤓), the list rows get a red edge, *Další kontrola → Nevejde se do okna hry* in the filters shows only
  them, and the file strip jumps to the next one. A line "does not fit" when its translation needs more lines than the limit in *Nastavení* and the original did not.

## Choices and their menu, search, texts the generator missed (from the Lexo project)

* **Menu tab** (*Menu*, the default tab of a choice): choices live in `translate strings`, far from the dialogue, so the tab reads the game script (`prehled/menus.py`) and shows
  the **question** (or, for a menu without one, the last two lines said before it), **all choices** of the menu with their translations and `if` conditions, and the
  **first lines after each choice** (original and translation); a choice with no dialogue shows the first lines of its body (variables, `jump`). The tab also opens
  from a dialogue line that belongs to a menu (marked *tento řádek*), and the menu is shown under the film strip in the quick modes. Ren'Py 7 records the line of the `menu:`
  statement for every choice of the menu, newer versions the line of the choice; both work (`/api/entry/menu`). A text used in several menus is listed once by Ren'Py (at its first place, one shared translation): in the other menus the choice says where it is listed and the click jumps there. Needs the scripts as `.rpy`.
* **Whole-word search**: the *Celé slovo* switch next to the search boxes of *Řádky*, *Kontrola* and *Slovník* (`Sage` no longer finds `Massage`; `word=1` on `/api/entries` and `/api/validation`).
* **Quick modes and film layout**: a search or filter opens the first hit; a **results bar** (*Výsledek 3 z 16*, ← →, a list of all hits) shows while something narrows the lines; the
  ← / → keys move between lines like ↓ / ↑.
* **Texts the generator missed** (*Nástroje → Texty, které generátor vynechal…*, experimental): texts that Ren'Py's `translate` does not extract (`show text`, `renpy.input`
  prompts, titles kept in variables, dialogue without a block) are found in the game scripts (`prehled/missed.py`), shown with a *likely / maybe* level, and the ones you tick are
  written to `extra_strings.rpy` as untranslated lines (or, experimental, into the translation file of their own script). The project remembers its own text functions and the ignored
  texts in `_progress_data\missed.json`. Nothing is written until you choose.

## Detail window (second window)

**⧉** in the top bar (or the palette) opens a **window with nothing but the line detail**: the scene picture with the dialogue box and the tabs *Kontrola /
Korektura / Scéna / Skript* - no list, no sections, no settings. It **follows the line you select in the main window** (announced at once, in about 30 ms; if
the windows do not share a browser process the server answers as soon as the line changes) and shows the **text you are typing in the main editor** live in
the preview. While it is open the **main window slims down to the translating** (original + editor, below or beside the list - *◫ Detail vpravo*) and hands
the tabs to the detail window; *Ukázat je i tady* / the *Více* menu bring them back. Customizing the detail window: **Sledovat hlavní okno** (follow on / off),
**Editor i tady** (translate in this window too; then *Paměť* and *Historie* are available there as well) and **Scéna přes celé okno** (the picture fills the
window, scaled to fit). Edits go to the same files (one app, one project); only the first window saves preferences; the app quits when the **last** window is
closed. In the desktop window this opens another native window, in the browser mode an app window, and as a last resort a browser tab.

For one monitor, **◫ Detail vpravo** in *Řádky* puts the detail beside the list instead of under it (automatic on screens 1500 px wide and more; the
choice is remembered), and the scene picture is scaled to fit the height too, so the picture and the editor are visible without scrolling.

## Shortcuts, command palette, scene view

* **Shortcuts are customizable** (*Nastavení → Klávesové zkratky*): press **Změnit** and then the new key; **+** adds a second one, **Odebrat** removes them,
  **Výchozí** resets. A conflict asks before taking a key from another action; actions that also work while typing in a field need Ctrl / Alt / F-keys. Stored
  in the app's preferences; the help (`?`) is generated from the same list. `Ctrl+Enter` and `Esc` in the translation box stay fixed.
* **Command palette** (`Ctrl+K`): type to find any action (without diacritics: *nastaveni* finds *Nastavení*) or a file; arrows and Enter. Every action is in it, also
  those without a key (find & replace, approve by rule, fix, consistency, ignored, lint, snapshot, theme, density, change folder).
* **Scéna kolem řádku** (in the line detail): ±3 / 6 / 10 / 15 neighbouring lines with the **original next to the translation**, the current line marked; a click
  on a row jumps to it. The second window is described in *Detail window* above.

## Machine translation (optional, experimental)

*Nastavení → Strojový překlad*: choose DeepL, an OpenAI-compatible endpoint (also a local one) or LibreTranslate, enter your own API key and **tick the consent**. Then
the editor shows **Návrh strojem**: it sends the English text of *that one line* (OpenAI-compatible: plus the 2 previous lines as context and the glossary terms
found in the line) and shows the answer as a *suggestion* with the validator's findings; it is inserted only when you click, never saved by itself. Tags, variables and
`\n` never go to the service as text: they are swapped for placeholders and put back, and a warning appears if one came back lost or duplicated. The key is stored in
plain text in the app's `config.json` and never sent back to the UI. **Not tested against the real services** (only against a fake HTTP layer, written from their
documentation), so treat it as experimental and check the first results.

**Several lines at once**: *Nástroje → Přeložit strojem…*, or the button next to the counter after you pick lines with **Ctrl+click** (single) / **Shift+click**
(range) in *Řádky*, or **Přeložit scénu strojem…** in the *Scéna* tab (the untranslated lines ±15 around the open one). You choose the scope (picked lines, the scene,
the file in the filter, everything; only untranslated by default), see how many lines and characters will be sent, and the suggestions arrive **in batches of 10
with a progress bar and a Stop button** (at most 500 lines per run; a rejected key or a missing consent stops it at once). The result is a table where you can
**edit every suggestion**, tick what you want (lines with a validator finding or a lost placeholder start unticked) and write the ticked ones as **one undoable
step** (backup of the files, entry in the line history; approved lines are never overwritten). Nothing is sent before you press the button, and the service charges
for the characters sent - check the price with your provider.

## CI

`ui-selftest` in the workflow runs the UI self-test in Edge via Playwright (`tests/ui/run_selftest_ci.py`) and uploads a screenshot. It was added without a run in CI
(no browser on the author's PC), and has since been green, so it is a normal required-looking job (no `continue-on-error`).

## Backups of the translation folder and the Ren'Py lint

**Snapshots** (*Nastavení → Zálohy souborů překladu*): a zip of every `.rpy` file in `_progress_data\snapshots`, made automatically at start (when the last
one is older than the set hours), before bulk changes (replace, fixes, unify; at most one per 10 minutes) and on demand. **Obnovit…** lists the files of a
snapshot with *liší se / chybí / stejný* and restores the ticked ones after a double confirmation; it first saves the current state as a snapshot
*před obnovením*, so a restore can be undone the same way. Names and zip paths are validated (a zip cannot write outside the folder). The oldest are
deleted beyond the set count, manual ones last; folders over 400 MB are not zipped.

**Lint hry** (*Kontrola → Lint hry*): runs Ren'Py's own `lint` for the whole game with the SDK's bundled Python (`renpy.py <game> lint`, or `renpy.sh`), in
the background, and lists findings of the form `file:line message` (with *Zobrazit* for lines in the translation) plus the complete output. Needs the SDK
folder (*Nastavení*) and the game's `.rpy` sources above `game/tl/…`. The wrapper is covered by tests with a fake runner; I could not run it against a real
Ren'Py SDK here, so try it on your game and tell me if the SDK layout differs.

## Weekly goals and time estimates

*Přehled* shows **Cíl na tento týden** for translating and for proofreading (weeks start on Monday): lines done this week against a goal, a status
(*Splněno / Jdeš podle plánu / Zbývá N, to je asi M za den*) and what is needed per day to still make it. The goal comes from your own pace: the
average of the last up to four complete weeks plus 10 %, rounded up to tens, never more than what is left; with less than two complete weeks of history
there is no automatic goal. A goal set in *Nastavení → Týdenní cíle* wins (0 = automatic). Every episode also shows how many days it would take **at
your current pace** (the same pace as the completion estimate, shown only when the history supports a forecast).

## History of a line

*Historie textu* (under the editor) lists every text the line has had, newest first, with the time and how it came about: edit in the app, fix,
replace, unify, undo, or **a change made outside the app** (VS Code, another program) that the app noticed when you refreshed the files (F5). **Obnovit do
pole** puts an old version into the box (marked against the current text); it is only written when you save. The log is `_progress_data\historie_textu.jsonl`
(append-only, the oldest part is dropped beyond 60 000 entries, a damaged line is skipped). Two outside edits between two refreshes appear as one change.

## Translating in the app

The line detail (*Řádky*) has an editable **Překlad** box. **Ctrl+Enter** writes the text into the `.rpy` file and jumps to the next untranslated
line; **Esc** discards; *Kopírovat originál* pastes the source as a base. While you type, the validator checks the new text (tags, variables, length,
dialogue box, typos) and shows the result; a text that would break the string literal (a bare `"`, a lone `\`, a real line break) cannot be saved –
write a new line as `\n` and a quote as `\"`.

Only the text between the quotes is replaced; speaker, attributes, trailing code, line endings, BOM and every other line stay byte for byte as they
were. Each save makes a backup of the file in `_progress_data\backups`, writes atomically, parses the file again and verifies that exactly this one
line changed (otherwise the file is restored). It refuses when the file changed on disk since it was loaded (e.g. unsaved or saved edits in VS Code) –
refresh first. **↶ Vrátit poslední změnu souboru** (in the editor and in *Kontrola*) undoes the last file change from its backup, one step at a time (up
to 30 steps; refused when the file was edited elsewhere since). A line you had marked proofread becomes *changed after proofreading* automatically.

### Snippets, glossary suggestions, copying

Under the box: buttons that insert `{i}…`, `{b}…`, `{u}…` (wrap the selected text), `{w}`, `{p}`, `{nw}`, `\n`, `…` and Czech quotes `„ “` at the cursor.
*Chybí z originálu* offers every tag / `[variable]` of the original that the translation lacks (one click inserts it); *Slovník* offers the Czech
form of every glossary term found in the original (✓ when it is already used). **⧉ Originál / ⧉ Překlad / ⧉ Oboje** copy the texts to the clipboard,
*Originál do pole* pastes the source into the box.

## Ignoring findings

*Ignorovat…* (a finding in *Kontrola*, or in the line detail) hides that one finding on that one line from lists, counts, row highlighting and the
worst-files ranking; an optional note says why. Nothing is deleted: *Kontrola → Ignorované* lists everything ignored (state, note, date, the line's
translation) and **Přestat ignorovat** restores it; *Přehled* shows how many are ignored. An ignore is bound to the translation text of that line:
when the text changes it expires (*Text se změnil*) and the finding shows up again. Stored in `_progress_data\ignorovano.csv` (undoable with Ctrl+Z).

## UI self-test

`run_ui_selftest.bat` (or `py tests\ui\serve_selftest.py`) starts the app on a synthetic project (a temp folder named `.badik-selftest`) and opens
it with `?selftest=1`. `prehled/ui/selftest.js` walks through every tab and the main dialogs, fails on any JavaScript error and shows a PASS / FAIL
panel (window title `SELFTEST PASS (n)`). Only in that synthetic project does it also save a translation and undo it, and ignore / restore a finding.
On your own project, opening `?selftest=1` only reads. Python tests (`tests\test_ui_selftest_assets.py`) check that the harness and its project stay valid.

## Filters

Every list uses the same filter bar. In *Řádky*: search, file, and the **status as pills with counts** (*Vše, K přeložení, Přeložené, Schválené, Ke
korektuře, K opravě, Změněno po korektuře, Zkontrolované*). The counts honour all other filters, so you see what a pill would show before clicking it.
*Další filtry* (type, kind of untranslated line, validator result, sort order, speaker display) opens automatically when one of them is active.
Below, **active filters appear as removable chips** with *Zrušit všechny filtry*. *Kontrola* has the same bar (severity pills with counts, file, kind,
search) and shows **one table row per translation line with all its findings listed under each other** (each with its own *Opravit* / *Ignorovat…*,
plus *Ignorovat všech N…* for the line). *Soubory* and *Slovník* use the same labelled groups.

## Look

*Vzhled* button in the top bar: automatic (follows the system) / dark / light, remembered. Version 1.1 was a visual refresh (tabs with icons, cards,
light theme); 1.2 adds the side-by-side original / translation, a *Hustota* button (comfortable / compact tables) and the features above.

## More review tools

* **Typo hints** (`spelling.py`) – no dictionary: the words of the already translated lines are the vocabulary. A word that occurs ≤ 3× but looks like
  a mistyped form of a word used ≥ 5× and ≥ 5× more often is reported (`prijdu` → `přijdu`, `tkaový` → `takový`, `dobbře` → `dobře`). Source words,
  speaker names and glossary entries are never reported. Short words (`byt`/`být`) are only an info. Switch off in *Nastavení*.
* **Dialogue box check** – estimates the lines a translation needs (explicit `
` plus word wrap at *chars per line*) and warns when it exceeds the
  limit *and* the original needed fewer. Defaults (65 characters × 4 lines) come from the game's `gui.rpy` (text width 1116 px, font 33 px); both are
  editable in *Nastavení*.
* **Term occurrences** – *Slovník → Výskyty* lists every line whose original contains a glossary term and whether the Czech form is used there
  (stem comparison, so endings do not matter); filter *only missing*.
* **Script context** – the line detail shows the original game script around the line's `game/…:N` reference (read-only; needs the `.rpy` sources
  of the game above `game/tl/…`). Shown automatically for choice / UI strings, which have no dialogue around them.
* **Approve by rule** (*Řádky → Schválit podle pravidla…*) – search all files or only chosen ones (preselected from the *Soubory* picks or the file
  filter), preview, then approves with the normal, undoable approval: only symbols, interjections
  (Hmm, Ah, Haha…), or lines that consist only of glossary names. Untranslated English sentences never match.
* **Worst files** – *Přehled* ranks files by problems per 100 lines (an error counts three times).
* **Changed after proofreading** – lines marked proofread whose translation changed since are counted (*Přehled*, *Soubory* badge ↻, filter *Změněno po
  korektuře* in *Řádky*).
* **Project lock** – `_progress_data\lock.json` (pid, computer, refreshed every 15 s) stops a second copy of the app from opening the same project:
  it offers to take over. A lock not refreshed for 60 s (crash) counts as free; the copy that lost the project shows a warning in *Přehled*.

## Completion estimate

From `historie.csv` (last record of each day). A date is shown only if the history covers **≥ 7 days on ≥ 3 different days** in the last 28
days and lines were actually added; otherwise the app says why not. Pace = net lines/day in that window; early/late dates (≥ 3 full weeks)
use the best/worst weekly pace; confidence low/medium/high by coverage and stability; > 5 years away is not shown as a date. It recomputes
from the current remaining lines. `historie.csv` is never rewritten except for the newest row of the running session.

## Open in editor

*Nastavení → Editor*: automatic (VS Code, else Notepad++), VS Code (`code -g file:line`), Notepad++ (`-nLINE`), a custom command
(`"C:\Tools\ed.exe" --line {line} {file}`) or the system default (cannot jump to a line; the app says so). Commands run without a shell,
file names with spaces and `&` are safe, only `.rpy` files inside the project open. Failures are shown, not swallowed.

## Publishing progress to the website

Generating data and publishing it are separate steps:
1. **Generating** is continuous: `_progress_data\progress.json` is rewritten (and validated) on every change. *Publikace → Vygenerovat
   náhled* shows exactly what the website gets. Nothing leaves your computer.
2. **Publishing** (*Připravit publikování…*) first shows a preview: repository, branch/upstream, target file, what changes, the git commands and
   warnings (e.g. *push to `main` deploys the live site*). Only after you tick the confirmation and press *Publikovat* it runs `git pull
   --ff-only`, writes the one file atomically, commits **that file only** and pushes. If data or repository changed since the preview, it
   refuses. If the push fails, the local commit and the file are rolled back. There is **no automatic publishing**; from a terminal
   `progress.py --publish` prints the same preview and needs the word `PUBLISH`.

Authentication is whatever your git already uses. No tokens are stored.

**`progress.json` (schema 2)** keeps all schema-1 keys and adds `schema, scope, seasons[], episodes[].season/translation/proofreading/files_*,
general, unassigned, estimate`. It never contains file names. `web/progress-model.js` validates it in the browser (missing/invalid values
become "no data", never a made-up number).

**`web.json`** was read only by the old `progress.py` (repo, path, title, `push`, `allow_main`); nothing else used it. Its settings now live in
`config.json` (*Nastavení → Web*); an existing file is imported once without being deleted, `push`/`allow_main` are intentionally dropped.
You no longer need it.

## Command line

```
progress.py [folder] [--nogui] [--todo] [--find=file.rpy] [--skip=a.rpy,b.rpy] [--publish] [--edit] [--browser]
```
`--nogui` prints the summary and writes `_progress_data` (always next to the project, never into the current directory); `--publish` shows the
preview and asks for typed confirmation; `--browser` forces a browser window; `--episodes` is obsolete (the model is fixed in `seasons.py`).

## Build the exe

```
build_exe.bat            runs the tests, then builds
build_exe.bat /notest
```
or `py -m pip install -r requirements-build.txt` then `py -m PyInstaller --noconfirm --clean BaDIKTranslationManager.spec`.
Result: `dist\BaDIKTranslationManager.exe` (one file, no console, own icon from `assets/icon.ico`). It does not depend on the working
directory. `.github/workflows/translation-manager.yml` runs the tests on pull requests and builds the exe for tags `manager-v*` as a workflow
artifact only (no release, no deploy, no push).

## Tests

```
py -m unittest discover -s tests          (from this folder; stdlib only)
```
Covers parsing/counting (also checked against the real project), storage and atomic writes, refresh, bulk categorization, approvals and undo,
proofreading, glossary and import, validator, estimates, export consistency and the season model, config and `web.json` migration, editor
commands, publishing against throw-away local git repos (incl. rollback), the HTTP API (incl. a parallel-request stress test), the CLI, and
the website's content rules (links, licenses, images, logo/icon). Browser tests of the website are in [`/tests/web`](../../tests/web/README.md).

## Limitations

* Only *Being a DIK* seasons 1–2, Czech UI (see [Scope](#scope--please-read)).
* The `.rpy` parser is a heuristic that matches the old tool exactly on the real project; an unusual file could be counted wrongly.
* Files that are not UTF-8 are decoded with replacement characters without a warning; two copies of the app on one project can overwrite
  each other's CSV changes (no lock).
* Undo is in-memory (last 30 changes of the session); `backups\` is the disk-level safety net.
* Untested on real hardware: the native folder dialog, a real VS Code launch, the fallback without WebView2, publishing against GitHub itself.
