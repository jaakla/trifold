# Country-check benchmark: Trifold vs SQL spatial engines

This benchmark measures Trifold `countrycheck` two ways:

1. **Accuracy** against an independent real-world point set — 57,501 airports
   from OurAirports, each carrying an ISO country code.
2. **Speed** against point-in-polygon queries over the same GADM-derived country
   polygons (extended with coastal waters) in DuckDB, PostGIS, and BigQuery.

Local results were measured on June 13, 2026. BigQuery is documented but was not
run in this pass; follow the procedure in section 5 to reproduce it on your own
project.

All three scripts live in `scripts/` and are runnable from the repository root:

```text
scripts/accuracy_countrycheck_airports.py     accuracy vs airport iso_country
scripts/benchmark_countrycheck.py             generate points + time countrycheck
scripts/benchmark_countrycheck_sql_scalar.py  one SQL query per point (3 engines)
```

## 1. Accuracy vs airports

`osm-vector/airports.geojson` is the OurAirports dump: 57,501 point features,
each with an ISO 3166-1 alpha-2 `iso_country`. The test asks countrycheck which
country each airport falls in and compares to `iso_country`, with and without
the border refinement. The only code alias needed is `XK` ⇄ `XKO` (Kosovo);
everything else is compared on countrycheck's `iso2`.

```bash
.venv/bin/python scripts/accuracy_countrycheck_airports.py
```

| mode | agreement | airports placed in a country wrongly | no-country answers |
|---|---:|---:|---:|
| base (bundled best call) | **99.485%** | 199 | 97 |
| with border refinement | **99.657%** | 100 | 97 |

By answer kind, the refined run breaks down as:

| kind | airports | agreement |
|---|---:|---:|
| `country` (cell wholly in one country) | 56,636 | 99.94% |
| `border` (mixed cell) | 768 | 91.54% |
| `none` (open water) | 97 | 0% by definition |

The refinement only touches the 768 airports that fall in a **border cell**, and
that is exactly where it pays off:

| border-cell airports | agreement |
|---|---:|
| base best-call | 78.65% |
| refined exact polygon | **91.54%** |

The refinement corrected a net 99 of those 768 border airports. The residual
disagreement is dominated by genuine source differences, not location error:
airports on disputed or border territory that GADM assigns differently
(`KR`→`KP` along the Korean DMZ, `CA`→`US` for fields sitting exactly on the
49°N line), dependencies coded to a parent state versus a separate GADM entry
(Svalbard coded `NO` while GADM carries a distinct `SJ`), and a handful of
offshore or placeholder coordinates — including two literal null-island `0,0`
airports — that correctly resolve to open water.

This is an independent check: countrycheck's polygons and the airport codes come
from unrelated sources, so it is not a self-consistency test the way section 4
is.

## 2. Speed summary

The speed workload uses deterministic points uniformly distributed by surface
area on a sphere. Two execution modes are measured; each result is the median of
seven runs after one unreported warm-up. Setup/load time is separate.

- **Singular:** the first 1,000 points, one API or parameterized SQL call at a
  time, with one warm process and connection.
- **Batch:** all 100,000 points in one vectorized call or set-based SQL query.

The question is "which country (`gid_0`) covers this point?". Where coastal-water
buffers overlap, the SQL tie-break is the country with the larger land area
(`ORDER BY land_area_km2 DESC LIMIT 1`); countrycheck resolves overlaps at build
time.

### Batch: 100,000 points per call

| engine / mode | setup | median query | min-max | points/s | us/point | matched |
|---|---:|---:|---:|---:|---:|---:|
| Trifold base | 0.073 s | **0.247 s** | 0.238-0.253 s | 405,255 | 2.47 | 33,826 |
| Trifold + border refinement | 1.497 s | **0.261 s** | 0.256-0.266 s | 383,804 | 2.61 | 33,827 |
| PostGIS 3.6.3 | ~8 s | **3.093 s** | 3.086-3.111 s | 32,329 | 30.9 | 33,827 |
| DuckDB 1.5.3 Spatial | 2.84 s | **16.925 s** | 16.737-17.274 s | 5,909 | 169.3 | 33,827 |
| BigQuery on-demand | managed | not run | | | | |

```text
Trifold base     405,255 pts/s  ████████████████████████████████████████
Trifold + refine 383,804 pts/s  █████████████████████████████████████▉
PostGIS           32,329 pts/s  ███▏
DuckDB Spatial     5,909 pts/s  ▌
```

For this batch, refined Trifold was 11.9x faster than PostGIS and 65.0x faster
than DuckDB; base Trifold was 12.5x and 68.6x. PostGIS was 5.5x faster than
DuckDB on these complex country polygons. These ratios describe this specific
global, uniformly random workload.

