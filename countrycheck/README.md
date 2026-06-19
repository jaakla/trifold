# countrycheck — offline country lookup

This is created as Trifold application (also test and demonstration)

**Which country is this lat/long point in?** gets answered anywhere on
Earth in ~1–13 µs, fully offline, from a small **323 KB** bundled dataset —
with a confidence value for every answer. Works with Python and JavaScript.
Country polygons are extended with coastal waters, so points slightly
offshore still resolve to the nearest coastal country; open ocean returns
"no country".

Install: `pip install countrycheck` / `npm install countrycheck` (or use
straight from a repo checkout, as below).

```python
from countrycheck import CountryCheck   # installed; from a checkout, first:
                                        # import sys; sys.path.insert(0, "countrycheck/python")

cc = CountryCheck()
cc.country(24.7536, 59.4370)          # 'EST'   (lon, lat — Tallinn)
cc.check(-0.1276, 51.5072)
# CountryResult(country='GBR', iso2='GB', name='United Kingdom', kind='country',
#               confidence=1.0, share=1.0, cell='TFA95BM', refined=False)
```

```js
import { CountryCheck } from "./countrycheck/js/countrycheck.mjs";
const cc = await CountryCheck.fromFile();          // NodeJs takes bundled data directly
// OR:
const cc = await CountryCheck.fromUrl("/data/countries_L10.tfcs"); // browser needs to load data file online
cc.country(24.7536, 59.437);          // 'EST'
cc.check(-0.1276, 51.5072);
// { country: 'GBR', iso2: 'GB', name: 'United Kingdom', kind: 'country',
//   confidence: 1, share: 1, cell: 'TFA95BM', refined: false }
```

## How it works

The Trifold level-10 grid (~7 km triangles, 21M cells globally) is
classified against country polygons extended with coastal waters (256
countries and territories, including X-coded ones like Kosovo or the
Caspian Sea that have no ISO code). The **borders come from the
timezone-boundary-builder "with oceans" polygons** (OSM-derived, so they
follow the true line and already reach into nearby territorial water);
GADM level-0 supplies only the country identity and ISO codes, joined by
maximum land overlap. (That timezone source carries occasional antenna
artifacts — a vertex spiking off the border and back; `scripts/despike_countries.py`
removes them before the grid build, touching 0.02% of vertices with no
measurable area change.) 6.90M cells belong to some country, of which
195,473 are *border* cells (crossed by a country/country or country/water
edge) and the rest are wholly interior. Because Trifold addresses sort
hierarchically, every cell at any level maps to a contiguous range in the
canonical level-10 index space (`face·4¹⁰ + path`), so the entire
classification collapses to **222,855 run-length intervals** — 324 KB
compressed, including the country table and, for every border cell, the best country call with a
4-bit area share.

A lookup is: locate the point's level-10 triangle (pure float math, no
dependencies), then binary-search the runs.

| answer kind | meaning | `country` | `confidence` |
|---|---|---|---|
| `country` | cell wholly inside one country | that country | 1.0 |
| `none` | cell absent from dataset (international waters) | `None` | 1.0 |
| `border` | mixed cell | best call (may be `None`) | call's area share |
| `border` + `refined` | decided by exact polygon test | exact | 0.99 |

**Measured accuracy** (100,000 uniform random points vs. exact polygon
containment in the source dataset): 99.83% agreement overall; `country`
and `none` answers correct; *all* residual error lives in `border`
answers, which self-report their lower confidence. With the border
refinement loaded, agreement is **99.995%** (5 points in 100,000, all
coastal water claimed by two countries where the tie-break differs).

**Independent accuracy** — against 57,501 real airports (OurAirports,
each tagged with an ISO country code), countrycheck places **99.50%**
in the right country with the bundled data and **99.68%** with the
refinement. Interior-country answers are 99.91% right; the refinement
works only on the 729 airports that fall in a *border cell*, lifting
those from 80.66% to **95.20%**. The remaining disagreements are mostly
genuine source differences (disputed/border territory the sources assign
differently, dependencies coded to a parent state, offshore or
placeholder coordinates). Reproduce with
`scripts/accuracy_countrycheck_airports.py`.

Caveats inherited from the source data: coastal waters come from the
timezone "with oceans" polygons (an operational maritime extent, not
legal EEZ); disputed/border territory follows whatever the two sources
encode (e.g. Crimea, Western Sahara, the Korean DMZ); lakes belong to
their surrounding country except the Caspian Sea, which is its own `XCA`
entry.

## Optional border refinement

For applications that need exact borders, a second dataset
(`borders_L10.tfcr`, **19.2 MB**) stores the source country polygons
clipped to every border cell, quantized to a cell-local 16-bit grid
(~0.1 m) with delta-varint rings, one zone per country present in the
cell. When loaded, border answers switch from the bulk best-call guess
to an exact point-in-polygon test — country/country land borders and
the coastline both resolve exactly (~13 µs per refined lookup, Python):

