#!/usr/bin/env python3
"""Pack Blender-rendered cells into a pak128 sprite sheet.

Runs outside Blender (it needs Pillow). Takes the per-cell RGBA renders from
`tools/blender/build_maglev_track.py`, downsamples them, cuts them to the exact
tile silhouette and writes the finished sheet.

Why the silhouette is cut analytically
--------------------------------------
A renderer anti-aliases the diamond's left and right tips down to well under
50% coverage, so a plain alpha threshold drops those two pixels on every tile.
Four tiles meet at each of those points, so all four would drop them and the
ground would show through as a speckle along every run.

Instead the ground silhouette comes from the same projection maths the game
uses — a pixel belongs to the tile when its ground coordinates satisfy
|a| <= 1 and |b| <= 1 — and only the parts standing *above* ground (the girder
deck near the upper edges) fall back to a 50% coverage test. That test is
limited to a band above the tile so stray geometry swept past the tile edge
cannot bleed into a neighbour.

    python3 tools/assemble_sheet.py build/cells -o src/maglev/maglev_track.png
    python3 tools/assemble_sheet.py build/cells -o /tmp/sheet.png \
        --base src/maglev/maglev_track.png     # fill gaps from the 2D sheet
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pak128_layout as layout                      # noqa: E402
from render_maglev_track import (render_cursor, render_header,  # noqa: E402
                                 render_icon)

# Tallest thing standing on a tile, in screen pixels: the stop block. Coverage
# above the ground silhouette is only accepted within this band.
MAX_OBJECT_PX = 14

# A 4.3m glass tube reaches much higher than a stop block.
TUBE_MAX_PX = 34

# makeobj inverts the alpha channel (`pixel ^ 0xFF000000`, "we want 0 ==
# opaque") and then treats anything at or above 0xF8 as fully transparent. In
# PNG terms that means alpha 0..7 collapses to invisible, and the remaining
# range is quantised to 31 steps. Faint glass therefore has to be pushed clear
# of that floor or it silently disappears.
ALPHA_FLOOR = 8

# Simutrans reserves 31 exact colours (image_t::rgbtab): player colours, and
# lights that do not darken when the map dims at night. A rendered pixel that
# lands on one by accident becomes a light — several of these greys sit right
# in the concrete range, so without this guard every sheet ends up with a
# scatter of pixels that glow or refuse to dim after dark.
SPECIAL_COLOURS = frozenset([
    0x244B67, 0x395E7C, 0x4C7191, 0x6084A7, 0x7497BD, 0x88ABD3, 0x9CBEE9, 0xB0D2FF,
    0x7B5803, 0x8E6F04, 0xA18605, 0xB49D07, 0xC6B408, 0xD9CB0A, 0xECE20B, 0xFFF90D,
    0x57656F, 0x7F9BF1, 0xFFFF53, 0xFF211D, 0x01DD01, 0x6B6B6B, 0x9B9B9B, 0xB3B3B3,
    0xC9C9C9, 0xDFDFDF, 0xE3E3FF, 0xC1B1D1, 0x4D4D4D, 0xFF017F, 0x0101FF,
])

# "Lighter windows, lit blueish at night" — pale blue by day, glowing after
# dark. The tube's light cove is snapped to this exact value.
LIGHT_BLUE = (0x7F, 0x9B, 0xF1)

# Flat marker colour the accent geometry is rendered in.
FLAG_RGB = np.array([255, 0, 255])


def scrub_sheet(sheet: Image.Image, protect_light: bool = False) -> Image.Image:
    """Run the reserved-colour guard over a finished sheet.

    Applied to the whole sheet rather than per cell, because the icons, cursor
    and caption block are pasted in afterwards and would otherwise slip past —
    which is exactly where the first version of this guard missed them.
    """
    mode = sheet.mode
    arr = np.array(sheet.convert("RGBA"))
    protect = None
    if protect_light:
        packed = (arr[..., 0].astype(np.uint32) << 16
                  | arr[..., 1].astype(np.uint32) << 8 | arr[..., 2].astype(np.uint32))
        protect = packed == ((LIGHT_BLUE[0] << 16) | (LIGHT_BLUE[1] << 8) | LIGHT_BLUE[2])
    arr[..., :3] = avoid_special_colours(arr[..., :3], protect)
    return Image.fromarray(arr, "RGBA").convert(mode)


def avoid_special_colours(rgb: np.ndarray, protect: np.ndarray = None) -> np.ndarray:
    """Nudge any pixel that accidentally equals a reserved colour.

    One step on the blue channel is invisible at 128px and takes the pixel out
    of the table. `protect` marks pixels that are *meant* to be a special
    colour and must be left alone.
    """
    packed = (rgb[..., 0].astype(np.uint32) << 16 | rgb[..., 1].astype(np.uint32) << 8
              | rgb[..., 2].astype(np.uint32))
    clash = np.isin(packed, np.fromiter(SPECIAL_COLOURS, dtype=np.uint32))
    if protect is not None:
        clash &= ~protect
    if clash.any():
        out = rgb.copy()
        out[..., 2] = np.where(clash & (rgb[..., 2] > 0),
                               rgb[..., 2].astype(np.int16) - 1,
                               np.where(clash, 1, rgb[..., 2])).astype(np.uint8)
        return out
    return rgb


def ground_mask(spec) -> np.ndarray:
    """Exact tile silhouette, straight from the game's projection."""
    yy, xx = np.mgrid[0:layout.CELL, 0:layout.CELL].astype(float)
    a, b = layout.unproject(xx, yy, layout.tile_shape(spec))
    mask = (np.abs(a) <= 1.0) & (np.abs(b) <= 1.0)
    corner = layout.apron_corner(spec)
    if corner:
        mask &= layout.quarter_test(corner, a, b)
    return mask


