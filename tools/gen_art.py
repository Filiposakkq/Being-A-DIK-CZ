#!/usr/bin/env python3
"""Generates the original SVG artwork (hero scene, crest, favicon) in web/. All shapes are drawn here;
nothing is taken from the game. Run from the repository root: python3 tools/gen_art.py"""
import math, random
from pathlib import Path

random.seed(7)
NAVY = "#0f1b33"; GOLD = "#e2b04a"; CREAM = "#f5ecd6"; CRIM = "#c8283d"
OUT = Path(__file__).resolve().parent.parent / "web"


def letters(x, y, h, color, gap=0.42):
    """Greek letters Delta, Iota, Kappa as simple vector shapes (top-left x,y; height h)."""
    w = h * 0.62; s = h * 0.16; out = []; cx = x
    out.append(f'<polygon points="{cx+w/2},{y} {cx+w},{y+h} {cx},{y+h}" fill="none" stroke="{color}" stroke-width="{s}" stroke-linejoin="miter"/>')
    cx += w + h * gap
    out.append(f'<rect x="{cx+w/2-s/2}" y="{y}" width="{s}" height="{h}" fill="{color}"/>')
    cx += w * 0.5 + h * gap
    out.append(f'<rect x="{cx}" y="{y}" width="{s}" height="{h}" fill="{color}"/>')
    out.append(f'<polygon points="{cx+s},{y+h*0.52} {cx+w},{y} {cx+w+s*0.2},{y+s*1.1} {cx+s*2},{y+h*0.56}" fill="{color}"/>')
    out.append(f'<polygon points="{cx+s*1.4},{y+h*0.46} {cx+w+s*0.2},{y+h-s*1.1} {cx+w},{y+h} {cx+s},{y+h*0.58}" fill="{color}"/>')
    cx += w + s * 0.2
    return "".join(out), cx - x


