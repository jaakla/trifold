# Trifold T3 Discrete Global Grid System: Technical Reference for Integration and Comparison

*Companion document to the [README](../README.md), structured for readers
evaluating T3 against other DGGS (A5, H3, S2, rHEALPix, HTM/QTM) for
integration into pipelines, databases, or viewers.*

## TL;DR

- **Trifold T3 is a global, triangular, exactly-nesting DGGS** built on
  the icosahedron. It tiles the sphere with quasi-equilateral spherical
  triangles in an aperture-4 quadtree where **every parent cell is
  bit-for-bit the geometric union of its four children** — the property
  that motivates the whole design. Cells are 64-bit integers across **28
  resolution levels** (level 0 = 20 cells of ~25.5M km², level 27 ≈ 2 m
  edges). Reference implementations: Python (`trifold.api`) and JavaScript
  (`js/trifold.js`), cross-tested to agree. The CLI, builders, website, and
  Worker are adapters that use these SDKs.
- **Its headline strength is lossless hierarchy**: aggregating level-9
  statistics into level-6 cells is *exact* — no boundary slivers, no
  overlap weighting, no approximation. Compacted (variable-resolution)
  tilings snap together perfectly, and any cell's descendants form one
  contiguous uint64 range. Its trade-offs are **non-uniform neighbor
  semantics** (3 edge + 9 vertex neighbors, alternating cell orientation),
  **approximate equal-area only** (~±20% within a level, smooth), and a
  **young single-repo ecosystem**.
- **For integration**: `locate(lon, lat, level)` → address;
  `cell_geometry_ring` → boundary; `build_compacted` / `expand_to_base`
  for land-adaptive coverage; addresses convert between compact base32
  (`TF6958`), digit path (`F15-102111`), and sortable uint64. A zero-data
  Cloudflare Worker serves any cell from pure math.

## Key findings

### 1. Core design

- **Polyhedron: icosahedron** — 20 equilateral triangular faces, the
  platonic solid with the most faces, hence the least per-face distortion
  when projected to the sphere. The solid is rotated +7.3° in longitude so
  no vertex sits exactly on the ±180° meridian (avoids `atan2` sign
  instability). In this orientation **both geographic poles are lattice
  vertices** (each pole is exactly the normalized midpoint of an
  icosahedron edge), so six cells meet at each pole as meridian wedges —
  a clean, fully handled configuration.
- **Cell geometry.** Cells are spherical triangles whose edges are
  great-circle arcs. Subdivision connects the great-circle midpoints of a
  parent's edges, yielding 3 corner children plus 1 central
  (orientation-flipped) child. Cells alternate between "up" and "down"
  orientations; within a level all cells are congruent up to rotation and
  the slight shape variation inherited from the sphere.
- **Projection: none.** T3 works directly on the sphere with vector
  geometry (normalized midpoints, plane-side tests). There is no
  projection step and therefore no projection distortion to characterize;
  the price is that **areas are not exactly equal** — cell areas within a
  level vary smoothly by roughly ±20% globally (computed exactly per cell
  via spherical excess and exported as `area_km2`).

### 2. Hierarchy

- **Aperture = 4, exact and congruent.** Each cell has exactly 4 children
  and 1 parent, and the parent's geometry *is* the union of its children
  — verified programmatically in the build pipeline (symmetric-difference
  area ≈ 10⁻¹⁹ of parent area, i.e. floating-point noise only). This is
  the discriminating feature versus A5 (logical-only hierarchy) and H3
  (approximate aperture-7 containment); it is shared with S2, rHEALPix,
  and HTM/QTM.
- **Levels: 28** (0–27, limited by the 54 path bits of the uint64
  encoding). Counts and sizes: level 0 = 20 cells (mean edge 7,054 km);
  level 6 = 81,920 (~110 km, ~6,226 km²); level 9 = 5.2M (~13.8 km);
  level 12 = 336M (~1.7 km); level 27 ≈ 2 m edges. General formula:
  20 × 4^L cells; mean edge ≈ 7,054 km / 2^L.
- **Compaction.** Because nesting is exact, a land-adaptive tiling
  (interior cells merged to the coarsest wholly-inside level, boundary
  cells at base resolution) covers exactly the same area as the uniform
  tiling: verified 171.1M km² in both modes at level 6 (27,614 uniform →
  10,046 compacted cells, 2.7×).

### 3. Addressing / indexing

One cell identity, three encodings (see README §2 for the full spec):

- **uint64**: 5 face bits + up to 27 path digits at 2 bits each + 5 low
  level bits. The path is left-aligned. Numeric sort = depth-first order;
  parent/child/ancestor are O(1) bit operations; *all descendants of a
  cell* fall within the inclusive interval returned by `descendant_range`
  (ideal for DB range scans).
- **compact base32** (`TF6958`): Crockford alphabet, 5 bits/char —
  a level-6 cell is 6 characters, level 15 is 9. For humans, URLs, CSVs.
- **digit path** (`F15-102111`): one base-4 digit per level, the
  teaching/debug form.

All three round-trip losslessly. Python runs 5,000 randomized codec
round-trips, and `tests/test_worker.py` cross-tests representative points
against the JavaScript Worker's public endpoint.

### 4. Tooling

- **Python SDK**: `pip install -e .` → `import trifold.api`; key functions
  `locate`, `cell_triangle`, `encode64/decode64`, `to_compact/from_compact`,
  `to_path/from_path`, `parent64/children64/is_ancestor`,
  `build_compacted`, `expand_to_base`, `cell_geometry_ring`, `edge_km`, and
  `area_km2`. `LandClassifier` is in the optional `trifold.land` extension.
  CLI: `trifold locate|show|geom|parent|children`.
