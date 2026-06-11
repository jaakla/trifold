# Land-check benchmark: Trifold vs SQL spatial engines

This benchmark compares Trifold `landcheck` with point-in-polygon queries over
the same OSM simplified land polygons in DuckDB, PostGIS, and BigQuery. Local
results were measured on June 11, 2026. BigQuery batch results were supplied
from an uncached on-demand run; BigQuery singular results remain unmeasured.

## Summary

The workload uses deterministic points uniformly distributed by surface area on
a sphere. Two execution modes are measured. Each result is the median of seven
runs after one unreported warm-up. Setup/load time is measured separately.

- **Singular:** the first 1,000 points, one API or parameterized SQL call at a
  time, with one warm process and connection.
- **Batch:** all 100,000 points in one vectorized API call or set-based SQL query.

### Batch: 100,000 points per call

| engine / mode | setup | median query | min-max | points/s | us/point | land points |
|---|---:|---:|---:|---:|---:|---:|
| Trifold base (Natural Earth) | 0.031 s | **0.218 s** | 0.215-0.230 s | 459,096 | 2.18 | 28,920 |
| Trifold + OSM refinement | 1.205 s | **0.230 s** | 0.229-0.234 s | 435,463 | 2.30 | 29,003 |
| PostGIS 3.6.3 | 3.09 s | **0.911 s** | 0.910-0.963 s | 109,731 | 9.11 | 29,087 |
| DuckDB 1.5.3 Spatial | 2.62 s | **6.847 s** | 6.695-6.987 s | 14,605 | 68.5 | 29,087 |
| BigQuery on-demand, uncached | managed | **0.694 s** | 0.484-0.808 s | 144,092 | 6.94 | not recorded |

For this batch, refined Trifold was 3.02x faster than BigQuery, 3.97x faster
than PostGIS, and 29.8x faster than DuckDB. BigQuery was 1.31x faster than
PostGIS, and PostGIS was 7.51x faster than DuckDB. These ratios describe this
specific global, uniformly random workload and should not be generalized to
concurrent database service workloads.

### Singular: one point per call, 1,000 calls per run

| engine / mode | median run | min-max | queries/s | us/query | land points |
|---|---:|---:|---:|---:|---:|
| Trifold base (Natural Earth) | **0.0116 s** | 0.0115-0.0120 s | 86,391 | 11.6 | 287 |
| Trifold + OSM refinement | **0.0117 s** | 0.0116-0.0119 s | 85,666 | 11.7 | 285 |
| DuckDB 1.5.3 Spatial | **0.466 s** | 0.462-0.469 s | 2,146 | 466 | 283 |
| PostGIS 3.6.3 over localhost/Docker | **1.211 s** | 1.205-1.277 s | 826 | 1,211 | 283 |
| BigQuery | not run | follow procedure below | | | |

Refined Trifold was 39.9x faster than embedded DuckDB and 103.8x faster than
PostGIS through the host-to-Docker TCP connection. DuckDB was 2.60x faster than
that PostGIS client path. This singular result includes language-driver and
query-call overhead. It is not a pure GEOS predicate benchmark. In particular,
PostGIS includes local TCP and Docker VM transport while DuckDB is embedded in
the Python process.

The two local SQL engines, DuckDB and PostGIS, produced identical sorted
land-point IDs:

```text
72a5017d60d69fc675417fe8bd34d4856f5be2eb50577ae5dea5d090431aaaab
```

Trifold and the SQL rows do not have identical source semantics. The base TFLS
layer is derived from Natural Earth. The optional TFLR layer makes OSM
authoritative in refinement-covered coastline cells, but does not replace the
base source everywhere. Against the full OSM SQL result:

| Trifold mode | disagreements / 100,000 | agreement |
|---|---:|---:|
| base | 807 | 99.193% |
| OSM-refined | 486 | 99.514% |

The refinement changed 323 of the 100,000 Trifold answers. Therefore the speed
comparison is useful, but the refined Trifold row is still not a fully identical
implementation of global OSM polygon containment.

