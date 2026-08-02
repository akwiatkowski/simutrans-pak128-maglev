# Artwork tooling

Two renderers produce the maglev track sheet. They share the cell layout and
the sprite-sheet conventions, so either can fill `src/maglev/images/maglev_track.png`
and the `.dat` files never change.

| | 2D (`render_maglev_track.py`) | 3D (`blender/`) |
|---|---|---|
| Runtime | ~2 s | ~2 min for 136 cells |
| Needs | Python + Pillow + numpy | Blender 5.x as well |
| Shading | hand-authored tone ramps | real light, shadow, ambient occlusion |
| Edges | exact by construction | exact via the analytic clip in the assembler |

Use the 2D one to iterate on layout and proportions, the 3D one for the final
look. Both are kept: the 2D path is the fallback when Blender is unavailable
and stays useful for checking a geometry change quickly.

```sh
make track-2d          # procedural sheet, seconds
make track-3d          # Blender render + pack
make station depot     # the two buildings
make vehicle           # the middle section, eight directions
make head              # the powered nose car
make tube              # the enclosed glazed guideway (tier 4)
make art               # everything
make iso-selftest      # assert the camera still hits pak128's pixel grid
make preview           # lay tiles into a map, next to pak128's rail for comparison
make build             # makeobj -> dist/maglev-addon.pak
```

## What was reverse-engineered from pak128

Everything below was measured off `upstream/infrastructure/rail_tracks/rail_400_tracks.png`
with `sheet_inspect.py`, not guessed.

- **Sheet**: 8x11 cells of 128px. Row 0 holds icons and the build cursor,
  rows 1-5 summer, rows 6-10 winter.
- **Tile**: the diamond occupies y=65..127 in its cell, centred on (63.5, 96),
  128px wide and tapering 2px per row per side. Its widest row is 96 *alone*,
  which places the centre on a pixel centre — the half pixel that the Blender
  camera has to account for.
- **Directions**: N is the upper-right edge, E lower-right, S lower-left,
  W upper-left. So a `NS` way draws as `/` and an `EW` way as `\`.
- **Ramps**: `ImageUp[3|6|9|12]` are n, w, e, s in `way_writer.cc` order. Each
  raises two adjacent corners by 16px, pak128's height step.
- **Lighting**: the key light comes from screen lower left. pak128's shaded
  ramp fits a ~43 degree sun exactly; its sunlit ramp does not fit any single
  Lambert sun and was clearly lifted by hand, so both renderers reproduce the
  measured tones rather than the physics. See `RAMP_EXPOSURE`.
- **Transparency**: `#E7FFFF`, from `SPECIAL_TRANSPARENT` in the game's
  `descriptor/image.h`. The original placeholder PNGs used `#B3D9E3`, which is
  *not* keyed out and would have rendered an opaque blue box behind every
  sprite; all four sheets are regenerated now and use the right key.

## The Blender rig

`blender/simutrans_iso.py` is asset-agnostic — the station, depot and vehicle
can reuse it. The parameters that matter:

- Orthographic camera, `rotation_euler = (60°, 0, 45°)`. That is a 30 degree
  elevation, giving exactly 2:1. Blender's "true isometric" 54.736° would give
  2:1.1547 and drift a pixel every few tiles.
- `ortho_scale = sqrt(2)` with a 128px render: one tile edge is exactly 64px
  across and 32px down.
- World +Y is the N axis, +X the E axis, +Z is up. One tile is 16m of ground,
  which is what makes a real 3.1m Transrapid girder land on the ~14px band
  width the pak128 rail sets use.
- Render RGBA with `film_transparent`, view transform **Standard** (AgX would
  wash the palette out), and no diffuse bounce — light bouncing off a lit
  girder wall onto the apron reads as a smudge at this size.

`selftest.py` renders a bare tile and asserts the silhouette matches pak128's
diamond row by row. Run it after any change to the camera or scale.

### Glazing and real alpha

Simutrans supports **true per-pixel alpha** in pak images, which is what makes
an enclosed glass guideway possible. Two things to know:

- `image_writer.cc` does `return pixel ^ 0xFF000000;` — *"invert alpha channel,
  we want 0 == opaque"*. So author ordinary RGBA PNGs with standard alpha; the
  inversion is internal.
