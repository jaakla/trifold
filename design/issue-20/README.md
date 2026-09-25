# Issue #20 — design review checkpoint

Status: implemented on `feature/docs-unification-20` after renewed user approval.
Equal Earth is deferred by explicit user decision. MapLibre and CARTO light
vectors remain; no second renderer or paid Mapbox dependency was added.

## Concepts

- `map-workspace.png`: canonical common map toolbar, geographic inputs, layers,
  inspector and document navigation.
- `overview.png`: overview, library discovery and code/documentation layout.
- `api-reference.png`: API semantics, tables, loading and source information.
- `mobile.png`: portrait demo and global menu.

Generated with the built-in image tool for layout review, not as production UI.
Map graphics are illustrative and must be replaced by the real renderer/data.
The exact verified documentation sources govern API names and scientific copy;
minor generated text defects are not an instruction to reproduce them. In
particular the core is a T3 L12 transfer, not an S2 grid or a 1 km triangle grid.

Proposed common tokens: white content, charcoal text, cool gray rules, restrained
rust accent, system sans-serif and monospace code, consistent control sizing.
The workspace concept is the canonical header/sidebar treatment; use that same
shell on all pages rather than reproducing minor variations between concepts.
Specialized tools live in an expandable tools area using the same controls.

## Capability inventory to preserve during extraction

| Surface | Shared foundation | Adapter-specific demonstrators |
|---|---|---|
| Trifold comparison | Projection, camera, layer controls, coordinate inspection, selected cell/result | Seven grid systems, address/level choices, existing comparison overlays |
| Trifold coverage | Same map controls/selection/status framework | Bbox/polygon drawing, T3/S2 comparison, level, intersects/centroid, full/compacted/range output, compact/addr64 encoding |
| landcheck | Same controls; bounded point files/samples, result display | Land/sea/coast results, optional OSM refinement/source layer, route drawing/import/presets and sampling steps |
| countrycheck | Same controls; bounded point files/samples, result display | Country results, optional border refinement/source layer, route drawing/import/presets and sampling steps |
| settlementcheck | Same controls; add bounded point-file/sample workflow using existing lookup APIs | DEGURBA colors/results, class-only default, explicit lazy boundary details, retry, 6,500-cell cap |

Existing 1k/10k/100k point benchmarking actions remain specialized opt-in tools;
they must not be invoked by smoke tests or imply rendering unlimited polygons.
Unknown boundary details remain unknown, and scientific shares are not relabelled.

## Equal Earth feasibility finding (historical; requirement now deferred)

The pinned MapLibre 5.6.x projection factory supports Mercator, globe and vertical
perspective, not Equal Earth. An unrecognized name falls back to Mercator:
https://github.com/maplibre/maplibre-gl-js/blob/v5.6.2/src/geo/projection/projection_factory.ts

A temporary, bounded Playwright proof of concept used OpenLayers 10.10.0 and
proj4 2.20.9 for EPSG:8857 with the existing CARTO light raster URL. One map,
one known point, no library artifact or global L12 overlay was loaded.

- 26 tile requests completed; zero tile failures and zero page errors.
- Seven forward/inverse samples (Tallinn, London, equator, both antimeridian
  sides and ±85°) had maximum round-trip error below 3.4e-9 degrees.
- Equal Earth → Mercator → Equal Earth switching and Tallinn point picking
  passed. Picked longitude/latitude: 24.753599999999988, 59.43699999888089.
- Screenshots inspected: reprojected CARTO map and marker render, but raster
  labels visibly warp; world-edge clipping needs further work. This is a
  feasibility result, not acceptance of a production projection implementation.
- Browser plugin absent; existing Playwright Chromium used as fallback.

Earlier option considered: MapLibre for Globe/Mercator and an on-demand
OpenLayers backend for Equal Earth behind one controller/UI. It adds a second
renderer and requires coordinated layer/picking adapters, lifecycle cleanup,
seam handling and further QA. Do not eagerly load it on all pages. Retaining
the existing CARTO raster means accepting raster-label distortion in Equal Earth;
a label-friendly alternative basemap would require a separately agreed choice.
OpenLayers is BSD-2-Clause. Confirm and retain all dependency notices when pinning.

## Baseline and remaining work

Current generated HTML bytes: index 11,317,815; landcheck 292,756; countrycheck
483,034; settlementcheck 17,336. These include different embedded datasets and
are not like-for-like UI bundle sizes.

