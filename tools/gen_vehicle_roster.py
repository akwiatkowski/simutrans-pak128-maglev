#!/usr/bin/env python3
"""Generate the maglev vehicle roster as pak128 `.dat` files.

The roster is a ladder of trainsets from four manufacturers, spanning roughly
2000-2200. Everything derives from `ROSTER` plus the scaling rules below, so
rebalancing is one edit here rather than sixty-odd hand-maintained files.

    python3 tools/gen_vehicle_roster.py            # writes src/maglev/vehicles/
    python3 tools/gen_vehicle_roster.py --table    # print the roster, write nothing

The design
----------
Speed on a line is `min(vehicle, way)`, so vehicle and way speeds are
deliberately *staggered* — if they matched there would be no decision to make.
Two rules produce the stagger:

    standard  ~=  85% of the current way tier   (never maxes the track)
    flagship  ~=  the *next* way tier           (maxes it today, banks headroom)

A flagship therefore runs faster than a standard right now — it sits on the
track's cap, which the standard cannot reach — and jumps again for free when
the next way tier opens. That is what justifies its premium.

The two variants are opposite economic shapes, which matters because Simutrans
charges `runningcost` **per tile travelled** and `maintenance` **per month**
regardless of movement (see `convoi_t::add_running_cost`):

    flagship   expensive to buy, cheap per tile   -> long trunk routes
    standard   cheap to buy, costly per tile      -> short, dense routes

So the route picks the vehicle without any rule enforcing it: on a busy trunk
the flagship's lower per-tile cost repays its capital in years, on a short
feeder it never does. Standards get the higher power-to-weight instead, which
is what actually matters where stops are close together — below a break-even
stop spacing a standard is genuinely faster end to end despite the lower top
speed, because neither train ever reaches its ceiling.

Manufacturers
-------------
    Meridian   flagships; speed leader, lowest per-tile cost, expensive
    Kestrel    standards; acceleration, capacity, short dwell
    Volta      value; cheap to buy, poor per-tile economics, a class behind
    Aetheris   vacuum-era flagships, enters once tubes exist
"""

from __future__ import annotations

import argparse
import pathlib

# --------------------------------------------------------------------------
# Reference vehicle: the 300 km/h generation. Everything else scales off it.
# --------------------------------------------------------------------------

REF_SPEED = 300.0
REF_CAR_PAX = 60
REF_HEAD_PAX = 32
REF_MAIL = 50
REF_CAR_WEIGHT = 52.0
REF_HEAD_WEIGHT = 68.0
REF_POWER = 10_000          # kW, head only

# Cost & running-cost references are calibrated against pak128's own fastest
# rail stock (read straight out of vehicles.rail-engines / rail-psg+mail
# .pak): RVg Tigress 400km/h — engine run 494, wagon run 44, engine price
# 98.9M; RVg Thunder 2 370km/h — engine 304, wagon 55; ACE3/E320 320km/h —
# powered cars 207-512, trailers 130-330. pak128 passengers pay value=14 per
# unit-tile /3000 in cents, so a ~550-seat 400km/h set earns ~26 cr/tile at
# neutral speed bonus against ~13 cr/tile running cost — revenue ≈ 2x cost.
# The maglev ladder keeps a modest premium over the equivalent rail class;
# earlier constants (410/690 per car/head) were set by eye, priced every set
# 10-20x above rail and made every route run at a guaranteed loss.
REF_CAR_COST = 13_000_000
REF_HEAD_COST = 24_000_000
REF_CAR_RUN = 30
REF_HEAD_RUN = 240
REF_CAR_FIXED = 1_400
REF_HEAD_FIXED = 2_600

# Power rises as v^2, which keeps the *distance* needed to reach top speed
# proportional to speed. Holding acceleration itself constant would need v^3 —
# a 2360x jump from 300 to 4000 — which is absurd. Measured with the ported
# engine physics (tools/render_readme_trains.py) the ladder winds up in 6-15
# tiles — Transrapid-like, and quick enough that stop spacing is set by the
# dwell and fare bonus, not by acceleration.
POWER_EXP = 2.0

