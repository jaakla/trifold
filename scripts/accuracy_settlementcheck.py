#!/usr/bin/env python
"""Compare settlementcheck against direct reads of the pinned GHSL raster."""
from __future__ import annotations

import argparse
import collections
import math
import random
import sys
from pathlib import Path

import pyproj
import rasterio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "settlementcheck" / "python"))
from settlementcheck import CLASSES, SettlementCheck  # noqa: E402


def source_code(dataset, transformer, lon, lat):
    x, y = transformer.transform(lon, lat)
    row, col = dataset.index(x, y)
    if not (0 <= row < dataset.height and 0 <= col < dataset.width):
        return None
    value = int(next(dataset.sample([(x, y)]))[0])
    return value if value in CLASSES else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data", type=Path,
                        default=ROOT / "settlementcheck/data/degurba_R2025A_E2025_L12.tfdg")
    parser.add_argument("-n", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=2025)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    checker = SettlementCheck(args.data)
    matrix = collections.Counter()
    with rasterio.open(args.source) as dataset:
        transformer = pyproj.Transformer.from_crs("EPSG:4326", dataset.crs,
                                                  always_xy=True)
        for _ in range(args.n):
            lon = rng.uniform(-180, 180)
            lat = math.degrees(math.asin(rng.uniform(-1, 1)))
            expected = source_code(dataset, transformer, lon, lat)
            actual = checker.class_code(lon, lat)
            matrix[expected, actual] += 1
    correct = sum(count for (expected, actual), count in matrix.items()
                  if expected == actual)
    print(f"sphere-uniform agreement: {correct / args.n:.6%} "
          f"({correct:,}/{args.n:,})")
    for code in (*sorted(CLASSES), None):
        support = sum(count for (expected, _), count in matrix.items()
                      if expected == code)
        predicted = sum(count for (_, actual), count in matrix.items()
                        if actual == code)
        true_positive = matrix[code, code]
        recall = true_positive / support if support else float("nan")
        precision = true_positive / predicted if predicted else float("nan")
        label = CLASSES[code][0] if code is not None else "no_data"
        print(f"{str(code):>4} {label:<28} support={support:>7,} "
              f"precision={precision:8.3%} recall={recall:8.3%}")


if __name__ == "__main__":
    main()
