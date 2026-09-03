# settlementcheck build, accuracy and runtime benchmark

This record covers the GHS-WUP-DEGURBA R2025A epoch-2025 source raster
(`7dda69a…d64a18`) and the TFDG v1 transfer. Measurements were made
2026-09-03 on an 8-vCPU AMD EPYC Genoa host with 15 GiB RAM, Python 3.12,
NumPy 2.5.2 and Rasterio 1.5.1. Commands are included for repetition.

## Resolution spike

| T3 level | mean area | evidence | build result |
|---:|---:|---|---|
| L10 | 24.3 km² | global diagnostic traversal | 5,022,116 nodes; 2,419,480 conservative boundary candidates; 63.6 s / 4 workers |
| L12 | 1.52 km² | exact global transfer | 41,316,372 nodes; 16,640,960 true mixed cells; 511.1 s / 4 workers |
| L13 | 0.38 km² | L10→L12 boundary-scaling projection | deferred: materially larger transfer while source remains 1 km |
| L14 | 0.095 km² | boundary-scaling projection | rejected: far below source support and beyond TFDG v1's u32 base-index range |

L12 is selected because its mean area is closest to the equal-area 1 km
source pixel without presenting sub-source resolution as new information.
L13/L14 remain format-compatible future rebuild choices; the source—not the
T3 level—sets scientific resolution.

## Exact artifact

| metric | result |
|---|---:|
| Build wall time, 4 workers | 511.1 s |
| Nodes visited | 41,316,372 |
| Runs | 15,255,630 |
| Mixed cells | 16,640,960 (4.96% of L12 cells) |
| TFDG bytes | 31,951,126 (30.47 MiB) |
| Uncompressed payload | 94,398,452 bytes |
| Artifact SHA-256 | `a77651c2…8ad996a` |
| Encoding | all-class RLE |

All-class RLE was retained over implicit-water omission. The measured
implicit-water candidate was 31,906,032 bytes, only 45,094 bytes (0.14%)
smaller. That saving did not justify a default-class semantic and inability to
strictly detect incomplete coverage. Long water runs already compress well.

## Spatial agreement

The 100,000-point sphere-uniform sample agreed on **98.832%** of points.

| Source class | support | precision | recall |
|---|---:|---:|---:|
| Water (10) | 71,242 | 99.874% | 99.851% |
| Very-low-density rural (11) | 26,715 | 97.995% | 98.604% |
| Low-density rural (12) | 1,165 | 67.910% | 62.489% |
| Rural cluster (13) | 150 | 66.087% | 50.667% |
| Suburban/peri-urban (21) | 461 | 73.696% | 73.536% |
| Semi-dense urban cluster (22) | 40 | 74.194% | 57.500% |
| Dense urban cluster (23) | 82 | 78.873% | 68.293% |
| Urban centre (30) | 131 | 90.769% | 90.076% |
| Nodata | 14 | 100.000% | 100.000% |

Reproduce with:

```console
python scripts/accuracy_settlementcheck.py --source /path/to/GHS_WUP_DEGURBA_E2025_GLOBE_R2025A_54009_1000_V1_0.tif -n 100000
```

The sphere-uniform sample is area-weighted by construction. Per-class
precision/recall is reported so water and very-low-density rural cells cannot
hide errors in rarer settlement classes. This measures transfer agreement,
not accuracy of the source model.

## Reader performance

| runtime/path | load | peak RSS | throughput |
|---|---:|---:|---:|
| Python scalar | 9.11 s | 363 MiB | 31,608 queries/s |
| Python vectorized-location batch convenience | same load | same process | 106,336 points/s |
| Node scalar | 1.77 s | 606 MiB peak | 407,495 queries/s |

The provisional 20 µs Python / 2 µs Node targets were not met (31.6 µs and
2.45 µs respectively). Correct boundary semantics and a complete stream were
kept; reader-memory/run-index optimization is a follow-up opportunity.

Reproduce with:

```console
python scripts/benchmark_settlementcheck.py -n 100000
node scripts/benchmark_settlementcheck.mjs 100000
node settlementcheck/tests/test_settlementcheck.mjs
```

The browser preview separately displays current viewport cover/classification
time and enforces a 6,500-cell cap. That timing is diagnostic, never an
accuracy or scientific-quality measure.

Playwright/Chromium loaded and decoded the local page/data to an API-ready
state in 1.40 s at 1440×1000 and 1.29 s at 390×844. The initial Tallinn
viewport rendered 333 L12 cells in 66 ms on desktop and 101 cells in 46 ms on
mobile. The low-zoom cap, mixed-boundary toggle, point popup, and urban/water
presets were exercised. These localhost timings exclude network transfer.