# Cost and running-cost scaling are dictated by how Simutrans standard prices
# transport: fares do NOT rise with era — passengers pay value=14 per
# unit-tile forever, adjusted only by the speed bonus *relative to the fleet
# average*, and this roster IS the maglev fleet average (pak128's
# speedbonus.tab has no maglev line, so the game averages our own heads).
# Since revenue per tile is roughly flat across generations, speed can only
# pay through throughput: more tiles per year, not more credits per tile.
#
# RUN_EXP = 0 therefore: engineering progress exactly cancels the speed tax,
# which is what pak128's own stock does (its 400 km/h wagons run *cheaper*
# per seat-tile than its 320 km/h ones: Tigress 44/62 seats vs ACE3 ~200-500
# per powered car). Anything above ~0.3 makes every post-2100 set run at a
# guaranteed loss at full load — verified by sweeping the whole roster
# against the ported revenue model in tools/render_readme_trains.py.
#
# COST_EXP = 0.95 keeps purchase-price paybacks in the 5-15 game-year band
# across the ladder; at the old 1.8 the vacuum-era flagship needed >100
# years to repay itself against fares that never grew.
COST_EXP = 0.95
RUN_EXP = 0.0
# Capacity falls as speed rises: faster stock is more structure and more
# premium per seat. This is what stops later generations being strictly
# better. Gentler than the original -0.22: with flat fares the seat count is
# the only revenue lever left, and -0.22 starved the late roster into losses.
PAX_EXP = -0.10

# Per-variant character. `power` and `weight` together set acceleration:
# a standard ends up with ~1.7x the flagship's power-to-weight.
#
# Acceleration is tuned for 256-tile commuter spacing and bounded by human
# comfort: a standard reaches its top speed in ~5 tiles, which at pak128's
# loose "tile is about a kilometre" reading puts a 440 km/h set at
# ~1.5 m/s² — the metro-standard ceiling for standing passengers, so
# standards sit *at* the limit and nothing accelerates harder. Braking is
# not ours to tune: the engine crawls the last four tiles into every stop
# at 200/100/50/25 km/h caps (simconvoi.cc brake_speed_countdown), which is
# the irreducible per-stop tax — even infinite acceleration leaves a
# 440 km/h set at ~90% of its theoretical yield on 256-tile hops. The short
# commuter dwells (load 450-650ms vs the flagship's 900) claw back most of
# what remains.
VARIANTS = {
    "flagship": dict(pax=0.72, power=1.10, weight=1.10, cost=2.20,
                     run=0.62, fixed=0.62, load=900, life=90),
    "standard": dict(pax=1.15, power=1.70, weight=0.92, cost=1.00,
                     run=1.35, fixed=1.35, load=450, life=45),
    # Value stock crams high-density seating (pax 1.20) into a cheap shell:
    # it runs a class behind the fleet average, so it always sells discounted
    # speed-bonus fares — the extra seats are what keep it above water.
    "value":    dict(pax=1.20, power=1.10, weight=1.00, cost=0.55,
                     run=1.55, fixed=1.35, load=650, life=40),
}

COMPANY_LIVERY = {"Meridian": "meridian", "Kestrel": "kestrel",
                  "Volta": "volta", "Aetheris": "aetheris"}

# (company, speed, variant, intro year). Way tiers for reference:
# 300@2000, 500@2014, 700@2032, 1000@2058, 2000@2100, 4000@2165.
ROSTER = [
    ("Meridian",  500, "flagship", 2004),
    ("Kestrel",   260, "standard", 2008),
    ("Volta",     220, "value",    2012),
    ("Meridian",  700, "flagship", 2018),
    ("Kestrel",   440, "standard", 2020),
    ("Volta",     380, "value",    2026),
    ("Meridian", 1000, "flagship", 2036),
    ("Kestrel",   620, "standard", 2040),
    ("Volta",     540, "value",    2048),
    ("Aetheris", 2000, "flagship", 2064),
    ("Kestrel",   880, "standard", 2066),
    ("Volta",     760, "value",    2074),
    ("Aetheris", 4000, "flagship", 2105),
    ("Kestrel",  1750, "standard", 2110),
    ("Volta",    1500, "value",    2120),
    ("Kestrel",  3500, "standard", 2175),
]

