"""Build and render the maglev passenger section in Blender.

    blender --background --python tools/blender/build_maglev_vehicle.py -- \
        --out build/vehicle

Renders the eight travel directions Simutrans needs. The body is modelled once
along its own axis and then pointed down each heading, so all eight views come
from identical geometry and cannot drift apart the way hand-drawn ones do.

Shape
-----
A Transrapid wraps its guideway rather than sitting on rails: the body is a
rounded shell whose skirts come down *outside* the 3.2m beam, with a channel up
the middle for it. That channel is cut straight into the cross-section, so the
guideway drawn underneath disappears under the vehicle exactly where it should.

The section is symmetric with chamfered ends, because the prototype has one
vehicle type that couples to itself. See `NOSE_START` for why the ends are not
domed. A streamlined nose wants a second, head-only vehicle type.

Roles
-----
All four vehicle roles share one body loft; what tells them apart is the roof,
because from the 30-degree camera the roof is most of what a player sees:

* ``car``  — glazed skylight panes set into the accent crown band
* ``mail`` — sealed crown with transverse roof hatches, no windows anywhere
* ``head`` — streamlined nose plus a dorsal power blister on the flat roof
* ``tail`` — the head's geometry with the windscreen blanked to body colour,
  so a train visibly has a lit front and a blind back
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

# Metres. `length=12` in the .dat is 12/16 of a tile, so the body is 12m long
# and coupled sections meet without overlapping.
BODY_LENGTH = 12.0
HALF_LEN = BODY_LENGTH / 2

BODY_HALF = 1.95         # widest half width
SKIRT_BOTTOM = 0.25      # how close the skirts come to the apron
FLOOR = 1.05             # underside of the body, just above the 0.85m deck
CHANNEL_HALF = 1.75      # clears the 1.6m guideway deck half width
# Height and roof curvature are set against pak128's own vehicles rather than
# against real Transrapid dimensions. Measured off its Shinkansen, a pak128
# car is roughly two thirds of its real height and half its real length — the
# set draws vehicles well off ground scale. Modelling this one to true metres
# made it read as a fat white pill next to everything else, so the body sits
# low with a shallow roof and a long taper instead.
ROOF_TOP = 2.90
SHOULDER = 2.20          # where the sides stop and the roof curve starts
ROOF_SEGMENTS = 10

WINDOW_LO, WINDOW_HI = 1.46, 1.98
ACCENT_LO, ACCENT_HI = 1.18, 1.44
# Company colour also runs along the crown. From a 30-degree camera you see
# far more roof than flank, so a side stripe alone is nearly invisible at
# 128px — the roof band is what actually identifies the operator.
ROOF_BAND_HALF = 0.55

# The prototype has one vehicle type that couples to itself, so both ends of
# every section are the same. Doming them made a coupled train read as a chain
# of separate pods, so the ends are only chamfered: coupled sections form a
# near-continuous tube with a joint line, which is how an articulated maglev
# actually looks, and a single unit still reads as finished rather than sawn
# off. A streamlined nose needs a separate head vehicle type.
# --------------------------------------------------------------------------
# Per-set proportions.
#
# Silhouette carries the datasheet: a standard is taller and boxier and really
# does seat ~1.6x a flagship; a flagship is long-nosed and low and really does
# trade capacity for speed. Shape is not decoration here.
#
# Era is continuous rather than banded — proportions are driven by the set's
# own speed, so all sixteen trainsets differ, streamlining progressively from
# blunt commuter to pure capsule.
# --------------------------------------------------------------------------

SPEED_LO, SPEED_HI = 220.0, 4000.0     # ends of the roster

GRADES = {                              # nose, roof, window band, doors per car
    "flagship": dict(nose=1.25, roof=0.95, window=0.85, doors=1),
    "standard": dict(nose=0.80, roof=1.06, window=1.15, doors=3),
    "value":    dict(nose=0.85, roof=1.00, window=1.00, doors=2),
}

DOOR_WIDTH = 0.95
DOOR_LO, DOOR_HI = 0.34, 2.05
DOOR_PROUD = 0.03
MAIL_DOOR_WIDTH = 2.40                  # one wide loading door, no windows

# --------------------------------------------------------------------------
# Per-role roof and flank treatments.
#
# Every role shares the loft; the roof is what tells them apart, because the
# 30-degree camera shows far more roof than flank. Passenger cars carry glass
# up there, mail carries machinery, the head carries its power blister.
# --------------------------------------------------------------------------

# Recessed door grooves and a segmented window band. Set False to revert to
# proud door panels on a continuous band (the pre-2026-08 flank look).
SCULPTED_FLANKS = True

# Passenger skylight: glazed panes replacing stretches of the accent crown
# band, so the company colour frames the glass instead of vanishing under it.
SKYLIGHT_SPAN = 0.62         # fraction of the body length under glass
SKYLIGHT_PANES = 3
SKYLIGHT_GAP = 0.28          # accent-coloured mullion between panes, metres

# Mail roof: transverse hatch fairings. Grey machinery on a sealed white
# crown is what separates mail from passenger when both share one loft.
HATCH_POSITIONS = (-2.8, 0.0, 2.8)
HATCH_LEN = 0.85             # along the body
HATCH_HALF = 0.55            # across; inside the roof band
HATCH_RISE = 0.12            # proud of the crown
HATCH_SINK = 0.08            # buried below it, so edges never float

# Head dorsal blister: a power fairing on whatever flat roof the nose leaves.
# Fast sets grow their nose until no flat roof remains, so the blister
# disappears on its own — a vacuum capsule stays sealed and smooth.
BLISTER_HALF = 0.62          # widest half width, inside the roof band
BLISTER_RISE = 0.26          # above the crown at its highest
BLISTER_SINK = 0.10          # buried into the roof
BLISTER_MAX_LEN = 3.4
BLISTER_MIN_LEN = 1.2        # less flat roof than this: no blister at all

# Flank sculpting (all behind SCULPTED_FLANKS).
GROOVE_DEPTH = 0.05          # door pocket recess into the body side
GROOVE_MARGIN = 0.10         # pocket wider than its door, each side
WINDOW_PANE = 1.35           # window segment length between mullions
WINDOW_PANE_GAP = 0.30       # body-coloured mullion between segments
STATION_STEP = 0.35          # interior loft density so treatments land crisp


def era(speed: float) -> float:
    """0 at the slowest set in the roster, 1 at the fastest."""
    return min(1.0, max(0.0, math.log(speed / SPEED_LO)
                        / math.log(SPEED_HI / SPEED_LO)))


def proportions(speed: float, grade: str):
    """Nose length, roof height, shoulder and window band for one trainset."""
    t = era(speed)
    g = GRADES[grade]
    nose = (3.8 + 4.4 * t) * g["nose"]
    roof = (3.20 - 0.55 * t) * g["roof"]
    # Sides straighten out early and round over late: a pressure vessel, not a
    # slab-sided carriage.
    shoulder = roof - (0.55 + 0.45 * t)
    band = (0.62 - 0.30 * t) * g["window"]
    win_hi = shoulder - 0.16
    # The nose may run the whole length of the body — a head car that is
    # nothing but nose is exactly right at the fast end, and capping it at half
    # the body made every flagship share one silhouette.
    return dict(nose=min(nose, BODY_LENGTH * 0.92), roof=roof, shoulder=shoulder,
                win_lo=win_hi - band, win_hi=win_hi, doors=g["doors"])


NOSE_START = 5.1         # coupling-end chamfer begins this far from centre
NOSE_MIN = 0.72          # width left at that end, as a fraction

# Head car: a long wedge nose over the front third of the body.
NOSE_LEN = 6.0           # metres of nose, measured back from the tip
NOSE_WIDTH_MIN = 0.80    # upper body draw-in at the tip
NOSE_HEIGHT_MIN = 0.30   # roof height at the tip, about the floor line

BODY, WINDOW, ACCENT, SKIRT = 0, 1, 2, 3

# One livery per manufacturer. Bodies stay light across the board: later stock
# runs inside tinted glass tubes, and a dark body reads as a smudge through
# the glazing. The accent stripe is what tells the companies apart.
LIVERIES = {
    "meridian": {                        # flagships — precision, speed records
        "body": (0.870, 0.880, 0.900),
        "window": (0.050, 0.065, 0.090),
        "accent": (0.090, 0.230, 0.520),
        "skirt": (0.210, 0.225, 0.250),
    },
    "kestrel": {                         # standards — throughput, dependability
        "body": (0.815, 0.795, 0.735),
        "window": (0.055, 0.075, 0.075),
        "accent": (0.640, 0.180, 0.150),
        "skirt": (0.225, 0.240, 0.230),
    },
    "volta": {                           # value engineering
        "body": (0.700, 0.705, 0.715),
        "window": (0.065, 0.070, 0.080),
        "accent": (0.780, 0.480, 0.060),
        "skirt": (0.245, 0.245, 0.250),
    },
    "aetheris": {                        # vacuum era, enters late
        "body": (0.845, 0.885, 0.925),
        "window": (0.040, 0.055, 0.075),
        "accent": (0.150, 0.640, 0.640),
        "skirt": (0.200, 0.215, 0.240),
    },
}


def profile(prop=None):
    """Closed cross-section as (across, height, material of the edge that starts here).

    Runs up the left flank, over the roof, down the right flank, then back
    along the underside — which is where the guideway channel is cut.
    """
    roof_top = prop["roof"] if prop else ROOF_TOP
    shoulder = prop["shoulder"] if prop else SHOULDER
    win_lo = prop["win_lo"] if prop else WINDOW_LO
    win_hi = prop["win_hi"] if prop else WINDOW_HI
    acc_lo, acc_hi = win_lo - 0.26, win_lo - 0.04

    points = [
        (-BODY_HALF, SKIRT_BOTTOM, BODY),
        (-BODY_HALF, acc_lo, ACCENT),
        (-BODY_HALF, acc_hi, WINDOW),
        (-BODY_HALF, win_hi, BODY),
        (-BODY_HALF, shoulder, BODY),
    ]
    # Roof: half ellipse from shoulder to shoulder.
    rise = roof_top - shoulder
    for i in range(1, ROOF_SEGMENTS):
        t = math.pi * i / ROOF_SEGMENTS
        across = -BODY_HALF * math.cos(t)
        points.append((across, shoulder + rise * math.sin(t),
                       ACCENT if abs(across) < ROOF_BAND_HALF else BODY))
    points += [
        (BODY_HALF, shoulder, BODY),
        (BODY_HALF, win_hi, WINDOW),
        (BODY_HALF, acc_hi, ACCENT),
        (BODY_HALF, acc_lo, BODY),
        (BODY_HALF, SKIRT_BOTTOM, SKIRT),
        # Underside, cutting the channel the guideway passes through.
        (CHANNEL_HALF, SKIRT_BOTTOM, SKIRT),
        (CHANNEL_HALF, FLOOR, SKIRT),
        (-CHANNEL_HALF, FLOOR, SKIRT),
        (-CHANNEL_HALF, SKIRT_BOTTOM, SKIRT),
    ]
    return points


def chamfer(u: float) -> tuple[float, float]:
    """Width and height factors for a coupling end."""
    over = abs(u) - NOSE_START
    if over <= 0.0:
        return 1.0, 1.0
    t = min(1.0, over / (HALF_LEN - NOSE_START))
    s = max(NOSE_MIN, math.sqrt(max(0.0, 1.0 - t * t)))
    return s, 0.55 + 0.45 * s


def nose(u: float, nose_len: float = None) -> tuple[float, float]:
    """Width and height factors along the streamlined nose of the head car.

    A maglev nose is a wedge, not a cone. The vehicle wraps its guideway all
    the way to the tip, so the skirts cannot pull in — narrowing the section
    would drive the underside channel into the 3.2m beam. The taper is
    therefore almost all in height, measured about the floor line so the
    channel and skirts stay exactly where they are, with only a slight draw-in
    of the upper body.
    """
    length = nose_len or NOSE_LEN
    over = u - (HALF_LEN - length)
    if over <= 0.0:
        return 1.0, 1.0
    t = min(1.0, over / length)
    width = 1.0 - (1.0 - NOSE_WIDTH_MIN) * t * t
    height = 1.0 - (1.0 - NOSE_HEIGHT_MIN) * math.sin(t * math.pi / 2) ** 1.5
    return width, height


def stations(role: str, nose_len: float = None):
    """Positions along the body where a cross-section is placed."""
    length = nose_len or NOSE_LEN
    out = {-HALF_LEN, 0.0, HALF_LEN}
    for i in range(9):                              # dense through the tapers
        out.add(-HALF_LEN + (HALF_LEN - NOSE_START) * i / 8)
    if role in ("head", "tail"):
        for i in range(15):                         # denser still up the nose
            out.add(HALF_LEN - length + length * i / 14)
    else:
        for i in range(9):
            out.add(HALF_LEN - (HALF_LEN - NOSE_START) * i / 8)
    # Uniform interior rings: skylight panes, window mullions and door grooves
    # are painted per face, so the loft needs faces there to paint.
    steps = int(2 * NOSE_START / STATION_STEP)
    for i in range(steps + 1):
        out.add(-NOSE_START + i * STATION_STEP)
    return sorted(round(u, 4) for u in out)


def door_spots(count: int, mail: bool):
    """Door centre positions along the body, shared by doors and grooves."""
    if mail or count == 1:
        return [0.0]
    span = BODY_LENGTH * 0.30
    if count == 2:
        return [-span * 0.7, span * 0.7]
    return [-span, 0.0, span]


def skylight_pane(u: float) -> bool:
    """Is this position under one of the passenger skylight panes?"""
    span = BODY_LENGTH * SKYLIGHT_SPAN
    pane = (span - (SKYLIGHT_PANES - 1) * SKYLIGHT_GAP) / SKYLIGHT_PANES
    x = u + span / 2
    return 0.0 <= x <= span and x % (pane + SKYLIGHT_GAP) <= pane


def window_gap(u: float) -> bool:
    """Is this position on a mullion between window segments?"""
    return (u + HALF_LEN) % (WINDOW_PANE + WINDOW_PANE_GAP) > WINDOW_PANE


def in_groove(u: float, grooves) -> bool:
    return any(lo + 0.01 < u < hi - 0.01 for lo, hi in grooves)


_BOX_FACES = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4],
              [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]


def _box(name, forward, across, up, u_lo, u_hi, v_half, z_lo, z_hi, material):
    """An axis-aligned box in body coordinates, sunk wherever z_lo says."""
    corners = [(u_lo, -v_half), (u_hi, -v_half), (u_hi, v_half), (u_lo, v_half)]
    verts = []
    for z in (z_lo, z_hi):
        for du, dv in corners:
            verts.append(forward * iso.m(du) + across * iso.m(dv)
                         + up * iso.m(z))
    iso.new_mesh(name, verts, _BOX_FACES, material)


# --------------------------------------------------------------------------
# Manufacturer logo: one bold glyph on each flank near the coupling end.
#
# The flank renders at 4px per metre, so a "realistic" half-metre emblem is
# two pixels of nothing — the glyph is billboard-sized (~1.3m), the same
# deliberate exaggeration pak128 applies everywhere. Shapes are built from
# axis-aligned plates only, chosen to stay distinct at 5px: Meridian a solid
# disc, Kestrel twin bars, Volta a lightning step, Aetheris a hollow ring.
# --------------------------------------------------------------------------

LOGO_U = -4.35           # centre along the body: clear of doors (max |u| 3.6)
                         # and inside the coupling chamfer at 5.1
LOGO_H = 0.93            # centre height: the clean body panel between the
                         # skirt top and the accent stripe (acc_lo ~ 1.6)
LOGO_S = 0.65            # glyph half size
LOGO_PROUD = 0.04        # plate stands this far off the flank

# (du, dh, half_u, half_h) rects in glyph units, scaled by LOGO_S.
LOGO_GLYPHS = {
    "meridian": [(0.0, 0.0, 0.46, 0.62), (0.0, 0.0, 0.72, 0.36)],  # disc
    "kestrel":  [(-0.42, 0.0, 0.24, 0.80), (0.42, 0.0, 0.24, 0.80)],  # bars
    "volta":    [(-0.52, 0.52, 0.30, 0.30), (0.0, 0.0, 0.30, 0.30),
                 (0.52, -0.52, 0.30, 0.30)],                       # lightning
    "aetheris": [(0.0, 0.72, 0.72, 0.22), (0.0, -0.72, 0.72, 0.22),
                 (-0.72, 0.0, 0.22, 0.50), (0.72, 0.0, 0.22, 0.50)],  # ring
}


def build_logo(forward, across, up, livery: str, accent_mat) -> None:
    for side in (-1.0, 1.0):
        for k, (du, dh, hu, hh) in enumerate(LOGO_GLYPHS[livery]):
            u_c = LOGO_U + du * LOGO_S
            h_c = LOGO_H + dh * LOGO_S
            corners = [(u_c - hu * LOGO_S, u_c + hu * LOGO_S)]
            verts = []
            for v in (BODY_HALF, BODY_HALF + LOGO_PROUD):
                for u in corners[0]:
                    for h in (h_c - hh * LOGO_S, h_c + hh * LOGO_S):
                        verts.append(forward * iso.m(u)
                                     + across * iso.m(side * v)
                                     + up * iso.m(h))
            faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 2, 6, 4],
                     [1, 5, 7, 3], [0, 4, 5, 1], [2, 3, 7, 6]]
            iso.new_mesh(f"logo_{side:+.0f}_{k}", verts, faces, accent_mat)


def build_hatches(forward, across, up, prop, material):
    """Transverse roof hatches: the mail van's identity from above."""
    for k, u0 in enumerate(HATCH_POSITIONS):
        _box(f"hatch_{k}", forward, across, up,
             u0 - HATCH_LEN / 2, u0 + HATCH_LEN / 2, HATCH_HALF,
             prop["roof"] - HATCH_SINK, prop["roof"] + HATCH_RISE, material)


