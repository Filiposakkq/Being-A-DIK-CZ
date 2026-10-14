"""Ren'Py aware validation of translated strings.

Reports *problems for a human to judge*; nothing is ever rewritten. Severities:
  error    Ren'Py would raise, or the script structure is broken (stray closing tag, unterminated
           [variable, variable that the source does not have, changed speaker / trailing code).
  warning  Suspicious and probably a mistake (a tag or variable of the source is missing,
           different tag arguments, changed number of \\n, unusual length).
  info     Frequently intentional in Czech (different count of {w} / {p} pauses, dropped {#...}).

The tokenizer follows Ren'Py's text rules instead of treating every brace as a tag:
`{{` and `[[` are escaped literals, `{}` is a positional placeholder of system strings,
`{#...}` is a comment/disambiguation tag, and only known tag names are checked for pairing.
Comparison is always *relative to the source*: an unclosed {i} that the English source also
leaves unclosed is not reported.
"""
import re
from collections import Counter
from dataclasses import dataclass, field

# Tags that must be closed.
PAIRED_TAGS = {"i", "b", "u", "s", "plain", "color", "size", "font", "a", "alpha", "k",
               "outlinecolor", "rb", "rt", "art", "cps", "language", "shader"}
# Tags that stand alone.
SINGLE_TAGS = {"w", "p", "nw", "fast", "done", "clear", "image", "space", "vspace"}
# Tags whose argument is part of the layout and should stay as in the source.
ARG_TAGS = {"color", "size", "font", "a", "alpha", "outlinecolor", "image", "space", "vspace", "cps", "k"}
FLOW_TAGS = {"nw", "fast", "done", "clear"}     # change how the line advances
PAUSE_TAGS = {"w", "p"}

PERCENT_RE = re.compile(r"%\(\w+\)[sdifr]|%[sdifr]")
ESCAPE_NL_RE = re.compile(r"\\n")


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    category: str = "syntax"      # syntax | structure | length
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return {"severity": self.severity, "code": self.code, "message": self.message,
                "category": self.category, **self.extra}


@dataclass
class Tokens:
    open_tags: list = field(default_factory=list)    # (name, arg, full)
    close_tags: list = field(default_factory=list)   # name
    singles: list = field(default_factory=list)      # (name, full)
    comments: list = field(default_factory=list)     # {#...}
    unknown: list = field(default_factory=list)      # full text of unknown tags
    variables: list = field(default_factory=list)    # full expression inside [...]
    placeholders: int = 0                            # '{}' positional placeholders
    percents: list = field(default_factory=list)
    order: list = field(default_factory=list)        # ('open'|'close', name) in text order
    problems: list = field(default_factory=list)     # (code, message) syntax problems of this text


def tokenize(text):
    t = Tokens()
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            if text.startswith("{{", i):
                i += 2
                continue
            j = text.find("}", i + 1)
            if j == -1:
                t.problems.append(("unterminated-tag", "Neukončená značka – chybí „}“."))
                break
            body = text[i + 1:j]
            full = text[i:j + 1]
            i = j + 1
            if body == "":
                t.placeholders += 1
            elif body.startswith("#"):
                t.comments.append(full)
            elif body.startswith("/"):
                name = body[1:].strip()
                t.close_tags.append(name)
                t.order.append(("close", name, full))
            else:
                name, _, arg = body.partition("=")
                name = name.strip()
                if name in PAIRED_TAGS:
                    t.open_tags.append((name, arg, full))
                    t.order.append(("open", name, full))
                elif name in SINGLE_TAGS:
                    t.singles.append((name, full))
                else:
                    t.unknown.append(full)
            continue
        if ch == "[":
            if text.startswith("[[", i):
                i += 2
                continue
            depth, j = 1, i + 1
            while j < n and depth:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                j += 1
            if depth:
                t.problems.append(("unterminated-variable", "Neukončená proměnná – chybí „]“."))
                break
            t.variables.append(text[i + 1:j - 1].strip())
            i = j
            continue
        if ch == "}" or ch == "]":
            i += 1
            continue
        i += 1
    t.percents = PERCENT_RE.findall(text)
    return t


def nesting_problems(tok):
    """Problems with the order of paired tags: stray / mismatched closers (errors) and
    unclosed openers (warnings). Returns [(severity, code, tagname)]."""
    out, stack = [], []
    for kind, name, _full in tok.order:
        if kind == "open":
            stack.append(name)
        elif not stack:
            out.append(("error", "stray-close", name))
        elif stack[-1] != name:
            out.append(("error", "mismatched-close", name))
            if name in stack:
                while stack and stack.pop() != name:
                    pass
        else:
            stack.pop()
    for name in stack:
        out.append(("warning", "unclosed", name))
    return out


def _var_base(expr):
    return re.split(r"[!:]", expr, maxsplit=1)[0].strip()


