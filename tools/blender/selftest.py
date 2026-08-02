"""Prove the Blender rig lands on pak128's pixel grid.

Renders a bare tile quad and checks the silhouette against the diamond pak128
puts in every way cell: apex at y=65, full width at y=96, base at y=127, and a
2px-per-row taper. If this passes, geometry modelled in world units will tile
seamlessly in game; if it drifts even a pixel, every joint in a long run shows
it.

    blender --background --python tools/blender/selftest.py
"""

from __future__ import annotations

import os
import sys
import tempfile

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simutrans_iso as iso  # noqa: E402

SUPERSAMPLE = 4


def alpha_mask(path: str, size: int, supersample: int):
    """Load the render and box-downsample its alpha to a 1x coverage mask."""
    img = bpy.data.images.load(path)
    px = list(img.pixels)          # flat RGBA, bottom-up
    big = size * supersample
    mask = [[0.0] * size for _ in range(size)]
    for y in range(big):
        row = size - 1 - (y // supersample)   # flip to top-down
        base = y * big * 4
        for x in range(big):
            mask[row][x // supersample] += px[base + x * 4 + 3]
    n = supersample * supersample
    return [[v / n for v in row] for row in mask]


def main() -> None:
    iso.setup(supersample=SUPERSAMPLE, samples=16)
    mat = iso.make_material("probe", (0.73, 0.73, 0.73))
    iso.polygon("tile", "flat",
                [iso.CORNER_TOP, iso.CORNER_RIGHT, iso.CORNER_BOTTOM, iso.CORNER_LEFT],
                mat)

    out = os.path.join(tempfile.gettempdir(), "simutrans_iso_selftest.png")
    iso.render_to(out)

    mask = alpha_mask(out, iso.TILE_PX, SUPERSAMPLE)
    rows = [(y, [x for x, v in enumerate(row) if v >= 0.5])
            for y, row in enumerate(mask)]
    rows = [(y, xs) for y, xs in rows if xs]

    top, bottom = rows[0][0], rows[-1][0]
    widest = max(rows, key=lambda r: len(r[1]))
    print("\n=== pak128 alignment ===")
    print(f"  diamond rows      : y={top}..{bottom}   (reference 65..127)")
    print(f"  widest row        : y={widest[0]} spanning "
          f"x={widest[1][0]}..{widest[1][-1]}   (reference y=96, x=0..127)")

    # pak128's taper: each row away from the middle loses 2px per side.
    bad = []
    for y, xs in rows:
        half = 2 * min(y - 64, 128 - y)
        want_lo, want_hi = max(0, 64 - half), min(127, 63 + half)
        if (xs[0], xs[-1]) != (want_lo, want_hi):
            bad.append((y, xs[0], xs[-1], want_lo, want_hi))
    if bad:
        print(f"  taper mismatches  : {len(bad)} rows, first few:")
        for row in bad[:6]:
            print(f"      y={row[0]} got x={row[1]}..{row[2]} want {row[3]}..{row[4]}")
    else:
        print("  taper             : exact on all rows")

    ok = (top, bottom) == (65, 127) and not bad
    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}\n")


if __name__ == "__main__":
    main()
