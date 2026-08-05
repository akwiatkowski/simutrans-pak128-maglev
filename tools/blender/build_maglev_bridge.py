"""Build and render the maglev bridges in Blender.

Three bridge classes, mirroring the crossing ladder Olek picked (500 / 1000
/ 4000): the 500 is the open precast viaduct — the 500 tier's girder riding
a haunched spine one level up — and the 1000 / 4000 are the glazed tubes
carried across on the same spine, split back/front down the crown exactly
like the tube way, so a pod crossing a valley is still seen through the
glass.

Cell plan per class (packed by `tools/assemble_sheet.py --sheet bridge`):

    row 0  header, icon (col 6), cursor (col 7)
    row 1  span:  back NS, front NS, back EW, front EW, pillar S, pillar W
    row 2  ramps: back/front x N,S,E,W
    row 3  starts: back/front x N,S,E,W
    rows 4-6 the same in winter

Bridge sprites live in way-tile coordinates with the riding surface one
height level (+16px) above the tile's ground, and the dat uses zero image
offsets — the content is simply drawn where it belongs. The ramp climbs
from the tile's low edge to the high edge over the foundation band; a start
is a span with an abutment head under its landward end.

    blender --background --python tools/blender/build_maglev_bridge.py -- \
        --out build/bridge500 --class 500 --samples 96
"""

from __future__ import annotations

import argparse
import os
import sys

import bpy  # noqa: F401
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import simutrans_iso as iso              # noqa: E402
import build_maglev_track as track       # noqa: E402

UP = Vector((0.0, 0.0, 1.0))

# Directions in world axes (+Y = N, +X = E) and their sheet columns.
DIR = {"n": Vector((0.0, 1.0, 0.0)), "s": Vector((0.0, -1.0, 0.0)),
       "e": Vector((1.0, 0.0, 0.0)), "w": Vector((-1.0, 0.0, 0.0))}

LIFT = iso.HEIGHT_STEP        # bridge deck rides one height level up

# The spine: a shallow box girder under the guideway, the structure that
# actually spans. Narrower than the deck so the crossing reads as a beam
# on a beam, plus a haunch where it meets a pillar.
SPINE_HALF = 0.95
SPINE_DEPTH = 0.75            # metres of structure below the guideway base

PILLAR_HALF = 0.55            # tapered column, across the run
PILLAR_THICK = 0.42

ABUTMENT_HALF = 2.1           # concrete head under a start's landward end
ABUTMENT_LEN = 2.4

CLASSES = {
    500: dict(tier=500, enclosure=None),
    1000: dict(tier=1000, enclosure=1000),
    4000: dict(tier=4000, enclosure=4000),
}


def girder_materials(tier: int, season: str):
    """The span reuses the way's own materials so a bridge continues its
    line seamlessly; the flexing-steel and band logic do not apply here."""
    pal = track.PALETTE[season]
    cfg = track.TRACK_TIERS.get(tier, track.TUBE_BEAM)
    winter = season == "winter"
    if cfg["girder"] is None:
        girder_color = pal["girder"]
    elif winter and not cfg["heated_deck"]:
        girder_color = pal["girder"]
    elif winter:
        girder_color = (0.052, 0.058, 0.066)
    else:
        girder_color = cfg["girder"]
    deck_pal = track.PALETTE["summer"] if (winter and cfg["heated_deck"]) else pal
    girder_mat = iso.make_material("girder", girder_color, roughness=0.72,
                                   noise=0.12, seams=cfg["girder_seams"],
                                   seam_period_m=cfg["seam_period"],
                                   seam_width_m=cfg["seam_width"])
    slot_mat = iso.make_material("slot", cfg["slot"] or deck_pal["slot"],
                                 roughness=0.45, metallic=0.55)
    lev_mat = iso.make_material("levitation", deck_pal["levitation"],
                                roughness=0.35, metallic=0.35)
    return [girder_mat, slot_mat, lev_mat], cfg


def concrete(season: str):
    pal = track.PALETTE[season]
    return iso.make_material("structure", tuple(c * 0.92 for c in pal["apron"]),
                             roughness=0.85, noise=0.20,
                             seams=0.12, seam_period_m=4.0)


def sweep_girder(start, end, axis, tier, season, lift0, lift1):
    """The guideway girder between two points, each with its own lift."""
    axis_n = (end - start).normalized()
    right = axis_n.cross(UP).normalized()
    mats, cfg = girder_materials(tier, season)
    profile = track.profile_world(False)
    edge_materials = {e: 1 for e in track.SLOT_EDGES}
    edge_materials.update({e: 2 for e in track.DECK_EDGES})
    a = start + UP * lift0
    b = end + UP * lift1
    iso.extrude_profile("girder", profile, a, b, right, UP,
                        mats, edge_materials, bevel=iso.m(0.06))
    return a, b, right


