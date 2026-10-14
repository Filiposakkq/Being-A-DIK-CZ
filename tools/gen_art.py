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
<linearGradient id="mist" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8fa6d8" stop-opacity="0"/><stop offset=".5" stop-color="#8fa6d8" stop-opacity=".16"/><stop offset="1" stop-color="#8fa6d8" stop-opacity="0"/></linearGradient>
<radialGradient id="vig" cx=".62" cy=".5" r=".85"><stop offset=".55" stop-color="#050912" stop-opacity="0"/><stop offset="1" stop-color="#050912" stop-opacity=".62"/></radialGradient>
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
    hero_extras(o, W, H, bx, by)
    o.append('</svg>')
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "assets" / "hero.svg").write_text("\n".join(o), encoding="utf-8")


def hero_extras(o, W, H, bx, by):
    """Depth and life for the hero: lamp posts, student silhouettes, fireflies, ground mist, vignette."""
    random.seed(11)
    # lamp posts along the path
    for lx in (bx + 205, bx + 475):
        o.append(f'<rect x="{lx-3}" y="{by-70}" width="6" height="190" fill="#070d1f"/>')
        o.append(f'<rect x="{lx-11}" y="{by-84}" width="22" height="16" rx="3" fill="#070d1f"/>')
        o.append(f'<circle cx="{lx}" cy="{by-76}" r="46" fill="url(#bulb)" opacity=".9"/>')
        o.append(f'<rect x="{lx-7}" y="{by-81}" width="14" height="9" rx="2" fill="#ffe9a8"/>')

    def person(x, base, s_, rim=True):
        col = "#070d1f"
        o.append(f'<circle cx="{x}" cy="{base-74*s_:.0f}" r="{9*s_:.1f}" fill="{col}"/>')
        o.append(f'<path d="M{x-15*s_:.0f} {base-60*s_:.0f} Q{x:.0f} {base-70*s_:.0f} {x+15*s_:.0f} {base-60*s_:.0f} L{x+13*s_:.0f} {base-26*s_:.0f} L{x+8*s_:.0f} {base:.0f} L{x+1*s_:.0f} {base:.0f} L{x:.0f} {base-24*s_:.0f} L{x-1*s_:.0f} {base:.0f} L{x-8*s_:.0f} {base:.0f} L{x-13*s_:.0f} {base-26*s_:.0f} Z" fill="{col}"/>')
        if rim:
            o.append(f'<path d="M{x+15*s_:.0f} {base-60*s_:.0f} L{x+13*s_:.0f} {base-26*s_:.0f}" stroke="{CREAM}" stroke-opacity=".28" stroke-width="1.6" fill="none"/>')
            o.append(f'<path d="M{x+4*s_:.0f} {base-82*s_:.0f} a{9*s_:.1f} {9*s_:.1f} 0 0 1 {7*s_:.1f} {6*s_:.1f}" stroke="{CREAM}" stroke-opacity=".3" stroke-width="1.5" fill="none"/>')
    for x, base, sc in ((bx + 150, by + 78, 1.05), (bx + 182, by + 82, 1.0), (bx + 520, by + 70, 1.1),
                        (bx + 548, by + 74, 1.0), (bx + 590, by + 96, 1.15), (bx + 70, by + 100, 1.2)):
        person(x, base, sc)
    # fireflies / dust in the lamp light
    for _ in range(46):
        x = random.uniform(0, W); y = random.uniform(by - 140, H - 30); r = random.choice([1.2, 1.6, 2.2])
        o.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r*3.4:.1f}" fill="#ffe9a8" opacity=".10"/>')
        o.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="#ffe9a8" opacity="{random.uniform(.5,.95):.2f}"/>')
    # ground mist + vignette
    o.append(f'<rect y="{by-10}" width="{W}" height="120" fill="url(#mist)"/>')
    o.append(f'<rect width="{W}" height="{H}" fill="url(#vig)"/>')


