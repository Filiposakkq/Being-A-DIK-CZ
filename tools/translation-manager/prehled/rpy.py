"""Parser for Ren'Py translation files (game/tl/<language>/*.rpy).

A *translation unit* is either
  - a dialogue block:   translate czech <id>:  + `# who "source"` comment + `who "target"` line, or
  - a strings pair:     old "source" / new "target"  inside `translate czech strings:`.

`parse_text` returns every unit as an Entry. A unit is *pending* (not yet translated) when its
code line equals the source comment (or `new` equals `old`, or `new ""`). That is the same rule
the original tool used, so the counts stay comparable with historie.csv.
"""
import hashlib
import re
from dataclasses import dataclass, field

from .util import norm_ws

OLD_RE = re.compile(r'^\s*old\s+"(.*)"\s*$')
NEW_RE = re.compile(r'^\s*new\s+"(.*)"\s*$')
TRANSLATE_RE = re.compile(r"^translate\s+(\w+)\s+(\w+)\s*:\s*$")
GAME_REF_RE = re.compile(r"^(game/\S+?:\d+)\s*$")
STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
TAG_RE = re.compile(r"\{[^}]*\}|\[[^\]]*\]")
WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")
LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")

# Statement keywords that start lines containing quotes but are not dialogue.
NON_TEXT = {"voice", "play", "queue", "stop", "show", "hide", "scene", "with", "window",
            "nvl", "pause", "call", "jump", "return", "image", "transform", "define",
            "default", "python", "renpy", "camera", "if", "elif", "else", "while", "menu"}

# Lines made only of symbols ("...", "?!") are dialogue but cannot be translated.
# True = count them as translated, False = count them as untranslated (original behaviour).
COUNT_SYMBOL_ONLY_AS_DONE = False

# Common English words (without those that also exist in Czech: a, to, on, no, do, by, my, he, me...)
EN_WORDS = set("""
the and you your yours is are was were be been being am i i'm i'll i've i'd it it's its
that this these those what who whom whose which when where why how not don't doesn't didn't
can't won't isn't aren't wasn't couldn't wouldn't shouldn't have has had having will would
could should shall may might must of in for with at from about into over after before
but or so if then than too very just only also all any some more most much many each every
she her hers him his they them their we us our there here out up down off again
get got go going gone know think want need like see say said tell let come make take look
yes okay ok well oh hey hi hello please thanks thank sorry right really maybe
you're we're they're he's she's that's what's there's let's
""".split())
DIACRITICS = set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")

K_EMPTY = "Prázdný překlad"
K_ENGLISH = "Anglicky (nepřeloženo?)"
K_SAME = "Shodné – možná OK"
K_SYMBOLS = "Jen znaky (…, ?!)"
KIND_RANK = {K_EMPTY: 0, K_ENGLISH: 1, K_SAME: 2, K_SYMBOLS: 3}
KIND_CODE = {K_EMPTY: "empty", K_ENGLISH: "english", K_SAME: "same", K_SYMBOLS: "symbols"}


def classify(text):
    """Category of a pending (identical / empty) line based on its content."""
    if text.strip() == "":
        return K_EMPTY
    plain = TAG_RE.sub(" ", text).replace("\\n", " ").replace("’", "'")
    words = WORD_RE.findall(plain)
    if not words:
        return K_SYMBOLS
    if any(ch in DIACRITICS for ch in plain):
        return K_SAME
    hits = sum(1 for w in words if w.lower() in EN_WORDS)
    if hits or len(words) >= 5:
        return K_ENGLISH
    return K_SAME


@dataclass
class Entry:
    line: int            # 1-based line of the translated text (what the editor should open)
    src_line: int        # 1-based line of the source comment / old line (0 when unknown)
    block: str           # approval key part: 'translate czech <id>' or 'strings'
    unit: str            # 'dialogue' | 'string'
    who: str             # text before the string literal (speaker + attributes), '' for strings
    suffix: str          # text after the string literal (e.g. ' with vpunch')
    source: str          # raw source text between the quotes (None when no source is known)
    target: str          # raw translated text between the quotes
    src_raw: str = ""    # source line as written in the file (trimmed)
    cur_raw: str = ""    # translated line as written in the file (trimmed)
    src_who: str = ""
    src_suffix: str = ""
    category: str = ""   # K_* when pending, '' when translated
    ref: str = ""        # original game script position Ren'Py recorded, e.g. 'game/script.rpy:2155'

    @property
    def pending(self):
        return bool(self.category)

    @property
    def key(self):
        """Identity used for manual approval: block + normalized source (not the line number)."""
        return (self.block, norm_ws(self.source if self.source is not None else self.target))


@dataclass
class ParsedFile:
    entries: list = field(default_factory=list)
    block_ids: list = field(default_factory=list)   # (language, id, line)
    structure: list = field(default_factory=list)   # (line, code, message)
    digest: str = ""
    languages: set = field(default_factory=set)

    @property
    def pending(self):
        return [e for e in self.entries if e.pending]


