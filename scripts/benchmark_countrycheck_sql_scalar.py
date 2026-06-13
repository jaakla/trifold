#!/usr/bin/env python3
"""Benchmark one parameterized SQL country-lookup query per input point.

Mirrors scripts/benchmark_landcheck_sql_scalar.py, but the workload is "which
country (gid_0) covers this point?" against the same GADM-derived country
polygons (extended with coastal waters) that countrycheck is built from.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from pathlib import Path

DUCKDB_QUERY = """
SELECT gid_0
FROM countries
WHERE ST_Covers(geom, ST_Point(?, ?))
ORDER BY land_area_km2 DESC
LIMIT 1
"""

POSTGIS_QUERY = """
SELECT gid_0
FROM countries
WHERE ST_Covers(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
ORDER BY land_area_km2 DESC
LIMIT 1
"""

BIGQUERY_QUERY = """
SELECT gid_0
FROM `{table}`
WHERE ST_COVERS(geom, ST_GEOGPOINT(@lon, @lat))
ORDER BY land_area_km2 DESC
LIMIT 1
"""


def read_points(path: Path, count: int) -> list[tuple[float, float]]:
    points = []
    with path.open(newline="", encoding="ascii") as handle:
        for row in csv.DictReader(handle):
            points.append((float(row["lon"]), float(row["lat"])))
            if len(points) == count:
                break
    if len(points) != count:
        raise ValueError(f"requested {count} points, found {len(points)}")
    return points


def signature(codes) -> str:
    """Stable checksum of the per-point answers, for run-to-run equality."""
    joined = "\n".join("" if c is None else str(c) for c in codes)
    return hashlib.sha256(joined.encode()).hexdigest()


def summarize(seconds, count: int) -> dict:
    median = statistics.median(seconds)
    return {
        "runs_seconds": seconds,
        "min_seconds": min(seconds),
        "median_seconds": median,
        "max_seconds": max(seconds),
        "median_queries_per_second": count / median,
        "median_microseconds_per_query": median * 1e6 / count,
    }


def run_duckdb(database: Path, points, repeats: int) -> dict:
    import duckdb

    connection = duckdb.connect(str(database), read_only=True)
    connection.execute("LOAD spatial")

    def run_once():
        out = []
        for lon, lat in points:
            row = connection.execute(DUCKDB_QUERY, (lon, lat)).fetchone()
            out.append(row[0] if row else None)
        return out

    expected = run_once()
    sig = signature(expected)
    runs = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = run_once()
        runs.append((time.perf_counter_ns() - start) / 1e9)
        if signature(result) != sig:
            raise RuntimeError("DuckDB result changed between runs")
    connection.close()
    return {"matched": sum(c is not None for c in expected),
            "signature": sig, **summarize(runs, len(points))}


def run_postgis(dsn: str, points, repeats: int) -> dict:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            def run_once():
                out = []
                for point in points:
                    cursor.execute(POSTGIS_QUERY, point, prepare=True)
                    row = cursor.fetchone()
                    out.append(row[0] if row else None)
                return out

            expected = run_once()
            sig = signature(expected)
            runs = []
            for _ in range(repeats):
                start = time.perf_counter_ns()
                result = run_once()
                runs.append((time.perf_counter_ns() - start) / 1e9)
                if signature(result) != sig:
                    raise RuntimeError("PostGIS result changed between runs")
    return {"matched": sum(c is not None for c in expected),
            "signature": sig, **summarize(runs, len(points))}


def run_bigquery(project: str, location: str, table: str,
                 points, repeats: int) -> dict:
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=location)
    query = BIGQUERY_QUERY.format(table=table)

    def run_once():
        out = []
        stats = {"slot_millis": 0, "bytes_processed": 0, "bytes_billed": 0}
        for lon, lat in points:
            config = bigquery.QueryJobConfig(
                use_query_cache=False,
                query_parameters=[
                    bigquery.ScalarQueryParameter("lon", "FLOAT64", lon),
                    bigquery.ScalarQueryParameter("lat", "FLOAT64", lat),
                ],
            )
            job = client.query(query, job_config=config, location=location)
            rows = list(job.result())
            out.append(rows[0]["gid_0"] if rows else None)
            stats["slot_millis"] += int(job.slot_millis or 0)
            stats["bytes_processed"] += int(job.total_bytes_processed or 0)
            stats["bytes_billed"] += int(job.total_bytes_billed or 0)
        return out, stats

    expected, _ = run_once()
    sig = signature(expected)
    runs = []
    job_stats = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result, stats = run_once()
        runs.append((time.perf_counter_ns() - start) / 1e9)
        job_stats.append(stats)
        if signature(result) != sig:
            raise RuntimeError("BigQuery result changed between runs")
    client.close()
    return {"matched": sum(c is not None for c in expected),
            "signature": sig, "runs_job_stats": job_stats,
            **summarize(runs, len(points))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=("duckdb", "postgis", "bigquery"))
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--project")
    parser.add_argument("--location", default="EU")
    parser.add_argument("--table")
    parser.add_argument(
        "--dsn",
        default="host=127.0.0.1 port=55432 dbname=postgres "
                "user=postgres password=benchmark",
    )
    args = parser.parse_args()
    if args.count <= 0 or args.repeats <= 0:
        parser.error("--count and --repeats must be positive")

    points = read_points(args.points, args.count)
    if args.engine == "duckdb":
        if args.database is None:
            parser.error("DuckDB requires --database")
        result = run_duckdb(args.database, points, args.repeats)
    elif args.engine == "postgis":
        result = run_postgis(args.dsn, points, args.repeats)
    else:
        if not args.project or not args.table:
            parser.error("BigQuery requires --project and --table")
        result = run_bigquery(args.project, args.location, args.table,
                              points, args.repeats)
    print(json.dumps({
        "engine": args.engine,
        "point_count": args.count,
        "repeats": args.repeats,
        **result,
    }, indent=2))


if __name__ == "__main__":
    main()