def check_text(source, target):
    """Compare a translation with its source. Returns [Issue]."""
    issues = []
    s, t = tokenize(source), tokenize(target)

    for code, msg in t.problems:
        if (code, msg) not in s.problems:
            issues.append(Issue("error", code, msg))

    # ---- nesting of paired tags (only what is new compared with the source)
    src_nest = Counter((c, n) for _sev, c, n in nesting_problems(s))
    tgt_nest = Counter()
    for sev, code, name in nesting_problems(t):
        tgt_nest[(code, name)] += 1
        if tgt_nest[(code, name)] > src_nest.get((code, name), 0):
            if code == "stray-close":
                issues.append(Issue("error", code, f"Závěrečná značka {{/{name}}} nemá odpovídající otevírací."))
            elif code == "mismatched-close":
                issues.append(Issue("error", code, f"Značka {{/{name}}} je zavřena ve špatném pořadí (špatné zanoření)."))
            else:
                issues.append(Issue("warning", code, f"Značka {{{name}}} není zavřená, ale v originálu ano."
                                    if name in s.close_tags else f"Značka {{{name}}} není zavřená."))

    # ---- paired tags: counts
    so, to = Counter(n for n, _a, _f in s.open_tags), Counter(n for n, _a, _f in t.open_tags)
    sc, tc = Counter(s.close_tags), Counter(t.close_tags)
    for name in sorted(set(so) | set(to) | set(sc) | set(tc)):
        if name not in PAIRED_TAGS:
            if tc[name] > sc[name]:
                issues.append(Issue("warning", "unknown-close-tag", f"Neznámá závěrečná značka {{/{name}}}."))
            continue
        if to[name] < so[name]:
            issues.append(Issue("warning", "tag-missing", f"V překladu chybí značka {{{name}}} (originál ji má {so[name]}×, překlad {to[name]}×)."))
        elif to[name] > so[name]:
            issues.append(Issue("warning", "tag-extra", f"Překlad má značku {{{name}}} navíc ({to[name]}× proti {so[name]}× v originále)."))
        if tc[name] < sc[name] and to[name] >= so[name]:
            issues.append(Issue("warning", "close-missing", f"V překladu chybí závěrečná značka {{/{name}}}."))

    # ---- tag arguments (color=, size=, font=, a=...) should match the source
    src_args = Counter(f.replace(" ", "") for n, a, f in s.open_tags if n in ARG_TAGS and a)
    tgt_args = Counter(f.replace(" ", "") for n, a, f in t.open_tags if n in ARG_TAGS and a)
    for full, c in (tgt_args - src_args).items():
        # only report when the same tag name exists on both sides, otherwise tag-missing/extra covers it
        name = full[1:].split("=", 1)[0]
        if so[name] and to[name]:
            issues.append(Issue("warning", "tag-arg", f"Argument značky {full} se liší od originálu."))

    # ---- single tags
    ss, ts = Counter(n for n, _f in s.singles), Counter(n for n, _f in t.singles)
    for name in sorted(set(ss) | set(ts)):
        if ss[name] == ts[name]:
            continue
        if name in FLOW_TAGS:
            sev = "warning"
        elif name in PAUSE_TAGS:
            sev = "info"
        else:
            sev = "warning"
        issues.append(Issue(sev, "single-tag", f"Počet značek {{{name}}} se liší (originál {ss[name]}×, překlad {ts[name]}×)."))

    # ---- unknown tags that appear only in the translation
    for full in sorted(set(t.unknown) - set(s.unknown)):
        issues.append(Issue("warning", "unknown-tag", f"Neznámá značka {full} (není v originálu) – překlep?"))

    # ---- {#...} disambiguation comments
    if Counter(s.comments) != Counter(t.comments) and s.comments:
        issues.append(Issue("info", "comment-tag", "Značka {#…} z originálu v překladu chybí nebo se liší (Ren'Py ji při zobrazení ignoruje)."))

    # ---- positional {} placeholders of system strings
    if s.placeholders != t.placeholders:
        issues.append(Issue("error", "placeholder", f"Počet zástupných {{}} se liší (originál {s.placeholders}×, překlad {t.placeholders}×)."))

    # ---- [variables]
    sv, tv = Counter(s.variables), Counter(t.variables)
    s_bases = {_var_base(v) for v in s.variables}
    for expr in sorted(set(tv) - set(sv)):
        if _var_base(expr) not in s_bases:
            issues.append(Issue("error", "variable-unknown", f"Proměnná [{expr}] není v originálu – překlep? Hra by mohla spadnout."))
        else:
            issues.append(Issue("warning", "variable-changed", f"Proměnná [{expr}] se liší od originálu (např. jiný příznak)."))
    for expr in sorted(set(sv) - set(tv)):
        if _var_base(expr) not in {_var_base(v) for v in t.variables}:
            issues.append(Issue("warning", "variable-missing", f"V překladu chybí proměnná [{expr}]."))
    for expr in sorted(set(sv) & set(tv)):
        if tv[expr] > sv[expr]:
            issues.append(Issue("info", "variable-repeat", f"Proměnná [{expr}] je v překladu {tv[expr]}× (originál {sv[expr]}×)."))
        elif tv[expr] < sv[expr]:
            issues.append(Issue("info", "variable-fewer", f"Proměnná [{expr}] je v překladu {tv[expr]}× (originál {sv[expr]}×)."))

    # ---- %-formats of system strings ("Page %s")
    if Counter(s.percents) != Counter(t.percents):
        issues.append(Issue("error", "percent-format", f"Formátovací značky % se liší (originál {', '.join(s.percents) or '—'}, překlad {', '.join(t.percents) or '—'})."))

    # ---- escapes
    if len(ESCAPE_NL_RE.findall(source)) != len(ESCAPE_NL_RE.findall(target)):
        issues.append(Issue("warning", "newline-count",
                            f"Počet zalomení \\n se liší (originál {len(ESCAPE_NL_RE.findall(source))}×, překlad {len(ESCAPE_NL_RE.findall(target))}×)."))
    stripped = re.sub(r"\\.", "", target)
    if stripped.endswith("\\") or "\\" in stripped:
        issues.append(Issue("error", "bad-escape", "Osamocený zpětný lomítko „\\“ – neplatná escape sekvence."))
    return issues


