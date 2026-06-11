"""landcheck — offline land/sea lookup for lon/lat points (Trifold subproject).

A ~180 KB bundled dataset answers "is this point on land?" anywhere on
Earth in microseconds, fully offline.  Built from the Trifold level-10
grid (~7 km triangles) classified against Natural Earth 1:50m land.

    >>> from landcheck import LandCheck
    >>> lc = LandCheck()
    >>> lc.is_land(24.75, 59.44)        # lon, lat — Tallinn
    True
    >>> r = lc.check(-0.1276, 51.5072)  # London
    >>> r.land, r.kind, round(r.confidence, 2)
    (True, 'land', 1.0)

Answer semantics
----------------
kind='land'   cell is wholly inside land            -> land, confidence 1.0
kind='sea'    cell absent from the dataset           -> sea,  confidence 1.0
kind='coast'  mixed cell; the bundled land fraction of the cell is used:
              land = fraction >= 0.5, confidence = max(f, 1 - f).

Confidence is relative to the source dataset (Natural Earth 1:50m).
Features smaller than its resolution — islets, narrow fjords — can be
misrepresented; 'coast' answers flag exactly where that risk lives.
"""
from __future__ import annotations

import struct
import zlib
from array import array
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

try:
    from ._fastloc import (locate_index as _locate_index,
                           index_to_lonlat_ring as _index_to_ring)
except ImportError:  # imported as a plain module, not a package
    from _fastloc import (locate_index as _locate_index,
                          index_to_lonlat_ring as _index_to_ring)


def _ringbox(index: int, level: int) -> tuple[float, float, float, float]:
    ring = _index_to_ring(index, level)
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return min(lons), min(lats), max(lons), max(lats)

__all__ = ["LandCheck", "LandResult"]

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford, as trifold.address


def _index_to_compact(index: int, level: int) -> str:
    """Compact Trifold address of a canonical cell index (e.g. 'TFAVKGR')."""
    face = index >> (2 * level)
    path = index & ((1 << (2 * level)) - 1)
    bits = 2 * level
    pad = (-bits) % 5
    path <<= pad
    chars = []
    for shift in range(bits + pad - 5, -1, -5):
        chars.append(_B32[(path >> shift) & 0x1F])
    return "T" + _B32[face] + _B32[level] + "".join(chars)

_MAGIC = b"TFLS"
_DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "landsea_L10.tfls"

_KIND_LAND = "land"
_KIND_COAST = "coast"
_KIND_SEA = "sea"


@dataclass(frozen=True)
class LandResult:
    """One lookup answer."""
    land: bool                  #: best land/sea call
    kind: str                   #: 'land' | 'coast' | 'sea'
    confidence: float           #: probability the ``land`` bool is right
    land_fraction: float | None  #: land share of the cell (None if not bundled)
    cell: str | None            #: compact Trifold address, None for open sea
    refined: bool = False       #: True if a coastal refinement polygon decided it


_REFINED_CONFIDENCE = 0.99  # OSM simplified polygons; quantization ~0.1 m


