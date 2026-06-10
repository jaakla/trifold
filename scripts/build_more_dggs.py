#!/usr/bin/env python
"""Comparison layers for three more DGGS: authentic S2 (s2sphere),
rHEALPix (rhealpixdggs), and HTM (octahedral triangles, built with
Trifold's own machinery — HTM is Trifold's octahedron-based ancestor).

  system    | base res | avg cell    | nesting
  ----------+----------+-------------+------------------------
  s2        | level 6  | ~20,750 km² | exact quadtree (aperture 4)
  rhealpix  | res 4    | ~12,950 km² | exact congruent (aperture 9)
  htm       | level 6  | ~15,570 km² | exact congruent (aperture 4)

Output: data/cmp_{s2,rhealpix,htm}_{compacted,uncompacted}.{geo,topo}json
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
from shapely.geometry import Polygon

from build_comparison_dggs import load_land, write, feature


# ------------------------------------------------------------ ring utils
def normalize_ring(pts, pole_lat_hint=None):
    """Unwrap lon/lat ring; polar-cap representation if it encircles a pole."""
    ring, prev, off = [], None, 0.0
    for lon, lat in pts:
        while lon > 180:
            lon -= 360
        while lon < -180:
            lon += 360
        lon += off
        if prev is not None:
            while lon - prev > 180:
                lon -= 360; off -= 360
            while lon - prev < -180:
                lon += 360; off += 360
        ring.append((lon, lat))
        prev = lon
    lons = [p[0] for p in ring]
    if max(lons) - min(lons) > 350:                      # encircles a pole
        lat_pole = pole_lat_hint if pole_lat_hint is not None else \
                   (90.0 if np.mean([p[1] for p in ring]) > 0 else -90.0)
        folded = [(((lon + 180.0) % 360.0) - 180.0, lat) for lon, lat in ring]
        ll = sorted(folded, key=lambda q: q[0])
        return ll + [(180.0, lat_pole), (-180.0, lat_pole)]
    mean = np.mean(lons)
    shift = 0.0
    while mean + shift > 180:
        shift -= 360
    while mean + shift <= -180:
        shift += 360
    return [(lon + shift, lat) for lon, lat in ring]


def valid_poly(ring):
    p = Polygon(ring)
    return p if p.is_valid else p.buffer(0)


# ------------------------------------------------------------------- S2
def build_s2(classify, base_level, outdir):
    import s2sphere

    def vert(cell, k):
        return np.array(s2sphere.Cell(cell).get_vertex(k)._Point__point,
                        dtype=float)

    def slerp(a, b, t):
        om = np.arccos(np.clip(np.dot(a, b), -1, 1))
        if om < 1e-12:
            return a
        return (np.sin((1 - t) * om) * a + np.sin(t * om) * b) / np.sin(om)

    def ring_of(cid, seg=5):
        vs = [vert(cid, k) for k in range(4)]
        pts3 = []
        for i in range(4):
            a, b = vs[i], vs[(i + 1) % 4]
            for t in np.linspace(0, 1, seg, endpoint=False):
                pts3.append(slerp(a, b, t))
        # pole-as-vertex (cube face centre = corner of 4 cells): wedge repr
        pole_idx = [i for i, p in enumerate(pts3) if abs(p[2]) >= 1 - 1e-9]
        if pole_idx:
            polelat = 90.0 if pts3[pole_idx[0]][2] > 0 else -90.0
            n = len(pts3)
            lonlat, prev, off = {}, None, 0.0
            for i in range(n):
                if i in pole_idx:
                    continue
                p = pts3[i]
                lon = np.degrees(np.arctan2(p[1], p[0])) + off
                lat = np.degrees(np.arcsin(np.clip(p[2], -1, 1)))
                if prev is not None:
                    while lon - prev > 180:
                        lon -= 360; off -= 360
                    while lon - prev < -180:
                        lon += 360; off += 360
                lonlat[i] = (lon, lat); prev = lon
            ring = []
            for i in range(n):
                if i in pole_idx:
                    ip, inx = (i - 1) % n, (i + 1) % n
                    while ip in pole_idx: ip = (ip - 1) % n
                    while inx in pole_idx: inx = (inx + 1) % n
                    ring.append((lonlat[ip][0], polelat))
                    ring.append((lonlat[inx][0], polelat))
                else:
                    ring.append(lonlat[i])
            mean = np.mean([q[0] for q in ring]); shift = 0.0
            while mean + shift > 180: shift -= 360
            while mean + shift <= -180: shift += 360
            return [(lon + shift, lat) for lon, lat in ring]
        pts = [(np.degrees(np.arctan2(p[1], p[0])),
                np.degrees(np.arcsin(np.clip(p[2], -1, 1)))) for p in pts3]
        return normalize_ring(pts)

    comp, unc = [], []

    def expand(cid):
        if cid.level() == base_level:
            unc.append(feature(cid.to_token(), base_level, ring_of(cid), True))
            return
        for ch in cid.children():
            expand(ch)

    def recurse(cid):
        poly = valid_poly(ring_of(cid))
        cls = classify(poly)
        if cls == 'sea':
            return
        if cls == 'interior':
            comp.append(feature(cid.to_token(), cid.level(), ring_of(cid), True))
            expand(cid)
            return
        if cid.level() == base_level:
            f = feature(cid.to_token(), base_level, ring_of(cid), False)
            comp.append(f); unc.append(f)
            return
        for ch in cid.children():
            recurse(ch)

    for face in range(6):
        recurse(s2sphere.CellId.from_face_pos_level(face, 0, 0))
    write(comp, 'cmp_s2_compacted', outdir)
    write(unc, 'cmp_s2_uncompacted', outdir)


# -------------------------------------------------------------- rHEALPix
def build_rhealpix(classify, base_res, outdir):
    from rhealpixdggs.dggs import RHEALPixDGGS
    rd = RHEALPixDGGS()           # WGS84 ellipsoid default

    def shape_of(cell):
        sh = cell.ellipsoidal_shape
        return sh() if callable(sh) else sh

    def ring_of(cell):
        if shape_of(cell) == 'cap':
            lat = cell.boundary(2, False)[0][1]
            pole = 90.0 if lat > 0 else -90.0
            lons = np.linspace(-180, 180, 73)
            ring = [(float(l), float(lat)) for l in lons]
            return ring + [(180.0, pole), (-180.0, pole)]
        pts = [(float(p[0]), float(p[1])) for p in cell.boundary(6, False)]
        return normalize_ring(pts)

    comp, unc = [], []

    def expand(cell):
        if cell.resolution == base_res:
            unc.append(feature(str(cell), base_res, ring_of(cell), True))
            return
        for ch in cell.subcells():
            expand(ch)

    def recurse(cell):
        poly = valid_poly(ring_of(cell))
        cls = classify(poly)
        if cls == 'sea':
            return
        if cls == 'interior':
            comp.append(feature(str(cell), cell.resolution, ring_of(cell), True,
                                {'shape': shape_of(cell)}))
            expand(cell)
            return
        if cell.resolution == base_res:
            f = feature(str(cell), base_res, ring_of(cell), False,
                        {'shape': shape_of(cell)})
            comp.append(f); unc.append(f)
            return
        for ch in cell.subcells():
            recurse(ch)

    for c0 in rd.grid(0):          # 6 base cells: N, O..R (equatorial), S
        recurse(c0)
    write(comp, 'cmp_rhealpix_compacted', outdir)
    write(unc, 'cmp_rhealpix_uncompacted', outdir)


# ------------------------------------------------------------------ HTM
OCTA_VERTS = np.array([
    [0, 0, 1],                 # N
    [1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0],   # equator 0,90,180,270
    [0, 0, -1],                # S
], dtype=float)
OCTA_FACES = [
    (1, 2, 0), (2, 3, 0), (3, 4, 0), (4, 1, 0),     # N0..N3
    (2, 1, 5), (3, 2, 5), (4, 3, 5), (1, 4, 5),     # S0..S3
]
HTM_NAMES = ['N0', 'N1', 'N2', 'N3', 'S0', 'S1', 'S2', 'S3']


def build_htm(classifier, base_level, outdir):
    """HTM = aperture-4 triangles on the octahedron: Trifold's machinery
    with different verts/faces. Poles are octahedron VERTICES, so polar
    cells are meridian wedges — already handled by build_export_ring."""
    from trifold.grid import build_compacted, expand_to_base, cell_geometry_ring

    vf = (OCTA_VERTS, OCTA_FACES)
    comp_cells = build_compacted(classifier, base_level=base_level,
                                 verts_faces=vf)
    unc_cells = expand_to_base(comp_cells, base_level, classifier)

    def rename(cid):               # F03-012 -> N3-012
        face = int(cid[1:3])
        return HTM_NAMES[face] + cid[3:]

    for cells, name in ((comp_cells, 'cmp_htm_compacted'),
                        (unc_cells, 'cmp_htm_uncompacted')):
        feats = []
        for c in cells:
            ring, pole = cell_geometry_ring(c)
            feats.append(feature(rename(c['cell_id']), c['level'], ring,
                                 c['interior'], {'pole': pole}))
        write(feats, name, outdir)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--land', default='natural-earth-vector/geojson/ne_50m_land.geojson')
    ap.add_argument('--out', default='data')
    ap.add_argument('--s2level', type=int, default=6)
    ap.add_argument('--rhpxres', type=int, default=4)
    ap.add_argument('--htmlevel', type=int, default=6)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    classify = load_land(args.land)
    print("S2 (s2sphere, exact quadtree):")
    build_s2(classify, args.s2level, args.out)
    print("rHEALPix (rhealpixdggs, aperture 9, equal-area):")
    build_rhealpix(classify, args.rhpxres, args.out)

    import geopandas as gpd
    from trifold.land import LandClassifier
    print("HTM (octahedral triangles via Trifold machinery):")
    clf = LandClassifier(gpd.read_file(args.land))
    build_htm(clf, args.htmlevel, args.out)