def sweep_duct(a, b, right):
    """The 500's orange cable tray continues across its viaduct — a bridge
    is the same line, not a different object."""
    duct_mat = iso.make_material("duct", (0.760, 0.235, 0.045),
                                 roughness=0.55, metallic=0.0)
    bsdf = duct_mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Emission Color"].default_value = (0.760, 0.235, 0.045, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 0.28
    for s in (-1.0, 1.0):
        x_in = s * (track.GIRDER_HALF - 0.02)
        x_out = s * (track.GIRDER_HALF + track.CONDUIT_PROUD)
        duct = [(iso.m(x_in), iso.m(track.CONDUIT_LO)),
                (iso.m(x_out), iso.m(track.CONDUIT_LO)),
                (iso.m(x_out), iso.m(track.CONDUIT_HI)),
                (iso.m(x_in), iso.m(track.CONDUIT_HI))]
        iso.extrude_profile(f"duct{s:+.0f}", duct, a, b, right, UP,
                            duct_mat, bevel=0.0, caps=False)


def sweep_spine(a, b, right, season, depth=SPINE_DEPTH):
    spine = [(iso.m(-SPINE_HALF), iso.m(-depth)),
             (iso.m(-SPINE_HALF), 0.0),
             (iso.m(SPINE_HALF), 0.0),
             (iso.m(SPINE_HALF), iso.m(-depth))]
    iso.extrude_profile("spine", spine, a, b, right, UP,
                        concrete(season), bevel=iso.m(0.05))


def tube_shell(start, end, axis, tier, season, near: bool, lift):
    """Far or near half of the glazed tube, lifted to bridge level.

    Mirrors build_maglev_track.build_tube: same profile, hoops and light
    cove, so a tube crossing is indistinguishable from the way it extends.
    """
    cfg = track.TUBE_TIERS[tier]
    winter = season == "winter"
    glass = iso.make_glass("glazing",
                           tuple(min(1.0, c + (0.10 if winter else 0.0))
                                 for c in cfg["tint"]),
                           face_alpha=cfg["face"], edge_alpha=cfg["edge"])
    frame = iso.make_material("frame",
                              tuple(min(1.0, c + (0.09 if winter else 0.0))
                                    for c in cfg["frame"]),
                              roughness=0.38, metallic=0.55, noise=0.05)
    cove = iso.make_flag_emission("cove")

    axis_n = (end - start).normalized()
    side = axis_n.cross(UP).normalized()
    if (side.x - side.y) < 0.0:
        side = -side
    if not near:
        side = -side

    a = start + UP * lift
    b = end + UP * lift
    wall = track.tube_profile()
    shell = iso.extrude_profile("tube", wall, a, b, side, UP, glass,
                                bevel=0.0, caps=False)
    iso.no_shadow(shell)
    hoop = track.tube_profile(swell=track.RIB_PROUD)
    for k, along in enumerate(track.rib_positions(a, axis_n, (b - a).length,
                                                  cfg["rib_pitch"])):
        base = a + axis_n * along
        iso.extrude_profile(f"hoop{k}", hoop,
                            base - axis_n * iso.m(track.RIB_WIDTH / 2),
                            base + axis_n * iso.m(track.RIB_WIDTH / 2),
                            side, UP, frame, bevel=0.0, caps=False)
    # Light cove along the springing, swapped to the reserved light when
    # packed — a tube crossing glows at night like the rest of the line.
    w = track.TUBE_HALF_WIDTH
    strip = [(iso.m(w - track.COVE_PROUD), iso.m(track.COVE_LO)),
             (iso.m(w + track.COVE_PROUD), iso.m(track.COVE_LO)),
             (iso.m(w + track.COVE_PROUD), iso.m(track.COVE_HI)),
             (iso.m(w - track.COVE_PROUD), iso.m(track.COVE_HI))]
    lit = iso.extrude_profile("cove", strip, a, b, side, UP, cove,
                              bevel=0.0, caps=False)
    iso.no_shadow(lit)


def edge_points(direction: str):
    """Centre of the tile edge the run leaves through, and its opposite."""
    d = DIR[direction]
    far = Vector((d.x * 0.5, d.y * 0.5, 0.0))
    return -far, far


def build_span(cls, season, direction, part):
    """One full-tile span at bridge level. `part` back/front only matters
    for the glazed classes; the open 500 puts everything in back."""
    tier, enclosure = cls["tier"], cls["enclosure"]
    a3, b3 = edge_points(direction)
    over = (DIR[direction]) * iso.m(track.OVERRUN_STRAIGHT)
    a3, b3 = a3 - over, b3 + over
    if part == "back":
        a, b, right = sweep_girder(a3, b3, DIR[direction], tier, season,
                                   LIFT, LIFT)
        sweep_spine(a, b, right, season)
        if tier == 500:
            sweep_duct(a, b, right)
        if enclosure:
            tube_shell(a3, b3, DIR[direction], enclosure, season,
                       near=False, lift=LIFT)
    elif enclosure:
        tube_shell(a3, b3, DIR[direction], enclosure, season,
                   near=True, lift=LIFT)


