#!/usr/bin/env python
"""Build the TFDG settlementcheck dataset from the official GHSL raster.

The builder transfers the published categorical result to T3; it never
recomputes DEGURBA. Homogeneous T3 ancestors become canonical intervals.
At the selected base level, source pixels are intersected in the native
equal-area CRS to store a dominant class, its area share, and mix flags.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import struct
import sys
import time
import zlib
from array import array
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from trifold.core import icosahedron, subdivide  # noqa: E402

MAGIC = b"TFDG"
VERSION = 1
VALID_CODES = (10, 11, 12, 13, 21, 22, 23, 30)
NODATA_CODE = 255
CODE_TO_SLOT = {code: slot for slot, code in enumerate(VALID_CODES)}
CODE_TO_SLOT[NODATA_CODE] = 8
HEADER = struct.Struct("<4sBBBBHBBIIII32s")
SOURCE_CRS = "ESRI:54009"
SOURCE_TRANSFORM = (1000.0, 0.0, -18041000.0, 0.0, -1000.0, 9000000.0)
SOURCE_WIDTH = 36082
SOURCE_HEIGHT = 18000
SOURCE_NODATA = -200
# ESRI:54009 in the distributed raster applies Mollweide to WGS84's
# semi-major axis (matching PROJ/GDAL for this WKT definition).
MOLLWEIDE_RADIUS_M = 6378137.0


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def midpoint(a, b):
    value = a + b
    return value / np.linalg.norm(value)


def edge_points(a, b, halvings):
    if halvings == 0:
        return [a]
    middle = midpoint(a, b)
    return edge_points(a, middle, halvings - 1) + edge_points(
        middle, b, halvings - 1)


class RasterClassifier:
    def __init__(self, path: Path):
        self.path = path
        self.dataset = rasterio.open(path)
        ds = self.dataset
        actual_transform = tuple(ds.transform)[:6]
        if ds.width != SOURCE_WIDTH or ds.height != SOURCE_HEIGHT:
            raise ValueError(f"unexpected raster shape {ds.width}x{ds.height}")
        if ds.crs.to_string() != SOURCE_CRS:
            raise ValueError(f"unexpected CRS {ds.crs}")
        if not np.allclose(actual_transform, SOURCE_TRANSFORM):
            raise ValueError(f"unexpected transform {actual_transform}")
        if ds.nodata != SOURCE_NODATA:
            raise ValueError(f"unexpected nodata {ds.nodata}")
        cache = path.with_suffix(path.suffix + f".{sha256(path)[:12]}.normalized-u8")
        expected_size = ds.width * ds.height
        if not cache.exists() or cache.stat().st_size != expected_size:
            print(f"creating normalized raster cache {cache}", flush=True)
            values = np.memmap(cache, mode="w+", dtype=np.uint8,
                               shape=(ds.height, ds.width))
            for _, window in ds.block_windows(1):
                rows = slice(int(window.row_off), int(window.row_off + window.height))
                cols = slice(int(window.col_off), int(window.col_off + window.width))
                values[rows, cols] = self._normalise(ds.read(1, window=window))
            values.flush()
            del values
        self.values = np.memmap(cache, mode="r", dtype=np.uint8,
                                shape=(ds.height, ds.width))
        self.block_h, self.block_w = ds.block_shapes[0]
        self.block_rows = math.ceil(ds.height / self.block_h)
        self.block_cols = math.ceil(ds.width / self.block_w)
        self.block_masks = np.zeros((self.block_rows, self.block_cols), dtype=np.uint16)
        self._build_block_masks()
        self.integrals = []
        for slot in range(9):
            present = ((self.block_masks >> slot) & 1).astype(np.uint16)
            integral = np.zeros((self.block_rows + 1, self.block_cols + 1),
                                dtype=np.uint32)
            integral[1:, 1:] = present.cumsum(0).cumsum(1)
            self.integrals.append(integral)

    def _normalise(self, data):
        out = np.full(data.shape, NODATA_CODE, dtype=np.uint8)
        for code in VALID_CODES:
            out[data == code] = code
        unexpected = np.unique(data[(data != SOURCE_NODATA)
                                    & ~np.isin(data, VALID_CODES)])
        if unexpected.size:
            raise ValueError(f"unexpected source codes: {unexpected.tolist()}")
        return out

    def _mask(self, data):
        result = 0
        values = set(data.ravel().tolist()) if data.size < 256 else np.unique(data)
        for value in values:
            result |= 1 << CODE_TO_SLOT[int(value)]
        return result

    def _build_block_masks(self):
        for _, window in self.dataset.block_windows(1):
            row = int(window.row_off) // self.block_h
            col = int(window.col_off) // self.block_w
            rows = slice(int(window.row_off), int(window.row_off + window.height))
            cols = slice(int(window.col_off), int(window.col_off + window.width))
            self.block_masks[row, col] = self._mask(self.values[rows, cols])

    @staticmethod
    def _project_lonlat(lon, lat):
        lon = math.radians(lon)
        lat = math.radians(lat)
        if abs(abs(lat) - math.pi / 2) < 1e-12:
            theta = math.copysign(math.pi / 2, lat)
        else:
            theta = lat
            for _ in range(7):
                value = 2 * theta
                theta -= ((value + math.sin(value) - math.pi * math.sin(lat))
                          / (2 + 2 * math.cos(value)))
        return (2 * math.sqrt(2) * MOLLWEIDE_RADIUS_M / math.pi
                * lon * math.cos(theta),
                math.sqrt(2) * MOLLWEIDE_RADIUS_M * math.sin(theta))

    def _integral_any(self, slot, row0, col0, row1, col1):
        if row0 >= row1 or col0 >= col1:
            return False
        values = self.integrals[slot]
        count = (int(values[row1, col1]) - int(values[row0, col1])
                 - int(values[row1, col0]) + int(values[row0, col0]))
        return count > 0

    def projected_parts(self, tri, level):
        """Project a cell, splitting antimeridian cells into two pieces."""
        halvings = max(0, 7 - level)
        xyz = []
        if halvings:
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                xyz.extend(edge_points(a, b, halvings))
        else:
            xyz = list(tri)
        lonlat = []
        previous = None
        for x, y, z in xyz:
            lon = math.degrees(math.atan2(y, x))
            lat = math.degrees(math.asin(max(-1.0, min(1.0, z))))
            if previous is not None:
                while lon - previous > 180:
                    lon -= 360
                while lon - previous < -180:
                    lon += 360
            lonlat.append((lon, lat))
            previous = lon
        mean_lon = sum(point[0] for point in lonlat) / len(lonlat)
        while mean_lon > 180:
            lonlat = [(lon - 360, lat) for lon, lat in lonlat]
            mean_lon -= 360
        while mean_lon <= -180:
            lonlat = [(lon + 360, lat) for lon, lat in lonlat]
            mean_lon += 360
        parts = [lonlat]
        if max(point[0] for point in lonlat) > 180:
            parts = [
                self._clip_axis(lonlat, 0, 180, False),
                [(lon - 360, lat) for lon, lat in
                 self._clip_axis(lonlat, 0, 180, True)],
            ]
        elif min(point[0] for point in lonlat) < -180:
            parts = [
                self._clip_axis(lonlat, 0, -180, True),
                [(lon + 360, lat) for lon, lat in
                 self._clip_axis(lonlat, 0, -180, False)],
            ]
        return [tuple(self._project_lonlat(lon, lat) for lon, lat in part)
                for part in parts if len(part) >= 3]

    def bbox_mask(self, bounds):
        left, bottom, right, top = bounds
        transform = self.dataset.transform
        col0 = math.floor((left - transform.c) / transform.a)
        col1 = math.ceil((right - transform.c) / transform.a)
        row0 = math.floor((top - transform.f) / transform.e)
        row1 = math.ceil((bottom - transform.f) / transform.e)
        mask = 0
        if col0 < 0 or row0 < 0 or col1 > self.dataset.width or row1 > self.dataset.height:
            mask |= 1 << CODE_TO_SLOT[NODATA_CODE]
        col0, col1 = max(0, col0), min(self.dataset.width, col1)
        row0, row1 = max(0, row0), min(self.dataset.height, row1)
        if col0 >= col1 or row0 >= row1:
            return mask or (1 << CODE_TO_SLOT[NODATA_CODE])

        br0, br1 = row0 // self.block_h, (row1 - 1) // self.block_h
        bc0, bc1 = col0 // self.block_w, (col1 - 1) // self.block_w
        full_r0 = math.ceil(row0 / self.block_h)
        full_r1 = row1 // self.block_h
        full_c0 = math.ceil(col0 / self.block_w)
        full_c1 = col1 // self.block_w
        for slot in range(9):
            if self._integral_any(slot, full_r0, full_c0, full_r1, full_c1):
                mask |= 1 << slot

        for block_row in range(br0, br1 + 1):
            for block_col in range(bc0, bc1 + 1):
                if (full_r0 <= block_row < full_r1
                        and full_c0 <= block_col < full_c1):
                    continue
                r0 = max(row0, block_row * self.block_h)
                r1 = min(row1, (block_row + 1) * self.block_h)
                c0 = max(col0, block_col * self.block_w)
                c1 = min(col1, (block_col + 1) * self.block_w)
                data = self.values[r0:r1, c0:c1]
                mask |= self._mask(data)
        return mask

    @staticmethod
    def _clip_axis(points, axis, boundary, keep_greater):
        output = []
        if not points:
            return output
        previous = points[-1]
        previous_inside = ((previous[axis] >= boundary) if keep_greater
                           else (previous[axis] <= boundary))
        for current in points:
            current_inside = ((current[axis] >= boundary) if keep_greater
                              else (current[axis] <= boundary))
            if current_inside != previous_inside:
                delta = current[axis] - previous[axis]
                fraction = 0.0 if delta == 0 else (boundary - previous[axis]) / delta
                point = [previous[0] + fraction * (current[0] - previous[0]),
                         previous[1] + fraction * (current[1] - previous[1])]
                point[axis] = boundary
                output.append(tuple(point))
            if current_inside:
                output.append(current)
            previous, previous_inside = current, current_inside
        return output

    @staticmethod
    def _area(points):
        return abs(sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(points, points[1:] + points[:1]))) / 2

    @classmethod
    def _rectangle_intersection_area(cls, points, left, bottom, right, top):
        clipped = cls._clip_axis(points, 0, left, True)
        clipped = cls._clip_axis(clipped, 0, right, False)
        clipped = cls._clip_axis(clipped, 1, bottom, True)
        clipped = cls._clip_axis(clipped, 1, top, False)
        return cls._area(clipped) if len(clipped) >= 3 else 0.0

    def exact(self, parts):
        transform = self.dataset.transform
        areas = defaultdict(float)
        polygon_area = 0.0
        for points in parts:
            points = list(points)
            part_area = self._area(points)
            polygon_area += part_area
            before = sum(areas.values())
            left = min(point[0] for point in points)
            right = max(point[0] for point in points)
            bottom = min(point[1] for point in points)
            top = max(point[1] for point in points)
            col0 = max(0, math.floor((left - transform.c) / transform.a))
            col1 = min(self.dataset.width, math.ceil((right - transform.c) / transform.a))
            row0 = max(0, math.floor((top - transform.f) / transform.e))
            row1 = min(self.dataset.height, math.ceil((bottom - transform.f) / transform.e))
            if col0 < col1 and row0 < row1:
                values = self.values[row0:row1, col0:col1]
                for row in range(row0, row1):
                    pixel_top = transform.f + row * transform.e
                    pixel_bottom = pixel_top + transform.e
                    for col in range(col0, col1):
                        pixel_left = transform.c + col * transform.a
                        area = self._rectangle_intersection_area(
                            points, pixel_left, pixel_bottom,
                            pixel_left + transform.a, pixel_top)
                        if area:
                            areas[int(values[row - row0, col - col0])] += area
            outside = max(0.0, part_area - (sum(areas.values()) - before))
            if outside > part_area * 1e-10:
                areas[NODATA_CODE] += outside
        if not areas:
            areas[NODATA_CODE] = polygon_area
        # Stable tie break: higher source code wins, nodata last.
        dominant = max(areas, key=lambda code: (areas[code], code != NODATA_CODE, code))
        share = areas[dominant] / polygon_area if polygon_area else 1.0
        kinds = {code for code, area in areas.items() if area > polygon_area * 1e-10}
        mixed = len(kinds) > 1
        water_mix = 10 in kinds and any(code not in (10, NODATA_CODE) for code in kinds)
        nodata_mix = NODATA_CODE in kinds and len(kinds) > 1
        return dominant, share, mixed, water_mix, nodata_mix

    def sample(self, x, y):
        """Diagnostic-only nearest source pixel at projected coordinates."""
        transform = self.dataset.transform
        col = math.floor((x - transform.c) / transform.a)
        row = math.floor((y - transform.f) / transform.e)
        if not (0 <= col < self.dataset.width and 0 <= row < self.dataset.height):
            return NODATA_CODE
        return int(self.values[row, col])


class RunWriter:
    def __init__(self, level):
        self.level = level
        self.starts = array("I")
        self.lengths = array("I")
        self.codes = bytearray()
        self.mixed_runs = bytearray()
        self.mixed = bytearray()

    def add(self, start, length, code, mixed=False, share=1.0,
            water_mix=False, nodata_mix=False):
        if (self.starts and self.starts[-1] + self.lengths[-1] == start
                and self.codes[-1] == code and self.mixed_runs[-1] == mixed):
            self.lengths[-1] += length
        else:
            self.starts.append(start)
            self.lengths.append(length)
            self.codes.append(code)
            self.mixed_runs.append(int(mixed))
        if mixed:
            quantized = min(255, max(0, round(share * 255)))
            flags = int(water_mix) | (int(nodata_mix) << 1)
            self.mixed.extend((quantized, flags))

    @property
    def n_mixed(self):
        return len(self.mixed) // 2

    @property
    def n_runs(self):
        return len(self.starts)

    def extend(self, other):
        self.starts.extend(other.starts)
        self.lengths.extend(other.lengths)
        self.codes.extend(other.codes)
        self.mixed_runs.extend(other.mixed_runs)
        self.mixed.extend(other.mixed)

    def records(self):
        return zip(self.starts, self.lengths, self.codes, self.mixed_runs)


def build_face(classifier, face, level, diagnostic_centroid=False,
               progress=1_000_000):
    writer = RunWriter(level)
    verts, faces = icosahedron()
    visited = 0
    started = time.perf_counter()

    def visit(tri, current_level, start):
        nonlocal visited
        visited += 1
        if progress and visited % progress == 0:
            elapsed = time.perf_counter() - started
            print(f"  {visited:,} nodes; {writer.n_runs:,} runs; "
                  f"{writer.n_mixed:,} mixed; {elapsed:.1f}s", flush=True)
        parts = classifier.projected_parts(tri, current_level)
        mask = 0
        for points in parts:
            xs, ys = zip(*points)
            mask |= classifier.bbox_mask(
                (min(xs), min(ys), max(xs), max(ys)))
        if mask and not (mask & (mask - 1)):
            slot = mask.bit_length() - 1
            code = (*VALID_CODES, NODATA_CODE)[slot]
            writer.add(start, 4 ** (level - current_level), code)
            return
        if current_level == level:
            if diagnostic_centroid:
                points = parts[0]
                xs, ys = zip(*points)
                code = classifier.sample(sum(xs) / len(xs), sum(ys) / len(ys))
                writer.add(start, 1, code, True, 0.5, mask & 1 != 0,
                           bool(mask & (1 << CODE_TO_SLOT[NODATA_CODE])))
                return
            code, share, mixed, water_mix, nodata_mix = classifier.exact(parts)
            writer.add(start, 1, code, mixed, share, water_mix, nodata_mix)
            return
        span = 4 ** (level - current_level - 1)
        for digit, child in enumerate(subdivide(tri)):
            visit(child, current_level + 1, start + digit * span)

    indexes = faces[face]
    tri = tuple(verts[index] for index in indexes)
    visit(tri, 0, face * 4 ** level)
    elapsed = time.perf_counter() - started
    expected = 4 ** level
    assert sum(writer.lengths) == expected
    return writer, visited, elapsed


_WORKER_CLASSIFIER = None


def _worker_init(source):
    global _WORKER_CLASSIFIER
    _WORKER_CLASSIFIER = RasterClassifier(Path(source))


def _face_task(arguments):
    face, level, diagnostic_centroid = arguments
    writer, visited, elapsed = build_face(
        _WORKER_CLASSIFIER, face, level, diagnostic_centroid, progress=0)
    return face, writer, visited, elapsed


def build(classifier, level, progress=1_000_000, diagnostic_centroid=False,
          jobs=1):
    started = time.perf_counter()
    if jobs == 1:
        results = []
        for face in range(20):
            face_writer, visited, elapsed = build_face(
                classifier, face, level, diagnostic_centroid, progress)
            print(f"  face {face:02d}: {visited:,} nodes, "
                  f"{face_writer.n_mixed:,} mixed, {elapsed:.1f}s", flush=True)
            results.append((face, face_writer, visited, elapsed))
    else:
        tasks = [(face, level, diagnostic_centroid) for face in range(20)]
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=jobs, initializer=_worker_init,
                initargs=(str(classifier.path),)) as pool:
            results = []
            for result in pool.map(_face_task, tasks):
                face, face_writer, visited, elapsed = result
                print(f"  face {face:02d}: {visited:,} nodes, "
                      f"{face_writer.n_mixed:,} mixed, {elapsed:.1f}s", flush=True)
                results.append(result)
    writer = RunWriter(level)
    visited = 0
    for _, face_writer, face_visited, _ in sorted(results):
        writer.extend(face_writer)
        visited += face_visited
    elapsed = time.perf_counter() - started
    expected = 20 * 4 ** level
    assert sum(writer.lengths) == expected
    print(f"classified {expected:,} L{level} cells via {visited:,} nodes in "
          f"{elapsed:.1f}s: {writer.n_runs:,} runs, {writer.n_mixed:,} mixed")
    return writer, visited, elapsed


def write_dataset(path, writer, raster_sha):
    body = bytearray()
    cursor = 0
    for start, length, code, mixed in writer.records():
        body += varint(start - cursor)
        body += varint(length)
        body.append(code)
        body.append(int(mixed))
        cursor = start + length
    body += bytes(writer.mixed)
    compressed = zlib.compress(bytes(body), 9)
    header = HEADER.pack(
        MAGIC, VERSION, writer.level, 1, 0, 2025, 1, 10,
        writer.n_runs, writer.n_mixed, 20 * 4 ** writer.level,
        len(body), bytes.fromhex(raster_sha),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + compressed)
    print(f"wrote {path}: {len(header) + len(compressed):,} bytes "
          f"({len(body):,} raw)")


def main():
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--level", type=int, default=12)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--diagnostic-centroid", action="store_true",
                        help="profile traversal only; output is not publishable")
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.level <= 13:
        parser.error("--level must be in 1..13 (TFDG v1 uses u32 indexes)")
    output = args.out or repo / "settlementcheck" / "data" / (
        f"degurba_R2025A_E2025_L{args.level}.tfdg")
    raster_sha = sha256(args.source)
    print(f"source sha256 {raster_sha}")
    classifier = RasterClassifier(args.source)
    try:
        writer, visited, elapsed = build(
            classifier, args.level, diagnostic_centroid=args.diagnostic_centroid,
            jobs=args.jobs)
    finally:
        classifier.dataset.close()
    write_dataset(output, writer, raster_sha)
    if args.stats:
        stats = {
            "level": args.level, "nodes_visited": visited,
            "runs": writer.n_runs, "mixed_cells": writer.n_mixed,
            "build_seconds": elapsed, "artifact_bytes": output.stat().st_size,
            "raster_sha256": raster_sha,
        }
        args.stats.write_text(json.dumps(stats, indent=2) + "\n")


if __name__ == "__main__":
    main()
