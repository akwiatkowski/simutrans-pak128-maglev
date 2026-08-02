#!/usr/bin/env python3
"""Render the maglev guideway sprite sheet for pak128.

The sheet mirrors the layout of pak128's `rail_400_tracks.png` cell for cell, so
the `.dat` files can address the same `image.row.col` slots. What changes is the
artwork: instead of two rails on a ballast strip, every tile carries a
continuous Transrapid-style guideway girder sitting on the same concrete apron.

Sheet layout (8 columns x 11 rows of 128px cells)
-------------------------------------------------
    row 0     header text, three speed icons (0.4/0.5/0.6), build cursor (0.7)
    rows 1-5  summer tiles
    rows 6-10 winter tiles (same order, snow palette)

How the tiles are drawn
-----------------------
Everything is evaluated per pixel in *ground* coordinates rather than
rasterised as polygons, which keeps the pixel art crisp (no anti-aliased
fringes against Simutrans' `#E7FFFF` transparency key) and makes slopes and
diagonals fall out of the same code path.

A tile's ground plane uses local coordinates `(a, b)` in `[-1, 1]^2`:

    a = +1 towards the N edge midpoint   (screen: up-right)
    b = +1 towards the E edge midpoint   (screen: down-right)

which projects to screen pixels as

    x = CX + 32 * (a + b)
    y = y0 +  p * a + q * b

`(p, q, y0)` depend on the tile shape: flat, or one of the four single-height
ramps. The ramps were measured off pak128's own rail sheet, so the maglev tiles
sit exactly on the same ground quads (see `SHAPES`).

The guideway is a prism of height `H_BEAM` standing on that plane. For a screen
pixel we walk `k` downwards from the tallest possible beam height: the ground
point under `(x, y + k)` that is inside the footprint with height exactly `k`
is the visible top surface; a hit with height greater than `k` means we are
looking at the girder's front wall.

Usage
-----
    python3 tools/render_maglev_track.py -o src/maglev/images/maglev_track.png
    python3 tools/render_maglev_track.py -o /tmp/preview.png --preview /tmp/zoom.png
"""

from __future__ import annotations

import argparse

import numpy as np
from PIL import Image, ImageDraw

# --------------------------------------------------------------------------
# Sheet constants
# --------------------------------------------------------------------------

CELL = 128
COLS, ROWS = 8, 11
# Simutrans reads this exact colour as transparent (SPECIAL_TRANSPARENT in the
# game's descriptor/image.h). Anything else ends up in the .pak.
KEY = (231, 255, 255)

# Centre of a flat tile inside its cell, measured from pak128's rail sheet: the
# diamond spans y=65..127 and x=0..127.
CX, CY = 63.5, 96.0

# Screen projection per tile shape: (p, q, y0) for y = y0 + p*a + q*b.
# Flat is the plain 2:1 isometric diamond. Each ramp raises two adjacent
# corners by 16px, which is pak128's height step; the names match the
# `ImageUp[3|6|9|12]` slots, whose way_writer order is n, w, e, s.
SHAPES = {
    "flat": (-16.0, 16.0, 96.0),
    "up_n": (-8.0, 16.0, 88.0),   # left + bottom corners raised
    "up_w": (-16.0, 8.0, 88.0),   # right + bottom corners raised
    "up_e": (-16.0, 24.0, 88.0),  # top + left corners raised
    "up_s": (-24.0, 16.0, 88.0),  # top + right corners raised
}

# One unit of `a` or `b` is this many screen pixels along the ground plane.
# |(32, -16)| = |(32, 16)| = 35.777, and it stays the same on every ramp, so a
# single scale converts ground units to the pixel widths used below.
UNIT_PX = np.hypot(32.0, 16.0)

# --------------------------------------------------------------------------
# Guideway design
#
# Cross-section of the girder, in screen pixels from the centreline. 14px wide
# against pak128's ~11px rail pair: a single solid band rather than two thin
# lines, and narrow enough that the vehicle overhangs it the way a Transrapid
# wraps its guideway.
#
# What separates this from rail at a glance is *rhythm*. Rail is a dashed
# texture — sleeper after sleeper. The guideway is deliberately smooth: one
# continuous band, two crisp guidance slots, and girder joints only every
# quarter tile. Absence of the tie pattern is the strongest maglev cue
# available at 128px, so nothing here repeats faster than that.
# --------------------------------------------------------------------------

