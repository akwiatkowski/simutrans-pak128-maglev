# Documentation

Design notes for the pak — what each object is, why it looks and behaves the way
it does. Start at the [project README](../README.md) for what this add-on is and
how to build and install it.

| Document | Covers |
|---|---|
| [guideways.md](guideways.md) | The seven way tiers, junctions, bridges, tunnels, signals, and the way-builder tuning the add-on installs |
| [stations.md](stations.md) | The five stops and the depot, how a station sprite is layered, and the rendered gallery |
| [rolling-stock.md](rolling-stock.md) | Trainset anatomy, why bodies change shape up the speed ladder, and all sixteen sets with worked economics |

Two documents live outside this directory, next to what they describe:

- [`../tools/README.md`](../tools/README.md) — the artwork pipeline: what was
  measured off pak128, the Blender rig, the sprite-sheet conventions, and how to
  add a new asset. Its paths are relative to `tools/`, which is why it stays
  there.
- [`../src/maglev/README.md`](../src/maglev/README.md) — the source directory
  layout and the display-name file.

Architecture decisions are logged in [`../ADR_DECISIONS.md`](../ADR_DECISIONS.md).

## Regenerating the galleries

The station gallery in `stations.md` and the trainset showcases in
`rolling-stock.md` are generated, injected between HTML comment markers:

```sh
make docs              # both
make docs-stations     # station gallery only
make docs-trains       # trainset showcases + economics only
```

Both need Pillow, neither needs Blender — they composite sheets that are already
rendered. Re-run `make docs-trains` after any change to the vehicle roster, or
the economics paragraphs will describe trains that no longer exist.
