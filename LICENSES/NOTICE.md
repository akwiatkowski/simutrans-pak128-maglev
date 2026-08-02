# Asset Notices

## What this repository contains

All artwork, `.dat` definitions, tooling and documentation committed here are
**original work** for this addon, licensed under Artistic License 2.0 — the same
license pak128 uses, so the addon stays compatible with the pakset it extends.
A copy of the license is included as `LICENSES/ARTISTIC-2.0.txt`.

Every sprite sheet is generated from source in `tools/`, not drawn over or
traced from pak128 material. The sheets share pak128's *conventions* — cell
grid, tile geometry, direction mapping, transparency key, lighting — because
an addon has to; they do not share its pixels.

## What this repository does NOT contain

No pak128 artwork is redistributed here. Three directories hold pak128-derived
material and are deliberately gitignored:

- `upstream/` — a local checkout of the official pak128 source, used purely for
  measurement and reference.
- `reference/` — way files extracted from an installed pak128 package.
- `src/maglev/versions/` — early prototype snapshots. These were literal copies
  of pak128 rail artwork (`v0-rail-placeholder/maglev_track.png` is
  pixel-for-pixel identical to `rail_400_tracks.png`) or tinted derivatives of
  it. They are kept locally as history only.

pak128 itself is Artistic License 2.0; its author credits are in the upstream
checkout's `doc/authors.txt`. Anyone copying or redistributing material from
those three directories is redistributing pak128, not this addon, and should
carry the upstream attribution accordingly.
