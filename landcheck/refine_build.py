#!/usr/bin/env python
"""Build the optional coastal-refinement dataset (TFLR) for landcheck.

For every coastal cell in a TFLS dataset, clips a land-polygon source —
OSM simplified land polygons (https://osmdata.openstreetmap.de/data/land-polygons.html)
are the intended one — to the cell triangle and stores the result as
quantized, delta-encoded rings.  At lookup time a point-in-polygon test
against the clipped rings replaces the coarse land-fraction guess with a
near-exact answer for 'coast' cells.

TFLR v1 layout (little-endian)
------------------------------
  magic    4s   b"TFLR"
  version  u8   1
  level    u8   grid level L (10)
  flags    u8   0
  reserved u8   0
  n_cells  u32
  payload  zlib-deflated stream, cells in ascending canonical index order:
      varint(index - previous index)        (first: index - 0)
      varint(code)   0 = cell is all sea, 1 = all land,
                     n >= 2: (n - 1) rings follow
      per ring: varint(n_points), then n_points x-pairs of
                zigzag-varint deltas in the cell-local u16 grid
                (cell bbox of the unwrapped 3-vertex triangle -> 0..65535)

Rings combine by even-odd rule (exteriors and holes need no distinction).

Usage:
  python landcheck/refine_build.py --land /tmp/osm_simplified_land_polygons.geojson
        [--tfls landcheck/data/landsea_L10.tfls]
        [--out landcheck/data/coastal_osm_L10.tflr]
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))
from _fastloc import index_to_lonlat_ring  # noqa: E402
from landcheck import LandCheck  # noqa: E402

MAGIC = b"TFLR"
VERSION = 1
FULL = 0.999999  # area ratio considered "all land"


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


def zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 63)


def coastal_indexes(lc: LandCheck):
    for start, end, coastal in zip(lc._starts, lc._ends, lc._coastal):
        if coastal:
            yield from range(start, end)


def encode_rings(geoms, bbox):
    """Quantize polygon rings to the cell-local u16 grid; None if degenerate."""
    minx, miny, maxx, maxy = bbox
    sx = 65535.0 / (maxx - minx)
    sy = 65535.0 / (maxy - miny)
    rings = []
    for geom in geoms:
        polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            for ring in (poly.exterior, *poly.interiors):
                pts = []
                for x, y in ring.coords[:-1]:  # drop closing point
                    qx = min(65535, max(0, round((x - minx) * sx)))
                    qy = min(65535, max(0, round((y - miny) * sy)))
                    if not pts or pts[-1] != (qx, qy):
                        pts.append((qx, qy))
                if len(pts) >= 3:
                    rings.append(pts)
    if not rings:
        return None
    body = bytearray()
    for pts in rings:
        body += varint(len(pts))
        px = py = 0
        for qx, qy in pts:
            body += varint(zigzag(qx - px))
            body += varint(zigzag(qy - py))
            px, py = qx, qy
    return len(rings), bytes(body)


def main():
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--land", required=True, type=Path,
                    help="land polygons GeoJSON (OSM simplified recommended)")
    ap.add_argument("--tfls", default=repo / "landcheck/data/landsea_L10.tfls",
                    type=Path)
    ap.add_argument("--out", default=repo / "landcheck/data/coastal_osm_L10.tflr",
                    type=Path)
    args = ap.parse_args()

    from shapely.geometry import Polygon, shape
    from shapely.strtree import STRtree
    from shapely import affinity

    lc = LandCheck(args.tfls)
    level = lc.level

    print(f"loading land polygons from {args.land} ...", flush=True)
    with open(args.land) as f:
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
    print(f"  {len(pieces)} pieces (x3 antimeridian copies)")

    body = bytearray()
    prev = 0
    n_cells = n_sea = n_land = n_mixed = 0
    todo = list(coastal_indexes(lc))
    for done, index in enumerate(todo):
        ring = index_to_lonlat_ring(index, level)
        tri = Polygon(ring)
        tri_area = tri.area
        clipped = []
        land_area = 0.0
        for i in tree.query(tri):
            inter = tri.intersection(extended[i])
            if not inter.is_empty and inter.area > 0.0:
                clipped.append(inter)
                land_area += inter.area
        record = None
        if land_area <= 0.0:
            code = 0
            n_sea += 1
        elif land_area >= FULL * tri_area:
            code = 1
            n_land += 1
        else:
            encoded = encode_rings(clipped, tri.bounds)
            if encoded is None:  # quantized away: snap to majority
                code = 1 if land_area >= 0.5 * tri_area else 0
                n_land += code
                n_sea += 1 - code
            else:
                n_rings, record = encoded
                code = n_rings + 1
                n_mixed += 1
        body += varint(index - prev)
        body += varint(code)
        if record is not None:
            body += record
        prev = index
        n_cells += 1
        if (done + 1) % 20000 == 0:
            print(f"  {done + 1}/{len(todo)} coastal cells", flush=True)

    payload = zlib.compress(bytes(body), 9)
    header = struct.pack("<4sBBBBI", MAGIC, VERSION, level, 0, 0, n_cells)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(header + payload)
    print(f"wrote {args.out}: {n_cells} cells "
          f"(sea {n_sea}, land {n_land}, mixed {n_mixed}), "
          f"{len(body)} B raw -> {len(header) + len(payload)} B file")


if __name__ == "__main__":
    main()