# One sheet per trainset, not per company: proportions are driven by the set's
# own speed and grade, so no two share a silhouette. Sheets live in
# src/maglev/images/, so the reference is relative to the vehicles/ dat dir.
SHEET = {"head": "../images/maglev_head_{tag}", "car": "../images/maglev_car_{tag}",
         "mail": "../images/maglev_mail_{tag}", "tail": "../images/maglev_tail_{tag}"}
DIRS = ["w", "nw", "n", "ne", "e", "se", "s", "sw"]
CELL = {"w": "1.0", "nw": "1.1", "n": "1.2", "ne": "1.3",
        "e": "1.4", "se": "1.5", "s": "1.6", "sw": "1.7"}
OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e",
            "ne": "sw", "sw": "ne", "nw": "se", "se": "nw"}


def scale(value, speed, exponent):
    return value * (speed / REF_SPEED) ** exponent


def spec(company, speed, variant):
    """All derived numbers for one trainset."""
    v = VARIANTS[variant]
    pax_scale = (speed / REF_SPEED) ** PAX_EXP
    return dict(
        car_pax=max(8, round(REF_CAR_PAX * pax_scale * v["pax"])),
        head_pax=max(6, round(REF_HEAD_PAX * pax_scale * v["pax"])),
        mail=max(8, round(REF_MAIL * pax_scale * v["pax"])),
        car_weight=round(REF_CAR_WEIGHT * v["weight"], 1),
        head_weight=round(REF_HEAD_WEIGHT * v["weight"], 1),
        power=round(scale(REF_POWER, speed, POWER_EXP) * v["power"]),
        car_cost=round(scale(REF_CAR_COST, speed, COST_EXP) * v["cost"], -4),
        head_cost=round(scale(REF_HEAD_COST, speed, COST_EXP) * v["cost"], -4),
        car_run=round(scale(REF_CAR_RUN, speed, RUN_EXP) * v["run"]),
        head_run=round(scale(REF_HEAD_RUN, speed, RUN_EXP) * v["run"]),
        car_fixed=round(scale(REF_CAR_FIXED, speed, RUN_EXP) * v["fixed"]),
        head_fixed=round(scale(REF_HEAD_FIXED, speed, RUN_EXP) * v["fixed"]),
        load=v["load"],
        life=v["life"],
    )


def images(sheet, reversed_dirs=False):
    order = (OPPOSITE[d] for d in DIRS) if reversed_dirs else iter(DIRS)
    return "".join(f"emptyimage[{d}]={sheet}.{CELL[c]}\n"
                   for d, c in zip(DIRS, order))


