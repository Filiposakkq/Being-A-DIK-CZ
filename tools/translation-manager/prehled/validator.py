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

from .util import fold

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
    category: str = "syntax"      # syntax | structure | length | text
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


# ---------------------------------------------------------------- text quality checks (category "text")
# Common English function words that are not Czech words; "i", "most", "had" are Czech too and interjections
# (hello, okay...) are often kept on purpose, so neither counts.
_NOT_ENGLISH_EVIDENCE = {"i", "most", "had", "yes", "okay", "ok", "oh", "hey", "hi", "hello", "please", "thanks",
                         "thank", "sorry", "well", "right", "really", "maybe", "being"}
ENGLISH_EVIDENCE = None     # filled lazily from rpy.EN_WORDS (avoids an import cycle at module load)
_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)
_REPEAT_RE = re.compile(r"\b([^\W\d_]{2,})\s+\1\b", re.IGNORECASE | re.UNICODE)
# words that are legitimately doubled in Czech speech ("to to je", "tak tak", "ne ne")
REPEAT_OK = {"to", "tak", "ne", "no", "ať", "jo", "hej", "ha", "ah", "se", "si", "že", "jak", "co", "ani", "už",
             "ale", "čuk", "haha", "hihi", "ho", "bla", "ještě", "moc", "hodně", "hrozně", "pořád", "dobře", "fajn", "ok", "hmm", "ach"}


def plain_text(text):
    """What the player reads: tags and [variables] removed, \n as a space."""
    out = re.sub(r"\{\{", "{", text)
    out = re.sub(r"\{[^}]*\}", "", out)
    out = re.sub(r"\[\[", "[", out)
    out = re.sub(r"\[[^\]]*\]", " ", out)
    return out.replace("\\n", " ").replace('\\"', '"')


def check_quality(source, target):
    """Cheap human-error checks on the visible text. Always relative to the source; warnings only."""
    global ENGLISH_EVIDENCE
    if ENGLISH_EVIDENCE is None:
        from .rpy import EN_WORDS
        ENGLISH_EVIDENCE = set(EN_WORDS) - _NOT_ENGLISH_EVIDENCE
    issues = []
    ps, pt = plain_text(source), plain_text(target)

    # numbers must survive the translation
    ns, nt = Counter(re.findall(r"\d+", ps)), Counter(re.findall(r"\d+", pt))
    if ns != nt:
        # a number written out in words ("14" -> "čtrnáct") is normal Czech; changed digits are suspicious
        sev = "info" if ns and not nt else "warning"
        issues.append(Issue(sev, "numbers-differ",
                            f"Čísla se liší od originálu (originál: {', '.join(sorted(ns.elements())) or '—'}; "
                            f"překlad: {', '.join(sorted(nt.elements())) or '—'}).", category="text"))

    # double spaces inside the text
    if re.search(r"\S {2,}\S", target) and not re.search(r"\S {2,}\S", source):
        issues.append(Issue("warning", "double-space", "V překladu je dvojitá mezera.", category="text",
                            extra={"fixable": True, "kind": "spaces"}))

    # the same word twice in a row (typo), unless the source does it as well or Czech does it normally
    src_rep = {m.group(1).lower() for m in _REPEAT_RE.finditer(ps)}
    for m in _REPEAT_RE.finditer(pt):
        w = m.group(1).lower()
        if w not in REPEAT_OK and w not in src_rep:
            issues.append(Issue("warning", "repeated-word", f"Dvakrát za sebou stejné slovo: „{w} {w}“.", category="text"))
            break

    # English left in a translated line
    words = [w.lower() for w in _WORD_RE.findall(pt)]
    hits = [w for w in words if w in ENGLISH_EVIDENCE]
    if len(hits) >= 3 or (len(hits) >= 2 and len(hits) / max(1, len(words)) >= 0.4):
        issues.append(Issue("warning", "english-left",
                            f"V překladu zůstala angličtina ({', '.join(sorted(set(hits))[:5])}). Nezapomněl/a ses část nepřeložit?",
                            category="text"))
    return issues


def _stem(word):
    folded = fold(word)
    return folded[:max(3, len(folded) - 2)]


