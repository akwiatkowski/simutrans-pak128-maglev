"""Build and render the maglev stop and depot in Blender.

    blender --background --python tools/blender/build_maglev_buildings.py -- \
        --object station --out build/station

Both objects share Simutrans' building layout: two orientations (layout 0 for a
N/S way, layout 1 for E/W) and, per orientation, a back image drawn before
vehicles and a front image drawn after. That split is what lets a train stand
between a station's two platforms, or sit inside a depot with the shed in
front of it.

Everything is modelled in track-local coordinates — `u` along the way, `v`
across it, `w` up — and then mapped onto world axes per layout, so each object
is described once rather than four times.

Sizes are metres against a 16m tile, the same scale the guideway uses.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import simutrans_iso as iso          # noqa: E402
import pak128_layout as layout       # noqa: E402

# --------------------------------------------------------------------------
# Station: two platforms flanking the guideway.
#
# The guideway deck is 3.2m wide, so the platform edge stands clear of it at
# 2.2m and the vehicle, which wraps the beam, still has room. The way keeps
# drawing the apron underneath, so nothing here paves the ground.
# --------------------------------------------------------------------------

PLATFORM_INNER = 2.2
PLATFORM_OUTER = 6.2
PLATFORM_TOP = 1.20
EDGE_STRIP = 0.55        # tactile safety strip along the platform edge
PARAPET_THICK = 0.18
PARAPET_TOP = 0.55       # above the platform deck; kept low so a
                         # stopped train is not walled in

# Profile of one platform, as (distance from centreline, height). Swept along
# the way exactly like the guideway's cross-section.
PLATFORM_PROFILE = [
    (PLATFORM_INNER, 0.0),                              # 0 -> 1 edge face
    (PLATFORM_INNER, PLATFORM_TOP),                     # 1 -> 2 safety strip
    (PLATFORM_INNER + EDGE_STRIP, PLATFORM_TOP),        # 2 -> 3 deck
    (PLATFORM_OUTER - PARAPET_THICK, PLATFORM_TOP),     # 3 -> 4 parapet inside
    (PLATFORM_OUTER - PARAPET_THICK, PLATFORM_TOP + PARAPET_TOP),
    (PLATFORM_OUTER, PLATFORM_TOP + PARAPET_TOP),       # 5 -> 6 outer face
    (PLATFORM_OUTER, 0.0),
]
PLATFORM_STRIP_EDGE = 1          # profile edge carrying the safety strip
PLATFORM_LENGTH = 8.05           # half length; a touch over half a tile so
                                 # neighbouring station tiles join up

## --------------------------------------------------------------------------
# Depot: a maintenance hangar filling the tile, open on the gable end facing
# the camera. pak128's own depot puts the doorway on a near-facing side so the
# interior is visible; this does the same.
#
# Deliberately *not* a pitched-roof shed with eaves — that silhouette reads as
# a barn, which is wrong for a maglev. A barrel vault over flush panel walls,
# with a glazed arch above the door, is the shape modern rail and aircraft
# maintenance halls actually use, and it is legible at 128px.
# --------------------------------------------------------------------------

HALL_HALF_LEN = 7.0      # along the way
HALL_HALF_WID = 6.6      # across it
WALL_TOP = 5.0           # top of the vertical cladding
RIDGE_TOP = 9.2          # crown of the vault
VAULT_SEGMENTS = 14
DOOR_HALF = 3.0
DOOR_TOP = 4.3
WALL_THICK = 0.35

PALETTE = {
    "summer": {
        "platform": (0.560, 0.560, 0.555),
        "strip": (0.640, 0.520, 0.170),      # amber tactile strip
        "wall": (0.615, 0.625, 0.640),
        "shell": (0.545, 0.565, 0.595),
        "glazing": (0.120, 0.155, 0.190),
        "interior": (0.070, 0.075, 0.085),
    },
    "winter": {
        "platform": (0.790, 0.800, 0.805),
        "strip": (0.620, 0.510, 0.180),
        "wall": (0.720, 0.730, 0.740),
        "shell": (0.760, 0.775, 0.790),       # snow on the vault
        "glazing": (0.130, 0.170, 0.210),
        "interior": (0.070, 0.075, 0.085),
    },
}


def frame(layout_index: int):
    """Track-local axes for a layout, as world vectors.

    `u` runs along the way with the doorway end at -u, `v` across it towards
    the camera. Layout 0 is a N/S way whose depot opens south; layout 1 is E/W
    and opens east. Both open towards the viewer, which is why the doorway
    always sits on the -u end here.
    """
    if layout_index == 0:
        return Vector((0, 1, 0)), Vector((1, 0, 0))     # along N, near side +X
    return Vector((-1, 0, 0)), Vector((0, -1, 0))       # along W, near side -Y


def local(u_axis, v_axis, u, v, w=0.0):
    return u_axis * iso.m(u) + v_axis * iso.m(v) + Vector((0, 0, iso.m(w)))


def box(name, u_axis, v_axis, u0, u1, v0, v1, w0, w1, material, bevel=0.0):
    """Axis-aligned box in track-local coordinates."""
    corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    verts = [local(u_axis, v_axis, u, v, w0) for u, v in corners]
    verts += [local(u_axis, v_axis, u, v, w1) for u, v in corners]
    faces = [[0, 3, 2, 1], [4, 5, 6, 7],
             [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return iso.new_mesh(name, verts, faces, material, bevel)


# --------------------------------------------------------------------------
# Station
# --------------------------------------------------------------------------

def build_station(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    concrete = iso.make_material("platform", pal["platform"], roughness=0.94,
                                 noise=0.28, seams=0.07, seam_period_m=4.0)
    strip = iso.make_material("strip", pal["strip"], roughness=0.85, noise=0.20)

    profile = [(iso.m(p), iso.m(h)) for p, h in PLATFORM_PROFILE]
    start = local(u_axis, v_axis, -PLATFORM_LENGTH, 0.0)
    end = local(u_axis, v_axis, PLATFORM_LENGTH, 0.0)
    up = Vector((0, 0, 1))

    # The near platform is the one on +v; the far one is the same profile
    # mirrored, which is just the opposite perpendicular.
    sides = [1.0] if part == "front" else [-1.0, 1.0]
    for side in sides:
        iso.extrude_profile(f"platform{side:+.0f}", profile, start, end,
                            v_axis * side, up, [concrete, strip],
                            {PLATFORM_STRIP_EDGE: 1}, bevel=iso.m(0.05))


# --------------------------------------------------------------------------
# Depot
# --------------------------------------------------------------------------

def vault_profile():
    """Cross-section of the hangar: flush walls closed by a half-ellipse vault.

    Returned as (across, height) in metres, left to right. The first and last
    edges are the vertical walls; everything between is the vault.
    """
    points = [(-HALL_HALF_WID, 0.0)]
    rise = RIDGE_TOP - WALL_TOP
    for i in range(VAULT_SEGMENTS + 1):
        t = math.pi * i / VAULT_SEGMENTS
        points.append((-HALL_HALF_WID * math.cos(t), WALL_TOP + rise * math.sin(t)))
    points.append((HALL_HALF_WID, 0.0))
    return points


def build_depot(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    wall = iso.make_material("wall", pal["wall"], roughness=0.55, noise=0.06,
                             seams=0.05, seam_period_m=1.6, seam_width_m=0.05)
    shell = iso.make_material("shell", pal["shell"], roughness=0.42,
                              metallic=0.25, noise=0.05,
                              seams=0.06, seam_period_m=1.6, seam_width_m=0.05)
    glazing = iso.make_material("glazing", pal["glazing"], roughness=0.12,
                                metallic=0.45)
    interior = iso.make_material("interior", pal["interior"], roughness=1.0)

    profile_m = vault_profile()
    profile = [(iso.m(v), iso.m(w)) for v, w in profile_m]
    nose = local(u_axis, v_axis, -HALL_HALF_LEN, 0.0)
    tail = local(u_axis, v_axis, HALL_HALF_LEN, 0.0)
    up = Vector((0, 0, 1))

    if part == "back":
        # Only what shows through the doorway. Shrinking the same profile gives
        # a dark inner skin that follows the vault, so the opening reads as
        # depth rather than as a flat black panel.
        inner = [(iso.m(v * 0.93), iso.m(w * 0.93)) for v, w in profile_m]
        iso.extrude_profile("interior_skin", inner, nose, tail, v_axis, up,
                            interior, caps=True)
        return

    # Shell: walls plus vault as one open-ended skin, so the ends can carry
    # their own geometry.
    edge_materials = {i: 1 for i in range(1, len(profile) - 2)}
    iso.extrude_profile("shell", profile, nose, tail, v_axis, up,
                        [wall, shell], edge_materials, bevel=iso.m(0.05),
                        caps=False)

    # Ribbon glazing along both flanks, flush with the cladding.
    for side in (-1.0, 1.0):
        box(f"ribbon{side:+.0f}", u_axis, v_axis,
            -HALL_HALF_LEN + 1.4, HALL_HALF_LEN - 1.4,
            side * HALL_HALF_WID, side * (HALL_HALF_WID + 0.05),
            WALL_TOP - 2.1, WALL_TOP - 0.7, glazing)

    # Rear end: closed by the full profile.
    iso.new_mesh("rear", [local(u_axis, v_axis, HALL_HALF_LEN, v, w)
                          for v, w in profile_m],
                 [list(range(len(profile_m)))], shell)

    # Front end: cladding either side of the doorway, a lintel above it, and
    # the vault arch glazed. Built as separate polygons rather than a boolean.
    for side in (-1.0, 1.0):
        quad = [(side * DOOR_HALF, 0.0), (side * HALL_HALF_WID, 0.0),
                (side * HALL_HALF_WID, WALL_TOP), (side * DOOR_HALF, WALL_TOP)]
        iso.new_mesh(f"front{side:+.0f}",
                     [local(u_axis, v_axis, -HALL_HALF_LEN, v, w) for v, w in quad],
                     [[0, 1, 2, 3]], wall)
    lintel = [(-DOOR_HALF, DOOR_TOP), (DOOR_HALF, DOOR_TOP),
              (DOOR_HALF, WALL_TOP), (-DOOR_HALF, WALL_TOP)]
    iso.new_mesh("lintel",
                 [local(u_axis, v_axis, -HALL_HALF_LEN, v, w) for v, w in lintel],
                 [[0, 1, 2, 3]], wall)

    arch = profile_m[1:-1]          # the vault span, wall top to wall top
    iso.new_mesh("arch_glazing",
                 [local(u_axis, v_axis, -HALL_HALF_LEN + 0.05, v, w) for v, w in arch],
                 [list(range(len(arch)))], glazing)


BUILDERS = {"station": build_station, "depot": build_depot}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--object", required=True, choices=sorted(BUILDERS))
    p.add_argument("--out", required=True)
    p.add_argument("--season", default="summer", choices=["summer", "winter"])
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--supersample", type=int, default=4)
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    builder = BUILDERS[args.object]
    pal = PALETTE[args.season]

    for (row, col), spec in sorted(layout.STATION_PLAN.items()):
        iso.setup(supersample=args.supersample, samples=args.samples)
        builder(spec["layout"], spec["part"], pal)
        iso.render_to(os.path.join(args.out, f"cell_{row}_{col}.png"))
        print(f"[maglev] rendered {args.object} {spec['part']} "
              f"layout {spec['layout']} -> {row}.{col}")


if __name__ == "__main__":
    main()
