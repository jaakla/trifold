"""Offline DEGURBA classes with optional, lazily loaded boundary details."""
from __future__ import annotations
import argparse
import json
import struct
import zlib
from array import array
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
try:
    from ._fastloc import locate_index as _locate_index
except ImportError:
    from _fastloc import locate_index as _locate_index

__all__ = ["SettlementCheck", "SettlementResult", "DetailsNotLoadedError", "CLASSES"]
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
_SLOTS = (10, 11, 12, 13, 21, 22, 23, 30, 255)
NODATA_CODE = 255
URBAN_CODES = frozenset((21, 22, 23, 30))
_HEADER = struct.Struct("<4sBBBBHBBIIII32s")
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_MAX_RAW = 256 * 1024 * 1024


class DetailsNotLoadedError(RuntimeError):
    """Boundary shard unavailable; class lookup still works."""


def _default_data():
    here = Path(__file__).resolve().parent
    for directory in (here / "data", here.parent / "data"):
        path = directory / "degurba_R2025A_E2025_L12.tfdg"
        if path.is_file():
            return path
    return path


def _compact(index, level):
    face, path = divmod(index, 4 ** level)
    bits = 2 * level
    padding = (-bits) % 5
    path <<= padding
    return "T" + _B32[face] + _B32[level] + "".join(
        _B32[(path >> shift) & 31] for shift in range(bits + padding - 5, -1, -5))


def _read_file(raw, magic, flags, sections):
    offset = 92 + 8 * sections
    if len(raw) < offset:
        raise ValueError("truncated TFDG header/directory")
    values = _HEADER.unpack_from(raw)
    m, version, level, f, face, year, release, resolution, runs, mixed, cells, size, sha = values
    if m != magic:
        raise ValueError("not a TFDG/TFDD file")
    if version != 1 or f != flags:
        raise ValueError("unsupported TFDG layout (rebuild obsolete WIP v1 files)")
    if (not 1 <= level <= 13 or cells != 20 * 4 ** level or year != 2025
            or release != 1 or resolution != 10 or face >= 20
            or (magic == b'TFDG' and face != 0) or size > _MAX_RAW
            or runs > cells or mixed > cells):
        raise ValueError("invalid TFDG metadata")
    blocks, total = [], 0
    for section in range(sections):
        length, expected = struct.unpack_from('<II', raw, 92 + 8 * section)
        total += expected
        if total > size or offset + length > len(raw):
            raise ValueError("truncated/invalid TFDG payload section")
        decoder = zlib.decompressobj()
        try:
            block = decoder.decompress(raw[offset:offset + length], expected + 1)
        except zlib.error as error:
            raise ValueError("invalid TFDG payload") from error
        if (len(block) != expected or not decoder.eof or decoder.unused_data
                or decoder.unconsumed_tail):
            raise ValueError("invalid TFDG payload length")
        blocks.append(block)
        offset += length
    if offset != len(raw) or total != size:
        raise ValueError("invalid TFDG section directory")
    return values, raw[60:92].hex(), blocks


def _varints(block):
    value = shift = 0
    for byte in block:
        if shift >= 35:
            raise ValueError("invalid TFDG varint")
        value |= (byte & 127) << shift
        if byte & 128:
            shift += 7
        else:
            if value > 0xffffffff:
                raise ValueError("TFDG varint overflow")
            yield value
            value = shift = 0
    if shift:
        raise ValueError("truncated TFDG varint")


@dataclass(frozen=True)
class SettlementResult:
    code: int | None
    settlement_class: str | None
    label: str | None
    level1_code: int | None
    level1_class: str | None
    surface: str | None
    class_share: float | None
    mixed: bool | None
    nodata_mixed: bool | None
    status: str
    cell: str
    level: int
    source: str
    source_release: str
    year: int
    estimate_kind: str
    source_resolution_km: float
    details_loaded: bool


