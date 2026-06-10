#!/usr/bin/env python
"""Generate the A5 pentagonal DGGS comparison layer (https://a5geo.org).

A5: dodecahedron-based, exactly equal-area pentagons, aperture-4 *logical*
hierarchy (parents do not geometrically contain children exactly — like H3's
approximate containment, unlike Trifold's exact nesting).

Resolution 6 (~8,300 km^2/cell) chosen as the closest match to Trifold L6
(~6,200 km^2) and H3 res 3 (~12,400 km^2).

Output: data/cmp_a5_{compacted,uncompacted}.{geojson,topojson}
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import a5
import numpy as np
from shapely.geometry import Polygon

# reuse the shared land classifier + writers from the comparison script
from build_comparison_dggs import load_land, write, feature


def ring_of(cell):
    """Unwrapped lon/lat ring; polar-cap representation if ring encircles
    a pole (A5 res-0/1 polar cells and any cell with a +/-90 vertex)."""
    b = a5.cell_to_boundary(cell)
    if b and b[0] == b[-1]:
        b = b[:-1]
    # unwrap longitudes to a continuous sequence
    ring = []
    prev = None
    off = 0.0
    for lon, lat in b:
        # a5 may emit lons outside [-180,180]; fold first
        while lon > 180:
            lon -= 360
        while lon < -180:
            lon += 360
        lon += off
        if prev is not None:
            while lon - prev > 180:
                lon -= 360
                off -= 360
            while lon - prev < -180:
                lon += 360
                off += 360
        ring.append((lon, lat))
        prev = lon
    lons = [p[0] for p in ring]
    if max(lons) - min(lons) > 350:            # encircles a pole
        lat_pole = 90.0 if np.mean([p[1] for p in ring]) > 0 else -90.0
        ll = sorted(ring, key=lambda q: q[0])
        ring = ll + [(180.0, lat_pole), (-180.0, lat_pole)]
    else:                                       # recentre near [-180,180]
        mean = np.mean(lons)
        shift = 0.0
        while mean + shift > 180:
            shift -= 360
        while mean + shift <= -180:
            shift += 360
        ring = [(lon + shift, lat) for lon, lat in ring]
    return ring


def poly_of(cell):
    p = Polygon(ring_of(cell))
    return p if p.is_valid else p.buffer(0)


def build_a5(classify, base_res, outdir):
    land_cells = []                    # (cell, interior) at base_res

    def visit(cell):
        r = a5.get_resolution(cell)
        poly = poly_of(cell)
        cls = classify(poly)
        if cls == 'sea':
            if r >= base_res:
                return
            # logical hierarchy: children can spill slightly outside the
            # parent ring, so don't prune coarse 'sea' parents too eagerly —
            # re-test with a buffer of ~one child-cell radius.
            edge_deg = np.degrees(np.sqrt(a5.cell_area(r + 1)) / 6371008.8)
            if classify(poly.buffer(edge_deg)) == 'sea':
                return
        if r == base_res:
            if cls != 'sea':
                land_cells.append((cell, cls == 'interior'))
            return
        for ch in a5.cell_to_children(cell):
            visit(ch)

    for c0 in a5.get_res0_cells():
        visit(c0)

    feats_unc = []
    interiors = []
    for cell, inter in sorted(land_cells):
        if inter:
            interiors.append(cell)
        feats_unc.append(feature(a5.u64_to_hex(cell), base_res, ring_of(cell),
                                 inter, {'area_km2': round(a5.cell_area(base_res)/1e6)}))
    write(feats_unc, 'cmp_a5_uncompacted', outdir)

    comp = a5.compact(interiors)       # native logical compaction
    feats_c = []
    for cell in comp:
        r = a5.get_resolution(cell)
        feats_c.append(feature(a5.u64_to_hex(cell), r, ring_of(cell), True,
                               {'area_km2': round(a5.cell_area(r)/1e6)}))
    for f in feats_unc:
        if not f['properties']['interior']:
            feats_c.append(f)
    write(feats_c, 'cmp_a5_compacted', outdir)
    n_merged = sum(1 for f in feats_c
                   if f['properties']['interior'] and
                   f['properties']['level'] < base_res)
    print(f"    merged interior pentagons above base res: {n_merged}")
    print(f"    (A5 hierarchy is logical: parent rings only approximately "
          f"cover children)")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--land', default='natural-earth-vector/geojson/ne_50m_land.geojson')
    ap.add_argument('--out', default='data')
    ap.add_argument('--res', type=int, default=6)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    classify = load_land(args.land)
    print(f"A5 pentagons (res {args.res}, "
          f"{a5.cell_area(args.res)/1e6:,.0f} km²/cell):")
    build_a5(classify, args.res, args.out)
