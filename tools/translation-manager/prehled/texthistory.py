"""History of the translated text of every line.

Each change of a translation is appended to `historie_textu.jsonl` in the data folder: when, which line (file + the same
key that proofreading uses: block + normalized original, so it follows the line when the file is reorganised), the old
and the new text, and how it happened (edit in the app, fix, replace, unify, undo, or a change made outside the app that
was noticed at the next refresh). The translator can look at all versions of a line and restore one.

Changes made by other programs are only seen when the files are refreshed, so a file edited twice between two
refreshes yields one entry. The file is append-only; when it grows beyond MAX_LINES the oldest entries are dropped.
"""
import json
import threading
from collections import defaultdict
from datetime import datetime

from .util import norm_ws

FILE_NAME = "historie_textu.jsonl"
MAX_LINES = 60000
KEEP_LINES = 40000
VIA = {"edit": "úprava v aplikaci", "fix": "oprava", "replace": "nahrazení", "unify": "sjednocení",
       "undo": "vrácení změny", "restore": "obnovení ze zálohy", "external": "změna mimo aplikaci"}


def key_of(block, source):
    return [str(block), norm_ws(str(source))]


class TextHistory:
    def __init__(self, path):
        self.path = path
        self.by_key = defaultdict(list)      # (file, block, source) -> [record]
        self.total = 0
        self._lock = threading.Lock()

    def load(self):
        self.by_key.clear()
        self.total = 0
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return self
        if len(lines) > MAX_LINES:                      # keep the newest part, once, at load time
            lines = lines[-KEEP_LINES:]
            try:
                self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                pass
        for ln in lines:
            try:
                r = json.loads(ln)
                self.by_key[(r["f"], r["k"][0], r["k"][1])].append(r)
                self.total += 1
            except (ValueError, KeyError, IndexError, TypeError):
                continue                                 # a damaged line never breaks the history
        return self

    def record(self, items, via):
        """items: [{file, key:(block, source), old, new}]. Entries with an unchanged text are ignored."""
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for it in items:
            if it["old"] == it["new"]:
                continue
            blk, src = it["key"][0], norm_ws(it["key"][1])
            rows.append({"t": now, "f": it["file"], "k": [blk, src], "o": it["old"], "n": it["new"], "v": via})
        if not rows:
            return 0
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            except OSError:
                return 0
            for r in rows:
                self.by_key[(r["f"], r["k"][0], r["k"][1])].append(r)
            self.total += len(rows)
        return len(rows)

    def versions(self, file, key, current):
        """Texts this line has had, newest first: [{text, time, via, current}]. The text before the first recorded
        change is included as the oldest version."""
        recs = self.by_key.get((file, str(key[0]), norm_ws(str(key[1]))), [])
        if not recs:
            return []
        seq = [{"text": recs[0]["o"], "time": "", "via": "původní text před první zaznamenanou změnou"}]
        for r in recs:
            seq.append({"text": r["n"], "time": r["t"], "via": VIA.get(r["v"], r["v"])})
        out = []
        for i, v in enumerate(reversed(seq)):
            v["current"] = v["text"] == current and not any(o["current"] for o in out)
            out.append(v)
        return out[:60]


def diff_files(old_entries, new_entries):
    """Changed translations between two parses of the same file: [{key, old, new}] (matched by key and order)."""
    seen = defaultdict(list)
    for e in old_entries:
        seen[e.key].append(e.target)
    used = defaultdict(int)
    out = []
    for e in new_entries:
        olds = seen.get(e.key)
        if not olds:
            continue
        i = used[e.key]
        used[e.key] += 1
        if i < len(olds) and olds[i] != e.target:
            out.append({"key": e.key, "old": olds[i], "new": e.target, "block": e.block, "source": e.source})
    return out