```python
cc = CountryCheck(refine_path="countrycheck/data/borders_L10.tfcr")
```

```js
await cc.loadRefinement("countrycheck/data/borders_L10.tfcr");
```

Only border cells pay the polygon-test cost; interior and open-water
answers are unaffected (they are already exact).

Command-line one-off checks (uses refinement automatically when the
file is present):

```console
$ python countrycheck/python/countrycheck.py 24.7536 59.4370
EST  iso2=EE  name='Estonia'  kind=country  confidence=1.000  share=1.0  cell=TFAVKGR  refined=False
```

## Performance

| operation | speed |
|---|---|
| Python scalar `country` | ~13 µs/point (79k/s) |
| Python batch `country_batch` (numpy) | ~3 µs/point |
| JavaScript `country` (Node) | ~0.6 µs/point (1.6M/s) |
| dataset load | ~40–75 ms |

The Python library is dependency-free (stdlib only); `country_batch`
optionally uses numpy + the trifold SDK. The JS library is a single
ES module, works with browser + Node.

## Benchmark vs SQL spatial engines

Same job for every engine: assign a country (`gid_0`) to 100,000
sphere-uniform random points against the same country polygons. Median of
seven warm runs on an Apple M5 Pro (June 2026). Refined countrycheck
reproduced exact point-in-polygon containment on 99.995% of the points
(5 of 100,000, all coastal-overlap tie-breaks; base 99.83%) while running
far faster:

| engine | batch | points/s | vs Trifold |
|---|---:|---:|---:|
| **Trifold base** | 0.221 s | **452,594** | 1× |
| **Trifold + refinement** | 0.234 s | **428,151** | 1× |
| PostGIS 3.6.3 | 1.694 s | 59,043 | 7.7× slower |
| DuckDB 1.5.3 Spatial | 21.499 s | 4,651 | 97× slower |

Called one point at a time, Trifold answered ~88,000 lookups/s vs 2,261
(DuckDB) and 1,265 (PostGIS). DuckDB and PostGIS returned byte-identical
answers. Full methodology, the singular numbers, dataset manifest, the
airport accuracy test and the BigQuery procedure are in
[`countrycheck_benchmark.md`](../countrycheck_benchmark.md); the scripts
are `scripts/benchmark_countrycheck.py` and
`scripts/benchmark_countrycheck_sql_scalar.py`.

## Files

```
build.py               TFCS + TFCR builder: countries_coastal.geojson -> data/
python/                countrycheck.py (public API) · _fastloc.py (point location)
js/countrycheck.mjs    the JS library (same data, same answers)
data/                  countries_L10.tfcs (bundled) · borders_L10.tfcr (optional)
tests/                 pytest + node:test suites, shared fixture (points.json)
```

Rebuild from the source polygons:

```bash
python countrycheck/build.py               # needs osm-vector/countries_coastal.geojson
python countrycheck/tests/make_fixture.py  # refresh cross-language fixture
pytest countrycheck/tests/ && node --test countrycheck/tests/test_countrycheck.mjs
```

## Format notes

Custom data format is used to ensure compactness.

* **TFCS** (country runs): 20-byte header + zlib stream of a country table (code/iso2/name strings), then `varint(gap), varint(length<<1 | border)` per run — interior runs carry `varint(country_id)`, border runs are followed (in a separate block) by a per-cell best call (`varint(0=none | country_id+1)`) and a 4-bit area share. 

* **TFCR** (refinement): 12-byte header + zlib stream of `varint(Δindex), varint(n_zones)` per border cell, each zone a country id plus quantized zigzag-delta rings combined by the even-odd rule (zero rings = whole cell). Both formats are level-agnostic (the level lives in the header), so the same tooling can serve an L8 or L12 variant.

## Roadmap

* Level-12 (~1.8 km trifolds) variant for higher-precision use.
* Timezone detection from the same source data (`tzids` are already
  in the per-country properties; cells would map to tzid instead of
  country id).
* **Custom polygon identities** — generalise the builder into a universal
  "polygon layer → grid identity" indexer for any non-overlapping layer
  (counties, ZIP/postal areas, admin units, electoral or sales districts,
  timezones — the item above is just one instance). This is mostly `build.py`
  parameterised: take an arbitrary id field instead of `gid_0`/`iso2`/`name`,
  drop the country-specific source prep (coastal/territorial-water extension,
  GADM↔timezone reconciliation), and choose the level per layer (finer for
  dense small polygons). The cell runs, the mixed-cell best-call + area share,
  and the TFCR exact-border refinement are already identity-agnostic; only the
  65,535-identity ceiling (a u16 header count + the `len(countries) > 0xFFFF`
  guard — payload ids are already varints) needs widening to u32 for very large
  layers such as global postal codes.

countrycheck is published on both registries: `pip install countrycheck` and
`npm install countrycheck` (the core SDK is `t3grid`). When cutting a release,
bump the version in both `pyproject.toml` and `package.json`, rebuild
(`uv build`), then `uv publish` and `npm publish --access public`.