def visible_length(text):
    """Characters a player would see: tags removed, variables counted as a short name."""
    out = re.sub(r"\{\{", "{", text)
    out = re.sub(r"\{[^}]*\}", "", out)
    out = re.sub(r"\[\[", "[", out)
    out = re.sub(r"\[[^\]]*\]", "XXXXX", out)
    out = out.replace("\\n", " ").replace('\\"', '"')
    return len(re.sub(r"\s+", " ", out).strip())


LENGTH_DEFAULTS = {"enabled": True, "min_source_chars": 12, "max_ratio": 2.2, "min_ratio": 0.45,
                   "min_extra_chars": 25, "min_missing_chars": 18}


def check_length(source, target, cfg=None):
    """Optional review aid: unusually long / short translation. Never an error."""
    c = dict(LENGTH_DEFAULTS, **(cfg or {}))
    if not c["enabled"]:
        return []
    ls, lt = visible_length(source), visible_length(target)
    if ls < c["min_source_chars"] or lt == 0:
        return []
    ratio = lt / ls
    extra = {"ratio": round(ratio, 2), "source_len": ls, "target_len": lt}
    if ratio > c["max_ratio"] and lt - ls >= c["min_extra_chars"]:
        return [Issue("warning", "length-long", f"Překlad je výrazně delší než originál ({lt} vs {ls} znaků, {ratio:.1f}×). Česky bývá text delší, ale tohle je hodně.",
                      category="length", extra=extra)]
    if ratio < c["min_ratio"] and ls - lt >= c["min_missing_chars"]:
        return [Issue("warning", "length-short", f"Překlad je výrazně kratší než originál ({lt} vs {ls} znaků, {ratio:.1f}×). Nechybí část textu?",
                      category="length", extra=extra)]
    return []


def check_entry(entry, length_cfg=None):
    """All issues for one parsed Entry (see rpy.Entry). Untranslated lines are not validated."""
    if entry.pending and entry.category:
        return []
    issues = []
    if entry.source is None:
        return issues
    # structure: speaker / attributes / trailing code must stay as in the comment
    if entry.unit == "dialogue":
        if " ".join(entry.who.split()) != " ".join(entry.src_who.split()):
            issues.append(Issue("error", "speaker-changed",
                                f"Mluvčí / atributy se liší od originálu: „{entry.src_who}“ → „{entry.who}“.",
                                category="structure"))
        if " ".join(entry.suffix.split()) != " ".join(entry.src_suffix.split()):
            issues.append(Issue("error", "suffix-changed",
                                f"Kód za textem se liší od originálu: „{entry.src_suffix}“ → „{entry.suffix}“.",
                                category="structure"))
    if entry.target.strip() == "" and entry.source.strip() != "":
        return issues
    issues += check_text(entry.source, entry.target)
    issues += check_length(entry.source, entry.target, length_cfg)
    return issues


def check_parsed(parsed, length_cfg=None):
    """Issues for a whole ParsedFile: [(line, Issue, entry|None)] sorted by line."""
    out = []
    for e in parsed.entries:
        for iss in check_entry(e, length_cfg):
            out.append((e.line, iss, e))
    for line, code, msg in parsed.structure:
        out.append((line, Issue("error", code, msg, category="structure"), None))
    out.sort(key=lambda r: r[0])
    return out