def write_set(out_dir, company, speed, variant, intro):
    tag = f"{COMPANY_LIVERY[company]}{speed}"
    s = spec(company, speed, variant)
    stem = f"Maglev_{company}{speed}"
    retire = intro + s["life"]
    head_sheet = SHEET["head"].format(tag=tag)
    car_sheet = SHEET["car"].format(tag=tag)
    mail_sheet = SHEET["mail"].format(tag=tag)
    tail_sheet = SHEET["tail"].format(tag=tag)

    common = (f"waytype=maglev_track\nengine_type=electric\n"
              f"speed={speed}\nlength=12\nsmoke=-1\n"
              f"intro_year={intro}\nintro_month=1\n"
              f"retire_year={retire}\nretire_month=1\n"
              f"loading_time={s['load']}\n")

    files = {}

    files[f"{stem}_head.dat"] = (
        f"obj=vehicle\nname={stem}_Head\ncopyright=Aleksander Kwiatkowski\n{common}"
        f"sound=train-horn-electric-0.wav\n"
        f"freight=Passagiere\npayload={s['head_pax']}\n"
        f"power={s['power']}\ngear=260\nweight={s['head_weight']}\n"
        f"cost={s['head_cost']:.0f}\nrunningcost={s['head_run']}\n"
        f"maintenance={s['head_fixed']}\n"
        f"constraint[prev][0]=none\n"
        f"constraint[next][0]={stem}_Car\n"
        f"constraint[next][1]={stem}_Mail\n"
        f"constraint[next][2]={stem}_Tail\n"
        + images(head_sheet))

    files[f"{stem}_car.dat"] = (
        f"obj=vehicle\nname={stem}_Car\ncopyright=Aleksander Kwiatkowski\n{common}sound=-1\n"
        f"freight=Passagiere\npayload={s['car_pax']}\n"
        f"power=0\nweight={s['car_weight']}\n"
        f"cost={s['car_cost']:.0f}\nrunningcost={s['car_run']}\n"
        f"maintenance={s['car_fixed']}\n"
        f"constraint[prev][0]={stem}_Head\n"
        f"constraint[prev][1]={stem}_Car\n"
        f"constraint[prev][2]={stem}_Mail\n"
        f"constraint[next][0]={stem}_Car\n"
        f"constraint[next][1]={stem}_Mail\n"
        f"constraint[next][2]={stem}_Tail\n"
        + images(car_sheet))

    files[f"{stem}_mail.dat"] = (
        f"obj=vehicle\nname={stem}_Mail\ncopyright=Aleksander Kwiatkowski\n{common}sound=-1\n"
        f"freight=Post\npayload={s['mail']}\n"
        f"power=0\nweight={round(s['car_weight'] * 0.95, 1)}\n"
        f"cost={s['car_cost'] * 0.88:.0f}\nrunningcost={round(s['car_run'] * 0.9)}\n"
        f"maintenance={round(s['car_fixed'] * 0.9)}\n"
        f"constraint[prev][0]={stem}_Head\n"
        f"constraint[prev][1]={stem}_Car\n"
        f"constraint[prev][2]={stem}_Mail\n"
        f"constraint[next][0]={stem}_Car\n"
        f"constraint[next][1]={stem}_Mail\n"
        f"constraint[next][2]={stem}_Tail\n"
        + images(mail_sheet))

    # The tail sheet is the head rendered with a blanked windscreen, used with
    # every direction swapped for its opposite so the nose points back down
    # the train — a train has a lit front and a blind back.
    files[f"{stem}_tail.dat"] = (
        f"obj=vehicle\nname={stem}_Tail\ncopyright=Aleksander Kwiatkowski\n{common}sound=-1\n"
        f"freight=Passagiere\npayload={s['head_pax']}\n"
        f"power=0\nweight={round(s['head_weight'] * 0.82, 1)}\n"
        f"cost={s['head_cost'] * 0.55:.0f}\nrunningcost={round(s['head_run'] * 0.6)}\n"
        f"maintenance={round(s['head_fixed'] * 0.6)}\n"
        f"constraint[prev][0]={stem}_Car\n"
        f"constraint[prev][1]={stem}_Mail\n"
        f"constraint[prev][2]={stem}_Head\n"
        f"constraint[next][0]=none\n"
        + images(tail_sheet, reversed_dirs=True))

    for name, body in files.items():
        (out_dir / name).write_text(body)
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--out", default="src/maglev/vehicles")
    parser.add_argument("--table", action="store_true", help="print, write nothing")
    args = parser.parse_args()

    if args.table:
        head = ("set", "intro", "retire", "speed", "car pax", "mail",
                "power", "cost/car", "run/car", "fix/car")
        print("{:<18}{:>6}{:>8}{:>7}{:>9}{:>7}{:>10}{:>12}{:>9}{:>9}".format(*head))
        for company, speed, variant, intro in ROSTER:
            s = spec(company, speed, variant)
            print("{:<18}{:>6}{:>8}{:>7}{:>9}{:>7}{:>10}{:>12.0f}{:>9}{:>9}".format(
                f"{company} {speed}", intro, intro + s["life"], speed,
                s["car_pax"], s["mail"], s["power"], s["car_cost"],
                s["car_run"], s["car_fixed"]))
        return

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    total = sum(write_set(out, *entry) for entry in ROSTER)
    print(f"wrote {total} vehicle .dat files for {len(ROSTER)} trainsets -> {out}")


if __name__ == "__main__":
    main()