For the first 1,000-point singular sample, SQL classified 283 points as land.
Trifold base disagreed on 6 points and OSM-refined Trifold on 2 points.

## Test machine and versions

```text
Machine:       MacBook Pro Mac17,9, Apple M5 Pro
CPU:           15 cores (5 Super, 10 Performance)
Memory:        24 GB
Host OS:       macOS 26.5.1, arm64
Repository:    67552ae1552122f518a93912c635ee1cdc8074a7
Python:        3.12.13
NumPy:         2.4.6
DuckDB:        1.5.3, Spatial extension b68b309, native arm64
PostgreSQL:    17.10, aarch64 Linux under Docker Desktop
PostGIS:       3.6.3, GEOS 3.11.1, PROJ 9.1.1
Docker image:  postgres@sha256:517f51201e18a12503a42945ef0b434d65a5297d72a4180f11905d905fcc5612
Docker limits: no explicit memory or CPU limit
```

Docker Desktop adds a Linux VM layer to PostGIS, while Trifold and DuckDB run
natively on macOS. All use the same laptop CPU and memory, but this is not a
cycle-perfect hardware comparison.

## Dataset manifest

```text
URL:           https://maps.goplex.ee/osm/osm_simplified_land_polygons.geojson
HTTP modified: 2026-06-10 18:47:12 GMT
ETag:          "8a88bce3bf34fe5851a7429925bd2b4a"
Bytes:         62,358,405 (59.47 MiB)
SHA-256:       e7543aeb9a15c51fcba4983fe7f5353db4d11eb98d71a08105a20a6e5735919e
CRS:           OGC CRS84 / WGS84 longitude-latitude
Features:      67,992 MultiPolygons
Bounds:        [-180, -85.0511288, 180, 83.6651099]
Invalid input: FID 28234 and 66048 (self-intersections)
License:       OpenStreetMap data, ODbL; preserve required attribution
```

All SQL loaders run `ST_MakeValid` on the two invalid features before indexing.
This also matches the valid-geography requirement in the BigQuery procedure.

Stored footprint after loading and indexing:

| representation | bytes | MiB |
|---|---:|---:|
| Trifold TFLS base | 182,318 | 0.17 |
| Trifold TFLS + TFLR | 12,868,994 | 12.27 |
| DuckDB database | 49,557,504 | 47.26 |
| PostGIS land + points + indexes | 70,410,240 | 67.15 |

## Benchmark contract

1. Generate 100,000 points with NumPy `PCG64`, seed `20260611`.
2. Longitude is uniform in `[-180, 180)`.
3. Latitude is `degrees(asin(U[-1, 1)))`, giving sphere-area-uniform points.
4. Persist the points to CSV once; every engine reads the same decimal values.
5. Include point-on-boundary as land (`ST_Covers` semantics). Random points make
   exact boundary hits extraordinarily unlikely, but the rule is explicit.
6. Repair only invalid source geometries. Do not simplify or subdivide further.
7. Singular mode issues one call/query per point over the first 1,000 points,
   reusing one process and database connection. No client-side concurrency or
   pipelining is used.
8. Batch mode uses one vectorized API call or one set-based SQL query over all
   100,000 points.
9. Warm each implementation once, then time seven complete runs of each mode.
10. Report median, min, max, result count, versions, setup time, and footprint.
11. Do not include source download, process/container startup, or load/index time
   in warm query time. Printing the single result row is negligible and included.
12. Keep the laptop on power, close heavy applications, and do not run the four
    engines concurrently.

This distribution gives a global throughput measurement. A coastal-heavy or
population-weighted workload will have different relative costs, especially for
Trifold refinement.

## 1. Prepare shared inputs

Run from the repository root:

```bash
mkdir -p /private/tmp/trifold-landcheck-benchmark

curl -L --fail --retry 3 \
  -o /private/tmp/osm_simplified_land_polygons.geojson \
  https://maps.goplex.ee/osm/osm_simplified_land_polygons.geojson

shasum -a 256 /private/tmp/osm_simplified_land_polygons.geojson

.venv/bin/python scripts/benchmark_landcheck.py \
  --count 100000 \
  --scalar-count 1000 \
  --seed 20260611 \
  --repeats 7 \
  --output-dir /private/tmp/trifold-landcheck-benchmark
```

The driver writes:

```text
points.csv                 shared SQL/BigQuery input
trifold_results.csv        per-point base and refined answers
trifold_benchmark.json     raw Trifold run timings and metadata
```

The driver measures both `LandCheck.is_land` in a Python loop and
`LandCheck.is_land_batch`. It verifies that scalar and batch answers agree.

## 2. DuckDB

The tested DuckDB version was Homebrew DuckDB 1.5.3 with an already installed
Spatial extension. Confirm the pin:

```bash
duckdb -c "SELECT version(); LOAD spatial; SELECT extension_version
           FROM duckdb_extensions() WHERE extension_name='spatial';"
```

Load, repair, index, and analyze:

```bash
OUT=/private/tmp/trifold-landcheck-benchmark
DB="$OUT/duckdb.db"
rm -f "$DB"

/usr/bin/time -p duckdb "$DB" -c "
  LOAD spatial;
  SET threads=15;

  CREATE TABLE land AS
  SELECT FID, geom::GEOMETRY AS geom
  FROM ST_Read('/private/tmp/osm_simplified_land_polygons.geojson');

  UPDATE land
  SET geom=ST_MakeValid(geom)
  WHERE NOT ST_IsValid(geom);

  CREATE INDEX land_geom_rtree ON land USING RTREE (geom);
  ANALYZE land;

  CREATE TABLE points AS
  SELECT id::INTEGER AS id,
         lon::DOUBLE AS lon,
         lat::DOUBLE AS lat,
         ST_Point(lon::DOUBLE, lat::DOUBLE) AS geom
  FROM read_csv('$OUT/points.csv', header=true);
  ANALYZE points;
"
```

The benchmark query is:

```sql
SELECT count(DISTINCT p.id) AS land_points
FROM points p
JOIN land l ON ST_DWithin(l.geom, p.geom, 0);
```

For a point and polygon, zero distance means the point is in the polygon or on
its boundary, including correct exclusion by polygon holes. This gives the same
29,087 IDs as `ST_Intersects`/`ST_Covers` on this dataset, while using DuckDB's
optimized native `ST_DWithin` implementation. A direct `ST_Intersects` spatial
join was also tested and took 43.26 seconds before validity normalization; its
result count was the same. The persistent R-tree satisfies the indexed-load
scenario, although DuckDB's batch `SPATIAL_JOIN` operator builds its own
temporary R-tree for the smaller join side.

Run all eight queries in one CLI session so process startup is excluded:

```bash
{
  echo '.timer on'
  echo 'LOAD spatial;'
  echo 'SET threads=15;'
  for i in 0 1 2 3 4 5 6 7; do
    echo 'SELECT count(DISTINCT p.id) AS land_points
          FROM points p
          JOIN land l ON ST_DWithin(l.geom, p.geom, 0);'
  done
} | duckdb -csv "$DB"
```

The first two timer lines are `LOAD` and `SET`. Of the next eight timer lines,
discard query run 0 and summarize query runs 1-7.

For singular lookup, use the exact `ST_Covers` predicate. Unlike scalar
`ST_DWithin`, this query shape uses DuckDB's persistent `land_geom_rtree` index:

```bash
UV_CACHE_DIR=/private/tmp/trifold-uv-cache \
uv run --no-project --with duckdb==1.5.3 \
  python scripts/benchmark_landcheck_sql_scalar.py duckdb \
  --points "$OUT/points.csv" \
  --count 1000 \
  --repeats 7 \
  --database "$DB"
```

