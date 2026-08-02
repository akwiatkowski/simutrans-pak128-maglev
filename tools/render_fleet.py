#!/usr/bin/env python3
"""Render and pack every trainset in the roster.

Drives Blender once per sheet — head, passenger car and mail van for each of
the sixteen trainsets in `gen_vehicle_roster.ROSTER` — then packs each into a
vehicle sheet. Proportions come from the set's own speed and grade, so no two
trainsets share a silhouette.

    python3 tools/render_fleet.py                  # everything, ~8 minutes
    python3 tools/render_fleet.py --only Meridian  # one manufacturer
    python3 tools/render_fleet.py --samples 32     # rough and quick
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen_vehicle_roster as roster  # noqa: E402

BUILDER = "tools/blender/build_maglev_vehicle.py"
PACKER = "tools/assemble_sheet.py"
PARTS = (("head", "head", False), ("car", "middle", False), ("mail", "middle", True))


def render(part, variant, mail, company, speed, grade, cells, samples, blender):
    cmd = [blender, "--background", "--python", BUILDER, "--",
           "--variant", variant, "--livery", roster.COMPANY_LIVERY[company],
           "--grade", grade, "--speed", str(speed),
           "--out", str(cells), "--samples", str(samples)]
    if mail:
        cmd.append("--mail")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="src/maglev/images")
    parser.add_argument("--work", default="build/fleet")
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--only", help="only sets from this manufacturer")
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(args.work)

    sets = [e for e in roster.ROSTER if not args.only or e[0] == args.only]
    total = len(sets) * len(PARTS)
    done = 0

    for company, speed, grade, _intro in sets:
        for part, variant, mail in PARTS:
            tag = f"{roster.COMPANY_LIVERY[company]}{speed}"
            cells = work / f"{part}_{tag}"
            cells.mkdir(parents=True, exist_ok=True)
            render(part, variant, mail, company, speed, grade,
                   cells, args.samples, args.blender)
            sheet = out / f"maglev_{part}_{tag}.png"
            subprocess.run([args.python, PACKER, str(cells), "-o", str(sheet),
                            "--sheet", "vehicle"], check=True,
                           stdout=subprocess.DEVNULL)
            done += 1
            print(f"[{done}/{total}] {sheet.name}", flush=True)

    print(f"rendered {done} sheets for {len(sets)} trainsets")


if __name__ == "__main__":
    main()
