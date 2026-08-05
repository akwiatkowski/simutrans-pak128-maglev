#!/usr/bin/env python3
"""Validate the asset sources before makeobj sees them.

Every failure this checks for has actually shipped in this repository at least
once. The pipeline's characteristic fault is silent drift — a generator and its
consumer agree on a filename or a colour by convention, nothing enforces it, and
the result looks fine until it doesn't:

- a sheet was renamed per-trainset but the `.dat` generator still emitted the
  old per-company name, so 64 vehicles pointed at a file that no longer existed
- an accent rendered in a marker colour was only converted to a real Simutrans
  light where it was unoccluded, leaving 11,096 magenta pixels on a shipped
  sheet
- reserved "do not darken at night" greys sat in the concrete range and slipped
  into the icon row, which the per-cell guard never looked at

    python3 tools/check_assets.py            # all checks
    python3 tools/check_assets.py --quiet    # only failures

Exit status is non-zero if anything fails, so it can gate a build.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pak128_layout as layout  # noqa: E402
from assemble_sheet import (LIGHT_BLUE, LIGHT_GREEN, LIGHT_RED,  # noqa: E402
                            SPECIAL_COLOURS)

SOURCE = pathlib.Path("src/maglev")
IMAGES = SOURCE / "images"
CELL = layout.CELL
KEY = np.array(layout.KEY)

def parse_ref(value):
    """`> ../images/sheet.1.5,0,-16` -> ("../images/sheet", 1, 5).

    The name may be a relative path, so the row and column are taken as the
    last two dot-separated components rather than matched by pattern.
    """
    value = value.split(",")[0].strip().lstrip(">").strip()
    parts = value.rsplit(".", 2)
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        return parts[0], int(parts[1]), int(parts[2])
    return None

# Sheets that legitimately carry per-pixel alpha (glazing).
RGBA_EXPECTED = re.compile(r"maglev_(tube|concourse)")

# Sheets that legitimately carry the reserved #7F9BF1 light: the tubes' cove,
# the concourse's cove, the depot's lit door portal and pit strips, and the
# open track's lit fence-base rails (tier 700).
LIGHT_EXPECTED = re.compile(r"maglev_(tube|concourse|depot|track)")


class Report:
    def __init__(self, quiet: bool):
        self.quiet, self.failures = quiet, 0

    def ok(self, label, detail=""):
        if not self.quiet:
            print(f"  PASS  {label}{'  ' + detail if detail else ''}")

    def fail(self, label, detail):
        self.failures += 1
        print(f"  FAIL  {label}  {detail}")


def load_sheets():
    """The addon's own sheets.

    Only `images/` — `versions/` holds gitignored pak128-derived snapshots whose
    filenames collide with the real ones, and scanning by bare stem meant the
    first version of this checker was validating pak128's artwork instead.
    """
    return {png: Image.open(png) for png in sorted(IMAGES.glob("*.png"))}


def dat_image_refs():
    """Every (dat, key, sheet-name, row, col) referenced across the sources."""
    for dat in sorted(SOURCE.rglob("*.dat")):
        for line in dat.read_text().splitlines():
            line = line.split("#", 1)[0]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            if not value.strip() or "image" not in key.lower() and \
               key.strip().lower() not in ("icon", "cursor"):
                continue
            ref = parse_ref(value)
            if ref:
                yield (dat, key.strip(), *ref)


def check_references(sheets, report):
    """Does every image reference resolve to a real, non-empty cell?

    Resolution is relative to the .dat's own directory, which is how makeobj
    does it — root dats say `images/x`, vehicle dats say `../images/x`.
    """
    missing_file = collections.Counter()
    empty_cell, checked = [], 0
    cache = {}
    for dat, key, name, row, col in dat_image_refs():
        checked += 1
        path = (dat.parent / f"{name}.png").resolve()
        if not path.exists():
            missing_file[(dat.name, name)] += 1
            continue
        if path not in cache:
            cache[path] = Image.open(path)
        img = cache[path]
        if (col + 1) * CELL > img.width or (row + 1) * CELL > img.height:
            empty_cell.append(f"{dat.name}:{key} -> {name}.{row}.{col} is outside the sheet")
            continue
        tile = np.array(img.convert("RGB"))[row*CELL:(row+1)*CELL, col*CELL:(col+1)*CELL]
        if bool((tile == KEY).all(axis=-1).all()):
            empty_cell.append(f"{dat.name}:{key} -> {name}.{row}.{col} is blank")

    if missing_file:
        for (dat, name), n in missing_file.most_common(5):
            report.fail("image reference", f"{dat} points at missing sheet {name}.png ({n} refs)")
    if empty_cell:
        for line in empty_cell[:5]:
            report.fail("image reference", line)
        if len(empty_cell) > 5:
            report.fail("image reference", f"...and {len(empty_cell)-5} more")
    if not missing_file and not empty_cell:
        report.ok("image references", f"{checked} refs resolve to non-empty cells")


def check_transparency(sheets, report):
    """RGB sheets must use the #E7FFFF key; glazed sheets must carry alpha."""
    bad = []
    for path, img in sorted(sheets.items()):
        name = path.stem
        wants_alpha = bool(RGBA_EXPECTED.search(name))
        has_alpha = img.mode == "RGBA"
        if wants_alpha and not has_alpha:
            bad.append(f"{path.name} is {img.mode}, glazing needs RGBA")
        elif not wants_alpha:
            arr = np.array(img.convert("RGB")).reshape(-1, 3)
            if not (arr == KEY).all(axis=-1).any():
                bad.append(f"{path.name} has no #E7FFFF pixels — wrong transparency key?")
    for line in bad:
        report.fail("transparency", line)
    if not bad:
        report.ok("transparency", f"{len(sheets)} sheets")


