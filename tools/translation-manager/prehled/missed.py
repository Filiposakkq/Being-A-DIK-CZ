"""Texts that Ren'Py's `translate` command does not extract, found by reading the game's scripts.

The generator only takes what goes through the translation system with a block of its own: dialogue in labels, menu choices, screens and strings
marked `_("...")`. A text shown some other way (`show text "..."`, `renpy.input("prompt")`, `renpy.notify(...)`, a title assigned to a variable and
shown later with `[title]`, or dialogue in a place the generator does not reach) has no block, yet it can be translated with a
`translate <lang> strings:` block (old / new). This module finds such texts and writes them into a strings file, so the translator does not have to
search for them by hand.

It is a heuristic and says so: every finding has a `level`:
  likely   the text is given to a function or statement that shows text (`show text`, `renpy.input`, `renpy.notify`, `Text(...)`, ...), or assigned
           to a variable whose name says text (title, name, message ...), or it is a dialogue line that has no translation block at all;
  maybe    any other string that looks like a sentence or a title (it contains a space, a tag or a [variable]).
and a `kind`: `text` or `dialogue`. Nothing is changed by the search. Menu choices and everything inside `screen` blocks are skipped, because
Ren'Py extracts those itself.
"""
import json
import re
from pathlib import Path

from .util import atomic_write_text

SKIP_DIRS = {"tl", "cache", "saves", ".lexo", "_progress_data", ".git", "__pycache__"}
STRING = r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''
LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
# a dialogue line (`who "text"`, `"text"`, with an optional `with`/`id` tail) and a menu choice (`"text" if cond:`)
SAY_RE = re.compile(rf'^\s*(?:[A-Za-z_]\w*(?:\s+[\w.@]+)*\s+)?(?:{STRING})(?:\s+(?:with|id)\s+\S+)*\s*$')
CHOICE_RE = re.compile(rf'^\s*(?:{STRING})(?:\s+if\s+.+)?:\s*$')
# words that start a Ren'Py statement: a line beginning with one of them is not a dialogue line, whatever follows
NOT_A_SPEAKER = {"show", "hide", "scene", "play", "queue", "stop", "window", "pause", "nvl", "call", "jump", "return", "with", "python", "init",
                 "define", "default", "if", "elif", "else", "while", "for", "menu", "label", "screen", "image", "transform", "style", "voice",
                 "camera", "pass", "renpy"}
STATEMENT_SKIP = ("translate ", "image ", "transform ", "style ", "label ", "jump ", "call ", "play ", "queue ", "stop ", "scene ",
                  "hide ", "with ", "from ", "import ", "init offset", "python hide", "define build.", "define config.", "define gui.",
                  "build.", "config.", "gui.", "$ config.", "$ gui.")
# top-level statements whose indented body is not text for the player (image definitions, transforms, styles, translations)
BLOCK_SKIP = ("image ", "transform ", "style ", "translate ", "layeredimage ", "init python in ")
SINK_NAMES = r"show\s+text|renpy\.input|renpy\.notify|renpy\.confirm|renpy\.say|renpy\.display_say|Notify|Text|ui\.text|renpy\.show_screen|tooltip|[A-Za-z_]\w*\.say"
SINK_RE = re.compile(rf"\b(?:{SINK_NAMES})\b")
CALL_RE = re.compile(rf"([A-Za-z_][\w.]*)\s*\(\s*(?:{STRING})")
# callables that take a string but are not text for the player: never suggested as "functions that show text"
NOT_TEXT_FUNCTIONS = {"Character", "DynamicCharacter", "Image", "Transform", "Solid", "Color", "Movie", "Play", "Queue", "Stop", "Show", "Hide", "Jump",
                      "Call", "SetVariable", "SetField", "ToggleVariable", "Function", "Return", "Action", "Fixed", "Frame", "LiveComposite", "Null",
                      "AlphaMask", "ConditionSwitch", "DynamicImage", "FileSave", "FileLoad", "OpenURL", "Preference", "Notify", "Text", "SetDict",
                      "getattr", "setattr", "hasattr", "isinstance", "len", "str", "int", "float", "print", "open", "range", "list", "dict", "set"}


