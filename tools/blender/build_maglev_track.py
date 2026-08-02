"""Build and render the maglev guideway tiles in Blender.

Run headless; it writes one RGBA PNG per sheet cell, which
`tools/assemble_sheet.py` then packs into the pak128 sprite sheet.

    blender --background --python tools/blender/build_maglev_track.py -- \
        --out build/cells --season summer

    # fast iteration on a few cells
    blender --background --python tools/blender/build_maglev_track.py -- \
        --out /tmp/cells --cells 1.5 2.3 3.7 4.6 --samples 32

The guideway
------------
Modelled to Transrapid proportions against a 16m tile: a 3.1m girder standing
1.0m above a concrete apron, its deck carrying two recessed guidance slots for
the stator packs. Everything is one extruded cross-section (`PROFILE`) swept
along straight runs, so the slots, the deck overhang and the girder sides all
come from a single polygon — change the profile and every tile follows.

Going through Blender rather than drawing the band by hand buys three things
that are painful in 2D: real contact shadows where the girder meets the apron,
ambient occlusion inside the guidance slots, and correct foreshortening on the
ramp tiles.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import simutrans_iso as iso          # noqa: E402
import pak128_layout as layout       # noqa: E402

# --------------------------------------------------------------------------
# Guideway cross-section, in metres from the centreline. Ordered
# counter-clockwise in the (perp, height) plane and mirrored about the centre,
# so only the right half is written out.
#
#      deck ______--+--______ deck
#          /  slot     slot  \
#         |                   |
#         |      girder       |
#     ----+-------------------+----  apron
# --------------------------------------------------------------------------

GIRDER_HALF = 1.40      # body half width
DECK_HALF = 1.60        # deck overhangs the body, so it catches a rim light
DECK_TOP = 0.85         # girder height above the apron
SLOT_INNER, SLOT_OUTER = 0.60, 1.10
SLOT_FLOOR = 0.74
LEVITATION_HALF = 0.30  # slightly proud centre strip the vehicle rides over

RIGHT_HALF = [
    (0.0, DECK_TOP + 0.04),                    # 0  centre of the levitation strip
    (LEVITATION_HALF, DECK_TOP + 0.04),        # 1
    (LEVITATION_HALF + 0.06, DECK_TOP),        # 2
    (SLOT_INNER, DECK_TOP),                    # 3
    (SLOT_INNER, SLOT_FLOOR),                  # 4  down into the guidance slot
    (SLOT_OUTER, SLOT_FLOOR),                  # 5
    (SLOT_OUTER, DECK_TOP),                    # 6  back up to the deck
    (DECK_HALF, DECK_TOP),                     # 7  outer edge of the deck
    (DECK_HALF, DECK_TOP - 0.22),              # 8
    (GIRDER_HALF, DECK_TOP - 0.34),            # 9  deck overhangs the body here
    (GIRDER_HALF, 0.0),                        # 10 down to the apron
]
# Closed loop: up the mirrored left side, over the deck, down the right side.
# The final edge back to the start is the underside, hidden against the apron.
PROFILE_M = [(-p, h) for p, h in reversed(RIGHT_HALF)] + RIGHT_HALF[1:]

# Profile edge i is the face swept between profile points i and i+1. Naming
# them here keeps material assignment independent of world position, which
# matters on the ramps where the whole section is tilted.
LEFT = len(RIGHT_HALF)          # index of the centre point, 11
SLOT_EDGES = [4, 5, 6, LEFT + 2, LEFT + 3, LEFT + 4]
DECK_EDGES = [LEFT - 2, LEFT - 1]   # the two halves of the levitation strip

STOP_BLOCK_LEN = 0.9    # metres of girder closed off at an unconnected end
STOP_BLOCK_TOP = 2.1

# Runs are swept a little past the tile so nothing shows a hairline seam. A
# corner piece needs a full deck half-width of overrun: its band is cut by the
# tile edge at 45°, so the last of it sits beyond the edge midpoints.
OVERRUN_STRAIGHT = 0.15   # metres
OVERRUN_CORNER = DECK_HALF + 0.2
CROSSING_LIFT = 0.02      # metres, breaks the coplanar decks at a junction

PALETTE = {
    "summer": {
        "apron": (0.500, 0.500, 0.500),
        "girder": (0.610, 0.625, 0.645),
        "slot": (0.255, 0.275, 0.300),
        "levitation": (0.430, 0.480, 0.520),
        "glass_tint": (0.62, 0.78, 0.82),
        "glass_face": 0.10,          # nearly clear where you look through it
        "glass_edge": 0.60,          # bright along the silhouette
        "frame": (0.470, 0.495, 0.535),
    },
    "winter": {
        "apron": (0.790, 0.805, 0.815),
        "girder": (0.800, 0.815, 0.830),
        "slot": (0.235, 0.255, 0.280),
        "levitation": (0.480, 0.530, 0.570),
        "glass_tint": (0.72, 0.84, 0.88),
        "glass_face": 0.12,
        "glass_edge": 0.78,
        "frame": (0.560, 0.585, 0.620),
    },
}


def profile_world():
    return [(iso.m(p), iso.m(h)) for p, h in PROFILE_M]


# --------------------------------------------------------------------------
# Enclosure: the glass tube of the high-speed tiers.
#
# Cross-section is a superellipse arch springing from the apron, not a circle:
# a flattened crown with drawn-in shoulders reads as an engineered fairing,
# and silhouette is most of what the eye gets at 128px.
#
# The tube is split down its crown into a near and a far half. The far half
# ships in the back image with the beam; the near half ships in the front
# image, which Simutrans draws after vehicles, so a pod is seen *through* the
# glass rather than hidden behind it.
# --------------------------------------------------------------------------

TUBE_HALF_WIDTH = 2.60   # springing point, metres from the centreline
TUBE_HEIGHT = 3.90       # crown height above the apron
TUBE_THICKNESS = 0.18    # glazing plus frame; gives the silhouette two edges
TUBE_EXPONENT = 2.6      # 2 would be a plain semi-ellipse; higher flattens
TUBE_SEGMENTS = 11

# Two hoops per tile. Every hoop shows twice — you see the far one through the
# glass — so the on-screen rhythm is double the pitch. At 4m it read as a
# polytunnel; 8m leaves the glass room to be glass.
# Tier character. Escalation is *density of engineering*, not new shapes —
# same reason the guideway ladder works. The 4000 tier deliberately gets the
# sparsest framing: greebles read as industrial, and at the endgame a smoother,
# more seamless tube reads as the more advanced one.
TUBE_TIERS = {
    1000: dict(rib_pitch=8.0, tint=(0.62, 0.78, 0.82), face=0.10, edge=0.60,
               frame=(0.470, 0.495, 0.535)),
    2000: dict(rib_pitch=6.0, tint=(0.52, 0.70, 0.76), face=0.13, edge=0.66,
               frame=(0.400, 0.430, 0.480)),
    4000: dict(rib_pitch=11.0, tint=(0.44, 0.60, 0.70), face=0.16, edge=0.72,
               frame=(0.330, 0.360, 0.420)),
}

RIB_PITCH = 8.0          # metres between structural hoops
RIB_WIDTH = 0.26
RIB_PROUD = 0.09         # how far a rib stands off the glazing

# Foundation strip carried under the tube instead of an apron across the tile.
PLINTH_HALF = 3.05
PLINTH_TOP = 0.20

# Light cove along the springing line. Rendered in a flag colour and swapped
# during packing for a Simutrans light that does not dim at night.
COVE_LO, COVE_HI = 0.26, 0.66
COVE_PROUD = 0.07

# A continuous spine along the crown. One unbroken line down the run is what
# separates engineered infrastructure from a greenhouse.
SPINE_HALF = 0.34
SPINE_DEPTH = 0.13


def arch(half_width, height, segments=TUBE_SEGMENTS):
    """Half a superellipse arch, crown first, as (perp, height) in metres."""
    points = []
    for i in range(segments + 1):
        angle = (math.pi / 2) * i / segments
        points.append((half_width * math.sin(angle) ** (2.0 / TUBE_EXPONENT),
                       height * math.cos(angle) ** (2.0 / TUBE_EXPONENT)))
    return points


def tube_profile(swell=0.0, scale=1.0):
    """Closed crescent for one half of the tube wall, in world units.

    Outer arc from crown to springing, across the thickness, inner arc back.
    `swell` fattens it into a rib.
    """
    half, high = TUBE_HALF_WIDTH * scale, TUBE_HEIGHT * scale
    outer = arch(half + swell, high + swell)
    inner = arch(half + swell - TUBE_THICKNESS, high + swell - TUBE_THICKNESS)
    loop = outer + list(reversed(inner))
    return [(iso.m(p), iso.m(h)) for p, h in loop]


def rib_positions(start, axis, length, pitch=RIB_PITCH):
    """World positions of the hoops along a run.

    Measured from the world origin rather than from the run, so hoops line up
    across tile boundaries the same way the apron's panel joints do.
    """
    origin_offset = start.dot(axis) / iso.m(1.0)      # in metres
    first = math.ceil(origin_offset / pitch) * pitch
    out, here = [], first
    while here < origin_offset + length / iso.m(1.0):
        out.append(iso.m(here - origin_offset))
        here += pitch
    return out


# --------------------------------------------------------------------------
# Runs: the same connection model the 2D renderer uses, expressed in world axes
# --------------------------------------------------------------------------

# Edge midpoints of the tile in world coordinates. These are where a way
# leaves the tile, and every run is drawn between two of them.
EDGE_MID = {layout.N: (0.0, 0.5), layout.S: (0.0, -0.5),
            layout.E: (0.5, 0.0), layout.W: (-0.5, 0.0)}


def runs_for(spec):
    """Girder runs for one cell.

    Yields dicts with `start`, `end`, `cap_start`, `cap_end`, `overrun` and
    `lift`. World +Y is the N axis and world +X the E axis, both spanning
    -0.5..0.5 across the tile.

    `lift` raises the through route by a couple of centimetres where two runs
    cross. Their decks are otherwise exactly coplanar, which z-fights into
    speckle at the junction; the offset is a tenth of a pixel on screen but
    settles the depth test, and which route wins is what the switch variants
    are for.
    """
    def run(start, end, cap_start=False, cap_end=False,
            overrun=OVERRUN_STRAIGHT, lift=0.0):
        return {"start": start, "end": end, "cap_start": cap_start,
                "cap_end": cap_end, "overrun": overrun, "lift": lift}

    if "corner" in spec:
        # N and E both leave on the right-hand side of the diamond, so the run
        # linking them is simply the straight line between those two edge
        # midpoints — which projects to a vertical band on screen.
        first, second = {"ne": (layout.N, layout.E), "se": (layout.S, layout.E),
                         "nw": (layout.N, layout.W), "sw": (layout.S, layout.W)}[
            spec["corner"]]
        return [run(EDGE_MID[first], EDGE_MID[second], overrun=OVERRUN_CORNER)]

    ribi = spec["ribi"]
    has = lambda bit: bool(ribi & bit)
    runs = []

    if ribi == 0:
        # pak128 draws the isolated tile as a full crossing closed by buffers.
        return [run((-0.5, 0.0), (0.5, 0.0), True, True),
                run((0.0, -0.5), (0.0, 0.5), True, True, lift=CROSSING_LIFT)]

    # A lone stub still spans the whole tile and closes its unused end with a
    # stop block, which is how pak128 draws its single-connection images.
    ns_only = has(layout.N) != has(layout.S) and not (has(layout.E) or has(layout.W))
    ew_only = has(layout.E) != has(layout.W) and not (has(layout.N) or has(layout.S))

    # Variant 1 hands the through route to the E/W axis; otherwise N/S runs
    # unbroken and E/W merges into it.
    ns_lift = 0.0 if spec.get("variant") == 1 else CROSSING_LIFT
    ew_lift = CROSSING_LIFT - ns_lift

    if has(layout.N) or has(layout.S):
        lo = -0.5 if (has(layout.S) or ns_only) else 0.0
        hi = 0.5 if (has(layout.N) or ns_only) else 0.0
        runs.append(run((0.0, lo), (0.0, hi),
                        ns_only and not has(layout.S),
                        ns_only and not has(layout.N), lift=ns_lift))
    if has(layout.E) or has(layout.W):
        lo = -0.5 if (has(layout.W) or ew_only) else 0.0
        hi = 0.5 if (has(layout.E) or ew_only) else 0.0
        runs.append(run((lo, 0.0), (hi, 0.0),
                        ew_only and not has(layout.W),
                        ew_only and not has(layout.E), lift=ew_lift))
    return runs


# --------------------------------------------------------------------------
# Cell construction
# --------------------------------------------------------------------------

def build_cell(spec, season, enclosure="none", part="back", tier=1000):
    """Populate the scene with one tile's geometry.

    With `enclosure="tube"` the cell is split: the back part carries the apron,
    the beam and the far half of the tube; the front part carries only the near
    half of the tube, drawn over vehicles so a pod shows through the glass.
    """
    pal = PALETTE[season]
    shape = layout.tile_shape(spec)

    if enclosure == "tube" and part == "front":
        build_tube(spec, season, near=True, tier=tier)
        return

    # The apron is panelled concrete like every other pak128 way; the girder
    # carries the same grid, which reads along a run as segment joints.
    apron_mat = iso.make_material("apron", pal["apron"], roughness=0.95,
                                  noise=0.30, seams=0.075, seam_period_m=4.0)
    girder_mat = iso.make_material("girder", pal["girder"], roughness=0.72,
                                   noise=0.12, seams=0.10, seam_period_m=4.0,
                                   seam_width_m=0.07)
    slot_mat = iso.make_material("slot", pal["slot"], roughness=0.45, metallic=0.55)
    lev_mat = iso.make_material("levitation", pal["levitation"], roughness=0.35,
                                metallic=0.35)
    girder_slots = [girder_mat, slot_mat, lev_mat]

    up = iso.ground_normal(shape)

    if enclosure == "tube":
        # An enclosed tube is a structure, not a paved way: it gets a plinth
        # under its footprint rather than an apron across the whole tile, so
        # the ground either side stays visible.
        build_plinth(spec, shape, up, apron_mat)
    else:
        corner = layout.apron_corner(spec)
        if corner:
            tri = {"ne": (iso.CORNER_TOP, iso.CORNER_RIGHT, iso.CORNER_BOTTOM),
                   "sw": (iso.CORNER_TOP, iso.CORNER_BOTTOM, iso.CORNER_LEFT),
                   "nw": (iso.CORNER_TOP, iso.CORNER_RIGHT, iso.CORNER_LEFT),
                   "se": (iso.CORNER_RIGHT, iso.CORNER_BOTTOM, iso.CORNER_LEFT)}[corner]
            iso.polygon("apron", shape, tri, apron_mat)
        else:
            iso.polygon("apron", shape,
                        [iso.CORNER_TOP, iso.CORNER_RIGHT,
                         iso.CORNER_BOTTOM, iso.CORNER_LEFT], apron_mat)
    profile = profile_world()

    edge_materials = {e: 1 for e in SLOT_EDGES}
    edge_materials.update({e: 2 for e in DECK_EDGES})

    for i, spec_run in enumerate(runs_for(spec)):
        lift = up * iso.m(spec_run["lift"])
        start = iso.ground_point(shape, *spec_run["start"]) + lift
        end = iso.ground_point(shape, *spec_run["end"]) + lift
        axis = end - start
        if axis.length < 1e-6:
            continue
        axis.normalize()
        right = axis.cross(up).normalized()
        over = iso.m(spec_run["overrun"])

        iso.extrude_profile(f"girder{i}", profile,
                            start - axis * over, end + axis * over,
                            right, up, girder_slots, edge_materials,
                            bevel=iso.m(0.06))

        for j, (capped, base, direction) in enumerate(
                ((spec_run["cap_start"], start, axis),
                 (spec_run["cap_end"], end, -axis))):
            if capped:
                build_stop_block(f"stop{i}_{j}", base, direction, right, up,
                                 girder_mat)

    if enclosure == "tube":
        build_tube(spec, season, near=False, tier=tier)


def build_plinth(spec, shape, up, material) -> None:
    """Foundation strip under an enclosed way, swept along each run."""
    section = [(iso.m(-PLINTH_HALF), 0.0),
               (iso.m(-PLINTH_HALF), iso.m(PLINTH_TOP)),
               (iso.m(PLINTH_HALF), iso.m(PLINTH_TOP)),
               (iso.m(PLINTH_HALF), 0.0)]
    for i, spec_run in enumerate(runs_for(spec)):
        start = iso.ground_point(shape, *spec_run["start"])
        end = iso.ground_point(shape, *spec_run["end"])
        axis = end - start
        if axis.length < 1e-6:
            continue
        axis.normalize()
        side = axis.cross(up).normalized()
        over = iso.m(spec_run["overrun"])
        iso.extrude_profile(f"plinth{i}", section,
                            start - axis * over, end + axis * over,
                            side, up, material, bevel=iso.m(0.05))


def build_tube(spec, season, near: bool, tier: int = 1000) -> None:
    """Sweep one half of the glass tube, with its structural hoops."""
    pal = PALETTE[season]
    cfg = TUBE_TIERS[tier]
    shape = layout.tile_shape(spec)
    up = iso.ground_normal(shape)

    winter = season == "winter"
    cove_mat = iso.make_flag_emission("cove")
    glass = iso.make_glass("glazing",
                           tuple(min(1.0, c + (0.10 if winter else 0.0))
                                 for c in cfg["tint"]),
                           face_alpha=cfg["face"], edge_alpha=cfg["edge"])
    frame = iso.make_material("frame",
                              tuple(min(1.0, c + (0.09 if winter else 0.0))
                                    for c in cfg["frame"]),
                              roughness=0.38, metallic=0.55, noise=0.05)

    spine = [(iso.m(-SPINE_HALF), iso.m(TUBE_HEIGHT - 0.02)),
             (iso.m(SPINE_HALF), iso.m(TUBE_HEIGHT - 0.02)),
             (iso.m(SPINE_HALF), iso.m(TUBE_HEIGHT + SPINE_DEPTH)),
             (iso.m(-SPINE_HALF), iso.m(TUBE_HEIGHT + SPINE_DEPTH))]

    # At a junction two tubes would otherwise clip edge to edge, which reads as
    # a modelling error rather than a junction. Shrinking the branch bore lets
    # it nest inside the through bore the way a real branch tunnel meets a main
    # one. The through route is the one the switch variant already raised.
    runs = runs_for(spec)
    through = max(runs, key=lambda r: r.get("lift", 0.0)) if len(runs) > 1 else None

    for i, spec_run in enumerate(runs):
        branch = through is not None and spec_run is not through
        bore = 0.90 if branch else 1.0
        wall = tube_profile(scale=bore)
        hoop = tube_profile(swell=RIB_PROUD, scale=bore)

        start = iso.ground_point(shape, *spec_run["start"])
        end = iso.ground_point(shape, *spec_run["end"])
        axis = end - start
        if axis.length < 1e-6:
            continue
        run_length = axis.length
        axis.normalize()

        # `right` points towards the camera: screen y grows with world X and
        # falls with world Y, so a horizontal direction leans towards the
        # viewer when x - y is positive.
        side = axis.cross(up).normalized()
        if (side.x - side.y) < 0.0:
            side = -side
        if not near:
            side = -side

        over = iso.m(spec_run["overrun"])
        shell = iso.extrude_profile(f"tube{i}", wall,
                                    start - axis * over, end + axis * over,
                                    side, up, glass, bevel=0.0, caps=False)
        iso.no_shadow(shell)

        w = TUBE_HALF_WIDTH
        cove = [(iso.m(w - COVE_PROUD), iso.m(COVE_LO)),
                (iso.m(w + COVE_PROUD), iso.m(COVE_LO)),
                (iso.m(w + COVE_PROUD), iso.m(COVE_HI)),
                (iso.m(w - COVE_PROUD), iso.m(COVE_HI))]
        strip = iso.extrude_profile(f"cove{i}", cove,
                                    start - axis * over, end + axis * over,
                                    side, up, cove_mat, bevel=0.0, caps=False)
        iso.no_shadow(strip)

        # Only the near pass carries the spine; drawing it in both would
        # double a line that sits exactly on the crown.
        if near and not branch:
            iso.extrude_profile(f"spine{i}", spine,
                                start - axis * over, end + axis * over,
                                side, up, frame, bevel=0.0, caps=False)

        for k, along in enumerate(rib_positions(start, axis, run_length,
                                                 cfg["rib_pitch"])):
            base = start + axis * along
            iso.extrude_profile(f"hoop{i}_{k}", hoop,
                                base - axis * iso.m(RIB_WIDTH / 2),
                                base + axis * iso.m(RIB_WIDTH / 2),
                                side, up, frame, bevel=0.0, caps=False)


def build_stop_block(name, base: Vector, direction: Vector, right: Vector,
                     up: Vector, material) -> None:
    """Solid block closing an unconnected girder end."""
    length = iso.m(STOP_BLOCK_LEN)
    half = iso.m(DECK_HALF + 0.25)
    top = iso.m(STOP_BLOCK_TOP)
    a = base
    b = base + direction * length
    verts = []
    for p in (a, b):
        for s in (-half, half):
            verts.append(p + right * s)
            verts.append(p + right * s + up * top)
    # verts order per end: (-half, 0), (-half, top), (+half, 0), (+half, top)
    faces = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4],
             [2, 6, 7, 3], [1, 3, 7, 5], [0, 4, 6, 2]]
    iso.new_mesh(name, verts, faces, material, bevel=iso.m(0.05))


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="directory for the cell PNGs")
    p.add_argument("--season", default="both", choices=["summer", "winter", "both"])
    p.add_argument("--cells", nargs="*", help="only these cells, e.g. 1.5 3.7")
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--supersample", type=int, default=4)
    p.add_argument("--enclosure", default="none", choices=["none", "tube"])
    p.add_argument("--tier", type=int, default=1000, choices=sorted(TUBE_TIERS))
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)

    wanted = None
    if args.cells:
        wanted = {tuple(int(n) for n in c.split(".")) for c in args.cells}
    seasons = ["summer", "winter"] if args.season == "both" else [args.season]

    cells = sorted(layout.CELL_PLAN)
    for season in seasons:
        for (row, col) in cells:
            if wanted and (row, col) not in wanted:
                continue
            spec = layout.CELL_PLAN[(row, col)]
            parts = ("back", "front") if args.enclosure == "tube" else ("back",)
            for part in parts:
                iso.setup(supersample=args.supersample, samples=args.samples,
                          shape=layout.tile_shape(spec))
                build_cell(spec, season, args.enclosure, part, args.tier)
                if args.enclosure == "tube":
                    out_row = layout.tube_row(row, part, season)
                else:
                    out_row = row + (layout.WINTER_ROW_OFFSET
                                     if season == "winter" else 0)
                iso.render_to(os.path.join(args.out, f"cell_{out_row}_{col}.png"))
                print(f"[maglev] rendered {season} {part} cell {out_row}.{col}")


if __name__ == "__main__":
    main()