### Singular: one point per call, 1,000 calls per run

| engine / mode | median run | min-max | queries/s | us/query | matched |
|---|---:|---:|---:|---:|---:|
| Trifold base scalar | **0.01252 s** | 0.0124-0.0127 s | 79,849 | 12.5 | 352 |
| Trifold + refinement scalar | **0.01402 s** | 0.0139-0.0222 s | 71,341 | 14.0 | 352 |
| DuckDB 1.5.3 Spatial | **0.414 s** | 0.409-0.424 s | 2,415 | 414 | 352 |
| PostGIS 3.6.3 over localhost/Docker | **0.867 s** | 0.856-0.904 s | 1,153 | 867 | 352 |
| BigQuery | not run | follow section 5 | | | |

```text
Trifold base scalar  79,849 q/s  ████████████████████████████████████████
Trifold + refine     71,341 q/s  ███████████████████████████████████▊
DuckDB Spatial        2,415 q/s  █▏
PostGIS               1,153 q/s  ▌
```

Trifold base scalar was 33.1x faster than embedded DuckDB and 69.3x faster than
PostGIS through the host-to-Docker TCP connection. The singular result includes
language-driver and query-call overhead; the PostGIS path includes localhost TCP
and Docker VM transport while DuckDB is embedded in the Python process.

## 3. Cross-engine agreement

DuckDB and PostGIS returned byte-identical answers for the 1,000 singular points
(same SHA-256 over the per-point `gid_0` sequence):

```text
fa29d26a64a2b03569d51f86643c47ae5b6e2e6396ef9747d62c2aca0ec87a71
```

All three local engines agreed on the matched-country count for the full
100,000-point batch: 33,827 points fall in some country (the rest are open
ocean → no country).

## 4. countrycheck vs exact SQL containment

The benchmark driver writes `countrycheck_results.csv` (per-point base and
refined `gid_0`). Joining it against the exact DuckDB containment result over the
same `countries_coastal` polygons:

| Trifold mode | disagreements / 100,000 | agreement |
|---|---:|---:|
| base | 160 | 99.840% |
| border-refined | **0** | **100.000%** |

Every base disagreement is a border cell, and the refinement resolves all of
them on this sample — refined countrycheck reproduces exact point-in-polygon
containment here, while running ~12x faster than PostGIS and ~65x faster than
DuckDB performing that same containment. (This is consistent with the library's
documented accuracy: 99.82% base / 100.0% refined on a separate 30,000-point
random sample.)

To reproduce the cross-check in one DuckDB session after section 6 setup:

```sql
LOAD spatial;
CREATE OR REPLACE TABLE exact_country AS
  SELECT p.id, arg_max(l.gid_0, l.land_area_km2) AS gid_0
  FROM points p JOIN countries l ON ST_Covers(l.geom, p.geom)
  GROUP BY p.id;
CREATE OR REPLACE TABLE tr AS
  SELECT id::INTEGER AS id, countrycheck_base, countrycheck_refined
  FROM read_csv('/private/tmp/trifold-countrycheck-benchmark/countrycheck_results.csv',
                header=true);
SELECT
  count(*) FILTER (WHERE coalesce(e.gid_0,'') <> coalesce(tr.countrycheck_base,''))
    AS base_disagreements,
  count(*) FILTER (WHERE coalesce(e.gid_0,'') <> coalesce(tr.countrycheck_refined,''))
    AS refined_disagreements
FROM tr LEFT JOIN exact_country e USING (id);
```

## Test machine and versions

```text
Machine:       MacBook Pro, Apple M5 Pro
Host OS:       macOS 26.5.1, arm64
Repository:    1266513f00792cb0729315b637842da4dec574a1
Python:        3.12.13
NumPy:         2.4.6
DuckDB:        1.5.3 (Variegata), Spatial extension b68b309, native arm64
PostgreSQL:    17, bookworm under Docker Desktop
PostGIS:       3.6.3, GEOS 3.11.1, PROJ 9.1.1
Docker image:  postgres:17-bookworm (PGDG postgresql-17-postgis-3 installed in container)
```

Docker Desktop adds a Linux VM layer to PostGIS, while Trifold and DuckDB run
natively on macOS. This is not a cycle-perfect hardware comparison.

## Dataset manifest

```text
Country polygons: osm-vector/countries_coastal.geojson
Bytes:            72,741,597 (69.37 MiB)
Features:         256 MultiPolygons, one per GADM gid_0
Key columns:      gid_0, iso2, land_area_km2, has_coastal_extension
CRS:              WGS84 longitude-latitude
Source:           GADM admin-0, extended with distance-based coastal waters
                  (not legal EEZ); 7 X-coded territories without ISO codes.

Ground-truth points: osm-vector/airports.geojson (OurAirports)
Features:            57,501 Points with iso_country (ISO 3166-1 alpha-2)
```

