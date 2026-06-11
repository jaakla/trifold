# landcheck — offline land/sea lookup 

This is created as Trifold application (also test and demonstration)

**Is this lat/long point on land or in the sea?** gets answered anywhere on
Earth in ~1–13 µs, fully offline, from a small **182 KB** bundled dataset —
with a confidence value for every answer. Works with Python and JavaScript.

```python
import sys; sys.path.insert(0, "landcheck/python")
from landcheck import LandCheck

lc = LandCheck()
lc.is_land(24.7536, 59.4370)          # True   (lon, lat — Tallinn)
lc.check(-0.1276, 51.5072)
# LandResult(land=True, kind='land', confidence=1.0, land_fraction=1.0,
#            cell='TFA95BM', refined=False)
```

```js
import { LandCheck } from "./landcheck/js/landcheck.mjs";
const lc = await LandCheck.fromFile();          // NodeJs takes bundled data directly
// OR:
const lc = await LandCheck.fromUrl("/data/landsea_L10.tfls"); // browser needs to load data file online
lc.isLand(24.7536, 59.437);           // true
lc.check(-0.1276, 51.5072);
// { land: true, kind: 'land', confidence: 1, landFraction: 1,
//   cell: 'TFA95BM', refined: false }
```

## How it works

The Trifold level-10 grid (~7 km triangles, 21M cells globally) is
classified against Natural Earth 1:50m land: 6.15M cells touch land,
of which 168,833 are *coastal* (mixed land/sea) and the rest are wholly
interior. Because Trifold addresses sort hierarchically, every cell at
any level maps to a contiguous range in the canonical level-10 index
space (`face·4¹⁰ + path`), so the entire classification collapses to
**153,884 run-length intervals** — 182 KB compressed, including a 4-bit
land-area fraction for every coastal cell.

A lookup is: locate the point's level-10 triangle (pure float math, no
dependencies), then binary-search the runs.

| answer kind | meaning | `land` | `confidence` |
|---|---|---|---|
| `land` | cell wholly inside land | `True` | 1.0 |
| `sea` | cell absent from dataset | `False` | 1.0 |
| `coast` | mixed cell | `land_fraction >= 0.5` | `max(f, 1−f)` |
| `coast` + `refined` | decided by OSM polygon test | exact | 0.99 |

**Measured accuracy** (30,000 uniform random points vs. exact polygon
containment in the source dataset): 99.82% agreement overall; `land` and
`sea` answers 100% correct; *all* residual error lives in `coast`
answers, which self-report their lower confidence (mean calibration
credit 0.997).

Caveats inherited from the source data: Natural Earth 1:50m treats **lakes as land and omits islets** below its resolution; `coast` cells flag exactly where such risk is concentrated.

## Optional coastal refinement (OSM)

For applications that need near-exact coastlines, a second dataset
(`coastal_osm_L10.tflr`, **7.1 MB**) stores OSM simplified land polygons
([osmdata.openstreetmap.de](https://osmdata.openstreetmap.de/data/land-polygons.html))
clipped to each coastal triangle, quantized to a cell-local 16-bit grid
(~0.1 m) with delta-varint rings: 134,527 cells carry polygon detail,
the other 34,306 resolve to a single all-land/all-sea bit. When loaded,
`coast` answers switch from the bulk land-fraction guess to an exact
point-in-polygon test. This has **99.95% agreement** with full polygon containment on 4,000 random points inside coastal cells (~23 µs per refined lookup, Python):

```python
lc = LandCheck(refine_path="landcheck/data/coastal_osm_L10.tflr")
```

```js
await lc.loadRefinement("landcheck/data/coastal_osm_L10.tflr");
```

Only coastal cells pay the (still tiny) polygon-test cost; `land`/`sea` answers are untouched.

Note on dataset semantics: the base layer keeps Natural Earth's view of
the world for `land`/`sea` kinds. NE and OSM systematically disagree
about Antarctica (OSM land polygons are clipped near the pole and draw
ice-shelf edges differently); refinement only ever changes answers
*inside* coastal cells, so that disagreement does not leak into the
high-confidence kinds.

Command-line one-off checks (uses refinement automatically when the
file is present):

```console
$ python landcheck/python/landcheck.py 24.7536 59.4370
LAND  kind=land  confidence=1.000  land_fraction=1.0  cell=TFAVKGR  refined=False
```

## Performance

| operation | speed |
|---|---|
| Python scalar `is_land` | ~13 µs/point (77k/s) |
| Python batch `is_land_batch` (numpy) | ~2.8 µs/point (360k/s) |
| JavaScript `isLand` (Node) | ~0.8 µs/point (1.2M/s) |
| dataset load | ~30 ms |

The Python library is dependency-free (stdlib only); `is_land_batch`
optionally uses numpy + the trifold SDK. The JS library is a single
ES module, works with browser + Node.

## Files

```
build.py          TFLS builder: compacted L10 grid GeoJSON -> landsea_L10.tfls
refine_build.py   TFLR builder: land polygons + TFLS -> coastal_osm_L10.tflr
python/           landcheck.py (public API) · _fastloc.py (point location)
js/landcheck.mjs  the JS library (same data, same answers)
data/             landsea_L10.tfls (bundled) · coastal_osm_L10.tflr (optional)
tests/            pytest + node:test suites, shared fixture (points.json)
```

Rebuild from a Trifold grid product:

```bash
python landcheck/build.py                  # needs data/global_tri_L10_compacted.geojson
python landcheck/refine_build.py --land osm_simplified_land_polygons.geojson
python landcheck/tests/make_fixture.py     # refresh cross-language fixture
pytest landcheck/tests/ && node --test landcheck/tests/test_landcheck.mjs
```

## Format notes

Custom data format is used to ensure compactness.

**TFLS** (land/sea runs): 16-byte header + zlib stream of
`varint(gap), varint(length<<1 | coastal)` per run, then 4-bit land
fractions for coastal cells. **TFLR** (refinement): 12-byte header +
zlib stream of `varint(Δindex), varint(code)` per coastal cell, where
code 0/1 = all sea/land and code n≥2 introduces n−1 quantized
zigzag-delta rings combined by the even-odd rule. Both formats are
level-agnostic (the level lives in the header), so the same tooling can
serve an L8 (~30 KB) or L12 (~3 MB) variant.

## Roadmap

* **Country detection**: the run-length layer maps
  each cell to a country id instead of a land bit (runs split at borders;
  border cells carry clipped boundary polygons like TFLR does for
  coastlines). Probably can use same formats, same lookup path, same confidence model.
* Level-12 (~1.8 km trifolds) variant for higher-precision use.
* Published packages (`pip install trifold-landcheck`, npm equivalent).
