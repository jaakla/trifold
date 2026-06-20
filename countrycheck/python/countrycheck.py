"""countrycheck — offline country lookup for lon/lat points (Trifold subproject).

A few-MB bundled dataset answers "which country is this point in?"
anywhere on Earth in microseconds, fully offline.  Built from the Trifold
level-10 grid (~7 km triangles) classified against GADM-derived country
polygons extended with coastal waters, so points slightly offshore still
resolve to the nearest coastal country.

    >>> from countrycheck import CountryCheck
    >>> cc = CountryCheck()
    >>> cc.country(24.75, 59.44)        # lon, lat — Tallinn
    'EST'
    >>> r = cc.check(-0.1276, 51.5072)  # London
    >>> r.country, r.iso2, r.name, r.kind
    ('GBR', 'GB', 'United Kingdom', 'country')

Answer semantics
----------------
kind='country'  cell is wholly inside one country  -> that country, confidence 1.0
kind='none'     cell absent from the dataset       -> no country,   confidence 1.0
                (international waters)
kind='border'   mixed cell (country/country or country/water edge); the
                bundled best call is used with its area share as confidence.

With the optional border refinement loaded, border cells are decided by a
point-in-polygon test against the exact clipped country polygons.
"""
from __future__ import annotations

import struct
import zlib
from array import array
from bisect import bisect_right
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Sequence

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

__all__ = [
    "CountryCheck",
    "CountryResult",
    "PolylineCountryResult",
    "PolylineCountrySegment",
]

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

_MAGIC = b"TFCS"

def _find_default_data() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here / "data" / "countries_L10.tfcs",          # installed package
                 here.parent / "data" / "countries_L10.tfcs"):  # repo checkout
        if cand.is_file():
            return cand
    return cand

_DEFAULT_DATA = _find_default_data()

_KIND_COUNTRY = "country"
_KIND_BORDER = "border"
_KIND_NONE = "none"


@dataclass(frozen=True)
class CountryResult:
    """One lookup answer."""
    country: str | None         #: country code (gid_0, e.g. 'EST'), None = no country
    iso2: str | None            #: ISO 3166-1 alpha-2 ('' for X-coded territories)
    name: str | None            #: English name
    kind: str                   #: 'country' | 'border' | 'none'
    confidence: float           #: probability the ``country`` call is right
    share: float | None         #: bundled area share of the call in this cell
    cell: str | None            #: compact Trifold address, None for open water
    refined: bool = False       #: True if a border refinement polygon decided it


_REFINED_CONFIDENCE = 0.99  # exact source polygons; quantization ~0.1 m


