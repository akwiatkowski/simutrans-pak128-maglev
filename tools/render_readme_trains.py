#!/usr/bin/env python3
"""Showcase image + economics paragraph for every trainset in the roster.

For each entry in `gen_vehicle_roster.ROSTER` this renders a sample train —
head, four passenger cars, a mail van and the tail, composited onto the
guideway tier the set is built for — and computes the numbers a player
actually plans a line around:

    * the most efficient distance between stops,
    * predicted income for one full train over one trip at that spacing,
    * predicted income per game year of constant back-and-forth travel.

The whole block, one paragraph + screenshot per train, is then injected into
`src/maglev/README.md` between the `<!-- trains:begin -->` / `<!-- trains:end -->`
markers, so re-running the script after a roster change refreshes the README.

    python3 tools/render_readme_trains.py            # images + README section
    python3 tools/render_readme_trains.py --table    # just print the numbers

Where every constant comes from
-------------------------------
The revenue and physics model is ported from the Simutrans *standard* engine
(the `../simutrans` checkout) rather than guessed:

    revenue   simware.cc  ware_t::calc_revenue():
                  per unit and per tile of distance, in 1/100 credit /3000:
                  value * max(basefactor, 1000 + kmh_base * speed_bonus)
                  kmh_base = 100*v/ref - 100  (integer division)
              vehicle.cc  vehicle_t::calc_revenue(): summed over the cargo,
                  multiplied by tiles travelled, divided by 3000 -> cents.
    ref speed vehikelbauer.cc get_speedbonus(): pak128's speedbonus.tab has
                  **no maglev line**, so the reference falls back to the mean
                  top speed of all maglev vehicles with power available that
                  year — i.e. this very roster defines its own baseline. A
                  flagship earns its bonus by beating the fleet average.
    fares     parsed from pak128's factories.all.pak GOOD nodes:
                  Passagiere value 14, speed_bonus 18, 85 kg/unit
                  Post       value 16, speed_bonus 15, 50 kg/unit
              basefactor 125 (settings.cc default; pak128 does not override),
              price multiplier 1000 = neutral (non-beginner game).
    physics   simconvoi.cc res_power()/calc_acceleration(), integer-exact:
                  res = P - (s*(fw*s/3125 + 1)/2048 + tw*64/1000)
                  with P = sum(power_kW * gear*64/100), s internal speed
                  (kmh*64/5, simunits.h), weights in kg, friction factor 1 on
                  straight flat track (vehicle.cc calc_friction).
    braking   simconvoi.cc brake_speed_countdown: the game only brakes over
                  the last 4 tiles, staged to 200/100/50/25 km/h.
    distance  simunits.h: YARDS_PER_TILE = 2^20; tiles = speed*ticks / 2^20.
    time      pak128 simuconf.tab bits_per_month=19 -> month = 2^19 ticks,
                  year = 12 months. loading_time in the dat is game-ms for a
                  full load (simconvoi.cc hat_gehalten); a stop that swaps a
                  full complement costs one unload plus one load.

Distances are given in **tiles** — standard Simutrans defines no metre size
for a tile, so tiles and game-years are the only honest units.

Assumptions (documented, not hidden): the line is straight and flat (no curve
or slope friction), every departure leaves with a full complement in both
directions, and signals never hold the train. Real yields will be lower;
relative comparisons between sets remain valid because all sets share the
assumptions.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import gen_vehicle_roster as roster                  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGES = ROOT / "src/maglev/images"
OUT_DIR = IMAGES / "readme"
README = ROOT / "src/maglev/README.md"

# --------------------------------------------------------------------------
# Game constants — sources in the module docstring.
# --------------------------------------------------------------------------

PAX_VALUE, PAX_BONUS, PAX_KG = 14, 18, 85     # pak128 GOOD "Passagiere"
POST_VALUE, POST_BONUS, POST_KG = 16, 15, 50  # pak128 GOOD "Post"
BONUS_BASEFACTOR = 125                        # settings.cc default floor

TICKS_PER_MONTH = 1 << 19                     # pak128 bits_per_month = 19
TICKS_PER_YEAR = 12 * TICKS_PER_MONTH
YARDS_PER_TILE = 1 << 20                      # simunits.h (shifts 8 + 12)
BRAKE_STAGES = (200, 100, 50, 25)             # km/h caps on the last 4 tiles
FRICTION = 1                                  # straight, flat guideway

# The guideway ladder, from the compiled .dat files (intro_year, topspeed).
WAY_LADDER = [(2000, 300), (2014, 500), (2032, 700),
              (2080, 1000), (2100, 2000), (2165, 4000)]

# The showcase and economics formation: head + 4 passenger cars + mail + tail.
# Seven 12-carunit vehicles = 5.25 tiles, which fits a six-tile platform.
N_CARS = 4


def kmh_to_speed(kmh: float) -> int:
    """km/h -> internal speed (yards per tick), simunits.h."""
    return int(kmh) * 64 // 5


def gear_internal(dat_gear: int = 260) -> int:
    """dat gear (percent*100) -> internal gear, makeobj stores gear*64/100."""
    return dat_gear * 64 // 100


# --------------------------------------------------------------------------
# Roster access
# --------------------------------------------------------------------------

def sets():
    """All roster entries with their derived spec, in intro order."""
    entries = []
    for company, speed, variant, intro in roster.ROSTER:
        s = roster.spec(company, speed, variant)
        entries.append(dict(company=company, speed=speed, variant=variant,
                            intro=intro, retire=intro + s["life"], spec=s,
                            tag=f"{roster.COMPANY_LIVERY[company]}{speed}",
                            name=f"{company} {speed}"))
    return sorted(entries, key=lambda e: e["intro"])


def ref_speed(year: int) -> int:
    """Speed-bonus reference: mean top speed of powered maglev stock available
    in `year` (vehikelbauer.cc fallback — only heads carry power, one per
    set, so this is the mean over available sets)."""
    avail = [e["speed"] for e in sets() if e["intro"] <= year < e["retire"]]
    return sum(avail) // len(avail) if avail else 300


def best_way(year: int) -> int:
    """Fastest guideway tier open in `year`."""
    speeds = [s for y, s in WAY_LADDER if y <= year]
    return max(speeds) if speeds else WAY_LADDER[0][1]


def home_way(set_speed: int) -> int:
    """The tier a set is built for: the slowest guideway that does not cap it
    (the fastest tier for the eternally-capped vacuum stock)."""
    for _, s in WAY_LADDER:
        if s >= set_speed:
            return s
    return WAY_LADDER[-1][1]


def way_year(way_speed: int) -> int:
    return next(y for y, s in WAY_LADDER if s == way_speed)


# --------------------------------------------------------------------------
# Formation: aggregate weight, power, capacity, costs
# --------------------------------------------------------------------------

def formation(entry):
    s = entry["spec"]
    pax = s["head_pax"] + N_CARS * s["car_pax"] + s["head_pax"]   # head + cars + tail
    mail = s["mail"]
    empty_kg = round((s["head_weight"] + N_CARS * s["car_weight"]
                      + s["car_weight"] * 0.95            # mail van
                      + s["head_weight"] * 0.82) * 1000)  # tail
    cargo_kg = pax * PAX_KG + mail * POST_KG
    run = (s["head_run"] + N_CARS * s["car_run"]
           + round(s["car_run"] * 0.9) + round(s["head_run"] * 0.6))
    fixed = (s["head_fixed"] + N_CARS * s["car_fixed"]
             + round(s["car_fixed"] * 0.9) + round(s["head_fixed"] * 0.6))
    price = (s["head_cost"] + N_CARS * s["car_cost"]
             + round(s["car_cost"] * 0.88) + round(s["head_cost"] * 0.55))
    return dict(pax=pax, mail=mail,
                weight_kg=empty_kg + cargo_kg,
                power_gear=s["power"] * gear_internal(),
                run_cents=run, fixed_cents=fixed, price_cents=price,
                load_ms=s["load"])


# --------------------------------------------------------------------------
# Physics: integer-exact port of convoi_t::calc_acceleration
# --------------------------------------------------------------------------

def accel_profile(power_gear: int, weight_kg: int, cap_kmh: int,
                  dt: int = 16, limit_ticks: int = 20 * 60 * 1000):
    """Simulate a standing start on straight flat track.

    Returns (ticks, yards) sampled every step until the convoy reaches its
    speed cap — the same integer arithmetic the game runs, including the
    fractional-speed carry (`previous_delta_v`).
    """
    cap = kmh_to_speed(cap_kmh)
    fw = FRICTION * weight_kg
    s = 0
    carry = 0
    t = 0
    yards = 0
    path = [(0, 0, 0)]
    while s < cap and t < limit_ticks:
        res = power_gear - ((s * ((fw * s) // 3125 + 1)) // 2048
                            + (weight_kg * 64) // 1000)
        dv = (res * dt * 1000) // weight_kg + carry
        carry = dv & 0xFFF
        s = max(cap >> 4, s + (dv >> 12))
        s = min(s, cap)
        t += dt
        yards += s * dt
        path.append((t, yards, s))
    return path


def brake_tail_ticks(cap_kmh: int) -> int:
    """The game brakes only across the last four tiles, staged down through
    BRAKE_STAGES — time to cover those four tiles at the staged caps."""
    ticks = 0
    for stage in BRAKE_STAGES:
        v = kmh_to_speed(min(cap_kmh, stage))
        ticks += YARDS_PER_TILE // max(v, 1)
    return ticks


def trip_ticks(path, cap_kmh: int, dist_tiles: int, load_ms: int) -> int:
    """One stop-to-stop hop plus the dwell to swap a full complement."""
    run_yards = max(0, (dist_tiles - len(BRAKE_STAGES)) * YARDS_PER_TILE)
    # accelerate...
    t_acc, y_acc, v = path[-1]
    if y_acc > run_yards:                      # short hop: never reaches cap
        t_acc, y_acc, v = next(p for p in path if p[1] >= run_yards)
    # ...cruise the rest...
    cruise = (run_yards - y_acc) // max(v, 1)
    # ...brake into the platform, then swap the load (unload + load).
    return t_acc + cruise + brake_tail_ticks(cap_kmh) + 2 * load_ms


# --------------------------------------------------------------------------
# Revenue: integer-exact port of ware_t::calc_revenue
# --------------------------------------------------------------------------

def bonus_factor(v_kmh: int, ref_kmh: int, speed_bonus: int) -> int:
    kmh_base = (100 * v_kmh) // ref_kmh - 100
    return max(BONUS_BASEFACTOR, 1000 + kmh_base * speed_bonus)


def revenue_per_tile_cents(entry, v_kmh: int, year: int) -> float:
    """Full train, both goods, in 1/100 credits per tile of distance."""
    f = formation(entry)
    ref = ref_speed(year)
    pax = f["pax"] * PAX_VALUE * bonus_factor(v_kmh, ref, PAX_BONUS)
    post = f["mail"] * POST_VALUE * bonus_factor(v_kmh, ref, POST_BONUS)
    return (pax + post) / 3000.0


def economics(entry):
    """The three numbers the README quotes, plus context for the paragraph.

    Evaluated in the set's element: the year its home guideway exists (or its
    intro, whichever is later, clamped to its sales life). A flagship spends
    its first years capped on the previous tier while singlehandedly raising
    the fleet average it is paid against — that story goes in the prose, the
    headline numbers describe the set doing the job it was built for.
    """
    year = min(max(entry["intro"], way_year(home_way(entry["speed"]))),
               entry["retire"] - 1)
    f = formation(entry)
    v_line = min(entry["speed"], best_way(year))

    rev_tile = revenue_per_tile_cents(entry, v_line, year) / 100.0   # credits
    run_tile = f["run_cents"] / 100.0
    margin = rev_tile - run_tile
    fixed_month = f["fixed_cents"] / 100.0

    path = accel_profile(f["power_gear"], f["weight_kg"], v_line)
    windup_tiles = path[-1][1] / YARDS_PER_TILE
    v_int = kmh_to_speed(v_line)

    # Yearly net income as a function of stop spacing: the per-tile margin is
    # constant, so yield/year climbs with spacing purely because more of the
    # cycle is spent at cruise. It approaches an asymptote; the "most
    # efficient" spacing is where the curve reaches 95% of it — closer stops
    # burn yield on wind-up and dwell, further ones buy almost nothing.
    def yearly(d_tiles: int) -> float:
        cycle = trip_ticks(path, v_line, d_tiles, f["load_ms"])
        trips = TICKS_PER_YEAR / cycle
        return (margin * d_tiles) * trips - fixed_month * 12

    asymptote = margin * v_int * TICKS_PER_YEAR / YARDS_PER_TILE \
        - fixed_month * 12
    d_star = next((d for d in range(5, 4001)
                   if yearly(d) >= 0.95 * asymptote), 4000)
    net_year = yearly(d_star)
    cycle = trip_ticks(path, v_line, d_star, f["load_ms"])
    net_trip = margin * d_star - fixed_month * cycle / TICKS_PER_MONTH

    # Commuter yardstick: how much of the theoretical ceiling survives at a
    # 256-tile stop spacing. Bounded above by the engine's fixed four-tile
    # station crawl, which no amount of power can buy back.
    net_256 = yearly(256)
    pct_256 = 100.0 * net_256 / asymptote if asymptote > 0 else 0.0

    return dict(v_line=v_line, ref=ref_speed(year),
                rev_tile=rev_tile, run_tile=run_tile, margin=margin,
                windup_tiles=windup_tiles, d_star=d_star,
                net_256=net_256, pct_256=pct_256,
                net_trip=net_trip, net_year=net_year,
                trips_year=TICKS_PER_YEAR / cycle,
                price_cr=f["price_cents"] / 100.0,
                payback_years=(f["price_cents"] / 100.0) / net_year
                if net_year > 0 else float("inf"),
                pax=f["pax"], mail=f["mail"])


# --------------------------------------------------------------------------
# Showcase renderer
# --------------------------------------------------------------------------

KEY = (231, 255, 255)
CELL = 128
TILE_DX, TILE_DY = 64, 32          # screen step of one tile to the N
VEH_FRAC = 12 / 16                 # vehicle length in tiles (12 carunits)

# Sprite cells in every fleet sheet, row 1: w nw n ne e se s sw.
DIR_CELL = {"w": 0, "nw": 1, "n": 2, "ne": 3, "e": 4, "se": 5, "s": 6, "sw": 7}


def crop_cell(sheet: Image.Image, row: int, col: int) -> Image.Image:
    tile = sheet.crop((col * CELL, row * CELL, (col + 1) * CELL,
                       (row + 1) * CELL)).convert("RGBA")
    px = tile.load()
    for y in range(CELL):
        for x in range(CELL):
            if px[x, y][:3] == KEY:
                px[x, y] = (0, 0, 0, 0)
    return tile


def track_layers(way_speed: int):
    """(back tile, front tile or None) for a straight N-S run of the tier."""
    if way_speed <= 700:
        sheet = Image.open(IMAGES / f"maglev_track_{way_speed}.png")
        return crop_cell(sheet, 1, 5), None
    name = {1000: "maglev_tube.png", 2000: "maglev_tube2000.png",
            4000: "maglev_tube4000.png"}[way_speed]
    sheet = Image.open(IMAGES / name).convert("RGBA")
    # Tube sheets carry two ribi sets: back summer rows 0-4, front rows 5-9.
    back = sheet.crop((5 * CELL, 1 * CELL, 6 * CELL, 2 * CELL))
    front = sheet.crop((5 * CELL, 6 * CELL, 6 * CELL, 7 * CELL))
    return back, front


def render_showcase(entry, out_path: pathlib.Path, n_tiles: int = 8):
    """The sample train on its home guideway, heading N (up-right)."""
    tag = entry["tag"]
    way = home_way(entry["speed"])
    back, front = track_layers(way)

    wide = CELL + (n_tiles - 1) * TILE_DX
    high = CELL + (n_tiles - 1) * TILE_DY
    img = Image.new("RGBA", (wide, high), (0, 0, 0, 0))

    def tile_origin(k: float):
        return int(k * TILE_DX), int((n_tiles - 1 - k) * TILE_DY)

    for k in range(n_tiles):
        img.alpha_composite(back, tile_origin(k))

    # Vehicles: head first (north-most, drawn first = behind), then the rest
    # marching back toward the S corner, each 12/16 of a tile long. The tail
    # sheet is used with swapped directions, so a north-bound tail shows its
    # 's' cell — the nose facing back down the train.
    sheets = {part: Image.open(IMAGES / f"maglev_{part}_{tag}.png")
              for part in ("head", "car", "mail", "tail")}
    train = (["head"] + ["car"] * 2 + ["mail"] + ["car"] * (N_CARS - 2)
             + ["tail"])
    p = n_tiles - 1.55                      # head position, in tiles along N
    for i, part in enumerate(train):
        col = DIR_CELL["s"] if part == "tail" else DIR_CELL["n"]
        sprite = crop_cell(sheets[part], 1, col)
        x, y = tile_origin(p - i * VEH_FRAC)
        img.alpha_composite(sprite, (x, y))

    if front is not None:
        for k in range(n_tiles):
            img.alpha_composite(front, tile_origin(k))

    img = img.crop(img.getbbox())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


# --------------------------------------------------------------------------
# README section
# --------------------------------------------------------------------------

ROLE = {
    ("Meridian", "flagship"):
        "{name} is the speed leader of its generation",
    ("Aetheris", "flagship"):
        "{name} is vacuum-era stock, built for the enclosed tubes",
    ("Kestrel", "standard"):
        "{name} is the commuter workhorse of its generation",
    ("Volta", "value"):
        "{name} is the budget option of its generation",
}


def paragraph(entry, econ) -> str:
    name = entry["name"]
    way = home_way(entry["speed"])
    capped = econ["v_line"] < entry["speed"]
    lines = []

    role = ROLE[(entry["company"], entry["variant"])].format(name=name)
    lines.append(
        f"{role}: {entry['speed']} km/h, sold {entry['intro']}–"
        f"{entry['retire']}, {econ['pax']} passengers and {econ['mail']} bags "
        f"of mail in the showcase formation (head + {N_CARS} cars + mail van "
        f"+ tail, {econ['price_cr']:,.0f} cr).")

    if way_year(way) > entry["intro"]:
        cap_at_launch = min(entry["speed"], best_way(entry["intro"]))
        lines.append(
            f"At launch the {best_way(entry['intro'])} guideway caps it at "
            f"{cap_at_launch} km/h — while its own top speed drags the fleet "
            f"average (and everyone's fares) around — so it does not earn "
            f"properly until its {way} tier opens in {way_year(way)}; the "
            f"numbers below are from that era.")
    elif capped:
        lines.append(
            f"Even its home {way} guideway caps it at {econ['v_line']} km/h.")
    else:
        lines.append(
            f"It runs full speed on the {way} guideway of {way_year(way)}.")

    if econ["d_star"] >= 4000:
        spacing = ("Its most efficient stop spacing is off the chart — even "
                   "**4,000 tiles** between stops leaves it short of full "
                   "stride, so give it the longest trunk a map can hold")
    else:
        spacing = (f"which sets the most efficient stop spacing at "
                   f"≈**{econ['d_star']} tiles**: closer stops trade cruise "
                   f"for wind-up, further ones add almost nothing")
    lines.append(
        f"Against the {econ['ref']} km/h fleet average it earns "
        f"{econ['rev_tile']:.1f} cr per tile fully loaded and burns "
        f"{econ['run_tile']:.1f} cr per tile to move, so the margin is "
        f"{econ['margin']:.1f} cr per tile. From a standing start it needs "
        f"about {econ['windup_tiles']:.0f} tiles to wind up, {spacing}.")

    if econ["payback_years"] > (entry["retire"] - entry["intro"]):
        payback = (f"— it never quite repays its "
                   f"{econ['price_cr']:,.0f} cr before it retires; buy it to "
                   f"put maglev where nothing better goes, not to get rich")
    else:
        payback = (f"— the formation pays for itself in about "
                   f"{econ['payback_years']:.1f} years")
    lines.append(
        f"At that spacing a full train clears ≈**{econ['net_trip']:,.0f} cr "
        f"per trip** and, shuttling constantly "
        f"({econ['trips_year']:.0f} trips a game year), "
        f"≈**{econ['net_year']:,.0f} cr per year** {payback}.")

    if entry["variant"] in ("standard", "value"):
        if econ["pct_256"] >= 80:
            lines.append(
                f"It is built for commuter work: on 256-tile hops it still "
                f"banks ≈{econ['net_256']:,.0f} cr per year — "
                f"{econ['pct_256']:.0f}% of its ceiling, most of the rest "
                f"lost to the mandatory four-tile crawl into every platform.")
        else:
            lines.append(
                f"Commuter spacing is beneath it by this era: 256-tile hops "
                f"still pay ≈{econ['net_256']:,.0f} cr per year, but that is "
                f"only {econ['pct_256']:.0f}% of its ceiling — at these "
                f"speeds the four-tile platform crawl eats the hop, so keep "
                f"it on trunks.")

    return " ".join(lines)


def build_section() -> str:
    out = ["", "Generated by `tools/render_readme_trains.py` — the numbers "
           "are the Simutrans standard revenue and acceleration formulas run "
           "over the actual dat values (sources and assumptions in the "
           "script header). Distances are in tiles; income in credits.", ""]
    for entry in sets():
        econ = economics(entry)
        img = OUT_DIR / f"{entry['tag']}.png"
        render_showcase(entry, img)
        rel = img.relative_to(README.parent)
        out.append(f"#### {entry['name']}")
        out.append("")
        out.append(f"![{entry['name']}]({rel})")
        out.append("")
        out.append(paragraph(entry, econ))
        out.append("")
        print(f"  {entry['name']:<15} D*={econ['d_star']:>4} tiles  "
              f"trip={econ['net_trip']:>8,.0f} cr  "
              f"year={econ['net_year']:>11,.0f} cr")
    return "\n".join(out)


def inject(section: str) -> None:
    text = README.read_text()
    begin, end = "<!-- trains:begin -->", "<!-- trains:end -->"
    if begin not in text or end not in text:
        raise SystemExit(f"README is missing the {begin} / {end} markers")
    new = re.sub(re.escape(begin) + ".*?" + re.escape(end),
                 begin + "\n" + section + "\n" + end, text, flags=re.S)
    README.write_text(new)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", action="store_true",
                        help="print the economics, write nothing")
    args = parser.parse_args()

    if args.table:
        for entry in sets():
            e = economics(entry)
            print(f"{entry['name']:<15} intro {entry['intro']} "
                  f"line {e['v_line']:>4} km/h ref {e['ref']:>4} "
                  f"margin {e['margin']:>6.1f} cr/tile "
                  f"D* {e['d_star']:>4} trip {e['net_trip']:>9,.0f} "
                  f"year {e['net_year']:>12,.0f} payback {e['payback_years']:.1f}y")
        return

    section = build_section()
    inject(section)
    print(f"wrote {len(roster.ROSTER)} showcases -> {OUT_DIR}, README updated")


if __name__ == "__main__":
    main()
