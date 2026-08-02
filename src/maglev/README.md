# Maglev Source Assets

Editable maglev `.dat` files and source images live in this directory, kept
apart: infrastructure `.dat` files sit at the root, the generated vehicle
`.dat` files in `vehicles/`, and every sprite sheet in `images/` — dat files
reference them as `images/...` (root) or `../images/...` (vehicles). The asset
Makefile writes generated `.pak` files to `dist/`.

All original maglev assets in this directory use Artistic License 2.0.

## Track

`maglev_track.png` is **generated**, not hand-edited. Two renderers produce it,
both writing the same 8x11 cell layout that pak128's rail sets use, so the
`.dat` files work with either:

```sh
make track-2d     # procedural 2D renderer, seconds
make track-3d     # Blender render + pack, ~2 minutes
```

See `tools/README.md` for how the pak128 grid, direction mapping, ramp
projections and lighting were measured off the reference rail sheet, and for
the Blender camera parameters. Edit `tools/render_maglev_track.py` or
`tools/blender/build_maglev_track.py` rather than the PNG.

The three open tiers — 160, 250 and 400 km/h — share the one sheet and differ
by `topspeed`, cost and maintenance in their `.dat` files. Each has its own
toolbar icon in row 0 so they can be told apart when building. The sheet
carries winter tiles as well as summer ones.

## Speed ladder

Way tiers and vehicle speeds are deliberately **staggered** — line speed is
`min(vehicle, way)`, so if they matched there would be no decision to make.

| Tier | Speed | From | Sheet |
|---|---|---|---|
| open | 300 | 2000 | `maglev_track.png` |
| open | 500 | 2014 | `maglev_track.png` |
| open | 700 | 2032 | `maglev_track.png` |
| tube | 1000 | 2080 | `maglev_tube.png` |
| tube | 2000 | 2100 | `maglev_tube2000.png` |
| tube | 4000 | 2165 | `maglev_tube4000.png` |

The three open tiers share one sheet and differ only by `topspeed`, cost and
intro year, each with its own toolbar icon. See the plan for why the ladder is
staggered against the vehicle roster.

## Enclosed guideway (tiers 4-6)

The glazed tubes are the only sheets written as **RGBA** — glass needs real
per-pixel alpha, which the `#E7FFFF` key cannot express. `make tube` renders
the 1000; the 2000 and 4000 use the same geometry with denser or sparser
framing and a deeper tint (`TUBE_TIERS` in the builder).

At a junction the branch bore is rendered at 90% scale so it nests inside the
through bore, rather than two equal tubes clipping edge to edge.

A light cove runs along the springing, rendered in a marker colour and swapped
during packing for `#7F9BF1` — a reserved Simutrans light that does not darken
at night, so a tube line stays lit when the map dims.

It carries **two full ribi sets** in four 5-row blocks (back summer, front
summer, back winter, front winter). The back images hold the apron, the beam
and the far half of the tube; the front images hold the near half, which
Simutrans draws *after* vehicles, so a pod is seen through the glass rather
than hidden behind it.

The tube keeps the same central beam as every other tier, which is what makes
all rolling stock compatible with all guideways: every pod wraps the same beam,
so it cannot look wrong on any tier.

## Stop, depot and vehicle

All three are original artwork now, rendered from the same Blender rig:

```sh
make station     # two platforms flanking the guideway
make depot       # barrel-vault maintenance hangar
make fleet       # every trainset in the roster, eight travel directions each
make art         # all of the above plus the track
```

Stop and depot are Simutrans *buildings*: two orientations (layout 0 for a N/S
way, layout 1 for E/W), each split into a back image drawn before vehicles and
a front image drawn after. That split is what puts the near platform in front
of a stopped train, and the shed in front of a stabled one. The way keeps
drawing the guideway underneath, so neither sheet paves the ground.

Vehicle sizing follows pak128's convention rather than real metres — measured
against its own Shinkansen, a pak128 car is about two thirds of its real height
and half its real length. Modelling to true Transrapid dimensions produced a
body that read as a fat white pill beside everything else.

## Rolling stock

Four vehicle types make up a train, generated per trainset into `vehicles/`
by `tools/gen_vehicle_roster.py` (`*_head`, `*_car`, `*_mail`, `*_tail`):
the powered head, unpowered passenger and mail trailers, and the tail.
Valid formations are head + tail, or head + any mix of trailers + tail.

The tail has **no artwork of its own**: it points at the head sheet with
every direction swapped for its opposite, so the nose faces back down the
train. A tail car is a head car seen the other way round, and rendering a
second sheet for it would only invite the two to drift apart.

The nose is a wedge rather than a cone. The body wraps its guideway all the way
to the tip, so the skirts cannot pull in — narrowing them would drive the
underside channel into the beam. The taper is therefore nearly all in height,
measured about the floor line, with only a slight draw-in of the upper body.

Propulsion on a real maglev is in the guideway, not the vehicle, but Simutrans
needs a vehicle to carry the power rating, so the head does.

## Display names

`text/en.tab` carries the display names; `make install` copies it to
`addons/pak128/text/`, which is where Simutrans looks for addon translations
(`dataobj/translator.cc`). Without it the depot list shows raw object ids.
Regenerate it alongside the roster.

## Known gaps

- `Level=9` on the stop, and the payload / cost / weight figures across all
  three vehicle types, are rough. They have not been balanced against pak128's
  rail stock — the middle section's power was moved to the head, and the costs
  split by eye.
- Nothing has been run in the game yet. Everything is verified by compositing
  the sheets the way Simutrans layers them, plus a clean `makeobj` pack.
- Junction tiles simply let the two tubes intersect. It reads acceptably as a
  cross vault, but a proper junction treatment would be better.

## Historical artwork

`versions/` keeps earlier passes for reference. They are not compiled:

- `v0-rail-placeholder/` — the original reused pak128 rail images
- `v1-blue-guideway/` — first tint pass

Gameplay track versions are the compiled `.dat` speed tiers, not these
directories.
