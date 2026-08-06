#!/usr/bin/env python3
"""Showcase image + paragraph for every station in the README.

Each stop is staged the way Simutrans layers it — way back image, station
back, the stopped train, way front (the tube's near glass), station front —
on its era-matching guideway with an era-matching trainset at the platform.
The block is injected into `src/maglev/README.md` between the
`<!-- stations:begin -->` / `<!-- stations:end -->` markers.

    python3 tools/render_readme_stations.py
"""

from __future__ import annotations

import pathlib
import re
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGES = ROOT / "src/maglev/images"
OUT_DIR = IMAGES / "readme"
README = ROOT / "src/maglev/README.md"

KEY = (231, 255, 255)
CELL = 128
TILE_DX, TILE_DY = 64, 32
VEH_FRAC = 12 / 16

# Station sheets: row 1 = back L0, back L1, front L0, front L1, icon, cursor.
BACK_L0, FRONT_L0 = 0, 2

# (name, station sheet, way, train tag, train parts, year line, paragraph)
# A way name prefixed with "^" is the elevated tier: the engine draws the
# stop and the train on the lifted ground, which the compositor emulates by
# shifting them one height level (16px) up over the columned way.
SCENES = [
    ("skystop", "maglev_skystop", ("^elevated", False), "volta220",
     "Urban elevated stop — 2008, Level 10",
     "The 160 km/h urban tier's stop: railed floating platforms and thin "
     "teal-fascia canopies, lifted by the engine onto the elevated ground "
     "while the guideway's own columns carry the street beneath. A Volta "
     "220 calls, capped at metro speed — any trainset can, since every pod "
     "wraps the same beam."),
    ("stop", "maglev_station", ("track_300", False), "kestrel260",
     "Open stop — 2000, Level 9",
     "Two bare platforms flanking the guideway, amber safety strips and "
     "nothing overhead: the pioneer decade's stop, here with a Kestrel 260 "
     "commuter set on the 300 guideway between its service masts."),
    ("shelter", "maglev_shelter", ("track_700", False), "kestrel620",
     "Canopy shelter — 2032, Level 12",
     "The 700 era's stop: thin flat glass canopies on slim steel posts, a "
     "lit rail along each platform edge in the same reserved light as the "
     "guideway's fence bases — shelter and track glow together after dark. "
     "Shown with a Kestrel 620 on the 700 shell guideway."),
    ("concourse", "maglev_concourse", ("tube", True), "meridian1000",
     "Concourse — 2064, Level 15",
     "The fusion era's roofed stop, the tube in bloom: one glazed "
     "superellipse vault spanning both platforms on the tube's own hoop "
     "grid, split down the crown so a waiting train is seen through the "
     "glass. A Meridian 1000 waits inside the 1000 tube."),
    ("terminal", "maglev_terminal", ("tube2000", True), "aetheris2000",
     "Vacuum terminal — 2100, Level 22",
     "The vacuum century's interchange: twin gull-wings in the 2000 tube's "
     "deeper glass rise from outer walls to high lit lips facing each other "
     "over the arriving pods. An Aetheris 2000 capsule slides in beneath "
     "them."),
]

DIR_CELL_N, DIR_CELL_S = 2, 6      # vehicle sheet columns for n and s


def crop(sheet: Image.Image, row: int, col: int) -> Image.Image:
    tile = sheet.crop((col * CELL, row * CELL, (col + 1) * CELL,
                       (row + 1) * CELL)).convert("RGBA")
    px = tile.load()
    for y in range(CELL):
        for x in range(CELL):
            if px[x, y][:3] == KEY:
                px[x, y] = (0, 0, 0, 0)
    return tile


def way_layers(way: str, tube: bool):
    sheet = Image.open(IMAGES / f"maglev_{way}.png")
    back = crop(sheet, 1, 5)
    front = crop(sheet, 6, 5) if tube else None
    return back, front


def render_scene(name, station_sheet, way_spec, train_tag, n_tiles=5):
    way, tube = way_spec
    lift = (0, 0)
    if way.startswith("^"):
        way, lift = way[1:], (0, -16)
    way_back, way_front = way_layers(way, tube)
    st = Image.open(IMAGES / f"{station_sheet}.png")
    st_back, st_front = crop(st, 1, BACK_L0), crop(st, 1, FRONT_L0)

    wide = CELL + (n_tiles - 1) * TILE_DX
    high = CELL + (n_tiles - 1) * TILE_DY
    img = Image.new("RGBA", (wide, high), (0, 0, 0, 0))

    def origin(k: float):
        return int(k * TILE_DX), int((n_tiles - 1 - k) * TILE_DY)

    station_tiles = (1, 2, 3)
    sheets = {p: Image.open(IMAGES / f"maglev_{p}_{train_tag}.png")
              for p in ("head", "car", "tail")}
    train = ["head", "car", "car", "tail"]
    p_head = 3.35                    # head at the north end of the platforms

    def lifted(k):
        x, y = origin(k)
        return x + lift[0], y + lift[1]

    # North-to-south painter's algorithm, all layers per tile pass.
    for k in range(n_tiles - 1, -1, -1):
        img.alpha_composite(way_back, origin(k))
        if k in station_tiles:
            img.alpha_composite(st_back, lifted(k))
    for i, part in enumerate(train):
        col = DIR_CELL_S if part == "tail" else DIR_CELL_N
        sprite = crop(sheets[part], 1, col)
        x, y = origin(p_head - i * VEH_FRAC)
        img.alpha_composite(sprite, (x + lift[0], y + lift[1]))
    for k in range(n_tiles - 1, -1, -1):
        if way_front is not None:
            img.alpha_composite(way_front, origin(k))
        if k in station_tiles:
            img.alpha_composite(st_front, lifted(k))

    img = img.crop(img.getbbox())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"station_{name}.png"
    img.save(out)
    return out


def build_section() -> str:
    out = ["", "Generated by `tools/render_readme_stations.py` — each stop "
           "staged the way the game layers it, on its era's guideway with "
           "an era-matching trainset at the platform.", ""]
    for name, sheet, way_spec, train, headline, prose in SCENES:
        path = render_scene(name, sheet, way_spec, train)
        rel = path.relative_to(README.parent)
        out += [f"#### {headline}", "", f"![{headline}]({rel})", "",
                prose, ""]
        print(f"  {name:<10} -> {rel}")
    return "\n".join(out)


def main() -> None:
    section = build_section()
    text = README.read_text()
    begin, end = "<!-- stations:begin -->", "<!-- stations:end -->"
    if begin not in text or end not in text:
        raise SystemExit(f"README is missing the {begin} / {end} markers")
    README.write_text(re.sub(re.escape(begin) + ".*?" + re.escape(end),
                             begin + "\n" + section + "\n" + end, text,
                             flags=re.S))
    print("README stations section updated")


if __name__ == "__main__":
    main()
