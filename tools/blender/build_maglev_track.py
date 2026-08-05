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


# --------------------------------------------------------------------------
# Open-guideway tiers. The tubes' law — escalation is density of engineering —
# run so the ladder converges toward the tube, and each tier tells it through
# where its services live: the 300 strings them on masts beside the beam, the
# 500 clamps them into an orange tray on the flank, the 700 swallows them into
# the shell entirely and keeps only two lit threads on the deck edges — the
# first 40cm of the enclosure that the 1000 tier finally completes.
#
# Every motif here is sized to survive 128px: hue temperature on the girder
# (warm sand → cool precast → pale shell), plus one bold rhythm per tier
# (stator teeth / clamp ticks / lit edges). Centimetre realism that reads as
# flat grey at map zoom is deliberately exaggerated.
# --------------------------------------------------------------------------

TRACK_TIERS = {
    300: dict(girder=(0.500, 0.430, 0.300),   # warm site-cast sand
              girder_seams=0.42, seam_period=8.0, seam_width=0.22,
              slot=(0.330, 0.285, 0.205),     # concrete slot floor between packs
              stators=True, snow_slots=True, posts=True, cabinets=0.0,
              conduit=False, fairing=False, fence=False, heated_deck=False,
              lit_edges=False),
    500: dict(girder=(0.360, 0.395, 0.450),   # the cool precast standard
              girder_seams=0.06, seam_period=16.0, seam_width=0.05,
              slot=None,
              stators=False, snow_slots=False, posts=False, cabinets=10.7,
              conduit=True, fairing=False, fence=False, heated_deck=False,
              lit_edges=False),
    700: dict(girder=(0.620, 0.665, 0.720),   # pale engineered shell
              girder_seams=0.10, seam_period=4.0, seam_width=0.05,
              slot=None,
              stators=False, snow_slots=False, posts=False, cabinets=21.4,
              conduit=False, fairing=True, fence=True, heated_deck=True,
              lit_edges=True),
}

# The beam under an enclosed tube keeps the pre-tier standard look; its
# character comes from the tube around it, not the concrete inside.
TUBE_BEAM = dict(girder=None, girder_seams=0.10, seam_period=4.0,
                 seam_width=0.07, slot=None,
                 stators=False, snow_slots=False, posts=False, cabinets=0.0,
                 conduit=False, fairing=False, fence=False, heated_deck=False,
                 lit_edges=False)

# The guideway does not pave its tile: an elevated beam only needs a
# foundation band, and the ground either side stays living terrain — the
# same read as pak128's own ballast strips. The band is a precast slab a
# little wider than the deck, a drainage gutter running along each edge,
# and the trackside hardware stands on it: the 300's mast footings, the
# 500/700's service cabinets (their cables are buried, so the surface
# grows boxes on a world-anchored rhythm instead of masts).
BAND_HALF = 2.30          # slab half width; deck half is 1.60
BAND_TOP = 0.07           # slab thickness above grade
GUTTER = 0.25             # drainage gutter width along each slab edge
CABINET_W = 0.52          # service cabinet along the run
CABINET_D = (1.72, 2.16)  # cabinet footprint across, near the slab edge
CABINET_H = 0.74

# Exposed stator packs in the 300's guidance slots: real raised blocks, not a
# seam texture — the world-XY seam grid runs a line *along* a slot as happily
# as across it, which smeared the dashes into continuous stripes. Geometry
# dashes correctly on every direction and picks up real AO.
STATOR_PITCH = 1.2        # metres between pack centres
STATOR_LEN = 0.62         # length of one pack along the run
STATOR_CLEAR = 0.03       # pack top sits this far below the deck lip

# Service masts beside the 300: the cables the 500 will bury in its conduit.
POST_PITCH = 5.3          # three masts per 16m tile
POST_OFFSET = 2.45        # mast centreline from the girder axis
POST_HALF = 0.09
POST_TOP = 2.05           # mast height above the apron
ARM_HALF = 0.34           # crossarm half length
ARM_DROP = 0.12           # crossarm sits this far below the mast top
WIRE_HALF = 0.035
WIRE_DROP = 0.28          # catenary sag at mid-span
WIRE_SEGS = 4             # straight segments approximating one span

