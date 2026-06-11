#!/usr/bin/env python
"""Build the bundled landcheck dataset from a compacted Trifold land grid.

Reads ``data/global_tri_L10_compacted.geojson`` (cells at levels <= L with
``interior`` true/false), maps every cell onto the canonical level-L index
space, and writes a compact run-length binary (TFLS format) that the Python
and JavaScript lookup libraries load.

Canonical index
---------------
For a cell address ``a`` (uint64, see trifold.address) at level <= L the
top ``5 + 2L`` bits (face + L path digits) are ``a >> (59 - 2L + 5)``;
for L=10 that is ``a >> 39``.  A level-l cell covers exactly ``4**(L-l)``
consecutive indices.  The whole Earth is ``20 * 4**L`` indices.

TFLS v1 layout (little-endian)
------------------------------
  magic    4s   b"TFLS"
  version  u8   1
  level    u8   grid level L (10)
  flags    u8   bit0 = coastal land fractions present
  reserved u8   0
  n_runs   u32  number of land runs
  n_coast  u32  total coastal cells (sum of coastal run lengths)
  payload  zlib-deflated stream of:
      runs:      per run, varint(gap from previous run end)
                 then varint((length << 1) | coastal)
      fractions: if flags bit0, ceil(n_coast/2) bytes, one 4-bit value
                 per coastal cell in run order; fraction = (q + 0.5) / 16

Gaps between runs are sea.  ``coastal`` runs are mixed land/sea cells
(``interior: false``); non-coastal runs are certain land.

Usage:
  python landcheck/build.py [--grid data/global_tri_L10_compacted.geojson]
        [--land natural-earth-vector/geojson/ne_50m_land.geojson]
        [--out landcheck/data/landsea_L10.tfls] [--no-fractions]
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import zlib
from pathlib import Path

MAGIC = b"TFLS"
VERSION = 1
LEVEL_FIELD_BITS = 5  # addr64 low bits


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def cell_to_span(addr64: int, level_target: int) -> tuple[int, int, int]:
    """(base index, span, level) of a cell in the canonical level-L space."""
    level = addr64 & 0x1F
    if level > level_target:
        raise ValueError(f"cell level {level} > target level {level_target}")
    shift = 59 - 2 * level_target  # drop level field + unused path bits
    base = addr64 >> shift
    return base, 4 ** (level_target - level), level


def load_cells(grid_path: Path, level_target: int):
    """Yield (base, span, coastal, geometry) per cell, sorted by base."""
    print(f"reading {grid_path} ...", flush=True)
    with open(grid_path) as f:
        collection = json.load(f)
    cells = []
    for feature in collection["features"]:
        props = feature["properties"]
        addr = int(props["addr64"])
        base, span, level = cell_to_span(addr, level_target)
        coastal = not props["interior"]
        if coastal and level != level_target:
            raise ValueError(
                f"coastal cell {props['id']} at level {level}, expected {level_target}")
        cells.append((base, span, coastal, feature["geometry"]))
    cells.sort(key=lambda c: c[0])
    prev_end = -1
    for base, span, _, _ in cells:
        if base <= prev_end:
            raise ValueError(f"overlapping cells at index {base}")
        prev_end = base + span - 1
    print(f"  {len(cells)} cells, "
          f"{sum(c[1] for c in cells)} level-{level_target} equivalents")
    return cells


def build_runs(cells):
    """Merge adjacent same-state cells into (start, length, coastal) runs."""
    runs = []
    for base, span, coastal, _ in cells:
        if runs and runs[-1][2] == coastal and runs[-1][0] + runs[-1][1] == base:
            runs[-1][1] += span
        else:
            runs.append([base, span, coastal])
    return runs


def coastal_fractions(cells, land_path: Path):
    """Exact land-area fraction of each coastal cell, keyed by base index.

    Computed in lon/lat: over a ~7 km cell the plate-carree mapping is
    locally affine, and affine maps preserve area ratios, so the fraction
    matches the spherical one to far better than the 4-bit quantization.
    Antimeridian cells (continuous longitudes >180) are handled by also
    testing land translated +-360 degrees.
    """
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    from shapely import affinity

    print(f"loading land polygons from {land_path} ...", flush=True)
    with open(land_path) as f:
        land = json.load(f)
    pieces = []
    for feature in land["features"]:
        geom = shape(feature["geometry"])
        if geom.geom_type == "Polygon":
            pieces.append(geom)
        else:
            pieces.extend(geom.geoms)
    extended = []
    for dx in (-360.0, 0.0, 360.0):
        for p in pieces:
            extended.append(affinity.translate(p, xoff=dx) if dx else p)
    tree = STRtree(extended)
    print(f"  {len(pieces)} land pieces (x3 antimeridian copies)")

    fractions = {}
    coastal = [(base, geom) for base, _, c, geom in cells if c]
    for i, (base, geom) in enumerate(coastal):
        poly = shape(geom)
        area = poly.area
        if area <= 0.0:
            fractions[base] = 0.5
            continue
        land_area = 0.0
        for idx in tree.query(poly):
            inter = poly.intersection(extended[idx])
            if not inter.is_empty:
                land_area += inter.area
        fractions[base] = min(1.0, land_area / area)
        if (i + 1) % 20000 == 0:
            print(f"  {i + 1}/{len(coastal)} coastal cells", flush=True)
    return fractions


def write_tfls(out_path: Path, level: int, runs, fractions=None):
    body = bytearray()
    prev_end = 0
    for start, length, coastal in runs:
        body += varint(start - prev_end)
        body += varint((length << 1) | int(coastal))
        prev_end = start + length

    n_coast = sum(length for _, length, c in runs if c)
    flags = 0
    if fractions is not None:
        flags |= 1
        nibbles = bytearray(math.ceil(n_coast / 2))
        pos = 0
        for start, length, coastal in runs:
            if not coastal:
                continue
            for base in range(start, start + length):
                q = min(15, int(fractions[base] * 16.0))
                if pos & 1:
                    nibbles[pos >> 1] |= q << 4
                else:
                    nibbles[pos >> 1] = q
                pos += 1
        assert pos == n_coast
        body += nibbles

    payload = zlib.compress(bytes(body), 9)
    header = struct.pack("<4sBBBBII", MAGIC, VERSION, level, flags, 0,
                         len(runs), n_coast)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + payload)
    print(f"wrote {out_path}: {len(runs)} runs, {n_coast} coastal cells, "
          f"{len(body)} B raw -> {len(header) + len(payload)} B file")


def main():
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--grid", default=repo / "data/global_tri_L10_compacted.geojson",
                    type=Path)
    ap.add_argument("--land", default=repo / "natural-earth-vector/geojson/ne_50m_land.geojson",
                    type=Path)
    ap.add_argument("--out", default=repo / "landcheck/data/landsea_L10.tfls",
                    type=Path)
    ap.add_argument("--level", type=int, default=10)
    ap.add_argument("--no-fractions", action="store_true",
                    help="skip coastal land fractions (smaller, less confident)")
    args = ap.parse_args()

    cells = load_cells(args.grid, args.level)
    runs = build_runs(cells)
    print(f"  {len(runs)} runs after merging")

    fractions = None
    if not args.no_fractions:
        if not args.land.exists():
            sys.exit(f"land dataset not found: {args.land} "
                     f"(pass --land PATH or --no-fractions)")
        fractions = coastal_fractions(cells, args.land)

    write_tfls(args.out, args.level, runs, fractions)


if __name__ == "__main__":
    main()
