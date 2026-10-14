# BaDIK Translation Manager 1.0

Desktop tool for the Czech translation of *Being a DIK*: it reads the Ren'Py translation files
(`game/tl/czech/**/*.rpy`), tracks translation / proofreading progress per file, episode and season,
checks the translated text, and produces the `progress.json` that the website shows.

The UI is Czech. The application itself needs only Python's standard library (the optional `pywebview`
gives it its own window; without it an Edge/Chrome "app" window is used).

## Start

| How | What |
|---|---|
| `BaDIKTranslationManager.exe` | Standalone, no Python needed. Build it yourself (see [Build](#build-the-exe)). Can live in any folder. |
| `run_manager.bat` | From source (Python 3.9+). Works from any folder. |
| `py progress.py [folder] [options]` | Same, from a terminal. |

On the first start the app asks for the translation folder (`…\game\tl\czech`). **It remembers it** in
`%APPDATA%\BaDIKTranslationManager\config.json` and opens it automatically next time. If the saved folder
disappears, the welcome screen asks for a new one; *Změnit…* in the top bar (or *Nastavení*) switches
project at any time. A folder passed on the command line wins over the saved one and is remembered too.

Everything the app writes for a project lives in `<translation folder>\_progress_data\` (same files and
formats as before, so existing data keeps working and CSVs can still be opened in Excel):

| File | Content |
|---|---|
| `korekce.csv` | hand-typed proofread baseline per file, manual translated-lines override |
| `korektura_radky.csv` | per-line proofreading marks and "to fix" notes |
| `slovnik.csv` | glossary: speaker code → full name (type `speaker`), or other terms (type `term`) |
| `prirazeni.csv` | file → `Obecné` / `Epizoda N` |
| `schvaleno.csv` | manually approved "untranslated-looking" lines |
| `epizody.csv` | hand-set episode status (Nezačato / Rozpracováno / Přeloženo / V korekci / Hotovo) |
| `historie.csv` | progress log (basis for the charts and the finish estimate) |
| `progress.csv` | per-file overview (for Excel) |
| `progress.json` | the public data for the website (see below) |
| `backups\` | automatic backups of a CSV before it is overwritten (at most one per 5 minutes per file, last 20 kept) |

Old files lying next to the program (from earlier versions) are moved into `_progress_data` once.
`progress.html` (the read-only snapshot) is no longer generated; the window is the live view.
The separate "Hledač" window is replaced by the *Řádky* tab.

All writes are atomic (temp file + replace). If a file is locked (open in Excel) the app says so,
keeps the change in memory, and retries on the next *Obnovit soubory*; nothing is lost silently.

## Season and episode model

| Season | Episodes | Status |
|---|---|---|
| 1 | 1 – 4 | active |
| 2 | 5 – 8 | active |
| 3 | – | **planned**: no files, no numbers, never part of any percentage or estimate |

The mapping lives in one place: [`prehled/seasons.py`](prehled/seasons.py). Statistics, the export,
the website data and the tests all use it. (`web/progress-model.js` has a fallback copy for *old*
data files; a unit test keeps it identical.) To start Season 3 work later, change `seasons.py`
deliberately; nothing else is hard-coded.

**Definitions** (same for the manager, `progress.json` and the website):
a *line* is one translation unit (a `translate` dialogue block or an `old`/`new` pair).
*Overall* = every scanned file, including shared (`Obecné`) and unassigned ones. An *episode*/*season* = only
the files assigned to it. Therefore `overall = Σ episodes + Obecné + nezařazené`; the exporter checks it.

## Links and license

The top bar has icon buttons for Ko-fi, GitHub and the project website (they open in your browser; the app only ever opens these fixed addresses).
The application is **not open source**: see [LICENSE](LICENSE) (personal, non-commercial use; redistribution, modification and commercial use only with the author's written permission).

## Using it

**Přehled** – totals, remaining work, proofreading, validation counts, finish estimate, per-season and
per-episode progress with **both** percentages (translation green, proofreading purple); set the episode status here, including *V korekci*, recent activity, what *Zpět* (undo) would revert.

**Soubory** – all files with full names (the column wraps, never truncates; drag the column borders to
resize, scroll sideways if needed; the detail panel on the right always shows the whole path).
Edit *Překlad* / *Korektura* numbers (number, `50%`, or `ano`), `↺` restores the automatic count.

*Bulk categorization* — tick files (Shift+click for a range) and *Zařadit vybrané…*, or *Navrhnout zařazení…*
for the whole project. The suggestions come from the path (`ep4`, `episode4`), `updateN` files, season folders
(`season2/`) and the assignment of siblings in the same folder. You review a table (current / proposed /
confidence / reason / state: *Nové, Beze změny, Konflikt, Nejednoznačné, Neznámé*) and can change any value.
Nothing is written until *Zapsat zařazení*. A manually set assignment is only replaced for rows whose
checkbox you tick yourself. One undo step.

**Řádky** – every translation unit. Columns: file, *Řádek* (line in the translation file), *Skript* (the original `game/script.rpy:NNN` position Ren'Py recorded for the line), *Typ*, *Stav*, *Korektura*, speaker, source, translation, checks.
*Typ* is **Dialog**, or **Volba** for lines from `translate czech strings` – mostly menu choices but also interface texts, so it is a hint; the *Typ řádku* filter shows only dialogues or only choices/strings. Proofreading has its own column and colour (purple; green = translated). Details: Filter by
file / status / kind / validation, sort, search. Select a row for the full texts, the block id, the
neighbouring lines and any problems. *Otevřít v editoru* jumps to the exact line.

*Global approval* — an "untranslated" line that is correct as it is (`Hmm...`, names) can be approved
(counts as translated). *Schválit všechny shodné…* finds lines with **identical source and translation**
and shows the occurrences; scope: this line / this file / whole project. Defaults are cautious: other
speakers and English-looking lines are unchecked, empty translations can never be approved, already-approved
lines are shown but untouched. Broad approvals need a second confirming click, and every approval is
undoable (`Ctrl+Z`).

### Proofreading

Select a translated line in *Řádky* (filter **Ke korektuře** shows what is still unchecked):

| Key | Does |
|---|---|
| `P` | mark the line **proofread** (✓) and jump to the next unchecked line; pressing it again un-marks |
| `F` | flag the line **k opravě** (⚑) and write a note; flagged lines are not counted as proofread until you mark them ✓ |
| `Shift+P` | mark every unchecked translated line of the file **up to this one** (for "I read everything down to here") |

* Filters: *Ke korektuře*, *K opravě (korektura)*, *Zkontrolované*. *Pokračovat v korektuře* (file detail in *Soubory*, or the *Přehled* card) opens the first unchecked line.
* If a proofread line's translation is edited later, its mark becomes **stale** (↻ "změněno po korektuře"), is no longer counted and shows up again under *Ke korektuře*.
* The number in *Korektura* (files table, overview, `progress.json`, website) = the **number you typed by hand** (e.g. the 436 lines already checked) **+ the lines marked one by one**. Typing a number never drops marked lines; *Ano* = whole file.
* Marks are stored in `_progress_data\korektura_radky.csv` (file; block; source; ok/fix; translation fingerprint; note; date), survive refreshes and renames, are backed up, and every change is undoable (`Ctrl+Z`). Untranslated lines can't be proofread.

**Slovník** (glossary) – speakers in the files are only codes (`mc`, `de`, `ji`…). The tab lists every code found in the project with its line count and an example line; type the character's full name next to it (saved when you leave the field; undoable). Nothing is pre-filled or guessed. *Mluvčí: kód / celé jméno / jméno i kód* decides how speakers are shown in *Řádky*, the detail pane and the neighbouring lines (attributes such as `mc happy` are kept; a code without a name is always shown as the code). *Importovat z characters.rpy…* reads the game's `define xx = Character("Name", …)` lines (found automatically next to `game/tl`, or enter the path), shows a preview (*Nové / Shodné / Jiné než ve slovníku*; the player-named `mc` is skipped) and writes only what you tick - names you already typed are never overwritten unless you tick them. It also lists speaker codes used in the translation that `characters.rpy` does not define (defined elsewhere, or typos). *+ Přidat položku* adds other entries (type *termín*: names, places, the fraternity…) which are stored for later features.

**Kontrola** – the validator (see below). **Publikace** – see below. **Nastavení** – folder, editor,
thresholds, website.

### Keyboard

`Ctrl+F` or `/` search · `↑ ↓` / `J K` move · `PgUp/PgDn` · `A` approve / un-approve · `Shift+A` approve all
identical (with preview) · `P` / `F` / `Shift+P` proofreading · `E` / `Enter` open in editor · `Ctrl+Z` undo · `F5` refresh · `Alt+1…7` switch tabs · `?` help.
Shortcuts are ignored while you type in a field, so they never conflict with text editing.
Filters, sorting, column widths and the last tab are remembered (stored by the app, not the browser).

### Refresh without restart

*Obnovit soubory* (`F5`) rescans the folder and re-reads only files whose size/time changed. It reports
added / changed / renamed / removed files. A rename is detected by identical content (or the same block ids),
and the file's proofreading counts, assignment and approvals move with it. Metadata of removed files is kept
(so a file that returns, or a drive that was briefly unavailable, loses nothing). If something is unsaved
(a locked CSV, a half-edited number) you are asked before refreshing. Unreadable files keep their last state.

### Validation

Compares each translation with its source; never rewrites anything. Only known Ren'Py tags are treated as
tags; `{{`, `[[`, `{}` and `{#…}` are handled as Ren'Py does, and comparisons are relative to the source (a tag
the English also leaves open is not blamed on the translator; word order and length may differ freely).

| Severity | Examples |
|---|---|
| **Chyba** (error) | stray or mis-nested closing tag, unterminated `[var` / `{tag`, a `[variable]` the source doesn't have, changed number of `{}` or `%s`, changed speaker / trailing code (`with vpunch`), lone `\` |
| **Varování** (suspicious) | a tag or `[variable]` of the source missing, extra tag, changed tag argument (`{color=…}`), missing `{nw}`/`{fast}`, different `\n` count, unclosed tag that the source closes, length far from the source |
| **Info** (hidden by default) | different number of `{w}` / `{p}` pauses, dropped `{#…}` comment tag |

Length warnings are a review aid with configurable thresholds (Nastavení): default *warn when the translation is
> 2.2× or < 0.45× the visible length* and the absolute difference is large enough; tags and `[variables]` don't count
as text, very short sources are skipped.

### Completion estimate

From `historie.csv`, last record of each day. A projected date is shown only if the history covers **at least
7 days on at least 3 different days** (within the last 28 days) and lines were actually added; otherwise
the app says why it can't estimate. The pace is the net lines/day over that window; the early/late dates
(shown when ≥ 3 full weeks exist) use the best/worst weekly pace; confidence is low/medium/high by coverage and
stability; more than 5 years away is not shown as a date. It recomputes from the current remaining lines.
`historie.csv` is never rewritten except for the newest row of the running session.

### Editor

Settings → *Editor*: automatic (VS Code, else Notepad++), VS Code (`code -g file:line`), Notepad++ (`-nLINE`),
a custom command (`"C:\Tools\ed.exe" --line {line} {file}`) or the system default (cannot jump to a line; the
app says so). Commands are run without a shell, file names with spaces and `&` are safe, only `.rpy` files inside
the project are opened. If nothing can be started the error is shown instead of failing silently.

## Publishing progress to the website

Generating data and publishing it are separate:

1. **Generating** happens continuously: `_progress_data\progress.json` is rewritten (and validated) on every change.
   *Publikace → Vygenerovat náhled* shows exactly what the website will get. Nothing leaves your computer.
2. **Publishing** (*Připravit publikování…*) first shows a preview: repository, branch/upstream, target file,
   what changes, the git commands that will run and warnings (e.g. *push to `main` deploys the live site*).
   Only after you tick the confirmation and press *Publikovat* the app runs: `git pull --ff-only`, write the
   one file atomically, `git add`/`git commit` **that file only**, `git push`. If the data or the repository changed
   since the preview, it refuses and asks you to preview again. If the push fails, the local commit and the file are
   rolled back. There is **no automatic publishing** (the old `push: true` setting and "push on exit" are gone).
   From a terminal: `progress.py --publish` prints the same preview and needs you to type `PUBLISH`.

Authentication is whatever your git already uses (Credential Manager / SSH). No tokens are stored by the app.

### `progress.json` (schema 2) and the website

The website (`web/`, deployed by Cloudflare Workers from this repo) fetches `progress.json` only; it has no other data
source. Schema 2 keeps all schema-1 keys (`title, updated, translation, proofreading, files, episodes[n,status,percent,files], history`)
and adds `schema, scope, seasons[], episodes[].season/translation/proofreading/files_*, general, unassigned, estimate`.
It never contains file names (checked before writing). `web/progress-model.js` validates the data in the browser
(missing / invalid values become "no data", never a made-up number), so an old or broken file cannot crash the page.

### What happened to `web.json`

`web.json` was read **only** by the old `progress.py` (repo URL, target path, title, `push`, `allow_main`). The
website, Cloudflare Worker and GitHub never read it, it is git-ignored and contained no secrets. Its settings now
live in the app's `config.json` and are edited in *Nastavení → Web*. On first open the app imports an existing
`_progress_data\web.json` once (only filling empty settings; it never deletes or overwrites). `push` and `allow_main` are
intentionally **not** migrated. **You no longer need to maintain `web.json`**; you may delete it or keep it as a backup.
The previous local clone `~\.progress-web\<repo>` is reused if present.

## Command line

```
progress.py [folder] [--nogui] [--todo] [--find=file.rpy] [--skip=a.rpy,b.rpy] [--publish] [--edit] [--browser]
```
`--nogui` prints the summary and writes `_progress_data` (always next to the project, never into the current
directory); `--publish` shows the preview and asks for typed confirmation; `--browser` forces a browser window.
`--episodes=N` is obsolete (the season model is fixed in `seasons.py`).

## Build the exe

```
build_exe.bat            runs the tests, then builds
build_exe.bat /notest
```
or `py -m pip install -r requirements-build.txt` then `py -m PyInstaller --noconfirm --clean BaDIKTranslationManager.spec`.
Result: `dist\BaDIKTranslationManager.exe` (one file, no console). It does not depend on the working directory: settings are in
`%APPDATA%\BaDIKTranslationManager`, data in `_progress_data` next to the translation files, the UI is bundled.
A crash shows a message box and is logged to `%APPDATA%\BaDIKTranslationManager\error.log`.
`.github/workflows/translation-manager.yml` runs the tests on pull requests and builds the exe for tags `manager-v*`
as a workflow artifact only (no release, no deploy, no push).

## Tests

```
py -m unittest discover -s tests          (from this folder; stdlib only)
```
Covers parsing/counting (also checked against the real project: identical to the old tool), storage and atomic
writes, refresh (added/changed/renamed/removed/locked), bulk categorization, global approval and undo, validator,
estimates, export consistency and the season mapping, config persistence, `web.json` migration, editor commands, publishing
against throw-away local git repos (incl. rollback), the HTTP API and the CLI.
Website tests are HTML pages in `/tests/web` (`model.test.html`, `site.test.html`): serve the repo root (`py -m http.server`)
and open them in a browser — each prints `N passed, 0 failed`. With `PREHLED_BROWSER_TESTS=1` and Edge/Chrome installed,
`tests/test_web.py` runs them headless.

## Limitations

* The window needs WebView2 (present on current Windows 10/11); otherwise a browser window is used.
* Undo is in-memory (last 30 changes of this session); the `backups\` folder is the disk-level safety net.
* The editor's *Otevřít v editoru* cannot jump to a line in the system-default fallback.
* Per-episode history does not exist (only overall `historie.csv`), so estimates are project-wide.
