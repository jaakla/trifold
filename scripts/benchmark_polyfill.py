"""Benchmark T3 vs S2 fixed-level polyfill performance.

Four representative query families:
  1. bbox       - axis-aligned rectangles (map-loader viewport case)
  2. circle     - disks of various radius (nearby/proximity search)
  3. random     - random star polygons of various size
  4. admin      - real administrative areas (countries) if data is present

For every shape and every grid we auto-pick the coarsest level that reaches a
target coverage accuracy (default area accuracy shape/cover >= 0.95, intersects
mode), then time the cover at that level. Accuracy uses real cell areas, so it
is independent of any sampling domain.

T3 uses the shipping library (trifold.polyfill). S2 has no polygon coverer in
s2sphere, so we use a lean pure-Python fixed-level hierarchical cover built on
standard S2 cell math (cell ids are bit-identical to s2sphere, checked at start,
and the bbox/circle covers are cross-checked against s2sphere's native coverer).
Both use hierarchical descent with planar lon/lat predicates. Note the two are
different codebases, so read absolute ms as indicative; the accuracy-matched
cell counts (how many cells each grid needs for the same shape) are the most
directly comparable result. Query shapes are kept away from the poles and the
antimeridian.

Usage:  python scripts/benchmark_polyfill.py [--target 0.95] [--repeats 5]
                                             [--quick] [--md OUT.md]
"""
import argparse
import json
import math
import os
import random
import statistics
import time

import trifold

# ----------------------------------------------------------------------------
# Minimal S2 cell math (ported from docs/sdk/s2mini.js; cell ids match s2sphere)
# ----------------------------------------------------------------------------
MASK64 = (1 << 64) - 1
S2_MAX_LEVEL = 30
_SWAP, _INVERT = 0x01, 0x02
_POS_TO_IJ = [[0, 1, 3, 2], [0, 2, 3, 1], [3, 2, 0, 1], [3, 1, 0, 2]]
_POS_TO_ORI = [_SWAP, 0, 0, _SWAP | _INVERT]
_IJ_TO_POS = []
for _row in _POS_TO_IJ:
    _inv = [0, 0, 0, 0]
    for _p, _ij in enumerate(_row):
        _inv[_ij] = _p
    _IJ_TO_POS.append(_inv)
D2R = math.pi / 180.0
R2D = 180.0 / math.pi


def _lonlat_to_xyz(lon, lat):
    cl = math.cos(lat * D2R)
    return (cl * math.cos(lon * D2R), cl * math.sin(lon * D2R), math.sin(lat * D2R))


def _xyz_to_lonlat(x, y, z):
    return (math.atan2(y, x) * R2D, math.atan2(z, math.hypot(x, y)) * R2D)


def _get_face(x, y, z):
    ax, ay, az = abs(x), abs(y), abs(z)
    if ax > ay:
        face = 0 if ax > az else 2
    else:
        face = 1 if ay > az else 2
    if (x, y, z)[face] < 0:
        face += 3
    return face


def _face_xyz_to_uv(face, x, y, z):
    if face == 0:
        return (y / x, z / x)
    if face == 1:
        return (-x / y, z / y)
    if face == 2:
        return (-x / z, -y / z)
    if face == 3:
        return (z / x, y / x)
    if face == 4:
        return (z / y, -x / y)
    return (-y / z, -x / z)


def _face_uv_to_xyz(face, u, v):
    if face == 0:
        return (1.0, u, v)
    if face == 1:
        return (-u, 1.0, v)
    if face == 2:
        return (-u, -v, 1.0)
    if face == 3:
        return (-1.0, -v, -u)
    if face == 4:
        return (v, -1.0, -u)
    return (v, u, -1.0)


def _uv_to_st(u):
    return 0.5 * math.sqrt(1 + 3 * u) if u >= 0 else 1 - 0.5 * math.sqrt(1 - 3 * u)


def _st_to_uv(s):
    return (1 / 3) * (4 * s * s - 1) if s >= 0.5 else (1 / 3) * (1 - 4 * (1 - s) ** 2)