Implemented: shared shell/assets, extracted map controller and adapters,
generated API/reference pages, preserved links/features, and bounded
functional/accessibility and concept-to-render QA. No merge or production
deployment is authorized by this change.

## Implementation design system

- White `#fff` surfaces, charcoal `#202630`, cool gray `#dce1e7` rules,
  rust `#b83f25` for navigation/actions, system sans-serif and monospace code.
- 60px shared header, persistent product rail, content gutter, separate section
  navigation, 5–6px controls/panels, no screenshot-based interactive UI.
- All six product destinations remain available on mobile. Menu supports
  keyboard focus, Tab cycling, Escape and focus return; section navigation
  uses real anchors and a small-screen disclosure.
- Page/toolbar copy follows the workspace concept and authored documentation.
  The code examples use the real SDK/package contract, not generated concept
  text. Settlement installation is repository-local because it is unpublished.
- Scientific palettes and source semantics are independent of the rust accent.
  CARTO vector labels are ordered above analytical overlays.

## Visual fidelity ledger

Reviewed the concepts and browser PNGs with `view_image`, including the native
1505×1045 desktop size and 390×844 mobile. Also checked 1024px and 320px widths.
The implemented shared visual system was verified against the concept set;
the following deliberate production adaptations are not pixel-identical mocks.

| Comparison point | Concept / rendered evidence | Fix or intentional adaptation |
|---|---|---|
| Shell hierarchy | `map-workspace.png`, `implemented-workspace.png` | Same header, product rail, active rust rule, compact page title; narrower rail makes room for existing tools. |
| Typography and palette | Workspace/API concepts and rendered pages | Removed settlement's serif/green system and old cream backgrounds; explicitly styled controls, labels, code and tables. |
| Map/control ownership | Workspace/mobile concepts, real-data workspace | Shared toolbar/inspector rather than floating independent panels. Rich tools use a disclosure; analytical layers and result fields remain library-specific. |
| Basemap and imagery | Illustrative concept vs real CARTO/T3 render | Real CARTO vectors replace illustrative geography. No concept image ships as UI. Equal Earth is omitted by user instruction. |
| Responsive reading flow | `mobile.png`, `implemented-mobile.png` | Global and local menus retain all links; map and inspector stack. Fixed main-page address-diagram overflow and an exposed navigation placeholder found during visual QA. |
| Content and code | `overview.png`, `api-reference.png`, generated overview/reference | Preserved scientific copy and section anchors; moved lengthy demo explanation below the workspace. Corrected package names and unpublished install commands. |
| Selection semantics | Real-data workspace inspector | Full current result fields, unknown details explicit, no inferred population or homogeneity; taller inspector scrolls independently on desktop. |

Above-the-fold copy audit: the brand/product names, settlement purpose,
Quickstart/Demo/API/Data/Sources, projection/reset, coordinates, presets,
copy/clear and layers derive from the concepts or issue requirements. Additional
local links expose retained authored sections; the point-dataset control is
required by #20. No fabricated metrics, scientific labels or decorative badges.
The old promotional map screenshot was removed from the overview so it does not
advertise a different control design. The actual richer demos remain intact.

## Validation and evidence

- 112 Python tests pass; 22 land/country JS tests pass; settlement JS fixture and
  bundled-release tests pass; six isolated shared-controller tests pass.
- The six-page sequential browser suite passes: identity/content, runtime errors,
  coordinate validation, copy/result/clear, presets, projection URL changes,
  upload/sample/clear, route input, refinement failure/retry, coverage variants,
  lazy settlement details and retry, antimeridian selection, and mobile menus.
- Browser plugin unavailable; existing Playwright Chromium used as fallback.
- Heavy overlay tests are intentionally excluded. The browser contract suite uses
  tiny explicit UI fixtures. A separate real-core smoke check at city-block zoom
  rendered 15 real settlement cells, classified Tallinn as urban centre, and
  fetched zero detail shards, with zero page errors.
- Canonical regeneration is deterministic; internal links and prior section
  anchors pass static checks. Scientific binary artifacts and SDKs are unchanged.
- `implemented-workspace.png` and `implemented-mobile.png` show the real
  settlement core at a bounded city-block view, not synthetic fixture results.
  Other browser screenshots are temporary test evidence, not deployed assets.

Remaining limitations: Equal Earth is parked; no full-world L12 stress test or
100k browser benchmark was run. Hosted comparison PMTiles restrict CORS to the
production origin (verified read-only); local QA uses a one-cell fixture for
those overlays. Firefox/WebKit are not part of this bounded Chromium check.
