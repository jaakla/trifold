"""Cell covering helpers for bbox and GeoJSON polygon queries.

These routines are dependency-free and intentionally conservative.  They
operate in WGS84 lon/lat space over Trifold's exported cell rings, then let
callers apply exact post-filters when a query needs exact point or geometry
membership.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

from .address import MAX_LEVEL, descendant_range, encode64
from .core import (
    build_export_ring,
    contains_point,
    densified_ring_xyz,
    icosahedron,
    subdivide,
)

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


def _cover(level: int, overlaps_query, accepts) -> list[int]:
    verts, faces = icosahedron()
    out: set[int] = set()

    def recurse(face: int, digits: tuple[int, ...], tri) -> None:
        ring = _cell_ring(tri, len(digits))
        if not overlaps_query(ring):
            return
        if len(digits) == level:
            if accepts(ring, tri):
                out.add(encode64(face, digits))
            return
        for digit, child in enumerate(subdivide(tri)):
            recurse(face, (*digits, digit), child)

    for face, (i, j, k) in enumerate(faces):
        recurse(face, (), (verts[i], verts[j], verts[k]))
    return sorted(out)


def _cell_ring(tri, level: int) -> Ring:
    pts = densified_ring_xyz(tri, level=level)
    ring, _ = build_export_ring(pts, tri)
    return [(float(lon), float(lat)) for lon, lat in ring]


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
    point = tri[0] + tri[1] + tri[2]
    point = point / np.linalg.norm(point)
    lon = float(np.degrees(np.arctan2(point[1], point[0])))
    lat = float(np.degrees(np.arcsin(np.clip(point[2], -1, 1))))
    return lon, lat


def _lonlat_to_xyz(lon: float, lat: float):
    lam = np.radians(lon)
    phi = np.radians(lat)
    cp = np.cos(phi)
    return np.array([cp * np.cos(lam), cp * np.sin(lam), np.sin(phi)])


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
        if any(contains_point(tri, _lonlat_to_xyz(lon, lat))
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
        if any(contains_point(tri, _lonlat_to_xyz(lon, lat))
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
