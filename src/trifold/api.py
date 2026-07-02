"""Public Python SDK for the Trifold triangular grid.

Applications should import from this module (or from :mod:`trifold`, which
re-exports the same names).  The implementation modules remain available for
advanced use, but are not the compatibility boundary.

The SDK is split into four groups:

* address codecs and hierarchy operations;
* spherical grid geometry and point location;
* GeoJSON helpers for individual cells;
* land-adaptive coverage generation through a classifier object.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeAlias

import numpy as np

from .address import (
    LEVEL_BITS,
    MAX_LEVEL,
    children64,
    decode64,
    decode_rhombus64,
    descendant_range,
    encode64,
    face_of,
    from_compact,
    from_path,
    is_ancestor,
    hex_id,
    level_of,
    lattice_triangle,
    parent64,
    path_of,
    rhombus64,
    rhombus_coords,
    rhombus_id,
    to_compact,
    to_path,
)
from .core import (
    EARTH_R,
    EXPORT_DEPTH,
    area_km2,
    build_export_ring,
    cell_triangle,
    contains_point,
    densified_ring_xyz,
    edge_km,
    icosahedron,
    locate,
    locate_batch,
    slerp,
    subdivide,
    unwrap_ring_lonlat,
    xyz_to_lonlat,
)
from .grid import build_compacted, cell_geometry_ring, expand_to_base
from .cover import bbox_cover, cover_ranges, hilbert_ranges, polyfill

AddressLike: TypeAlias = int | str | tuple[int, Sequence[int]]

__all__ = [
    "AddressLike",
    "EARTH_R",
    "EXPORT_DEPTH",
    "MAX_LEVEL",
    "area_km2",
    "build_compacted",
    "bbox_cover",
    "build_export_ring",
    "cell_feature",
    "cell_geometry_ring",
    "cell_metrics",
    "cell_ring",
    "cell_triangle",
    "children64",
    "contains_point",
    "cover_ranges",
    "hilbert_ranges",
    "decode64",
    "decode_rhombus64",
    "densified_ring_xyz",
    "descendant_range",
    "edge_km",
    "encode64",
    "expand_to_base",
    "face_of",
    "from_compact",
    "from_path",
    "hex_id",
    "icosahedron",
    "is_ancestor",
    "lattice_triangle",
    "level_of",
    "locate",
    "locate_address",
    "locate_address_batch",
    "locate_batch",
    "parent64",
    "parse_address",
    "path_of",
    "polyfill",
    "rhombus64",
    "rhombus_coords",
    "rhombus_id",
    "sample_polyline",
    "slerp",
    "subdivide",
    "to_compact",
    "to_path",
    "unwrap_ring_lonlat",
    "xyz_to_lonlat",
]


def parse_address(address: AddressLike) -> int:
    """Normalize an address to its unsigned 64-bit integer representation.

    ``address`` may be an integer, a compact address such as ``TF6958``, a
    path address such as ``F15-102111``, or a ``(face, digits)`` tuple.
    """
    if isinstance(address, bool):
        raise TypeError("boolean values are not Trifold addresses")
    if isinstance(address, int):
        if not 0 <= address < 1 << 64:
            raise ValueError(f"addr64 value {address} is outside uint64")
        face, digits = decode64(address)
        if not 0 <= face < 20 or len(digits) > MAX_LEVEL:
            raise ValueError(f"invalid addr64 value {address}")
        return address
    if isinstance(address, str):
        text = address.strip()
        return from_path(text) if text.upper().startswith("F") else from_compact(text)
    if isinstance(address, tuple) and len(address) == 2:
        face, digits = address
        return encode64(int(face), tuple(int(digit) for digit in digits))
    raise TypeError("address must be an int, string, or (face, digits) tuple")


def locate_address(lon: float, lat: float, level: int) -> int:
    """Return the addr64 cell containing ``(lon, lat)`` at ``level``."""
    if not -180 <= lon <= 180:
        raise ValueError("longitude must be in [-180, 180]")
    if not -90 <= lat <= 90:
        raise ValueError("latitude must be in [-90, 90]")
    if not 0 <= level <= MAX_LEVEL:
        raise ValueError(f"level must be in [0, {MAX_LEVEL}]")
    return encode64(*locate(lon, lat, level))


def locate_address_batch(lons, lats, level: int, chunk_size: int = 1_000_000):
    """Vectorised point location returning addr64 values.

    Equivalent to calling :func:`locate_address` on every element, but
    processes the full array with numpy — typically **100–1000× faster**
    than a Python loop.

    Parameters
    ----------
    lons, lats : array-like of float
        Longitude (−180 .. 180) and latitude (−90 .. 90).
    level : int
        Subdivision level (0 .. ``MAX_LEVEL``).
    chunk_size : int, optional
        Max points per processing chunk (controls peak memory).

    Returns
    -------
    numpy.ndarray of uint64
        One addr64 value per input point.
    """
    faces, path_bits = locate_batch(lons, lats, level,
                                    chunk_size=chunk_size)
    path_left = path_bits << np.uint64(2 * (MAX_LEVEL - level))
    return (faces.astype(np.uint64) << np.uint64(59)
            | path_left << np.uint64(LEVEL_BITS)
            | np.uint64(level))


def cell_ring(
    address: AddressLike,
    *,
    depth: int = EXPORT_DEPTH,
    precision: int | None = None,
    close: bool = True,
) -> list[list[float]]:
    """Return a cell boundary as continuous-longitude ``[lon, lat]`` pairs.

    Longitudes may extend outside ``[-180, 180]`` for antimeridian cells.
    Pole cells use the meridian-wedge representation documented by Trifold.
    """
    addr = parse_address(address)
    face, digits = decode64(addr)
    triangle = cell_triangle(face, digits)
    points = densified_ring_xyz(triangle, level=len(digits), depth=depth)
    ring, _ = build_export_ring(points, triangle)
    if precision is not None:
        result = [[round(float(lon), precision), round(float(lat), precision)]
                  for lon, lat in ring]
    else:
        result = [[float(lon), float(lat)] for lon, lat in ring]
    if close and result:
        result.append(result[0].copy())
    return result


def cell_metrics(address: AddressLike) -> dict[str, float | int | str]:
    """Return identifiers and spherical size metrics for one cell."""
    addr = parse_address(address)
    face, digits = decode64(addr)
    triangle = cell_triangle(face, digits)
    return {
        "id": to_compact(addr),
        "path": to_path(addr),
        "addr64": addr,
        "rhombus_id": rhombus_id(addr),
        "rhombus_hilbert": rhombus64(addr),
        "hex_id": hex_id(addr),
        "face": face,
        "level": len(digits),
        "edge_km": edge_km(triangle),
        "area_km2": area_km2(triangle),
    }


def cell_feature(address: AddressLike, *, precision: int = 6) -> dict[str, Any]:
    """Return a GeoJSON Feature for one cell.

    ``addr64`` is serialized as a decimal string because JavaScript JSON
    numbers cannot represent every unsigned 64-bit integer exactly.
    """
    addr = parse_address(address)
    face, digits = decode64(addr)
    triangle = cell_triangle(face, digits)
    points = densified_ring_xyz(triangle, level=len(digits))
    ring, pole = build_export_ring(points, triangle)
    coordinates = [[round(float(lon), precision), round(float(lat), precision)]
                   for lon, lat in ring]
    coordinates.append(coordinates[0].copy())
    return {
        "type": "Feature",
        "properties": {
            "id": to_compact(addr),
            "path": to_path(addr),
            "addr64": str(addr),
            "rhombus_id": rhombus_id(addr),
            "rhombus_hilbert": str(rhombus64(addr)),
            "hex_id": hex_id(addr),
            "level": len(digits),
            "pole": pole,
        },
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
    }


def sample_polyline(
    coords: list[tuple[float, float]],
    step_km: float = 3.5,
    mode: str = "uniform",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample a polyline at uniform great-circle intervals.

    Parameters
    ----------
    coords : list of (lon, lat) pairs
        The polyline vertices in WGS84 degrees.
    step_km : float
        Approximate sample spacing in km (default 3.5, half the L10 ~7 km
        cell edge).
    mode : str
        ``"uniform"`` — walk each segment at ``step_km`` intervals via
        great-circle slerp (vertices are always included).
        ``"vertex"`` — only the original vertices are returned.

    Returns
    -------
    samples : (N, 2) ndarray of [lon, lat]
        Sample points along the polyline.
    cumulative_km : (N,) ndarray
        Distance from the start of the polyline to each sample.
    segment_ids : (N,) ndarray of int
        Index of the original polyline segment each sample belongs to
        (0-based, i.e. the edge between vertex i and i+1).
    """
    if len(coords) < 2:
        raise ValueError("polyline must have at least 2 vertices")
    if mode not in ("uniform", "vertex"):
        raise ValueError("mode must be 'uniform' or 'vertex'")

    if mode == "vertex":
        samples = np.array(coords, dtype=np.float64)
        # compute great-circle distances between consecutive vertices
        n = len(coords)
        cumulative_km = np.zeros(n, dtype=np.float64)
        segment_ids = np.zeros(n, dtype=np.int64)
        for i in range(1, n):
            lon1, lat1 = coords[i - 1]
            lon2, lat2 = coords[i]
            d = _great_circle_km(lon1, lat1, lon2, lat2)
            cumulative_km[i] = cumulative_km[i - 1] + d
            segment_ids[i] = i - 1
        return samples, cumulative_km, segment_ids

    # uniform mode: walk each segment at step_km intervals
    samples_list: list[tuple[float, float]] = []
    dists_list: list[float] = []
    seg_list: list[int] = []
    running_km = 0.0

    for seg_idx in range(len(coords) - 1):
        lon1, lat1 = coords[seg_idx]
        lon2, lat2 = coords[seg_idx + 1]
        seg_len = _great_circle_km(lon1, lat1, lon2, lat2)

        # include the segment start vertex
        if len(samples_list) == 0:
            samples_list.append((lon1, lat1))
            dists_list.append(running_km)
            seg_list.append(seg_idx)

        if seg_len < 1e-9:
            continue

        n_steps = max(1, int(np.ceil(seg_len / step_km)))
        # walk along the great-circle arc
        p1 = _lonlat_to_xyz(lon1, lat1)
        p2 = _lonlat_to_xyz(lon2, lat2)
        for step in range(1, n_steps):
            t = step / n_steps
            pt = slerp(p1, p2, t)
            slon, slat = xyz_to_lonlat(pt)
            samples_list.append((float(slon), float(slat)))
            dists_list.append(running_km + step * (seg_len / n_steps))
            seg_list.append(seg_idx)

        running_km += seg_len

        # include the segment end vertex
        samples_list.append((lon2, lat2))
        dists_list.append(running_km)
        seg_list.append(seg_idx)

    samples = np.array(samples_list, dtype=np.float64)
    cumulative_km = np.array(dists_list, dtype=np.float64)
    segment_ids = np.array(seg_list, dtype=np.int64)
    return samples, cumulative_km, segment_ids


def _lonlat_to_xyz(lon: float, lat: float) -> np.ndarray:
    """Convert WGS84 lon/lat (degrees) to unit-sphere XYZ."""
    lam = np.radians(lon)
    phi = np.radians(lat)
    cp = np.cos(phi)
    return np.array([cp * np.cos(lam), cp * np.sin(lam), np.sin(phi)])


def _great_circle_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km between two lon/lat points (WGS84)."""
    p1 = _lonlat_to_xyz(lon1, lat1)
    p2 = _lonlat_to_xyz(lon2, lat2)
    dot = np.clip(np.dot(p1, p2), -1.0, 1.0)
    return float(np.arccos(dot)) * EARTH_R
