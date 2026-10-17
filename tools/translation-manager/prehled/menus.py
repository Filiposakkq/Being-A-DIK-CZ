"""Menus of a Ren'Py script: which lines are choices, what question they answer and what follows each of them.

A menu in the game script looks like

    menu:
        "What do you say?"           <- optional question (a line of dialogue)
        "Invite her" if met_her:     <- a choice, maybe with a condition
            mc "Coffee?"             <- its body: the first lines of dialogue show what the choice means
            jump cafe
        "Leave":
            ...

The translation of a choice sits in `translate <lang> strings:` (far from the dialogue), so the translator needs the menu around it.
This module only reads the script text; it finds nothing it cannot see (no jumps, no `call screen`, no menus built in Python).
"""
import re

OPTION_RE = re.compile(r"""^\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')\s*(?:\bif\b\s+(.+?))?\s*:\s*(?:#.*)?$""")
MENU_RE = re.compile(r"^\s*menu(?:\s+\w+)?\s*(?:\(.*\))?\s*:\s*(?:#.*)?$")
# a line of dialogue: `"text"`, or `who "text"`, or `who attr attr "text" with x`; not a statement that merely contains a string
SAY_RE = re.compile(r"""^\s*(?:[A-Za-z_][\w.]*(?:\s+[\w@.]+)*\s+)?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*(?:with\s+.+)?$""")
NOT_SAY = {"if", "elif", "else", "while", "for", "show", "scene", "hide", "play", "stop", "queue", "with", "image", "define", "default", "label", "jump", "call",
           "return", "pass", "python", "init", "screen", "transform", "style", "translate", "window", "pause", "voice", "renpy", "camera", "text", "menu", "$"}
BODY_LINES = 4            # first lines of the body of a choice kept as they are (what a choice does when no dialogue follows)
AFTER_LINES = 2           # lines of dialogue shown after each choice
BEFORE_LINES = 2          # lines of dialogue shown before a menu that has no question of its own
LOOK_BACK = 60


def indent_of(text):
    return len(text) - len(text.lstrip(" \t"))


def blank(text):
    s = text.strip()
    return not s or s.startswith("#")


def is_say(text):
    if blank(text) or not SAY_RE.match(text):
        return False
    first = text.strip().split(None, 1)[0].rstrip(":").lower()
    return first not in NOT_SAY


def literal_of(text):
    """The text between the quotes of the first string literal of a line."""
    m = re.search(r"""(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""", text)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else ""


def _said_before(lines, head):
    """The last lines of dialogue before the menu on line index `head`, on the way the story reaches it: lines of the same block, and, when the
    menu is the first thing in an `if` / `else` block, the lines before that `if` (the body of an earlier branch or of an earlier menu is skipped)."""
    out, level = [], indent_of(lines[head])
    for i in range(head - 1, max(-1, head - 1 - LOOK_BACK), -1):
        text = lines[i]
        if blank(text):
            continue
        ind = indent_of(text)
        if ind > level:
            continue
        if ind < level:
            if re.match(r"\s*(?:if|elif|else|while|for|with)\b", text):
                level = ind
                continue
            break
        if is_say(text):
            out.insert(0, i + 1)
            if len(out) >= BEFORE_LINES:
                break
        elif MENU_RE.match(text) or re.match(r"\s*label\b", text):
            break
    return out


def menu_around(lines, line, choice=None):
    """The menu a line of the script is part of, or None: the choice itself (see find_menu), the question, the first lines of the body of a
    choice, or the lines said just before the menu. Only lines that the menu shows count."""
    found = find_menu(lines, line, choice)
    if found or not 1 <= line <= len(lines) or not is_say(lines[line - 1]):
        return found
    head, own = None, indent_of(lines[line - 1])
    for i in range(line - 2, max(-1, line - 2 - 400), -1):          # inside a menu: the first ancestor that is the menu or one of its choices
        if blank(lines[i]):
            continue
        ind = indent_of(lines[i])
        if ind >= own:
            continue
        if MENU_RE.match(lines[i]):
            head = i
            break
        if OPTION_RE.match(lines[i]):
            inner = find_menu(lines, i + 1)
            head = inner["menu_line"] - 1 if inner else None
            break
        if re.match(r"\s*label\b", lines[i]):
            break
        own = ind                                                    # an `if` inside the choice: keep going up
    if head is None:                                                 # said just before a menu
        seen = 0
        for i in range(line, min(len(lines), line + 80)):
            if blank(lines[i]):
                continue
            seen += 1
            if seen > 10 or re.match(r"\s*label\b", lines[i]):
                break
            if MENU_RE.match(lines[i]):
                head = i
                break
    inner = find_menu(lines, head + 1) if head is not None else None
    if inner and line in inner["question"] + inner["before"] + [n for o in inner["options"] for n in o["after"]]:
        return inner
    return None


def find_menu(lines, line, choice=None):
    """The menu a choice belongs to, or None. `line` (1-based) is where Ren'Py recorded the choice: the line of the choice itself, or (Ren'Py 7 and
    others) the line of the `menu:` statement, the same for all its choices; `choice` is the original text of the choice, which then tells which one it is.
    {menu_line, question:[line numbers], before:[line numbers], options:[{n, text, cond, after:[line numbers]}], current: index of the choice}."""
    if not 1 <= line <= len(lines):
        return None
    head = None
    if MENU_RE.match(lines[line - 1]):
        head = line - 1
    elif OPTION_RE.match(lines[line - 1]):
        own = indent_of(lines[line - 1])
        for i in range(line - 2, max(-1, line - 2 - 400), -1):      # up to the `menu:` line: the first line with less indent
            if blank(lines[i]):
                continue
            if indent_of(lines[i]) < own:
                head = i if MENU_RE.match(lines[i]) else None
                break
    if head is None:
        return None
    level = next((indent_of(x) for x in lines[head + 1:] if not blank(x)), indent_of(lines[head]) + 1)
    if level <= indent_of(lines[head]):
        return None
    question, options = [], []
    for i in range(head + 1, len(lines)):
        text = lines[i]
        if blank(text):
            continue
        ind = indent_of(text)
        if ind < level:
            break
        if ind == level:
            m = OPTION_RE.match(text)
            if m:
                options.append({"n": i + 1, "text": m.group(1) if m.group(1) is not None else m.group(2), "cond": m.group(3) or "", "after": [], "body": []})
            elif not options and is_say(text):
                question.append(i + 1)
        elif options:
            if len(options[-1]["body"]) < BODY_LINES:
                options[-1]["body"].append(text.rstrip())
        if ind > level and options and len(options[-1]["after"]) < AFTER_LINES:
            if MENU_RE.match(text):                                   # a menu inside a choice: its lines are not this choice's
                options[-1]["after"].append(0)
            elif is_say(text) and 0 not in options[-1]["after"]:
                options[-1]["after"].append(i + 1)
    for o in options:
        o["after"] = [n for n in o["after"] if n]
    before = _said_before(lines, head) if not question else []     # a menu without a question: the lines said just before it give the context
    cur = next((k for k, o in enumerate(options) if o["n"] == line), -1)
    if cur < 0 and choice is not None:
        want = " ".join(str(choice).split())
        cur = next((k for k, o in enumerate(options) if " ".join(o["text"].split()) == want), -1)
    return {"menu_line": head + 1, "question": question, "before": before, "options": options, "current": cur}
