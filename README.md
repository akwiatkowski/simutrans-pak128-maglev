# Simutrans pak128 Maglev

Standalone pak128 addon source for a playable maglev prototype.

This repository is intentionally separate from the Simutrans engine and from
the downloaded base `pak128/` directory. Editable assets belong under
`src/maglev/`. Generated `.pak` files belong under `dist/` and are ignored.
The official pak128 source checkout is kept under `upstream/` as a local
reference and is intentionally not vendored into this repository.

## Current Milestone

The first milestone is one complete passenger service:

- maglev track
- compatible station
- compatible depot
- one passenger maglev train
- one mostly straight test route long enough to show top speed

The first graphics pass will use placeholders or reused pak128-style assets.
Original isometric artwork comes after the data and packaging pipeline works.

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