BEAM_HALF = 7.0     # half width of the girder
H_BEAM = 3          # girder height above the apron, in screen pixels
H_CAP = 6           # height of the stop block closing an unconnected end
CAP_LEN = 6.0       # length of that stop block, along the beam
JOINT_PITCH = 32.0  # girder segment joints, along the beam

# Palette. The apron stays pak128's neutral concrete so the addon sits in the
# same family as the rail sets. The girder is the same value range as a
# railhead — bright top, dark slots — but pushed a few points cool, and the
# levitation channel carries one restrained tint. That tint is the only
# non-grey in the sheet; any more and it stops reading as infrastructure.
SUMMER = {
    "apron": (189, 189, 189),
    "apron_seam": (178, 178, 179),
    "beam_rim": (232, 236, 240),
    "beam_stator": (206, 212, 218),
    "beam_groove": (126, 133, 142),
    "beam_centre": (211, 216, 221),
    "beam_accent": (176, 197, 208),
    "beam_joint": (168, 175, 182),
    "wall_dark": (116, 122, 130),
    "wall_lit": (150, 157, 165),
    "cap_top": (196, 200, 205),
    "cap_wall": (96, 101, 108),
    "contact": (164, 166, 168),
}
WINTER = {
    "apron": (228, 231, 233),
    "apron_seam": (216, 219, 221),
    "beam_rim": (243, 246, 248),
    "beam_stator": (230, 234, 238),
    "beam_groove": (112, 119, 128),
    "beam_centre": (234, 238, 241),
    "beam_accent": (198, 214, 222),
    "beam_joint": (206, 211, 215),
    "wall_dark": (124, 130, 138),
    "wall_lit": (158, 165, 173),
    "cap_top": (222, 226, 230),
    "cap_wall": (104, 110, 117),
    "contact": (200, 203, 205),
}

# pak128 lights this sheet from the lower left: its ramp facing that way is the
# brightest tile on the rail sheet (mean 222) and the opposite ramp the darkest
# (mean 167), against 186 for flat ground. Same factors here.
RAMP_SHADE = {"flat": 1.0, "up_n": 0.90, "up_w": 1.01, "up_e": 1.00, "up_s": 1.18}

# --------------------------------------------------------------------------
# Ribi codes
#
# Simutrans encodes way connections as a bitmask, n=1 e=2 s=4 w=8, and
# way_writer.cc expects the image list in that numeric order followed by the
# ten switch variants. `-` means an isolated tile with no connections.
# --------------------------------------------------------------------------

N, E, S, W = 1, 2, 4, 8


def segments_for(ribi: int, variant: int = 0) -> list[dict]:
    """Guideway pieces for a connection mask.

    Each piece is a straight run of girder. `kind` selects the axis, `z` the
    draw order (higher wins where two runs overlap) and `taper` narrows a run
    towards the tile centre so the through route visually dominates a switch.
    """
    has = lambda bit: bool(ribi & bit)
    segs: list[dict] = []

    if ribi == 0:
        # pak128 draws the isolated tile as a full crossing closed off by
        # buffer stops on all four ends; we do the same with stop blocks.
        segs.append(dict(kind="b", lo=-1.0, hi=1.0, z=0, cap_lo=True, cap_hi=True))
        segs.append(dict(kind="a", lo=-1.0, hi=1.0, z=1, cap_lo=True, cap_hi=True))
        return segs

    # The N/S axis runs along `a`, the E/W axis along `b`. A single stub still
    # draws the whole straight and closes the unused end, matching pak128.
    ns_lo = -1.0 if has(S) else (0.0 if has(N) else None)
    ns_hi = 1.0 if has(N) else (0.0 if has(S) else None)
    ew_lo = -1.0 if has(W) else (0.0 if has(E) else None)
    ew_hi = 1.0 if has(E) else (0.0 if has(W) else None)

    ns_only = has(N) != has(S) and not (has(E) or has(W))
    ew_only = has(E) != has(W) and not (has(N) or has(S))

    if ns_only:
        ns_lo, ns_hi = -1.0, 1.0
    if ew_only:
        ew_lo, ew_hi = -1.0, 1.0

    # Switch variants only change which route runs through unbroken, so they
    # differ purely in draw order. Variant 2 is the flat crossing: neither
    # route gives way and both flare into a shared junction pad instead.
    flare = variant == 2
    ns_on_top = variant != 1

    if ns_lo is not None:
        segs.append(dict(kind="a", lo=ns_lo, hi=ns_hi, z=2 if ns_on_top else 1,
                         cap_lo=ns_only and not has(S), cap_hi=ns_only and not has(N),
                         flare=flare))
    if ew_lo is not None:
        segs.append(dict(kind="b", lo=ew_lo, hi=ew_hi, z=1 if ns_on_top else 2,
                         cap_lo=ew_only and not has(W), cap_hi=ew_only and not has(E),
                         flare=flare))
    return segs


