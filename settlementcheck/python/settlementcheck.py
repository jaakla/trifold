"""Offline GHS-WUP Degree of Urbanisation lookup on the Trifold T3 grid."""
from __future__ import annotations

import argparse
import json
import struct
import zlib
from array import array
from bisect import bisect_right
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from ._fastloc import locate_index as _locate_index
except ImportError:
    from _fastloc import locate_index as _locate_index

__all__ = ["SettlementCheck", "SettlementResult", "CLASSES"]

CLASSES = {
    30: ("urban_centre", "Urban centre", 3, "urban_centre"),
    23: ("dense_urban_cluster", "Dense urban cluster", 2, "urban_cluster"),
    22: ("semi_dense_urban_cluster", "Semi-dense urban cluster", 2, "urban_cluster"),
    21: ("suburban_or_peri_urban", "Suburban or peri-urban", 2, "urban_cluster"),
    13: ("rural_cluster", "Rural cluster", 1, "rural_grid_cell"),
    12: ("low_density_rural", "Low-density rural", 1, "rural_grid_cell"),
    11: ("very_low_density_rural", "Very-low-density rural", 1, "rural_grid_cell"),
    10: ("water", "Water", 1, "rural_grid_cell"),
}
URBAN_CODES = frozenset((21, 22, 23, 30))
NODATA_CODE = 255
_MAGIC = b"TFDG"
_HEADER = struct.Struct("<4sBBBBHBBIIII32s")
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _default_data() -> Path:
    here = Path(__file__).resolve().parent
    name = "degurba_R2025A_E2025_L12.tfdg"
    for candidate in (here / "data" / name, here.parent / "data" / name):
        if candidate.is_file():
            return candidate
    return candidate


def _compact(index: int, level: int) -> str:
    face = index >> (2 * level)
    path = index & ((1 << (2 * level)) - 1)
    bits = 2 * level
    padding = (-bits) % 5
    path <<= padding
    chars = [_B32[(path >> shift) & 31]
             for shift in range(bits + padding - 5, -1, -5)]
    return "T" + _B32[face] + _B32[level] + "".join(chars)


@dataclass(frozen=True)
class SettlementResult:
    code: int | None
    settlement_class: str | None
    label: str | None
    level1_code: int | None
    level1_class: str | None
    surface: str
    class_share: float | None
    mixed: bool
    nodata_mixed: bool
    status: str
    cell: str
    level: int
    source: str
    source_release: str
    year: int
    estimate_kind: str
    source_resolution_km: float


