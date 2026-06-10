#!/usr/bin/env python
"""Generate comparison DGGS layers (land-adaptive compacted + uniform):

  * h3       — hexagons (Uber H3, aperture 7), res 3 (~12,400 km2 avg)
  * cubequad — quadtree on cube-sphere faces (S2-like, aperture 4), level 5
  * rectquad — plain lon/lat quadtree (aperture 4), level 5

Resolutions are chosen to give cell areas within ~2x of trifold L6
(~6,200 km2 avg) so the visual comparison is fair-ish; exact area
equality across systems is impossible (different apertures).

Output: data/cmp_{system}_{mode}.geojson (+ .topojson)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import geopandas as gpd
from shapely.geometry import Polygon, box, mapping
from shapely.prepared import prep
from shapely.strtree import STRtree
from shapely import affinity


# ----------------------------------------------------------------- shared
def load_land(path):
    land = gpd.read_file(path)
    pieces = []
    for geom in land.geometry:
        pieces.extend(geom.geoms if geom.geom_type == 'MultiPolygon' else [geom])
    ext, src = [], []
    for dx in (-360.0, 0.0, 360.0):
        for p in pieces:
            ext.append(affinity.translate(p, xoff=dx) if dx else p)
    tree = STRtree(ext)
    preps = {}
    def classify(poly):
        cand = tree.query(poly)
        hit = False
        for i in cand:
            i = int(i)
            if i not in preps:
                preps[i] = prep(ext[i])
            pg = preps[i]
            if pg.contains(poly):
                return 'interior'
            if not hit and pg.intersects(poly):
                hit = True
        return 'mixed' if hit else 'sea'
    return classify


def write(feats, name, outdir):
    fc = {'type': 'FeatureCollection', 'features': feats}
    gj = os.path.join(outdir, f'{name}.geojson')
    with open(gj, 'w') as f:
        json.dump(fc, f, separators=(',', ':'))
    import topojson
    topo = topojson.Topology(fc, prequantize=1e6)
    tj = gj.replace('.geojson', '.topojson')
    with open(tj, 'w') as f:
        f.write(topo.to_json())
    print(f"  {name}: {len(feats)} cells | geojson "
          f"{os.path.getsize(gj)/1e6:.1f} MB | topojson "
          f"{os.path.getsize(tj)/1e6:.1f} MB")


def feature(cell_id, level, ring, interior, extra=None):
    coords = [[round(x, 5), round(y, 5)] for x, y in ring]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    props = {'id': str(cell_id), 'level': int(level),
             'interior': bool(interior)}
    if extra:
        props.update(extra)
    return {'type': 'Feature', 'properties': props,
            'geometry': {'type': 'Polygon', 'coordinates': [coords]}}


# ----------------------------------------------------------------- H3
def build_h3(classify, res, outdir):
    import h3
    # 1. uniform: all cells whose boundary intersects land
    base0 = h3.get_res0_cells()
    land_cells = set()

    def ring_of(c):
        b = h3.cell_to_boundary(c)            # [(lat, lon), ...]
        lons = [q[1] for q in b]
        # unwrap antimeridian
        ring = []
        prev = None
        off = 0.0
        for lat, lon in b:
            lon += off
            if prev is not None:
                while lon - prev > 180:
                    lon -= 360; off -= 360
                while lon - prev < -180:
                    lon += 360; off += 360
            ring.append((lon, lat))
            prev = lon
        return ring

    def visit(c):
        r = h3.get_resolution(c)
        poly = Polygon(ring_of(c))
        if not poly.is_valid:
            poly = poly.buffer(0)
        cls = classify(poly)
        if cls == 'sea':
            return
        if r == res:
            land_cells.add(c)
            return
        for ch in h3.cell_to_children(c):
            visit(ch)

    for c in base0:
        visit(c)

    feats_unc = []
    interiors = []
    for c in sorted(land_cells):
        poly = Polygon(ring_of(c))
        cls = classify(poly if poly.is_valid else poly.buffer(0))
        inter = cls == 'interior'
        if inter:
            interiors.append(c)
        feats_unc.append(feature(c, res, ring_of(c), inter,
                                 {'pent': h3.is_pentagon(c)}))
    write(feats_unc, f'cmp_h3_uncompacted', outdir)

    # 2. compacted: H3 native compaction of the interior set + coastal
    comp = h3.compact_cells(interiors)
    feats_c = []
    for c in comp:
        feats_c.append(feature(c, h3.get_resolution(c), ring_of(c), True,
                               {'pent': h3.is_pentagon(c)}))
    for f in feats_unc:
        if not f['properties']['interior']:
            feats_c.append(f)
    write(feats_c, f'cmp_h3_compacted', outdir)
    print(f"    (note: H3 aperture 7 -> parent does NOT exactly contain "
          f"children; compaction is approximate by design)")


# ------------------------------------------------------- cube-sphere quad
CUBE_FACES = [  # (axis, sign): +x,-x,+y,-y,+z,-z with (u,v) tangent axes
    (np.array([1, 0, 0]), np.array([0, 1, 0]), np.array([0, 0, 1])),
    (np.array([-1, 0, 0]), np.array([0, -1, 0]), np.array([0, 0, 1])),
    (np.array([0, 1, 0]), np.array([-1, 0, 0]), np.array([0, 0, 1])),
    (np.array([0, -1, 0]), np.array([1, 0, 0]), np.array([0, 0, 1])),
    (np.array([0, 0, 1]), np.array([0, 1, 0]), np.array([-1, 0, 0])),
    (np.array([0, 0, -1]), np.array([0, 1, 0]), np.array([1, 0, 0])),
]


def cube_cell_ring(face, u0, v0, u1, v1, n=6):
    """Ring of the cube-face cell [u0,u1]x[v0,v1] projected to the sphere."""
    c, eu, ev = CUBE_FACES[face]
    ring = []
    edges = [((u0, v0), (u1, v0)), ((u1, v0), (u1, v1)),
             ((u1, v1), (u0, v1)), ((u0, v1), (u0, v0))]
    for (ua, va), (ub, vb) in edges:
        for t in np.linspace(0, 1, n, endpoint=False):
            u = ua + (ub - ua) * t
            v = va + (vb - va) * t
            p = c + u * eu + v * ev
            p = p / np.linalg.norm(p)
            ring.append(p)
    # to unwrapped lon/lat
    out = []
    prev = None
    off = 0.0
    for p in ring:
        lon = np.degrees(np.arctan2(p[1], p[0])) + off
        lat = np.degrees(np.arcsin(np.clip(p[2], -1, 1)))
        if prev is not None:
            while lon - prev > 180:
                lon -= 360; off -= 360
            while lon - prev < -180:
                lon += 360; off += 360
        out.append((lon, lat))
        prev = lon
    return out


def build_cubequad(classify, max_level, outdir):
    comp, unc = [], []

    def recurse(face, u0, v0, u1, v1, cid, level):
        ring = cube_cell_ring(face, u0, v0, u1, v1)
        # pole cells: cube faces 4,5 contain poles at centre; ring is fine
        # except the exact-centre cell ring wraps; handle as polygon w/ unwrap
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
        # pole special case: cell containing pole centre has wrapped ring
        lons = [p[0] for p in ring]
        if max(lons) - min(lons) > 350:   # contains a pole -> cap repr
            lat_pole = 90.0 if face == 4 else -90.0
            ll = sorted(ring, key=lambda q: q[0])
            ring = ll + [(180.0, lat_pole), (-180.0, lat_pole)]
            poly = Polygon(ring)
        cls = classify(poly)
        if cls == 'sea':
            return
        if cls == 'interior':
            comp.append(feature(cid, level, ring, True))
            # expand for uniform
            stack = [(u0, v0, u1, v1, cid, level)]
            while stack:
                a0, b0, a1, b1, c_, l_ = stack.pop()
                if l_ == max_level:
                    unc.append(feature(c_, l_,
                               cube_cell_ring(face, a0, b0, a1, b1), True))
                    continue
                am, bm = (a0 + a1) / 2, (b0 + b1) / 2
                for q, (na0, nb0, na1, nb1) in enumerate(
                        [(a0, b0, am, bm), (am, b0, a1, bm),
                         (a0, bm, am, b1), (am, bm, a1, b1)]):
                    stack.append((na0, nb0, na1, nb1, f"{c_}{q}", l_ + 1))
            return
        if level == max_level:
            comp.append(feature(cid, level, ring, False))
            unc.append(feature(cid, level, ring, False))
            return
        um, vm = (u0 + u1) / 2, (v0 + v1) / 2
        for q, (a0, b0, a1, b1) in enumerate(
                [(u0, v0, um, vm), (um, v0, u1, vm),
                 (u0, vm, um, v1), (um, vm, u1, v1)]):
            recurse(face, a0, b0, a1, b1, f"{cid}{q}", level + 1)

    for f in range(6):
        recurse(f, -1, -1, 1, 1, f"C{f}-", 0)
    write(comp, 'cmp_cubequad_compacted', outdir)
    write(unc, 'cmp_cubequad_uncompacted', outdir)


# --------------------------------------------------------- lon/lat quad
def build_rectquad(classify, max_level, outdir):
    comp, unc = [], []

    def ring(x0, y0, x1, y1):
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def recurse(x0, y0, x1, y1, cid, level):
        poly = box(x0, y0, x1, y1)
        cls = classify(poly)
        if cls == 'sea':
            return
        if cls == 'interior':
            comp.append(feature(cid, level, ring(x0, y0, x1, y1), True))
            stack = [(x0, y0, x1, y1, cid, level)]
            while stack:
                a0, b0, a1, b1, c_, l_ = stack.pop()
                if l_ == max_level:
                    unc.append(feature(c_, l_, ring(a0, b0, a1, b1), True))
                    continue
                am, bm = (a0 + a1) / 2, (b0 + b1) / 2
                for q, (na) in enumerate([(a0, b0, am, bm), (am, b0, a1, bm),
                                          (a0, bm, am, b1), (am, bm, a1, b1)]):
                    stack.append((*na, f"{c_}{q}", l_ + 1))
            return
        if level == max_level:
            comp.append(feature(cid, level, ring(x0, y0, x1, y1), False))
            unc.append(feature(cid, level, ring(x0, y0, x1, y1), False))
            return
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        for q, (a) in enumerate([(x0, y0, xm, ym), (xm, y0, x1, ym),
                                 (x0, ym, xm, y1), (xm, ym, x1, y1)]):
            recurse(*a, f"{cid}{q}", level + 1)

    # two root cells (west/east hemispheres), like quadtree on 2:1 plate
    recurse(-180, -90, 0, 90, 'R0-', 0)
    recurse(0, -90, 180, 90, 'R1-', 0)
    write(comp, 'cmp_rectquad_compacted', outdir)
    write(unc, 'cmp_rectquad_uncompacted', outdir)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--land', default='natural-earth-vector/geojson/ne_50m_land.geojson')
    ap.add_argument('--out', default='data')
    ap.add_argument('--h3res', type=int, default=3)
    ap.add_argument('--cubelevel', type=int, default=5)
    ap.add_argument('--rectlevel', type=int, default=6)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    classify = load_land(args.land)
    print("H3 hexagons:")
    build_h3(classify, args.h3res, args.out)
    print("Cube-sphere quadtree (S2-like):")
    build_cubequad(classify, args.cubelevel, args.out)
    print("Lon/lat rect quadtree:")
    build_rectquad(classify, args.rectlevel, args.out)