class CountryCheck:
    """Offline country point lookup. Thread-safe after construction.

    ``refine_path`` optionally loads a TFCR border-refinement dataset
    (built by build.py alongside the main file). Border cells are then
    decided by a point-in-polygon test against the exact clipped country
    polygons instead of the bundled per-cell best call.
    """

    def __init__(self, data_path: str | Path = _DEFAULT_DATA,
                 refine_path: str | Path | None = None):
        raw = Path(data_path).read_bytes()
        (magic, version, level, flags, _, n_runs, n_border,
         n_countries, _) = struct.unpack_from("<4sBBBBIIHH", raw, 0)
        if magic != _MAGIC:
            raise ValueError(f"{data_path}: not a TFCS file")
        if version != 1:
            raise ValueError(f"{data_path}: unsupported TFCS version {version}")
        self.level = level
        body = zlib.decompress(raw[20:])
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

        def read_str() -> str:
            nonlocal pos
            n = read_varint()
            s = body[pos:pos + n].decode("utf-8")
            pos += n
            return s

        self.countries = tuple(
            {"code": read_str(), "iso2": read_str(), "name": read_str()}
            for _ in range(n_countries))

        starts = array("I")
        ends = array("I")
        border = bytearray(n_runs)
        run_cid = array("H", bytes(2 * n_runs))
        border_before = array("I")  # border cells in runs before this one
        cursor = 0
        n_border_seen = 0
        for i in range(n_runs):
            cursor += read_varint()
            packed = read_varint()
            length = packed >> 1
            starts.append(cursor)
            ends.append(cursor + length)
            border_before.append(n_border_seen)
            if packed & 1:
                border[i] = 1
                n_border_seen += length
            else:
                run_cid[i] = read_varint()
            cursor += length
        if n_border_seen != n_border:
            raise ValueError(f"{data_path}: border count mismatch")

        calls = array("H")
        for _ in range(n_border):
            calls.append(read_varint())

        self._starts = starts
        self._ends = ends
        self._border = bytes(border)
        self._run_cid = run_cid
        self._border_before = border_before
        self._calls = calls
        self._shares = body[pos:] if flags & 1 else None
        if self._shares is not None and len(self._shares) < (n_border + 1) // 2:
            raise ValueError(f"{data_path}: truncated share block")

        self._refine = None
        if refine_path is not None:
            self.load_refinement(refine_path)

    def load_refinement(self, path: str | Path) -> None:
        """Load a TFCR border-refinement dataset (built by build.py)."""
        raw = Path(path).read_bytes()
        magic, version, level, _, _, n_cells = struct.unpack_from("<4sBBBBI", raw, 0)
        if magic != b"TFCR":
            raise ValueError(f"{path}: not a TFCR file")
        if version != 1:
            raise ValueError(f"{path}: unsupported TFCR version {version}")
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
            zones = []
            for _ in range(read_varint()):
                cid = read_varint()
                n_rings = read_varint()
                if n_rings == 0:
                    zones.append((cid, None))  # whole cell is this country
                    continue
                rings = []
                for _ in range(n_rings):
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
                zones.append((cid, rings))
            cells[index] = zones
        self._refine = cells

    def _refined_cid(self, index: int, lon: float, lat: float) -> int | None:
        """Exact country id from the refinement zones; -1 = no country,
        None = cell not covered by the refinement."""
        if self._refine is None:
            return None
        zones = self._refine.get(index)
        if zones is None:
            return None
        minx, miny, maxx, maxy = _ringbox(index, self.level)
        if maxx > 180.0 and lon < 0.0:
            lon += 360.0
        qx = (lon - minx) * 65535.0 / (maxx - minx)
        qy = (lat - miny) * 65535.0 / (maxy - miny)
        for cid, rings in zones:
            if rings is None:
                return cid
            inside = False  # even-odd rule over the zone's rings
            for pts in rings:
                n = len(pts) // 2
                x1, y1 = pts[2 * (n - 1)], pts[2 * (n - 1) + 1]
                for i in range(n):
                    x2, y2 = pts[2 * i], pts[2 * i + 1]
                    if (y1 > qy) != (y2 > qy):
                        if qx < x1 + (qy - y1) * (x2 - x1) / (y2 - y1):
                            inside = not inside
                    x1, y1 = x2, y2
            if inside:
                return cid
        return -1

    def _result_fields(self, cid: int | None):
        if cid is None:
            return None, None, None
        c = self.countries[cid]
        return c["code"], c["iso2"], c["name"]

    # ------------------------------------------------------------- lookups
    def check(self, lon: float, lat: float) -> CountryResult:
        """Full answer for one point (lon, lat in degrees, WGS84)."""
        if not -180.0 <= lon <= 180.0:
            raise ValueError("longitude must be in [-180, 180]")
        if not -90.0 <= lat <= 90.0:
            raise ValueError("latitude must be in [-90, 90]")
        index = _locate_index(lon, lat, self.level)
        run = bisect_right(self._starts, index) - 1
        hit = run >= 0 and index < self._ends[run]
        refined = self._refined_cid(index, lon, lat)
        if refined is not None:
            share = (self._share_at(run, index)
                     if hit and self._border[run] else (1.0 if hit else 0.0))
            cid = None if refined < 0 else refined
            code, iso2, name = self._result_fields(cid)
            return CountryResult(code, iso2, name, _KIND_BORDER,
                                 _REFINED_CONFIDENCE, share,
                                 _index_to_compact(index, self.level),
                                 refined=True)
        if not hit:
            return CountryResult(None, None, None, _KIND_NONE, 1.0, 0.0, None)
        cell = _index_to_compact(index, self.level)
        if not self._border[run]:
            code, iso2, name = self._result_fields(self._run_cid[run])
            return CountryResult(code, iso2, name, _KIND_COUNTRY, 1.0, 1.0, cell)
        call = self._calls[self._border_before[run] + (index - self._starts[run])]
        share = self._share_at(run, index)
        cid = None if call == 0 else call - 1
        code, iso2, name = self._result_fields(cid)
        confidence = 0.5 if share is None else share
        return CountryResult(code, iso2, name, _KIND_BORDER,
                             confidence, share, cell)

    def country(self, lon: float, lat: float) -> str | None:
        """Best country code (gid_0) for one point, None = no country."""
        index = _locate_index(lon, lat, self.level)
        refined = self._refined_cid(index, lon, lat)
        if refined is not None:
            return None if refined < 0 else self.countries[refined]["code"]
        run = bisect_right(self._starts, index) - 1
        if run < 0 or index >= self._ends[run]:
            return None
        if not self._border[run]:
            return self.countries[self._run_cid[run]]["code"]
        call = self._calls[self._border_before[run] + (index - self._starts[run])]
        return None if call == 0 else self.countries[call - 1]["code"]

    def country_batch(self, lons, lats):
        """Vectorised lookup for many points (requires numpy + trifold).

        Returns a list of country codes (None for no country); orders of
        magnitude faster than a Python loop for large inputs.
        """
        import numpy as np
        from trifold.api import locate_address_batch

        addrs = locate_address_batch(lons, lats, self.level)
        index = (addrs >> np.uint64(59 - 2 * self.level)).astype(np.int64)
        starts = np.frombuffer(self._starts, dtype=np.uint32).astype(np.int64)
        ends = np.frombuffer(self._ends, dtype=np.uint32).astype(np.int64)
        run = np.searchsorted(starts, index, side="right") - 1
        safe = np.maximum(run, 0)
        hit = (run >= 0) & (index < ends[safe])
        border = np.frombuffer(self._border, dtype=np.uint8).astype(bool)
        run_cid = np.frombuffer(self._run_cid, dtype=np.uint16).astype(np.int64)
        calls = np.frombuffer(self._calls, dtype=np.uint16).astype(np.int64)
        border_before = np.frombuffer(self._border_before,
                                      dtype=np.uint32).astype(np.int64)
        cid = np.full(len(index), -1, dtype=np.int64)  # -1 = no country
        is_interior = hit & ~border[safe]
        cid[is_interior] = run_cid[safe[is_interior]]
        is_border = hit & border[safe]
        n = border_before[safe[is_border]] + index[is_border] - starts[safe[is_border]]
        cid[is_border] = calls[n] - 1
        if self._refine:
            for pos, cell_index in enumerate(index):
                idx = int(cell_index)
                if idx in self._refine:
                    refined = self._refined_cid(
                        idx, float(lons[pos]), float(lats[pos]))
                    if refined is not None:
                        cid[pos] = refined
        return [None if c < 0 else self.countries[c]["code"] for c in cid]

    def iso2(self, lon: float, lat: float) -> str | None:
        """Best ISO 3166-1 alpha-2 code for one point (None if no country
        or the territory has no ISO code)."""
        code = self.country(lon, lat)
        if code is None:
            return None
        iso2 = next(c["iso2"] for c in self.countries if c["code"] == code)
        return iso2 or None

    # ------------------------------------------------------------- helpers
    def _share_at(self, run: int, index: int) -> float | None:
        if self._shares is None:
            return None
        n = self._border_before[run] + (index - self._starts[run])
        byte = self._shares[n >> 1]
        q = (byte >> 4) if n & 1 else (byte & 0x0F)
        return (q + 0.5) / 16.0

    @property
    def stats(self) -> dict:
        """Dataset summary (for diagnostics)."""
        n_border = sum(e - s for s, e, b in
                       zip(self._starts, self._ends, self._border) if b)
        n_interior = sum(e - s for s, e, b in
                         zip(self._starts, self._ends, self._border) if not b)
        return {
            "level": self.level,
            "countries": len(self.countries),
            "runs": len(self._starts),
            "interior_cells": n_interior,
            "border_cells": n_border,
            "has_shares": self._shares is not None,
            "has_refinement": self._refine is not None,
        }

    # ----------------------------------------------------- polyline lookups
    def check_polyline(
        self,
        coords: Sequence[tuple[float, float]],
        *,
        step_km: float = 3.5,
        mode: str = "uniform",
    ) -> PolylineCountryResult:
        """Country classification for every segment of a polyline.

        Samples the line at ``step_km`` intervals (or at vertices only if
        ``mode='vertex'``), runs the point lookup at each sample, then
        merges consecutive samples with the same country code into directed
        distance-annotated segments. The optional border refinement is used
        when loaded.

        Parameters
        ----------
        coords : list of (lon, lat)
            Polyline vertices in WGS84 degrees.
        step_km : float
            Sample spacing (default 3.5 km).
        mode : str
            ``"uniform"`` or ``"vertex"``.

        Returns
        -------
        PolylineCountryResult
            Segments ordered along the line.
        """
        from trifold.api import sample_polyline

        samples, cumulative_km, _segment_ids = sample_polyline(
            list(coords), step_km=step_km, mode=mode)
        total_km = float(cumulative_km[-1]) if len(cumulative_km) > 0 else 0.0

        # collect per-sample country results
        results: list[CountryResult] = []
        for lon, lat in samples:
            results.append(self.check(float(lon), float(lat)))

        # merge consecutive same-(country,kind) samples into segments
        segments = _merge_country_segments(results, cumulative_km)

        # compute fractions
        for seg in segments:
            seg.fraction = seg.distance_km / total_km if total_km > 0 else 0.0

        # stats
        unique = sorted(set(s.country for s in segments if s.country))
        n_segments = len(segments)
        refined = self._refine is not None
        stats = {
            "total_distance_km": total_km,
            "n_segments": n_segments,
            "unique_countries": len(unique),
            "countries": unique,
            "refined": refined,
        }
        return PolylineCountryResult(
            segments=segments,
            total_distance_km=total_km,
            stats=stats,
            refined=refined,
        )

    def country_polyline(
        self,
        coords: Sequence[tuple[float, float]],
        *,
        step_km: float = 3.5,
        mode: str = "uniform",
    ) -> list[PolylineCountrySegment]:
        """Return the directed country segments for a polyline.

        Equivalent to :meth:`check_polyline` but returns only the segment
        list without the wrapper result.
        """
        return self.check_polyline(coords, step_km=step_km, mode=mode).segments


