# Polyfill benchmark: T3 vs S2

Target area accuracy (shape/cover) >= 0.95 (intersects mode); per-shape level auto-picked; median of 3 runs. S2 cells are bit-identical to s2sphere; bbox/circle covers cross-checked against s2sphere's native coverer.

The `@0.95` columns interpolate each size metric at exactly the target accuracy (log-linear between bracketing levels), removing the level-quantization artifact; `~` marks extrapolation past the level cap. `cells` = full fixed-level cover, `compacted` = after folding complete sibling sets, `ranges` = merged index intervals (SQL scan cost) over each grid's canonical key (T3 addr64 via `cover_ranges`, S2 cellid), `hranges` = intervals over the Hilbert key (T3 `rhombus64` via `hilbert_ranges`; identical to `ranges` for S2, whose canonical key is already Hilbert-ordered).

| family | shape | sys | level | acc | cells | compacted | ms | cells/s | cells@0.95 | compacted@0.95 | ranges@0.95 | hranges@0.95 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bbox | city ~25km | T3 | 14 | 0.96 | 5337 | 396 | 75.81 | 70398 | 3789 | 331 | 331 | 55 |
| bbox | city ~25km | S2 | 15 | 0.98 | 7973 | 320 | 83.01 | 96047 | 2173 | 167 | 55 | 55 |
| bbox | metro ~120km | T3 | 12 | 0.97 | 8715 | 495 | 106.12 | 82122 | 3597 | 312 | 312 | 59 |
| bbox | metro ~120km | S2 | 12 | 0.96 | 3343 | 238 | 34.69 | 96366 | 2081 | 176 | 47 | 47 |
| bbox | region ~600km | T3 | 9 | 0.96 | 4682 | 368 | 66.34 | 70581 | 3697 | 325 | 325 | 59 |
| bbox | region ~600km | S2 | 10 | 0.97 | 6932 | 275 | 69.82 | 99280 | 1859 | 151 | 45 | 45 |
| circle | r=2km | T3 | 16 | 0.94 | 2292 | 234 | 257.76 | 8892 | ~2657 | ~250 | ~250 | ~43 |
| circle | r=2km | S2 | 16 | 0.92 | 950 | 131 | 23.26 | 40836 | ~1759 | ~201 | ~38 | ~38 |
| circle | r=20km | T3 | 13 | 0.96 | 3531 | 324 | 389.08 | 9075 | 2810 | 280 | 280 | 46 |
| circle | r=20km | S2 | 14 | 0.97 | 5658 | 315 | 133.95 | 42239 | 2089 | 193 | 49 | 49 |
| circle | r=150km | T3 | 10 | 0.96 | 3098 | 248 | 347.59 | 8913 | 2570 | 228 | 228 | 46 |
| circle | r=150km | S2 | 11 | 0.97 | 4997 | 317 | 117.73 | 42446 | 2489 | 221 | 60 | 60 |
| random | rand 0.3deg | T3 | 14 | 0.97 | 9578 | 599 | 370.31 | 25865 | 3746 | 354 | 354 | 59 |
| random | rand 0.3deg | S2 | 14 | 0.95 | 3317 | 293 | 65.32 | 50779 | 3054 | 280 | 82 | 82 |
| random | rand 1.2deg | T3 | 12 | 0.96 | 12991 | 925 | 473.24 | 27451 | 9549 | 763 | 763 | 148 |
| random | rand 1.2deg | S2 | 12 | 0.95 | 4825 | 400 | 93.58 | 51558 | 4343 | 382 | 103 | 103 |
| random | rand 4.0deg | T3 | 10 | 0.97 | 8260 | 598 | 518.39 | 15934 | 3186 | 352 | 352 | 55 |
| random | rand 4.0deg | S2 | 11 | 0.98 | 9078 | 600 | 268.05 | 33867 | 3339 | 347 | 101 | 101 |
| admin | Luxembourg | T3 | 13 | 0.95 | 7190 | 647 | 2989.98 | 2405 | 6785 | 624 | 624 | 116 |
| admin | Luxembourg | S2 | 13 | 0.93 | 2741 | 302 | 159.59 | 17176 | ~4188 | ~385 | ~103 | ~103 |
| admin | Belgium | T3 | 12 | 0.97 | 21971 | 1226 | 22880.18 | 960 | 9800 | 763 | 763 | 134 |
| admin | Belgium | S2 | 12 | 0.95 | 8305 | 625 | 1517.80 | 5472 | 6990 | 567 | 160 | 160 |
| admin | Switzerland | T3 | 12 | 0.97 | 28310 | 1550 | 15543.11 | 1821 | 11335 | 883 | 883 | 177 |
| admin | Switzerland | S2 | 12 | 0.96 | 11246 | 872 | 789.49 | 14245 | 8950 | 762 | 212 | 212 |
| admin | Estonia | T3 | 11 | 0.97 | 10529 | 605 | 3332.67 | 3159 | 5039 | 413 | 413 | 85 |
| admin | Estonia | S2 | 12 | 0.97 | 12426 | 651 | 596.09 | 20846 | 4237 | 359 | 96 | 96 |

## Issue #11: polyfill hot-path rewrite — before/after

The T3 timings above are with the scalar fast path (`src/trifold/cover.py`,
issue #11). Before/after (same machine, Apple M5 Pro, median of 3, identical
cell outputs — verified over a 192-case corpus incl. antimeridian, polar and
admin shapes):

| shape | before ms | after ms | speedup | after cells/s |
|---|---:|---:|---:|---:|
| bbox city L14 | 484.95 | 49.32 | 9.8x | 108,211 |
| bbox metro L12 | 707.90 | 78.99 | 9.0x | 110,336 |
| bbox region L9 | 436.95 | 47.77 | 9.1x | 98,016 |
| circle r=2km L16 | 1,575.13 | 183.30 | 8.6x | 12,504 |
| circle r=20km L13 | 2,396.96 | 271.72 | 8.8x | 12,995 |
| circle r=150km L10 | 2,146.44 | 240.89 | 8.9x | 12,860 |
| random 0.3deg L14 | 2,403.77 | 259.82 | 9.3x | 36,864 |
| random 1.2deg L12 | 3,072.54 | 329.97 | 9.3x | 39,370 |
| random 4.0deg L10 | 3,366.54 | 354.77 | 9.5x | 23,283 |
| admin Luxembourg L13 | 19,215.34 | 2,214.44 | 8.7x | 3,247 |
| admin Belgium L12 | 81,274.36 | 14,326.57 | 5.7x | 1,534 |
| admin Switzerland L12 | 100,615.20 | 9,396.92 | 10.7x | 3,013 |
| admin Estonia L11 | 20,710.46 | 2,101.14 | 9.9x | 5,011 |

Root cause was numpy per-call overhead on 3-vectors (~42% of runtime in
argument plumbing alone); the covering logic itself was ~5%. The rewrite
replaces the per-node geometry with pure-scalar mirrors performing the same
IEEE-754 operations, private to `cover.py`; `trifold.core` is untouched.
