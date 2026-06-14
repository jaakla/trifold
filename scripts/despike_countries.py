#!/usr/bin/env python3
"""Remove antenna-spike artifacts from countries_coastal.geojson.

The country borders come from the timezone-boundary-builder "with oceans"
polygons (accurate, OSM-derived), but that source carries small "antenna"
artifacts: a ring vertex that pokes out perpendicular to the border and
immediately returns (a near-180 degree reversal), plus a few fully degenerate
near-zero-area rings (e.g. a ring sitting entirely on one latitude). They render
as little spikes / horizontal-vertical lines jutting off the boundary.

This removes them surgically: a vertex is dropped when the interior angle at it
is below ANGLE_MIN (the path reverses), iterated until stable; rings that
collapse or are degenerate slivers are dropped; the result is validated with
shapely. Real border detail (gradual meanders, normal corners) is untouched.

Run from the repository root (writes in place, keeps a .spiked.bak):

    .venv/bin/python scripts/despike_countries.py
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.validation import make_valid

ANGLE_MIN = 30.0       # interior angle (deg) below which a vertex is a spike tip
SLIVER_RATIO = 1e-3    # ring area / bbox-diagonal^2 below this = degenerate sliver
MAX_ITERS = 60


def _interior_angle(a, b, c) -> float:
    coslat = math.cos(math.radians(b[1]))
    v1x, v1y = (a[0] - b[0]) * coslat, a[1] - b[1]
    v2x, v2y = (c[0] - b[0]) * coslat, c[1] - b[1]
    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 == 0 or n2 == 0:
        return 0.0  # duplicate point: treat as removable
    cos = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def _ring_area(pts) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _despike_ring(ring):
    """ring: closed list [[lon,lat],...]; returns cleaned closed ring or None."""
    pts = [tuple(p) for p in ring[:-1]]
    for _ in range(MAX_ITERS):
        m = len(pts)
        if m < 4:
            break
        flagged = {i for i in range(m)
                   if _interior_angle(pts[(i - 1) % m], pts[i], pts[(i + 1) % m])
                   < ANGLE_MIN}
        if not flagged:
            break
        pts = [p for i, p in enumerate(pts) if i not in flagged]
    # drop consecutive duplicates
    dedup = [pts[0]]
    for p in pts[1:]:
        if p != dedup[-1]:
            dedup.append(p)
    pts = dedup
    if len(pts) < 3:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    diag2 = (max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2
    if diag2 == 0 or _ring_area(pts) / diag2 < SLIVER_RATIO:
        return None  # degenerate sliver / zero-height ring
    return pts + [pts[0]]


def _despike_polygon(coords):
    shell = _despike_ring(coords[0])
    if shell is None:
        return None
    holes = [h for h in (_despike_ring(r) for r in coords[1:]) if h is not None]
    return [shell] + holes


def despike_geometry(geom):
    if geom["type"] == "Polygon":
        polys = [p for p in [_despike_polygon(geom["coordinates"])] if p]
    elif geom["type"] == "MultiPolygon":
        polys = [p for p in (_despike_polygon(c) for c in geom["coordinates"]) if p]
    else:
        return geom, 0
    if not polys:
        return None, 0
    parts = [Polygon(p[0], p[1:]) for p in polys]
    g = MultiPolygon(parts) if len(parts) > 1 else parts[0]
    if not g.is_valid:
        g = make_valid(g)
        # keep only polygonal parts
        if g.geom_type == "GeometryCollection":
            polys2 = [x for x in g.geoms if x.geom_type in ("Polygon", "MultiPolygon")]
            g = MultiPolygon([p for x in polys2 for p in
                              (x.geoms if x.geom_type == "MultiPolygon" else [x])])
    if g.geom_type == "Polygon":
        g = MultiPolygon([g])
    return mapping(g), 1


def count_spikes(geom) -> int:
    def rings(gm):
        t = gm["type"]
        c = gm["coordinates"]
        return c if t == "Polygon" else [r for poly in c for r in poly]
    n = 0
    for r in rings(geom):
        m = len(r)
        for i in range(1, m - 1):
            if _interior_angle(r[i - 1], r[i], r[i + 1]) < ANGLE_MIN:
                n += 1
    return n


def npoints(geom) -> int:
    c = geom["coordinates"]
    rs = c if geom["type"] == "Polygon" else [r for poly in c for r in poly]
    return sum(len(r) for r in rs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geojson", type=Path,
                        default=Path("osm-vector/countries_coastal.geojson"))
    args = parser.parse_args()

    data = json.loads(args.geojson.read_text())
    spikes_before = spikes_after = pts_before = pts_after = 0
    area_warn = []
    for f in data["features"]:
        geom = f.get("geometry")
        if not geom:
            continue
        spikes_before += count_spikes(geom)
        pts_before += npoints(geom)
        before = shape(geom)
        new_geom, _ = despike_geometry(geom)
        if new_geom is None:
            continue
        after = shape(new_geom)
        # sanity: relative area change should be tiny (only spikes removed)
        if before.area > 0:
            rel = abs(after.area - before.area) / before.area
            if rel > 0.001:
                area_warn.append((f["properties"]["gid_0"], round(rel * 100, 3)))
        f["geometry"] = new_geom
        spikes_after += count_spikes(new_geom)
        pts_after += npoints(new_geom)

    backup = args.geojson.with_suffix(".spiked.bak")
    if not backup.exists():
        shutil.copy2(args.geojson, backup)
    args.geojson.write_text(json.dumps(data))
    print(f"spike vertices: {spikes_before} -> {spikes_after}")
    print(f"total vertices: {pts_before:,} -> {pts_after:,} "
          f"({pts_before - pts_after:,} removed, "
          f"{100*(pts_before-pts_after)/pts_before:.2f}%)")
    print(f"countries with >0.1% area change: {area_warn or 'none'}")
    print(f"backup: {backup}")


if __name__ == "__main__":
    main()
