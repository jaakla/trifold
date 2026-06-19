# Country-check benchmark: Trifold vs SQL spatial engines

This benchmark measures Trifold `countrycheck` two ways:

1. **Accuracy** against an independent real-world point set — 57,501 airports
   from OurAirports, each carrying an ISO country code.
2. **Speed** against point-in-polygon queries over the same country polygons in
   DuckDB, PostGIS, and BigQuery.

The country polygons take their **borders from the timezone-boundary-builder
"with oceans" dataset** (OSM-derived, accurate, already extended into nearby
territorial water) and their **identity/ISO codes from GADM** level-0, joined by
maximum land overlap (see `sql/build_countries_coastal.sql`). Local results were
measured on June 13, 2026. BigQuery is documented but was not run in this pass;
follow the procedure in section 5 to reproduce it on your own project.

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
| base (bundled best call) | **99.496%** | 191 | 99 |
| with border refinement | **99.680%** | 85 | 99 |

By answer kind, the refined run breaks down as:

| kind | airports | agreement |
|---|---:|---:|
| `country` (cell wholly in one country) | 56,673 | 99.91% |
| `border` (mixed cell) | 729 | 95.20% |
| `none` (open water) | 99 | 0% by definition |

The refinement only touches the 729 airports that fall in a **border cell**, and
that is exactly where it pays off:

| border-cell airports | agreement |
|---|---:|
| base best-call | 80.66% |
| refined exact polygon | **95.20%** |

The refinement corrected a net 106 of those 729 border airports. The residual
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
| Trifold base | 0.065 s | **0.221 s** | 0.218-0.230 s | 452,594 | 2.21 | 33,463 |
| Trifold + border refinement | 1.995 s | **0.234 s** | 0.231-0.241 s | 428,151 | 2.34 | 33,463 |
| PostGIS 3.6.3 | ~6 s | **1.694 s** | 1.686-1.736 s | 59,043 | 16.9 | 33,463 |
| DuckDB 1.5.3 Spatial | 3.18 s | **21.499 s** | 21.163-21.813 s | 4,651 | 215.0 | 33,463 |
| BigQuery on-demand | managed | not run | | | | |

```text
Trifold base     452,594 pts/s  ████████████████████████████████████████
Trifold + refine 428,151 pts/s  █████████████████████████████████████▊
PostGIS           59,043 pts/s  █████▏
DuckDB Spatial     4,651 pts/s  ▍
```

