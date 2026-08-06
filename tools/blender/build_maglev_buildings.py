"""Build and render the maglev stop, depot and concourse in Blender.

    blender --background --python tools/blender/build_maglev_buildings.py -- \
        --object station --out build/station

All objects share Simutrans' building layout: two orientations (layout 0 for a
N/S way, layout 1 for E/W) and, per orientation, a back image drawn before
vehicles and a front image drawn after. That split is what lets a train stand
between a station's two platforms, sit inside a depot with the shed in front
of it, or show through the near half of a glazed canopy.

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
# The shell is a *superellipse* vault, not a half-ellipse: a flattened crown
# with drawn-in shoulders is the same engineered-fairing family as the vacuum
# tube, so the depot reads as maglev infrastructure rather than a barn or a
# polytunnel. Its character follows the set's law — escalation is density of
# engineering — through details sized to survive 128px: proud steel rib hoops
# on a strict rhythm, a crown spine carrying the overhead crane rail out over
# the doorway, skylight strips, segmented flank glazing between pilasters,
# roof vents, a comms mast, the 500's safety-orange conduit arriving home
# along the plinth, and a door portal outlined in the marker colour that the
# packer swaps for the reserved never-dim light.
# --------------------------------------------------------------------------

HALL_HALF_LEN = 7.0      # along the way
HALL_HALF_WID = 6.6      # across it
WALL_TOP = 4.6           # top of the vertical cladding
RIDGE_TOP = 9.0          # crown of the vault
VAULT_EXP = 2.6          # same superellipse exponent as the tube
VAULT_SEGMENTS = 16
DOOR_HALF = 3.0
DOOR_TOP = 4.2

RIB_US = (-5.6, -2.8, 0.0, 2.8, 5.6)   # hoop centrelines along the hall
RIB_WIDTH = 0.45         # along the way; ~2px, a clear band not a wire
RIB_PROUD = 0.32         # how far a hoop stands off the shell
PILASTER_PROUD = 0.18    # the hoop's continuation down the wall

SPINE_HALF = 0.55        # crane-rail housing along the crown
SPINE_DEPTH = 0.50
SPINE_NOSE = 0.9         # housing overhangs the door, so the crane can pick
                         # up a bogie from the apron — the working detail
                         # that says "maintenance", not "warehouse"

SKYLIGHT_BANDS = ((0.53, 0.61), (0.39, 0.47))   # vault params, near and far
WINDOW_LO, WINDOW_HI = 2.4, 3.9                 # flank glazing band heights

VENT_US = (1.4, 3.4, 5.4)    # extraction pods, rear half of the far slope
VENT_V = -2.3
VENT_HALF = 0.75
VENT_TOP = 0.62

MAST_U, MAST_V = 6.3, -5.6   # comms mast on the rear far shoulder
MAST_TOP = 11.0
MAST_HALF = 0.11

CONDUIT_LO, CONDUIT_HI = 0.55, 0.95   # orange service tray on the plinth,
CONDUIT_PROUD = 0.16                  # the 500 guideway's tray arriving home

PORTAL_PROUD = 0.25      # door frame standing off the front face
PORTAL_THICK = 0.55
LIT_STRIP = 0.30         # marker-lit door outline; ~1px of light after
                         # packing, swapped for the reserved #7F9BF1

PALETTE = {
    "summer": {
        "platform": (0.560, 0.560, 0.555),
        "strip": (0.640, 0.520, 0.170),      # amber tactile strip
        "wall": (0.615, 0.625, 0.640),
        "shell": (0.655, 0.695, 0.735),      # pale engineered composite (700)
        "frame": (0.420, 0.450, 0.500),      # structural steel
        "glazing": (0.120, 0.155, 0.190),
        "interior": (0.070, 0.075, 0.085),
        "canopy_tint": (0.50, 0.70, 0.76),   # fusion-era teal glass
        "canopy_frame": (0.400, 0.430, 0.480),
    },
    "winter": {
        "platform": (0.790, 0.800, 0.805),
        "strip": (0.620, 0.510, 0.180),
        "wall": (0.720, 0.730, 0.740),
        "shell": (0.760, 0.775, 0.790),       # snow on the vault
        "frame": (0.550, 0.580, 0.630),
        "glazing": (0.130, 0.170, 0.210),
        "interior": (0.070, 0.075, 0.085),
        "canopy_tint": (0.60, 0.80, 0.86),
        "canopy_frame": (0.490, 0.520, 0.570),
    },
}

# Safety-orange, same paint as the 500's cable tray; carries a whisper of
# self-emission so the shaded flank cannot turn the paint to mud.
DUCT_ORANGE = (0.760, 0.235, 0.045)


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


def make_duct_material():
    duct = iso.make_material("duct", DUCT_ORANGE, roughness=0.55)
    bsdf = duct.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Emission Color"].default_value = (*DUCT_ORANGE, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 0.28
    return duct


# --------------------------------------------------------------------------
# Station
# --------------------------------------------------------------------------

def build_platforms(u_axis, v_axis, part: str, pal) -> None:
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


def build_station(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    build_platforms(u_axis, v_axis, part, pal)


# --------------------------------------------------------------------------
# Depot
# --------------------------------------------------------------------------

def vault_point(t: float):
    """Point on the vault at parameter t: 0 = left springing, 1 = right.

    (v, w) in metres. The arc is a superellipse sitting on the wall top.
    """
    ang = math.pi * (t - 0.5)
    s = math.sin(ang)
    v = HALL_HALF_WID * math.copysign(abs(s) ** (2.0 / VAULT_EXP), s)
    w = WALL_TOP + (RIDGE_TOP - WALL_TOP) * math.cos(ang) ** (2.0 / VAULT_EXP)
    return v, w


def vault_normal(t: float):
    """Outward unit normal of the vault at parameter t, via the tangent."""
    d = 1e-3
    (v0, w0) = vault_point(max(0.0, t - d))
    (v1, w1) = vault_point(min(1.0, t + d))
    length = math.hypot(v1 - v0, w1 - w0)
    return -(w1 - w0) / length, (v1 - v0) / length


def vault_ribbon(t0: float, t1: float, lift_inner: float, lift_outer: float,
                 steps: int = 12):
    """Closed crescent hugging the vault between params t0..t1, in metres.

    Details that follow the shell — rib hoops, skylight strips — are offset
    along the true surface normal; offsetting along w alone would leave them
    flush at the shoulders where the surface turns vertical.
    """
    ts = [t0 + (t1 - t0) * i / steps for i in range(steps + 1)]
    outer, inner = [], []
    for t in ts:
        v, w = vault_point(t)
        nv, nw = vault_normal(t)
        outer.append((v + nv * lift_outer, w + nw * lift_outer))
        inner.append((v + nv * lift_inner, w + nw * lift_inner))
    return outer + list(reversed(inner))


def vault_profile():
    """Cross-section of the hall: flush walls closed by the superellipse."""
    points = [(-HALL_HALF_WID, 0.0)]
    points += [vault_point(i / VAULT_SEGMENTS) for i in range(VAULT_SEGMENTS + 1)]
    points.append((HALL_HALF_WID, 0.0))
    return points


def vault_w(v: float) -> float:
    """Shell height above a given offset from the centreline."""
    rise = RIDGE_TOP - WALL_TOP
    return WALL_TOP + rise * (1.0 - (abs(v) / HALL_HALF_WID) ** VAULT_EXP) \
        ** (1.0 / VAULT_EXP)


def sweep(name, profile_m, u_axis, v_axis, u0, u1, material,
          edge_materials=None, bevel=0.0, caps=True):
    """Extrude a (v, w) metre profile along the hall axis from u0 to u1."""
    profile = [(iso.m(v), iso.m(w)) for v, w in profile_m]
    return iso.extrude_profile(name, profile,
                               local(u_axis, v_axis, u0, 0.0),
                               local(u_axis, v_axis, u1, 0.0),
                               v_axis, Vector((0, 0, 1)), material,
                               edge_materials, bevel=bevel, caps=caps)


def build_depot(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    wall = iso.make_material("wall", pal["wall"], roughness=0.55, noise=0.06,
                             seams=0.05, seam_period_m=1.6, seam_width_m=0.05)
    shell = iso.make_material("shell", pal["shell"], roughness=0.42,
                              metallic=0.25, noise=0.05,
                              seams=0.06, seam_period_m=1.6, seam_width_m=0.05)
    steel = iso.make_material("steel", pal["frame"], roughness=0.38,
                              metallic=0.55, noise=0.05)
    glazing = iso.make_material("glazing", pal["glazing"], roughness=0.12,
                                metallic=0.45)
    interior = iso.make_material("interior", pal["interior"], roughness=1.0)
    lit = iso.make_flag_emission("lit")

    profile_m = vault_profile()

    if part == "back":
        # Only what shows through the doorway. Shrinking the same profile gives
        # a dark inner skin that follows the vault. Open at the door end —
        # a capped end puts a flat dark panel right at the door plane, which
        # both kills the depth and hides the pit lights behind it.
        inner = [(v * 0.93, w * 0.93) for v, w in profile_m]
        sweep("interior_skin", inner, u_axis, v_axis,
              -HALL_HALF_LEN, HALL_HALF_LEN, interior, caps=False)
        iso.new_mesh("interior_rear",
                     [local(u_axis, v_axis, HALL_HALF_LEN, v, w)
                      for v, w in inner],
                     [list(range(len(inner)))], interior)
        # Service-pit edge lights either side of the beam: two raised bars in
        # the marker colour, so the hall glows faintly through the open door
        # after dark — a depot that is never quite asleep.
        for side in (-1.0, 1.0):
            bar = box(f"pit{side:+.0f}", u_axis, v_axis,
                      -HALL_HALF_LEN + 0.2, HALL_HALF_LEN - 1.0,
                      side * 0.85, side * 1.15, 0.0, 0.30, lit)
            iso.no_shadow(bar)
        return

    # Shell: walls plus vault as one open-ended skin, so the ends can carry
    # their own geometry.
    edge_materials = {i: 1 for i in range(1, len(profile_m) - 2)}
    sweep("shell", profile_m, u_axis, v_axis, -HALL_HALF_LEN, HALL_HALF_LEN,
          [wall, shell], edge_materials, bevel=iso.m(0.05), caps=False)

    # Skylight strips flanking the crown spine, running the length of the
    # hall. The rib hoops cross proud over them, chopping the glass into a
    # bar rhythm — the roof detail that reads at 128px.
    for i, (t0, t1) in enumerate(SKYLIGHT_BANDS):
        sweep(f"skylight{i}", vault_ribbon(t0, t1, -0.06, 0.05, steps=6),
              u_axis, v_axis, -HALL_HALF_LEN + 0.6, HALL_HALF_LEN - 0.6,
              glazing, caps=False)

    # Structural rib hoops over the vault, continued down the walls as
    # pilasters: one bold rhythm, the way each guideway tier carries one.
    hoop = vault_ribbon(0.0, 1.0, 0.02, RIB_PROUD, steps=24)
    for u in RIB_US:
        sweep(f"rib{u:+.1f}", hoop, u_axis, v_axis,
              u - RIB_WIDTH / 2, u + RIB_WIDTH / 2, steel, caps=False)
        for side in (-1.0, 1.0):
            box(f"pilaster{u:+.1f}{side:+.0f}", u_axis, v_axis,
                u - RIB_WIDTH / 2, u + RIB_WIDTH / 2,
                side * HALL_HALF_WID, side * (HALL_HALF_WID + PILASTER_PROUD),
                0.0, WALL_TOP + 0.05, steel)

    # Crown spine housing the overhead crane rail, run out over the doorway so
    # the crane can pick straight off the apron.
    box("spine", u_axis, v_axis,
        -HALL_HALF_LEN - SPINE_NOSE, HALL_HALF_LEN,
        -SPINE_HALF, SPINE_HALF,
        RIDGE_TOP - SPINE_DEPTH + 0.30, RIDGE_TOP + 0.30, steel,
        bevel=iso.m(0.05))

    # Extraction pods on the far slope, and a comms mast on the rear shoulder:
    # the roof furniture a working hall actually grows.
    for u in VENT_US:
        base = vault_w(VENT_V) - 0.15
        box(f"vent{u:+.1f}", u_axis, v_axis, u - VENT_HALF, u + VENT_HALF,
            VENT_V - 0.6, VENT_V + 0.6, base, base + VENT_TOP, steel,
            bevel=iso.m(0.04))
    mast_base = vault_w(MAST_V) - 0.2
    box("mast", u_axis, v_axis, MAST_U - MAST_HALF, MAST_U + MAST_HALF,
        MAST_V - MAST_HALF, MAST_V + MAST_HALF, mast_base, MAST_TOP, steel)
    box("mast_arm", u_axis, v_axis, MAST_U - 0.06, MAST_U + 0.06,
        MAST_V - 0.5, MAST_V + 0.5, MAST_TOP - 0.5, MAST_TOP - 0.38, steel)

    # Segmented flank glazing between the pilasters — a lit workshop band
    # rather than one anonymous ribbon.
    duct = make_duct_material()
    for side in (-1.0, 1.0):
        for u0, u1 in zip(RIB_US, RIB_US[1:]):
            box(f"window{u0:+.1f}{side:+.0f}", u_axis, v_axis,
                u0 + RIB_WIDTH / 2 + 0.35, u1 - RIB_WIDTH / 2 - 0.35,
                side * HALL_HALF_WID, side * (HALL_HALF_WID + 0.05),
                WINDOW_LO, WINDOW_HI, glazing)
        # The 500's safety-orange service tray, arrived home along the plinth.
        box(f"conduit{side:+.0f}", u_axis, v_axis,
            -HALL_HALF_LEN + 0.1, HALL_HALF_LEN - 0.1,
            side * (HALL_HALF_WID + 0.02), side * (HALL_HALF_WID + CONDUIT_PROUD),
            CONDUIT_LO, CONDUIT_HI, duct)

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

    arch_pts = [vault_point(i / VAULT_SEGMENTS) for i in range(VAULT_SEGMENTS + 1)]
    iso.new_mesh("arch_glazing",
                 [local(u_axis, v_axis, -HALL_HALF_LEN + 0.05, v, w)
                  for v, w in arch_pts],
                 [list(range(len(arch_pts)))], glazing)

    # Door portal: a proud steel frame, its inner edge traced in the marker
    # colour — packed into the reserved light, the doorway stays outlined
    # after the map dims. The depot's own thread that never goes out.
    front = -HALL_HALF_LEN
    for side in (-1.0, 1.0):
        box(f"portal{side:+.0f}", u_axis, v_axis,
            front - PORTAL_PROUD, front + 0.2,
            side * DOOR_HALF, side * (DOOR_HALF + PORTAL_THICK),
            0.0, DOOR_TOP + PORTAL_THICK, steel, bevel=iso.m(0.04))
    box("portal_head", u_axis, v_axis, front - PORTAL_PROUD, front + 0.2,
        -DOOR_HALF - PORTAL_THICK, DOOR_HALF + PORTAL_THICK,
        DOOR_TOP, DOOR_TOP + PORTAL_THICK, steel, bevel=iso.m(0.04))
    for side in (-1.0, 1.0):
        strip = box(f"portal_lit{side:+.0f}", u_axis, v_axis,
                    front - PORTAL_PROUD - 0.03, front - PORTAL_PROUD + 0.10,
                    side * (DOOR_HALF + 0.02), side * (DOOR_HALF + 0.02 + LIT_STRIP),
                    0.25, DOOR_TOP + 0.02, lit)
        iso.no_shadow(strip)
    head = box("portal_lit_head", u_axis, v_axis,
               front - PORTAL_PROUD - 0.03, front - PORTAL_PROUD + 0.10,
               -DOOR_HALF - 0.02 - LIT_STRIP, DOOR_HALF + 0.02 + LIT_STRIP,
               DOOR_TOP + 0.02, DOOR_TOP + 0.02 + LIT_STRIP, lit)
    iso.no_shadow(head)


# --------------------------------------------------------------------------
# Concourse: the fusion-era roofed stop — the tube in bloom.
#
# A wide superellipse glass vault spans both platforms, the same fairing
# family and the same 8m structural grid as the vacuum tube, so a tube line
# arriving at a concourse reads as one system opening out. Split down the
# crown exactly like the tube: the far half ships in the back image, the near
# half in the front image, which Simutrans draws after vehicles — a train is
# seen *through* the canopy. A light cove runs along both springing lines in
# the marker colour, swapped at pack time for the reserved #7F9BF1, so a
# night concourse glows like the tubes it feeds.
# --------------------------------------------------------------------------

CANOPY_HALF = 7.35       # springing, metres from the centreline
CANOPY_RISE = 6.7        # crown height; airy over a 4m train
CANOPY_THICK = 0.16      # glazing plus frame; two edges in silhouette
CANOPY_SEGMENTS = 12
CANOPY_RIB_US = (-8.0, 0.0, 8.0)   # the tube's 8m hoop grid, so hoops land on
                                   # tile joints and chain across a platform
CANOPY_RIB_WIDTH = 0.28
CANOPY_RIB_PROUD = 0.10
CANOPY_SPINE_HALF = 0.40
CANOPY_SPINE_DEPTH = 0.14
COVE_LO, COVE_HI = 0.60, 1.00      # light cove along the springing
COVE_PROUD = 0.08
FOOT_IN, FOOT_OUT = 0.45, 0.30     # base beam the glass lands on
FOOT_TOP = 0.50


def canopy_profile(swell: float = 0.0):
    """Closed crescent for one half of the canopy, crown to springing."""
    outer = iso.arch(CANOPY_HALF + swell, CANOPY_RISE + swell, CANOPY_SEGMENTS)
    inner = iso.arch(CANOPY_HALF + swell - CANOPY_THICK,
                     CANOPY_RISE + swell - CANOPY_THICK, CANOPY_SEGMENTS)
    return outer + list(reversed(inner))


def build_concourse(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    up = Vector((0, 0, 1))
    build_platforms(u_axis, v_axis, part, pal)

    glass = iso.make_glass("canopy", pal["canopy_tint"],
                           face_alpha=0.12, edge_alpha=0.65)
    steel = iso.make_material("canopy_frame", pal["canopy_frame"],
                              roughness=0.38, metallic=0.55, noise=0.05)
    concrete = iso.make_material("foot", pal["platform"], roughness=0.94,
                                 noise=0.28)
    cove_mat = iso.make_flag_emission("cove")

    # Near half rides in the front image, far half in the back image; the
    # profile is one-sided, so the side is just the sweep perpendicular.
    side = 1.0 if part == "front" else -1.0
    start = local(u_axis, v_axis, -PLATFORM_LENGTH, 0.0)
    end = local(u_axis, v_axis, PLATFORM_LENGTH, 0.0)

    def half_sweep(name, profile_m, material, u0=-PLATFORM_LENGTH,
                   u1=PLATFORM_LENGTH, caps=False):
        profile = [(iso.m(v), iso.m(w)) for v, w in profile_m]
        return iso.extrude_profile(name, profile,
                                   local(u_axis, v_axis, u0, 0.0),
                                   local(u_axis, v_axis, u1, 0.0),
                                   v_axis * side, up, material, caps=caps)

    shell = half_sweep("canopy", canopy_profile(), glass)
    iso.no_shadow(shell)

    # Structural hoops on the tube's world grid, and the crown spine on the
    # near half only — one unbroken line down the run.
    hoop = canopy_profile(swell=CANOPY_RIB_PROUD)
    for u in CANOPY_RIB_US:
        half_sweep(f"hoop{u:+.0f}", hoop, steel,
                   u - CANOPY_RIB_WIDTH / 2, u + CANOPY_RIB_WIDTH / 2)
    if part == "front":
        spine = [(-CANOPY_SPINE_HALF, CANOPY_RISE - 0.02),
                 (CANOPY_SPINE_HALF, CANOPY_RISE - 0.02),
                 (CANOPY_SPINE_HALF, CANOPY_RISE + CANOPY_SPINE_DEPTH),
                 (-CANOPY_SPINE_HALF, CANOPY_RISE + CANOPY_SPINE_DEPTH)]
        iso.extrude_profile("spine", [(iso.m(v), iso.m(w)) for v, w in spine],
                            start, end, v_axis, up, steel, caps=False)

    # The glass lands on a low concrete base beam outside each platform, with
    # the light cove along its top edge — the never-dim thread at eye height.
    half_sweep("foot", [(CANOPY_HALF - FOOT_IN, 0.0),
                        (CANOPY_HALF - FOOT_IN, FOOT_TOP),
                        (CANOPY_HALF + FOOT_OUT, FOOT_TOP),
                        (CANOPY_HALF + FOOT_OUT, 0.0)], concrete, caps=True)
    cove = half_sweep("cove", [(CANOPY_HALF - COVE_PROUD, COVE_LO),
                               (CANOPY_HALF + COVE_PROUD, COVE_LO),
                               (CANOPY_HALF + COVE_PROUD, COVE_HI),
                               (CANOPY_HALF - COVE_PROUD, COVE_HI)], cove_mat,
                      caps=True)
    iso.no_shadow(cove)


# --------------------------------------------------------------------------
# Shelter (2032): the 700 era's stop. Platforms under thin flat glass
# canopies on slim steel posts, each canopy edge carried on a lit base rail
# — the same reserved-light thread as the 700 guideway's fence bases, so a
# mid-era stop glows gently where its trains do.
# --------------------------------------------------------------------------

SHELTER_POST_US = (-6.0, 0.0, 6.0)   # posts along each platform
SHELTER_POST_V = 4.6                 # post line, metres from the centreline
SHELTER_POST_HALF = 0.14
SHELTER_ROOF_H = 4.05                # underside of the glass
SHELTER_ROOF_IN = 1.9                # roof spans this v .. SHELTER_ROOF_OUT
SHELTER_ROOF_OUT = 6.6
SHELTER_ROOF_THICK = 0.14
SHELTER_RAIL_H = 0.16                # lit base rail on the roof's inner edge


def build_shelter(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    up = Vector((0, 0, 1))
    build_platforms(u_axis, v_axis, part, pal)

    glass = iso.make_glass("roof", pal["canopy_tint"],
                           face_alpha=0.16, edge_alpha=0.70)
    steel = iso.make_material("post", pal["frame"],
                              roughness=0.40, metallic=0.60)
    cove_mat = iso.make_flag_emission("rail")

    sides = [1.0] if part == "front" else [-1.0, 1.0]
    for side in sides:
        start = local(u_axis, v_axis, -PLATFORM_LENGTH, 0.0)
        end = local(u_axis, v_axis, PLATFORM_LENGTH, 0.0)
        roof = [(iso.m(side * SHELTER_ROOF_IN), iso.m(SHELTER_ROOF_H)),
                (iso.m(side * SHELTER_ROOF_OUT), iso.m(SHELTER_ROOF_H)),
                (iso.m(side * SHELTER_ROOF_OUT),
                 iso.m(SHELTER_ROOF_H + SHELTER_ROOF_THICK)),
                (iso.m(side * SHELTER_ROOF_IN),
                 iso.m(SHELTER_ROOF_H + SHELTER_ROOF_THICK))]
        pane = iso.extrude_profile(f"roof{side:+.0f}", roof, start, end,
                                   v_axis, up, glass, caps=False)
        iso.no_shadow(pane)
        # Lit rail along the platform-side roof edge, marker-swapped to the
        # reserved light when packed.
        rail = [(iso.m(side * SHELTER_ROOF_IN), iso.m(SHELTER_ROOF_H)),
                (iso.m(side * (SHELTER_ROOF_IN + 0.22)),
                 iso.m(SHELTER_ROOF_H)),
                (iso.m(side * (SHELTER_ROOF_IN + 0.22)),
                 iso.m(SHELTER_ROOF_H + SHELTER_RAIL_H)),
                (iso.m(side * SHELTER_ROOF_IN),
                 iso.m(SHELTER_ROOF_H + SHELTER_RAIL_H))]
        lit = iso.extrude_profile(f"rail{side:+.0f}", rail, start, end,
                                  v_axis, up, cove_mat, caps=False)
        iso.no_shadow(lit)
        for u in SHELTER_POST_US:
            base = local(u_axis, v_axis, u, side * SHELTER_POST_V)
            sq = iso.m(SHELTER_POST_HALF)
            post_profile = [(-sq, -sq), (sq, -sq), (sq, sq), (-sq, sq)]
            iso.extrude_profile(f"post{side:+.0f}_{u:+.0f}", post_profile,
                                base + up * iso.m(PLATFORM_TOP),
                                base + up * iso.m(SHELTER_ROOF_H + 0.02),
                                u_axis, v_axis, steel, caps=True)


# --------------------------------------------------------------------------
# Terminal (2100): the vacuum century's interchange. Two gull-wings — one
# over each platform — rising from outer walls toward high glass lips that
# face each other over the open guideway, in the 2000 tube's deeper tint
# and denser framing, a lit cove along each lip. The sky stays open above
# the beam: pods arrive under the wings, not through a wall.
# --------------------------------------------------------------------------

TERM_WALL_V = 7.1        # outer wall line, metres from the centreline
TERM_WALL_TOP = 3.6
TERM_LIP_V = 2.5         # inner high edge over the platform's track side
TERM_LIP_TOP = 7.6
TERM_THICK = 0.22
TERM_RIB_US = (-8.0, -2.7, 2.7, 8.0)     # denser than the concourse's 8m
TERM_RIB_WIDTH = 0.55
TERM_RIB_PROUD = 0.12
TERM_TINT = (0.52, 0.70, 0.76)           # the 2000 tube's deeper glass
TERM_FRAME = (0.400, 0.430, 0.480)


def terminal_wing(swell: float = 0.0):
    """Closed crescent of one gull-wing: outer wall top to inner lip, a
    quarter-superellipse leaning over the platform."""
    outer, inner = [], []
    steps = 10
    for i in range(steps + 1):
        t = i / steps
        s = math.sin(math.pi / 2 * t)
        v = TERM_WALL_V + (TERM_LIP_V - TERM_WALL_V) * (s ** 1.15)
        w = TERM_WALL_TOP + (TERM_LIP_TOP - TERM_WALL_TOP) * (1 - math.cos(
            math.pi / 2 * t) ** 1.3)
        outer.append((v + swell * 0.4, w + swell))
        inner.append((v + swell * 0.4, w + swell - TERM_THICK))
    return outer + list(reversed(inner))


def build_terminal(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    up = Vector((0, 0, 1))
    build_platforms(u_axis, v_axis, part, pal)

    glass = iso.make_glass("wing", TERM_TINT, face_alpha=0.15,
                           edge_alpha=0.72)
    steel = iso.make_material("term_frame", TERM_FRAME,
                              roughness=0.38, metallic=0.55, noise=0.05)
    wall = iso.make_material("term_wall", pal["wall"], roughness=0.80,
                             noise=0.18, seams=0.12, seam_period_m=4.0)
    cove_mat = iso.make_flag_emission("cove")

    side = 1.0 if part == "front" else -1.0
    start = local(u_axis, v_axis, -PLATFORM_LENGTH, 0.0)
    end = local(u_axis, v_axis, PLATFORM_LENGTH, 0.0)

    def sweep(name, profile_m, material, u0=-PLATFORM_LENGTH,
              u1=PLATFORM_LENGTH, caps=False):
        profile = [(iso.m(v), iso.m(w)) for v, w in profile_m]
        return iso.extrude_profile(name, profile,
                                   local(u_axis, v_axis, u0, 0.0),
                                   local(u_axis, v_axis, u1, 0.0),
                                   v_axis * side, up, material, caps=caps)

    # Outer wall from grade to the wing's springing.
    sweep("wall", [(TERM_WALL_V - 0.3, 0.0), (TERM_WALL_V - 0.3, TERM_WALL_TOP),
                   (TERM_WALL_V + 0.3, TERM_WALL_TOP), (TERM_WALL_V + 0.3, 0.0)],
          wall, caps=True)
    wing = sweep("wing", terminal_wing(), glass)
    iso.no_shadow(wing)
    for u in TERM_RIB_US:
        sweep(f"rib{u:+.0f}", terminal_wing(swell=TERM_RIB_PROUD), steel,
              u - TERM_RIB_WIDTH / 2, u + TERM_RIB_WIDTH / 2)
    # Lit cove along the high lip: the terminal's signature at night — two
    # bright lines facing each other over the arriving pods.
    lip = [(TERM_LIP_V - 0.16, TERM_LIP_TOP - 0.34),
           (TERM_LIP_V + 0.16, TERM_LIP_TOP - 0.34),
           (TERM_LIP_V + 0.16, TERM_LIP_TOP - 0.06),
           (TERM_LIP_V - 0.16, TERM_LIP_TOP - 0.06)]
    lit = sweep("lip", lip, cove_mat)
    iso.no_shadow(lit)


# --------------------------------------------------------------------------
# Skystop (2008): the urban elevated tier's stop. The engine draws a stop
# building on the elevated ground already lifted (pak128's suspended
# monorail station is authored at normal height with no offsets), and the
# way's own columns carry the street-level visual — so this is a floating
# metro stop: slim platforms, steel railings, a thin teal-fascia canopy.
# --------------------------------------------------------------------------

SKY_RAIL_TOP = 1.05          # railing above the platform deck
SKY_ROOF_H = 3.55
SKY_ROOF_IN, SKY_ROOF_OUT = 2.4, 6.0
SKY_POST_US = (-5.0, 5.0)
TEAL = (0.055, 0.290, 0.300)


def build_skystop(layout_index: int, part: str, pal) -> None:
    u_axis, v_axis = frame(layout_index)
    up = Vector((0, 0, 1))
    build_platforms(u_axis, v_axis, part, pal)

    glass = iso.make_glass("roof", pal["canopy_tint"],
                           face_alpha=0.15, edge_alpha=0.65)
    steel = iso.make_material("steel", pal["frame"],
                              roughness=0.40, metallic=0.60)
    teal = iso.make_material("fascia", TEAL, roughness=0.45, metallic=0.20)

    start = local(u_axis, v_axis, -PLATFORM_LENGTH, 0.0)
    end = local(u_axis, v_axis, PLATFORM_LENGTH, 0.0)
    sides = [1.0] if part == "front" else [-1.0, 1.0]
    for side in sides:
        # Railing along the outer platform edge: a floating platform needs
        # one, and its thin dark line is what says "elevated" at 128px.
        rail_v = PLATFORM_OUTER - 0.12
        for h in (SKY_RAIL_TOP,):
            bar = [(iso.m(side * (rail_v - 0.04)), iso.m(PLATFORM_TOP + h - 0.05)),
                   (iso.m(side * (rail_v + 0.04)), iso.m(PLATFORM_TOP + h - 0.05)),
                   (iso.m(side * (rail_v + 0.04)), iso.m(PLATFORM_TOP + h)),
                   (iso.m(side * (rail_v - 0.04)), iso.m(PLATFORM_TOP + h))]
            iso.extrude_profile(f"rail{side:+.0f}", bar, start, end,
                                v_axis, up, steel, caps=False)
        for u in (-6.5, -2.2, 2.2, 6.5):
            base = local(u_axis, v_axis, u, side * rail_v)
            sq = iso.m(0.045)
            iso.extrude_profile(f"baluster{side:+.0f}_{u:+.1f}",
                                [(-sq, -sq), (sq, -sq), (sq, sq), (-sq, sq)],
                                base + up * iso.m(PLATFORM_TOP),
                                base + up * iso.m(PLATFORM_TOP + SKY_RAIL_TOP),
                                u_axis, v_axis, steel, caps=True)
        # Thin glass canopy with a teal fascia edge, on two slim posts.
        roof = [(iso.m(side * SKY_ROOF_IN), iso.m(SKY_ROOF_H)),
                (iso.m(side * SKY_ROOF_OUT), iso.m(SKY_ROOF_H)),
                (iso.m(side * SKY_ROOF_OUT), iso.m(SKY_ROOF_H + 0.12)),
                (iso.m(side * SKY_ROOF_IN), iso.m(SKY_ROOF_H + 0.12))]
        pane = iso.extrude_profile(f"roof{side:+.0f}", roof, start, end,
                                   v_axis, up, glass, caps=False)
        iso.no_shadow(pane)
        fascia = [(iso.m(side * SKY_ROOF_IN), iso.m(SKY_ROOF_H)),
                  (iso.m(side * (SKY_ROOF_IN + 0.24)), iso.m(SKY_ROOF_H)),
                  (iso.m(side * (SKY_ROOF_IN + 0.24)), iso.m(SKY_ROOF_H + 0.20)),
                  (iso.m(side * SKY_ROOF_IN), iso.m(SKY_ROOF_H + 0.20))]
        iso.extrude_profile(f"fascia{side:+.0f}", fascia, start, end,
                            v_axis, up, teal, caps=False)
        for u in SKY_POST_US:
            base = local(u_axis, v_axis, u, side * 4.4)
            sq = iso.m(0.11)
            iso.extrude_profile(f"post{side:+.0f}_{u:+.0f}",
                                [(-sq, -sq), (sq, -sq), (sq, sq), (-sq, sq)],
                                base + up * iso.m(PLATFORM_TOP),
                                base + up * iso.m(SKY_ROOF_H + 0.02),
                                u_axis, v_axis, steel, caps=True)


BUILDERS = {"station": build_station, "depot": build_depot,
            "concourse": build_concourse, "shelter": build_shelter,
            "terminal": build_terminal, "skystop": build_skystop}


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