- Anything at PNG alpha **0-7 collapses to fully transparent**, and the rest is
  quantised to **31 steps**. Faint glazing has to clear that floor or it
  silently disappears — hence `ALPHA_FLOOR` in `assemble_sheet.py`.

Enclosed ways need **two full ribi sets**. `way_writer.cc` reads the second as
`frontimage[<ribi>][<season>]`, `frontimageup[...]`, `frontdiagonal[...]`, and
draws it *after* vehicles. So the back image carries the apron, beam and far
half of the tube, the front image carries the near half, and a pod ends up
inside the glass.

Two things learned tuning it:

- **Every hoop draws twice** — you see the far one through the glass as well as
  the near one — so on-screen rib rhythm is double the modelled pitch. 4m read
  as a polytunnel; 8m reads as infrastructure.
- **A continuous spine along the crown** did more for the high-tech read than
  any amount of rib tuning. One unbroken line down the run is what separates
  engineered structure from a greenhouse.
- Alpha alone is not glass. Drive it from a **Layer Weight *Facing*** output so
  the glazing is clear face-on and bright at the silhouette, and turn off the
  glass's **shadow casting** or it lays a solid dark band across the apron.

### Sub-pixel corners

A renderer anti-aliases the diamond's left and right tips to well under 50%
coverage, so a plain alpha threshold drops them. Four tiles meet at each of
those points and all four would drop them, leaving the ground showing through
as a speckle along every run. `assemble_sheet.py` therefore takes the ground
silhouette from the projection maths instead, and only uses a coverage test for
the parts standing above ground.

## The visual language

Nothing here is decoration: every visual difference encodes something a player
can act on, so shape and colour double as the datasheet.

**Guideway tiers — enclosure grows, the beam never changes.** All tiers keep the
same central T-beam, which is what makes every vehicle compatible with every
way: a pod wraps the same beam everywhere, so it cannot look wrong on any tier.
Tiers differ by what is built *around* it — bare beam, side walls, fairings,
then a glazed tube. The enclosed tiers escalate by *density of engineering*
(rib pitch, tint, framing), not by new shapes.

Two things learned tuning the tube, both counter-intuitive:

- **Every hoop draws twice** — you see the far one through the glass as well as
  the near one — so on-screen rib rhythm is double the modelled pitch. 4m read
  as a polytunnel; 8m reads as infrastructure.
- **A continuous spine along the crown** did more for the high-tech read than
  any amount of rib tuning. And for the *endgame* tier the framing gets
  sparser, not denser: greebles read as industrial, and a smoother tube reads
  as the more advanced one.

**Vehicles — three independent axes.**

| Axis | Carries | How |
|---|---|---|
| Manufacturer | who operates it | colour band along the **roof** |
| Grade | flagship / standard / value | proportions and door count |
| Era | how advanced | continuous streamlining by speed |
| Cargo | passengers or mail | windows, or none |

Grade is the important one, because the silhouette states the stats:

| | Nose | Roof | Window band | Doors |
|---|---|---|---|---|
| Flagship | long | low | narrow | **1** |
| Standard | short | tall | deep | **3** |
| Value | short | medium | medium | **2** |

A standard *looks* boxier and really does seat ~1.6x a flagship. **Door count is
the readable form of dwell time** — three doors and a 700ms stop against one
door and 1100ms. Era is a continuous function of the set's own speed rather
than a set of buckets, so all sixteen trainsets differ; the arc runs *train ->
capsule*, and at the fast end a head car is almost entirely nose.

Colour goes on the **roof**, never the flank — see the isometric note below.
A mail van is identified by having no windows and one wide loading door, which
reads at 50x25px where a change of hue does not.

## Adding a new asset

The rig is done; a new object is mostly measurement plus geometry. The order
below is what actually worked, and skipping step 1 is what costs time.

