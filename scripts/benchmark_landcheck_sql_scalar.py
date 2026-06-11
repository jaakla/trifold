#!/usr/bin/env python3
"""Benchmark one parameterized SQL land-check query per input point."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path


DUCKDB_QUERY = """
SELECT EXISTS (
  SELECT 1
  FROM land
  WHERE ST_Covers(geom, ST_Point(?, ?))
  LIMIT 1
)
"""

POSTGIS_QUERY = """
SELECT EXISTS (
  SELECT 1
  FROM land
  WHERE ST_Covers(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
  LIMIT 1
)
"""

BIGQUERY_QUERY = """
SELECT EXISTS (
  SELECT 1
  FROM `{table}`
  WHERE ST_COVERS(geom, ST_GEOGPOINT(@lon, @lat))
  LIMIT 1
) AS land
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


def summarize(seconds: list[float], count: int) -> dict[str, object]:
    median = statistics.median(seconds)
    return {
        "runs_seconds": seconds,
        "min_seconds": min(seconds),
        "median_seconds": median,
        "max_seconds": max(seconds),
        "median_queries_per_second": count / median,
        "median_microseconds_per_query": median * 1e6 / count,
    }


def run_duckdb(database: Path, points: list[tuple[float, float]],
               repeats: int) -> dict[str, object]:
    import duckdb

    connection = duckdb.connect(str(database), read_only=True)
    connection.execute("LOAD spatial")

    def run_once() -> int:
        return sum(bool(connection.execute(DUCKDB_QUERY, point).fetchone()[0])
                   for point in points)

    expected = run_once()
    runs = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = run_once()
        runs.append((time.perf_counter_ns() - start) / 1e9)
        if result != expected:
            raise RuntimeError("DuckDB result changed between runs")
    connection.close()
    return {"land_points": expected, **summarize(runs, len(points))}


def run_postgis(dsn: str, points: list[tuple[float, float]],
                repeats: int) -> dict[str, object]:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            def run_once() -> int:
                land = 0
                for point in points:
                    cursor.execute(POSTGIS_QUERY, point, prepare=True)
                    land += bool(cursor.fetchone()[0])
                return land

            expected = run_once()
            runs = []
            for _ in range(repeats):
                start = time.perf_counter_ns()
                result = run_once()
                runs.append((time.perf_counter_ns() - start) / 1e9)
                if result != expected:
                    raise RuntimeError("PostGIS result changed between runs")
    return {"land_points": expected, **summarize(runs, len(points))}


def run_bigquery(project: str, location: str, table: str,
                 points: list[tuple[float, float]],
                 repeats: int) -> dict[str, object]:
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=location)
    query = BIGQUERY_QUERY.format(table=table)

    def run_once() -> tuple[int, dict[str, int]]:
        land = 0
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
            land += bool(next(iter(job.result()))["land"])
            stats["slot_millis"] += int(job.slot_millis or 0)
            stats["bytes_processed"] += int(job.total_bytes_processed or 0)
            stats["bytes_billed"] += int(job.total_bytes_billed or 0)
        return land, stats

    expected, _ = run_once()
    runs = []
    job_stats = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result, stats = run_once()
        runs.append((time.perf_counter_ns() - start) / 1e9)
        job_stats.append(stats)
        if result != expected:
            raise RuntimeError("BigQuery result changed between runs")
    client.close()
    return {
        "land_points": expected,
        "runs_job_stats": job_stats,
        **summarize(runs, len(points)),
    }


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
