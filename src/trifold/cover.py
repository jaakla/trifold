"""Cell covering helpers for bbox and GeoJSON polygon queries.

These routines are dependency-free and intentionally conservative.  They
operate in WGS84 lon/lat space over Trifold's exported cell rings, then let
callers apply exact post-filters when a query needs exact point or geometry
membership.

Performance note: the per-node geometry (triangle subdivision, plane-side
containment, ring building) is implemented here as pure-scalar mirrors of the
``trifold.core`` numpy routines.  numpy's per-call overhead on 3-vectors
dominated cover time (~90%, see issue #11); the scalar mirrors perform the
same IEEE-754 operations in the same order, so covers are identical (verified
against the numpy implementation over a bbox/circle/polygon/polar corpus),
~10x faster.  ``trifold.core`` remains the canonical geometry for everything
else.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

from .address import MAX_LEVEL, descendant_range, encode64
from .core import EXPORT_DEPTH, icosahedron

EPS = 1e-12
Point2 = tuple[float, float]
Ring = list[Point2]
Polygon = list[Ring]
BBox = tuple[float, float, float, float]


def bbox_cover(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    level: int,
    *,
    mode: str = "intersects",
) -> list[int]:
    """Return fixed-level cells intersecting a WGS84 bounding box.

    ``min_lon > max_lon`` denotes a bbox that crosses the antimeridian.
    ``mode="intersects"`` returns cells whose exported cell polygon
    intersects the bbox.  ``mode="centroid"`` returns cells whose
    representative center lies inside the bbox.
    """
    _validate_level(level)
    _validate_mode(mode)
    rects = _split_bbox(min_lon, min_lat, max_lon, max_lat)

    def overlaps_query(ring: Ring) -> bool:
        return any(_ring_bbox_overlaps_bbox(ring, rect) for rect in rects)

    def accepts(ring: Ring, tri) -> bool:
        if mode == "centroid":
            center = _triangle_center_lonlat(tri)
            return any(_point_in_rect(center, rect) for rect in rects)
        return any(_cell_intersects_rect(ring, tri, rect) for rect in rects)

    return _cover(level, overlaps_query, accepts)


def polyfill(
    geometry: dict[str, Any],
    level: int,
    *,
    mode: str = "intersects",
) -> list[int]:
    """Return fixed-level cells intersecting a GeoJSON polygon geometry.

    ``geometry`` may be a GeoJSON ``Polygon``, ``MultiPolygon``, ``Feature``,
    or ``FeatureCollection``.  Coordinates are interpreted as WGS84
    ``[lon, lat]`` pairs.  Antimeridian-crossing rings are unwrapped into a
    continuous longitude domain before planar intersection tests run.
    """
    _validate_level(level)
    _validate_mode(mode)
    polygons = _polygons_from_geojson(geometry)
    if not polygons:
        return []
    bboxes = [_polygon_bbox(polygon) for polygon in polygons]

    def overlaps_query(ring: Ring) -> bool:
        return any(_ring_bbox_overlaps_bbox(ring, bbox) for bbox in bboxes)

    def accepts(ring: Ring, tri) -> bool:
        if mode == "centroid":
            center = _triangle_center_lonlat(tri)
            return any(_point_in_polygon_any_shift(center, polygon)
                       for polygon in polygons)
        return any(_cell_intersects_polygon(ring, tri, polygon)
                   for polygon in polygons)

    return _cover(level, overlaps_query, accepts)


def cover_ranges(cells: Iterable[int]) -> list[tuple[int, int]]:
    """Return sorted, coalesced descendant ranges for covered cells."""
    ranges = sorted(descendant_range(int(cell)) for cell in cells)
    if not ranges:
        return []
    merged = [ranges[0]]
    for low, high in ranges[1:]:
        prev_low, prev_high = merged[-1]
        if low <= prev_high + 1:
            merged[-1] = (prev_low, max(prev_high, high))
        else:
            merged.append((low, high))
    return merged


# ------------------------------------------------------------------------
# Pure-scalar mirrors of trifold.core geometry (see module docstring).
# Triangles are tuples of three (x, y, z) float tuples.
# ------------------------------------------------------------------------
_POLE_Z = 1 - 1e-9
_RAD2DEG = 180.0 / math.pi


def _norm3(x: float, y: float, z: float) -> tuple[float, float, float]:
    n = math.sqrt(x * x + y * y + z * z)
    return (x / n, y / n, z / n)


def _sub4(tri):
    """Mirror of core.subdivide on scalar tuples."""
    v0, v1, v2 = tri
    m01 = _norm3(v0[0] + v1[0], v0[1] + v1[1], v0[2] + v1[2])
    m12 = _norm3(v1[0] + v2[0], v1[1] + v2[1], v1[2] + v2[2])
    m20 = _norm3(v2[0] + v0[0], v2[1] + v0[1], v2[2] + v0[2])
    return ((v0, m01, m20), (m01, v1, m12), (m20, m12, v2), (m01, m12, m20))


def _contains3(tri, p) -> bool:
    """Mirror of core.contains_point: dot(cross(a, b), p) plane-side tests."""
    v0, v1, v2 = tri
    px, py, pz = p
    if ((v0[1] * v1[2] - v0[2] * v1[1]) * px
            + (v0[2] * v1[0] - v0[0] * v1[2]) * py
            + (v0[0] * v1[1] - v0[1] * v1[0]) * pz) < -1e-14:
        return False
    if ((v1[1] * v2[2] - v1[2] * v2[1]) * px
            + (v1[2] * v2[0] - v1[0] * v2[2]) * py
            + (v1[0] * v2[1] - v1[1] * v2[0]) * pz) < -1e-14:
        return False
    return ((v2[1] * v0[2] - v2[2] * v0[1]) * px
            + (v2[2] * v0[0] - v2[0] * v0[2]) * py
            + (v2[0] * v0[1] - v2[1] * v0[0]) * pz) >= -1e-14


def _xyz_to_lonlat3(p) -> Point2:
    z = p[2]
    if z > 1.0:
        z = 1.0
    elif z < -1.0:
        z = -1.0
    return (math.atan2(p[1], p[0]) * _RAD2DEG, math.asin(z) * _RAD2DEG)


def _edge_points3(a, b, n_halvings):
    """Mirror of core._edge_points (recursive normalized-midpoint)."""
    if n_halvings <= 0:
        return [a]
    m = _norm3(a[0] + b[0], a[1] + b[1], a[2] + b[2])
    return (_edge_points3(a, m, n_halvings - 1)
            + _edge_points3(m, b, n_halvings - 1))


def _unwrap_lonlat3(pts_xyz) -> Ring:
    """Mirror of core.unwrap_ring_lonlat (sequential mean; see note below)."""
    ring = []
    prev = None
    off = 0.0
    for p in pts_xyz:
        lon, lat = _xyz_to_lonlat3(p)
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
    return _recenter3(ring)


def _recenter3(ring: Ring) -> Ring:
    # core uses np.mean (pairwise summation); sequential sum may differ in the
    # last ulp, which could only flip the +/-360 recentring when the mean sits
    # exactly on 180 -- and every predicate below retries shifts of -360/0/360,
    # so cover membership cannot change.
    mean = sum(point[0] for point in ring) / len(ring)
    shift = 0.0
    while mean + shift > 180:
        shift -= 360
    while mean + shift <= -180:
        shift += 360
    if shift == 0.0:
        return ring
    return [(lon + shift, lat) for lon, lat in ring]


def _cell_ring(tri, level: int) -> Ring:
    """Mirror of core.densified_ring_xyz(level=..) + core.build_export_ring."""
    n_halvings = EXPORT_DEPTH - level
    if n_halvings < 0:
        n_halvings = 0
    pts = []
    pts.extend(_edge_points3(tri[0], tri[1], n_halvings))
    pts.extend(_edge_points3(tri[1], tri[2], n_halvings))
    pts.extend(_edge_points3(tri[2], tri[0], n_halvings))

    pole_idx = [i for i, p in enumerate(pts) if abs(p[2]) >= _POLE_Z]
    if pole_idx:
        polelat = 90.0 if pts[pole_idx[0]][2] > 0 else -90.0
        n = len(pts)
        pole_set = set(pole_idx)
        lonlat = {}
        prev_lon = None
        off = 0.0
        for i in range(n):
            if i in pole_set:
                continue
            lon, lat = _xyz_to_lonlat3(pts[i])
            lon += off
            if prev_lon is not None:
                while lon - prev_lon > 180:
                    lon -= 360
                    off -= 360
                while lon - prev_lon < -180:
                    lon += 360
                    off += 360
            lonlat[i] = (lon, lat)
            prev_lon = lon
        ring = []
        for i in range(n):
            if i in pole_set:
                iprev = (i - 1) % n
                inext = (i + 1) % n
                while iprev in pole_set:
                    iprev = (iprev - 1) % n
                while inext in pole_set:
                    inext = (inext + 1) % n
                ring.append((lonlat[iprev][0], polelat))
                ring.append((lonlat[inext][0], polelat))
            else:
                ring.append(lonlat[i])
        return _recenter3(ring)

    north = _contains3(tri, (0.0, 0.0, 1.0))
    if north or _contains3(tri, (0.0, 0.0, -1.0)):
        polelat = 90.0 if north else -90.0
        ll = sorted((_xyz_to_lonlat3(p) for p in pts), key=lambda q: q[0])
        return ll + [(180.0, polelat), (-180.0, polelat)]

    return _unwrap_lonlat3(pts)


def _cover(level: int, overlaps_query, accepts) -> list[int]:
    verts, faces = icosahedron()
    verts = [(float(v[0]), float(v[1]), float(v[2])) for v in verts]
    out: set[int] = set()

    def recurse(face: int, digits: tuple[int, ...], tri) -> None:
        ring = _cell_ring(tri, len(digits))
        if not overlaps_query(ring):
            return
        if len(digits) == level:
            if accepts(ring, tri):
                out.add(encode64(face, digits))
            return
        for digit, child in enumerate(_sub4(tri)):
            recurse(face, (*digits, digit), child)

    for face, (i, j, k) in enumerate(faces):
        recurse(face, (), (verts[i], verts[j], verts[k]))
    return sorted(out)


def _validate_level(level: int) -> None:
    if not isinstance(level, int) or isinstance(level, bool):
        raise TypeError("level must be an integer")
    if not 0 <= level <= MAX_LEVEL:
        raise ValueError(f"level must be in [0, {MAX_LEVEL}]")


def _validate_mode(mode: str) -> None:
    if mode not in {"intersects", "centroid"}:
        raise ValueError("mode must be 'intersects' or 'centroid'")


def _split_bbox(min_lon: float, min_lat: float,
                max_lon: float, max_lat: float) -> list[BBox]:
    values = [min_lon, min_lat, max_lon, max_lat]
    if not all(isinstance(value, (int, float)) for value in values):
        raise TypeError("bbox coordinates must be numbers")
    min_lon, min_lat, max_lon, max_lat = (float(value) for value in values)
    if not -180 <= min_lon <= 180 or not -180 <= max_lon <= 180:
        raise ValueError("bbox longitudes must be in [-180, 180]")
    if not -90 <= min_lat <= 90 or not -90 <= max_lat <= 90:
        raise ValueError("bbox latitudes must be in [-90, 90]")
    if min_lat > max_lat:
        raise ValueError("min_lat must be <= max_lat")
    if min_lon <= max_lon:
        return [(min_lon, min_lat, max_lon, max_lat)]
    return [(min_lon, min_lat, 180.0, max_lat),
            (-180.0, min_lat, max_lon, max_lat)]


def _triangle_center_lonlat(tri) -> Point2:
    v0, v1, v2 = tri
    return _xyz_to_lonlat3(_norm3(v0[0] + v1[0] + v2[0],
                                  v0[1] + v1[1] + v2[1],
                                  v0[2] + v1[2] + v2[2]))


def _lonlat_to_xyz(lon: float, lat: float):
    lam = math.radians(lon)
    phi = math.radians(lat)
    cp = math.cos(phi)
    return (cp * math.cos(lam), cp * math.sin(lam), math.sin(phi))


def _ring_bbox(ring: Ring) -> BBox:
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return min(lons), min(lats), max(lons), max(lats)


def _bbox_overlap(a: BBox, b: BBox) -> bool:
    return not (a[2] < b[0] - EPS or b[2] < a[0] - EPS
                or a[3] < b[1] - EPS or b[3] < a[1] - EPS)


def _shift_ring(ring: Ring, shift: float) -> Ring:
    if shift == 0:
        return ring
    return [(lon + shift, lat) for lon, lat in ring]


def _ring_bbox_overlaps_bbox(ring: Ring, bbox: BBox) -> bool:
    return any(_bbox_overlap(_ring_bbox(_shift_ring(ring, shift)), bbox)
               for shift in (-360.0, 0.0, 360.0))


def _point_in_rect(point: Point2, rect: BBox) -> bool:
    lon, lat = point
    return (rect[0] - EPS <= lon <= rect[2] + EPS
            and rect[1] - EPS <= lat <= rect[3] + EPS)


def _rect_corners(rect: BBox) -> list[Point2]:
    min_lon, min_lat, max_lon, max_lat = rect
    return [(min_lon, min_lat), (max_lon, min_lat),
            (max_lon, max_lat), (min_lon, max_lat)]


def _rect_edges(rect: BBox) -> list[tuple[Point2, Point2]]:
    corners = _rect_corners(rect)
    return list(zip(corners, corners[1:] + corners[:1]))


def _segments(ring: Ring) -> list[tuple[Point2, Point2]]:
    return list(zip(ring, ring[1:] + ring[:1]))


def _cell_intersects_rect(ring: Ring, tri, rect: BBox) -> bool:
    rect_edges = _rect_edges(rect)
    for shift in (-360.0, 0.0, 360.0):
        shifted = _shift_ring(ring, shift)
        if not _bbox_overlap(_ring_bbox(shifted), rect):
            continue
        if any(_point_in_rect(point, rect) for point in shifted):
            return True
        if any(_contains3(tri, _lonlat_to_xyz(lon, lat))
               for lon, lat in _rect_corners(rect)):
            return True
        for edge in _segments(shifted):
            if any(_segments_intersect(edge[0], edge[1], r0, r1)
                   for r0, r1 in rect_edges):
                return True
    return False


def _polygons_from_geojson(geometry: dict[str, Any]) -> list[Polygon]:
    if not isinstance(geometry, dict):
        raise TypeError("geometry must be a GeoJSON mapping")
    gtype = geometry.get("type")
    if gtype == "Feature":
        return _polygons_from_geojson(geometry.get("geometry"))
    if gtype == "FeatureCollection":
        polygons: list[Polygon] = []
        for feature in geometry.get("features", []):
            polygons.extend(_polygons_from_geojson(feature))
        return polygons
    if gtype == "Polygon":
        return [_normalize_polygon(geometry.get("coordinates"))]
    if gtype == "MultiPolygon":
        return [_normalize_polygon(coords)
                for coords in geometry.get("coordinates", [])]
    raise ValueError("geometry must be Polygon, MultiPolygon, Feature, or FeatureCollection")


def _normalize_polygon(coords: Any) -> Polygon:
    if not isinstance(coords, Sequence) or not coords:
        raise ValueError("polygon coordinates must contain at least one ring")
    rings = [_normalize_ring(ring) for ring in coords]
    if not rings[0]:
        raise ValueError("polygon exterior ring is empty")
    return rings


def _normalize_ring(ring: Any) -> Ring:
    if not isinstance(ring, Sequence) or len(ring) < 4:
        raise ValueError("linear rings must contain at least four positions")
    points = []
    prev_lon = None
    offset = 0.0
    for raw in ring:
        if not isinstance(raw, Sequence) or len(raw) < 2:
            raise ValueError("positions must be [lon, lat] pairs")
        lon = float(raw[0]) + offset
        lat = float(raw[1])
        if not -90 <= lat <= 90:
            raise ValueError("polygon latitudes must be in [-90, 90]")
        if prev_lon is not None:
            while lon - prev_lon > 180:
                lon -= 360
                offset -= 360
            while lon - prev_lon < -180:
                lon += 360
                offset += 360
        points.append((lon, lat))
        prev_lon = lon
    if _same_point(points[0], points[-1]):
        points.pop()
    if len(points) < 3:
        raise ValueError("linear rings must contain at least three unique positions")
    return points


def _same_point(a: Point2, b: Point2) -> bool:
    return abs(a[0] - b[0]) <= EPS and abs(a[1] - b[1]) <= EPS


def _polygon_bbox(polygon: Polygon) -> BBox:
    return _ring_bbox(polygon[0])


def _point_in_polygon(point: Point2, polygon: Polygon) -> bool:
    if not _point_in_ring(point, polygon[0]):
        return False
    return not any(_point_in_ring(point, hole) for hole in polygon[1:])


def _point_in_polygon_any_shift(point: Point2, polygon: Polygon) -> bool:
    return any(_point_in_polygon((point[0] + shift, point[1]), polygon)
               for shift in (-360.0, 0.0, 360.0))


def _point_in_ring(point: Point2, ring: Ring) -> bool:
    x, y = point
    inside = False
    count = len(ring)
    for index in range(count):
        x0, y0 = ring[index]
        x1, y1 = ring[(index + 1) % count]
        if _point_on_segment(point, (x0, y0), (x1, y1)):
            return True
        crosses = (y0 > y) != (y1 > y)
        if crosses:
            x_at_y = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x <= x_at_y + EPS:
                inside = not inside
    return inside


def _cell_intersects_polygon(ring: Ring, tri, polygon: Polygon) -> bool:
    bbox = _polygon_bbox(polygon)
    for shift in (-360.0, 0.0, 360.0):
        shifted = _shift_ring(ring, shift)
        if not _bbox_overlap(_ring_bbox(shifted), bbox):
            continue
        if any(_point_in_polygon(point, polygon) for point in shifted):
            return True
        if any(_contains3(tri, _lonlat_to_xyz(lon, lat))
               for lon, lat in polygon[0]):
            return True
        cell_edges = _segments(shifted)
        for poly_ring in polygon:
            for edge in cell_edges:
                if any(_segments_intersect(edge[0], edge[1], p0, p1)
                       for p0, p1 in _segments(poly_ring)):
                    return True
    return False


def _point_on_segment(point: Point2, a: Point2, b: Point2) -> bool:
    px, py = point
    ax, ay = a
    bx, by = b
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > EPS:
        return False
    return (min(ax, bx) - EPS <= px <= max(ax, bx) + EPS
            and min(ay, by) - EPS <= py <= max(ay, by) + EPS)


def _orientation(a: Point2, b: Point2, c: Point2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a: Point2, b: Point2, c: Point2, d: Point2) -> bool:
    bbox_ab = (min(a[0], b[0]), min(a[1], b[1]),
               max(a[0], b[0]), max(a[1], b[1]))
    bbox_cd = (min(c[0], d[0]), min(c[1], d[1]),
               max(c[0], d[0]), max(c[1], d[1]))
    if not _bbox_overlap(bbox_ab, bbox_cd):
        return False
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if ((o1 > EPS and o2 < -EPS) or (o1 < -EPS and o2 > EPS)) and (
        (o3 > EPS and o4 < -EPS) or (o3 < -EPS and o4 > EPS)
    ):
        return True
    return (
        _point_on_segment(c, a, b)
        or _point_on_segment(d, a, b)
        or _point_on_segment(a, c, d)
        or _point_on_segment(b, c, d)
    )
