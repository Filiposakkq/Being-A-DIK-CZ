"""Advance widths read from cmap + hmtx of a font file (a hand-built minimal sfnt; no font library needed)."""
import struct
import unittest

import helpers  # noqa: F401  (puts the package on the path)
from prehled import fontmetrics


def build_font(advances, cmap, n_hmetrics=None, fmt=4, magic=b"\x00\x01\x00\x00", upm=1000):
    """advances: glyph advances in glyph-id order; cmap: {codepoint: glyph id}."""
    n_h = len(advances) if n_hmetrics is None else n_hmetrics
    head = bytearray(54)
    struct.pack_into(">H", head, 18, upm)
    hhea = bytearray(36)
    struct.pack_into(">H", hhea, 34, n_h)
    hmtx = b"".join(struct.pack(">Hh", a, 0) for a in advances[:n_h]) + b"".join(struct.pack(">h", 0) for _ in advances[n_h:])
    cps = sorted(cmap)
    if fmt == 12:
        groups = b"".join(struct.pack(">III", cp, cp, cmap[cp]) for cp in cps)
        sub = struct.pack(">HHIIII", 12, 0, 16 + len(groups), 0, len(cps), 0)[:12] + struct.pack(">I", len(cps)) + groups
        sub = struct.pack(">HHII", 12, 0, 16 + len(groups), 0) + struct.pack(">I", len(cps)) + groups
    else:
        segs = [(cp, cp, (cmap[cp] - cp) & 0xFFFF) for cp in cps] + [(0xFFFF, 0xFFFF, 1)]
        n = len(segs)
        body = b"".join(struct.pack(">H", s[1]) for s in segs) + b"\0\0" + b"".join(struct.pack(">H", s[0]) for s in segs)
        body += b"".join(struct.pack(">H", s[2]) for s in segs) + b"\0\0" * n
        sub = struct.pack(">HHHHHHH", 4, 14 + len(body), 0, n * 2, 0, 0, 0) + body
    cmap_t = struct.pack(">HH", 0, 1) + struct.pack(">HHI", 3, 1, 12) + sub
    tables = {"cmap": cmap_t, "head": bytes(head), "hhea": bytes(hhea), "hmtx": hmtx}
    off = 12 + 16 * len(tables)
    directory, blob = b"", b""
    for tag, data in tables.items():
        directory += struct.pack(">4sIII", tag.encode(), 0, off + len(blob), len(data))
        blob += data + b"\0" * (-len(data) % 4)
    return magic + struct.pack(">HHHH", len(tables), 0, 0, 0) + directory + blob


class FontMetricsTests(unittest.TestCase):
    def test_advances_come_from_hmtx_through_cmap(self):
        data = build_font([1000, 409, 496, 371], {ord("s"): 1, ord("e"): 2, 0x161: 1, ord(","): 3})
        m = fontmetrics.advances(data)
        self.assertEqual(m["upm"], 1000)
        self.assertEqual((m["adv"][ord("s")], m["adv"][0x161], m["adv"][ord("e")], m["adv"][ord(",")]), (409, 409, 496, 371))

    def test_format_12_and_glyphs_past_the_last_full_metric(self):
        data = build_font([500, 600, 700, 0, 0], {0x41: 1, 0x42: 4}, n_hmetrics=3, fmt=12)
        m = fontmetrics.advances(data)
        self.assertEqual((m["adv"][0x41], m["adv"][0x42]), (600, 700))      # glyph 4 repeats the last advance

    def test_otf_magic_is_accepted_and_other_files_are_not(self):
        self.assertIsNotNone(fontmetrics.advances(build_font([500, 600], {0x41: 1}, magic=b"OTTO")))
        for bad in (b"", b"wOFF" + b"\0" * 60, b"\x00\x01\x00\x00", b"\x00\x01\x00\x00" + b"\xff" * 40, b"not a font" * 20):
            self.assertIsNone(fontmetrics.advances(bad), bad[:8])

    def test_a_truncated_or_hostile_file_never_raises(self):
        data = build_font([1000, 409, 496], {ord("s"): 1, ord("e"): 2})
        for cut in range(0, len(data), 7):
            fontmetrics.advances(data[:cut])                              # must return something or None, never raise
        evil = bytearray(data)
        evil[12 + 8: 12 + 12] = struct.pack(">I", 0xFFFFFF00)             # a table offset far outside the file
        self.assertIsNone(fontmetrics.advances(bytes(evil)))
        zero_upm = build_font([500, 600], {0x41: 1}, upm=0)
        self.assertIsNone(fontmetrics.advances(zero_upm))


if __name__ == "__main__":
    unittest.main()