1. **Measure the pak128 equivalent first — never guess the conventions.**
   Find the closest object under `upstream/` and read it with
   `sheet_inspect.py map` (which cells are used) and its `.dat` (what each cell
   means). Every layout question so far had a measurable answer:
   - Orientation of a layout: fit the principal axis of a directional image.
     Long thin shapes like platforms give a clean answer; chunky ones do not,
     so use the entropy test instead — a feature running `/` keeps `y + x/2`
     constant, one running `\` keeps `y - x/2` constant, and the flatter
     histogram is the odd one out. This is how layout 0 = N/S was established.
     Beware measuring the wrong feature: the depot's *front* image reads
     opposite because its roof ridge runs across the entrance.
   - Which way a building faces: composite its back and front images the way
     the game layers them and just look. One picture settled the depot.

2. **Add the cell plan to `pak128_layout.py`.** Standard library only — it is
   the one module both the repo Python and Blender's Python can import.

3. **Write `blender/build_<thing>.py`.** Model in metres in object-local axes
   (`u` along, `v` across, `w` up) and map to world per layout, so the object
   is described once instead of once per orientation. `extrude_profile` sweeps
   a cross-section and takes per-edge materials; `caps=False` leaves the ends
   open when they need their own geometry, such as a wall with a doorway.

4. **Pick the clip in `assemble_sheet.py`.** Ground-hugging way tiles need the
   analytic tile silhouette; buildings and vehicles legitimately overhang the
   tile, so plain coverage is right for them.

5. **Check it composited, not cell by cell.** A cell in isolation tells you
   almost nothing. `preview_layout.py` lays way tiles into a map; for buildings
   and vehicles, stack way + back + vehicle + front in that order.

6. `make build`, then update the `.dat` copyright away from the placeholder.

### Traps already paid for

- **Scale is not consistent across pak128.** Ground and vehicles are drawn to
  different scales. A vehicle modelled to true metres came out as a fat white
  pill; measured against pak128's own Shinkansen, its cars are about two thirds
  of real height and half of real length. Measure the neighbours, not reality.
- **A vehicle that wraps its guideway cannot taper its skirts.** Narrowing the
  nose drove the underside channel into the beam. Taper in height about the
  floor line instead — which is why real maglev noses are wedges.
- **Symmetric ends make a coupled train read as separate pods.** Chamfer them,
  or add a proper head type.
- **Coplanar faces z-fight into speckle** where two runs cross. Lift the
  through route a couple of centimetres; it is a tenth of a pixel on screen.
- **A reversed vehicle needs no new artwork.** Point its `.dat` at the same
  sheet with every direction swapped for its opposite.
- **Identity marks belong on top surfaces.** A 30-degree camera shows far more
  roof than flank; a side stripe is effectively invisible at 128px. Four
  liveries were indistinguishable until the colour moved to the roof.
- **Two coordinate conventions coexist here** and they are transposed: Blender
  works in world `(x=E, y=N)`, the sheet layout in tile `(a=N, b=E)`. Hand-placed
  preview sprites hide the confusion; `preview_layout.place_consist` derives the
  cell from the way and raises on a mismatch instead.
- **Reserved colours are a trap.** Simutrans keeps 31 exact colours that mean
  player colour or "do not darken at night", and several of the greys sit in the
  concrete range. `assemble_sheet.scrub_sheet` nudges accidental matches; apply
  it to the *whole sheet*, since icons and captions are pasted after the cells.
- **Flag-colour substitution needs a loose test.** An accent rendered in a
  marker colour and swapped for a real Simutrans light shifts a long way from
  the marker once it is seen through glass. An exact match let pink streaks
  through on every junction tile.

## Scripts

- `sheet_inspect.py` — analyse any pak128 sheet: `map`, `crop`, `contact`,
  `profile`, `colors`.
- `pak128_layout.py` — the cell plan, shared by both renderers. Standard
  library only, because Blender's Python has no Pillow.
- `render_maglev_track.py` — the 2D renderer.
- `preview_layout.py` — compose tiles into a map to judge continuity.
- `assemble_sheet.py` — pack Blender cells into a sheet. `--sheet track`
  clips to the tile analytically; `--sheet station|depot|vehicle` uses plain
  coverage, since buildings and vehicles legitimately overhang the tile.
- `blender/simutrans_iso.py` — the reusable isometric rig.
- `blender/build_maglev_track.py` — guideway geometry and the render loop.
- `blender/build_maglev_buildings.py` — stop and depot.
- `blender/build_maglev_vehicle.py` — rolling stock, lofted from one
  cross-section and pointed down each of the eight headings.
  `--variant middle|head` switches between the chamfered trailer and the
  wedge-nosed power car.
- `blender/selftest.py` — pixel-grid assertion.
