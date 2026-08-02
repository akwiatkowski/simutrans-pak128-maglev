# Architecture Decision Records

## ADR-1: Buildings may ship RGBA sheets (concourse)
- **Context**: The roofed concourse's glass canopy needs per-pixel alpha; the
  `#E7FFFF` key used by building sheets cannot express it.
- **Decision**: `assemble_sheet.py --sheet concourse` packs an RGBA sheet,
  exactly like the tube way sheets, with the same makeobj alpha-floor clamp.
- **Alternatives**: near-opaque fake glass on an RGB sheet — rejected, a train
  waiting under the canopy would be invisible, killing the front/back split's
  whole point.
- **Consequences**: the checker's RGBA/reserved-light expectations are regex
  lists (`maglev_(tube|concourse)`) that must grow with each glazed sheet.

## ADR-2: One superellipse family for every curved shell
- **Context**: The depot's half-ellipse vault read as a barn; the new depot and
  concourse both needed engineered curved roofs.
- **Decision**: `simutrans_iso.arch()` (superellipse, exponent 2.6) is the
  single source for the tube, depot vault and concourse canopy; buildings pick
  their own spans, and the concourse reuses the tube's 8m hoop grid.
- **Alternatives**: per-building bespoke curves — rejected, silhouette kinship
  is what makes the set read as one system at 128px.
- **Consequences**: changing the exponent reshapes every shell in the pak at
  the next render; that coupling is intentional.