CONDUIT_LO, CONDUIT_HI = 0.24, 0.56   # cable tray on the girder flank (500)
CONDUIT_PROUD = 0.13
CLAMP_PITCH = 2.2         # clamp blocks pinning the tray, a visible rhythm
CLAMP_LEN = 0.18
CLAMP_PROUD = 0.05

FENCE_TOP = 0.42          # low glass wind fence above the deck edge (700)
FENCE_THICK = 0.07
FENCE_INSET = 0.06
FENCE_BASE = 0.12         # lit base rail under the glass, marker-swapped
                          # to the reserved non-darkening light at pack time

# Tier 700 fills the deck overhang with a flared skirt: same deck, same
# slots, but the exposed underside notch becomes a smooth shroud.
FAIRING_HALF = GIRDER_HALF + 0.30
_FAIRING_RIGHT = RIGHT_HALF[:8] + [
    (DECK_HALF, DECK_TOP - 0.10),
    (FAIRING_HALF, 0.20),
    (FAIRING_HALF, 0.0),
]
FAIRING_M = [(-p, h) for p, h in reversed(_FAIRING_RIGHT)] + _FAIRING_RIGHT[1:]
assert len(FAIRING_M) == len(PROFILE_M)   # SLOT_EDGES/DECK_EDGES stay valid


def profile_world(fairing: bool = False):
    points = FAIRING_M if fairing else PROFILE_M
    return [(iso.m(p), iso.m(h)) for p, h in points]


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
    return iso.arch(half_width, height, segments, TUBE_EXPONENT)


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

def anchored(start, axis, length, pitch_m, margin=0.0):
    """World-anchored positions along a run, like `rib_positions` but with a
    margin either side, so a rhythm (stator packs, clamps, masts) continues
    seamlessly across a tile boundary — the neighbour computes the very same
    world multiples."""
    origin_offset = start.dot(axis) / iso.m(1.0)      # in metres
    margin_m = margin / iso.m(1.0)
    first = math.ceil((origin_offset - margin_m) / pitch_m) * pitch_m
    out, here = [], first
    while here <= origin_offset + length / iso.m(1.0) + margin_m:
        out.append(iso.m(here - origin_offset))
        here += pitch_m
    return out


def build_stators(i, start, axis, length, over, right, up, stator_mat):
    """Exposed stator packs in the 300's guidance slots.

    Raised dark blocks on a world-anchored pitch: a bold dash rhythm that
    reads at 128px on any direction, with real ambient occlusion between the
    packs. (A seam texture cannot do this — the world-XY seam grid runs a
    line along a slot as happily as across it.)
    """
    half = iso.m(STATOR_LEN) / 2
    for s in (-1.0, 1.0):
        x_lo = iso.m(min(s * (SLOT_INNER + 0.02), s * (SLOT_OUTER - 0.02)))
        x_hi = iso.m(max(s * (SLOT_INNER + 0.02), s * (SLOT_OUTER - 0.02)))
        pack = [(x_lo, iso.m(SLOT_FLOOR + 0.01)),
                (x_hi, iso.m(SLOT_FLOOR + 0.01)),
                (x_hi, iso.m(DECK_TOP - STATOR_CLEAR)),
                (x_lo, iso.m(DECK_TOP - STATOR_CLEAR))]
        for k, t in enumerate(anchored(start, axis, length,
                                       STATOR_PITCH, over)):
            iso.extrude_profile(f"stator{i}_{s:+.0f}_{k}", pack,
                                start + axis * (t - half),
                                start + axis * (t + half),
                                right, up, stator_mat, bevel=0.0, caps=True)


