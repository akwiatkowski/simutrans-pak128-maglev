# Maglev Source Assets

Editable maglev `.dat` files and source images live in this directory, kept
apart: infrastructure `.dat` files sit at the root, the generated vehicle `.dat`
files in `vehicles/`, and every sprite sheet in `images/` — dat files reference
them as `images/...` (root) or `../images/...` (vehicles). The asset Makefile
writes generated `.pak` files to `dist/`.

All original maglev assets in this directory use Artistic License 2.0.

**Design notes for these objects are in [`docs/`](../../docs/):**
[guideways](../../docs/guideways.md) · [stops and depot](../../docs/stations.md)
· [rolling stock](../../docs/rolling-stock.md). How the artwork is generated is
in [`tools/README.md`](../../tools/README.md).

## Display names

`text/en.tab` carries the display names; `make install` copies it to
`addons/pak128/text/`, which is where Simutrans looks for addon translations
(`dataobj/translator.cc`). Without it the depot list shows raw object ids.
Regenerate it alongside the roster.

## Historical artwork

`versions/` keeps earlier passes for reference. They are not compiled, and are
git-ignored because they contain literal pak128 material:

- `v0-rail-placeholder/` — the original reused pak128 rail images
- `v1-blue-guideway/` — first tint pass

Gameplay track versions are the compiled `.dat` speed tiers, not these
directories.
