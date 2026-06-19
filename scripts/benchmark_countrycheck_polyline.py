#!/usr/bin/env python3
"""Benchmark countrycheck polyline queries vs GIS-based approaches.

Generates a set of random global polylines, runs countrycheck polyline
classification (both base and border-refined, both uniform and vertex modes),
and outputs a JSON report. Follows the same format as benchmark_countrycheck.py.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "countrycheck" / "python"))
sys.path.insert(0, str(REPO / "src"))

from countrycheck import CountryCheck  # noqa: E402

TFCS = REPO / "countrycheck" / "data" / "countries_L10.tfcs"
TFCR = REPO / "countrycheck" / "data" / "borders_L10.tfcr"


def timed_runs(fn, repeats: int):
    fn()
    durations = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = fn()
        durations.append((time.perf_counter_ns() - start) / 1e9)
    assert result is not None
    return result, durations


def summary(seconds: list[float], count: int) -> dict:
    median = statistics.median(seconds)
    return {
        "min_seconds": min(seconds),
        "median_seconds": median,
        "max_seconds": max(seconds),
        "median_items_per_second": count / median,
        "median_milliseconds_per_item": median * 1e3 / count,
    }


def generate_polylines(
    n_polylines: int, max_vertices: int = 8, seed: int = 20260613
) -> list[list[tuple[float, float]]]:
    """Generate random global polylines (surface-area-uniform endpoints)."""
    rng = np.random.default_rng(seed)
    polylines = []
    for _ in range(n_polylines):
        n_verts = rng.integers(2, max_vertices + 1)
        lons = rng.uniform(-180.0, 180.0, n_verts)
        lats = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, n_verts)))
        coords = [(float(lons[i]), float(lats[i])) for i in range(n_verts)]
        polylines.append(coords)
    return polylines


def classify_all(
    checker: CountryCheck, polylines: list[list[tuple[float, float]]],
    step_km: float, mode: str
):
    results = []
    for coords in polylines:
        results.append(checker.check_polyline(coords, step_km=step_km, mode=mode))
    return results


def load_timed(*, refine_path: Path | None = None):
    start = time.perf_counter_ns()
    checker = CountryCheck(refine_path=refine_path)
    return checker, (time.perf_counter_ns() - start) / 1e9


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-polylines", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20_260_613)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/private/tmp/trifold-countrycheck-polyline-bench"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "countrycheck_polyline_benchmark.json"

    polylines = generate_polylines(args.n_polylines, seed=20_260_614)

    # compute total km across all polylines for rate stats
    from trifold.api import sample_polyline
    total_km = 0.0
    for coords in polylines:
        _, cum, _ = sample_polyline(coords, mode="vertex")
        total_km += float(cum[-1]) if len(cum) > 0 else 0.0

    # --- base (no refinement) ---
    base, base_load = load_timed()
    base_uniform, base_uniform_runs = timed_runs(
        lambda: classify_all(base, polylines, 3.5, "uniform"), args.repeats)
    base_vertex, base_vertex_runs = timed_runs(
        lambda: classify_all(base, polylines, 3.5, "vertex"), args.repeats)

    # --- refined ---
    refined, refined_load = load_timed(refine_path=TFCR)
    refd_uniform, refd_uniform_runs = timed_runs(
        lambda: classify_all(refined, polylines, 3.5, "uniform"), args.repeats)
    refd_vertex, refd_vertex_runs = timed_runs(
        lambda: classify_all(refined, polylines, 3.5, "vertex"), args.repeats)

    # verify consistency across runs
    n_seg_base = sum(len(r.segments) for r in base_uniform)
    n_seg_refd = sum(len(r.segments) for r in refd_uniform)

    report = {
        "n_polylines": args.n_polylines,
        "total_km": round(total_km, 1),
        "seed": 20_260_614,
        "repeats": args.repeats,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "countrycheck_base": {
            "load_seconds": base_load,
            "dataset_bytes": TFCS.stat().st_size,
            "uniform": {
                "n_segments": n_seg_base,
                "runs_seconds": base_uniform_runs,
                **summary(base_uniform_runs, args.n_polylines),
            },
            "vertex": {
                "runs_seconds": base_vertex_runs,
                **summary(base_vertex_runs, args.n_polylines),
            },
        },
        "countrycheck_refined": {
            "load_seconds": refined_load,
            "dataset_bytes": TFCR.stat().st_size,
            "base_dataset_bytes": TFCS.stat().st_size,
            "uniform": {
                "n_segments": n_seg_refd,
                "runs_seconds": refd_uniform_runs,
                **summary(refd_uniform_runs, args.n_polylines),
            },
            "vertex": {
                "runs_seconds": refd_vertex_runs,
                **summary(refd_vertex_runs, args.n_polylines),
            },
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()