class SettlementCheck:
    """Read-only, dependency-free scalar lookup against a bundled TFDG file."""

    def __init__(self, data_path: str | Path | None = None):
        path = Path(data_path) if data_path is not None else _default_data()
        raw = path.read_bytes()
        if len(raw) < _HEADER.size:
            raise ValueError(f"{path}: truncated TFDG header")
        (magic, version, level, flags, reserved, year, release_id,
         resolution_tenths, n_runs, n_mixed, n_cells, raw_length,
         raster_sha) = _HEADER.unpack_from(raw)
        if magic != _MAGIC:
            raise ValueError(f"{path}: not a TFDG file")
        if version != 1:
            raise ValueError(f"{path}: unsupported TFDG version {version}")
        if reserved or release_id != 1 or year != 2025 or resolution_tenths != 10:
            raise ValueError(f"{path}: unsupported TFDG metadata")
        if not 1 <= level <= 13 or n_cells != 20 * 4 ** level:
            raise ValueError(f"{path}: inconsistent TFDG level/cell count")
        try:
            body = zlib.decompress(raw[_HEADER.size:])
        except zlib.error as error:
            raise ValueError(f"{path}: invalid TFDG payload") from error
        if len(body) != raw_length:
            raise ValueError(f"{path}: truncated TFDG payload")

        position = 0

        def read_varint():
            nonlocal position
            value = shift = 0
            while True:
                if position >= len(body) or shift > 35:
                    raise ValueError(f"{path}: truncated TFDG run table")
                byte = body[position]
                position += 1
                value |= (byte & 127) << shift
                if not byte & 128:
                    return value
                shift += 7

        ends, mixed_before = array("I"), array("I")
        codes, mixed_runs = bytearray(n_runs), bytearray(n_runs)
        cursor = mixed_seen = 0
        for run in range(n_runs):
            start = cursor + read_varint()
            length = read_varint()
            if not length or position + 2 > len(body):
                raise ValueError(f"{path}: invalid TFDG run")
            code, mixed = body[position], body[position + 1]
            position += 2
            if code not in CLASSES and code != NODATA_CODE:
                raise ValueError(f"{path}: unexpected class code {code}")
            if mixed not in (0, 1) or start + length > n_cells:
                raise ValueError(f"{path}: invalid TFDG run metadata")
            if flags & 1 and start != cursor:
                raise ValueError(f"{path}: incomplete all-runs TFDG dataset")
            ends.append(start + length)
            codes[run] = code
            mixed_runs[run] = mixed
            mixed_before.append(mixed_seen)
            if mixed:
                mixed_seen += length
            cursor = start + length
        if mixed_seen != n_mixed or position + 2 * n_mixed != len(body):
            raise ValueError(f"{path}: inconsistent TFDG mixed-cell block")
        if flags & 1 and (not ends or ends[-1] != n_cells):
            raise ValueError(f"{path}: incomplete all-runs TFDG dataset")

        self.path = path
        self.level = level
        self.year = year
        self.source = "GHS-WUP-DEGURBA"
        self.source_release = "R2025A"
        self.estimate_kind = "projected"
        self.source_resolution_km = resolution_tenths / 10
        self.raster_sha256 = raster_sha.hex()
        self._ends = ends
        self._codes, self._mixed_runs = bytes(codes), bytes(mixed_runs)
        self._mixed_before = mixed_before
        self._mixed_data = body[position:]
        self._n_cells, self._n_mixed = n_cells, n_mixed

    def _lookup(self, lon: float, lat: float):
        if not -180.0 <= lon <= 180.0:
            raise ValueError("longitude must be in [-180, 180]")
        if not -90.0 <= lat <= 90.0:
            raise ValueError("latitude must be in [-90, 90]")
        index = _locate_index(lon, lat, self.level)
        run = bisect_right(self._ends, index)
        if run >= len(self._ends):
            return index, NODATA_CODE, False, None, 0
        code = self._codes[run]
        if not self._mixed_runs[run]:
            return index, code, False, 1.0, 0
        start = 0 if run == 0 else self._ends[run - 1]
        offset = self._mixed_before[run] + index - start
        share = self._mixed_data[2 * offset] / 255.0
        mix_flags = self._mixed_data[2 * offset + 1]
        return index, code, True, share, mix_flags

    def check(self, lon: float, lat: float) -> SettlementResult:
        return self._to_result(*self._lookup(lon, lat))

    def _to_result(self, index, code, mixed, share, mix_flags):
        if code == NODATA_CODE:
            fields = (None, None, None, None, None)
            status = "no_data"
            surface = "unknown"
            share = None
        else:
            name, label, level1_code, level1_class = CLASSES[code]
            fields = (code, name, label, level1_code, level1_class)
            status = "classified"
            if mix_flags & 1:
                surface = "mixed"
            elif code == 10:
                surface = "water"
            else:
                surface = "land"
        return SettlementResult(
            *fields, surface, share, mixed, bool(mix_flags & 2), status,
            _compact(index, self.level),
            self.level, self.source, self.source_release, self.year,
            self.estimate_kind, self.source_resolution_km,
        )

    def settlement(self, lon: float, lat: float) -> str | None:
        code = self._lookup(lon, lat)[1]
        return None if code == NODATA_CODE else CLASSES[code][0]

    def class_code(self, lon: float, lat: float) -> int | None:
        code = self._lookup(lon, lat)[1]
        return None if code == NODATA_CODE else code

    def is_urban(self, lon: float, lat: float) -> bool | None:
        code = self.class_code(lon, lat)
        return None if code is None else code in URBAN_CODES

    def check_batch(self, lons: Iterable[float], lats: Iterable[float]):
        lons, lats = list(lons), list(lats)
        if len(lons) != len(lats):
            raise ValueError("lons and lats must have the same length")
        try:
            import numpy as np
            from trifold.api import locate_address_batch
        except ImportError:
            return [self.check(float(lon), float(lat))
                    for lon, lat in zip(lons, lats)]
        lon_values = np.asarray(lons, dtype=float)
        lat_values = np.asarray(lats, dtype=float)
        if ((lon_values < -180).any() or (lon_values > 180).any()
                or (lat_values < -90).any() or (lat_values > 90).any()
                or not np.isfinite(lon_values).all()
                or not np.isfinite(lat_values).all()):
            raise ValueError("coordinates outside valid lon/lat ranges")
        addresses = locate_address_batch(lon_values, lat_values, self.level)
        indexes = (addresses >> np.uint64(59 - 2 * self.level)).astype(np.int64)
        ends = np.frombuffer(self._ends, dtype=np.uint32).astype(np.int64)
        runs = np.searchsorted(ends, indexes, side="right")
        codes = np.frombuffer(self._codes, dtype=np.uint8)[runs]
        mixed_runs = np.frombuffer(self._mixed_runs, dtype=np.uint8)[runs].astype(bool)
        starts = np.where(runs == 0, 0, ends[np.maximum(runs - 1, 0)])
        before = np.frombuffer(self._mixed_before, dtype=np.uint32).astype(np.int64)
        offsets = before[runs] + indexes - starts
        mixed_data = np.frombuffer(self._mixed_data, dtype=np.uint8)
        answers = []
        for index, code, mixed, offset in zip(indexes, codes, mixed_runs, offsets):
            share = mixed_data[2 * offset] / 255.0 if mixed else 1.0
            flags = int(mixed_data[2 * offset + 1]) if mixed else 0
            answers.append(self._to_result(int(index), int(code), bool(mixed),
                                           float(share), flags))
        return answers

    def settlement_batch(self, lons: Iterable[float], lats: Iterable[float]):
        return [result.settlement_class for result in self.check_batch(lons, lats)]

    @property
    def stats(self):
        return {"level": self.level, "runs": len(self._ends),
                "mixed_cells": self._n_mixed, "cells": self._n_cells,
                "source_release": self.source_release, "year": self.year}


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline DEGURBA point lookup")
    parser.add_argument("lon", type=float)
    parser.add_argument("lat", type=float)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = SettlementCheck(args.data).check(args.lon, args.lat)
    if args.json:
        print(json.dumps(asdict(result), separators=(",", ":")))
    elif result.status == "no_data":
        print(f"no_data cell={result.cell} source={result.source}/{result.source_release} "
              f"year={result.year}")
    else:
        print(f"{result.settlement_class} code={result.code} "
              f"share={result.class_share:.3f} mixed={str(result.mixed).lower()} "
              f"cell={result.cell} source={result.source}/{result.source_release} "
              f"year={result.year}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
