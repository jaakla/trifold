#!/usr/bin/env python
"""Measure settlementcheck load, scalar lookup and batch-convenience rates."""
from __future__ import annotations

import argparse
import random
import resource
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "settlementcheck" / "python"))
from settlementcheck import SettlementCheck  # noqa: E402


def timed(function, repeats=5):
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        values.append(time.perf_counter() - started)
    return statistics.median(values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path,
                        default=ROOT / "settlementcheck/data/degurba_R2025A_E2025_L12.tfdg")
    parser.add_argument("-n", type=int, default=100_000)
    args = parser.parse_args()
    started = time.perf_counter()
    checker = SettlementCheck(args.data)
    load = time.perf_counter() - started
    core_load_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    rng = random.Random(2025)
    lons = [rng.uniform(-180, 180) for _ in range(args.n)]
    lats = [rng.uniform(-90, 90) for _ in range(args.n)]
    scalar = timed(lambda: [checker.class_code(lon, lat)
                            for lon, lat in zip(lons, lats)])
    batch = timed(lambda: checker.settlement_batch(lons, lats))
    print(f"artifact_bytes={args.data.stat().st_size}")
    print(f"runs={checker.stats['runs']} mixed_cells={checker.stats['mixed_cells']}")
    print(f"load_seconds={load:.6f}")
    print(f"core_load_peak_rss_mib={core_load_rss:.2f}")
    print(f"scalar_queries_per_second={args.n / scalar:.0f}")
    print(f"batch_convenience_points_per_second={args.n / batch:.0f}")
    print(f"core_peak_rss_mib={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.2f}")
    started = time.perf_counter()
    checker.check(-0.1276, 51.5072)
    print(f"first_detail_face_seconds={time.perf_counter() - started:.6f}")
    detail = timed(lambda: [checker.check(-0.1276, 51.5072) for _ in range(1000)])
    print(f"warm_detail_queries_per_second={1000 / detail:.0f}")
    print(f"with_detail_peak_rss_mib={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.2f}")


if __name__ == "__main__":
    main()
