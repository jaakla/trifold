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

from .address import (
    MAX_LEVEL,
    children64,
    decode64,
    descendant_range,
    encode64,
    face_of,
    from_compact,
    from_path,
    is_ancestor,
    level_of,
    parent64,
    path_of,
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
    slerp,
    subdivide,
    unwrap_ring_lonlat,
    xyz_to_lonlat,
)
from .grid import build_compacted, cell_geometry_ring, expand_to_base

AddressLike: TypeAlias = int | str | tuple[int, Sequence[int]]

__all__ = [
    "AddressLike",
    "EARTH_R",
    "EXPORT_DEPTH",
    "MAX_LEVEL",
    "area_km2",
    "build_compacted",
    "build_export_ring",
    "cell_feature",
    "cell_geometry_ring",
    "cell_metrics",
    "cell_ring",
    "cell_triangle",
    "children64",
    "contains_point",
    "decode64",
    "densified_ring_xyz",
    "descendant_range",
    "edge_km",
    "encode64",
    "expand_to_base",
    "face_of",
    "from_compact",
    "from_path",
    "icosahedron",
    "is_ancestor",
    "level_of",
    "locate",
    "locate_address",
    "parent64",
    "parse_address",
    "path_of",
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
            "level": len(digits),
            "pole": pole,
        },
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
    }