def term_in_text(text, term):
    """Does the English `term` occur in `text` as a whole word (case-insensitive)?"""
    return bool(term) and bool(re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", plain_text(text).lower()))


def term_used(target, czech):
    """Is the Czech form of a glossary term present in the translation (any ending, matched by word stem)?"""
    cz_stems = [_stem(w) for w in _WORD_RE.findall(czech)]
    if not cz_stems:
        return True
    t_stems = {_stem(w) for w in _WORD_RE.findall(plain_text(target))}
    return all(any(len(ts) >= 3 and (ts.startswith(cs) or cs.startswith(ts)) for ts in t_stems) for cs in cz_stems)


def check_terms(source, target, terms):
    """Glossary terms: when the original uses the English term, the translation should use the Czech one
    (any ending). `terms` = {english: czech}. Info only – Czech declension makes this approximate."""
    issues = []
    for en, cz in terms.items():
        if en and cz and term_in_text(source, en) and not term_used(target, cz):
            issues.append(Issue("info", "term-inconsistent",
                                f"Termín „{en}“ se ve Slovníku překládá jako „{cz}“, ale v překladu to nevidím.", category="text"))
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


TEXTBOX_DEFAULTS = {"enabled": True, "chars_per_line": 65, "max_lines": 4}


def lines_needed(text, per_line):
    """Lines a text takes in the dialogue box: explicit \\n breaks plus greedy word wrap at `per_line` characters."""
    out = re.sub(r"\{\{", "{", text)
    out = re.sub(r"\{[^}]*\}", "", out)
    out = re.sub(r"\[\[", "[", out)
    out = re.sub(r"\[[^\]]*\]", "XXXXX", out)
    total = 0
    for seg in out.replace('\\"', '"').split("\\n"):
        line_len, n = 0, 1
        for w in seg.split():
            need = len(w) + (1 if line_len else 0)
            if line_len + need > per_line and line_len:
                n += 1
                line_len = len(w)
            else:
                line_len += need
        total += n
    return total


def check_textbox(source, target, cfg=None):
    """Will the translation fit the dialogue box? Defaults come from the game's gui.rpy (box text width 1116 px at
    33 px font ≈ 65 characters per line, about 4 lines). Only reported when the translation needs more lines than
    the limit AND more than the original did (an original that already overflows is the game's own problem)."""
    c = dict(TEXTBOX_DEFAULTS, **(cfg or {}))
    if not c["enabled"] or not c["chars_per_line"] or not c["max_lines"]:
        return []
    ls, lt = lines_needed(source, c["chars_per_line"]), lines_needed(target, c["chars_per_line"])
    if lt > c["max_lines"] and lt > ls:
        return [Issue("warning", "textbox-overflow",
                      f"Text se nemusí vejít do okna dialogu: asi {lt} řádků (limit {c['max_lines']}, originál {ls}). "
                      f"Zkrať ho, nebo ho rozděl pomocí {{p}}.", category="length",
                      extra={"lines": lt, "limit": c["max_lines"]})]
    return []


def check_entry(entry, length_cfg=None, terms=None, spell=None, textbox=None):
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
                                category="structure", extra={"fixable": True, "kind": "speaker"}))
        if " ".join(entry.suffix.split()) != " ".join(entry.src_suffix.split()):
            issues.append(Issue("error", "suffix-changed",
                                f"Kód za textem se liší od originálu: „{entry.src_suffix}“ → „{entry.suffix}“.",
                                category="structure", extra={"fixable": True, "kind": "speaker"}))
    if entry.target.strip() == "" and entry.source.strip() != "":
        return issues
    issues += check_text(entry.source, entry.target)
    issues += check_length(entry.source, entry.target, length_cfg)
    issues += check_quality(entry.source, entry.target)
    if terms:
        issues += check_terms(entry.source, entry.target, terms)
    if spell is not None:
        issues += spell.check(entry.source, entry.target)
    if entry.unit == "dialogue":
        issues += check_textbox(entry.source, entry.target, textbox)
    return issues


def check_parsed(parsed, length_cfg=None, terms=None, spell=None, textbox=None):
    """Issues for a whole ParsedFile: [(line, Issue, entry|None)] sorted by line."""
    out = []
    for e in parsed.entries:
        for iss in check_entry(e, length_cfg, terms, spell, textbox):
            out.append((e.line, iss, e))
    for line, code, msg in parsed.structure:
        out.append((line, Issue("error", code, msg, category="structure"), None))
    out.sort(key=lambda r: r[0])
    return out