NOISE_NAME_RE = re.compile(r"(?:Error|Exception|Warning)$|^self\.|\.(?:write|log|debug|info|warning|error|print|join|format|get|pop|startswith|endswith|replace|split|say)$|_indent$")


LIST_METHODS = {"append", "remove", "insert", "extend", "add", "update", "discard", "setdefault", "index", "count", "get", "pop", "join"}


def sink_regex(functions=()):
    """The pattern for "this text is shown to the player": the built-in functions plus the project's own (`functions`, e.g. ["notify", "popup"])."""
    extra = [re.escape(f.strip()) for f in functions if f and re.fullmatch(r"[A-Za-z_][\w.]*", f.strip())]
    return re.compile(rf"\b(?:{SINK_NAMES}{'|' + '|'.join(extra) if extra else ''})\b")
NAME_HINT_RE = re.compile(r"\w*(?:title|name|text|message|msg|caption|label|desc|prompt|hint|tip|header|heading)\w*\s*=(?!=)", re.I)
CHARACTER_DEF_RE = re.compile(r"\bCharacter\s*\(")
PATHLIKE_RE = re.compile(r"/|\\(?![ntr\"'\\])|\.(?:png|jpg|jpeg|webp|webm|mp4|mp3|ogg|opus|wav|rpy|rpyc|ttf|otf|py|json|txt)\b", re.I)
IDENT_RE = re.compile(r"^[\w.\[\]]+$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
TAG_RE = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]")
COMMENT_SAY_RE = re.compile(rf'^\s*#\s*(?:[A-Za-z_]\w*(?:\s+[\w.@]+)*\s+)?({STRING})')


def looks_like_text(text):
    """Does this string look like something a person reads (not an id, a path, a colour or a single lower-case word)?"""
    plain = TAG_RE.sub(" ", text)                      # {i} and {/i} must not look like a path
    if len(text) < 3 or COLOR_RE.match(text) or PATHLIKE_RE.search(plain):
        return False
    if not re.search(r"[A-Za-z]{3,}", plain):
        return False
    if " " in text.strip():
        return True
    if IDENT_RE.match(text) and not text[:1].isupper():
        return False
    return text[:1].isupper() and "_" not in text


def _scripts(game_dir):
    game_dir = Path(game_dir)
    for path in sorted(game_dir.rglob("*.rpy")):
        parts = path.relative_to(game_dir).parts
        if set(parts[:-1]) & SKIP_DIRS:
            continue
        yield path, "/".join(parts)


def has_scripts(game_dir):
    """Is there at least one script (outside tl and the other skipped folders) below `game_dir`?"""
    return any(True for _ in _scripts(game_dir))


def _literal(m):
    return m.group(1) if m.group(1) is not None else m.group(2)


REF_RE = re.compile(r"^#\s*(?:game/)?(?P<file>[^:]+?\.rpym?):(?P<line>\d+)\s*$")          # a file name may hold spaces
DATA_START = ("init", "python", "define ", "default ", "$ ")


def known_texts(tl_dir):
    """(strings, dialogue, places): the `old "..."` strings of the translation; the original texts of its dialogue blocks (the `# who "text"`
    comments); and the places `(file, line)` that its blocks point to (the `# game/script.rpy:22` comments of Ren'Py's generator)."""
    strings, dialogue, places = set(), set(), set()
    for path in Path(tl_dir).rglob("*.rpy"):
        if "_progress_data" in path.parts or ".lexo" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("old "):
                m = LITERAL_RE.search(s)
                if m:
                    strings.add(_literal(m))
            elif s.startswith("#"):
                ref = REF_RE.match(s)
                if ref:
                    places.add((ref.group("file").replace("\\", "/"), int(ref.group("line"))))
                    continue
                m = COMMENT_SAY_RE.match(s)
                if m:
                    dialogue.add(m.group(1)[1:-1])
    return strings, dialogue, places


def known_strings(tl_dir):
    return known_texts(tl_dir)[0]