class LandCheck:
    """Offline land/sea point lookup. Thread-safe after construction.

    ``refine_path`` optionally loads a TFLR coastal-refinement dataset
    (see refine_build.py): 'coast' answers are then decided by an exact
    point-in-polygon test against clipped land polygons instead of the
    cell's bulk land fraction.
    """

    def __init__(self, data_path: str | Path = _DEFAULT_DATA,
                 refine_path: str | Path | None = None):
        raw = Path(data_path).read_bytes()
        magic, version, level, flags, _, n_runs, n_coast = struct.unpack_from(
            "<4sBBBBII", raw, 0)
        if magic != _MAGIC:
            raise ValueError(f"{data_path}: not a TFLS file")
        if version != 1:
            raise ValueError(f"{data_path}: unsupported TFLS version {version}")
        self.level = level
        body = zlib.decompress(raw[16:])

        starts = array("I")
        ends = array("I")
        coastal = bytearray(n_runs)
        coast_before = array("I")  # coastal cells in runs before this one
        pos = 0
        cursor = 0
        n_coast_seen = 0

        def read_varint() -> int:
            nonlocal pos
            shift = 0
            value = 0
            while True:
                b = body[pos]
                pos += 1
                value |= (b & 0x7F) << shift
                if not b & 0x80:
                    return value
                shift += 7

        for i in range(n_runs):
            cursor += read_varint()
            packed = read_varint()
            length = packed >> 1
            starts.append(cursor)
            ends.append(cursor + length)
            coast_before.append(n_coast_seen)
            if packed & 1:
                coastal[i] = 1
                n_coast_seen += length
            cursor += length
        if n_coast_seen != n_coast:
            raise ValueError(f"{data_path}: coastal count mismatch")

        self._starts = starts
        self._ends = ends
        self._coastal = bytes(coastal)
        self._coast_before = coast_before
        self._fractions = body[pos:] if flags & 1 else None
        if self._fractions is not None and len(self._fractions) < (n_coast + 1) // 2:
            raise ValueError(f"{data_path}: truncated fraction block")

        self._refine = None
        if refine_path is not None:
            self.load_refinement(refine_path)

    def load_refinement(self, path: str | Path) -> None:
        """Load a TFLR coastal-refinement dataset (built by refine_build.py)."""
        raw = Path(path).read_bytes()
        magic, version, level, _, _, n_cells = struct.unpack_from("<4sBBBBI", raw, 0)
        if magic != b"TFLR":
            raise ValueError(f"{path}: not a TFLR file")
        if version != 1:
            raise ValueError(f"{path}: unsupported TFLR version {version}")
        if level != self.level:
            raise ValueError(f"{path}: level {level} != dataset level {self.level}")
        body = zlib.decompress(raw[12:])
        pos = 0

        def read_varint() -> int:
            nonlocal pos
            shift = 0
            value = 0
            while True:
                b = body[pos]
                pos += 1
                value |= (b & 0x7F) << shift
                if not b & 0x80:
                    return value
                shift += 7

        cells = {}
        index = 0
        for _ in range(n_cells):
            index += read_varint()
            code = read_varint()
            if code < 2:
                cells[index] = code  # 0 = all sea, 1 = all land
            else:
                rings = []
                for _ in range(code - 1):
                    n_pts = read_varint()
                    pts = array("i")
                    x = y = 0
                    for _ in range(n_pts):
                        zx, zy = read_varint(), read_varint()
                        x += (zx >> 1) ^ -(zx & 1)
                        y += (zy >> 1) ^ -(zy & 1)
                        pts.append(x)
                        pts.append(y)
                    rings.append(pts)
                cells[index] = rings
        self._refine = cells

    def _refined_land(self, index: int, lon: float, lat: float) -> bool | None:
        """Exact land/sea from the refinement polygons, None if unavailable."""
        if self._refine is None:
            return None
        entry = self._refine.get(index)
        if entry is None:
            return None
        if isinstance(entry, int):
            return bool(entry)
        ring = _ringbox(index, self.level)
        (minx, miny, maxx, maxy) = ring
        if maxx > 180.0 and lon < 0.0:
            lon += 360.0
        qx = (lon - minx) * 65535.0 / (maxx - minx)
        qy = (lat - miny) * 65535.0 / (maxy - miny)
        inside = False  # even-odd rule over all rings
        for pts in entry:
            n = len(pts) // 2
            x1, y1 = pts[2 * (n - 1)], pts[2 * (n - 1) + 1]
            for i in range(n):
                x2, y2 = pts[2 * i], pts[2 * i + 1]
                if (y1 > qy) != (y2 > qy):
                    if qx < x1 + (qy - y1) * (x2 - x1) / (y2 - y1):
                        inside = not inside
                x1, y1 = x2, y2
        return inside

    # ------------------------------------------------------------- lookups
    def check(self, lon: float, lat: float) -> LandResult:
        """Full answer for one point (lon, lat in degrees, WGS84)."""
        if not -180.0 <= lon <= 180.0:
            raise ValueError("longitude must be in [-180, 180]")
        if not -90.0 <= lat <= 90.0:
            raise ValueError("latitude must be in [-90, 90]")
        index = _locate_index(lon, lat, self.level)
        run = bisect_right(self._starts, index) - 1
        if run < 0 or index >= self._ends[run]:
            return LandResult(False, _KIND_SEA, 1.0, 0.0, None)
        cell = _index_to_compact(index, self.level)
        if not self._coastal[run]:
            return LandResult(True, _KIND_LAND, 1.0, 1.0, cell)
        fraction = self._fraction_at(run, index)
        refined = self._refined_land(index, lon, lat)
        if refined is not None:
            return LandResult(refined, _KIND_COAST, _REFINED_CONFIDENCE,
                              fraction, cell, refined=True)
        if fraction is None:
            return LandResult(True, _KIND_COAST, 0.5, None, cell)
        return LandResult(fraction >= 0.5, _KIND_COAST,
                          max(fraction, 1.0 - fraction), fraction, cell)

    def is_land(self, lon: float, lat: float) -> bool:
        """Best land/sea bool for one point."""
        index = _locate_index(lon, lat, self.level)
        run = bisect_right(self._starts, index) - 1
        if run < 0 or index >= self._ends[run]:
            return False
        if not self._coastal[run]:
            return True
        refined = self._refined_land(index, lon, lat)
        if refined is not None:
            return refined
        fraction = self._fraction_at(run, index)
        return True if fraction is None else fraction >= 0.5

    def is_land_batch(self, lons, lats):
        """Vectorised lookup for many points (requires numpy + trifold).

        Returns a boolean numpy array; orders of magnitude faster than a
        Python loop for large inputs.
        """
        import numpy as np
        from trifold.api import locate_address_batch

        addrs = locate_address_batch(lons, lats, self.level)
        index = (addrs >> np.uint64(59 - 2 * self.level)).astype(np.int64)
        starts = np.frombuffer(self._starts, dtype=np.uint32).astype(np.int64)
        ends = np.frombuffer(self._ends, dtype=np.uint32).astype(np.int64)
        run = np.searchsorted(starts, index, side="right") - 1
        hit = (run >= 0) & (index < ends[np.maximum(run, 0)])
        out = np.zeros(len(index), dtype=bool)
        coastal = np.frombuffer(self._coastal, dtype=np.uint8).astype(bool)
        hit_runs = run[hit]
        is_coast = coastal[hit_runs]
        land = ~is_coast
        if self._fractions is not None and is_coast.any():
            coast_before = np.frombuffer(self._coast_before,
                                         dtype=np.uint32).astype(np.int64)
            n = (coast_before[hit_runs] + index[hit] - starts[hit_runs])[is_coast]
            nib = np.frombuffer(self._fractions, dtype=np.uint8)[n >> 1]
            q = np.where(n & 1, nib >> 4, nib & 0x0F)
            land = land.copy()
            land[is_coast] = q >= 8  # fraction (q+0.5)/16 >= 0.5
        else:
            land = land | is_coast  # no fractions: coast counts as land
        out[hit] = land
        return out

    # ------------------------------------------------------------- helpers
    def _fraction_at(self, run: int, index: int) -> float | None:
        if self._fractions is None:
            return None
        n = self._coast_before[run] + (index - self._starts[run])
        byte = self._fractions[n >> 1]
        q = (byte >> 4) if n & 1 else (byte & 0x0F)
        return (q + 0.5) / 16.0

    @property
    def stats(self) -> dict:
        """Dataset summary (for diagnostics)."""
        n_coast = sum(e - s for s, e, c in
                      zip(self._starts, self._ends, self._coastal) if c)
        n_land = sum(e - s for s, e, c in
                     zip(self._starts, self._ends, self._coastal) if not c)
        return {
            "level": self.level,
            "runs": len(self._starts),
            "interior_cells": n_land,
            "coastal_cells": n_coast,
            "has_fractions": self._fractions is not None,
            "has_refinement": self._refine is not None,
        }


def _main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="landcheck", description="offline land/sea lookup for a point")
    ap.add_argument("lon", type=float, help="longitude (-180..180)")
    ap.add_argument("lat", type=float, help="latitude (-90..90)")
    ap.add_argument("--data", default=_DEFAULT_DATA)
    ap.add_argument("--refine", default=None,
                    help="optional TFLR coastal-refinement file")
    args = ap.parse_args(argv)
    refine = args.refine
    if refine is None:
        default_tflr = Path(args.data).parent / "coastal_osm_L10.tflr"
        refine = default_tflr if default_tflr.exists() else None
    result = LandCheck(args.data, refine_path=refine).check(args.lon, args.lat)
    print(f"{'LAND' if result.land else 'SEA'}  kind={result.kind}  "
          f"confidence={result.confidence:.3f}  "
          f"land_fraction={result.land_fraction}  cell={result.cell}  "
          f"refined={result.refined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