For this batch, refined Trifold was 7.3x faster than PostGIS and 92x faster than
DuckDB; base Trifold was 7.7x and 97x. PostGIS was 12.7x faster than DuckDB on
these polygons (its lateral GiST join handles the tz polygons, which have far
fewer disjoint island parts than the previous GADM geometry, much better than
DuckDB's R-tree scan). These ratios describe this specific global, uniformly
random workload.

### Singular: one point per call, 1,000 calls per run

| engine / mode | median run | min-max | queries/s | us/query | matched |
|---|---:|---:|---:|---:|---:|
| Trifold base scalar | **0.01138 s** | 0.0113-0.0117 s | 87,848 | 11.4 | 348 |
| Trifold + refinement scalar | **0.01172 s** | 0.0116-0.0119 s | 85,361 | 11.7 | 348 |
| DuckDB 1.5.3 Spatial | **0.442 s** | 0.435-0.451 s | 2,261 | 442 | 348 |
| PostGIS 3.6.3 over localhost/Docker | **0.791 s** | 0.785-0.812 s | 1,265 | 791 | 348 |
| BigQuery | not run | follow section 5 | | | |

```text
Trifold base scalar  87,848 q/s  ████████████████████████████████████████
Trifold + refine     85,361 q/s  ██████████████████████████████████████▉
DuckDB Spatial        2,261 q/s  █
PostGIS               1,265 q/s  ▌
```

Trifold base scalar was 38.9x faster than embedded DuckDB and 69.4x faster than
PostGIS through the host-to-Docker TCP connection. The singular result includes
language-driver and query-call overhead; the PostGIS path includes localhost TCP
and Docker VM transport while DuckDB is embedded in the Python process.

## 3. Cross-engine agreement

DuckDB and PostGIS returned byte-identical answers for the 1,000 singular points
(same SHA-256 over the per-point `gid_0` sequence):

```text
7eb1e6e1ca36fa64cbdda58aaccefa4c97459ec0a72d5b1d76f08f3a35f5e5e9
```

All three local engines agreed on the matched-country count for the full
100,000-point batch: 33,463 points fall in some country (the rest are open
ocean → no country).

## 4. countrycheck vs exact SQL containment

The benchmark driver writes `countrycheck_results.csv` (per-point base and
refined `gid_0`). Joining it against the exact DuckDB containment result over the
same `countries_coastal` polygons:

| Trifold mode | disagreements / 100,000 | agreement |
|---|---:|---:|
| base | 168 | 99.832% |
| border-refined | **5** | **99.995%** |

Every base disagreement is a border cell. The refinement resolves all but 5 of
them; those 5 are points in coastal water claimed by two countries, where the SQL
tie-break (larger land area) and countrycheck's build-time assignment differ —
not a containment error. So refined countrycheck reproduces exact point-in-polygon
containment to 99.995% here, while running ~7x faster than PostGIS and ~92x faster
than DuckDB performing that same containment. (Consistent with the library's
documented 99.82% base / 100.0% refined on a separate 30,000-point random
sample.)

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
Bytes:            119,955,620 (114.4 MiB)
Features:         256 MultiPolygons, one per GADM gid_0
Key columns:      gid_0, iso2, land_area_km2, has_coastal_extension
CRS:              WGS84 longitude-latitude
Borders:          timezone-boundary-builder "with oceans" (OSM-derived), which
                  also supplies the territorial-water extent; GADM admin-0 joined
                  for identity/ISO by max land overlap (sql/build_countries_coastal.sql).
                  7 X-coded territories without ISO codes.

Ground-truth points: osm-vector/airports.geojson (OurAirports)
Features:            57,501 Points with iso_country (ISO 3166-1 alpha-2)
```

SQL loaders run `ST_MakeValid` on invalid input features. One country polygon
makes-valid into a GeometryCollection, so the PostGIS loader coerces the repair
back to polygons with `ST_Multi(ST_CollectionExtract(..., 3))`.

Stored footprint after loading and indexing:

| representation | bytes | MiB |
|---|---:|---:|
| Trifold TFCS base | 323,646 | 0.31 |
| Trifold TFCS + TFCR | 19,528,154 | 18.62 |
| DuckDB database | 78,655,488 | 75.01 |
| PostGIS countries + points + indexes | 102,670,336 | 97.92 |

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

## 9. Polyline queries (per-sample workload)

`CountryCheck.check_polyline` answers "which countries does this *line* cross?"
by sampling the polyline at uniform great-circle intervals (default 3.5 km, half
the L10 cell edge), running the point lookup at each sample, and merging
consecutive same-country samples into directed, distance-annotated segments.

There is **no polyline-specific path in SQL** — the equivalent job is one
`ST_Covers` point-in-polygon per sampled point. So the comparable metric across
all engines is **per-sample throughput**; Trifold is the only engine that also
pays sampling + segment-merge overhead. This pass was measured separately on
**2026-06-19** (see machine note below), so its absolute numbers are not directly
comparable to the 2026-06-13 point run in section 2 — read the ratios.

Workload: 60 random global polylines (NumPy `PCG64`, seed `20260614`, 2-8
vertices each), sampled at 3.5 km uniform → 669,430 sample points. Trifold is
timed over all samples; the SQL engines run a bound `ST_Covers` query over the
first 3,000 samples (per-query rate is the comparable figure, and DuckDB at
~3.5k q/s would take minutes over the full set). Median of repeated warm runs.

| engine / mode | per-sample rate | us/sample | vs Trifold base |
|---|---:|---:|---:|
| Trifold base | **38,172 samples/s** | 26.2 | 1x |
| Trifold + refinement | **37,633 samples/s** | 26.6 | 0.99x |
| PostGIS 16 / 3.4 (amd64 emulated) | **5,761 samples/s** | 173.6 | 6.6x slower |
| DuckDB 1.5.4 Spatial | **3,477 samples/s** | 287.6 | 11.0x slower |
| BigQuery | TODO | | follow section 8 |

```text
Trifold base     38,172 samples/s  ████████████████████████████████████████
Trifold + refine 37,633 samples/s  ███████████████████████████████████████▍
PostGIS           5,761 samples/s  ██████
DuckDB Spatial    3,477 samples/s  ███▋
```

As whole-polyline latency, Trifold averaged **~290 ms/polyline base, ~300 ms
refined** — but these are extreme synthetic lines (~11,000 samples each, global
random spanning thousands of km). A realistic route such as Berlin -> Warsaw ->
Vilnius (~260 samples) classifies in **~7 ms**.

Two effects worth noting:

- **SQL is faster per query on this workload than on the scattered points of
  section 2** (PostGIS 5,761 vs 1,232 samples/s; DuckDB 3,477 vs ~2,098):
  consecutive polyline samples cluster spatially and keep the GiST / R-tree warm.
  Trifold gets no such benefit — each `locate` is independent — and its per-sample
  rate sits well below its raw point-scalar rate because each sample also pays the
  great-circle sampling and segment-merge overhead on top of the lookup. The
  trifold figure is the sustained warm-run median; an earlier single pass clocked
  a cold ~59k/s, so treat ~38k as the reproducible sustained rate on this laptop.
- DuckDB and PostGIS returned **byte-identical** answers over the 3,000 samples
  (same SHA-256 over the per-sample `gid_0` sequence): `d0c89d12...`.

`check_polyline` calls the scalar `country()` in a Python loop; it does not yet
use the vectorized `country_batch` path (~450k pts/s in section 2), so there is
clear headroom to raise Trifold's polyline throughput several-fold.

### Reproduce

Generate the shared sampled-point set, then reuse the section 6/7 DuckDB and
PostGIS setup (the `countries` table is identical) and the scalar driver:

```bash
# 1. Materialise the 669,430-sample polyline workload to CSV
.venv/bin/python - <<'PY'
import csv, sys; sys.path.insert(0, "src")
import numpy as np
from trifold.api import sample_polyline
rng = np.random.default_rng(20260614)
polys = []
for _ in range(60):
    nv = rng.integers(2, 9)
    lons = rng.uniform(-180, 180, nv)
    lats = np.degrees(np.arcsin(rng.uniform(-1, 1, nv)))
    polys.append([(float(lons[i]), float(lats[i])) for i in range(nv)])
with open("/private/tmp/cc_poly_samples.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["lon", "lat"])
    for p in polys:
        for lon, lat in sample_polyline(p, step_km=3.5)[0]:
            w.writerow([float(lon), float(lat)])
PY

# 2. SQL per-sample rate (first 3,000 samples; reuses the section 6/7 DB + container)
.venv/bin/python scripts/benchmark_countrycheck_sql_scalar.py duckdb \
  --points /private/tmp/cc_poly_samples.csv --database "$DB" --count 3000 --repeats 3
.venv/bin/python scripts/benchmark_countrycheck_sql_scalar.py postgis \
  --points /private/tmp/cc_poly_samples.csv --count 3000 --repeats 3

# 3. Trifold whole-workload rate
.venv/bin/python scripts/benchmark_countrycheck_polyline.py --n-polylines 60 --repeats 5
```

This pass ran the DuckDB DB and a Dockerized PostGIS built from the same
`countries_coastal.geojson` polygons. PostGIS used `postgis/postgis:16-3.4`,
which is an **amd64 image emulated on Apple-silicon Docker** (Trifold and DuckDB
ran native arm64); its point-scalar rate nonetheless matched the section-2 native
run within noise, so emulation overhead is minor for this latency-bound scalar
workload. BigQuery for the polyline workload is **TODO** — the procedure is
identical to section 8, feeding the sampled points instead of the uniform set.

## Interpretation and limits

- Trifold wins both local modes because the lookup is a compact hierarchical cell
  lookup; only refinement-covered border cells pay any polygon cost.
- Country polygons are heavier for the SQL engines than the land/sea mask in
  `benchmark.md`, so the speed gap is wider here (7-97x vs 3-30x). DuckDB's
  R-tree scan suffers most; PostGIS's lateral GiST join holds up far better.
- SQL engines return exact containment for the loaded polygons; refined Trifold
  matched that to 99.995% on this 100,000-point sample (5 coastal-overlap
  tie-breaks), base Trifold to 99.83%.
- Singular mode measures sequential warm-client latency; batch mode measures 100K
  set throughput. Neither covers concurrency, updates, cold starts, or non-local
  production network latency.
- Uniform random points emphasize open ocean and continental interiors. A
  border-heavy or population-weighted workload shifts the refinement's relative
  cost and the accuracy split.
- The polyline workload (section 9) is per-sample point-in-polygon for every
  engine; Trifold leads by 10-17x there, a narrower gap than the scattered-point
  modes because spatial locality of consecutive samples warms the SQL indexes
  while Trifold pays per-sample sampling/merge overhead and does not yet use its
  vectorized batch path.
