"""The pictures of the game, found by their Ren'Py image name, and the picture a line is shown on.

Ren'Py games keep their images in .rpa archives or loose in game/images. A script line names an image (`scene ep1_cafe_maya1`),
which is either a file called like that, or an `image ep1_cafe_maya1:` statement whose first string is another image name or a
path (animations list their frames). This module indexes the archives (read-only), parses those statements, and answers
"which picture is behind this script line": the last `scene` / `show` of an image that can be resolved before the line.

It is an approximation: it follows the text of the script upwards (no jumps, no conditions, no layered images), which is exactly
right for games made of full-screen renders and a good guess for the rest.
"""
import bisect
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

from . import rpa

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".avif": "image/avif", ".gif": "image/gif"}
IMAGE_DEF_RE = re.compile(r"^image\s+([A-Za-z0-9_ .\-]+?)\s*(=|:)\s*(.*)$")
STRING_RE = re.compile(r"\"([^\"\\]*)\"|'([^'\\]*)'")
CANDIDATE_RE = re.compile(r"^[\w ./\-]+$")
STMT_RE = re.compile(r"^\s*(scene|show)\s+(.+?)\s*:?\s*$")
CUT_RE = re.compile(r"\s+(?:with|at|as|zorder|onlayer|behind)\b.*$")
SKIP_FIRST = ("screen ", "text ", "expression ", "layer ", "\"", "'", "(")
FLAT = {"black": "#000000", "white": "#ffffff"}
SKIP_DIRS = {"cache", "tl", "__pycache__", ".git"}
LOOK_UP = 1500            # lines upwards that are searched for the last scene / show
CACHE_FILES = 24


def _clean(name):
    return re.sub(r"\s+", " ", str(name).strip().strip("\"'")).lower()


