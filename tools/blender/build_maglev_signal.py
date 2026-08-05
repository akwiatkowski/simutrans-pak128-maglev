"""Build and render the maglev signals in Blender.

Two signal types, each rendered in four travel directions and two aspects:

    row 1  block signal   — single head on a slim mast
    row 2  choose signal  — twin heads, the classic route-indicator silhouette

Sheet columns follow pak128's signal convention (state 0 = red/closed in
columns 0-3 as n,e,s,w; state 1 = green/clear in columns 4-7), verified
against `p128_sign_rail_signals_classic_modern.png`. `tools/assemble_sheet.py
--sheet signal` packs the cells and stamps the lamp pixels to Simutrans'
reserved light colours (#FF211D red, #01DD01 green), so a signal aspect stays
lit when the map dims — the same mechanism as the tube's light cove.

    blender --background --python tools/blender/build_maglev_signal.py -- \
        --out build/signal --samples 96

The mast is the 300 tier's galvanised service-mast steel — signals are
trackside hardware, so they wear the hardware palette, not the guideway's.
A small round repeater lamp sits on the *back* of each head: the iso camera
sees the back of two of the four rotations, and without a repeater those
directions would hide the aspect entirely.
"""

from __future__ import annotations

import argparse
import os
import sys

import bpy  # noqa: F401  (imported for side effect: running inside Blender)
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import simutrans_iso as iso          # noqa: E402

# --------------------------------------------------------------------------
# Geometry, in metres. The guideway deck half is 1.6m; the mast stands on
# the apron beside it, right-hand side of the travel direction.
# --------------------------------------------------------------------------

OFFSET = 2.35            # mast centre from the guideway centreline
FOOT_HALF = 0.26         # concrete foot
FOOT_TOP = 0.30
MAST_HALF = 0.09         # slim square steel mast
MAST_TOP = 3.35
HEAD_W = 0.55            # lamp head: width across, height, thickness
HEAD_H = 1.05
HEAD_T = 0.20
HEAD_BASE = 2.25         # bottom of the head above the apron
LAMP = 0.32              # square aspect lamps on the face
LAMP_PROUD = 0.10        # lamps stand proud so their lit sides catch the
                         # iso camera — a flush lamp face is foreshortened
                         # to a couple of pixels and the aspect vanishes
REPEATER = 0.18          # repeater lamp on the back
TWIN_GAP = 0.16          # gap between the choose signal's twin heads

DIRS = {"n": Vector((0.0, 1.0, 0.0)), "e": Vector((1.0, 0.0, 0.0)),
        "s": Vector((0.0, -1.0, 0.0)), "w": Vector((-1.0, 0.0, 0.0))}
COL = {"n": 0, "e": 1, "s": 2, "w": 3}
UP = Vector((0.0, 0.0, 1.0))


def box(name, centre, axis_u, axis_v, axis_w, hu, hv, hw, material):
    """Axis-aligned-to-the-signal box: half extents along three unit axes."""
    verts = []
    for su in (-1, 1):
        for sv in (-1, 1):
            for sw in (-1, 1):
                verts.append(centre + axis_u * (su * hu)
                             + axis_v * (sv * hv) + axis_w * (sw * hw))
    faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1],
             [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return iso.new_mesh(name, verts, faces, material)


def build_signal(direction: str, aspect: int, choose: bool) -> None:
    axis = DIRS[direction]
    right = axis.cross(UP).normalized()          # right-hand side of travel
    face = -axis                                 # towards the approaching pod

    mast_mat = iso.make_material("mast", (0.085, 0.092, 0.100),
                                 roughness=0.50, metallic=0.60)
    foot_mat = iso.make_material("foot", (0.42, 0.42, 0.42),
                                 roughness=0.95, noise=0.30)
    case_mat = iso.make_material("case", (0.030, 0.032, 0.036),
                                 roughness=0.45, metallic=0.30)
    dark_mat = iso.make_material("dark_lamp", (0.015, 0.016, 0.018),
                                 roughness=0.25, metallic=0.0)
    lit_mat = iso.make_flag_emission(
        "lit_lamp", (0.0, 1.0, 0.0) if aspect else (1.0, 0.0, 0.0))

    base = right * iso.m(OFFSET)

    box("foot", base + UP * iso.m(FOOT_TOP / 2), right, axis, UP,
        iso.m(FOOT_HALF), iso.m(FOOT_HALF), iso.m(FOOT_TOP / 2), foot_mat)
    box("mast", base + UP * iso.m((FOOT_TOP + MAST_TOP) / 2), right, axis, UP,
        iso.m(MAST_HALF), iso.m(MAST_HALF),
        iso.m((MAST_TOP - FOOT_TOP) / 2), mast_mat)

    heads = [0.0] if not choose else [-(HEAD_W + TWIN_GAP) / 2,
                                      +(HEAD_W + TWIN_GAP) / 2]
    for i, shift in enumerate(heads):
        centre = (base + right * iso.m(shift)
                  + UP * iso.m(HEAD_BASE + HEAD_H / 2))
        box(f"head{i}", centre, right, axis, UP,
            iso.m(HEAD_W / 2), iso.m(HEAD_T / 2), iso.m(HEAD_H / 2), case_mat)

        # Two aspect lamps on the face: red above, green below, only the
        # current aspect lit. The lamps sit proud of the casing so the
        # emission survives the downsample.
        for lamp_i, (dz, lit) in enumerate([(+HEAD_H / 4, aspect == 0),
                                            (-HEAD_H / 4, aspect == 1)]):
            lamp_c = (centre + UP * iso.m(dz)
                      + face * iso.m(HEAD_T / 2 + LAMP_PROUD / 2))
            lamp = box(f"lamp{i}_{lamp_i}", lamp_c, right, axis, UP,
                       iso.m(LAMP / 2), iso.m(LAMP_PROUD / 2),
                       iso.m(LAMP / 2),
                       lit_mat if lit else dark_mat)
            if lit:
                iso.no_shadow(lamp)

        # Back repeater: the aspect, readable from behind.
        rep_c = (centre - face * iso.m(HEAD_T / 2 + LAMP_PROUD / 2))
        rep = box(f"rep{i}", rep_c, right, axis, UP,
                  iso.m(REPEATER / 2), iso.m(LAMP_PROUD / 2),
                  iso.m(REPEATER / 2), lit_mat)
        iso.no_shadow(rep)


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--supersample", type=int, default=4)
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    for row, choose in ((1, False), (2, True)):
        for aspect in (0, 1):
            for direction, col in COL.items():
                iso.setup(args.supersample, args.samples, "flat")
                build_signal(direction, aspect, choose)
                cell = os.path.join(args.out,
                                    f"cell_{row}_{4 * aspect + col}.png")
                iso.render_to(cell)
                print(f"[maglev] rendered signal cell {row}."
                      f"{4 * aspect + col}", flush=True)


if __name__ == "__main__":
    main()