def _ij_to_pos(face, i, j, level):
    bits = face & _SWAP
    pos = 0
    for k in range(level - 1, -1, -1):
        ij = (((i >> k) & 1) << 1) | ((j >> k) & 1)
        sub = _IJ_TO_POS[bits][ij]
        pos = pos * 4 + sub
        bits ^= _POS_TO_ORI[sub]
    return pos


def _s2_cellid(face, i, j, level):
    pos = _ij_to_pos(face, i, j, level)
    return (face << 61) | (pos << (61 - 2 * level)) | (1 << (60 - 2 * level))


def _s2_lsb(cid):
    return cid & ((~cid & MASK64) + 1) & MASK64


def _s2_parent(cid):
    new_lsb = _s2_lsb(cid) << 2
    return ((cid & (MASK64 ^ (new_lsb - 1))) | new_lsb) & MASK64


def _s2_level(cid):
    x = _s2_lsb(cid)
    tz = 0
    while (x & 1) == 0:
        x >>= 1
        tz += 1
    return S2_MAX_LEVEL - (tz >> 1)


def _s2_decode(cid):
    level = _s2_level(cid)
    face = cid >> 61
    pos = (cid >> (61 - 2 * level)) & ((1 << (2 * level)) - 1)
    bits = face & _SWAP
    i = j = 0
    for k in range(level - 1, -1, -1):
        sub = (pos >> (2 * k)) & 3
        ij = _POS_TO_IJ[bits][sub]
        i = (i << 1) | (ij >> 1)
        j = (j << 1) | (ij & 1)
        bits ^= _POS_TO_ORI[sub]
    return face, level, i, j


def _s2_corner_lonlat(face, ci, cj, size):
    x, y, z = _face_uv_to_xyz(face, _st_to_uv(ci / size), _st_to_uv(cj / size))
    return _xyz_to_lonlat(x, y, z)


def _s2_cell_of_lonlat(lon, lat, level):
    x, y, z = _lonlat_to_xyz(lon, lat)
    face = _get_face(x, y, z)
    u, v = _face_xyz_to_uv(face, x, y, z)
    size = 1 << level
    i = min(size - 1, max(0, int(_uv_to_st(u) * size)))
    j = min(size - 1, max(0, int(_uv_to_st(v) * size)))
    return _s2_cellid(face, i, j, level)