The runner keeps one embedded connection open and executes one bound query per
point. `EXPLAIN` should contain `RTREE_INDEX_SCAN` for `land_geom_rtree`.

To compare SQL output with Trifold:

```sql
CREATE OR REPLACE TABLE exact_land AS
SELECT DISTINCT p.id
FROM points p
JOIN land l ON ST_DWithin(l.geom, p.geom, 0);

CREATE OR REPLACE TABLE trifold_results AS
SELECT id::INTEGER AS id,
       trifold_base::INTEGER::BOOLEAN AS trifold_base,
       trifold_refined::INTEGER::BOOLEAN AS trifold_refined
FROM read_csv('/private/tmp/trifold-landcheck-benchmark/trifold_results.csv',
              header=true);

SELECT
  (SELECT count(*) FROM exact_land) AS exact_land_points,
  count_if(t.trifold_base <> (e.id IS NOT NULL)) AS base_disagreements,
  count_if(t.trifold_refined <> (e.id IS NOT NULL)) AS refined_disagreements
FROM trifold_results t
LEFT JOIN exact_land e USING (id);
```

## 3. PostGIS

The usual `postgis/postgis:17-3.5` image did not publish an arm64 manifest at
test time. To avoid x86 emulation on Apple Silicon, this run used the native
`postgres:17-bookworm` image and installed the PGDG PostGIS package inside the
ephemeral container.

```bash
docker run --name trifold-postgis-bench --rm -d \
  -e POSTGRES_PASSWORD=benchmark \
  -p 55432:5432 \
  -v /private/tmp:/bench:ro \
  postgres:17-bookworm

until docker exec trifold-postgis-bench pg_isready -U postgres; do sleep 1; done

docker exec -u root trifold-postgis-bench bash -lc \
  'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
   --no-install-recommends postgresql-17-postgis-3 gdal-bin'

docker exec trifold-postgis-bench \
  psql -U postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
```

Bulk-load and build reciprocal GiST indexes:

```bash
/usr/bin/time -p docker exec trifold-postgis-bench bash -lc "
  psql -U postgres -v ON_ERROR_STOP=1 \
    -c 'DROP TABLE IF EXISTS points; DROP TABLE IF EXISTS land;' &&

  PGPASSWORD=benchmark ogr2ogr \
    -f PostgreSQL \
    'PG:host=localhost port=5432 dbname=postgres user=postgres password=benchmark' \
    /bench/osm_simplified_land_polygons.geojson \
    -nln land \
    -lco GEOMETRY_NAME=geom \
    -nlt PROMOTE_TO_MULTI \
    -overwrite \
    --config PG_USE_COPY YES &&

  psql -U postgres -v ON_ERROR_STOP=1 -c \"
    UPDATE land
    SET geom=ST_MakeValid(geom)
    WHERE NOT ST_IsValid(geom);

    CREATE TABLE points (
      id integer PRIMARY KEY,
      lon double precision,
      lat double precision,
      geom geometry(Point,4326)
    );

    COPY points (id,lon,lat)
    FROM '/bench/trifold-landcheck-benchmark/points.csv'
    WITH (FORMAT csv, HEADER true);

    UPDATE points
    SET geom=ST_SetSRID(ST_MakePoint(lon,lat),4326);

    CREATE INDEX land_geom_gist ON land USING GIST (geom);
    CREATE INDEX points_geom_gist ON points USING GIST (geom);
    ANALYZE land;
    ANALYZE points;
  \"
"
```

Both GiST indexes matter. With only the land index, PostgreSQL selected 100,000
point-driven polygon probes and the query exceeded one minute. The following
polygon-driven lateral form uses the point index and completed in about one
second:

```sql
SELECT count(DISTINCT p.id) AS land_points
FROM land l
JOIN LATERAL (
  SELECT id
  FROM points p
  WHERE ST_Covers(l.geom, p.geom)
) p ON true;
```

Verify the plan before accepting a timing:

