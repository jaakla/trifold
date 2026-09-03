# settlementcheck

`settlementcheck` is a standalone, offline Python and JavaScript library for
answering which published GHS-WUP Degree of Urbanisation class contains a
longitude/latitude point. It bundles the R2025A, epoch-2025 Stage-I Level-2
classification as a compact Trifold T3 dataset.

```python
from settlementcheck import SettlementCheck

sc = SettlementCheck()
result = sc.check(24.7536, 59.4370)
print(result.settlement_class, result.code, result.mixed)
```

```js
import { SettlementCheck } from "settlementcheck";

const sc = await SettlementCheck.fromFile();
console.log(sc.check(24.7536, 59.4370));
```

The full result includes the Level-2 code/name, derived Level-1 domain,
`surface`, dominant `class_share`, explicit `mixed`, `nodata_mixed` and
`no_data` state, T3 cell,
source release, year, projected-estimate marker, and 1 km source resolution.
`is_urban()`/`isUrban()` means any code 21, 22, 23, or 30—not only an urban
centre. Level 1 classifies water in its residual “rural grid cell” domain;
always inspect `surface` when land/water matters.

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
python build.py --source /path/to/GHS_WUP_DEGURBA_E2025_GLOBE_R2025A_54009_1000_V1_0.tif --level 12 --jobs 4
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

The little-endian 60-byte header records magic/version, T3 level, epoch,
release id, source resolution, run/mixed/cell counts, uncompressed length,
and the 32-byte source-raster SHA-256. The zlib payload contains delta-varint
canonical runs (`gap`, `length`, class byte, mixed byte), followed by two
bytes per mixed cell (quantized dominant share and water/nodata flags).
TFDG v1 uses 32-bit base indexes and therefore supports through L13. Readers
reject gaps in an all-runs artifact, bad codes, incompatible metadata, and
truncated data.