def dilate_up(mask: np.ndarray, rows: int) -> np.ndarray:
    """Everything within `rows` pixels above the mask — the tile's air space."""
    out = mask.copy()
    for shift in range(1, rows + 1):
        out[:-shift] |= mask[shift:]
    return out


def downsample(img: Image.Image, factor: int) -> tuple[np.ndarray, np.ndarray]:
    """Box-average an RGBA render down to one cell, returning (rgb, alpha).

    Colour is averaged premultiplied, then divided back out; averaging straight
    colour would drag transparent pixels' undefined colour into the edges.
    """
    arr = np.asarray(img.convert("RGBA"), dtype=np.float64) / 255.0
    n = layout.CELL
    arr = arr.reshape(n, factor, n, factor, 4)

    alpha = arr[..., 3].mean(axis=(1, 3))
    premultiplied = (arr[..., :3] * arr[..., 3:4]).mean(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        rgb = np.where(alpha[..., None] > 1e-6, premultiplied / alpha[..., None], 0.0)
    return np.clip(rgb, 0.0, 1.0), alpha


def fill_holes(rgb: np.ndarray, valid: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Give kept-but-unrendered pixels a colour from their nearest neighbour.

    Only bites on the diamond's extreme tips, where coverage can round to zero.
    """
    holes = keep & ~valid
    if not holes.any():
        return rgb
    out = rgb.copy()
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, -1)):
        if not holes.any():
            break
        shifted_rgb = np.roll(np.roll(rgb, dy, axis=0), dx, axis=1)
        shifted_ok = np.roll(np.roll(valid, dy, axis=0), dx, axis=1)
        take = holes & shifted_ok
        out[take] = shifted_rgb[take]
        holes = holes & ~shifted_ok
    return out


def build_cell(path: pathlib.Path, spec, factor: int) -> np.ndarray:
    rgb, alpha = downsample(Image.open(path), factor)

    ground = ground_mask(spec)
    airspace = dilate_up(ground, MAX_OBJECT_PX)
    keep = ground | (airspace & (alpha >= 0.5))

    rgb = fill_holes(rgb, alpha > 0.02, keep)
    out = np.empty((layout.CELL, layout.CELL, 3), dtype=np.uint8)
    out[:, :] = layout.KEY
    out[keep] = np.round(rgb[keep] * 255.0).astype(np.uint8)
    return avoid_special_colours(out)


# --------------------------------------------------------------------------
# Building sheets (stop, depot)
#
# A building is not clipped to the tile: its roof legitimately rises above the
# diamond and its eaves overhang the neighbours, which is how every pak128
# building behaves. So the silhouette is a plain coverage test.
# --------------------------------------------------------------------------

def build_building_cell(path: pathlib.Path, factor: int) -> np.ndarray:
    rgb, alpha = downsample(Image.open(path), factor)
    keep = alpha >= 0.5
    out = np.empty((layout.CELL, layout.CELL, 3), dtype=np.uint8)
    out[:, :] = layout.KEY
    out[keep] = np.round(rgb[keep] * 255.0).astype(np.uint8)
    return avoid_special_colours(out)


def tile_cursor() -> np.ndarray:
    """Amber diamond outline marking where the building will go."""
    img = np.full((layout.CELL, layout.CELL, 3), layout.KEY, dtype=np.uint8)
    yy, xx = np.mgrid[0:layout.CELL, 0:layout.CELL].astype(float)
    a, b = layout.unproject(xx, yy)
    inside = (np.abs(a) <= 1.0) & (np.abs(b) <= 1.0)
    inner = (np.abs(a) <= 1.0 - 1.6 / layout.UNIT_PX) & \
            (np.abs(b) <= 1.0 - 1.6 / layout.UNIT_PX)
    img[inside & ~inner] = (232, 168, 34)
    return img


def building_icon(kind: str) -> np.ndarray:
    """32x32 toolbar glyph: a platform pair, or a shed with its doorway."""
    img = np.full((layout.CELL, layout.CELL, 3), layout.KEY, dtype=np.uint8)
    img[2:30, 2:30] = (206, 210, 214)
    if kind == "station":
        img[12:15, 4:28] = (150, 154, 158)      # far platform
        img[15:18, 4:28] = (120, 126, 134)      # guideway between them
        img[18:21, 4:28] = (176, 180, 184)      # near platform
        img[20:21, 4:28] = (163, 133, 43)       # safety strip
    else:
        img[16:27, 6:26] = (150, 155, 162)      # hall walls
        img[8:17, 6:26] = (96, 102, 112)        # roof
        img[19:27, 12:20] = (28, 30, 34)        # doorway
    return img


def build_tube_cell(path: pathlib.Path, spec, factor: int, part: str):
    """One cell of an enclosed way, returned as RGB plus fractional alpha.

    The back part holds the apron, so its ground silhouette is still cut
    analytically; the front part is glass standing above the tile and uses
    coverage alone, bounded to the tile's air space so it cannot bleed sideways
    into a neighbour.
    """
    img = np.asarray(Image.open(path).convert("RGBA"))
    # Find the accent at full resolution and paint it out before averaging,
    # so the marker colour cannot bleed a magenta fringe into its neighbours.
    flag = (np.abs(img[..., 0].astype(np.int16) - FLAG_RGB[0]) < 40) & \
           (img[..., 1] < 60) & \
           (np.abs(img[..., 2].astype(np.int16) - FLAG_RGB[2]) < 40) & \
           (img[..., 3] > 128)
    cleaned = img.copy()
    cleaned[flag, 0:3] = np.array(LIGHT_BLUE, dtype=np.uint8)
    n = layout.CELL
    cover = flag.reshape(n, factor, n, factor).mean(axis=(1, 3))

    rgb, alpha = downsample(Image.fromarray(cleaned, "RGBA"), factor)
    ground = ground_mask(spec)
    airspace = dilate_up(ground, TUBE_MAX_PX)

    if part == "back":
        # Unlike an open way, an enclosed one does not pave the tile — it only
        # lays a plinth under itself — so the silhouette cannot be forced to
        # the full diamond. Inside the tile keep whatever was rendered; above
        # it require solid coverage, which stops the swept overrun bleeding
        # into a neighbour.
        keep = np.where(ground, alpha > 0.02, airspace & (alpha >= 0.5))
    else:
        keep = airspace & (alpha > 0.02)

    out_rgb = np.zeros((layout.CELL, layout.CELL, 3), dtype=np.uint8)
    out_a = np.zeros((layout.CELL, layout.CELL), dtype=np.uint8)
    out_rgb[keep] = np.round(np.clip(rgb[keep], 0, 1) * 255.0).astype(np.uint8)
    out_a[keep] = np.clip(np.round(alpha[keep] * 255.0),
                          ALPHA_FLOOR, 255).astype(np.uint8)

    # The light cove has to be the exact reserved value or Simutrans will not
    # treat it as a light, so it is stamped after downsampling — averaging
    # would have shifted it off the table.
    lit = cover >= 0.5
    out_rgb[lit] = LIGHT_BLUE
    out_a[lit] = 255
    out_rgb = avoid_special_colours(out_rgb, protect=lit)
    return np.dstack([out_rgb, out_a])


def tube_icon() -> np.ndarray:
    """32x32 toolbar glyph: a glazed arch with a pod inside."""
    img = np.full((layout.CELL, layout.CELL, 3), layout.KEY, dtype=np.uint8)
    yy, xx = np.mgrid[0:layout.CELL, 0:layout.CELL].astype(float)
    # Superellipse arch, same family as the geometry.
    inside = (np.abs((xx - 15.5) / 13.0) ** 2.6 + np.abs((yy - 28.0) / 22.0) ** 2.6) <= 1.0
    inside &= yy <= 28
    img[inside] = (196, 214, 220)                       # glazing
    core = (np.abs((xx - 15.5) / 10.5) ** 2.6 + np.abs((yy - 28.0) / 18.0) ** 2.6) <= 1.0
    img[inside & core] = (222, 233, 237)
    img[(yy >= 20) & (yy <= 27) & (np.abs(xx - 15.5) <= 7)] = (232, 236, 240)   # pod
    img[(yy >= 22) & (yy <= 24) & (np.abs(xx - 15.5) <= 7)] = (40, 52, 66)      # window band
    img[(yy >= 28) & (yy <= 30) & (np.abs(xx - 15.5) <= 13)] = (150, 155, 162)  # apron
    for rib in (5, 15, 26):                                                     # hoops
        img[inside & (np.abs(xx - rib) <= 0.6)] = (120, 128, 140)
    return img


def assemble_tube(args) -> None:
    from PIL import ImageDraw

    cells_dir = pathlib.Path(args.cells)
    sheet = Image.new("RGBA", (layout.COLS * layout.CELL,
                               layout.TUBE_ROWS * layout.CELL), (0, 0, 0, 0))

    done, missing = 0, []
    for (row, col), spec in sorted(layout.CELL_PLAN.items()):
        for part in ("back", "front"):
            for season in ("summer", "winter"):
                out_row = layout.tube_row(row, part, season)
                path = cells_dir / f"cell_{out_row}_{col}.png"
                if not path.exists():
                    missing.append(f"{out_row}.{col}")
                    continue
                tile = build_tube_cell(path, spec, args.supersample, part)
                sheet.paste(Image.fromarray(tile, "RGBA"),
                            (col * layout.CELL, out_row * layout.CELL))
                done += 1

    def opaque(rgb_tile):
        """RGB cell with the key colour turned into real transparency."""
        alpha = np.where(np.all(rgb_tile == np.array(layout.KEY), axis=-1), 0, 255)
        return Image.fromarray(
            np.dstack([rgb_tile, alpha.astype(np.uint8)]), "RGBA")

    sheet.paste(opaque(tube_icon()), (6 * layout.CELL, 0))
    sheet.paste(opaque(tile_cursor()), (7 * layout.CELL, 0))

    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, 0, 4 * layout.CELL - 1, layout.CELL - 1],
                   fill=(255, 255, 255, 255))
    for i, line in enumerate([
            "name: MAGLEV_TUBE",
            "copyright: Olek - Artistic License 2.0",
            "",
            "generated by tools/blender/build_maglev_track.py --enclosure tube",
            "rows 1-5 back summer, 6-10 front summer,",
            "     11-15 back winter, 16-20 front winter"]):
        draw.text((10, 10 + i * 13), line, fill=(0, 0, 0, 255))

    scrub_sheet(sheet, protect_light=True).save(args.out)
    print(f"wrote {args.out}: {done} cells"
          + (f", {len(missing)} missing" if missing else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cells", help="directory of cell_<row>_<col>.png renders")
    parser.add_argument("-o", "--out", required=True)
    parser.add_argument("--base", help="sheet to take any missing cells from")
    parser.add_argument("--supersample", type=int, default=4)
    parser.add_argument("--sheet", default="track",
                        choices=["track", "tube", "station", "depot", "vehicle"],
                        help="which sheet layout to pack")
    args = parser.parse_args()

    if args.sheet == "tube":
        return assemble_tube(args)
    if args.sheet == "vehicle":
        return assemble_vehicle(args)
    if args.sheet != "track":
        return assemble_building(args)

    cells_dir = pathlib.Path(args.cells)
    size = (layout.COLS * layout.CELL, layout.ROWS * layout.CELL)
    if args.base:
        sheet = Image.open(args.base).convert("RGB")
        if sheet.size != size:
            parser.error(f"--base must be {size[0]}x{size[1]}")
    else:
        sheet = Image.new("RGB", size, layout.KEY)

    done, missing = 0, []
    for (row, col), spec in sorted(layout.CELL_PLAN.items()):
        for season_offset in (0, layout.WINTER_ROW_OFFSET):
            out_row = row + season_offset
            path = cells_dir / f"cell_{out_row}_{col}.png"
            if not path.exists():
                missing.append(f"{out_row}.{col}")
                continue
            tile = build_cell(path, spec, args.supersample)
            sheet.paste(Image.fromarray(tile),
                        (col * layout.CELL, out_row * layout.CELL))
            done += 1

    for col, speed in ((4, 160), (5, 250), (6, 400)):
        sheet.paste(Image.fromarray(render_icon(speed)), (col * layout.CELL, 0))
    sheet.paste(Image.fromarray(render_cursor()), (7 * layout.CELL, 0))
    from PIL import ImageDraw
    render_header(ImageDraw.Draw(sheet))

    scrub_sheet(sheet).save(args.out)
    print(f"wrote {args.out}: {done} rendered cells"
          + (f", {len(missing)} missing ({', '.join(missing[:8])}"
             + ("..." if len(missing) > 8 else "") + ")" if missing else ""))


def assemble_building(args) -> None:
    from PIL import ImageDraw

    cells_dir = pathlib.Path(args.cells)
    sheet = Image.new("RGB", (layout.STATION_COLS * layout.CELL,
                              layout.STATION_ROWS * layout.CELL), layout.KEY)

    done, missing = 0, []
    for (row, col) in sorted(layout.STATION_PLAN):
        path = cells_dir / f"cell_{row}_{col}.png"
        if not path.exists():
            missing.append(f"{row}.{col}")
            continue
        sheet.paste(Image.fromarray(build_building_cell(path, args.supersample)),
                    (col * layout.CELL, row * layout.CELL))
        done += 1

    irow, icol = layout.STATION_ICON_CELL
    sheet.paste(Image.fromarray(building_icon(args.sheet)),
                (icol * layout.CELL, irow * layout.CELL))
    crow, ccol = layout.STATION_CURSOR_CELL
    sheet.paste(Image.fromarray(tile_cursor()), (ccol * layout.CELL, crow * layout.CELL))

    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, 0, layout.STATION_COLS * layout.CELL - 1, layout.CELL - 1],
                   fill=(255, 255, 255))
    for i, line in enumerate([
            f"name: MAGLEV_{args.sheet.upper()}",
            "copyright: Olek - Artistic License 2.0",
            "",
            "generated by tools/blender/build_maglev_buildings.py",
            "row 1: back L0, back L1, front L0, front L1, icon, cursor"]):
        draw.text((10, 12 + i * 14), line, fill=(0, 0, 0))

    scrub_sheet(sheet).save(args.out)
    print(f"wrote {args.out}: {done} rendered cells"
          + (f", missing {', '.join(missing)}" if missing else ""))


def assemble_vehicle(args) -> None:
    """Pack the eight travel directions.

    A vehicle is never clipped to the tile — it leans over the edges as it
    moves between them — so, as with buildings, coverage alone decides the
    silhouette.
    """
    from PIL import ImageDraw

    cells_dir = pathlib.Path(args.cells)
    sheet = Image.new("RGB", (layout.VEHICLE_COLS * layout.CELL,
                              layout.VEHICLE_ROWS * layout.CELL), layout.KEY)

    done, missing = 0, []
    for (row, col), direction in sorted(layout.VEHICLE_PLAN.items()):
        path = cells_dir / f"cell_{row}_{col}.png"
        if not path.exists():
            missing.append(f"{row}.{col} ({direction})")
            continue
        sheet.paste(Image.fromarray(build_building_cell(path, args.supersample)),
                    (col * layout.CELL, row * layout.CELL))
        done += 1

    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, 0, layout.VEHICLE_COLS * layout.CELL - 1, layout.CELL - 1],
                   fill=(255, 255, 255))
    for i, line in enumerate([
            "name: MAGLEV_PASSENGER_SECTION",
            "copyright: Olek - Artistic License 2.0",
            "",
            "generated by tools/blender/build_maglev_vehicle.py",
            "row 1: w, nw, n, ne, e, se, s, sw"]):
        draw.text((10, 12 + i * 14), line, fill=(0, 0, 0))

    scrub_sheet(sheet).save(args.out)
    print(f"wrote {args.out}: {done} directions"
          + (f", missing {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()