def build_blister(forward, across, up, prop, material):
    """Dorsal power fairing on the head's remaining flat roof.

    Spans from just behind the nose taper back towards the coupling chamfer.
    The nose grows with speed, so late flagships have no flat roof left and
    the blister vanishes on its own — a capsule stays sealed.
    """
    flat_hi = HALF_LEN - prop["nose"] - 0.35
    flat_lo = -NOSE_START + 0.5
    length = min(BLISTER_MAX_LEN, flat_hi - flat_lo)
    if length < BLISTER_MIN_LEN:
        return
    base = prop["roof"] - BLISTER_SINK
    rings, arcs = 10, 7
    verts, faces = [], []
    for k in range(rings + 1):
        u = flat_hi - length + length * k / rings
        env = math.sin(math.pi * k / rings) ** 0.7     # domed ends
        for j in range(arcs + 1):
            a = math.pi * j / arcs
            v = math.cos(a) * BLISTER_HALF * (0.35 + 0.65 * env)
            z = base + (BLISTER_SINK + BLISTER_RISE) * math.sin(a) * env
            verts.append(forward * iso.m(u) + across * iso.m(v)
                         + up * iso.m(z))
    for k in range(rings):
        for j in range(arcs):
            a = k * (arcs + 1) + j
            b = a + arcs + 1
            faces.append([a, a + 1, b + 1, b])
    iso.new_mesh("blister", verts, faces, material)


