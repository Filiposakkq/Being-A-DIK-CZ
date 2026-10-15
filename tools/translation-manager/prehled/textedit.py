"""Text-level helpers for batch edits of translations: find / replace and the "safe fixes" that change only the text.

Everything here is pure (no file access): it turns a translated text into a proposed new text. Writing is done by
fixes.apply_edits after the user confirmed a preview. Tags `{i}`, variables `[name]` and escapes (`\\n`, `\\"`) are
protected by default, so a replacement can never break them.

What is deliberately NOT automated: variables and tags that are missing, extra or in a different order. In Czech the
word order often differs from English, so those findings are frequently false positives; they can only be ignored
or fixed by hand.
"""
import re

from . import validator

TOKEN_RE = re.compile(r"\{[^}]*\}|\[[^\]]*\]|\\.")      # tag, variable, escape
LETTER = r"[^\W\d_]"
MODES = ("plain", "word", "stem", "regex")


def mask(text):
    """Same length, with protected parts replaced by NUL so no pattern can match inside them."""
    return TOKEN_RE.sub(lambda m: "\x00" * len(m.group()), text)


def _case_like(model, new):
    if model[:1].isupper() and new[:1].islower():
        return new[:1].upper() + new[1:]
    return new


def sub_pattern(pattern, repl, text, protect=True, limit=0):
    """Apply a compiled `pattern` outside protected parts. `repl` is a function(match) -> str. Returns (new, count)."""
    hay = mask(text) if protect else text
    out, last, n = [], 0, 0
    for m in pattern.finditer(hay):
        if m.end() == m.start() or "\x00" in m.group():
            continue
        out.append(text[last:m.start()])
        out.append(repl(m))
        last, n = m.end(), n + 1
        if limit and n >= limit:
            break
    out.append(text[last:])
    return "".join(out), n


def stem_of(word):
    return word[:max(3, len(word) - 2)]


def make_replacer(find, replace, mode="plain", case=False):
    """Returns f(text, protect=True) -> (new_text, count). Raises ValueError for an unusable search."""
    if not find:
        raise ValueError("Zadej, co hledat.")
    if len(find) > 300 or len(replace) > 2000:
        raise ValueError("Hledaný nebo nahrazující text je příliš dlouhý.")
    if mode not in MODES:
        raise ValueError("Neznámý režim hledání.")
    flags = 0 if case else re.IGNORECASE
    if mode == "regex":
        try:
            pat = re.compile(find, flags | re.UNICODE)
            re.compile(pat.pattern).sub(replace, "test")        # reject bad group references early
        except re.error as e:
            raise ValueError(f"Neplatný regulární výraz: {e}") from e

        def rx(m):
            try:
                return m.expand(replace)
            except (re.error, IndexError) as e:
                raise ValueError(f"Neplatná náhrada: {e}") from e
        return lambda text, protect=True: sub_pattern(pat, rx, text, protect)
    if mode == "stem":
        if not re.fullmatch(LETTER + "{4,}", find) or not re.fullmatch(LETTER + "{2,}", replace):
            raise ValueError("Režim „podle kmene“ je jen pro jedno slovo (aspoň 4 písmena) a jedno nahrazující slovo.")
        stem = stem_of(find)
        pat = re.compile(f"(?<!{LETTER})({re.escape(stem)})({LETTER}*)", flags | re.UNICODE)
        new_stem = stem_of(replace)

        def st(m):
            whole = m.group(0)
            if whole.lower().startswith(find.lower()):
                new = replace + whole[len(find):]               # the whole word as typed, plus any ending after it
            else:
                new = new_stem + whole[len(stem):]              # another form: keep its ending, swap the stem
            return _case_like(whole, new)
        return lambda text, protect=True: sub_pattern(pat, st, text, protect)
    body = re.escape(find)
    if mode == "word":
        body = f"(?<!{LETTER}){body}(?!{LETTER})"
    pat = re.compile(body, flags | re.UNICODE)
    return lambda text, protect=True: sub_pattern(pat, lambda m: replace, text, protect)


# ---------------------------------------------------------------- safe fixes that only change the text

def fix_spaces(source, target):
    """Collapse runs of spaces between words, unless the original has them too. Returns the new text or None."""
    probe = re.compile(r"\S {2,}\S")
    if not probe.search(target) or probe.search(source):
        return None
    new, n = sub_pattern(re.compile(r"(?<=\S) {2,}(?=\S)"), lambda m: " ", target, True)
    return new if n and new != target else None


def fix_typos(spell, source, target):
    """Apply the spelling hints (missing diacritics, swapped / doubled letters) to the text.
    Returns (new_text, [(word, better, kind)]) or None."""
    if spell is None:
        return None
    new, done = target, []
    for iss in spell.check(source, target):
        w, better = iss.extra.get("word"), iss.extra.get("better")
        if not w or not better:
            continue
        pat = re.compile(f"(?<!{LETTER}){re.escape(w)}(?!{LETTER})", re.IGNORECASE | re.UNICODE)
        changed, n = sub_pattern(pat, lambda m: _case_like(m.group(0), better), new, True, limit=1)
        if n:
            new = changed
            done.append((w, better, iss.extra.get("typo_kind", "")))
    return (new, done) if done else None


def plan_text_fixes(project, spell, kinds, wanted=None, file=""):
    """Proposed text fixes: [{file, line, kind, before, after, default, note}] for the kinds "spaces" and "typo".
    `wanted` = {(file, line)} limits the plan. Untranslated lines are never touched."""
    out = []
    for rel in sorted(project.files, key=str.lower):
        if file and rel != file:
            continue
        for e in project.entries(rel):
            if e.unit not in ("dialogue", "string") or e.source is None or (e.pending and e.category) or not e.target:
                continue
            if wanted is not None and (rel, e.line) not in wanted:
                continue
            if "spaces" in kinds:
                new = fix_spaces(e.source, e.target)
                if new is not None:
                    out.append({"file": rel, "line": e.line, "kind": "spaces", "before": e.target, "after": new,
                                "default": True, "note": "dvojitá mezera"})
            if "typo" in kinds:
                res = fix_typos(spell, e.source, e.target)
                if res is not None:
                    new, done = res
                    sure = all(k == "diacritics" and len(w) >= 6 for w, _b, k in done)
                    out.append({"file": rel, "line": e.line, "kind": "typo", "before": e.target, "after": new,
                                "default": sure, "note": "; ".join(f"{w} → {b}" for w, b, _k in done)})
    return out


def chain_fixes(spell, source, target, kinds):
    """Apply the chosen text fixes one after another to the same text (spaces first, then typos)."""
    text = target
    if "spaces" in kinds:
        new = fix_spaces(source, text)
        text = new if new is not None else text
    if "typo" in kinds:
        res = fix_typos(spell, source, text)
        text = res[0] if res else text
    return text