def hero():
    W, H = 1500, 640
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">']
    o.append('''<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#070d1f"/><stop offset=".55" stop-color="#1a2b58"/><stop offset=".9" stop-color="#7d1c33"/><stop offset="1" stop-color="#a02a3a"/></linearGradient>
<radialGradient id="moonglow"><stop offset="0" stop-color="#f5ecd6" stop-opacity=".55"/><stop offset="1" stop-color="#f5ecd6" stop-opacity="0"/></radialGradient>
<radialGradient id="bulb"><stop offset="0" stop-color="#ffe9a8" stop-opacity=".95"/><stop offset="1" stop-color="#ffe9a8" stop-opacity="0"/></radialGradient>
<linearGradient id="lawn" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#14264a"/><stop offset="1" stop-color="#0a1226"/></linearGradient>
<linearGradient id="path" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f5ecd6" stop-opacity=".5"/><stop offset="1" stop-color="#f5ecd6" stop-opacity=".12"/></linearGradient>
</defs>''')
    o.append(f'<rect width="{W}" height="{H}" fill="url(#sky)"/>')
    for _ in range(70):
        x = random.uniform(0, W); y = random.uniform(0, 300); r = random.choice([.8, 1, 1.2, 1.6])
        o.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{CREAM}" opacity="{random.uniform(.25,.8):.2f}"/>')
    o.append('<circle cx="1390" cy="150" r="150" fill="url(#moonglow)"/>')
    o.append(f'<circle cx="1390" cy="150" r="58" fill="{CREAM}"/>')
    for cx, cy, r in ((1372, 138, 11), (1408, 168, 8), (1392, 120, 6), (1374, 172, 5)):
        o.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#d9ceb2" opacity=".6"/>')
    o.append('<path d="M0 470 C190 420 360 450 540 430 C720 410 820 460 1020 440 C1200 420 1340 455 1500 430 V640 H0Z" fill="#101e3f"/>')
    o.append('<path d="M0 500 C250 470 400 500 650 485 C900 470 1130 505 1500 480 V640 H0Z" fill="#0c1733"/>')

    bx, by = 640, 590
    for wx, ww in ((bx - 190, 160), (bx + 710, 160)):
        o.append(f'<rect x="{wx}" y="{by-150}" width="{ww}" height="150" fill="#13244a"/>')
        o.append(f'<polygon points="{wx-10},{by-150} {wx+ww/2},{by-205} {wx+ww+10},{by-150}" fill="#0d1a38"/>')
        for k in range(2):
            for r_ in range(2):
                o.append(f'<rect x="{wx+24+k*66}" y="{by-128+r_*58}" width="40" height="38" rx="2" fill="#f6d58a" opacity="{random.choice([1,1,.85,.35]):.2f}"/>')
                o.append(f'<path d="M{wx+44+k*66} {by-128+r_*58} v38 M{wx+24+k*66} {by-109+r_*58} h40" stroke="#13244a" stroke-width="3"/>')
    for i, (sx, sw) in enumerate(((bx - 50, 780), (bx - 30, 740), (bx - 10, 700))):
        o.append(f'<rect x="{sx}" y="{by-14*(i+1)}" width="{sw}" height="14" fill="{["#1b2f5e","#223a70","#2a4482"][i]}"/>')
    o.append(f'<rect x="{bx}" y="{by-300}" width="680" height="258" fill="#192d5a"/>')
    for k in range(5):
        wx = bx + 60 + k * 125
        o.append(f'<rect x="{wx}" y="{by-250}" width="56" height="170" fill="#f6d58a" opacity="{random.choice([1,1,.9]):.2f}"/>')
        o.append(f'<path d="M{wx+28} {by-250} v170 M{wx} {by-165} h56" stroke="#192d5a" stroke-width="4"/>')
    o.append(f'<rect x="{bx+310}" y="{by-170}" width="60" height="128" fill="#ffe9a8"/>')
    o.append(f'<path d="M{bx+340} {by-170} v128" stroke="#192d5a" stroke-width="3"/>')
    for k in range(6):
        cx = bx + 10 + k * 128
        o.append(f'<rect x="{cx}" y="{by-290}" width="34" height="250" fill="{CREAM}"/>')
        o.append(f'<rect x="{cx-6}" y="{by-300}" width="46" height="14" fill="{CREAM}"/>')
        o.append(f'<rect x="{cx-6}" y="{by-52}" width="46" height="12" fill="{CREAM}"/>')
        o.append(f'<path d="M{cx+10} {by-282} v236 M{cx+24} {by-282} v236" stroke="#d3c7a8" stroke-width="2"/>')
    o.append(f'<rect x="{bx-30}" y="{by-340}" width="740" height="44" fill="{CREAM}"/>')
    o.append(f'<rect x="{bx-30}" y="{by-336}" width="740" height="6" fill="{GOLD}"/>')
    o.append(f'<polygon points="{bx-40},{by-340} {bx+340},{by-440} {bx+720},{by-340}" fill="{CREAM}"/>')
    o.append(f'<polygon points="{bx+14},{by-348} {bx+340},{by-424} {bx+666},{by-348}" fill="{NAVY}"/>')
    lt, lw = letters(0, 0, 58, GOLD)
    o.append(f'<g transform="translate({bx+340-lw/2:.1f},{by-402})">{lt}</g>')
    o.append(f'<rect x="{bx+338}" y="{by-520}" width="4" height="84" fill="{CREAM}"/>')
    o.append(f'<polygon points="{bx+342},{by-518} {bx+396},{by-503} {bx+342},{by-488}" fill="{CRIM}"/>')
    o.append(f'<rect y="{by}" width="{W}" height="{H-by}" fill="url(#lawn)"/>')
    o.append(f'<polygon points="{bx+300},{by} {bx+380},{by} {bx+500},{H} {bx+180},{H}" fill="url(#path)"/>')

    def tree(x, base, s, col):
        o.append(f'<rect x="{x-5*s}" y="{base-60*s}" width="{10*s}" height="{60*s}" fill="#0a1226"/>')
        for dx, dy, r in ((0, -95, 46), (-34, -70, 34), (34, -70, 36), (0, -60, 40)):
            o.append(f'<circle cx="{x+dx*s}" cy="{base+dy*s}" r="{r*s}" fill="{col}"/>')
    tree(90, by + 30, 1.5, "#0b1a3a"); tree(250, by + 50, 1.0, "#0d1f45"); tree(380, by + 38, 1.2, "#0b1a3a")
    tree(1500, by + 40, 1.55, "#0b1a3a"); tree(1380, by + 55, 1.0, "#0d1f45")

    # string lights (top) and pennant bunting (below, clear of the pediment)
    n = 22
    pts = [(i / n * W, 22 + 14 * (i / n) + 40 * math.sin(math.pi * i / n)) for i in range(n + 1)]
    o.append('<path d="M' + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts) + '" fill="none" stroke="#050912" stroke-width="1.6" opacity=".7"/>')
    for i, (x, y) in enumerate(pts):
        if 0 < i < n:
            o.append(f'<circle cx="{x:.0f}" cy="{y+5:.0f}" r="14" fill="url(#bulb)"/>')
            o.append(f'<circle cx="{x:.0f}" cy="{y+5:.0f}" r="3.2" fill="#ffe9a8"/>')
    n = 15
    pts = [(i / n * W, 100 + 6 * (i / n) + 16 * math.sin(math.pi * i / n)) for i in range(n + 1)]
    o.append('<path d="M' + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts) + '" fill="none" stroke="#050912" stroke-width="1.5" opacity=".7"/>')
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + 30
        o.append(f'<polygon points="{x1+4:.0f},{y1:.0f} {x2-4:.0f},{y2:.0f} {mx:.0f},{my:.0f}" fill="{CRIM if i%2==0 else GOLD}" opacity=".92"/>')
    o.append('</svg>')
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "assets" / "hero.svg").write_text("\n".join(o), encoding="utf-8")


def crest():
    c = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 290" role="img" aria-label="Crest">']
    c.append(f'<path d="M20 20H220V142C220 212 164 252 120 272C76 252 20 212 20 142Z" fill="#16264a" stroke="{GOLD}" stroke-width="9" stroke-linejoin="round"/>')
    c.append(f'<path d="M34 34H206V140C206 200 160 236 120 254C80 236 34 200 34 140Z" fill="none" stroke="{CREAM}" stroke-opacity=".35" stroke-width="2"/>')
    c.append(f'<path d="M34 34H206V86H34Z" fill="{CRIM}"/>')
    lt, lw = letters(0, 0, 74, GOLD)
    c.append(f'<g transform="translate({120-lw/2:.1f},112)">{lt}</g>')
    c.append(f'<rect x="58" y="206" width="124" height="3" fill="{GOLD}"/>')
    c.append(f'<text x="120" y="68" text-anchor="middle" font-family="Georgia,\'Times New Roman\',serif" font-weight="700" font-size="26" letter-spacing="7" fill="{CREAM}">CZ</text>')
    c.append('</svg>')
    (OUT / "assets" / "crest.svg").write_text("\n".join(c), encoding="utf-8")
    lt, lw = letters(0, 0, 26, GOLD)
    (OUT / "favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 72"><path d="M5 5H59V37C59 55 44 65 32 70C20 65 5 55 5 37Z" fill="#16264a" stroke="{GOLD}" stroke-width="5" stroke-linejoin="round"/>'
        f'<g transform="translate({32-lw/2:.1f},24)">{lt}</g></svg>', encoding="utf-8")


if __name__ == "__main__":
    hero(); crest(); print("art written to", OUT)
