# Trifold SDK API

Trifold provides equivalent Python and JavaScript SDKs. The command-line
interface, data builders, website, and Cloudflare Worker consume these SDKs;
they do not define separate grid implementations.

## Package boundaries

| Domain | Python | JavaScript |
|---|---|---|
| Public SDK | `trifold.api` and `trifold` | `js/trifold.js`, package `@trifold/grid` |
| Optional land extension | `trifold.land` | not implemented |
| Applications | `trifold.cli`, `scripts/` | `worker/cell-server.js`, generated website |
| Implementation modules | `address.py`, `core.py`, `grid.py`, `classify.py` | none outside `js/trifold.js` |

Applications should use the public SDK modules. Implementation modules may
change without preserving their internal structure.

## Address model

A cell identity consists of an icosahedron face in `0..19` and zero to 27
base-4 path digits. Both SDKs support:

- unsigned 64-bit integer (`int` in Python, `BigInt` in JavaScript);
- compact Crockford base32, for example `TF6958`;
- path notation, for example `F15-102111`.

GeoJSON serializes `addr64` as a decimal string because JSON numbers do not
represent every unsigned 64-bit value exactly.

### Derived grouping indexes

Triangle geometry and `addr64` remain the source of truth. Two projections
support storage layout and display without defining a second grid:

| Key | Purpose | Cardinality |
|---|---|---|
| `rhombus_id` | exact grouping and display | two triangles on the complete grid |
| `rhombus_hilbert` / `rhombus64()` | spatial sort or partition key | one key per rhombus |
| `hex_id` | per-level display and neighbor-style grouping | six triangles in face interiors |

The twenty base faces are paired into ten diamonds. At level `L`, each
diamond is a `2^L × 2^L` rhombus array. Dropping the triangle orientation
from `(diamond, level, x, y, orientation)` is exactly 2:1, and each parent
rhombus is the union of four child rhombi. `rhombus64()` applies a standard
Hilbert traversal to `(x, y)` within the diamond.

`hex_id` uses a triangular-lattice three-coloring independently on each
icosahedron face. Face-interior groups contain six triangles. Groups on
face seams contain three or six triangles depending on phase; the fixed
vertex groups contain one or five. This is a display projection, not an
H3-compatible topology, and it has no hierarchy.

Land-filtered or variable-resolution products may contain partial rhombus or
hex groups. Their grouped features include `triangle_count`; exact 2:1
rhombus cardinality applies to a complete uniform-level grid.

## Python

Install the core SDK with `pip install .`. Install `.[land]` when using
`LandClassifier`, or `.[build]` for the repository's data-generation scripts.
Then import the facade:

```python
from trifold.api import (
    cell_feature,
    cell_metrics,
    children64,
    locate_address,
    parent64,
    to_compact,
)

address = locate_address(-0.1276, 51.5072, level=6)
assert to_compact(address) == "TF6958"

feature = cell_feature(address)
metrics = cell_metrics(address)
parent = parent64(address)
children = children64(parent)
```

`import trifold` re-exports the same API for compatibility. New application
code may prefer `trifold.api` because it makes the dependency boundary clear.

### Python API groups

Address and hierarchy:

- `parse_address`, `encode64`, `decode64`
- `to_compact`, `from_compact`, `to_path`, `from_path`
- `parent64`, `children64`, `is_ancestor`, `descendant_range`
- `face_of`, `level_of`, `path_of`
- `rhombus_id`, `rhombus64`, `decode_rhombus64`, `rhombus_coords`
- `hex_id`, `lattice_triangle`

Location and geometry:

- `locate_address` returns an addr64 integer
- `locate` returns `(face, digits)` for lower-level use
- `cell_triangle`, `cell_ring`, `cell_metrics`, `cell_feature`
- `edge_km`, `area_km2`
- `icosahedron`, `subdivide`, `contains_point`

Coverage generation:

- `bbox_cover`, `polyfill`, `cover_ranges`
- `build_compacted`
- `expand_to_base`
- `cell_geometry_ring`

`bbox_cover` covers a WGS84 bbox at a fixed level. `min_lon > max_lon`
means the bbox crosses the antimeridian. `polyfill` accepts GeoJSON
`Polygon`, `MultiPolygon`, `Feature`, or `FeatureCollection` input.
Both support `mode="intersects"` for conservative prefilters and
`mode="centroid"` for compact approximate visualization.

```python
from trifold.api import bbox_cover, cover_ranges

cells = bbox_cover(-0.3, 51.4, 0.1, 51.6, level=10)
ranges = cover_ranges(cells)
# Use addr64 BETWEEN low AND high for each range, then exact-filter points
# with lon/lat or your source geometry when exact query results are needed.
```

Land classification is a separate extension because it requires Shapely and
PyProj:

```python
from trifold.api import build_compacted
from trifold.land import LandClassifier

classifier = LandClassifier(land_geodataframe)
cells = build_compacted(classifier, base_level=6)
```

## JavaScript

The SDK is a dependency-free ES module. The repository includes npm package
metadata and TypeScript declarations.

```js
import {
  cellFeature,
  cellMetrics,
  children64,
  locateAddress,
  parent64,
  toCompact,
} from "./js/trifold.js";

const address = locateAddress(-0.1276, 51.5072, 6);
console.assert(toCompact(address) === "TF6958");

const feature = cellFeature(address);
const metrics = cellMetrics(address);
const parent = parent64(address);
const children = children64(parent);
```

In the generated GitHub Pages site, the same module is published at
`./sdk/trifold.js`.

### JavaScript API groups

Address and hierarchy:

- `parseAddress`, `encode64`, `decode64`
- `toCompact`, `fromCompact`, `toPath`, `fromPath`
- `parent64`, `children64`, `isAncestor`, `descendantRange`
- `rhombusId`, `rhombus64`, `decodeRhombus64`, `rhombusCoords`
- `hexId`, `latticeTriangle`

Location and geometry:

- `locateAddress` returns a `BigInt`
- `locate` returns `{face, digits}`
- `cellTriangle`, `cellRing`, `cellMetrics`, `cellFeature`
- `edgeKm`, `areaKm2`
- `icosahedron`, `subdivide`, `containsPoint`

Enumeration:

- `levelFeatureCollection(level, {face, maxLevel})`

Coverage:

- `bboxCover(minLon, minLat, maxLon, maxLat, level, {mode})`
- `polyfill(geometry, level, {mode})`
- `coverRanges(cells)`

The `maxLevel` option is an application safety limit for enumeration. It does
not change the address limit of 27.

## Compatibility

The compact, path, and addr64 encodings are shared across both SDKs. Tests
compare point location and GeoJSON coordinates between Python and JavaScript.
Public SDK names and encoded address values are compatibility-sensitive.