def find_missed(game_dir, known, known_dialogue=None, known_places=None, limit=5000, functions=(), ignored=()):
    """Texts in the game's scripts that the translation does not have. `known` = the string table; `known_places` = the places its dialogue
    blocks point to (a dialogue line at any other place has no block); `known_dialogue` = the texts of the dialogue blocks, used when the places are
    not known; with neither, dialogue is not examined. Returns {items, truncated}; each item is {text, kind, file, line, level, context, count}, the
    likely ones first. `functions`: names of the project's own functions that show text; `ignored`: texts the translator chose to leave out."""
    found = {}
    sink = sink_regex(functions)
    skip_texts = set(ignored)

    def add(text, kind, level, rel, no, context):
        old = found.get(text)
        if old:
            old["count"] += 1
            if level == "likely" and old["level"] != "likely":
                old.update(level="likely", kind=kind, context=context, file=rel, line=no)
        else:
            found[text] = {"text": text, "kind": kind, "file": rel, "line": no, "level": level, "context": context, "count": 1}

    for path, rel in _scripts(game_dir):
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        in_screen = in_skipped_block = in_data = False
        for no, line in enumerate(lines, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if not line.startswith((" ", "\t")):
                in_screen = s.startswith("screen ")
                in_skipped_block = s.startswith(BLOCK_SKIP)
                in_data = s.startswith(DATA_START)          # an indented line below `default x = [` or `init python:` is data, not a spoken line
            if in_skipped_block:
                continue
            if in_screen and not s.startswith("$"):        # the screen language is extracted by Ren'Py; only python lines (`$ ...`) can hide texts
                continue
            if s.startswith(STATEMENT_SKIP) or CHOICE_RE.match(line) or CHARACTER_DEF_RE.search(line):
                continue
            first = re.match(r"[A-Za-z_]\w*", s)
            if SAY_RE.match(line) and not (first and first.group(0) in NOT_A_SPEAKER):
                if in_data and line.startswith((" ", "\t")):
                    continue
                text = _literal(list(LITERAL_RE.finditer(line))[-1])
                if known_places:
                    without_block = (rel, no) not in known_places
                elif known_dialogue is not None:
                    without_block = text not in known_dialogue
                else:
                    continue
                if without_block and text not in known and text not in skip_texts and looks_like_text(text):
                    add(text, "dialogue", "likely", rel, no, s[:100])
                continue
            for m in LITERAL_RE.finditer(line):
                text = _literal(m)
                if text in known or text in skip_texts or not looks_like_text(text):
                    continue
                before = line[:m.start()]
                level = "likely" if (sink.search(before) or NAME_HINT_RE.search(before)) else "maybe"
                add(text, "text", level, rel, no, s[:100])
    items = sorted(found.values(), key=lambda i: (i["level"] != "likely", i["file"].lower(), i["line"]))
    return {"items": items[:limit], "truncated": len(items) > limit}


FILE_NAME = "extra_strings.rpy"


def _target_file(tl_dir, rel):
    """The translation file that mirrors the script `rel` (game/script2.rpy -> tl/<language>/script2.rpy) when it exists, else None."""
    if not rel or not rel.endswith(".rpy"):
        return None
    path = (tl_dir / rel).resolve()
    root = tl_dir.resolve()
    return path if (root in path.parents and path.is_file()) else None


def write_strings(tl_dir, language, items, backup_dir=None, into_files=False):
    """Add the chosen texts as `translate <language> strings:` blocks, with the original as the first translation (so they show up as
    untranslated). By default all of them go to `extra_strings.rpy`: one tidy place. With `into_files` (experimental) each text goes to the
    translation file that mirrors its script (script2.rpy -> tl/<language>/script2.rpy), so statistics by file and by group follow it; a text
    whose script has no translation file still goes to `extra_strings.rpy`. The place does not matter to the game: Ren'Py reads every strings
    block of every file. Texts already in the string table are not written twice. Returns {file, files: {path: count}, added, skipped}."""
    tl_dir = Path(tl_dir).resolve()                  # one spelling of the path (Windows short names such as RUNNER~1 differ otherwise)
    known = known_strings(tl_dir)
    targets, seen, skipped = {}, set(), 0
    for it in items:
        text = str(it.get("text", ""))
        if not text or text in known or text in seen:
            skipped += 1
            continue
        seen.add(text)
        rel = str(it.get("file", "")).replace("\\", "/")
        target = (_target_file(tl_dir, rel) if into_files else None) or (tl_dir / FILE_NAME)
        targets.setdefault(target, []).append({"text": text, "file": rel, "line": it.get("line", 0)})
    files = {}
    for path, entries in targets.items():
        old_text = path.read_bytes().decode("utf-8-sig", errors="replace") if path.is_file() else ""      # bytes: keep the line endings
        lines = [f"translate {language} strings:", ""]
        for f in entries:
            if f["file"]:
                lines.append(f"    # game/{f['file']}:{f['line']}")
            lines += [f'    old "{f["text"]}"', f'    new "{f["text"]}"', ""]
        nl = "\r\n" if "\r\n" in old_text else "\n"
        block = "\n".join(lines)
        new_text = (old_text.rstrip("\r\n") + "\n\n" if old_text.strip() else "") + block
        atomic_write_text(path, new_text, backup_dir=backup_dir, newline=nl)
        files[str(path.relative_to(tl_dir)).replace("\\", "/")] = len(entries)
    added = sum(files.values())
    return {"file": str(tl_dir / FILE_NAME), "files": files, "added": added, "skipped": skipped}



def suggest_functions(game_dir, known, functions=(), ignored=(), min_calls=3):
    """Functions of the game that are called again and again with a text as their first argument (`notify("Item added")`): the translator
    may add them to the project's list of functions that show text. Returns [{name, calls, example}], the most called first."""
    have = set(functions)
    skip_texts = set(ignored)
    count, example = {}, {}
    for path, rel in _scripts(game_dir):
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#") or s.startswith(STATEMENT_SKIP) or CHARACTER_DEF_RE.search(line):
                continue
            for m in CALL_RE.finditer(line):
                name = m.group(1)
                if "." in name or name in LIST_METHODS:        # methods of objects and lists are not "functions of the game"
                    continue
                if name in have or name in NOT_TEXT_FUNCTIONS or NOISE_NAME_RE.search(name) or name.split(".")[0] in {"renpy", "persistent", "store", "im", "config", "gui", "style"}:
                    continue
                lit = LITERAL_RE.match(line[m.end() - len(m.group(0)) + m.group(0).index("(") + 1:].lstrip())
                if not lit:
                    continue
                text = _literal(lit)
                if text in known or text in skip_texts or not looks_like_text(text) or " " not in text.strip():
                    continue
                count[name] = count.get(name, 0) + 1
                example.setdefault(name, text)
    out = [{"name": n, "calls": c, "example": example[n]} for n, c in count.items() if c >= min_calls]
    return sorted(out, key=lambda i: (-i["calls"], i["name"]))[:20]


SETTINGS_FILE = "missed.json"


def load_settings(data_dir):
    """{functions: [...], ignored: [...]} of the project (`<data dir>/missed.json`); a missing or damaged file means the defaults."""
    try:
        raw = json.loads((Path(data_dir) / SETTINGS_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}

    def strings(key):
        return sorted({str(x) for x in raw.get(key, []) if isinstance(x, str) and x}) if isinstance(raw.get(key), list) else []
    return {"functions": [f for f in strings("functions") if re.fullmatch(r"[A-Za-z_][\w.]*", f)], "ignored": strings("ignored")}


def save_settings(data_dir, functions, ignored):
    """Write the lists (sorted, without duplicates); returns what was saved."""
    clean = {"version": 1, "functions": sorted({f.strip() for f in functions if re.fullmatch(r"[A-Za-z_][\w.]*", str(f).strip())}),
             "ignored": sorted({str(t) for t in ignored if str(t)})}
    atomic_write_text(Path(data_dir) / SETTINGS_FILE, json.dumps(clean, ensure_ascii=False, indent=1) + "\n")
    return {"functions": clean["functions"], "ignored": clean["ignored"]}