class SettlementCheck:
    """Load classes initially; check() lazily reads a local face detail file.

    details_loader(face) may supply bytes from an application-managed source.
    No network is contacted by default. At most cache_faces shards are retained.
    """
    def __init__(self, data_path=None, *, details_path=None, details_loader=None, cache_faces=2):
        if not isinstance(cache_faces, int) or not 1 <= cache_faces <= 20:
            raise ValueError("cache_faces must be in 1..20")
        self.path = Path(data_path) if data_path is not None else _default_data()
        header, self.dataset_id, blocks = _read_file(self.path.read_bytes(), b'TFDG', 3, 2)
        _, _, self.level, _, _, self.year, _, resolution, runs, mixed, cells, _, sha = header
        lengths, slots = blocks
        if len(slots) != runs or not runs or len(lengths) < runs:
            raise ValueError("invalid TFDG class table")
        self._ends = array('I')
        cursor = 0
        for length in _varints(lengths):
            cursor += length
            if not length or cursor > cells or len(self._ends) >= runs:
                raise ValueError("invalid/incomplete TFDG coverage")
            self._ends.append(cursor)
        if len(self._ends) != runs or cursor != cells or any(slot > 8 for slot in slots):
            raise ValueError("invalid TFDG coverage/class code")
        self._codes = bytes(_SLOTS[slot] for slot in slots)
        self._n_cells, self._n_mixed = cells, mixed
        self.source, self.source_release = 'GHS-WUP-DEGURBA', 'R2025A'
        self.estimate_kind, self.source_resolution_km = 'projected', resolution / 10
        self.raster_sha256 = sha.hex()
        self._details_path = Path(details_path) if details_path is not None else self.path.with_suffix('.details')
        self._details_loader = details_loader
        self._cache_faces, self._details = cache_faces, OrderedDict()
        self._lock = RLock()

    def _index(self, lon, lat):
        if not -180 <= lon <= 180:
            raise ValueError('longitude must be in [-180, 180]')
        if not -90 <= lat <= 90:
            raise ValueError('latitude must be in [-90, 90]')
        return _locate_index(lon, lat, self.level)

    def _code(self, index):
        return self._codes[bisect_right(self._ends, index)]

    def load_details(self, lon, lat):
        """Load/cache only the face containing this point; failed reads are retryable."""
        return self._load_face(self._index(lon, lat) // 4 ** self.level)

    def _load_face(self, face):
        with self._lock:
            if face in self._details:
                self._details.move_to_end(face)
                return self._details[face]
            try:
                raw = (self._details_loader(face) if self._details_loader is not None else
                       (self._details_path / f'face-{face:02d}.tfdd').read_bytes())
            except FileNotFoundError as error:
                raise DetailsNotLoadedError(
                    'Boundary details are optional. Download the matching .details directory '
                    'and pass details_path=, or use classify()/class_code() without details.') from error
            header, identity, blocks = _read_file(raw, b'TFDD', 1, 4)
            if (identity != self.dataset_id or header[2] != self.level or header[4] != face
                    or header[-1].hex() != self.raster_sha256):
                raise ValueError('TFDD details do not match this core/face')
            runs, count = header[8:10]
            encoded, shares, water, nodata = blocks
            bit_bytes = (count + 7) // 8
            if (len(shares) != count or len(water) != bit_bytes or len(nodata) != bit_bytes
                    or count > 4 ** self.level or runs > count or len(encoded) < runs * 2):
                raise ValueError('invalid TFDD mixed-cell blocks')
            if count % 8 and any(b[-1] & ((1 << (8 - count % 8)) - 1) for b in (water, nodata)):
                raise ValueError('invalid TFDD bit padding')
            starts, ends, before = array('I'), array('I'), array('I')
            values = iter(_varints(encoded))
            cursor = seen = 0
            for gap in values:
                length = next(values, None)
                if length is None or not length or len(starts) >= runs:
                    raise ValueError('invalid TFDD interval')
                start = cursor + gap
                cursor = start + length
                if cursor > 4 ** self.level or seen + length > count:
                    raise ValueError('invalid TFDD interval bounds')
                starts.append(start)
                ends.append(cursor)
                before.append(seen)
                seen += length
            if len(starts) != runs or seen != count:
                raise ValueError('inconsistent TFDD coverage')
            shard = (starts, ends, before, shares, water, nodata)
            self._details[face] = shard
            while len(self._details) > self._cache_faces:
                self._details.popitem(last=False)
            return shard

    def unload_details(self):
        with self._lock:
            self._details.clear()

    def _result(self, index, detail=None):
        code = self._code(index)
        fields = (None,) * 5 if code == NODATA_CODE else (code, *CLASSES[code])
        if detail is None:
            mixed = share = nodata = surface = None
        else:
            mixed, share, water, nodata = detail
            surface = 'mixed' if water else 'water' if code == 10 else 'land'
        if code == NODATA_CODE:
            surface, share = 'unknown', None
        return SettlementResult(
            *fields, surface, share, mixed, nodata,
            'no_data' if code == NODATA_CODE else 'classified', _compact(index, self.level),
            self.level, self.source, self.source_release, self.year, self.estimate_kind,
            self.source_resolution_km, detail is not None)

    def classify(self, lon, lat):
        """Return class/provenance only; boundary fields are explicitly unknown."""
        return self._result(self._index(lon, lat))

    def check(self, lon, lat):
        index = self._index(lon, lat)
        starts, ends, before, shares, water, nodata = self._load_face(index // 4 ** self.level)
        local = index % 4 ** self.level
        run = bisect_right(ends, local)
        if run == len(ends) or local < starts[run]:
            detail = (False, 1.0, False, False)
        else:
            offset = before[run] + local - starts[run]
            bit = 7 - offset % 8
            detail = (True, shares[offset] / 255, bool((water[offset // 8] >> bit) & 1),
                      bool((nodata[offset // 8] >> bit) & 1))
        return self._result(index, detail)

    def class_code(self, lon, lat):
        code = self._code(self._index(lon, lat))
        return None if code == NODATA_CODE else code

    def settlement(self, lon, lat):
        code = self.class_code(lon, lat)
        return None if code is None else CLASSES[code][0]

    def is_urban(self, lon, lat):
        code = self.class_code(lon, lat)
        return None if code is None else code in URBAN_CODES

    def check_batch(self, lons, lats):
        lons, lats = list(lons), list(lats)
        if len(lons) != len(lats):
            raise ValueError('lons and lats must have the same length')
        faces = [self._index(lon, lat) // 4 ** self.level for lon, lat in zip(lons, lats)]
        results = [None] * len(lons)
        for i in sorted(range(len(lons)), key=faces.__getitem__):
            results[i] = self.check(lons[i], lats[i])
        return results

    def settlement_batch(self, lons, lats):
        lons, lats = list(lons), list(lats)
        if len(lons) != len(lats):
            raise ValueError('lons and lats must have the same length')
        try:
            import numpy as np
            from trifold.api import locate_address_batch
        except ImportError:
            return [self.settlement(lon, lat) for lon, lat in zip(lons, lats)]
        lon_values, lat_values = np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)
        if (not np.isfinite(lon_values).all() or not np.isfinite(lat_values).all()
                or (np.abs(lon_values) > 180).any() or (np.abs(lat_values) > 90).any()):
            raise ValueError('coordinates outside valid lon/lat ranges')
        if not lons:
            return []
        addresses = locate_address_batch(lon_values, lat_values, self.level)
        indexes = (addresses >> np.uint64(59 - 2 * self.level)).astype(np.uint32)
        runs = np.searchsorted(np.frombuffer(self._ends, dtype=np.uint32), indexes, side='right')
        codes = np.frombuffer(self._codes, dtype=np.uint8)[runs]
        return [None if code == NODATA_CODE else CLASSES[int(code)][0] for code in codes]

    @property
    def stats(self):
        return dict(level=self.level, runs=len(self._ends), mixed_cells=self._n_mixed,
                    cells=self._n_cells, source_release=self.source_release, year=self.year,
                    details_faces=list(self._details))


def _main(argv=None):
    parser = argparse.ArgumentParser(description='Offline DEGURBA point lookup')
    parser.add_argument('lon', type=float)
    parser.add_argument('lat', type=float)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--details', type=Path, help='optional matching details directory')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    checker = SettlementCheck(args.data, details_path=args.details)
    result = checker.check(args.lon, args.lat) if args.details else checker.classify(args.lon, args.lat)
    print(json.dumps(asdict(result)) if args.json else
          f'{result.settlement_class or "no_data"} code={result.code} cell={result.cell} '
          f'details_loaded={result.details_loaded} source={result.source}/{result.source_release}')
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