```bash
docker exec trifold-postgis-bench psql -U postgres -c "
  EXPLAIN (ANALYZE, BUFFERS, SUMMARY, TIMING OFF)
  SELECT count(DISTINCT p.id)
  FROM land l
  JOIN LATERAL (
    SELECT id FROM points p WHERE ST_Covers(l.geom,p.geom)
  ) p ON true;
"
```

The measured plan used a parallel sequential scan of `land` and an index scan
of `points_geom_gist`, with one worker. Run one warm-up and seven more queries in
one `psql` session using `\timing on`; discard the first timing.

Run the singular benchmark from the host through the published localhost port:

```bash
UV_CACHE_DIR=/private/tmp/trifold-uv-cache \
uv run --no-project --with 'psycopg[binary]==3.2.9' \
  python scripts/benchmark_landcheck_sql_scalar.py postgis \
  --points /private/tmp/trifold-landcheck-benchmark/points.csv \
  --count 1000 \
  --repeats 7
```

The runner keeps one psycopg connection and cursor open, forces a prepared
statement, and executes one bound `ST_Covers` query per point. This intentionally
includes localhost TCP and Docker VM transport, matching an application calling
a local database service. For an engine-only variant, run the same client inside
the container over its Unix socket and report it as a separate result.

Stop the disposable database when finished:

```bash
docker stop trifold-postgis-bench
```

## 4. BigQuery results and procedure

The batch query was run on BigQuery's on-demand plan with query caching
disabled. The seven measured jobs all processed 47,960,112 bytes (45.74 MiB)
and billed 48,234,496 bytes (46.00 MiB). The query result count was not included
in the supplied job statistics, so the summary table leaves it unrecorded and
the BigQuery output is not part of the correctness checksum comparison above.

| run | job ID | elapsed | slot-ms | processed bytes | billed bytes |
|---:|---|---:|---:|---:|---:|
| 1 | `trifold_landcheck_1_1781198904` | 484 ms | 67,983 | 47,960,112 | 48,234,496 |
| 2 | `trifold_landcheck_2_1781198906` | 695 ms | 107,455 | 47,960,112 | 48,234,496 |
| 3 | `trifold_landcheck_3_1781198909` | 665 ms | 70,780 | 47,960,112 | 48,234,496 |
| 4 | `trifold_landcheck_4_1781198911` | 694 ms | 79,184 | 47,960,112 | 48,234,496 |
| 5 | `trifold_landcheck_5_1781198914` | 808 ms | 146,918 | 47,960,112 | 48,234,496 |
| 6 | `trifold_landcheck_6_1781198917` | 519 ms | 77,840 | 47,960,112 | 48,234,496 |
| 7 | `trifold_landcheck_7_1781198920` | 715 ms | 96,978 | 47,960,112 | 48,234,496 |

Summary:

```text
Elapsed:       median 694 ms, range 484-808 ms, mean 654.3 ms
Slot usage:    median 79,184 slot-ms, range 67,983-146,918,
               mean 92,448 slot-ms
Throughput:    144,092 points/s at the median
Time per point: 6.94 us at the median
Cache hits:    0 of 7
Capacity:      on-demand
```

BigQuery is a managed distributed service, so there is no honest way to make
its hardware equivalent to a 15-core laptop. Treat it as a separate service
result. Record elapsed milliseconds, bytes processed, slot-milliseconds,
edition/reservation, region, and cache status for every job. Disable result
caching and do not compare only the console's displayed wall time.

Singular BigQuery queries are also not hardware-comparable to local function or
database calls: every point becomes a remote managed-service job. If this mode
matters to the application, run it separately as an end-to-end service-latency
test. Use one client, sequential parameterized queries, disabled result cache,
and the same first 1,000 points. Record both client wall time and every job's
`totalSlotMs`, processed bytes, and billed bytes. Expect this to be slow and to
incur BigQuery's per-query minimum billing; do not substitute a 1,000-row SQL
join and call it singular.

