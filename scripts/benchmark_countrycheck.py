#!/usr/bin/env python3
"""Generate repeatable points and benchmark Trifold countrycheck.

Run from the repository root. The generated CSV is also the input used by the
DuckDB, PostGIS, and BigQuery procedures documented in countrycheck_benchmark.md.

The workload is "which country (GADM gid_0) is each point in?" — the same
question the SQL engines answer with a point-in-polygon join over
osm-vector/countries_coastal.geojson.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "countrycheck" / "python"))

from countrycheck import CountryCheck  # noqa: E402

TFCS = REPO / "countrycheck" / "data" / "countries_L10.tfcs"
TFCR = REPO / "countrycheck" / "data" / "borders_L10.tfcr"


def timed_runs(fn, repeats: int):
    fn()  # warm caches and one-time NumPy paths
    durations = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = fn()
        durations.append((time.perf_counter_ns() - start) / 1e9)
    assert result is not None
    return result, durations


def scalar_country(checker: CountryCheck, lons, lats):
    return [checker.country(float(lon), float(lat))
            for lon, lat in zip(lons, lats)]


def summary(seconds, count: int) -> dict:
    median = statistics.median(seconds)
    return {
        "min_seconds": min(seconds),
        "median_seconds": median,
        "max_seconds": max(seconds),
        "median_points_per_second": count / median,
        "median_microseconds_per_point": median * 1e6 / count,
    }


def generate_points(count: int, seed: int):
    rng = np.random.default_rng(seed)
    lons = rng.uniform(-180.0, 180.0, count)
    lats = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, count)))
    return lons, lats


def write_points(path: Path, lons, lats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("id", "lon", "lat"))
        for point_id, (lon, lat) in enumerate(zip(lons, lats)):
            writer.writerow((point_id, format(float(lon), ".17g"),
                             format(float(lat), ".17g")))


def write_results(path: Path, base, refined) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("id", "countrycheck_base", "countrycheck_refined"))
        for point_id, (b, r) in enumerate(zip(base, refined)):
            writer.writerow((point_id, b or "", r or ""))


def load_timed(*, refine_path: Path | None = None):
    start = time.perf_counter_ns()
    checker = CountryCheck(refine_path=refine_path)
    return checker, (time.perf_counter_ns() - start) / 1e9


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--scalar-count", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=20_260_613)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/private/tmp/trifold-countrycheck-benchmark"))
    args = parser.parse_args()
    if min(args.count, args.scalar_count, args.repeats) <= 0:
        parser.error("--count, --scalar-count, and --repeats must be positive")
    if args.scalar_count > args.count:
        parser.error("--scalar-count cannot exceed --count")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    points_path = args.output_dir / "points.csv"
    results_path = args.output_dir / "countrycheck_results.csv"
    report_path = args.output_dir / "countrycheck_benchmark.json"

    lons, lats = generate_points(args.count, args.seed)
    write_points(points_path, lons, lats)

    base, base_load = load_timed()
    base_scalar, base_scalar_runs = timed_runs(
        lambda: scalar_country(base, lons[:args.scalar_count],
                               lats[:args.scalar_count]), args.repeats)
    base_batch, base_batch_runs = timed_runs(
        lambda: base.country_batch(lons, lats), args.repeats)

    refined, refined_load = load_timed(refine_path=TFCR)
    refined_scalar, refined_scalar_runs = timed_runs(
        lambda: scalar_country(refined, lons[:args.scalar_count],
                               lats[:args.scalar_count]), args.repeats)
    refined_batch, refined_batch_runs = timed_runs(
        lambda: refined.country_batch(lons, lats), args.repeats)

    if base_scalar != base_batch[:args.scalar_count]:
        raise RuntimeError("base scalar and batch results disagree")
    if refined_scalar != refined_batch[:args.scalar_count]:
        raise RuntimeError("refined scalar and batch results disagree")

    write_results(results_path, base_batch, refined_batch)

    def named(codes):
        return sum(1 for c in codes if c is not None)

    report = {
        "point_count": args.count,
        "scalar_point_count": args.scalar_count,
        "seed": args.seed,
        "repeats": args.repeats,
        "point_distribution": "uniform by surface area on a sphere",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "points_csv": str(points_path),
        "results_csv": str(results_path),
        "countrycheck_base": {
            "load_seconds": base_load,
            "dataset_bytes": TFCS.stat().st_size,
            "points_with_country": named(base_batch),
            "scalar": {"runs_seconds": base_scalar_runs,
                       **summary(base_scalar_runs, args.scalar_count)},
            "batch": {"runs_seconds": base_batch_runs,
                      **summary(base_batch_runs, args.count)},
        },
        "countrycheck_refined": {
            "load_seconds": refined_load,
            "dataset_bytes": TFCR.stat().st_size,
            "base_dataset_bytes": TFCS.stat().st_size,
            "points_with_country": named(refined_batch),
            "scalar": {"runs_seconds": refined_scalar_runs,
                       **summary(refined_scalar_runs, args.scalar_count)},
            "batch": {"runs_seconds": refined_batch_runs,
                      **summary(refined_batch_runs, args.count)},
        },
        "base_refined_disagreements": int(sum(
            1 for b, r in zip(base_batch, refined_batch) if b != r)),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