class GameImages:
    def __init__(self, game_dir):
        self.dir = Path(game_dir)
        self.stems = {}                 # lower-case file name without extension -> ref
        self.paths = {}                 # lower-case relative path -> ref
        self.defs = {}                  # lower-case image name -> [candidate strings]
        self.sorted_stems = []
        self.errors = []
        self._lock = threading.Lock()
        self._built = False
        self._cache = OrderedDict()
        self._script_cache = OrderedDict()

    # ------------------------------------------------------------ index
    def build(self):
        with self._lock:
            if self._built:
                return self
            archives, scripts = [], []
            for dirpath, dirs, files in os.walk(self.dir):
                dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_DIRS)
                for fn in sorted(files):
                    low, full = fn.lower(), Path(dirpath) / fn
                    if low.endswith(".rpa"):
                        archives.append(full)
                    elif low.endswith(".rpy"):
                        scripts.append(full)
                    elif low.endswith(IMG_EXT):
                        rel = full.relative_to(self.dir).as_posix()
                        self._add(rel, ("file", full, None, rel))
            for arc in archives:
                try:
                    _ver, idx = rpa.read_index(arc)
                except rpa.RpaError as e:
                    self.errors.append(f"{arc.name}: {e}")
                    continue
                for name, entry in idx.items():
                    if name.lower().endswith(IMG_EXT):
                        self._add(name, ("rpa", arc, entry, name))
            self._parse_defs(scripts)
            self.sorted_stems = sorted(self.stems)
            self._built = True
        return self

    def _add(self, rel, ref):
        low = rel.lower()
        self.paths.setdefault(low, ref)
        self.stems.setdefault(Path(low).stem, ref)

    def _parse_defs(self, scripts):
        for f in scripts:
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            i = 0
            while i < len(lines):
                m = IMAGE_DEF_RE.match(lines[i])
                i += 1
                if not m:
                    continue
                name, sep, rest = _clean(m.group(1)), m.group(2), m.group(3)
                texts = [rest]
                if sep == ":" or not rest.strip():
                    j = i
                    while j < len(lines) and j - i < 15 and (not lines[j].strip() or lines[j][:1] in " \t"):
                        texts.append(lines[j])
                        j += 1
                cands = []
                for t in texts:
                    for g in STRING_RE.finditer(t):
                        c = (g.group(1) or g.group(2) or "").strip()
                        if c and CANDIDATE_RE.match(c) and c.lower() not in ("dissolve", "fade", "none"):
                            cands.append(c)
                if cands and name not in self.defs:
                    self.defs[name] = cands[:6]

    # ------------------------------------------------------------ lookup
    def _stem_ref(self, key):
        return (key, self.stems[key]) if key in self.stems else None

    def resolve(self, name, depth=0):
        """(stem key, ref) of the picture an image name stands for, or None."""
        n = _clean(name)
        if not n or depth > 4:
            return None
        for cand in (n, n.replace(" ", "_")):
            hit = self._stem_ref(cand)
            if hit:
                return hit
        for cand in self.defs.get(n, []) + self.defs.get(n.replace(" ", "_"), []):
            low = cand.lower()
            if "/" in low or low.endswith(IMG_EXT):
                hit = self._stem_ref(Path(low).stem) or ((low, self.paths[low]) if low in self.paths else None)
            else:
                hit = self.resolve(cand, depth + 1)
            if hit:
                return hit
        base = n.replace(" ", "_")
        i = bisect.bisect_left(self.sorted_stems, base)
        near = [s for s in self.sorted_stems[i:i + 40] if s.startswith(base + "_") or s.startswith(base)]
        near = [s for s in near if re.fullmatch(re.escape(base) + r"[_\-]?(blink\d*|\d+|[a-z])?\d*", s)]
        if near:
            return self._stem_ref(min(near, key=lambda s: (len(s), s)))
        return None

    def image_bytes(self, key):
        """(bytes, mime) for a stem key returned by resolve; cached (a few recent pictures)."""
        key = _clean(key)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        ref = self.stems.get(key)
        if ref is None:
            raise rpa.RpaError("obrázek neexistuje")
        kind, where, entry, rel = ref
        data = rpa.read_entry(where, entry) if kind == "rpa" else Path(where).read_bytes()
        mime = self._sniff(data) or MIME.get(Path(rel).suffix.lower(), "image/jpeg")
        self._cache[key] = (data, mime)
        while len(self._cache) > CACHE_FILES:
            self._cache.popitem(last=False)
        return data, mime

    @staticmethod
    def _sniff(data):
        if data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        return None

    # ------------------------------------------------------------ the picture behind a script line
    def script_lines(self, path):
        key = str(path)
        if key in self._script_cache:
            self._script_cache.move_to_end(key)
            return self._script_cache[key]
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        self._script_cache[key] = lines
        while len(self._script_cache) > 8:
            self._script_cache.popitem(last=False)
        return lines

    def scene_for(self, script_path, line):
        """Walk up from `line` to the last scene / show whose image can be found.
        Returns {found, image, key, script_line, flat?, missing:[names that could not be found]}."""
        lines = self.script_lines(script_path)
        missing = []
        for n in range(min(line - 1, len(lines)) - 1, max(-1, line - 1 - LOOK_UP), -1):
            m = STMT_RE.match(lines[n])
            if not m:
                continue
            what = CUT_RE.sub("", m.group(2)).strip()
            if not what or what.lower().startswith(SKIP_FIRST):
                continue
            tokens = what.split()
            if m.group(1) == "scene" and tokens[0].lower() in FLAT:
                return {"found": True, "image": tokens[0], "key": "", "flat": FLAT[tokens[0].lower()], "script_line": n + 1, "missing": missing}
            for cand in (what, tokens[0]):
                hit = self.resolve(cand)
                if hit:
                    return {"found": True, "image": cand, "key": hit[0], "script_line": n + 1, "missing": missing}
            if len(missing) < 5:
                missing.append(what)
        return {"found": False, "image": "", "key": "", "script_line": 0, "missing": missing}
