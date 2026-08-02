# Simutrans pak128 Maglev

Standalone pak128 addon source for a playable maglev prototype.

This repository is intentionally separate from the Simutrans engine and from
the downloaded base `pak128/` directory. Editable assets belong under
`src/maglev/`. Generated `.pak` files belong under `dist/` and are ignored.
The official pak128 source is kept under `upstream/` as a local reference —
a blobless sparse clone holding only the directories the pipeline consults
(`git -C upstream sparse-checkout add <dir>` fetches more on demand) — and is
intentionally not vendored into this repository.

## Current Milestone

The first milestone is one complete passenger service:

- maglev track
- compatible station
- compatible depot
- one passenger maglev train
- one mostly straight test route long enough to show top speed

All artwork is original and generated: see `tools/README.md` for the 2D and
Blender render pipelines that produce every sheet under `src/maglev/images/`.

## The companies

The maglev century began quietly: a guideway hums instead of roaring, its
stators drink from the solar canopies strung along the corridor, and the
land underneath was never paved — orchards and meadow run right up to the
piers. Aviation faded not because anyone banned it, but because nobody
missed it. Four manufacturers share that century, and each sells a
different answer to the same question — what is speed worth?

**Meridian** builds flagships the way older centuries built bridges: to be
inherited. Founded around the first prototype guideway, it made its name
with a habit that looks like arrogance and works like patience — every
Meridian set is built for the *next* guideway, not the current one. The
Meridian 500 of 2004 spent its first decade capped at 300 km/h, waiting for
the track to catch up; when the 500 guideway opened in 2014, every operator
who had bought one got a fleet upgrade for free. One door per car, a long
nose, few seats, a service life of ninety years — nothing Meridian makes is
disposable, and its glazed skylight cars were designed around a simple
belief: at any speed, passengers deserve the sky.

**Kestrel** builds the trains everyone actually rides. Three doors a side,
short dwell times, roughly 1.6× the seating of a comparable flagship, and a
red stripe that has meant "the commuter is coming" since 2008. Kestrel never
chases records — it ships an honest set for whatever the guideway can do
today, engineered so a depot with hand tools can keep it running for
forty-five years. It outlasted every rival at the game it plays: the
Kestrel 3500 of 2175 is the last train ever introduced on the roster, still
a three-door commuter, now in a vacuum tube.

**Volta** engineers the price down until everyone can board. An
amber-striped Volta arrives a few years after the equivalent Kestrel, a
little slower and noticeably cheaper — the maker of choice for town
cooperatives and regional lines that count credits per seat rather than
seconds per trip. The frugality shows in the details (two doors instead of
three, a shorter service life) and in the ledger, where a Volta 220 cost
less than half its Kestrel contemporary. Every network's unglamorous,
load-bearing middle years run on Volta.

**Aetheris** did not exist until the vacuum era made it inevitable. It
appeared in 2064 with a sealed 2000 km/h capsule — sixteen years before the
first tube opened — repeating Meridian's old bet at ten times the stakes.
Its teal-striped capsules are the only sets designed tube-first: smooth,
nearly windowless hulls that look wrong under open sky and perfect inside
glass, gliding through sunlit tubes whose light coves never dim. Continental
distance for the energy budget of a short-haul flight, and the quietest
machines ever to cross a landscape without touching it.

## The trains

Sixteen trainsets, 2004–2175. Speeds are deliberately staggered against the
guideway ladder (300/500/700 open, 1000/2000/4000 tube) — line speed is
`min(vehicle, way)`, so a flagship bought early runs capped until its track
arrives.

| Set | In service | Top speed | Seats/car | Mail | Power | Cost/car | Notes |
|---|---|---|---|---|---|---|---|
| Meridian 500 | 2004–2094 | 500 km/h | 39 | 32 | 28 MW | 287M | The original headroom bet; capped at 300 for a decade |
| Kestrel 260 | 2008–2053 | 260 km/h | 71 | 59 | 11 MW | 40M | First commuter; defined the three-door dwell standard |
| Volta 220 | 2012–2052 | 220 km/h | 67 | 56 | 4.6 MW | 16M | Cheapest set ever sold; built half the early networks |
| Meridian 700 | 2018–2108 | 700 km/h | 36 | 30 | 54 MW | 526M | Bought for the 2032 guideway fourteen years early |
| Kestrel 440 | 2020–2065 | 440 km/h | 63 | 53 | 31 MW | 104M | The 500-guideway workhorse |
| Volta 380 | 2026–2066 | 380 km/h | 60 | 50 | 14 MW | 44M | Undercut the 440 by more than half |
| Meridian 1000 | 2036–2126 | 1000 km/h | 33 | 28 | 111 MW | 999M | Sat on 700 track for 44 years awaiting the first tube |
| Kestrel 620 | 2040–2085 | 620 km/h | 59 | 49 | 62 MW | 192M | Commuting at what was recently record pace |
| Volta 540 | 2048–2088 | 540 km/h | 55 | 46 | 28 MW | 82M | The everyman's 500-class, twenty years late and proud |
| Aetheris 2000 | 2064–2154 | 2000 km/h | 28 | 24 | 444 MW | 3.5B | A capsule with no tube to run in — until 2100 |
| Kestrel 880 | 2066–2111 | 880 km/h | 54 | 45 | 125 MW | 361M | Fastest open-guideway commuter ever built |
| Volta 760 | 2074–2114 | 760 km/h | 51 | 43 | 55 MW | 152M | Maxes the 700 guideway at a third of flagship cost |
| Aetheris 4000 | 2105–2195 | 4000 km/h | 24 | 20 | 1.8 GW | 12B | The pure capsule: all nose, no windows, no compromise |
| Kestrel 1750 | 2110–2155 | 1750 km/h | 47 | 39 | 493 MW | 1.2B | Three doors a side at Mach 1.4 |
| Volta 1500 | 2120–2160 | 1500 km/h | 44 | 37 | 213 MW | 518M | Vacuum travel for operators who still count credits |
| Kestrel 3500 | 2175–2220 | 3500 km/h | 40 | 33 | 2.0 GW | 4.3B | The last train; the commuter outlived everyone |

Every set is a head + optional cars/mail + tail formation; heads carry the
power rating (real maglev propulsion is in the guideway, but Simutrans needs
a vehicle to own the number). Payloads, costs and running costs are generated
by `tools/gen_vehicle_roster.py` from each set's speed and grade, so the
table above tracks the shipped `.dat` files.

## Build

The asset build uses `makeobj` from the Simutrans repository:

```sh
mise exec -- make -f Makefile build
```

Defaults assume the repositories are siblings:

```text
games/simutrans/
games/simutrans-pak128-maglev/
```

Override paths when needed:

```sh
mise exec -- make -f Makefile build \
  GAME_REPO=/path/to/simutrans \
  MAKEOBJ=/path/to/makeobj
```

The generated addon is `dist/maglev-addon.pak`.

## Evaluation

Install the addon into the asset repository's ignored evaluation directory and
run the game with a private user directory:

```sh
mise exec -- make -f Makefile run
```

This keeps saves, settings, and installed addon files under `evaluation` and
enables addon loading with `-addons`. The default evaluation starts in 2000 so
the prototype objects are available on the timeline.
The base pak128 package is not modified.

## Licensing

This addon uses Artistic License 2.0, the same license as the original pak128
graphical material. Reference material derived from pak128 remains clearly
separated and retains its upstream attribution. See `LICENSES/NOTICE.md` before
copying or redistributing any reference asset.
