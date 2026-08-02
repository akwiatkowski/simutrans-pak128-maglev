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


def stations(variant: str, nose_len: float = None):
    """Positions along the body where a cross-section is placed."""
    length = nose_len or NOSE_LEN
    out = {-HALF_LEN, 0.0, HALF_LEN}
    for i in range(9):                              # dense through the tapers
        out.add(-HALF_LEN + (HALF_LEN - NOSE_START) * i / 8)
    if variant == "head":
        for i in range(15):                         # denser still up the nose
            out.add(HALF_LEN - length + length * i / 14)
    else:
        for i in range(9):
            out.add(HALF_LEN - (HALF_LEN - NOSE_START) * i / 8)
    return sorted(round(u, 4) for u in out)


def build_doors(forward, across, up, count, mail, material, win_lo, win_hi):
    """Vertical door panels breaking the window band.

    Door *count* is the readable form of dwell time: a standard is a commuter
    set with three doors a side and a 700ms stop, a flagship has one and takes
    1100ms. A mail van gets a single wide loading door and no windows at all —
    which is what tells the two apart at 50x25px, far more than colour.
    """
    if mail:
        spots, width = [0.0], MAIL_DOOR_WIDTH
        lo, hi = DOOR_LO, win_hi + 0.10
    else:
        width, lo, hi = DOOR_WIDTH, DOOR_LO, DOOR_HI
        span = BODY_LENGTH * 0.30
        spots = ([0.0] if count == 1
                 else [(-1) ** i * span * (0.5 + i // 2) for i in range(count)][:count])
        if count == 3:
            spots = [-span, 0.0, span]
        elif count == 2:
            spots = [-span * 0.7, span * 0.7]
    for side in (-1.0, 1.0):
        for k, u in enumerate(spots):
            corners = [(u - width / 2, lo), (u + width / 2, lo),
                       (u + width / 2, hi), (u - width / 2, hi)]
            verts = []
            for depth in (BODY_HALF - 0.04, BODY_HALF + DOOR_PROUD):
                for du, dz in corners:
                    verts.append(forward * iso.m(du)
                                 + across * iso.m(side * depth)
                                 + up * iso.m(dz))
            faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4],
                     [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
            iso.new_mesh(f"door{side:+.0f}_{k}", verts, faces, material)


def build_body(heading, variant: str = "middle", livery: str = "meridian",
               mail: bool = False, speed: float = 500.0,
               grade: str = "flagship") -> None:
    """Loft the cross-section down the body and cap both ends.

    `mail` blanks the window band to body colour — no windows is what reads as
    a mail van at 50x25px, far more than any change of hue would.
    """
    forward = Vector((heading[0], heading[1], 0.0))
    across = Vector((-heading[1], heading[0], 0.0))
    up = Vector((0.0, 0.0, 1.0))

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
    us = stations(variant, prop["nose"])

    verts, faces, face_materials = [], [], []
    for u in us:
        if variant == "head" and u > 0.0:
            width, height_factor = nose(u, prop["nose"])
        else:
            width, height_factor = chamfer(u)
        for v, w, _ in section:
            if w <= FLOOR:
                # Skirts and the guideway channel never move: the body has to
                # keep wrapping the beam from end to end.
                height, across_scale = w, 1.0
            else:
                height = FLOOR + (w - FLOOR) * height_factor
                across_scale = width
            verts.append(forward * iso.m(u) + across * iso.m(v * across_scale)
                         + up * iso.m(height))

    for ring in range(len(us) - 1):
        base, nxt = ring * n, (ring + 1) * n
        for i in range(n):
            j = (i + 1) % n
            faces.append([base + i, base + j, nxt + j, nxt + i])
            face_materials.append(section[i][2])

    # The head's front cap is glazed: at 128px a dark tip is what reads as a
    # windscreen and tells you which way the train is pointing.
    nose_cap = WINDOW if variant == "head" else BODY
    for ring, order, material in ((0, list(range(n - 1, -1, -1)), BODY),
                                  (len(us) - 1, list(range(n)), nose_cap)):
        faces.append([ring * n + i for i in order])
        face_materials.append(material)

    obj = iso.new_mesh("body", verts, faces, materials, bevel=0.0)
    for poly, mat in zip(obj.data.polygons, face_materials):
        poly.material_index = mat

    # Doors only on trailers; a head car is mostly nose and has no flank left.
    if variant != "head":
        door_mat = iso.make_material(
            "door", pal["window"] if not mail else pal["skirt"],
            roughness=0.35, metallic=0.25)
        build_doors(forward, across, up, prop["doors"], mail, door_mat,
                    prop["win_lo"], prop["win_hi"])


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--variant", default="middle", choices=["middle", "head"])
    p.add_argument("--livery", default="meridian", choices=sorted(LIVERIES))
    p.add_argument("--mail", action="store_true")
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
        build_body(layout.VEHICLE_HEADING[direction], args.variant,
                   args.livery, args.mail, args.speed, args.grade)
        iso.render_to(os.path.join(args.out, f"cell_{row}_{col}.png"))
        tag = f"{args.livery}-{args.variant}" + ("-mail" if args.mail else "")
        print(f"[maglev] rendered {tag} {direction} -> {row}.{col}")


if __name__ == "__main__":
    main()