- **JavaScript SDK**: `js/trifold.js` is a dependency-free ES module with
  TypeScript declarations. `worker/cell-server.js` is an HTTP adapter with
  endpoints `/cell/{addr}`,
  `/cells/{a,b,…}`, `/locate/{lon},{lat}?level=N`, `/parent`, `/children`,
  `/level/{N}`. Deploy free with `npx wrangler deploy`.
- **Exports**: GeoJSON and TopoJSON (TopoJSON recommended — shared-arc
  deduplication cuts 40–60%, enabled across mixed levels by
  lattice-consistent edge densification); PMTiles recipe for vector-tile
  serving at scale (`scripts/make_pmtiles.sh`).
- **License**: MIT.

### 5. Land-adaptive / global coverage

- Enumerate: recursive descent from the 20 faces (`build_compacted`), or
  per-face via the Worker's `/level/{N}` endpoint.
- Classification is **exact polygon containment, not point sampling**,
  in three frames: standard lon/lat; an extended frame with land copies
  translated ±360° for antimeridian-crossing cells; and polar
  azimuthal-equidistant frames for cells containing or near the poles.
- **Gotchas (all handled, but consumers should know):** cells crossing
  ±180° are exported with *continuous* longitudes (e.g. 176→184) and
  flagged `xam: true` — a deliberate deviation from RFC 7946 §3.1.9 that
  preserves triangle semantics and renders correctly in MapLibre/deck.gl;
  re-split if a strict-RFC consumer requires it. Pole-touching cells are
  meridian wedges reaching exactly ±90°, flagged `pole: "vertex"`;
  Mercator clips them at ±85° (use globe view). Polygon-fill
  (`polyfill`-equivalent) is on the roadmap, not yet implemented.

### 6. Comparison

| Property | **T3** | A5 | H3 | S2 | rHEALPix | HTM/QTM |
|---|---|---|---|---|---|---|
| Base solid | Icosahedron | Dodecahedron | Icosahedron | Cube | Cube (HEALPix) | Octahedron |
| Cell shape | Triangle | Pentagon | Hexagon (+12 pentagons) | Quadrilateral | Quad (+caps/darts) | Triangle |
| Aperture | **4, exact** | 4 (logical only) | 7 (approximate) | 4, exact | 9, exact | 4, exact |
| Equal area | *~±20%, smooth* | **exact per level** | ~2× max/min | up to ~2× | near-exact | larger deformation (octahedron) |
| Edge neighbors | 3 (+9 vertex) | 5 | **6 uniform** | 4 | 4 | 3 (+vertex) |
| Index | uint64, prefix=subtree | uint64, Hilbert | uint64 | uint64, Hilbert | string | quadtree string/int |
| Ecosystem | this repo (2026) | young (2025), growing | **huge** | huge | niche/OGC | niche/astronomy |
| Best at | lossless hierarchy, simplicial/FEM, multi-res coverage | density statistics | neighbor ops, analytics | indexing, range queries | equal-area statistics | astronomy heritage |

**T3 vs HTM/QTM specifically**: T3 is essentially "HTM on an icosahedron
with modern addressing and web tooling." The icosahedron's smaller faces
roughly halve worst-case shape/area deformation versus HTM's octahedron
(whose faces span 90° arcs); the demo includes an authentic HTM layer so
the difference is visible rather than asserted.

**T3 vs A5**: mirror images. T3 has exact geometry and approximate areas;
A5 has exact areas and approximate (logical) geometry. Same 64-bit
indexing philosophy. Pick by which invariant your application cannot
tolerate breaking.

### 7. Status and limitations

Single-repo, single-author project (first release 2026, v0.1.0), no
independent benchmark yet, neighbor traversal across face boundaries not
implemented, equal-area variant (Snyder/ISEA-style projection per face)
on the roadmap. Core area preservation and point location are covered by
`tests/test_core.py`; published land-coverage figures come from generated
build outputs, not independent third-party validation. Treat T3 as
**research/demonstration grade**: suitable for analysis pipelines and
teaching today, not yet for production systems that need the routine
breadth of H3 or S2.

## Recommendations

1. **Adopt T3 when exact hierarchical aggregation is the binding
   constraint** — multi-resolution statistics, conservative regridding,
   simplicial/FEM-adjacent pipelines — and pair it with H3 when the same
   project also needs heavy neighbor traversal.
2. **Use `addr64` as the storage key** (8 bytes, sortable; use
   `descendant_range` for subtree scans); show `compact` in UIs and reserve
   `path` for documentation.
3. **Serve small extents from the Worker, large extents from PMTiles**;
   embed TopoJSON only below ~30k cells.
4. **Thresholds that would change this assessment**: an implemented
   neighbor API plus a polyfill routine would move T3 from
   "research-grade" to "usable alternative"; an ISEA-style equal-area
   variant would collapse its main disadvantage versus A5/rHEALPix.

## Caveats

- All per-level edge/area figures are *means*; per-cell exact values are
  in the exported `edge_km` / `area_km2` properties.
- The ±20% area-variation figure is the global spread at a fixed level,
  computed from the build outputs; it is smooth (no discontinuities), but
  it is **not** equal-area — do not use raw cell counts as density
  estimates without area-weighting.
- The comparison layers in the demo use each system's *own* official or
  faithful implementation (pya5, h3-py, s2sphere, rhealpixdggs, and an
  octahedral HTM built with T3's machinery), at the closest available
  cell sizes — exact size parity across different apertures is
  impossible, so per-system base resolutions differ by up to ~3×.