def build_ramp(cls, season, direction, part):
    """Climbing tile: low at the -d edge, bridge level at the +d edge,
    the foundation band still on the ground beneath."""
    if part == "front":
        if cls["enclosure"]:
            a3, b3 = edge_points(direction)
            # The tube on a ramp is left open — a climbing glazed shell
            # needs a lofted, tilted profile; the open climb reads as the
            # airlock apron every enclosed system needs anyway.
        return
    tier = cls["tier"]
    a3, b3 = edge_points(direction)
    band = [(iso.m(-track.BAND_HALF), 0.0),
            (iso.m(-track.BAND_HALF), iso.m(track.BAND_TOP)),
            (iso.m(track.BAND_HALF), iso.m(track.BAND_TOP)),
            (iso.m(track.BAND_HALF), 0.0)]
    axis_n = DIR[direction]
    right = axis_n.cross(UP).normalized()
    iso.extrude_profile("band", band, a3, b3, right, UP,
                        concrete(season), bevel=0.0)
    a, b, right = sweep_girder(a3, b3, axis_n, tier, season, 0.0, LIFT)
    if tier == 500:
        sweep_duct(a, b, right)
    # Abutment wedge filling under the climbing beam.
    verts = [a3 + right * iso.m(-SPINE_HALF), a3 + right * iso.m(SPINE_HALF),
             b3 + right * iso.m(SPINE_HALF), b3 + right * iso.m(-SPINE_HALF),
             b3 + right * iso.m(SPINE_HALF) + UP * LIFT,
             b3 + right * iso.m(-SPINE_HALF) + UP * LIFT]
    faces = [[0, 1, 2, 3], [3, 2, 4, 5], [0, 3, 5], [1, 2, 4],
             [0, 1, 4, 5]]
    iso.new_mesh("wedge", verts, faces, concrete(season))


def build_start(cls, season, direction, part):
    """A span with the abutment head under its landward (-d) end."""
    build_span(cls, season, "n" if direction in ("n", "s") else "e", part)
    if part != "back":
        return
    d = DIR[direction]
    land = Vector((-d.x * 0.5, -d.y * 0.5, 0.0))
    right = d.cross(UP).normalized()
    a = land
    b = land + d * iso.m(ABUTMENT_LEN)
    head = [(iso.m(-ABUTMENT_HALF), 0.0),
            (iso.m(-ABUTMENT_HALF), LIFT),
            (iso.m(ABUTMENT_HALF), LIFT),
            (iso.m(ABUTMENT_HALF), 0.0)]
    iso.extrude_profile("abutment", head, a, b, right, UP,
                        concrete(season), bevel=iso.m(0.04))


def build_pillar(cls, season, direction):
    """One column filling one height level, repeated downward by the game."""
    d = DIR["s"] if direction == "s" else DIR["w"]
    right = d.cross(UP).normalized()
    taper = 0.82
    verts = []
    for h, k in ((0.0, 1.0), (LIFT, taper)):
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(Vector((0, 0, h))
                         + right * iso.m(su * PILLAR_HALF * (k if h else 1))
                         + d * iso.m(sv * PILLAR_THICK * (k if h else 1)))
    faces = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1],
             [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]
    iso.new_mesh("pillar", verts, faces, concrete(season))


# Cell plan: (row, col) -> builder invocation.
def plan():
    cells = {}
    for season_off, season in ((0, "summer"), (3, "winter")):
        cells[(1 + season_off, 0)] = ("span", "n", "back", season)
        cells[(1 + season_off, 1)] = ("span", "n", "front", season)
        cells[(1 + season_off, 2)] = ("span", "e", "back", season)
        cells[(1 + season_off, 3)] = ("span", "e", "front", season)
        cells[(1 + season_off, 4)] = ("pillar", "s", "back", season)
        cells[(1 + season_off, 5)] = ("pillar", "w", "back", season)
        for i, d in enumerate("nsew"):
            cells[(2 + season_off, 2 * i)] = ("ramp", d, "back", season)
            cells[(2 + season_off, 2 * i + 1)] = ("ramp", d, "front", season)
            cells[(3 + season_off, 2 * i)] = ("start", d, "back", season)
            cells[(3 + season_off, 2 * i + 1)] = ("start", d, "front", season)
    return cells


BUILDERS = {"span": build_span, "ramp": build_ramp, "start": build_start}


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--class", dest="cls", type=int, required=True,
                   choices=sorted(CLASSES))
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--supersample", type=int, default=4)
    p.add_argument("--cells", nargs="*", help="only these cells, e.g. 1.0")
    args = p.parse_args(argv)

    cls = CLASSES[args.cls]
    os.makedirs(args.out, exist_ok=True)
    for (row, col), (kind, direction, part, season) in sorted(plan().items()):
        if args.cells and f"{row}.{col}" not in args.cells:
            continue
        iso.setup(args.supersample, args.samples, "flat")
        if kind == "pillar":
            build_pillar(cls, season, direction)
        else:
            BUILDERS[kind](cls, season, direction, part)
        iso.render_to(os.path.join(args.out, f"cell_{row}_{col}.png"))
        print(f"[maglev] rendered bridge{args.cls} {kind} {direction} "
              f"{part} {season} -> {row}.{col}", flush=True)


if __name__ == "__main__":
    main()