def build_doors(forward, across, up, count, mail, material, win_lo, win_hi):
    """Vertical door panels breaking the window band.

    Door *count* is the readable form of dwell time: a standard is a commuter
    set with three doors a side and a 700ms stop, a flagship has one and takes
    1100ms. A mail van gets a single wide loading door and no windows at all —
    which is what tells the two apart at 50x25px, far more than colour.
    """
    spots = door_spots(count, mail)
    if mail:
        width, lo, hi = MAIL_DOOR_WIDTH, DOOR_LO, win_hi + 0.10
    else:
        width, lo, hi = DOOR_WIDTH, DOOR_LO, DOOR_HI
    if SCULPTED_FLANKS:
        # The panel sits just proud of its groove floor, still shy of the
        # body wall: a pocket door, read as a dark slot in the flank.
        depths = (BODY_HALF - 2 * GROOVE_DEPTH, BODY_HALF - GROOVE_DEPTH + 0.005)
    else:
        depths = (BODY_HALF - 0.04, BODY_HALF + DOOR_PROUD)
    for side in (-1.0, 1.0):
        for k, u in enumerate(spots):
            corners = [(u - width / 2, lo), (u + width / 2, lo),
                       (u + width / 2, hi), (u - width / 2, hi)]
            verts = []
            for depth in depths:
                for du, dz in corners:
                    verts.append(forward * iso.m(du)
                                 + across * iso.m(side * depth)
                                 + up * iso.m(dz))
            iso.new_mesh(f"door{side:+.0f}_{k}", verts, _BOX_FACES, material)


