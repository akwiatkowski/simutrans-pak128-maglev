"""Build and render the maglev tunnel portals in Blender.

Three portal classes matching the crossing ladder (500 / 1000 / 4000). A
tunnel is only its portals — the bore is invisible — so each class is a
headwall with an opening shaped like what travels through it: the 500 a
rectangular precast frame sized to the girder-and-pod envelope, the tube
classes a circular collar the glazed tube socket into, with the light cove
marker carried through the opening so a tube line's glow runs right into
the hill.

Simutrans draws the FRONT image after vehicles and the BACK image before
them (pak128 convention, `rail_060_tunnel.dat`): the front is therefore the
whole headwall with the bore left transparent — a pod slides in and is
swallowed — and the back is the dark bore interior seen through the hole.

Sheet layout (packed by `tools/assemble_sheet.py --sheet tunnel`):

    row 0  summer front: n, w, s, e; icon (col 4)
    row 1  summer back:  n, w, s, e; cursor (col 4)
    rows 2-3 the same in winter

    blender --background --python tools/blender/build_maglev_tunnel.py -- \
        --out build/tunnel500 --class 500 --samples 96
"""

from __future__ import annotations

import argparse
import math
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
DIR = {"n": Vector((0.0, 1.0, 0.0)), "s": Vector((0.0, -1.0, 0.0)),
       "e": Vector((1.0, 0.0, 0.0)), "w": Vector((-1.0, 0.0, 0.0))}
COL = {"n": 0, "w": 1, "s": 2, "e": 3}

# Portal geometry, metres. The headwall plane sits towards the uphill edge
# of the entrance tile; wings run from its sides back to the tile edge.
PORTAL_AT = 0.22          # headwall plane, in tile units from the centre
HEAD_HALF = 3.6           # headwall half width
HEAD_TOP = {500: 4.4, 1000: 4.9, 4000: 4.9}   # wall height above grade
FRAME = 0.55              # visible frame width around the opening
WING_LEN = 0.28           # wings, in tile units towards the hill
BORE_DEPTH = 3.5          # metres of dark interior behind the wall

# Rectangular opening for the open class: clears the pod envelope
# (body 3.9m wide, roof ~3.2m) riding the 0.85m girder.
RECT_HALF = 2.30
RECT_TOP = 3.75
RECT_BOT = 0.10

CLASSES = {500: dict(round=False), 1000: dict(round=True, tier=1000),
           4000: dict(round=True, tier=4000)}


def concrete(season):
    pal = track.PALETTE[season]
    return iso.make_material("portal", tuple(c * 0.90 for c in pal["apron"]),
                             roughness=0.85, noise=0.20,
                             seams=0.15, seam_period_m=2.6)


def bore_mat():
    return iso.make_material("bore", (0.012, 0.013, 0.016), roughness=1.0)


def opening_ring(cls, n=16):
    """Points of the bore outline in (across, height) metres."""
    if not cls["round"]:
        return [(-RECT_HALF, RECT_BOT), (RECT_HALF, RECT_BOT),
                (RECT_HALF, RECT_TOP), (-RECT_HALF, RECT_TOP)]
    # The tube's own superellipse, with a small collar margin.
    pts = []
    w = track.TUBE_HALF_WIDTH + 0.18
    h = track.TUBE_HEIGHT + 0.18
    for i in range(n):
        t = math.pi * i / (n - 1)
        pts.append((-w * math.cos(t),
                    0.02 + h * (math.sin(t) ** (2.0 / 2.6))))
    return pts


