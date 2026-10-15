# BaDIK Translation Manager 1.1

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
*k opravě* (⚑) with a note, `Shift+P` marks everything up to this line. Filters *Ke korektuře / K opravě / Zkontrolované*; *Pokračovat v
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

## Look

*Vzhled* button in the top bar: automatic (follows the system) / dark / light, remembered. Version 1.1 is a visual refresh (tabs with icons, cards,
light theme) with the same functions as before.

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
