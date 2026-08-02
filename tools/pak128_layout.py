"""Sheet layout shared by the 2D and Blender renderers.

Standard library only, on purpose: Blender's bundled Python has no Pillow, so
this is the one module both pipelines can import. It answers "what goes in cell
row.col", nothing else — each renderer builds its own geometry from the spec.

The layout mirrors pak128's `rail_400_tracks.dat` slot for slot, so the maglev
`.dat` files address the same cells.
"""

from __future__ import annotations

CELL = 128
COLS, ROWS = 8, 11
WINTER_ROW_OFFSET = 5

# Simutrans reads this colour as transparent (SPECIAL_TRANSPARENT in the game's
# descriptor/image.h).
KEY = (231, 255, 255)

# Centre of a flat tile within its cell, measured off pak128's rail sheet.
CX, CY = 63.5, 96.0

# Connection bitmask, matching ribi_t in the game.
N, E, S, W = 1, 2, 4, 8

# Screen projection per tile shape: y = y0 + p*a + q*b, x = CX + 32*(a + b),
# where a runs towards the N edge and b towards the E edge, both in [-1, 1].
# The ramps raise two adjacent corners by pak128's 16px height step.
SHAPES = {
    "flat": (-16.0, 16.0, 96.0),
    "up_n": (-8.0, 16.0, 88.0),   # left + bottom corners raised
    "up_w": (-16.0, 8.0, 88.0),   # right + bottom corners raised
    "up_e": (-16.0, 24.0, 88.0),  # top + left corners raised
    "up_s": (-24.0, 16.0, 88.0),  # top + right corners raised
}

# One unit of a or b is this many screen pixels, on every shape.
UNIT_PX = 35.77708763999664


def unproject(x, y, shape="flat"):
    """Screen pixel -> ground coordinates (a, b) on that tile's plane.

    Works on scalars or numpy arrays.
    """
    p, q, y0 = SHAPES[shape]
    xu = (x - CX) / 32.0     # equals a + b
    a = ((y - y0) - q * xu) / (p - q)
    return a, xu - a


def quarter_test(corner, a, b):
    """Quarter-tile apron used by the corner/diagonal images."""
    return {"ne": a + b >= 0, "sw": a + b <= 0,
            "nw": a - b >= 0, "se": a - b <= 0}[corner]


def _plan():
    """cell -> spec. Spec is one of:

        {"ribi": mask, "variant": 0|1|2, "shape": name}   a normal way tile
        {"corner": "ne"|..., "quarter": bool}             a corner/diagonal tile
    """
    plan = {}
    for cell, ribi in {
        (1, 0): 0,
        (1, 1): N, (1, 2): S, (1, 3): E, (1, 4): W,
        (1, 5): N | S, (1, 6): E | W, (1, 7): N | S | E,
        (2, 0): N | S | W, (2, 1): N | E | W, (2, 2): S | E | W,
        (2, 3): N | S | E | W,
    }.items():
        plan[cell] = {"ribi": ribi, "variant": 0, "shape": "flat"}

    # Switch variants: same connections, different through route.
    for variant, cells in ((1, {(2, 4): N | S | E, (2, 5): N | S | W,
                                (2, 6): N | E | W, (2, 7): S | E | W,
                                (3, 0): N | S | E | W}),
                           (2, {(3, 1): N | S | E, (3, 2): N | S | W,
                                (3, 3): N | E | W, (3, 4): S | E | W,
                                (3, 5): N | S | E | W})):
        for cell, ribi in cells.items():
            plan[cell] = {"ribi": ribi, "variant": variant, "shape": "flat"}

    # Corner pieces. pak128 ships a full-tile and a quarter-tile version of
    # each; its .dat references the quarter one, so we provide the same pair.
    for cell, corner, quarter in [((3, 6), "ne", False), ((3, 7), "ne", True),
                                  ((4, 0), "se", False), ((4, 1), "se", True),
                                  ((4, 2), "nw", False), ((4, 3), "nw", True),
                                  ((4, 4), "sw", False), ((4, 5), "sw", True)]:
        plan[cell] = {"corner": corner, "quarter": quarter, "shape": "flat"}

    # Ramps, in way_writer's ImageUp order: 3=n, 6=w, 9=e, 12=s. The ramp
    # gradient runs along the axis whose two corners were raised.
    for cell, shape, ribi in [((4, 6), "up_n", N | S), ((4, 7), "up_w", E | W),
                              ((5, 0), "up_e", E | W), ((5, 1), "up_s", N | S)]:
        plan[cell] = {"ribi": ribi, "variant": 0, "shape": shape}

    return plan


CELL_PLAN = _plan()


def tile_shape(spec):
    return spec.get("shape", "flat")