SQL loaders run `ST_MakeValid` on invalid input features. One country polygon
makes-valid into a GeometryCollection, so the PostGIS loader coerces the repair
back to polygons with `ST_Multi(ST_CollectionExtract(..., 3))`.

Stored footprint after loading and indexing:

| representation | bytes | MiB |
|---|---:|---:|
| Trifold TFCS base | 323,038 | 0.31 |
| Trifold TFCS + TFCR | 12,127,421 | 11.57 |
| DuckDB database | 42,479,616 | 40.51 |
| PostGIS countries + points + indexes | 63,266,816 | 60.34 |

## Benchmark contract

1. Generate 100,000 points with NumPy `PCG64`, seed `20260613`.
2. Longitude is uniform in `[-180, 180)`.
3. Latitude is `degrees(asin(U[-1, 1)))`, giving sphere-area-uniform points.
4. Persist the points to CSV once; every engine reads the same decimal values.
5. Include point-on-boundary as inside (`ST_Covers` semantics).
6. Repair only invalid source geometries. Do not simplify further.
7. Resolve overlapping coastal-water buffers by larger land area, deterministically.
8. Singular mode issues one call/query per point over the first 1,000 points,
   reusing one process and connection. No client concurrency or pipelining.
9. Batch mode uses one vectorized call or one set-based SQL query over all 100,000.
10. Warm each implementation once, then time seven complete runs of each mode.
11. Report median, min, max, match count, versions, setup time, and footprint.
12. Exclude source download, process/container startup, and load/index time from
    warm query time.

## 5. Prepare shared inputs and run Trifold

Run from the repository root:

```bash
.venv/bin/python scripts/benchmark_countrycheck.py \
  --count 100000 --scalar-count 1000 --seed 20260613 --repeats 7 \
  --output-dir /private/tmp/trifold-countrycheck-benchmark
```

The driver writes `points.csv` (shared SQL input), `countrycheck_results.csv`
(per-point base and refined answers), and `countrycheck_benchmark.json` (raw
timings). It times both `CountryCheck.country` in a Python loop and the
vectorized `CountryCheck.country_batch`, and verifies they agree.

## 6. DuckDB

```bash
OUT=/private/tmp/trifold-countrycheck-benchmark
DB="$OUT/duckdb.db"; rm -f "$DB"

/usr/bin/time -p duckdb "$DB" -c "
  LOAD spatial; SET threads=8;
  CREATE TABLE countries AS
  SELECT gid_0, land_area_km2::DOUBLE AS land_area_km2, geom::GEOMETRY AS geom
  FROM ST_Read('osm-vector/countries_coastal.geojson');
  UPDATE countries SET geom=ST_MakeValid(geom) WHERE NOT ST_IsValid(geom);
  CREATE INDEX countries_geom_rtree ON countries USING RTREE (geom);
  ANALYZE countries;
  CREATE TABLE points AS
  SELECT id::INTEGER AS id, lon::DOUBLE AS lon, lat::DOUBLE AS lat,
         ST_Point(lon::DOUBLE, lat::DOUBLE) AS geom
  FROM read_csv('$OUT/points.csv', header=true);
  ANALYZE points;
"
```

Batch — run warm-up plus seven in one CLI session, discard run 0:

```bash
{
  echo '.timer on'; echo 'LOAD spatial;'; echo 'SET threads=8;'
  for i in 0 1 2 3 4 5 6 7; do
    echo 'SELECT count(DISTINCT p.id) AS matched
          FROM points p JOIN countries l ON ST_Covers(l.geom, p.geom);'
  done
} | duckdb -csv "$DB"
```

Singular — one bound `ST_Covers` query per point (uses the persistent R-tree):

```bash
UV_CACHE_DIR=/private/tmp/trifold-uv-cache \
uv run --no-project --with duckdb==1.5.3 \
  python scripts/benchmark_countrycheck_sql_scalar.py duckdb \
  --points "$OUT/points.csv" --count 1000 --repeats 7 --database "$DB"
```

## 7. PostGIS

