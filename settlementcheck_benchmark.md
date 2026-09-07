# settlementcheck build, accuracy and runtime benchmark

## Approved issue #18: class-only core and lazy details

The WIP format remains **version 1** as requested. Its old monolithic layout
is replaced, not supported as a published compatibility contract. See
[FORMAT.md](settlementcheck/FORMAT.md) for the exact section and shard layout.

The source remains GHS-WUP-DEGURBA R2025A epoch 2025, SHA-256
`7dda69a104a5eaef6b5ac6038fcc00ca00122218c759ab34e95d338721d64a18`.
The corrected global L12 build took 979.699 seconds with two workers,
visiting 41,316,372 nodes. L12 has 335,544,320 cells, mean area approximately
1.52 km², close to the source's 1 km pixel support. L13 is deferred; L14
exceeds this format's uint32 global-index range.

| Delivery | Bytes |
|---|---:|
| Previous monolithic artifact | 31,951,126 |
| New class-only core | 4,575,154 |
| Core plus all 20 optional detail shards | 23,307,781 |
| Smallest / largest detail shard | 1,232 / 3,851,584 |

The default download shrinks **85.7%**; complete data shrinks **27.1%**.
Totals exclude the small JSON manifest. Details retain 8-bit shares; no
4-bit quantization or lower-resolution substitution was introduced.
Core runs: 7,687,305. Corrected mixed cells: 16,024,557.
Core SHA-256:
`7e7ce23b14f94a50399862feec0605aaaaa29ec5feae34478d1c152f3d971454`.

Measured archives: wheel **4,588,538 bytes**, sdist **4,600,710 bytes**,
npm **4,589,760 bytes**. Python wheels/sdists and npm packages contain the core only. Boundary details
are optional sibling files, loaded per icosahedron face, with a two-face
LRU cache by default. Package archives are approximately 4.6 MB; exact sizes
depend on documentation and packaging metadata.

## Geometry corrections, separate from compression

A complete, chunked comparison of all 335,544,320 old/new cells found:

| Field | Changed cells |
|---|---:|
| Dominant class | 598 |
| Mixed flag | 617,771 |
| Nodata-mixed flag | 5,614,734 |
| Water-mixed flag | 56 |
| Quantized share byte | 2,266 |

Nodata-mixed counts fell from **5,625,179 to 11,685** after using stable
translated polygon areas and actual raster-rectangle clipping instead of
treating floating-point area residuals as nodata. Genuine nodata remains
represented. The near-pole Mollweide solve now converges and is checked
against PROJ. These are rebuilt geometry corrections, not lossy encoding.

Reproduce the comparison with an original monolithic artifact:

```console
python scripts/compare_settlementcheck_builds.py --original /path/to/original.tfdg --current settlementcheck/data/degurba_R2025A_E2025_L12.tfdg
python scripts/verify_settlementcheck_parity.py
```

The parity script hashes every decoded class interval and all 20 faces'
mixed intervals, shares and bitplanes in both readers, not just sampled
point results. Fixture tests also cover all fixture cells and sparse gaps.
Both readers produced decoded SHA-256
`10a537312df0b83d234c4042615022eba6e980a4296b4ac83b9379dc7bcfe080`.

## Spatial agreement

A repeated 100,000-point sphere-uniform sample (seed 2025) agreed with direct
source point reads on **98.831%** of points (previous build: 98.832%).

| Source class | support | precision | recall |
|---|---:|---:|---:|
| Water (10) | 71,242 | 99.874% | 99.850% |
| Very-low-density rural (11) | 26,715 | 97.995% | 98.604% |
| Low-density rural (12) | 1,165 | 67.910% | 62.489% |
| Rural cluster (13) | 150 | 66.087% | 50.667% |
| Suburban/peri-urban (21) | 461 | 73.696% | 73.536% |
| Semi-dense urban cluster (22) | 40 | 74.194% | 57.500% |
| Dense urban cluster (23) | 82 | 78.873% | 68.293% |
| Urban centre (30) | 131 | 90.769% | 90.076% |
| Nodata | 14 | 93.333% | 100.000% |

```console
python scripts/accuracy_settlementcheck.py --source /path/to/GHS_WUP_DEGURBA_E2025_GLOBE_R2025A_54009_1000_V1_0.tif -n 100000
```

This is area-weighted transfer agreement, not source-model accuracy.
Dominant water/rural classes mask substantially lower agreement for rare,
boundary-heavy classes; finer triangles would not improve source resolution.

## Reader performance

Measured on the development host, 100,000 points, September 2026:

| Runtime | Core load | Scalar classes/s | Batch classes/s | First London detail face | Warm detailed checks/s |
|---|---:|---:|---:|---:|---:|
| Python | 1.721 s | 30,746 | 169,725 | 0.260 s | 26,094 |
| Node | 0.404 s | 462,060 | — | 0.081 s | 322,549 |

Python peak RSS immediately after core loading was 74.93 MiB. Its process
peak after 100,000-point batch work was 172.94 MiB; Node's peak after scalar
work was 163.29 MiB. Loading one detail face did not exceed those previous
process peaks. These are process high-water marks, **not retained heap**;
the Python batch includes optional NumPy/trifold vectorized location arrays.

A smaller 10,000-point run isolated detail-loading overhead more clearly:
Python core-load peak 75.14 MiB, post-query peak 77.73 MiB, post-detail peak
85.11 MiB; Node core-query peak 130.53 MiB, post-detail peak 138.03 MiB.

Previous monolithic measurements were 9.11 s / 363 MiB for Python and
1.77 s / 606 MiB for Node. Those earlier runs are indicative comparisons,
not a controlled same-session benchmark. The provisional 20 µs Python /
2 µs Node scalar targets are still not met.

```console
python scripts/benchmark_settlementcheck.py -n 100000
node scripts/benchmark_settlementcheck.mjs 100000
node settlementcheck/tests/test_settlementcheck.mjs
```

## Browser safety and bounded QA

The demo retains its **6,500-cell cap** and does not attempt world-scale
L12 rendering. Ordinary class selection makes no detail requests.
Point details and boundary highlighting are explicit opt-ins; failed detail
requests preserve class results and allow retry.

Playwright/Chromium QA for this refactor uses a **130-byte L12 fixture**,
not the full release, at 1000×800 and 390×844. It checks initial core-only
loading, no detail request on ordinary selection, a failed detail request
and successful retry, returned share, boundary highlighting, and a wrapped
antimeridian click. There were no page errors. The release artifact is
validated separately in Python/Node. No new full-release browser readiness
or low-zoom stress timings are claimed: earlier user testing encountered
OOM, so heavy browser tests were deliberately avoided.