def diagonal_segments(corner: str) -> list[dict]:
    """The short run that links two adjacent edge midpoints of one tile.

    N+E both leave on the right-hand side of the diamond, so the connecting
    girder is the line `a + b = 1`, which projects to a vertical band. The
    other three corners are the same line mirrored.
    """
    line = {"ne": ("dsum", 1.0), "sw": ("dsum", -1.0),
            "nw": ("ddif", 1.0), "se": ("ddif", -1.0)}[corner]
    return [dict(kind=line[0], c=line[1], lo=-2.0, hi=2.0, z=1)]


def diagonal_apron(corner: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Quarter-tile apron that pak128 uses for the corner/diagonal images."""
    return {"ne": a + b >= 0, "sw": a + b <= 0,
            "nw": a - b >= 0, "se": a - b <= 0}[corner]


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def unproject(x: np.ndarray, y: np.ndarray, shape: str) -> tuple[np.ndarray, np.ndarray]:
    """Screen pixel -> ground coordinates on this tile's (possibly tilted) plane."""
    p, q, y0 = SHAPES[shape]
    xu = (x - CX) / 32.0          # equals a + b
    yu = y - y0                   # equals p*a + q*b
    a = (yu - q * xu) / (p - q)
    return a, xu - a


def seg_coords(seg: dict, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance along the run and perpendicular offset, both in screen pixels."""
    kind = seg["kind"]
    if kind == "a":
        return a * UNIT_PX, b * UNIT_PX
    if kind == "b":
        return b * UNIT_PX, a * UNIT_PX
    if kind == "dsum":        # girder along the line a + b = c
        return 16.0 * (a - b), 32.0 * (a + b - seg["c"])
    return 32.0 * (a + b), 32.0 * (a - b - seg["c"])   # "ddif"


def cap_zone(seg: dict, along: np.ndarray) -> np.ndarray:
    """Where an unconnected end is closed off by a stop block."""
    lo, hi = seg_limits(seg)
    zone = np.zeros(along.shape, dtype=bool)
    if seg.get("cap_lo"):
        zone |= along < lo + CAP_LEN
    if seg.get("cap_hi"):
        zone |= along > hi - CAP_LEN
    return zone


def seg_half_width(seg: dict, along: np.ndarray) -> np.ndarray:
    """Half width: flared into a pad at a flat crossing, and at a stop block."""
    half = np.full_like(along, BEAM_HALF)
    if seg.get("flare"):
        half = BEAM_HALF * (1.0 + 0.4 * np.clip(1.0 - np.abs(along) / 22.0, 0.0, 1.0))
    return np.where(cap_zone(seg, along), BEAM_HALF + 2.5, half)


def seg_limits(seg: dict) -> tuple[float, float]:
    """Run extent along the girder, in screen pixels."""
    scale = UNIT_PX if seg["kind"] in ("a", "b") else 32.0
    return seg["lo"] * scale, seg["hi"] * scale


def seg_height(seg: dict, along: np.ndarray) -> np.ndarray:
    """Girder height, raised where an unconnected end is closed by a stop block."""
    return np.where(cap_zone(seg, along), float(H_CAP), float(H_BEAM))


def seg_inside(seg: dict, a: np.ndarray, b: np.ndarray):
    """Footprint mask plus the along/perp coordinates, for one run."""
    along, perp = seg_coords(seg, a, b)
    lo, hi = seg_limits(seg)
    inside = (np.abs(perp) <= seg_half_width(seg, along)) & (along >= lo) & (along <= hi)
    return inside, along, perp


# --------------------------------------------------------------------------
# Shading
# --------------------------------------------------------------------------

def _mix(dst: np.ndarray, mask: np.ndarray, colour) -> None:
    dst[mask] = colour


def shade_apron(rgb: np.ndarray, mask: np.ndarray, a: np.ndarray, b: np.ndarray,
                pal: dict, rng: np.random.Generator) -> None:
    """Concrete slab: flat base, a little grain, and panel joints on a grid."""
    base = np.array(pal["apron"], dtype=np.int16)
    # Fine grain plus a slow swell across the tile, so the slab is not a dead
    # flat fill the way a plain fill would read next to pak128's mottling.
    grain = rng.integers(-3, 4, size=a.shape + (1,))
    swell = (2.5 * np.sin(2.2 * a + 1.1) * np.cos(1.7 * b - 0.4))[..., None]
    slab = np.clip(base + grain + swell, 0, 255).astype(np.uint8)
    rgb[mask] = slab[mask]

    seam = np.zeros(a.shape, dtype=bool)
    for coord in (a, b):
        for line in (-0.5, 0.5):
            seam |= np.abs((coord - line) * UNIT_PX) < 0.6
    _mix(rgb, mask & seam, pal["apron_seam"])


def shade_top(rgb: np.ndarray, mask: np.ndarray, perp: np.ndarray, along: np.ndarray,
              pal: dict) -> None:
    """Top of the girder: bright deck, two guidance slots, one tinted channel."""
    ap = np.abs(perp)
    _mix(rgb, mask & (ap >= 6.0), pal["beam_rim"])
    _mix(rgb, mask & (ap >= 4.5) & (ap < 6.0), pal["beam_stator"])
    _mix(rgb, mask & (ap >= 3.0) & (ap < 4.5), pal["beam_groove"])
    _mix(rgb, mask & (ap < 3.0), pal["beam_centre"])
    _mix(rgb, mask & (ap < 1.0), pal["beam_accent"])
    # Girder joints: one line across the full deck every 32px. Far sparser
    # than sleepers, on purpose — this is the beat that tells maglev apart
    # from rail, so it has to stay slow and it has to read as one clean line.
    joint = np.abs((along % JOINT_PITCH) - JOINT_PITCH / 2) > JOINT_PITCH / 2 - 0.6
    _mix(rgb, mask & joint, pal["beam_joint"])


def shade_wall(rgb: np.ndarray, mask: np.ndarray, kind: str, pal: dict) -> None:
    """Front wall of the girder.

    A run along `a` presents its wall to the lower right, away from pak128's
    lower-left key light, so it reads darker than a run along `b`.
    """
    _mix(rgb, mask, pal["wall_dark"] if kind in ("a", "dsum") else pal["wall_lit"])


# --------------------------------------------------------------------------
# Tile rendering
# --------------------------------------------------------------------------

def render_tile(segs: list[dict], shape: str = "flat", season: str = "summer",
                apron: str | None = None, seed: int = 0) -> np.ndarray:
    """Render one 128x128 cell.

    `apron` selects a quarter-tile slab ("ne"/"se"/"nw"/"sw") for the corner
    images; `None` paves the whole diamond like the straight pieces do.
    """
    pal = SUMMER if season == "summer" else WINTER
    rng = np.random.default_rng(seed)

    rgb = np.zeros((CELL, CELL, 3), dtype=np.uint8)
    rgb[:, :] = KEY
    yy, xx = np.mgrid[0:CELL, 0:CELL].astype(float)

    # Apron first: it only exists at ground level.
    a0, b0 = unproject(xx, yy, shape)
    on_tile = (np.abs(a0) <= 1.0) & (np.abs(b0) <= 1.0)
    apron_mask = on_tile & (diagonal_apron(apron, a0, b0) if apron else True)
    shade_apron(rgb, apron_mask, a0, b0, pal, rng)

    # Then the girder, walking down from the tallest stop block so the first
    # hit for a pixel is always the surface nearest the camera.
    assigned = np.zeros((CELL, CELL), dtype=bool)
    for k in range(H_CAP, -1, -1):
        a, b = unproject(xx, yy + k, shape)
        in_tile = (np.abs(a) <= 1.0) & (np.abs(b) <= 1.0)

        best_z = np.full((CELL, CELL), -1, dtype=np.int8)
        hit = np.zeros((CELL, CELL), dtype=bool)
        top = np.zeros((CELL, CELL), dtype=bool)
        cap = np.zeros((CELL, CELL), dtype=bool)
        kind_id = np.zeros((CELL, CELL), dtype=np.int8)
        along_of = np.zeros((CELL, CELL))
        perp_of = np.zeros((CELL, CELL))

        for seg in segs:
            inside, along, perp = seg_inside(seg, a, b)
            height = seg_height(seg, along)
            m = inside & in_tile & (k <= height) & (seg["z"] >= best_z)
            if not m.any():
                continue
            best_z[m] = seg["z"]
            hit |= m
            top[m] = k == height[m]
            cap[m] = height[m] > H_BEAM
            kind_id[m] = 0 if seg["kind"] in ("a", "dsum") else 1
            along_of[m] = along[m]
            perp_of[m] = perp[m]

        fresh = hit & ~assigned
        shade_top(rgb, fresh & top & ~cap, perp_of, along_of, pal)
        shade_wall(rgb, fresh & ~top & ~cap & (kind_id == 0), "a", pal)
        shade_wall(rgb, fresh & ~top & ~cap & (kind_id == 1), "b", pal)
        # The stop block closing an unconnected end is one solid object rather
        # than a taller slice of girder, so it gets its own two tones.
        _mix(rgb, fresh & cap & top, pal["cap_top"])
        _mix(rgb, fresh & cap & ~top, pal["cap_wall"])
        assigned |= fresh

    # Contact shadow: one line of apron directly under the girder's front wall.
    below = np.zeros((CELL, CELL), dtype=bool)
    below[1:] = assigned[:-1]
    _mix(rgb, below & ~assigned & apron_mask, pal["contact"])

    # Ramps are pre-shaded, the way pak128 pre-shades its own slope tiles.
    factor = RAMP_SHADE[shape]
    if factor != 1.0:
        drawn = apron_mask | assigned
        lit = np.clip(rgb.astype(float) * factor, 0, 255).astype(np.uint8)
        rgb[drawn] = lit[drawn]

    rgb[~(apron_mask | assigned)] = KEY
    return rgb


# --------------------------------------------------------------------------
# Icons, cursor, header
# --------------------------------------------------------------------------

# 3x5 digits, enough for the speed numbers on the tool icons.
DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


def render_icon(speed: int) -> np.ndarray:
    """32x32 tool icon: pak128's speed-sign convention plus a guideway stripe."""
    img = np.full((CELL, CELL, 3), KEY, dtype=np.uint8)
    cx, cy, r = 15.5, 13.0, 12.0
    yy, xx = np.mgrid[0:CELL, 0:CELL].astype(float)
    d = np.hypot(xx - cx, yy - cy)
    img[d <= r] = (250, 250, 250)
    img[(d <= r) & (d > r - 3.0)] = (196, 32, 32)

    text = str(speed)
    width = len(text) * 4 - 1
    ox, oy = int(cx - width / 2) + 1, int(cy - 2.5)
    for i, ch in enumerate(text):
        for row, bits in enumerate(DIGITS[ch]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    img[oy + row, ox + i * 4 + col] = (24, 24, 28)

    # A slice of guideway under the sign, so the icon reads as maglev and not
    # as another rail speed class.
    img[27:31, 2:30] = SUMMER["apron"]
    img[27:29, 6:26] = SUMMER["beam_stator"]
    img[28:29, 6:26] = SUMMER["beam_accent"]
    img[29:31, 6:26] = SUMMER["wall_dark"]
    return img


def render_cursor() -> np.ndarray:
    """Build cursor: a straight piece of guideway inside an amber tile outline."""
    tile = render_tile(segments_for(N | S), seed=99)
    yy, xx = np.mgrid[0:CELL, 0:CELL].astype(float)
    a, b = unproject(xx, yy, "flat")
    on_tile = (np.abs(a) <= 1.0) & (np.abs(b) <= 1.0)
    edge = on_tile & ~(
        (np.abs(a) <= 1.0 - 1.2 / UNIT_PX) & (np.abs(b) <= 1.0 - 1.2 / UNIT_PX)
    )
    tile[edge] = (232, 168, 34)
    return tile


def render_header(draw: ImageDraw.ImageDraw) -> None:
    """Human-readable caption block, the same courtesy pak128 sheets extend."""
    draw.rectangle([0, 0, 512, CELL - 1], fill=(255, 255, 255))
    lines = [
        "name: MAGLEV_TRACKS",
        "copyright: Aleksander Kwiatkowski - Artistic License 2.0",
        "",
        "generated by tools/render_maglev_track.py",
        "speeds: 160 / 250 / 400 km/h",
    ]
    for i, line in enumerate(lines):
        draw.text((10, 12 + i * 14), line, fill=(0, 0, 0))


# --------------------------------------------------------------------------
# Sheet assembly
# --------------------------------------------------------------------------

# Cell -> tile recipe, matching rail_400_tracks.dat slot for slot. Rows are
# given for the summer block; the winter block repeats them five rows down.
def season_plan() -> dict[tuple[int, int], dict]:
    ribi_cells = {
        (1, 0): 0,
        (1, 1): N, (1, 2): S, (1, 3): E, (1, 4): W,
        (1, 5): N | S, (1, 6): E | W, (1, 7): N | S | E,
        (2, 0): N | S | W, (2, 1): N | E | W, (2, 2): S | E | W, (2, 3): N | S | E | W,
    }
    plan: dict[tuple[int, int], dict] = {
        cell: dict(ribi=ribi, variant=0) for cell, ribi in ribi_cells.items()
    }

    # Switch variants: same connections, different through route.
    for cell, ribi in {(2, 4): N | S | E, (2, 5): N | S | W,
                       (2, 6): N | E | W, (2, 7): S | E | W,
                       (3, 0): N | S | E | W}.items():
        plan[cell] = dict(ribi=ribi, variant=1)
    for cell, ribi in {(3, 1): N | S | E, (3, 2): N | S | W,
                       (3, 3): N | E | W, (3, 4): S | E | W,
                       (3, 5): N | S | E | W}.items():
        plan[cell] = dict(ribi=ribi, variant=2)

    # Corner pieces. pak128 ships both a full-tile and a quarter-tile version
    # and its .dat references the quarter one, so we provide the same pair.
    for cell, corner, quarter in [((3, 6), "ne", False), ((3, 7), "ne", True),
                                  ((4, 0), "se", False), ((4, 1), "se", True),
                                  ((4, 2), "nw", False), ((4, 3), "nw", True),
                                  ((4, 4), "sw", False), ((4, 5), "sw", True)]:
        plan[cell] = dict(corner=corner, quarter=quarter)

    # Ramps, in way_writer's ImageUp order: 3=n, 6=w, 9=e, 12=s.
    for cell, shape, ribi in [((4, 6), "up_n", N | S), ((4, 7), "up_w", E | W),
                              ((5, 0), "up_e", E | W), ((5, 1), "up_s", N | S)]:
        plan[cell] = dict(ribi=ribi, variant=0, shape=shape)

    return plan


def build_sheet() -> Image.Image:
    sheet = Image.new("RGB", (COLS * CELL, ROWS * CELL), KEY)
    plan = season_plan()

    for season, row_offset in (("summer", 0), ("winter", 5)):
        for (row, col), spec in plan.items():
            if "corner" in spec:
                segs = diagonal_segments(spec["corner"])
                apron = spec["corner"] if spec["quarter"] else None
                shape = "flat"
            else:
                segs = segments_for(spec["ribi"], spec.get("variant", 0))
                apron, shape = None, spec.get("shape", "flat")
            seed = row * 31 + col * 7 + (0 if season == "summer" else 1000)
            tile = render_tile(segs, shape, season, apron, seed)
            sheet.paste(Image.fromarray(tile), (col * CELL, (row + row_offset) * CELL))

    for col, speed in ((4, 300), (5, 500), (6, 700)):
        sheet.paste(Image.fromarray(render_icon(speed)), (col * CELL, 0))
    sheet.paste(Image.fromarray(render_cursor()), (7 * CELL, 0))
    render_header(ImageDraw.Draw(sheet))
    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--out", default="src/maglev/images/maglev_track.png")
    parser.add_argument("--preview", help="also write a 4x zoom of a few key cells")
    args = parser.parse_args()

    sheet = build_sheet()
    sheet.save(args.out)
    print(f"wrote {args.out} ({sheet.width}x{sheet.height})")

    if args.preview:
        cells = [(1, 5), (1, 6), (2, 3), (1, 1), (3, 7), (4, 6), (5, 1), (6, 5)]
        zoom = 4
        out = Image.new("RGB", (CELL * zoom * 4, CELL * zoom * 2), KEY)
        for i, (r, c) in enumerate(cells):
            crop = sheet.crop((c * CELL, r * CELL, (c + 1) * CELL, (r + 1) * CELL))
            crop = crop.resize((CELL * zoom, CELL * zoom), Image.NEAREST)
            out.paste(crop, ((i % 4) * CELL * zoom, (i // 4) * CELL * zoom))
        out.save(args.preview)
        print(f"wrote {args.preview}")


if __name__ == "__main__":
    main()