```bash
cp osm-vector/countries_coastal.geojson /private/tmp/countries_coastal.geojson

docker run --name trifold-postgis-bench --rm -d \
  -e POSTGRES_PASSWORD=benchmark -p 55432:5432 \
  -v /private/tmp:/bench:ro postgres:17-bookworm
until docker exec trifold-postgis-bench pg_isready -U postgres; do sleep 1; done

docker exec -u root trifold-postgis-bench bash -lc \
  'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
   --no-install-recommends postgresql-17-postgis-3 gdal-bin'
docker exec trifold-postgis-bench psql -U postgres -c 'CREATE EXTENSION IF NOT EXISTS postgis;'

docker exec trifold-postgis-bench bash -lc "
  PGPASSWORD=benchmark ogr2ogr -f PostgreSQL \
    'PG:host=localhost port=5432 dbname=postgres user=postgres password=benchmark' \
    /bench/countries_coastal.geojson \
    -nln countries -lco GEOMETRY_NAME=geom -nlt PROMOTE_TO_MULTI -overwrite \
    --config PG_USE_COPY YES"

docker exec trifold-postgis-bench psql -U postgres -v ON_ERROR_STOP=1 -c \"
  UPDATE countries SET geom=ST_Multi(ST_CollectionExtract(ST_MakeValid(geom),3))
    WHERE NOT ST_IsValid(geom);
  CREATE TABLE points (id integer PRIMARY KEY, lon double precision,
    lat double precision, geom geometry(Point,4326));
  COPY points (id,lon,lat)
    FROM '/bench/trifold-countrycheck-benchmark/points.csv'
    WITH (FORMAT csv, HEADER true);
  UPDATE points SET geom=ST_SetSRID(ST_MakePoint(lon,lat),4326);
  CREATE INDEX countries_geom_gist ON countries USING GIST (geom);
  CREATE INDEX points_geom_gist ON points USING GIST (geom);
  ANALYZE countries; ANALYZE points;\"
```

Batch — the polygon-driven lateral form reuses the 256 polygons and probes the
point GiST index. Run warm-up plus seven in one `psql` session with `\timing on`
(feed the statements on stdin so each gets its own timing); discard the first:

```sql
SELECT count(DISTINCT p.id)
FROM countries l
JOIN LATERAL (SELECT id FROM points p WHERE ST_Covers(l.geom, p.geom)) p ON true;
```

Singular — from the host through the published localhost port:

```bash
UV_CACHE_DIR=/private/tmp/trifold-uv-cache \
uv run --no-project --with 'psycopg[binary]==3.2.9' \
  python scripts/benchmark_countrycheck_sql_scalar.py postgis \
  --points /private/tmp/trifold-countrycheck-benchmark/points.csv \
  --count 1000 --repeats 7

docker stop trifold-postgis-bench
```

## 8. BigQuery (procedure; not run in this pass)

BigQuery is a managed distributed service, not hardware-comparable to a laptop;
treat any result as a separate service measurement. Convert the country polygons
to newline-delimited JSON with a GeoJSON string column, load to a bucket, build a
persisted clustered `GEOGRAPHY` table, and run the same scalar driver:

```sql
CREATE OR REPLACE TABLE `PROJECT.DATASET.countries` CLUSTER BY geom AS
SELECT gid_0, land_area_km2,
       ST_GEOGFROMGEOJSON(geojson, make_valid => TRUE) AS geom
FROM `PROJECT.DATASET.countries_raw`;
```

Batch timed query (inner join lets BigQuery apply its optimized spatial join):

```sql
SELECT COUNT(DISTINCT p.id) AS matched
FROM `PROJECT.DATASET.points` p
JOIN `PROJECT.DATASET.countries` l ON ST_COVERS(l.geom, p.geom);
```

Singular: run `benchmark_countrycheck_sql_scalar.py bigquery --project ... --table
...`. Disable result caching (`use_query_cache=False`, already set), record each
job's elapsed ms, `totalSlotMs`, processed and billed bytes, region, and
edition/reservation. Expect per-query minimum billing on 8,000 jobs (warm-up plus
seven runs of 1,000). See the BigQuery section of `benchmark.md` for the full
loader and job-statistics commands; the only change is `land`→`countries` and the
`SELECT gid_0` projection.

## Interpretation and limits

- Trifold wins both local modes because the lookup is a compact hierarchical cell
  lookup; only refinement-covered border cells pay any polygon cost.
- Country polygons are heavier for the SQL engines than the land/sea mask in
  `benchmark.md`, so the speed gap is wider here (12-69x vs 3-30x).
- SQL engines return exact containment for the loaded polygons; refined Trifold
  matched that exactly on this 100,000-point sample, base Trifold to 99.84%.
- Singular mode measures sequential warm-client latency; batch mode measures 100K
  set throughput. Neither covers concurrency, updates, cold starts, or non-local
  production network latency.
- Uniform random points emphasize open ocean and continental interiors. A
  border-heavy or population-weighted workload shifts the refinement's relative
  cost and the accuracy split.
