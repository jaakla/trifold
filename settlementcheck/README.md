# settlementcheck

`settlementcheck` is a standalone, offline Python and JavaScript library for
answering which published GHS-WUP Degree of Urbanisation class contains a
longitude/latitude point. It bundles the R2025A, epoch-2025 Stage-I Level-2
classification as a **4.58 MB class-only Trifold T3 dataset**. Boundary
details are optional and loaded by face on demand; they are not bundled in
the Python/npm core packages. The core plus every detail shard is 23.31 MB.

```python
from settlementcheck import SettlementCheck

sc = SettlementCheck()
result = sc.classify(24.7536, 59.4370)  # no details read
print(result.settlement_class, result.code)
```

```js
import { SettlementCheck } from "settlementcheck";

const sc = await SettlementCheck.fromFile();
console.log(sc.classify(24.7536, 59.4370)); // no details read
```

The full result includes the Level-2 code/name, derived Level-1 domain,
`surface`, dominant `class_share`, explicit `mixed`, `nodata_mixed` and
`no_data` state, T3 cell,
source release, year, projected-estimate marker, and 1 km source resolution.
`is_urban()`/`isUrban()` means any code 21, 22, 23, or 30—not only an urban
centre. Level 1 classifies water in its residual “rural grid cell” domain;
always inspect `surface` when land/water matters.

## Optional, lazy boundary details

`class_code`/`classCode`, `settlement`, `is_urban`/`isUrban` and
`settlement_batch`/`settlementBatch` require only the core file. `classify`
also returns class labels, hierarchy, T3 address and provenance. Without
details it explicitly returns null for share, mixture booleans and surface
(except dominant nodata's `surface="unknown"`), and `details_loaded=False`
/ `detailsLoaded=false`. Missing detail data never means homogeneous.

The matching `degurba_R2025A_E2025_L12.details/` directory is available in
this repository and under the demo's `docs/data/`. Its manifest lists the
size and SHA-256 of each shard. Download it separately for fully offline use;
shards range from 1.2 KB to 3.85 MB, and a point requires only one of 20 faces.

```python
sc = SettlementCheck(details_path="/path/to/degurba_R2025A_E2025_L12.details")
r = sc.check(24.7536, 59.4370)  # reads the local face only on first use
print(r.class_share, r.mixed, r.nodata_mixed)
sc.unload_details()
```

Python never downloads data by default. For application-managed remote
loading, supply `details_loader(face)` returning the matching shard's bytes.
Missing local shards raise `DetailsNotLoadedError`; classification remains
available. The default local directory is beside the selected core file.

```js
const sc = await SettlementCheck.fromUrl(
  'https://jaakla.github.io/trifold/data/degurba_R2025A_E2025_L12.tfdg'
);
const r = await sc.checkAsync(24.7536, 59.4370); // fetches one sibling shard
console.log(r.classShare, r.mixed);
sc.check(24.7536, 59.4370); // synchronous, only while this face is cached
sc.unloadDetails();
```

JavaScript's synchronous `check` requires an already loaded face; use
`await checkAsync` or `await loadDetails` for lazy loading. `fromBytes` accepts
`{detailsLoader: async face => bytes}` when no source URL/path is known.
`fromFile` uses a sibling local directory, and `fromUrl` uses sibling URLs.
`checkBatchAsync` groups detailed lookups by face; `settlementBatch` never
loads details. The default cache retains two faces, configurable with
`cache_faces` / `cacheFaces` in 1..20. Failed loads are retryable, and JS
coalesces concurrent requests for the same face. JS loaders may have multiple
in-flight faces; applications should bound concurrent requests as well.

The CLI returns class/provenance by default. Pass `--details /path/to/directory`
for a detailed result, or `--json` for the explicit loading/status fields.

Population counts, settlement names and administrative polygons are separate
potential enrichments, not boundary details. See [ENRICHMENTS.md](ENRICHMENTS.md)
for the inspected sources, licensing and proposed lazy-loading approach.

## What the classes mean

DEGURBA is not a set of interchangeable density bands. The published model
combines permanent-land density, cluster population, connectivity, distance,
and urban-centre smoothing/gap filling. A class must not be converted back to
a numeric population density. The 2025 population input is projected, and a
T3 boundary finer than 1 km does not create finer scientific information.

The eight values are `urban_centre` (30), `dense_urban_cluster` (23),
`semi_dense_urban_cluster` (22), `suburban_or_peri_urban` (21),
`rural_cluster` (13), `low_density_rural` (12),
`very_low_density_rural` (11), and `water` (10). Source nodata is distinct.

## Rebuild

Download the source ZIP named in [`data/manifest.json`](data/manifest.json),
verify its SHA-256, extract the GeoTIFF, then run:

```console
python build.py --source /path/to/GHS_WUP_DEGURBA_E2025_GLOBE_R2025A_54009_1000_V1_0.tif --level 12 --jobs 2
```

Build dependencies are Rasterio and NumPy. Scalar package lookups have no
runtime dependency; install the `batch` extra for vectorized T3 location. See
[`data/NOTICE.md`](data/NOTICE.md) for
source attribution and the change notice.

## Resolution and limitations

The official class raster is authoritative. Homogeneous T3 ancestors are
stored as intervals; boundary cells retain the dominant equal-area source
class, an 8-bit area share, and water/nodata mix flags. `class_share` describes
the transferred T3 cell—it is not a probability or scientific confidence.
Small or narrow source features can be represented only to the chosen T3
level, and all source-model limitations remain.

## TFDG v1 format

The format remains **WIP version 1**. The class-only layout uses flags 3;
the obsolete experimental monolithic layout is rejected and must be rebuilt.
The core contains independently compressed lengths and class slots. Detail
shards contain sparse mixed intervals, 8-bit shares and two packed flag
planes. Both carry source metadata and a shared build identity that prevents
mixing releases. TFDG uses uint32 base indexes and supports through L13.
See [FORMAT.md](FORMAT.md) for the exact binary layout and validation rules.