def build_wall_with_hole(centre, d, right, ring, half_w, top, material):
    """The headwall: a quad strip between the outer rectangle and the bore
    outline, leaving the opening itself transparent."""
    # Simple robust construction: frame slabs around the ring's bounding
    # box plus a reveal band hugging the ring keeps the geometry watertight
    # without boolean cuts.
    axs = [p[0] for p in ring]
    hts = [p[1] for p in ring]
    lo_x, hi_x = min(axs), max(axs)
    hi_h = max(hts)
    thick = 0.35
    verts, faces = [], []

    def quad(x0, x1, h0, h1):
        base = len(verts)
        for dd in (0.0, thick):
            for (x, h) in ((x0, h0), (x1, h0), (x1, h1), (x0, h1)):
                verts.append(centre + right * iso.m(x) + UP * iso.m(h)
                             - d * iso.m(dd))
        faces.extend([[base, base + 1, base + 2, base + 3],
                      [base + 4, base + 7, base + 6, base + 5],
                      [base, base + 3, base + 7, base + 4],
                      [base + 1, base + 5, base + 6, base + 2],
                      [base + 3, base + 2, base + 6, base + 7],
                      [base, base + 4, base + 5, base + 1]])

    quad(-half_w, lo_x, 0.0, top)                     # left pier
    quad(hi_x, half_w, 0.0, top)                      # right pier
    quad(lo_x, hi_x, hi_h, top)                       # lintel over the bore
    obj = iso.new_mesh("headwall", verts, faces, material)

    # The frame that actually hugs the opening: a band following the ring.
    band_verts, band_faces = [], []
    for (a, h) in ring:
        band_verts.append(centre + right * iso.m(a) + UP * iso.m(h))
        band_verts.append(centre + right * iso.m(a * 1.0) + UP * iso.m(h)
                          - d * iso.m(thick))
    for i in range(len(ring) - 1):
        b = 2 * i
        band_faces.append([b, b + 2, b + 3, b + 1])
    iso.new_mesh("reveal", band_verts, band_faces, material)
    return obj


def build_portal(cls, season, direction, part):
    d = DIR[direction]
    right = d.cross(UP).normalized()
    centre = Vector((d.x * PORTAL_AT, d.y * PORTAL_AT, 0.0))
    ring = opening_ring(cls)
    top = HEAD_TOP[4000 if cls.get("round") and cls.get("tier") == 4000
                   else (1000 if cls.get("round") else 500)]

    if part == "front":
        build_wall_with_hole(centre, d, right, ring, HEAD_HALF, top,
                             concrete(season))
        # Wings angling back from the wall edges into the hillside.
        for s in (-1.0, 1.0):
            a = centre + right * iso.m(s * HEAD_HALF)
            b = centre + right * iso.m(s * (HEAD_HALF + 0.9)) + d * WING_LEN
            wing = [(0.0, 0.0), (0.0, iso.m(top * 0.82)),
                    (iso.m(0.35), iso.m(top * 0.82)), (iso.m(0.35), 0.0)]
            iso.extrude_profile(f"wing{s:+.0f}", wing, a, b, right, UP,
                                concrete(season), bevel=iso.m(0.03))
        if cls["round"]:
            # The cove light runs through the opening: the collar carries a
            # short marker stub either side, so the glow enters the hill.
            w = track.TUBE_HALF_WIDTH
            cove = iso.make_flag_emission("cove")
            for s in (-1.0, 1.0):
                strip = [(iso.m(s * (w - track.COVE_PROUD)), iso.m(track.COVE_LO)),
                         (iso.m(s * (w + track.COVE_PROUD)), iso.m(track.COVE_LO)),
                         (iso.m(s * (w + track.COVE_PROUD)), iso.m(track.COVE_HI)),
                         (iso.m(s * (w - track.COVE_PROUD)), iso.m(track.COVE_HI))]
                lit = iso.extrude_profile(f"cove{s:+.0f}", strip,
                                          centre - d * iso.m(0.05),
                                          centre + d * iso.m(0.6),
                                          right, UP, cove,
                                          bevel=0.0, caps=False)
                iso.no_shadow(lit)
    else:
        # Back: the dark bore interior seen through the opening.
        m = len(ring)
        verts, faces = [], []
        for depth in (0.0, BORE_DEPTH):
            for (a, h) in ring:
                verts.append(centre + right * iso.m(a) + UP * iso.m(h)
                             + d * iso.m(depth + 0.05))
        for i in range(m - 1):
            faces.append([i, i + 1, m + i + 1, m + i])
        faces.append(list(range(2 * m - 1, m - 1, -1)))    # end cap, dark
        iso.new_mesh("bore", verts, faces, bore_mat())


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--class", dest="cls", type=int, required=True,
                   choices=sorted(CLASSES))
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--supersample", type=int, default=4)
    args = p.parse_args(argv)

    cls = CLASSES[args.cls]
    os.makedirs(args.out, exist_ok=True)
    for season_off, season in ((0, "summer"), (2, "winter")):
        for part_off, part in ((0, "front"), (1, "back")):
            for direction, col in COL.items():
                iso.setup(args.supersample, args.samples, "flat")
                build_portal(cls, season, direction, part)
                row = season_off + part_off
                iso.render_to(os.path.join(args.out,
                                           f"cell_{row}_{col}.png"))
                print(f"[maglev] rendered tunnel{args.cls} {part} "
                      f"{direction} {season} -> {row}.{col}", flush=True)


if __name__ == "__main__":
    main()
