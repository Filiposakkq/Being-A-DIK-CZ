"""Typo hints without a dictionary: the project's own translated text is the vocabulary.

A word that occurs once or twice but looks like a mistyped form of a word used many times is reported:
  - missing diacritics    "prijdu"  → "přijdu"   (the folded form matches a frequent word with diacritics)
  - swapped letters       "tkaový"  → "takový"
  - doubled letter        "dobbře"  → "dobře"
These are hints only (info / warning, never errors). Words from the source, speaker names and glossary entries
are never reported, so names and invented words are left alone. Czech has real pairs such as byt / být, which is why
short words are only an info.
"""
import hashlib
import re
from collections import Counter

from .util import fold
from .validator import Issue, plain_text

WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
MIN_FREQUENT = 5            # a "correct" word must occur at least this often
FACTOR = 5                  # ... and this many times more often than the suspicious one
RARE = 3                    # a suspicious word occurs at most this often
MIN_LEN = 4


def words_of(text):
    return [w.lower() for w in WORD_RE.findall(plain_text(text))]


class Spelling:
    def __init__(self, vocab, known=()):
        self.vocab = vocab
        self.known = {k.lower() for k in known}
        self.by_fold = {}
        for w, n in vocab.items():
            f = fold(w)
            if f != w and n >= MIN_FREQUENT and n > vocab.get(self.by_fold.get(f, ""), 0):
                self.by_fold[f] = w
        self.sig = hashlib.sha1(
            ("%d|%d|%d" % (len(vocab), sum(vocab.values()), len(self.known))).encode()).hexdigest()[:12]

    @classmethod
    def build(cls, targets, known=()):
        """`targets`: iterable of translated texts."""
        vocab = Counter()
        for t in targets:
            vocab.update(words_of(t))
        return cls(vocab, known)

    def _frequent(self, v, c):
        n = self.vocab.get(v, 0)
        return n >= MIN_FREQUENT and n >= FACTOR * max(1, c)

    def suggest(self, w):
        """(kind, better word) for a suspicious word or None."""
        c = self.vocab.get(w, 0)
        if len(w) < MIN_LEN or c > RARE or w in self.known:
            return None
        if fold(w) == w:
            better = self.by_fold.get(w)
            if better and self._frequent(better, c):
                return "diacritics", better
        for i in range(1, len(w) - 3):                      # swapped neighbours, not in the ending
            if w[i] != w[i + 1]:
                v = w[:i] + w[i + 1] + w[i] + w[i + 2:]
                if self._frequent(v, c):
                    return "swap", v
        for i in range(len(w) - 1):                         # a letter typed twice
            if w[i] == w[i + 1]:
                v = w[:i] + w[i + 1:]
                if self._frequent(v, c):
                    return "double", v
        return None

    def check(self, source, target):
        src_words = set(words_of(source))
        out, seen = [], set()
        for w in words_of(target):
            if w in seen or w in src_words:
                continue
            seen.add(w)
            hit = self.suggest(w)
            if not hit:
                continue
            kind, better = hit
            if kind == "diacritics":
                msg = f"Chybí diakritika? „{w}“ → „{better}“."
                sev = "warning" if len(w) >= 6 else "info"
            else:
                msg = f"Překlep? „{w}“ → „{better}“."
                sev = "warning"
            out.append(Issue(sev, "typo-suspect", msg, category="text",
                             extra={"fixable": True, "kind": "typo", "word": w, "better": better, "typo_kind": kind}))
            if len(out) >= 3:
                break
        return out
