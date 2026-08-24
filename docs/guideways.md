# Guideways

Every way in the pak, why each tier looks the way it does, and the way-builder
tuning the add-on installs. Rolling stock is in [rolling-stock.md](rolling-stock.md),
stops in [stations.md](stations.md).

## The speed ladder

Way tiers and vehicle speeds are deliberately **staggered** — line speed is
`min(vehicle, way)`, so if they matched there would be no decision to make.

| Tier | Speed | From | Sheet |
|---|---|---|---|
| elevated | 160 | 2008 | `maglev_elevated.png` |
| open | 300 | 2000 | `maglev_track_300.png` |
| open | 500 | 2014 | `maglev_track_500.png` |
| open | 700 | 2032 | `maglev_track_700.png` |
| tube | 1000 | 2080 | `maglev_tube.png` |
| tube | 2000 | 2100 | `maglev_tube2000.png` |
| tube | 4000 | 2165 | `maglev_tube4000.png` |

Sheets live in `src/maglev/images/`; the `.dat` files that reference them sit at
the root of `src/maglev/`.

## The open tiers

The track sheets are **generated**, not hand-edited. Each open tier has its own
sheet — `maglev_track_{300,500,700}.png` — rendered by Blender from
`TRACK_TIERS` in the builder; the 2D renderer keeps feeding the shared
`maglev_track.png`, which serves as the fallback base for failed cells and quick
iteration. All use the same 8x11 cell layout as pak128's rail sets:

```sh
make track-2d     # procedural 2D renderer, seconds
make track-3d     # Blender render + pack, all three tiers, ~6 minutes
```

See [`tools/README.md`](../tools/README.md) for how the pak128 grid, direction
mapping, ramp projections and lighting were measured off the reference rail
sheet, and for the Blender camera parameters. Edit
`tools/render_maglev_track.py` or `tools/blender/build_maglev_track.py` rather
than the PNGs.

Tier character follows the tubes' law — escalation is density of engineering —
run so the open ladder converges toward the tube, and each tier tells it through
where its services live. Every motif is sized to survive 128px: hue temperature
on the girder (warm sand → cool precast → pale shell) plus one bold rhythm per
tier; centimetre realism that reads as flat grey at map zoom is deliberately
exaggerated.

- **300 "Pioneer"** — warm site-cast concrete, heavy segment joints, and exposed
  stator packs as raised dark blocks dashed along the guidance slots (real
  geometry, not a seam texture — the world-XY seam grid would smear a dash into
  a stripe on any run it parallels). Its services hang beside the beam on
  galvanised masts, two feeder cables sagging between them, world-anchored so
  the line of posts marches straight through tile joints.
- **500 "Standard"** — the seamless cool precast norm. The masts are gone:
  services moved into a safety-orange cable tray clamped along each flank, proud
  clamp blocks giving it a tick rhythm. The tray carries a whisper of
  self-emission so shade cannot turn the paint to mud.
- **700 "Shell"** — pale engineered composite with a flared skirt and low glass
  wind fences; the cables have vanished into the shell entirely. Each fence
  stands on a lit base rail rendered in the magenta marker and swapped at pack
  time for the reserved `#7F9BF1` light — the guideway already carrying a sliver
  of the tube's light cove, two threads that stay lit when the map dims.

Winter tells the same story: unheated beams vanish under the same snow as the
apron (the 300's slots fill with snow between the stator packs, its dark masts
standing against the white), the 500 keeps its orange thread through a grey map,
and the 700's powered deck melts itself into a wet black ribbon with its edge
threads still burning. Each tier keeps its own toolbar icon in row 0 — the
guideway slice under the speed sign wears the tier's colours — and every sheet
carries winter tiles as well as summer ones.

### The ground under the beam

The guideway does not pave its tile. Each run rides a precast foundation band
barely wider than the deck — a drainage gutter along each slab edge — and
everything beyond the band stays living terrain, the same read as pak128's own
ballast strips. The trackside hardware stands on that band or on its own
footings: the 300's masts get concrete pads out on the grass, while the 500 and
700 grow service cabinets on a world-anchored rhythm along the slab edge — their
cables are buried, and boxes on the surface are what buried services look like.
The packer keeps everything outside the rendered footprint transparent, so
terrain, snow and slopes show through exactly as the map draws them.

## The urban elevated

The 160 tier is a *place* tier, not a speed tier — the monorail role. It rides
one height level up on single tapered columns (`system_type=1`, so the engine
builds it elevated), the street left entirely free beneath: pale municipal
concrete, a teal service stripe along each beam flank, and the column rhythm as
its character. Any trainset runs on it — every pod wraps the same beam — capped
at 160, which is exactly what a metro headway wants. Junctions flex in steel at
height like everywhere else. Generated by `make elevated`.

## The vacuum tubes

