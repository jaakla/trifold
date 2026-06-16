#!/usr/bin/env python3
"""Decode a borders_L10.tfcr (+ its TFCS) back to standard GeoJSON.

The TFCR stores, per level-10 border cell, one or more country "zones"; each
zone is a set of rings quantized to a cell-local 16-bit grid and filled with the
even-odd rule. This tool reverses that so the geometry can be inspected/rendered
in any GIS (QGIS, geojson.io, ...).

Modes (``--mode``):
  polygons  one (Multi)Polygon per cell-zone, even-odd resolved   [default]
            -> fill-render this; it is the exact area the refined lookup tests.
  rings     every raw ring as a LineString, nothing filtered
            -> shows ALL edges, including cell-clip edges and artifacts.
  borders   border lines after the debug-layer artifact filter
            (drop segments along a triangle edge, and same-country internal
             clip-cuts) -> what the web "source border polygons" layer draws.

Use ``--bbox W,S,E,N`` to limit output to a region (recommended; the global
file is large). Example:

    .venv/bin/python scripts/tfcr_to_geojson.py \
        --tfcr countrycheck/data/borders_L10.tfcr \
        --bbox 13.6,48.6,14.1,48.95 --mode borders -o /tmp/border_lines.geojson
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "countrycheck" / "python"))

from countrycheck import CountryCheck, _ringbox  # noqa: E402
import _fastloc  # noqa: E402


def _cell_lonlat(index, level, minx, miny, sx, sy, pts):
    """quantized int pairs -> [[lon,lat],...]"""
    m = len(pts) // 2
    return [[minx + pts[2 * i] * sx, miny + pts[2 * i + 1] * sy] for i in range(m)]


def _even_odd_polygon(rings):
    """rings: list of [[lon,lat],...]; return a GeoJSON geometry (even-odd XOR)."""
    from shapely.geometry import Polygon, mapping
    polys = []
    for r in rings:
        if len(r) >= 3:
            p = Polygon(r)
            polys.append(p if p.is_valid else p.buffer(0))
    if not polys:
        return None
    acc = polys[0]
    for p in polys[1:]:
        acc = acc.symmetric_difference(p)
    if acc.is_empty:
        return None
    return mapping(acc)


def _seg_iter(geom):
    if geom.geom_type == "LineString":
        cs = list(geom.coords)
        for i in range(len(cs) - 1):
            yield cs[i], cs[i + 1]
    elif geom.geom_type in ("MultiLineString", "GeometryCollection",
                            "MultiPolygon", "Polygon"):
        if geom.geom_type == "Polygon":
            yield from _seg_iter(geom.boundary)
        else:
            for g in geom.geoms:
                yield from _seg_iter(g)


def _border_lines(index, zones, level, minx, miny, sx, sy):
    """Clean border lines: dissolve each country's rings (even-odd) into one
    polygon so split-piece and clip-cut seams within a country disappear, then
    drop the parts lying on the cell's triangle edges (cell-clip boundaries).
    What survives is real country/country borders and coastlines."""
    tri = [(p[0], p[1]) for p in _fastloc.index_to_lonlat_ring(index, level)]
    edges_ll = []
    for i in range(3):
        a, c = tri[i], tri[(i + 1) % 3]
        edges_ll.append((a[0], a[1], c[0] - a[0], c[1] - a[1]))

    def on_tri_edge(p, q):
        # both endpoints within ~6 m of the same triangle-edge line
        for ax, ay, dx, dy in edges_ll:
            L = math.hypot(dx, dy)
            if L == 0:
                continue
            dp = abs((p[0] - ax) * dy - (p[1] - ay) * dx) / L * 111320.0
            dq = abs((q[0] - ax) * dy - (q[1] - ay) * dx) / L * 111320.0
            if dp < 6 and dq < 6:
                return True
        return False

    out = []
    for cid, rings in zones:
        if rings is None:
            continue
        ll_rings = [_cell_lonlat(index, level, minx, miny, sx, sy, pts)
                    for pts in rings]
        geom = _even_odd_polygon(ll_rings)
        if geom is None:
            continue
        from shapely.geometry import shape
        poly = shape(geom)
        cur = []
        for p, q in _seg_iter(poly):
            if on_tri_edge(p, q):
                if len(cur) > 1:
                    out.append((cid, cur))
                cur = []
            else:
                if not cur:
                    cur.append([p[0], p[1]])
                cur.append([q[0], q[1]])
        if len(cur) > 1:
            out.append((cid, cur))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfcr", default="countrycheck/data/borders_L10.tfcr")
    ap.add_argument("--tfcs", default="countrycheck/data/countries_L10.tfcs")
    ap.add_argument("--mode", choices=("polygons", "rings", "borders"),
                    default="polygons")
    ap.add_argument("--bbox", help="W,S,E,N to clip output (lon/lat degrees)")
    ap.add_argument("-o", "--out", default="/dev/stdout")
    args = ap.parse_args()

    cc = CountryCheck(args.tfcs, refine_path=args.tfcr)
    level = cc.level
    bbox = None
    if args.bbox:
        bbox = tuple(float(v) for v in args.bbox.split(","))

    def in_bbox(minx, miny, maxx, maxy):
        if bbox is None:
            return True
        W, S, E, N = bbox
        return not (maxx < W or minx > E or maxy < S or miny > N)

    feats = []
    n_cells = 0
    for index, zones in cc._refine.items():
        minx, miny, maxx, maxy = _ringbox(index, level)
        if not in_bbox(minx, miny, maxx, maxy):
            continue
        n_cells += 1
        sx, sy = (maxx - minx) / 65535.0, (maxy - miny) / 65535.0

        if args.mode == "borders":
            for cid, line in _border_lines(index, zones, level, minx, miny, sx, sy):
                c = cc.countries[cid]
                feats.append({"type": "Feature",
                              "properties": {"cell": index, "cid": cid,
                                             "code": c["code"], "name": c["name"]},
                              "geometry": {"type": "LineString", "coordinates": line}})
            continue

        for cid, rings in zones:
            c = cc.countries[cid]
            props = {"cell": index, "cid": cid, "code": c["code"],
                     "iso2": c["iso2"], "name": c["name"]}
            if rings is None:  # whole-cell zone -> the triangle itself
                tri = [[p[0], p[1]] for p in _fastloc.index_to_lonlat_ring(index, level)]
                tri.append(tri[0])
                if args.mode == "rings":
                    feats.append({"type": "Feature", "properties": props,
                                  "geometry": {"type": "LineString", "coordinates": tri}})
                else:
                    feats.append({"type": "Feature", "properties": props,
                                  "geometry": {"type": "Polygon", "coordinates": [tri]}})
                continue
            ll_rings = [_cell_lonlat(index, level, minx, miny, sx, sy, pts) for pts in rings]
            if args.mode == "rings":
                for r in ll_rings:
                    feats.append({"type": "Feature", "properties": props,
                                  "geometry": {"type": "LineString",
                                               "coordinates": r + [r[0]]}})
            else:  # polygons
                geom = _even_odd_polygon(ll_rings)
                if geom is not None:
                    feats.append({"type": "Feature", "properties": props,
                                  "geometry": geom})

    fc = {"type": "FeatureCollection", "features": feats}
    Path(args.out).write_text(json.dumps(fc))
    print(f"{args.mode}: {n_cells:,} cells in bbox -> {len(feats):,} features "
          f"-> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