def star(cx, cy, r, color):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.42
        pts.append(f"{cx + rr * math.cos(ang):.1f},{cy + rr * math.sin(ang):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{color}"/>'


CREST_DEFS = (f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f7d98a"/><stop offset=".5" stop-color="{GOLD}"/><stop offset="1" stop-color="#b8862a"/></linearGradient>'
              '<linearGradient id="n" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22397a"/><stop offset="1" stop-color="#0d1731"/></linearGradient>'
              f'<linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e23b50"/><stop offset="1" stop-color="#9c1a2c"/></linearGradient></defs>')
SHIELD = "M20 20H220V142C220 212 164 252 120 272C76 252 20 212 20 142Z"
INNER = "M34 34H206V140C206 200 160 236 120 254C80 236 34 200 34 140Z"


def crest():
    """Shield crest: gold rim, crimson chief with CZ and stars, big golden Delta-Iota-Kappa, ribbon."""
    c = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 290" role="img" aria-label="BaDIK CZ crest">', CREST_DEFS,
         '<path d="M26 30H226V150C226 220 170 260 126 280C82 260 26 220 26 150Z" fill="#000" opacity=".28"/>',
         f'<path d="{SHIELD}" fill="url(#n)" stroke="url(#g)" stroke-width="10" stroke-linejoin="round"/>',
         f'<clipPath id="in"><path d="{INNER}"/></clipPath>',
         '<g clip-path="url(#in)">',
         '<path d="M34 34H206V92H34Z" fill="url(#r)"/>',
         f'<path d="M34 92H206" stroke="{GOLD}" stroke-width="3"/>',
         ]
    for k in range(-4, 12):                       # faint diagonal weave behind the letters
        c.append(f'<path d="M{34 + k * 26} 92 l60 160" stroke="{CREAM}" stroke-opacity=".05" stroke-width="10"/>')
    c.append('</g>')
    c.append(f'<path d="{INNER}" fill="none" stroke="{CREAM}" stroke-opacity=".4" stroke-width="2"/>')
    c.append(star(66, 62, 9, GOLD) + star(174, 62, 9, GOLD))
    c.append(f'<text x="120" y="75" text-anchor="middle" font-family="Georgia,\'Times New Roman\',serif" font-weight="700" font-size="32" letter-spacing="8" fill="{CREAM}">CZ</text>')
    lt, lw = letters(0, 0, 64, GOLD)
    c.append(f'<g transform="translate({120 - lw / 2 + 4:.1f},126)" opacity=".45"><g fill="#050912" stroke="#050912">{lt.replace(GOLD, "#050912")}</g></g>')
    c.append(f'<g transform="translate({120 - lw / 2:.1f},122)">{lt.replace(GOLD, "url(#g)")}</g>')
    c.append(f'<path d="M44 200 L196 200 L187 216 L196 232 L44 232 L53 216 Z" fill="url(#r)" stroke="{GOLD}" stroke-width="2.5" stroke-linejoin="round"/>')
    c.append(f'<text x="120" y="222" text-anchor="middle" font-family="Georgia,\'Times New Roman\',serif" font-weight="700" font-size="15" letter-spacing="5" fill="{CREAM}">ČESKY</text>')
    c.append('</svg>')
    (OUT / "assets" / "crest.svg").write_text("\n".join(c), encoding="utf-8")

    # favicon / small icon: bold and simple so it stays readable at 16-48 px (no text, no thin strokes)
    fav = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 72">',
           f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffe29a"/><stop offset=".5" stop-color="{GOLD}"/><stop offset="1" stop-color="#b8862a"/></linearGradient>'
           '<linearGradient id="n" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a4590"/><stop offset="1" stop-color="#0f1b3d"/></linearGradient>'
           '<linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ee4258"/><stop offset="1" stop-color="#b01e33"/></linearGradient></defs>',
           '<path d="M2 3H62V38C62 57 46 67 32 72C18 67 2 57 2 38Z" fill="url(#g)"/>',
           '<path d="M9 10H55V37C55 51 44 59 32 64C20 59 9 51 9 37Z" fill="url(#n)"/>',
           '<path d="M9 10H55V23H9Z" fill="url(#r)"/>',
           '<path d="M32 27 L45 53 H19 Z" fill="none" stroke="url(#g)" stroke-width="7" stroke-linejoin="miter"/>',
           '</svg>']
    (OUT / "favicon.svg").write_text("".join(fav), encoding="utf-8")


if __name__ == "__main__":
    hero(); crest(); print("art written to", OUT)