The glazed tubes are the only sheets written as **RGBA** — glass needs real
per-pixel alpha, which the `#E7FFFF` key cannot express. `make tube` renders the
1000; the 2000 and 4000 use the same geometry with denser or sparser framing and
a deeper tint (`TUBE_TIERS` in the builder).

A junction is a node, not a clip: a vertical glass rotunda drum wraps the bore
intersection — frame ring at the crown, shallow cap dome, and its own cove ring
at eye height, so every tube junction glows as a landmark at night. The drum
splits down the near/far line like the tubes themselves, so a pod inside the
node stays visible. Beneath the glass the branch bore still nests at 90% scale
inside the through bore rather than clipping edge to edge.

A light cove runs along the springing, rendered in a marker colour and swapped
during packing for `#7F9BF1` — a reserved Simutrans light that does not darken
at night, so a tube line stays lit when the map dims.

It carries **two full ribi sets** in four 5-row blocks (back summer, front
summer, back winter, front winter). The back images hold the apron, the beam and
the far half of the tube; the front images hold the near half, which Simutrans
draws *after* vehicles, so a pod is seen through the glass rather than hidden
behind it.

The tube keeps the same central beam as every other tier, which is what makes
all rolling stock compatible with all guideways: every pod wraps the same beam,
so it cannot look wrong on any tier.

## Junctions and diagonals: the bending beam

A real maglev has no turnouts to cast — a switch is a bare steel box girder that
actuators flex sideways, and a "curve" is that same bending beam. Every tile
where runs meet or bend (switches, crossings, and the 45° diagonals) therefore
renders its girder as dark segmented steel, one tier-neutral machine surface
across the whole ladder; the tier's dressing — stator packs, cable tray, wind
fences, masts, the 700's skirt — steps back for the length of the mechanism and
resumes beyond it. The flexing surface is kept ice-free, so junctions stay dark
on a winter map and can be spotted at a glance.

## Bridges and tunnels

Bridges and tunnels come in three classes — **500** (2014), **1000** (2080) and
**4000** (2165) — deliberately *not* one per way tier: line speed is
`min(way, bridge)`, so a fast-rated crossing never slows a slower line, and the
sparse ladder creates real decisions — a 700 trunk crosses valleys capped at 500
for half a century until the tube-era crossing opens.

The 500 bridge is the open viaduct: the tier's own girder (orange tray and all)
riding a haunched spine on tapered pylons. The 1000 and 4000 carry the glazed
tube across, split back/front down the crown like the tube way, so a pod
crossing a valley is still seen through the glass, cove alight. Tunnels are
portal pairs — the 500 a precast frame sized to the pod envelope, the tube
classes a collar the tube sockets into, the light cove running through the
opening so the glow enters the hill. Fronts are the headwall with the bore left
transparent: a pod slides in and is swallowed.

Generated by `make bridge` and `make tunnel`
(`tools/blender/build_maglev_{bridge,tunnel}.py`).

## Signals

`maglev_signal.dat` ships a single-head block signal and a twin-head choose
signal (routes a pod to any free platform), both from year 2000. The sheet is
generated by `make signal`; lamp pixels are stamped to the reserved lights
`#FF211D`/`#01DD01` at pack time, so an aspect keeps glowing after dark, and a
repeater lamp on the head's back keeps the aspect readable in the two rotations
that face away from the camera.

## Building long guideways

A maglev trunk wants to be straight for hundreds of tiles (see the stop spacings
in [rolling-stock.md](rolling-stock.md#the-roster)), and the stock route search
happily trades a straight line for a cheaper wiggle. The addon ships
`config/simuconf.tab`, which `make install` places in `addons/pak128/config/` —
the engine parses it after the pakset's own config, and your personal
`simuconf.tab` still wins afterwards:

- **Every drag builds straight.** `straight_way_without_control = 1` makes the
  way tool always take the direct route (what holding Ctrl does): horizontal,
  vertical, clean 45° diagonals, shallow angles as one diagonal leg plus one
  straight leg. If terrain blocks the direct path the drag fails rather than
  wiggling around — drop a waypoint and build two legs. Single-player only;
  network games ignore the flag.
- **The free router is retuned** for when the flag is off or scripts build:
  S-bends are taxed hard (`way_double_curve` 6 → 40, `way_90_curve` 15 → 120)
  while single 45° corners stay affordable — a long diagonal is legitimate
  routing, a zigzag is not. `way_count_maximum` rises to 8000 so a single
  1,000-tile drag fits the search budget.
- **Parallel tracks are an engine feature nobody documents**: start and end your
  drag on *empty* tiles within one tile of an existing maglev way, and the
  router switches to prefer-parallel mode — hugging the neighbour costs 1 per
  tile, drifting away 3, and merging into the existing line 25, so the second
  track lays itself alongside without touching the first. The raised
  `way_avoid_crossings = 64` makes it route around other ways instead of through
  them.