@dataclass
class PolylineCountrySegment:
    """One contiguous segment of a polyline classified to a single country."""

    country: str | None   #: country code (gid_0), None = no country
    iso2: str | None      #: ISO 3166-1 alpha-2
    name: str | None      #: English name
    kind: str             #: 'country' | 'border' | 'none'
    confidence: float     #: mean point confidence across the segment
    distance_km: float    #: length of this segment in km along the line
    fraction: float = 0.0  #: segment distance / total polyline distance


@dataclass
class PolylineCountryResult:
    """Full result of a polyline country check."""

    segments: list[PolylineCountrySegment]
    total_distance_km: float
    stats: dict
    refined: bool = False


def _merge_country_segments(
    results: list[CountryResult],
    cumulative_km: np.ndarray,
) -> list[PolylineCountrySegment]:
    """Merge consecutive samples that share the same country.

    Grouping is by country identity only, so one continuous country run is a
    single segment even where it crosses interior and border cells. The
    segment ``kind`` is the uniform sample kind, or ``"border"`` when the run
    mixes kinds (it touched at least one mixed cell). Segment boundaries are
    placed at midpoints between samples of different countries, so single-
    sample segments get a non-zero distance and edge segments start/end at the
    polyline endpoints.
    """
    import numpy as np

    n = len(results)

    groups = []
    for country, g in groupby(enumerate(results), key=lambda x: x[1].country):
        idxs = [i for i, _ in g]
        groups.append((country, idxs[0], idxs[-1]))

    segments = []
    for country, start_idx, end_idx in groups:
        # segment start: midpoint to previous sample (or 0 for first)
        if start_idx == 0:
            start_km = 0.0
        else:
            start_km = (cumulative_km[start_idx - 1] + cumulative_km[start_idx]) / 2.0

        # segment end: midpoint to next sample (or last cumulative for final)
        if end_idx == n - 1:
            end_km = cumulative_km[-1]
        else:
            end_km = (cumulative_km[end_idx] + cumulative_km[end_idx + 1]) / 2.0

        seg_len = max(end_km - start_km, 0.0)
        run = [results[i] for i in range(start_idx, end_idx + 1)]
        mean_conf = float(np.mean([s.confidence for s in run]))
        kinds = {s.kind for s in run}
        kind = next(iter(kinds)) if len(kinds) == 1 else "border"
        r = run[0]
        segments.append(
            PolylineCountrySegment(
                country=country,
                iso2=r.iso2,
                name=r.name,
                kind=kind,
                confidence=mean_conf,
                distance_km=seg_len,
            )
        )
    return segments


def _main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="countrycheck", description="offline country lookup for a point")
    ap.add_argument("lon", type=float, help="longitude (-180..180)")
    ap.add_argument("lat", type=float, help="latitude (-90..90)")
    ap.add_argument("--data", default=_DEFAULT_DATA)
    ap.add_argument("--refine", default=None,
                    help="optional TFCR border-refinement file")
    args = ap.parse_args(argv)
    refine = args.refine
    if refine is None:
        default_tfcr = Path(args.data).parent / "borders_L10.tfcr"
        refine = default_tfcr if default_tfcr.exists() else None
    result = CountryCheck(args.data, refine_path=refine).check(args.lon, args.lat)
    print(f"{result.country or 'NO COUNTRY'}  iso2={result.iso2}  "
          f"name={result.name!r}  kind={result.kind}  "
          f"confidence={result.confidence:.3f}  share={result.share}  "
          f"cell={result.cell}  refined={result.refined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