# --------------------------------------------------------------------------
# Enclosed (tube) way sheet
#
# A tube tier needs two full ribi sets: the back image carries the apron, the
# guideway beam and the far half of the tube; the front image carries the near
# half, which Simutrans draws *after* vehicles so the pod shows through the
# glass. `way_writer.cc` reads those as `frontimage[<ribi>][<season>]`,
# `frontimageup[...]` and `frontdiagonal[...]`, exactly parallel to the back
# keys, so the sheet is just the ordinary 5-row block repeated four times.
# --------------------------------------------------------------------------

TUBE_ROWS = 21

TUBE_ROW_OFFSET = {
    ("back", "summer"): 0,
    ("front", "summer"): 5,
    ("back", "winter"): 10,
    ("front", "winter"): 15,
}


def tube_row(base_row, part, season):
    """Sheet row for a cell of the tube sheet. `base_row` is the 1..5 row the
    ordinary track plan uses."""
    return base_row + TUBE_ROW_OFFSET[(part, season)]


# --------------------------------------------------------------------------
# Station sheet
#
# A stop is a building drawn over the way, not a way tile: the guideway keeps
# being drawn underneath, so the station artwork is platforms only.
#
# Simutrans splits a building into a back image drawn before vehicles and a
# front image drawn after, which is what lets the near platform stand in front
# of a train. pak128's own stops put both platforms in the back image and
# repeat the near one in the front image; this follows that.
#
# Layout 0 is a way running N/S, layout 1 E/W — measured off pak128's
# opentrainstop by fitting the principal axis of its front images.
# --------------------------------------------------------------------------

STATION_COLS, STATION_ROWS = 6, 2

STATION_PLAN = {
    (1, 0): {"layout": 0, "part": "back"},
    (1, 1): {"layout": 1, "part": "back"},
    (1, 2): {"layout": 0, "part": "front"},
    (1, 3): {"layout": 1, "part": "front"},
}
STATION_ICON_CELL = (1, 4)
STATION_CURSOR_CELL = (1, 5)


# --------------------------------------------------------------------------
# Vehicle sheet: 8 columns, the eight travel directions, in the cell order the
# maglev vehicle .dat already uses.
#
# Compass directions map to the same world axes as the way: N is +Y (screen
# up-right), E is +X (down-right). So a vehicle heading "ne" travels towards
# both, which comes out as straight right on screen.
# --------------------------------------------------------------------------

VEHICLE_COLS, VEHICLE_ROWS = 8, 2

VEHICLE_PLAN = {
    (1, 0): "w", (1, 1): "nw", (1, 2): "n", (1, 3): "ne",
    (1, 4): "e", (1, 5): "se", (1, 6): "s", (1, 7): "sw",
}

_R = 0.70710678
VEHICLE_HEADING = {
    "n": (0.0, 1.0), "s": (0.0, -1.0), "e": (1.0, 0.0), "w": (-1.0, 0.0),
    "ne": (_R, _R), "nw": (-_R, _R), "se": (_R, -_R), "sw": (-_R, -_R),
}

# direction -> the cell holding that view
VEHICLE_CELL = {direction: cell for cell, direction in VEHICLE_PLAN.items()}

OPPOSITE_DIR = {"n": "s", "s": "n", "e": "w", "w": "e",
                "ne": "sw", "sw": "ne", "nw": "se", "se": "nw"}

# Which way connections a direction of travel needs. Travelling "ne" leaves the
# tile towards both N and E, so the way must offer both.
DIRECTION_BITS = {"n": N, "s": S, "e": E, "w": W,
                  "ne": N | E, "nw": N | W, "se": S | E, "sw": S | W}


def way_allows(ribi, direction):
    """Can a vehicle travel `direction` on a way with this connection mask?"""
    bits = DIRECTION_BITS[direction]
    return (ribi & bits) == bits


def vehicle_cell(direction, reversed_nose=False):
    """Sheet cell for a vehicle travelling `direction`.

    `reversed_nose` is for a tail car, whose artwork is the head sheet with
    every direction swapped — so a tail heading east draws the head's westward
    view and its nose points back down the train.
    """
    return VEHICLE_CELL[OPPOSITE_DIR[direction] if reversed_nose else direction]


def station_axes(layout):
    """(track axis, outward perpendicular towards the viewer) in world axes.

    The near platform is the one on the perpendicular that points down the
    screen: world +X goes right and down, world +Y right and up.
    """
    return ((0.0, 1.0), (1.0, 0.0)) if layout == 0 else ((1.0, 0.0), (0.0, -1.0))


def apron_corner(spec):
    """Which quarter the apron covers, or None for a full diamond."""
    return spec["corner"] if spec.get("quarter") else None
