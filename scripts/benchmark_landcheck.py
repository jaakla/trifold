#!/usr/bin/env python3
"""Generate repeatable land-check points and benchmark Trifold landcheck.

Run from the repository root. The generated CSV is also the input used by
the DuckDB, PostGIS, and BigQuery procedures documented in benchmark.md.
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
LANDCHECK_PYTHON = REPO / "landcheck" / "python"
sys.path.insert(0, str(LANDCHECK_PYTHON))

from landcheck import LandCheck  # noqa: E402


def timed_runs(fn, repeats: int) -> tuple[np.ndarray, list[float]]:
    fn()  # warm caches and one-time NumPy paths
    durations = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = fn()
        durations.append((time.perf_counter_ns() - start) / 1e9)
    assert result is not None
    return result, durations


def scalar_land(checker: LandCheck, lons: np.ndarray,
                lats: np.ndarray) -> np.ndarray:
    return np.fromiter(
        (checker.is_land(float(lon), float(lat))
         for lon, lat in zip(lons, lats)),
        dtype=bool,
        count=len(lons),
    )


def summary(seconds: list[float], count: int) -> dict[str, float]:
    median = statistics.median(seconds)
    return {
        "min_seconds": min(seconds),
        "median_seconds": median,
        "max_seconds": max(seconds),
        "median_points_per_second": count / median,
        "median_microseconds_per_point": median * 1e6 / count,
    }


def generate_points(count: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Uniform points by surface area on a sphere, in lon/lat degrees."""
    rng = np.random.default_rng(seed)
    lons = rng.uniform(-180.0, 180.0, count)
    lats = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, count)))
    return lons, lats


def write_points(path: Path, lons: np.ndarray, lats: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("id", "lon", "lat"))
        for point_id, (lon, lat) in enumerate(zip(lons, lats)):
            writer.writerow((point_id, format(float(lon), ".17g"),
                             format(float(lat), ".17g")))


def write_results(path: Path, base: np.ndarray, refined: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("id", "trifold_base", "trifold_refined"))
        for point_id, (base_land, refined_land) in enumerate(zip(base, refined)):
            writer.writerow((point_id, int(base_land), int(refined_land)))


def load_timed(*, refine_path: Path | None = None) -> tuple[LandCheck, float]:
    start = time.perf_counter_ns()
    checker = LandCheck(refine_path=refine_path)
    return checker, (time.perf_counter_ns() - start) / 1e9


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--scalar-count", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=20_260_611)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/private/tmp/trifold-landcheck-benchmark"))
    args = parser.parse_args()
    if args.count <= 0 or args.scalar_count <= 0 or args.repeats <= 0:
        parser.error("--count, --scalar-count, and --repeats must be positive")
    if args.scalar_count > args.count:
        parser.error("--scalar-count cannot exceed --count")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    points_path = args.output_dir / "points.csv"
    classifications_path = args.output_dir / "trifold_results.csv"
    results_path = args.output_dir / "trifold_benchmark.json"

    lons, lats = generate_points(args.count, args.seed)
    write_points(points_path, lons, lats)

    base, base_load = load_timed()
    base_scalar_result, base_scalar_runs = timed_runs(
        lambda: scalar_land(base, lons[:args.scalar_count],
                            lats[:args.scalar_count]),
        args.repeats)
    base_result, base_runs = timed_runs(
        lambda: base.is_land_batch(lons, lats), args.repeats)

    refinement_path = REPO / "landcheck" / "data" / "coastal_osm_L10.tflr"
    refined, refined_load = load_timed(refine_path=refinement_path)
    refined_scalar_result, refined_scalar_runs = timed_runs(
        lambda: scalar_land(refined, lons[:args.scalar_count],
                            lats[:args.scalar_count]),
        args.repeats)
    refined_result, refined_runs = timed_runs(
        lambda: refined.is_land_batch(lons, lats), args.repeats)

    if not np.array_equal(base_scalar_result,
                          base_result[:args.scalar_count]):
        raise RuntimeError("base scalar and batch results disagree")
    if not np.array_equal(refined_scalar_result,
                          refined_result[:args.scalar_count]):
        raise RuntimeError("refined scalar and batch results disagree")

    write_results(classifications_path, base_result, refined_result)
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
        "classifications_csv": str(classifications_path),
        "trifold_base": {
            "load_seconds": base_load,
            "dataset_bytes": (REPO / "landcheck" / "data" /
                              "landsea_L10.tfls").stat().st_size,
            "land_points": int(base_result.sum()),
            "scalar": {
                "land_points": int(base_scalar_result.sum()),
                "runs_seconds": base_scalar_runs,
                **summary(base_scalar_runs, args.scalar_count),
            },
            "batch": {
                "land_points": int(base_result.sum()),
                "runs_seconds": base_runs,
                **summary(base_runs, args.count),
            },
        },
        "trifold_osm_refined": {
            "load_seconds": refined_load,
            "dataset_bytes": refinement_path.stat().st_size,
            "base_dataset_bytes": (REPO / "landcheck" / "data" /
                                   "landsea_L10.tfls").stat().st_size,
            "land_points": int(refined_result.sum()),
            "scalar": {
                "land_points": int(refined_scalar_result.sum()),
                "runs_seconds": refined_scalar_runs,
                **summary(refined_scalar_runs, args.scalar_count),
            },
            "batch": {
                "land_points": int(refined_result.sum()),
                "runs_seconds": refined_runs,
                **summary(refined_runs, args.count),
            },
        },
        "base_refined_disagreements": int(np.count_nonzero(
            base_result != refined_result)),
    }
    results_path.write_text(json.dumps(report, indent=2) + "\n", encoding="ascii")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