def build_posts(i, start, axis, length, right, up, runs, shape, current_run):
    """Service masts and drooping feeder cables beside the 300.

    The comment on the 500's conduit was always literal: the pioneer tier
    strings its services on galvanised masts a couple of metres off the beam,
    two wires sagging between them. Masts sit on the far side from the
    camera so the wires drape behind the girder, and are world-anchored so
    the line of posts marches straight through tile boundaries.
    """
    mast_mat = iso.make_material("mast", (0.085, 0.092, 0.100),
                                 roughness=0.50, metallic=0.60)
    wire_mat = iso.make_material("wire", (0.030, 0.032, 0.036),
                                 roughness=0.60, metallic=0.30)
    pad_mat = iso.make_material("mast_pad", (0.40, 0.40, 0.40),
                                roughness=0.95, noise=0.25)

    side_out = right if (right.x - right.y) < 0.0 else -right

    # Other runs on this tile (crossings, junctions): a mast standing inside
    # another girder is a modelling error, so those positions are skipped and
    # the wire span simply breaks — junction hardware gaps, like real ones.
    others = []
    for r in runs:
        if r is current_run:
            continue
        o_start = iso.ground_point(shape, *r["start"])
        o_end = iso.ground_point(shape, *r["end"])
        o_axis = o_end - o_start
        if o_axis.length > 1e-6:
            others.append((o_start, o_axis.normalized()))

    def clear_of_runs(point):
        for o_start, o_axis in others:
            offset = point - o_start
            if (offset - o_axis * offset.dot(o_axis)).length < iso.m(3.0):
                return False
        return True

    hang_h = POST_TOP - ARM_DROP - 0.06
    sq = iso.m(POST_HALF)
    mast_profile = [(-sq, -sq), (sq, -sq), (sq, sq), (-sq, sq)]
    wq = iso.m(WIRE_HALF)
    wire_profile = [(-wq, -wq), (wq, -wq), (wq, wq), (-wq, wq)]
    arm = iso.m(0.05)
    arm_profile = [(-arm, -arm), (arm, -arm), (arm, arm), (-arm, arm)]

    # Mast positions are world-anchored with one extra either side, so a
    # span's parabola is the same one the neighbour tile computes — but only
    # geometry inside this run is actually built, or mast tops and wire stubs
    # from beyond the boundary would float in this sprite's sky over tiles
    # that may hold no track at all.
    masts = []
    for t in anchored(start, axis, length, POST_PITCH, iso.m(POST_PITCH)):
        base = start + axis * t + side_out * iso.m(POST_OFFSET)
        masts.append((t, clear_of_runs(base)))

    pq = iso.m(0.34)
    pad_profile = [(-pq, -pq), (pq, -pq), (pq, pq), (-pq, pq)]

    for k, (t, keep) in enumerate(masts):
        if not keep or not (0.0 <= t <= length):
            continue
        base = start + axis * t + side_out * iso.m(POST_OFFSET)
        # With no tile-wide apron the mast stands on terrain, so it gets
        # its own concrete footing pad.
        iso.extrude_profile(f"pad{i}_{k}", pad_profile,
                            base - up * iso.m(0.02),
                            base + up * iso.m(0.10),
                            axis, side_out, pad_mat, bevel=0.0, caps=True)
        iso.extrude_profile(f"mast{i}_{k}", mast_profile,
                            base - up * iso.m(0.05),
                            base + up * iso.m(POST_TOP),
                            axis, side_out, mast_mat, bevel=0.0, caps=True)
        arm_c = base + up * iso.m(POST_TOP - ARM_DROP)
        iso.extrude_profile(f"arm{i}_{k}", arm_profile,
                            arm_c - side_out * iso.m(ARM_HALF),
                            arm_c + side_out * iso.m(ARM_HALF),
                            axis, up, mast_mat, bevel=0.0, caps=True)

    def hang_point(t, e):
        return (start + axis * t
                + side_out * iso.m(POST_OFFSET + e * (ARM_HALF - 0.08))
                + up * iso.m(hang_h))

    for k in range(len(masts) - 1):
        (t_a, keep_a), (t_b, keep_b) = masts[k], masts[k + 1]
        if not (keep_a and keep_b):
            continue
        # Clip the span to this run in parameter space: the sag formula keeps
        # using the *global* span, so the clipped piece rendered here and the
        # piece the neighbour renders are parts of one continuous curve.
        u_lo = max(0.0, (0.0 - t_a) / (t_b - t_a))
        u_hi = min(1.0, (length - t_a) / (t_b - t_a))
        if u_hi <= u_lo:
            continue
        for e in (-1.0, 1.0):
            p_a, p_b = hang_point(t_a, e), hang_point(t_b, e)
            for j in range(WIRE_SEGS):
                u0 = u_lo + (u_hi - u_lo) * j / WIRE_SEGS
                u1 = u_lo + (u_hi - u_lo) * (j + 1) / WIRE_SEGS
                # Parabolic approximation of the catenary: 4u(1-u) peaks at 1
                # mid-span, so the wire drops WIRE_DROP metres at its lowest.
                q0 = p_a.lerp(p_b, u0) - up * iso.m(WIRE_DROP * 4 * u0 * (1 - u0))
                q1 = p_a.lerp(p_b, u1) - up * iso.m(WIRE_DROP * 4 * u1 * (1 - u1))
                seg = iso.extrude_profile(f"wire{i}_{k}_{e:+.0f}_{j}",
                                          wire_profile, q0, q1,
                                          side_out, up, wire_mat,
                                          bevel=0.0, caps=False)
                iso.no_shadow(seg)


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

    cfg = TRACK_TIERS.get(tier, TUBE_BEAM)
    winter = season == "winter"

    # Winter is where the tiers tell their story: an unheated beam disappears
    # under the same snow dusting as the apron, while the 700's powered deck
    # melts itself dark — a wet black ribbon through a white map, its lit
    # edge threads still burning.
    if cfg["girder"] is None:
        girder_color = pal["girder"]
    elif winter and not cfg["heated_deck"]:
        girder_color = pal["girder"]
    elif winter:
        girder_color = (0.052, 0.058, 0.066)    # wet meltwater asphalt
    else:
        girder_color = cfg["girder"]
    deck_pal = PALETTE["summer"] if (winter and cfg["heated_deck"]) else pal
    slot_color = cfg["slot"] or deck_pal["slot"]
    if winter and cfg["snow_slots"]:
        # Snow settles between the exposed stator packs of the 300.
        slot_color = tuple(0.45 * c + 0.55 * w
                           for c, w in zip(slot_color, (0.86, 0.88, 0.89)))

    # A junction or diagonal is not concrete at all: a real maglev switch is
    # a bare steel box girder that actuators flex sideways, and a maglev
    # "curve" is that same bending beam — there are no sharp turnouts to
    # cast. So every tile where runs meet or bend renders its girder as
    # steel with a tight actuator-segment rhythm, one tier-neutral machine
    # surface across the whole ladder, and the tier's dressing (stators,
    # tray, fences, masts) steps back for the length of the mechanism. In
    # winter the flexing surface stays dark — a switch cannot be allowed to
    # ice over — which makes junctions read at a glance on a white map.
    flexing = ("corner" in spec) or len(runs_for(spec)) > 1

    # The apron is panelled concrete like every other pak128 way; the girder
    # carries its own joint rhythm — heavy segment joints on the site-cast
    # 300, nearly seamless on the engineered 700.
    apron_mat = iso.make_material("apron", pal["apron"], roughness=0.95,
                                  noise=0.30, seams=0.075, seam_period_m=4.0)
    if flexing:
        girder_mat = iso.make_material("flex_girder", (0.190, 0.205, 0.235),
                                       roughness=0.35, metallic=0.75,
                                       seams=0.30, seam_period_m=2.0,
                                       seam_width_m=0.09)
    else:
        girder_mat = iso.make_material("girder", girder_color, roughness=0.72,
                                       noise=0.12, seams=cfg["girder_seams"],
                                       seam_period_m=cfg["seam_period"],
                                       seam_width_m=cfg["seam_width"])
    slot_mat = iso.make_material("slot", slot_color, roughness=0.45,
                                 metallic=0.55)
    lev_mat = iso.make_material("levitation", deck_pal["levitation"],
                                roughness=0.35, metallic=0.35)
    girder_slots = [girder_mat, slot_mat, lev_mat]

    up = iso.ground_normal(shape)

    if enclosure == "tube":
        # An enclosed tube is a structure, not a paved way: it gets a plinth
        # under its footprint rather than an apron across the whole tile, so
        # the ground either side stays visible.
        build_plinth(spec, shape, up, apron_mat)
    # The open guideway paves nothing either: each run gets a foundation
    # band swept beneath it (built in the run loop below), and the rest of
    # the tile stays transparent so the terrain shows through.
    # The flexing beam is a bare mechanism: no skirt, no tray, no fences,
    # no stator dressing, no masts — the dressed tiers hand over to steel
    # for the length of the switch and pick up again beyond it.
    profile = profile_world(cfg["fairing"] and not flexing)

    edge_materials = {e: 1 for e in SLOT_EDGES}
    edge_materials.update({e: 2 for e in DECK_EDGES})

    duct_mat = clamp_mat = fence_mat = stator_mat = None
    if cfg["conduit"] and not flexing:
        # Safety-orange cable tray: the 500's services moved off the 300's
        # masts and onto the beam, and the tray is painted to be found. The
        # flank lives in the girder's own shade, which turns pure albedo
        # orange to mud — a whisper of self-emission holds the paint hue
        # without reading as a lamp.
        duct_mat = iso.make_material("duct", (0.760, 0.235, 0.045),
                                     roughness=0.55, metallic=0.0)
        bsdf = duct_mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Emission Color"].default_value = (0.760, 0.235, 0.045, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 0.28
        clamp_mat = iso.make_material("clamp", (0.100, 0.105, 0.115),
                                      roughness=0.50, metallic=0.60)
    if cfg["fence"] and not flexing:
        fence_mat = iso.make_glass("fence", deck_pal["glass_tint"],
                                   face_alpha=0.12, edge_alpha=0.80)
    if cfg["stators"] and not flexing:
        stator_mat = iso.make_material("stator", (0.055, 0.058, 0.065),
                                       roughness=0.40, metallic=0.70)

    runs = [r for r in runs_for(spec)]

    for i, spec_run in enumerate(runs):
        lift = up * iso.m(spec_run["lift"])
        start = iso.ground_point(shape, *spec_run["start"]) + lift
        end = iso.ground_point(shape, *spec_run["end"]) + lift
        axis = end - start
        if axis.length < 1e-6:
            continue
        length = axis.length
        axis.normalize()
        right = axis.cross(up).normalized()
        over = iso.m(spec_run["overrun"])

        if enclosure != "tube":
            # Foundation band under the run: slab top with a drainage
            # gutter along each edge, everything else left as terrain.
            gutter_mat = iso.make_material("gutter",
                                           tuple(c * 0.55 for c in pal["apron"]),
                                           roughness=0.90, noise=0.15)
            band = [(iso.m(-BAND_HALF), 0.0),
                    (iso.m(-BAND_HALF), iso.m(BAND_TOP)),
                    (iso.m(-BAND_HALF + GUTTER), iso.m(BAND_TOP)),
                    (iso.m(BAND_HALF - GUTTER), iso.m(BAND_TOP)),
                    (iso.m(BAND_HALF), iso.m(BAND_TOP)),
                    (iso.m(BAND_HALF), 0.0)]
            iso.extrude_profile(f"band{i}", band,
                                start - axis * over, end + axis * over,
                                right, up, [apron_mat, gutter_mat],
                                {1: 1, 3: 1}, bevel=0.0)

        iso.extrude_profile(f"girder{i}", profile,
                            start - axis * over, end + axis * over,
                            right, up, girder_slots, edge_materials,
                            bevel=iso.m(0.06))

        if cfg["cabinets"] and not flexing and enclosure != "tube":
            # Buried services surface as cabinets on a world-anchored
            # rhythm, camera side, standing on the slab edge.
            cab_mat = iso.make_material("cabinet", (0.060, 0.075, 0.070),
                                        roughness=0.55, metallic=0.35)
            cab_side = right if (right.x - right.y) > 0.0 else -right
            c_lo, c_hi = CABINET_D
            for k, t in enumerate(anchored(start, axis, length,
                                           cfg["cabinets"])):
                if not (0.0 <= t <= length):
                    continue
                sgn = 1.0 if cab_side is right else -1.0
                cab = [(iso.m(sgn * c_lo), iso.m(BAND_TOP)),
                       (iso.m(sgn * c_hi), iso.m(BAND_TOP)),
                       (iso.m(sgn * c_hi), iso.m(BAND_TOP + CABINET_H)),
                       (iso.m(sgn * c_lo), iso.m(BAND_TOP + CABINET_H))]
                iso.extrude_profile(f"cab{i}_{k}", cab,
                                    start + axis * (t - iso.m(CABINET_W) / 2),
                                    start + axis * (t + iso.m(CABINET_W) / 2),
                                    right, up, cab_mat, bevel=0.0, caps=True)

        if stator_mat:
            build_stators(i, start, axis, length, over, right, up, stator_mat)

        for s in (-1.0, 1.0):
            if duct_mat:
                # Cable tray along each flank, pinned by proud clamp blocks:
                # a tick rhythm, so the tray reads as hardware rather than a
                # painted stripe.
                x_in, x_out = s * (GIRDER_HALF - 0.02), s * (GIRDER_HALF + CONDUIT_PROUD)
                duct = [(iso.m(x_in), iso.m(CONDUIT_LO)),
                        (iso.m(x_out), iso.m(CONDUIT_LO)),
                        (iso.m(x_out), iso.m(CONDUIT_HI)),
                        (iso.m(x_in), iso.m(CONDUIT_HI))]
                iso.extrude_profile(f"duct{i}_{s:+.0f}", duct,
                                    start - axis * over, end + axis * over,
                                    right, up, duct_mat, bevel=0.0, caps=False)
                c_out = s * (GIRDER_HALF + CONDUIT_PROUD + CLAMP_PROUD)
                clamp = [(iso.m(min(x_in, c_out)), iso.m(CONDUIT_LO - 0.04)),
                         (iso.m(max(x_in, c_out)), iso.m(CONDUIT_LO - 0.04)),
                         (iso.m(max(x_in, c_out)), iso.m(CONDUIT_HI + 0.04)),
                         (iso.m(min(x_in, c_out)), iso.m(CONDUIT_HI + 0.04))]
                for k, t in enumerate(anchored(start, axis, length,
                                               CLAMP_PITCH, over)):
                    a = start + axis * (t - iso.m(CLAMP_LEN) / 2)
                    b = start + axis * (t + iso.m(CLAMP_LEN) / 2)
                    iso.extrude_profile(f"clamp{i}_{s:+.0f}_{k}", clamp,
                                        a, b, right, up, clamp_mat,
                                        bevel=0.0, caps=True)
            if fence_mat:
                # Low glass wind fence on each deck edge: the first 40cm of
                # the tube, grown from the guideway.
                x0 = s * (DECK_HALF - FENCE_INSET)
                x1 = s * (DECK_HALF - FENCE_INSET - FENCE_THICK)
                base_h = FENCE_BASE if cfg["lit_edges"] else 0.0
                wall = [(iso.m(x0), iso.m(DECK_TOP + base_h)),
                        (iso.m(x0), iso.m(DECK_TOP + FENCE_TOP)),
                        (iso.m(x1), iso.m(DECK_TOP + FENCE_TOP)),
                        (iso.m(x1), iso.m(DECK_TOP + base_h))]
                pane = iso.extrude_profile(f"fence{i}_{s:+.0f}", wall,
                                           start - axis * over,
                                           end + axis * over,
                                           right, up, fence_mat,
                                           bevel=0.0, caps=False)
                iso.no_shadow(pane)
                if cfg["lit_edges"]:
                    # The fence base rail renders as the magenta marker and is
                    # swapped for the reserved non-darkening light when the
                    # sheet is packed — two threads that stay lit at night,
                    # the guideway already carrying a sliver of the tube's
                    # light cove.
                    rail = [(iso.m(min(x0, x1)), iso.m(DECK_TOP + 0.01)),
                            (iso.m(max(x0, x1)), iso.m(DECK_TOP + 0.01)),
                            (iso.m(max(x0, x1)), iso.m(DECK_TOP + base_h)),
                            (iso.m(min(x0, x1)), iso.m(DECK_TOP + base_h))]
                    strip = iso.extrude_profile(f"litrail{i}_{s:+.0f}",
                                                rail,
                                                start - axis * over,
                                                end + axis * over,
                                                right, up,
                                                iso.make_flag_emission("lit"),
                                                bevel=0.0, caps=False)
                    iso.no_shadow(strip)

        if cfg["posts"] and not flexing:
            build_posts(i, start, axis, length, right, up, runs, shape,
                        spec_run)

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
    p.add_argument("--tier", type=int, default=None,
                   choices=sorted(TRACK_TIERS) + sorted(TUBE_TIERS))
    args = p.parse_args(argv)
    if args.tier is None:
        args.tier = 1000 if args.enclosure == "tube" else 300
    if (args.enclosure == "tube") != (args.tier in TUBE_TIERS):
        p.error(f"tier {args.tier} does not match enclosure {args.enclosure}")
    return args


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