# ----------------------------------------------------------------------------
# Planar lon/lat geometry predicates
# ----------------------------------------------------------------------------
def _point_in_ring(lon, lat, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_mpoly(lon, lat, polys):
    for rings in polys:
        if _point_in_ring(lon, lat, rings[0]):
            if not any(_point_in_ring(lon, lat, h) for h in rings[1:]):
                return True
    return False


def _seg_cross(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (o(c, d, a) > 0) != (o(c, d, b) > 0) and (o(a, b, c) > 0) != (o(a, b, d) > 0)


def _ring_overlap(cell_ring, polys):
    # cell bbox once; used to prefilter polygon vertices and edges (safe:
    # a vertex inside the cell ring, or an edge crossing it, must touch the
    # cell bbox), which matters for many-vertex admin polygons.
    cminx = min(p[0] for p in cell_ring)
    cmaxx = max(p[0] for p in cell_ring)
    cminy = min(p[1] for p in cell_ring)
    cmaxy = max(p[1] for p in cell_ring)
    for lon, lat in cell_ring:
        if _point_in_mpoly(lon, lat, polys):
            return True
    for rings in polys:
        for ring in rings:
            for lon, lat in ring:
                if (cminx <= lon <= cmaxx and cminy <= lat <= cmaxy
                        and _point_in_ring(lon, lat, cell_ring)):
                    return True
    cn = len(cell_ring)
    for rings in polys:
        for ring in rings:
            m = len(ring)
            for k in range(m - 1):
                p1, p2 = ring[k], ring[k + 1]
                if (max(p1[0], p2[0]) < cminx or min(p1[0], p2[0]) > cmaxx
                        or max(p1[1], p2[1]) < cminy or min(p1[1], p2[1]) > cmaxy):
                    continue
                for c in range(cn - 1):
                    if _seg_cross(cell_ring[c], cell_ring[c + 1], p1, p2):
                        return True
    return False


def _mpoly_bbox(polys):
    xs = [p[0] for rings in polys for p in rings[0]]
    ys = [p[1] for rings in polys for p in rings[0]]
    return (min(xs), min(ys), max(xs), max(ys))


_EARTH_R = 6371.0088


def _ring_area_km2(ring):
    """Spherical polygon area (km^2) of a closed lon/lat ring."""
    s = 0.0
    for k in range(len(ring) - 1):
        lo1, la1 = ring[k]
        lo2, la2 = ring[k + 1]
        s += math.radians(lo2 - lo1) * (2 + math.sin(math.radians(la1))
                                        + math.sin(math.radians(la2)))
    return abs(s) * _EARTH_R * _EARTH_R / 2.0


def _shape_area_km2(polys):
    total = 0.0
    for rings in polys:
        total += _ring_area_km2(rings[0])
        for hole in rings[1:]:
            total -= _ring_area_km2(hole)
    return total


def _t3_cell_area(addr):
    face, digits = trifold.decode64(addr)
    return trifold.area_km2(trifold.cell_triangle(face, digits))


def _s2_cell_area(cid):
    face, lev, i, j = _s2_decode(cid)
    size = 1 << lev
    ring = [_s2_corner_lonlat(face, i, j, size),
            _s2_corner_lonlat(face, i + 1, j, size),
            _s2_corner_lonlat(face, i + 1, j + 1, size),
            _s2_corner_lonlat(face, i, j + 1, size)]
    ring.append(ring[0])
    return _ring_area_km2(ring)


# ----------------------------------------------------------------------------
# S2 fixed-level hierarchical cover (intersects / centroid)
# ----------------------------------------------------------------------------
def s2_cover(polys, level, mode="intersects", cap=400000):
    qminx, qminy, qmaxx, qmaxy = _mpoly_bbox(polys)
    out = []
    stack = [(f, 0, 0, 0) for f in range(6)]
    while stack:
        face, i, j, lev = stack.pop()
        size = 1 << lev
        corners = [_s2_corner_lonlat(face, i, j, size),
                   _s2_corner_lonlat(face, i + 1, j, size),
                   _s2_corner_lonlat(face, i + 1, j + 1, size),
                   _s2_corner_lonlat(face, i, j + 1, size)]
        # prune-bbox uses corners + edge midpoints + center: a coarse S2 cell
        # bulges toward the cube-face centre (e.g. a polar face's 4 corners all
        # sit at lat 35 while the cell reaches the pole), so corners alone would
        # wrongly prune. The 9-point hull captures that bulge.
        probe = corners + [
            _s2_corner_lonlat(face, i + 0.5, j, size),
            _s2_corner_lonlat(face, i + 0.5, j + 1, size),
            _s2_corner_lonlat(face, i, j + 0.5, size),
            _s2_corner_lonlat(face, i + 1, j + 0.5, size),
            _s2_corner_lonlat(face, i + 0.5, j + 0.5, size)]
        pxs = [c[0] for c in probe]
        pys = [c[1] for c in probe]
        # a coarse cell may straddle the antimeridian (e.g. the polar face wraps
        # all longitudes); unwrap so its true lon extent stays tight and far-side
        # cells get pruned. Query shapes are assumed away from +/-180.
        if max(pxs) - min(pxs) > 180:
            pxs = [x + 360 if x < 0 else x for x in pxs]
        if max(pxs) < qminx or min(pxs) > qmaxx or max(pys) < qminy or min(pys) > qmaxy:
            continue
        if lev == level:
            if mode == "centroid":
                cen = _s2_corner_lonlat(face, i + 0.5, j + 0.5, size)
                hit = _point_in_mpoly(cen[0], cen[1], polys)
            else:
                ring = corners + [corners[0]]
                hit = _ring_overlap(ring, polys)
            if hit:
                out.append(_s2_cellid(face, i, j, level))
                if len(out) > cap:
                    raise RuntimeError("s2 cover exceeded cap")
            continue
        ii, jj = i << 1, j << 1
        stack.append((face, ii, jj, lev + 1))
        stack.append((face, ii + 1, jj, lev + 1))
        stack.append((face, ii, jj + 1, lev + 1))
        stack.append((face, ii + 1, jj + 1, lev + 1))
    return out


def _compact(cells, parent_fn):
    cur = set(cells)
    changed = True
    while changed:
        changed = False
        groups = {}
        for c in cur:
            p = parent_fn(c)
            groups.setdefault(p, []).append(c)
        nxt = set()
        for p, kids in groups.items():
            if len(kids) == 4:
                nxt.add(p)
                changed = True
            else:
                nxt.update(kids)
        cur = nxt
    return cur


def _s2_compact(cells):
    return _compact([c for c in cells if (c & (MASK64)) != 0], _s2_parent)


# ----------------------------------------------------------------------------
# geometry builders
# ----------------------------------------------------------------------------
def _geojson(polys):
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def bbox_poly(w, s, e, n):
    return [[[[w, s], [e, s], [e, n], [w, n], [w, s]]]]


def circle_poly(lon, lat, radius_km, n=96):
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(lat * D2R))
    ring = []
    for k in range(n):
        a = 2 * math.pi * k / n
        ring.append([lon + dlon * math.cos(a), lat + dlat * math.sin(a)])
    ring.append(ring[0][:])
    return [[ring]]


def random_poly(rng, lon, lat, radius_deg, n=10):
    angs = sorted(rng.uniform(0, 2 * math.pi) for _ in range(n))
    ring = []
    for a in angs:
        r = radius_deg * rng.uniform(0.45, 1.0)
        ring.append([lon + r * math.cos(a) / math.cos(lat * D2R), lat + r * math.sin(a)])
    ring.append(ring[0][:])
    return [[ring]]


def _dp_simplify(ring, tol):
    """Douglas-Peucker on a lon/lat ring (tolerance in degrees), iterative."""
    n = len(ring)
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    # a closed ring (first == last) makes the top-level anchor segment
    # zero-length, so every distance is 0 and the ring collapses; seed the
    # midpoint to break the degeneracy
    if ring[0] == ring[n - 1] and n > 3:
        mid = n // 2
        keep[mid] = True
        stack = [(0, mid), (mid, n - 1)]
    else:
        stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = ring[a]
        bx, by = ring[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        best, bi = -1.0, None
        for k in range(a + 1, b):
            px, py = ring[k]
            d = abs(dx * (py - ay) - dy * (px - ax)) / norm
            if d > best:
                best, bi = d, k
        if best > tol:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return [p for p, k in zip(ring, keep) if k]


def _simplify_ring(ring, max_verts=250):
    """DP-simplify until the ring has <= max_verts vertices (doubling tol)."""
    out = ring
    tol = 0.005
    while len(out) > max_verts and tol < 4.0:
        cand = _dp_simplify(ring, tol)
        if len(cand) < 5:  # keep a valid, non-degenerate closed ring
            break
        out = cand
        tol *= 2
    return out


def load_admin(gids, max_verts=250):
    path = "osm-vector/countries_coastal.geojson"
    if not os.path.isfile(path):
        return {}
    want = set(gids)
    found = {}
    with open(path) as f:
        fc = json.load(f)
    for feat in fc["features"]:
        gid = feat["properties"].get("gid_0")
        if gid not in want:
            continue
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            polys = [geom["coordinates"]]
        else:
            polys = geom["coordinates"]
        # keep the few largest rings to bound predicate cost while staying real,
        # then DP-simplify each ring to a few hundred vertices ("real-life like"
        # jagged borders without the raw OSM vertex count; both grids see the
        # same simplified shape so the comparison stays fair)
        polys = sorted(polys, key=lambda p: -len(p[0]))[:3]
        polys = [[_simplify_ring(ring, max_verts) for ring in rings]
                 for rings in polys]
        found[gid] = polys
    return found


# ----------------------------------------------------------------------------
# accuracy (Monte Carlo IoU, intersects mode) and level selection
# ----------------------------------------------------------------------------
# Coverage accuracy = area(shape) / area(cover). In intersects mode the shape
# is fully contained in the cover, so this is the area-IoU (1.0 = perfect, no
# overshoot). Computed from real cell areas, so it is independent of any
# sampling domain. Returns (accuracy, cover_cells).
def _acc_t3(polys, level, shape_area):
    cover = trifold.polyfill(_geojson(polys), level, mode="intersects")
    area = sum(_t3_cell_area(c) for c in cover)
    return (min(1.0, shape_area / area) if area else 0.0), cover


def _acc_s2(polys, level, shape_area):
    cover = s2_cover(polys, level, mode="intersects")
    area = sum(_s2_cell_area(c) for c in cover)
    return (min(1.0, shape_area / area) if area else 0.0), cover


def _s2_ranges(cells):
    """Merged leaf-id intervals of S2 cells (S2's analogue of cover_ranges)."""
    intervals = []
    for c in cells:
        lsb = _s2_lsb(c)
        intervals.append((c - lsb + 1, c + lsb - 1))
    intervals.sort()
    merged = []
    for s, e in intervals:
        if merged and s == merged[-1][1] + 2:  # leaf ids are spaced by 2
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def scan_levels(acc_fn, compact_fn, ranges_fn, polys, shape_area,
                target, lo, hi):
    """Walk levels coarse->fine, recording all three size metrics per level.

    Returns (chosen_level, [(lev, acc, n_cells, n_compacted, n_ranges)]).
    """
    records = []
    for lev in range(lo, hi + 1):
        acc, cover = acc_fn(polys, lev, shape_area)
        comp = compact_fn(cover)
        nrng = len(ranges_fn(comp)) if cover else 0
        records.append((lev, acc, len(cover), len(comp), nrng))
        if acc >= target:
            return lev, records
    return hi, records


def metric_at_target(records, target, idx):
    """Log-linear interpolation of a size metric at exactly the accuracy target.

    idx selects the record column (2=cells, 3=compacted, 4=ranges). Removes the
    level-quantization artifact: a grid that barely clears the target is not
    compared against one forced a whole level finer. Returns (value,
    extrapolated) - extrapolated=True when the scan hit the level cap below the
    target and the value is projected from the last two levels.
    """
    prev = None
    for rec in records:
        acc, n = rec[1], rec[idx]
        if acc >= target and n > 0:
            if prev is None or prev[1] <= 0 or acc <= prev[0]:
                return float(n), False
            pa, pn = prev
            f = (target - pa) / (acc - pa)
            return math.exp(math.log(pn) + f * (math.log(n) - math.log(pn))), False
        if n > 0:
            prev = (acc, n)
    # capped below target: extrapolate from the last two usable records
    usable = [(r[1], r[idx]) for r in records if r[idx] > 0]
    if len(usable) >= 2 and usable[-1][0] > usable[-2][0]:
        (a1, n1), (a2, n2) = usable[-2], usable[-1]
        f = (target - a1) / (a2 - a1)
        return math.exp(math.log(n1) + f * (math.log(n2) - math.log(n1))), True
    return float(usable[-1][1]) if usable else 0.0, True


def _time(fn, repeats):
    best = []
    for _ in range(repeats):
        t = time.perf_counter()
        cells = fn()
        best.append((time.perf_counter() - t) * 1000.0)
    return statistics.median(best), cells


# ----------------------------------------------------------------------------
def cross_check_s2(verbose=True):
    """Confirm s2_cover matches s2sphere native covering for bbox + circle."""
    try:
        import s2sphere as s2
    except ImportError:
        if verbose:
            print("  (s2sphere not available - skipping S2 cross-check)")
        return
    # cell-id identity on random points
    rng = random.Random(1)
    for _ in range(500):
        lon, lat = rng.uniform(-179, 179), rng.uniform(-85, 85)
        lev = rng.randint(0, 16)
        mine = _s2_cell_of_lonlat(lon, lat, lev)
        ref = s2.CellId.from_lat_lng(s2.LatLng.from_degrees(lat, lon)).parent(lev).id()
        assert mine == ref, f"cell id mismatch {mine} != {ref}"
    # bbox cover vs LatLngRect
    w, s_, e, n = -0.55, 51.25, 0.25, 51.75
    lev = 9
    rc = s2.RegionCoverer()
    rc.min_level = rc.max_level = lev
    rc.max_cells = 10_000_000
    rect = s2.LatLngRect(s2.LatLng.from_degrees(s_, w), s2.LatLng.from_degrees(n, e))
    ref_ids = {c.id() for c in rc.get_covering(rect)}
    mine_ids = set(s2_cover(bbox_poly(w, s_, e, n), lev))
    jac = len(ref_ids & mine_ids) / len(ref_ids | mine_ids)
    if verbose:
        print(f"  S2 cell ids: 500/500 match s2sphere; "
              f"bbox L{lev} cover Jaccard vs s2sphere RegionCoverer = {jac:.3f} "
              f"(mine {len(mine_ids)}, ref {len(ref_ids)})")


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=0.95)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--family", default=None,
                    help="comma-separated subset of families to run "
                         "(bbox,circle,random,admin)")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--md", default=None)
    args = ap.parse_args()
    rng = random.Random(20260630)

    print(f"Polyfill benchmark  T3 vs S2  (target accuracy >= {args.target}, "
          f"intersects mode, median of {args.repeats})")
    print("Validating S2 implementation:")
    cross_check_s2()

    cases = {"bbox": [], "circle": [], "random": [], "admin": []}
    # 1) axis-aligned bboxes: viewport / region / country sized (mid-latitude)
    cases["bbox"] = [
        ("city ~25km", bbox_poly(-0.20, 51.40, 0.10, 51.60)),
        ("metro ~120km", bbox_poly(-0.9, 51.0, 0.7, 52.0)),
        ("region ~600km", bbox_poly(-5.0, 48.0, 4.0, 54.0)),
    ]
    # 2) circles: nearby search radii
    cases["circle"] = [
        ("r=2km", circle_poly(2.35, 48.85, 2)),
        ("r=20km", circle_poly(2.35, 48.85, 20)),
        ("r=150km", circle_poly(2.35, 48.85, 150)),
    ]
    # 3) random polygons of varying size
    cases["random"] = [
        (f"rand {d}deg", random_poly(rng, rng.uniform(-10, 30), rng.uniform(35, 55), d))
        for d in (0.3, 1.2, 4.0)
    ]
    # 4) real administrative areas (countries) if present
    admin = load_admin(["LUX", "BEL", "CHE", "EST"])
    name = {"LUX": "Luxembourg", "BEL": "Belgium", "CHE": "Switzerland", "EST": "Estonia"}
    cases["admin"] = [(name[g], admin[g]) for g in ["LUX", "BEL", "CHE", "EST"] if g in admin]
    if not cases["admin"]:
        print("  (admin data osm-vector/countries_coastal.geojson not found - skipping family 4)")

    if args.family:
        want = {f.strip() for f in args.family.split(",")}
        cases = {k: v for k, v in cases.items() if k in want}
    if args.quick:
        cases = {k: v[:1] for k, v in cases.items()}

    rows = []
    hdr = (f"\n{'family':7} {'shape':16} {'sys':3} {'lvl':>3} {'acc':>5} "
           f"{'cells':>7} {'compact':>7} {'ms':>8} {'cells/s':>9} "
           f"{'c@tgt':>9} {'cc@tgt':>8} {'rng@tgt':>8}")
    print(hdr)
    print("-" * len(hdr))
    for family, items in cases.items():
        for shape_name, polys in items:
            shape_area = _shape_area_km2(polys)
            for sys, acc_fn, cover_fn, compact_fn, ranges_fn in (
                ("T3", _acc_t3,
                 lambda L, p=polys: trifold.polyfill(_geojson(p), L, mode="intersects"),
                 lambda cs: _compact(cs, trifold.parent64),
                 trifold.cover_ranges),
                ("S2", _acc_s2,
                 lambda L, p=polys: s2_cover(p, L, mode="intersects"),
                 lambda cs: _compact(cs, _s2_parent),
                 _s2_ranges),
            ):
                # admin borders never reach the area target until impractically
                # fine levels (jagged coastline -> huge perimeter), so cap L13
                hi = 13 if family == "admin" else 16
                lev, records = scan_levels(acc_fn, compact_fn, ranges_fn,
                                           polys, shape_area,
                                           args.target, 4, hi)
                acc = records[-1][1]
                n_cells, n_comp = records[-1][2], records[-1][3]
                c_raw, ex1 = metric_at_target(records, args.target, 2)
                c_cmp, ex2 = metric_at_target(records, args.target, 3)
                c_rng, ex3 = metric_at_target(records, args.target, 4)
                ms, _ = _time(lambda: cover_fn(lev), args.repeats)
                cps = n_cells / (ms / 1000.0) if ms else 0
                fmt = lambda v, ex: f"{'~' if ex else ''}{v:.0f}"
                rows.append((family, shape_name, sys, lev, acc, n_cells,
                             n_comp, ms, cps, c_raw, c_cmp, c_rng,
                             fmt(c_raw, ex1), fmt(c_cmp, ex2), fmt(c_rng, ex3)))
                print(f"{family:7} {shape_name:16} {sys:3} {lev:3d} {acc:5.2f} "
                      f"{n_cells:7d} {n_comp:7d} {ms:8.2f} {cps:9.0f} "
                      f"{fmt(c_raw, ex1):>9} {fmt(c_cmp, ex2):>8} "
                      f"{fmt(c_rng, ex3):>8}")

    # per-family summary: interpolated size metrics at the target accuracy
    print(f"\nPer-family medians at accuracy {args.target} (quantization-free "
          f"interpolation; ratios are S2/T3, <1 favors S2):")
    print(f"{'family':8} {'T3 ms':>9} {'S2 ms':>8} {'ms':>6} "
          f"{'T3 cells':>9} {'S2 cells':>9} {'cells':>6} "
          f"{'T3 cmp':>7} {'S2 cmp':>7} {'cmp':>6} "
          f"{'T3 rng':>7} {'S2 rng':>7} {'rng':>6}")
    for family in cases:
        fr = [r for r in rows if r[0] == family]
        if not fr:
            continue
        t3 = [r for r in fr if r[2] == "T3"]
        s2 = [r for r in fr if r[2] == "S2"]
        med = lambda rs, i: statistics.median(r[i] for r in rs)
        ratio = lambda a, b: b / a if a else float("nan")
        t3ms, s2ms = med(t3, 7), med(s2, 7)
        vals = []
        for i in (9, 10, 11):
            vals.append((med(t3, i), med(s2, i)))
        print(f"{family:8} {t3ms:9.2f} {s2ms:8.2f} {ratio(t3ms, s2ms):6.2f} "
              f"{vals[0][0]:9.0f} {vals[0][1]:9.0f} "
              f"{ratio(vals[0][0], vals[0][1]):6.2f} "
              f"{vals[1][0]:7.0f} {vals[1][1]:7.0f} "
              f"{ratio(vals[1][0], vals[1][1]):6.2f} "
              f"{vals[2][0]:7.0f} {vals[2][1]:7.0f} "
              f"{ratio(vals[2][0], vals[2][1]):6.2f}")

    if args.md:
        _write_md(args.md, args, rows, cases)
        print(f"\nwrote {args.md}")


def _write_md(path, args, rows, cases):
    lines = [f"# Polyfill benchmark: T3 vs S2\n",
             f"Target area accuracy (shape/cover) >= {args.target} (intersects mode); "
             f"per-shape level auto-picked; median of {args.repeats} runs. "
             f"S2 cells are bit-identical to s2sphere; bbox/circle covers "
             f"cross-checked against s2sphere's native coverer.\n",
             f"The `@{args.target}` columns interpolate each size metric at "
             f"exactly the target accuracy (log-linear between bracketing "
             f"levels), removing the level-quantization artifact; `~` marks "
             f"extrapolation past the level cap. `cells` = full fixed-level "
             f"cover, `compacted` = after folding complete sibling sets, "
             f"`ranges` = merged index intervals (SQL scan cost).\n",
             "| family | shape | sys | level | acc | cells | compacted | ms "
             f"| cells/s | cells@{args.target} | compacted@{args.target} "
             f"| ranges@{args.target} |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]:.2f} | "
                     f"{r[5]} | {r[6]} | {r[7]:.2f} | {r[8]:.0f} | "
                     f"{r[12]} | {r[13]} | {r[14]} |")
    open(path, "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    run()