def _split_literal(code_line):
    m = STR_RE.search(code_line)
    if not m:
        return code_line.strip(), "", "", ""
    return code_line[:m.start()].strip(), m.group(1), code_line[m.end():].strip(), code_line


def parse_text(text, digest=""):
    """Parse the contents of one .rpy file."""
    lines = LINE_SPLIT_RE.split(text)
    out = ParsedFile(digest=digest)
    entries = out.entries
    comments = {}      # normalized comment -> (comment text, line number)
    comment_list = []  # (normalized, text, line, who)
    code = []          # (line number, stripped line)
    block = ""
    block_ref = ""     # '# game/script.rpy:123' of the current translate block
    ref_pending = ""   # last such comment seen, waiting for its translate / old line
    old_ref = ""
    old_text = None
    old_no = 0

    def flush():
        used = set()
        for idx, (lineno, c) in enumerate(code):
            n = norm_ws(c)
            who, target, suffix, _ = _split_literal(c)
            if n in comments:
                ctext, cno = comments[n]
                entries.append(Entry(line=lineno, src_line=cno, block=block, unit="dialogue", ref=block_ref,
                                     who=who, suffix=suffix, source=target, target=target,
                                     src_raw=ctext, cur_raw=c, src_who=who, src_suffix=suffix,
                                     category=classify(target)))
                continue
            # translated: pair with a source comment by position, else by speaker
            pick = None
            if len(comment_list) == len(code):
                pick = comment_list[idx]
            else:
                for cand in comment_list:
                    if cand[2] not in used and _split_literal(cand[1])[0] == who:
                        pick = cand
                        break
            if pick is not None:
                used.add(pick[2])
                swho, ssrc, ssuffix, _ = _split_literal(pick[1])
                entries.append(Entry(line=lineno, src_line=pick[2], block=block, unit="dialogue", ref=block_ref,
                                     who=who, suffix=suffix, source=ssrc, target=target,
                                     src_raw=pick[1], cur_raw=c, src_who=swho, src_suffix=ssuffix))
            else:
                entries.append(Entry(line=lineno, src_line=0, block=block, unit="dialogue", ref=block_ref,
                                     who=who, suffix=suffix, source=None, target=target,
                                     cur_raw=c))
        comments.clear()
        comment_list.clear()
        code.clear()

    def close_old(at_line):
        nonlocal old_text
        if old_text is not None:
            out.structure.append((old_no, "old-without-new", 'Za řádkem "old" chybí odpovídající "new".'))
            old_text = None

    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if lineno == 1:
            line = line.lstrip("﻿")
            raw = raw.lstrip("﻿")
        if not line:
            continue
        if line.startswith("translate "):
            flush()
            close_old(lineno)
            block = line.rstrip(":")
            block_ref, ref_pending = ref_pending, ""
            m = TRANSLATE_RE.match(line)
            if m:
                out.languages.add(m.group(1))
                if m.group(2) != "strings":
                    out.block_ids.append((m.group(1), m.group(2), lineno))
            continue
        if line.startswith("#"):
            ctext = line.lstrip("#").strip()
            m_ref = GAME_REF_RE.match(ctext)
            if m_ref:
                ref_pending = m_ref.group(1)
            if '"' in ctext and not ctext.startswith("game/"):
                comments[norm_ws(ctext)] = (ctext, lineno)
                comment_list.append((norm_ws(ctext), ctext, lineno))
            continue
        m_old = OLD_RE.match(raw)
        if m_old:
            close_old(lineno)
            old_text = m_old.group(1)
            old_no = lineno
            old_ref, ref_pending = ref_pending, ""
            continue
        m_new = NEW_RE.match(raw)
        if m_new:
            new_text = m_new.group(1)
            if old_text is None:
                out.structure.append((lineno, "new-without-old", 'Řádek "new" nemá před sebou "old".'))
            cat = classify(new_text) if (new_text == "" or new_text == old_text) else ""
            entries.append(Entry(line=lineno, src_line=old_no if old_text is not None else 0,
                                 block="strings", unit="string", ref=old_ref, who="", suffix="",
                                 source=old_text, target=new_text,
                                 src_raw=f'old "{old_text}"' if old_text is not None else "",
                                 cur_raw=f'new "{new_text}"', category=cat))
            old_text = None
            continue
        first = line.split(None, 1)[0]
        if '"' in line and first not in NON_TEXT and not line.startswith("$"):
            code.append((lineno, line))
    flush()
    close_old(len(lines))
    entries.sort(key=lambda e: e.line)
    return out


def parse_bytes(data):
    return parse_text(data.decode("utf-8-sig", errors="replace"), hashlib.sha1(data).hexdigest())


def count(entries, approved=(), symbols_as_done=None):
    """(translated, untranslated, manually approved) — approved pending lines count as translated."""
    if symbols_as_done is None:
        symbols_as_done = COUNT_SYMBOL_ONLY_AS_DONE
    done = todo = appr = 0
    for e in entries:
        if not e.pending:
            done += 1
        elif symbols_as_done and e.category == K_SYMBOLS:
            done += 1
        elif e.key in approved:
            appr += 1
        else:
            todo += 1
    return done + appr, todo, appr
