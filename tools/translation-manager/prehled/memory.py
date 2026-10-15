"""Translation memory of the project itself: what was already translated, looked up by the English original.

Matching is done on the ORIGINAL (English) text, so Czech declension does not get in the way of finding a match.
It does get in the way of reusing the result: a Czech phrase may need another case or gender in the new sentence,
so everything here is only offered as a suggestion that the translator inserts and adapts.

  exact    the same original (ignoring case, punctuation, tags, variables) already translated -> its translations
  similar  an original that differs by a few words -> its translation, with the ratio of similarity
  groups   one original translated in several different ways (consistency check)
"""
import difflib
import re
from collections import Counter, defaultdict

from .util import norm_ws
from .validator import plain_text

WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
VAR = re.compile(r"\[[^\]\[]*\]|\{[^}]*\}")


def tokens(text):
    return WORD.findall(plain_text(text or "").lower())


def tags_of(text):
    """Variables and tags of a text, for a warning that a reused translation carries different ones."""
    return Counter(VAR.findall(text or ""))


class Memory:
    COMMON_FRACTION = 0.04

    def __init__(self, rows):
        """rows: iterable of (file, line, who, source, target) of translated lines."""
        self.rows = []
        self.exact = defaultdict(list)
        self.inv = defaultdict(list)
        for file, line, who, source, target in rows:
            toks = tokens(source)
            if not toks or not target:
                continue
            i = len(self.rows)
            self.rows.append({"file": file, "line": line, "who": who, "source": source, "target": target, "tokens": toks})
            self.exact[tuple(toks)].append(i)
            for t in set(toks):
                self.inv[t].append(i)
        n = len(self.rows)
        self.common = {t for t, ids in self.inv.items() if len(ids) > max(50, self.COMMON_FRACTION * n)}

    @staticmethod
    def _grouped(rows, skip):
        """Group rows by identical translation (case and spacing ignored), most used first."""
        groups = {}
        for r in rows:
            if (r["file"], r["line"]) == skip:
                continue
            g = groups.setdefault(norm_ws(r["target"]).casefold(), {"target": r["target"], "count": 0, "lines": []})
            g["count"] += 1
            if len(g["lines"]) < 5:
                g["lines"].append({"file": r["file"], "line": r["line"], "who": r["who"]})
        return sorted(groups.values(), key=lambda g: (-g["count"], g["target"]))

    def exact_matches(self, source, skip=None):
        toks = tuple(tokens(source))
        return self._grouped([self.rows[i] for i in self.exact.get(toks, [])], skip) if toks else []

    def similar(self, source, skip=None, limit=5, min_ratio=0.7):
        toks = tokens(source)
        if len(toks) < 2:
            return []
        score = Counter()
        for t in set(toks) - self.common:
            for i in self.inv.get(t, [])[:400]:
                score[i] += 1
        found = {}
        for i, _n in score.most_common(80):
            r = self.rows[i]
            if (r["file"], r["line"]) == skip or r["tokens"] == toks:
                continue
            ratio = difflib.SequenceMatcher(None, toks, r["tokens"], autojunk=False).ratio()
            if ratio < min_ratio:
                continue
            key = norm_ws(r["target"]).casefold()
            if key not in found or ratio > found[key]["ratio"]:
                found[key] = {"source": r["source"], "target": r["target"], "ratio": round(ratio, 2),
                              "file": r["file"], "line": r["line"], "who": r["who"]}
        return sorted(found.values(), key=lambda x: (-x["ratio"], x["target"]))[:limit]

    def groups(self, limit=500, loose=False, by_speaker=False):
        """Originals that were translated in more than one way: [{key, source, total, variants:[{target, count, lines}]}].

        By default the original must be EXACTLY the same text (case, punctuation and tags included): "Yeah.", "Yeah!" and
        "YEAH!!!" are different lines that are rightly translated differently ("Jo.", "Jo!", "JOOO!"), so they are never put
        together. `loose` compares only the words (the old behaviour, to find near duplicates); `by_speaker` keeps lines of
        different speakers apart (the same word can be said by a man and a woman, or in another tone)."""
        buckets = defaultdict(list)
        for i, r in enumerate(self.rows):
            base = " ".join(r["tokens"]) if loose else "=" + norm_ws(r["source"])
            who = (r["who"] or "").split()[0] if by_speaker and r["who"] else ""
            buckets[base + ("|" + who if by_speaker else "")].append(i)
        out = []
        for key, ids in buckets.items():
            if len(ids) < 2:
                continue
            rows = [self.rows[i] for i in ids]
            variants = {}
            for r in rows:
                v = variants.setdefault(norm_ws(r["target"]).casefold(), {"target": r["target"], "count": 0, "lines": []})
                v["count"] += 1
                v["lines"].append({"file": r["file"], "line": r["line"], "who": r["who"]})
            if len(variants) < 2:
                continue
            vs = sorted(variants.values(), key=lambda v: (-v["count"], v["target"]))
            out.append({"key": key, "source": rows[0]["source"], "total": len(rows), "variants": vs,
                        "sources": sorted({norm_ws(r["source"]) for r in rows})})
        out.sort(key=lambda g: (-g["total"], g["key"]))
        return out[:limit]
