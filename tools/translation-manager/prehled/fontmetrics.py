"""Advance widths of a font (TrueType / OpenType file), read from `cmap` and `hmtx` only.

Ren'Py draws text with FreeType, which takes the advance of a glyph from `hmtx`. A browser may take it from the CFF charstring instead,
and fonts made with a wrong `nominalWidthX` (some patched fonts with added Czech letters) then get a gap after every accented
letter in the browser. The scene preview therefore places every character by the `hmtx` advance. This reads the two tables with
struct only (no dependency) and never trusts the file: anything out of range gives None.
"""
import struct

MAX_CP = 0x3000            # the preview only needs Latin, punctuation and the like
MAX_GLYPHS = 70000


def _u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def _tables(data):
    if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return None
    out = {}
    for i in range(_u16(data, 4)):
        o = 12 + i * 16
        if o + 16 > len(data):
            return None
        tag, _chk, off, ln = struct.unpack_from(">4sIII", data, o)
        if off + ln > len(data):
            return None
        out[tag.decode("latin-1")] = (off, ln)
    return out


def _cmap(data, off, ln):
    """{codepoint: glyph id} from the best Unicode subtable (format 12 or 4)."""
    n = _u16(data, off + 2)
    best = None
    for i in range(n):
        plat, enc, sub = struct.unpack_from(">HHI", data, off + 4 + i * 8)
        if not (plat == 0 or (plat == 3 and enc in (1, 10))):
            continue
        fmt = _u16(data, off + sub)
        rank = (3 if fmt == 12 else 2 if fmt == 4 else 0) + (1 if (plat, enc) == (3, 10) else 0)
        if fmt in (4, 12) and (best is None or rank > best[0]):
            best = (rank, off + sub, fmt)
    if best is None:
        return {}
    _r, base, fmt = best
    cm = {}
    if fmt == 12:
        for g in range(_u32(data, base + 12)):
            start, end, gid = struct.unpack_from(">III", data, base + 16 + g * 12)
            for cp in range(start, min(end, MAX_CP - 1) + 1):
                cm[cp] = gid + (cp - start)
        return cm
    segs = _u16(data, base + 6) // 2
    ends, starts = base + 14, base + 16 + segs * 2
    deltas, ranges = starts + segs * 2, starts + segs * 4
    for s in range(segs):
        end, start = _u16(data, ends + s * 2), _u16(data, starts + s * 2)
        delta = struct.unpack_from(">h", data, deltas + s * 2)[0]
        rng = _u16(data, ranges + s * 2)
        for cp in range(start, min(end, MAX_CP - 1) + 1):
            if cp == 0xFFFF:
                continue
            if rng == 0:
                gid = (cp + delta) & 0xFFFF
            else:
                o = ranges + s * 2 + rng + (cp - start) * 2
                if o + 2 > len(data):
                    continue
                gid = _u16(data, o)
                if gid:
                    gid = (gid + delta) & 0xFFFF
            if gid:
                cm[cp] = gid
    return cm


def advances(data):
    """{"upm": units per em, "adv": {codepoint: advance in font units}} or None when the file is not a usable font."""
    try:
        t = _tables(data)
        if not t or not all(k in t for k in ("head", "hhea", "hmtx", "cmap")):
            return None
        upm = _u16(data, t["head"][0] + 18)
        n_h = _u16(data, t["hhea"][0] + 34)
        hm_off, hm_len = t["hmtx"]
        if not 16 <= upm <= 16384 or not 0 < n_h <= MAX_GLYPHS or n_h * 4 > hm_len:
            return None
        cm = _cmap(data, *t["cmap"])
        adv = {}
        for cp, gid in cm.items():
            i = min(gid, n_h - 1)
            adv[cp] = _u16(data, hm_off + i * 4)
        return {"upm": upm, "adv": adv} if adv else None
    except (struct.error, IndexError, ValueError):
        return None