After creating the `land` table below, run the same scalar driver. First use a
small smoke sample because the full command submits 8,000 BigQuery jobs (one
warm-up plus seven measured runs):

```bash
# Smoke test: 10 sequential uncached query jobs.
uv run --no-project --with google-cloud-bigquery \
  python scripts/benchmark_landcheck_sql_scalar.py bigquery \
  --points "$OUT/points.csv" \
  --count 10 \
  --repeats 1 \
  --project "$PROJECT" \
  --location "$LOCATION" \
  --table "$PROJECT.$DATASET.land"

# Comparable singular run: 1,000 jobs per run, 8,000 including warm-up.
uv run --no-project --with google-cloud-bigquery \
  python scripts/benchmark_landcheck_sql_scalar.py bigquery \
  --points "$OUT/points.csv" \
  --count 1000 \
  --repeats 7 \
  --project "$PROJECT" \
  --location "$LOCATION" \
  --table "$PROJECT.$DATASET.land" \
  > "$OUT/bigquery_scalar.json"

uv run --no-project --with google-cloud-bigquery \
  python -c 'import importlib.metadata as m; print(m.version("google-cloud-bigquery"))'
```

The JSON contains each run's wall time and summed `slot_millis`,
`bytes_processed`, and `bytes_billed`. Record the printed client-library version
next to the result. The runner uses one client, no concurrency, bound longitude
and latitude parameters, and `use_query_cache=False`.

Google documents that persisted `GEOGRAPHY` values perform better and that
inner spatial joins using `ST_COVERS` are optimized. See:

- [Working with geospatial data](https://cloud.google.com/bigquery/docs/geospatial-data)
- [ST_COVERS reference](https://cloud.google.com/bigquery/docs/reference/standard-sql/geography_functions#st_covers)
- [Loading GeoParquet and geospatial Parquet](https://cloud.google.com/bigquery/docs/loading-data-cloud-storage-parquet#geospatial_data)
- [Spatial analysis best practices](https://cloud.google.com/bigquery/docs/best-practices-spatial-analysis)

Set project-specific values:

```bash
export PROJECT=your-gcp-project
export DATASET=trifold_benchmark
export LOCATION=EU
export BUCKET=your-existing-benchmark-bucket
export OUT=/private/tmp/trifold-landcheck-benchmark
```

Convert the FeatureCollection to newline-delimited JSON. The geometry is kept as
a GeoJSON string so BigQuery can build a native, persisted `GEOGRAPHY` column:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

src = Path('/private/tmp/osm_simplified_land_polygons.geojson')
dst = Path('/private/tmp/trifold-landcheck-benchmark/land.ndjson')
data = json.loads(src.read_text())
with dst.open('w', encoding='ascii') as out:
    for feature in data['features']:
        row = {
            'fid': int(feature['properties']['FID']),
            'geojson': json.dumps(feature['geometry'], separators=(',', ':')),
        }
        out.write(json.dumps(row, separators=(',', ':')) + '\n')
PY

gcloud storage cp "$OUT/land.ndjson" "gs://$BUCKET/trifold-benchmark/land.ndjson"
gcloud storage cp "$OUT/points.csv" "gs://$BUCKET/trifold-benchmark/points.csv"
```

Create and load raw tables:

```bash
bq --location="$LOCATION" mk --dataset "$PROJECT:$DATASET"

bq --location="$LOCATION" load --replace \
  --source_format=NEWLINE_DELIMITED_JSON \
  "$PROJECT:$DATASET.land_raw" \
  "gs://$BUCKET/trifold-benchmark/land.ndjson" \
  fid:INTEGER,geojson:STRING

bq --location="$LOCATION" load --replace \
  --source_format=CSV --skip_leading_rows=1 \
  "$PROJECT:$DATASET.points_raw" \
  "gs://$BUCKET/trifold-benchmark/points.csv" \
  id:INTEGER,lon:FLOAT,lat:FLOAT
```

Persist and cluster native geography columns. `make_valid => TRUE` repairs the
same two invalid input polygons. GeoJSON uses planar edge semantics; BigQuery
converts those edges to a geodesic approximation, so points extremely close to
a coastline can differ from planar GEOS engines.

```sql
CREATE OR REPLACE TABLE `PROJECT.DATASET.land`
CLUSTER BY geom AS
SELECT fid, ST_GEOGFROMGEOJSON(geojson, make_valid => TRUE) AS geom
FROM `PROJECT.DATASET.land_raw`;

CREATE OR REPLACE TABLE `PROJECT.DATASET.points`
CLUSTER BY geom AS
SELECT id, lon, lat, ST_GEOGPOINT(lon, lat) AS geom
FROM `PROJECT.DATASET.points_raw`;
```

Replace `PROJECT` and `DATASET` before submitting. The timed query is an inner
join so BigQuery can apply its optimized spatial join:

```sql
SELECT COUNT(DISTINCT p.id) AS land_points
FROM `PROJECT.DATASET.points` p
JOIN `PROJECT.DATASET.land` l
  ON ST_COVERS(l.geom, p.geom);
```

Run one warm-up plus seven measured jobs with result caching disabled. Assign a
known job ID so each job's statistics can be saved:

```bash
SQL="SELECT COUNT(DISTINCT p.id) AS land_points
     FROM \`$PROJECT.$DATASET.points\` p
     JOIN \`$PROJECT.$DATASET.land\` l
       ON ST_COVERS(l.geom, p.geom)"

for run in 0 1 2 3 4 5 6 7; do
  JOB_ID="trifold_landcheck_${run}_$(date +%s)"
  bq --project_id="$PROJECT" \
    --location="$LOCATION" \
    --job_id="$JOB_ID" \
    query \
    --use_legacy_sql=false \
    --use_cache=false \
    "$SQL"

  bq --project_id="$PROJECT" --location="$LOCATION" \
    show --job --format=prettyjson \
    "$PROJECT:$JOB_ID" > "$OUT/bigquery_${run}.json"
done
```

Summarize runs 1-7 from each job JSON:

```bash
jq '{
  job_id: .jobReference.jobId,
  cache_hit: .statistics.query.cacheHit,
  elapsed_ms: ((.statistics.endTime|tonumber) - (.statistics.startTime|tonumber)),
  total_slot_ms: (.statistics.query.totalSlotMs|tonumber),
  bytes_processed: (.statistics.query.totalBytesProcessed|tonumber),
  bytes_billed: (.statistics.query.totalBytesBilled|tonumber)
}' "$OUT"/bigquery_{1,2,3,4,5,6,7}.json
```

Also record whether the project used on-demand capacity or a named reservation,
the BigQuery edition, reservation baseline/max slots, and any concurrent jobs.
Without those fields the BigQuery timing is not repeatable or comparable.

## Interpretation and limits

- Trifold wins both measured local modes because the lookup is a compact
  hierarchical cell lookup and only refinement-covered cells pay polygon cost.
- PostGIS performs well after the join is oriented to reuse polygons and probe
  the point GiST index. The default point-driven plan was much worse here.
- DuckDB's spatial join is convenient and fully local, but exact predicates on
  these complex global polygons are substantially more expensive than Trifold's
  precomputed representation.
- SQL engines return exact containment for the loaded OSM polygon snapshot;
  Trifold's compact representation has intentionally different size/accuracy
  tradeoffs and mixed Natural Earth/OSM provenance.
- Singular mode measures sequential warm-client latency; batch mode measures
  100K set throughput. Neither covers concurrency, update cost, operational
  complexity, cold starts, or non-local production network latency.
- Uniform random points emphasize open ocean and continental interiors. Add a
  separate coastal stress set before making decisions for vessel tracking,
  reverse geocoding near shore, or coastline QA.
- Repeat runs after pinning new engine or dataset versions. Do not label an
  unpinned `latest` dataset result as comparable to this one.