def build_body(heading, role: str = "car", livery: str = "meridian",
               speed: float = 500.0, grade: str = "flagship") -> None:
    """Loft the cross-section down the body, cap the ends, dress the role.

    `mail` blanks the window band to body colour — no windows is what reads as
    a mail van at 50x25px, far more than any change of hue would.
    """
    forward = Vector((heading[0], heading[1], 0.0))
    across = Vector((-heading[1], heading[0], 0.0))
    up = Vector((0.0, 0.0, 1.0))

    mail = role == "mail"
    nosed = role in ("head", "tail")

    pal = LIVERIES[livery]
    glazing = pal["body"] if mail else pal["window"]
    materials = [iso.make_material("body", pal["body"], roughness=0.30,
                                   metallic=0.15, noise=0.04),
                 iso.make_material("window", glazing,
                                   roughness=0.30 if mail else 0.08,
                                   metallic=0.15 if mail else 0.50),
                 iso.make_material("accent", pal["accent"], roughness=0.25,
                                   metallic=0.30),
                 iso.make_material("skirt", pal["skirt"], roughness=0.75)]

    prop = proportions(speed, grade)
    section = profile(prop)
    n = len(section)
    shoulder = prop["shoulder"]
    us = stations(role, prop["nose"])

    grooves = []
    if SCULPTED_FLANKS and role in ("car", "mail"):
        half = (MAIL_DOOR_WIDTH if mail else DOOR_WIDTH) / 2 + GROOVE_MARGIN
        grooves = [(s - half, s + half)
                   for s in door_spots(prop["doors"], mail)]
        # Rings on the pocket walls, so the recess is a step, not a smear.
        us = sorted(set(us) | {round(e, 4) for lo, hi in grooves
                               for e in (lo, hi, lo + 0.05, hi - 0.05)})
    groove_scale = (BODY_HALF - GROOVE_DEPTH) / BODY_HALF

    verts, faces, face_materials = [], [], []
    for u in us:
        if nosed and u > 0.0:
            width, height_factor = nose(u, prop["nose"])
        else:
            width, height_factor = chamfer(u)
        pocket = grooves and in_groove(u, grooves)
        for v, w, _ in section:
            if w <= FLOOR:
                # Skirts and the guideway channel never move: the body has to
                # keep wrapping the beam from end to end.
                height, across_scale = w, 1.0
            else:
                height = FLOOR + (w - FLOOR) * height_factor
                across_scale = width
                if pocket and abs(v) >= BODY_HALF - 1e-6 \
                        and w < shoulder - 1e-6:
                    across_scale *= groove_scale
            verts.append(forward * iso.m(u) + across * iso.m(v * across_scale)
                         + up * iso.m(height))

    # A commuter set gets its window band cut into segments; a flagship keeps
    # the sleek continuous ribbon. Door count already encodes exactly that.
    rhythm = SCULPTED_FLANKS and role == "car" and prop["doors"] >= 2
    for ring in range(len(us) - 1):
        base, nxt = ring * n, (ring + 1) * n
        u_mid = (us[ring] + us[ring + 1]) / 2
        for i in range(n):
            j = (i + 1) % n
            faces.append([base + i, base + j, nxt + j, nxt + i])
            mat = section[i][2]
            w_i = section[i][1]
            if role == "car" and mat == ACCENT and w_i > shoulder \
                    and skylight_pane(u_mid):
                mat = WINDOW    # skylight pane framed by the accent band
            elif rhythm and mat == WINDOW and w_i <= shoulder \
                    and window_gap(u_mid):
                mat = BODY      # mullion between window segments
            face_materials.append(mat)

    # The head's front cap is glazed: at 128px a dark tip is what reads as a
    # windscreen and tells you which way the train is pointing. The tail gets
    # the same geometry with the cap blanked — a blind rear, so a whole train
    # reads directional instead of double-ended.
    nose_cap = WINDOW if role == "head" else BODY
    for ring, order, material in ((0, list(range(n - 1, -1, -1)), BODY),
                                  (len(us) - 1, list(range(n)), nose_cap)):
        faces.append([ring * n + i for i in order])
        face_materials.append(material)

    obj = iso.new_mesh("body", verts, faces, materials, bevel=0.0)
    for poly, mat in zip(obj.data.polygons, face_materials):
        poly.material_index = mat

    trim = iso.make_material("trim", pal["skirt"], roughness=0.55,
                             metallic=0.35)
    logo_mat = iso.make_material("logo", pal["accent"], roughness=0.30,
                                 metallic=0.25)
    build_logo(forward, across, up, livery, logo_mat)
    if mail:
        build_hatches(forward, across, up, prop, trim)
    if nosed:
        build_blister(forward, across, up, prop, trim)
    else:
        # Doors only on trailers; a head car is mostly nose and has no flank.
        door_mat = iso.make_material(
            "door", pal["window"] if not mail else pal["skirt"],
            roughness=0.35, metallic=0.25)
        build_doors(forward, across, up, prop["doors"], mail, door_mat,
                    prop["win_lo"], prop["win_hi"])


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--role", default="car",
                   choices=["car", "mail", "head", "tail"])
    p.add_argument("--livery", default="meridian", choices=sorted(LIVERIES))
    p.add_argument("--speed", type=float, default=500.0)
    p.add_argument("--grade", default="flagship", choices=sorted(GRADES))
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--supersample", type=int, default=4)
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    for (row, col), direction in sorted(layout.VEHICLE_PLAN.items()):
        iso.setup(supersample=args.supersample, samples=args.samples)
        build_body(layout.VEHICLE_HEADING[direction], args.role,
                   args.livery, args.speed, args.grade)
        iso.render_to(os.path.join(args.out, f"cell_{row}_{col}.png"))
        print(f"[maglev] rendered {args.livery}-{args.role} "
              f"{direction} -> {row}.{col}")


if __name__ == "__main__":
    main()
