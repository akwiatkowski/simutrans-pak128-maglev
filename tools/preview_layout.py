#!/usr/bin/env python3
"""Compose way tiles, and optionally a train, the way Simutrans would draw them.

Judging a sprite cell by cell is misleading: what matters is whether the pieces
line up into a continuous run at 100% zoom, and whether a train sits on the way
correctly. This lays a fixed test layout onto a grass background so a sheet can
be eyeballed, or diffed against pak128's rail sheet.

Tiles step by (+64, -32) screen pixels along the `a` axis (towards N) and by
(+64, +32) along `b` (towards E); tiles closer to the camera are drawn last.

Vehicle direction is **derived from the way**, never passed in. Hand-placing
sprites by cell number is how a train ends up drawn ninety degrees across its
own track — `place_consist` picks the cell from the direction of travel and
raises if that direction is not something the way underneath actually offers.

    python3 tools/preview_layout.py src/maglev/images/maglev_track.png -o /tmp/map.png
    python3 tools/preview_layout.py A.png B.png -o /tmp/compare.png --zoom 2
    python3 tools/preview_layout.py src/maglev/images/maglev_track.png -o /tmp/t.png \
        --consist src/maglev/images --set meridian500
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pak128_layout as layout  # noqa: E402

CELL = layout.CELL
KEY = layout.KEY
GRASS = (108, 148, 84)

# Cell references from rail_400_tracks.dat, which the maglev sheet mirrors.
NS, EW = (1, 5), (1, 6)
NSEW, NSE = (2, 3), (1, 7)
STUB_N, STUB_S = (1, 1), (1, 2)

# (a, b) tile -> (sheet cell, connection mask). The mask is what lets a consist
# be checked against the track it is standing on.
LAYOUT = {
    (0, 0): (STUB_S, layout.S),
    (1, 0): (NS, layout.N | layout.S),
    (2, 0): (NS, layout.N | layout.S),
    (3, 0): (NS, layout.N | layout.S),
    (4, 0): (NSE, layout.N | layout.S | layout.E),
    (4, 1): (EW, layout.E | layout.W),
    (4, 2): (EW, layout.E | layout.W),
    (5, 0): (NS, layout.N | layout.S),
    (6, 0): (NS, layout.N | layout.S),
    (7, 0): (NSEW, layout.N | layout.S | layout.E | layout.W),
    (7, -1): (EW, layout.E | layout.W),
    (8, 0): (NS, layout.N | layout.S),
    (9, 0): (STUB_N, layout.N),
}

# `length=12` in the vehicle dats is twelve sixteenths of a tile.
VEHICLE_TILES = 12 / 16


def screen(a, b):
    return (a * 64 + b * 64, -a * 32 + b * 32)


def cutout(sheet: Image.Image, ref) -> Image.Image:
    """One cell with the transparency key turned into real alpha."""
    row, col = ref
    tile = sheet.crop((col * CELL, row * CELL, (col + 1) * CELL, (row + 1) * CELL))
    out = tile.convert("RGBA")
    out.putdata([(r, g, b, 0 if (r, g, b) == KEY else 255)
                 for r, g, b in tile.getdata()])
    return out


def place_consist(canvas, sheets, start, direction, roles, offset):
    """Draw a train along the layout, deriving every cell from `direction`.

    `roles` runs from the rear of the train forwards, each one of "tail",
    "mail", "car" or "head". A tail uses the head sheet with its directions
    reversed, so its nose points back down the train.
    """
    tile = LAYOUT.get(start)
    if tile is None:
        raise KeyError(f"no way at tile {start}")
    if not layout.way_allows(tile[1], direction):
        raise ValueError(
            f"a vehicle cannot travel {direction!r} on the way at {start}: "
            f"that way only connects {_mask_name(tile[1])}")

    # VEHICLE_HEADING is a world vector (x=E, y=N); `screen` takes tile
    # coordinates (a=N, b=E). They are transposed, so swap on the way through.
    east, north = layout.VEHICLE_HEADING[direction]
    for i, role in enumerate(roles):
        along = i * VEHICLE_TILES
        x, y = screen(north * along, east * along)
        sheet = sheets["head" if role in ("head", "tail") else role]
        cell = layout.vehicle_cell(direction, reversed_nose=(role == "tail"))
        art = cutout(sheet, cell)
        # Vehicles sit at fractions of a tile, so the step is not an integer.
        canvas.alpha_composite(art, (offset[0] + round(x), offset[1] + round(y)))


def _mask_name(ribi):
    return "".join(n for n, bit in (("N", layout.N), ("S", layout.S),
                                    ("E", layout.E), ("W", layout.W)) if ribi & bit)


def compose(sheet_path: str, zoom: int, consist_dir=None, set_tag=None) -> Image.Image:
    sheet = Image.open(sheet_path).convert("RGB")

    placed = sorted((screen(a, b)[1], screen(a, b)[0], ref)
                    for (a, b), (ref, _) in LAYOUT.items())
    xs = [x for _, x, _ in placed]
    ys = [y for y, _, _ in placed]
    pad = CELL
    size = (max(xs) - min(xs) + CELL + 2 * pad, max(ys) - min(ys) + CELL + 2 * pad)
    origin = (-min(xs) + pad, -min(ys) + pad)

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for y, x, ref in placed:
        canvas.alpha_composite(cutout(sheet, ref), (x + origin[0], y + origin[1]))

    if consist_dir and set_tag:
        base = pathlib.Path(consist_dir)
        sheets = {part: Image.open(base / f"maglev_{part}_{set_tag}.png").convert("RGB")
                  for part in ("head", "car", "mail")}
        start = (1, 0)
        sx, sy = screen(*start)
        place_consist(canvas, sheets, start, "n",
                      ["tail", "mail", "car", "head"],
                      (sx + origin[0], sy + origin[1]))

    out = Image.new("RGB", size, GRASS)
    out.paste(canvas, (0, 0), canvas)
    return out.resize((size[0] * zoom, size[1] * zoom), Image.NEAREST) if zoom > 1 else out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sheets", nargs="+")
    parser.add_argument("-o", "--out", required=True)
    parser.add_argument("-z", "--zoom", type=int, default=1)
    parser.add_argument("--consist", help="directory holding the vehicle sheets")
    parser.add_argument("--set", dest="set_tag", help="trainset tag, e.g. meridian500")
    args = parser.parse_args()

    maps = [compose(s, args.zoom, args.consist, args.set_tag) for s in args.sheets]
    width = max(m.width for m in maps)
    out = Image.new("RGB", (width, sum(m.height for m in maps)), GRASS)
    y = 0
    for m in maps:
        out.paste(m, (0, y))
        y += m.height
    out.save(args.out)
    print(f"wrote {args.out} ({out.width}x{out.height}) from {', '.join(args.sheets)}")


if __name__ == "__main__":
    main()
