#!/usr/bin/env python3
"""Inspect a Simutrans/pak128 sprite sheet.

pak128 sheets are grids of 128x128 cells. Object `.dat` files address them as
`<image>.<row>.<col>`. Simutrans treats the colour #E7FFFF as transparent
(see `SPECIAL_TRANSPARENT` in the game's `descriptor/image.h`), so a "used"
pixel is simply any pixel that is not that colour.

Subcommands
-----------
map      per-cell non-transparent pixel counts, i.e. which cells are occupied
crop     write single cells out, nearest-neighbour upscaled, for eyeballing
contact  write one labelled contact sheet of several cells
profile  per-scanline min/max x of a cell, for reverse-engineering geometry
colors   most common colours of a cell or of the whole sheet

Examples
--------
    python3 tools/sheet_inspect.py map  upstream/.../rail_400_tracks.png
    python3 tools/sheet_inspect.py crop upstream/.../rail_400_tracks.png 1.5 3.7 -o /tmp/out
    python3 tools/sheet_inspect.py profile upstream/.../rail_400_tracks.png 4.6
"""

from __future__ import annotations

import argparse
import pathlib

import numpy as np
from PIL import Image

# Simutrans' transparent key colour. Anything else is drawn.
TRANSPARENT = (231, 255, 255)
CELL = 128


def load(path: str) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


def cell(sheet: np.ndarray, row: int, col: int) -> np.ndarray:
    return sheet[row * CELL:(row + 1) * CELL, col * CELL:(col + 1) * CELL]


def opaque_mask(tile: np.ndarray) -> np.ndarray:
    """True where the pixel is *not* the transparency key colour."""
    return ~np.all(tile == np.array(TRANSPARENT), axis=-1)


def parse_ref(ref: str) -> tuple[int, int]:
    """`"3.7"` -> `(3, 7)`, matching the `.dat` `image.row.col` convention."""
    row, col = ref.split(".")
    return int(row), int(col)


def cmd_map(args: argparse.Namespace) -> None:
    sheet = load(args.sheet)
    rows, cols = sheet.shape[0] // CELL, sheet.shape[1] // CELL
    print(f"{args.sheet}: {cols}x{rows} cells of {CELL}px")
    for r in range(rows):
        counts = [f"{c}:{opaque_mask(cell(sheet, r, c)).sum():5d}" for c in range(cols)]
        print(f"  r{r:<2d} " + " ".join(counts))


def cmd_crop(args: argparse.Namespace) -> None:
    sheet = load(args.sheet)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for ref in args.cells:
        r, c = parse_ref(ref)
        img = Image.fromarray(cell(sheet, r, c))
        img = img.resize((CELL * args.zoom, CELL * args.zoom), Image.NEAREST)
        dest = out / f"cell_{r}_{c}.png"
        img.save(dest)
        print(dest)


def cmd_contact(args: argparse.Namespace) -> None:
    sheet = load(args.sheet)
    refs = [parse_ref(ref) for ref in args.cells]
    zoom, per_row = args.zoom, args.per_row
    size = CELL * zoom
    rows = (len(refs) + per_row - 1) // per_row
    out = Image.new("RGB", (size * min(per_row, len(refs)), size * rows), TRANSPARENT)
    for i, (r, c) in enumerate(refs):
        img = Image.fromarray(cell(sheet, r, c)).resize((size, size), Image.NEAREST)
        out.paste(img, ((i % per_row) * size, (i // per_row) * size))
    out.save(args.out)
    print(f"{args.out}: {' '.join(args.cells)}")


def cmd_profile(args: argparse.Namespace) -> None:
    sheet = load(args.sheet)
    r, c = parse_ref(args.cell)
    mask = opaque_mask(cell(sheet, r, c))
    print(f"cell {r}.{c}: y  xmin xmax count")
    for y in range(CELL):
        xs = np.nonzero(mask[y])[0]
        if len(xs):
            print(f"  {y:3d} {xs.min():4d} {xs.max():4d} {len(xs):4d}")


def cmd_colors(args: argparse.Namespace) -> None:
    sheet = load(args.sheet)
    pixels = cell(sheet, *parse_ref(args.cell)) if args.cell else sheet
    flat = pixels.reshape(-1, 3)
    flat = flat[~np.all(flat == np.array(TRANSPARENT), axis=-1)]
    colours, counts = np.unique(flat, axis=0, return_counts=True)
    for i in np.argsort(-counts)[:args.top]:
        r, g, b = colours[i]
        print(f"  #{r:02X}{g:02X}{b:02X}  rgb({r:3d},{g:3d},{b:3d})  {counts[i]:6d}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("map"); p.add_argument("sheet"); p.set_defaults(func=cmd_map)

    p = sub.add_parser("crop")
    p.add_argument("sheet"); p.add_argument("cells", nargs="+")
    p.add_argument("-o", "--out", default="."); p.add_argument("-z", "--zoom", type=int, default=4)
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("contact")
    p.add_argument("sheet"); p.add_argument("cells", nargs="+")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("-z", "--zoom", type=int, default=2)
    p.add_argument("-n", "--per-row", type=int, default=5)
    p.set_defaults(func=cmd_contact)

    p = sub.add_parser("profile")
    p.add_argument("sheet"); p.add_argument("cell"); p.set_defaults(func=cmd_profile)

    p = sub.add_parser("colors")
    p.add_argument("sheet"); p.add_argument("cell", nargs="?")
    p.add_argument("-t", "--top", type=int, default=20); p.set_defaults(func=cmd_colors)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
