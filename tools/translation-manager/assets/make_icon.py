"""Builds assets/icon.ico from PNG renders of the crest (web/assets/crest.svg + web/favicon.svg).

The PNGs were rendered from the SVG crest in a browser at 16..256 px; this script only packs them into a
multi-size Windows icon (PNG-compressed entries, supported since Windows Vista).
Usage: py assets/make_icon.py <folder with icon16.png ... icon256.png>
"""
import struct
import sys
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)


def build(src, out):
    imgs = [(n, (Path(src) / f"icon{n}.png").read_bytes()) for n in SIZES]
    head = struct.pack("<HHH", 0, 1, len(imgs))
    offset = 6 + 16 * len(imgs)
    entries, blobs = b"", b""
    for n, data in imgs:
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    Path(out).write_bytes(head + entries + blobs)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    build(sys.argv[1], here / "icon.ico")
    print("written", here / "icon.ico")