def check_reserved_colours(sheets, report):
    """No accidental hits on Simutrans' 31 reserved colours.

    The intended light (#7F9BF1) is allowed on glazed sheets, where it is the
    tube's night cove; the signal sheet additionally carries the reserved
    red and green lamp lights. Anywhere else a hit would be an accident.
    """
    light = (LIGHT_BLUE[0] << 16) | (LIGHT_BLUE[1] << 8) | LIGHT_BLUE[2]
    lamp_red = (LIGHT_RED[0] << 16) | (LIGHT_RED[1] << 8) | LIGHT_RED[2]
    lamp_green = (LIGHT_GREEN[0] << 16) | (LIGHT_GREEN[1] << 8) | LIGHT_GREEN[2]
    reserved = np.fromiter(SPECIAL_COLOURS, dtype=np.uint32)
    bad = []
    for path, img in sorted(sheets.items()):
        name = path.stem
        a = np.array(img.convert("RGB")).astype(np.uint32)
        packed = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
        hits = np.isin(packed, reserved)
        if LIGHT_EXPECTED.search(name):
            hits &= packed != light
        if "signal" in name:
            hits &= (packed != lamp_red) & (packed != lamp_green)
        n = int(hits.sum())
        if n:
            found = sorted({int(v) for v in packed[hits]})[:3]
            bad.append(f"{path.name}: {n} px on reserved colours "
                       + ", ".join(f"#{v:06X}" for found_v in [found] for v in found_v))
    for line in bad:
        report.fail("reserved colours", line)
    if not bad:
        report.ok("reserved colours", "no accidental hits")


def check_marker_leak(sheets, report):
    """No leftover marker colour from the flag-to-light substitution."""
    bad = []
    for path, img in sorted(sheets.items()):
        a = np.array(img.convert("RGB")).astype(int)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        n = int((((r - g) > 22) & ((b - g) > 22)).sum())
        if n:
            bad.append(f"{path.name}: {n} px still magenta-ish (marker not converted)")
    for line in bad:
        report.fail("marker leak", line)
    if not bad:
        report.ok("marker leak", "no unconverted markers")


def check_translations(report):
    """Every object name should have a display name."""
    tab = SOURCE / "text" / "en.tab"
    if not tab.exists():
        report.fail("translations", "src/maglev/text/en.tab is missing")
        return
    lines = [l for l in tab.read_text().splitlines() if l and not l.startswith("#")]
    keys = set(lines[1::2]) | set(lines[0::2])
    names = {line.split("=", 1)[1].strip()
             for dat in SOURCE.rglob("*.dat")
             for line in dat.read_text().splitlines()
             if line.lower().startswith("name=")}
    missing = sorted(names - keys)
    if missing:
        report.fail("translations", f"{len(missing)} objects have no display name, "
                                    f"e.g. {', '.join(missing[:3])}")
    else:
        report.ok("translations", f"{len(names)} objects named")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    report = Report(args.quiet)
    sheets = load_sheets()
    print(f"checking {len(sheets)} sheets and "
          f"{len(list(SOURCE.rglob('*.dat')))} dat files")
    check_references(sheets, report)
    check_transparency(sheets, report)
    check_reserved_colours(sheets, report)
    check_marker_leak(sheets, report)
    check_translations(report)

    if report.failures:
        print(f"\n{report.failures} check(s) failed")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
