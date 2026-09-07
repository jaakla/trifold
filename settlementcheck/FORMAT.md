# TFDG v1 (work in progress)

The WIP v1 layout now separates class lookup from boundary detail delivery.
The previous experimental monolithic v1 layout is obsolete and rejected by
its flags, rather than silently decoded as the new layout. No version 2 is
introduced. Rebuild experimental files with the current builder.

## Containers

All integers are little-endian. The first 60 bytes use
`<4sBBBBHBBIIII32s`:

| Offset | Field |
|---:|---|
| 0 | Magic: `TFDG` (core) or `TFDD` (detail shard) |
| 4 | Version: 1 |
| 5 | T3 level: 1..13 |
| 6 | Flags: exactly 3 for class-only full-coverage core; exactly 1 for details |
| 7 | Zero for core; face number 0..19 for details |
| 8 | Epoch, uint16: 2025 |
| 10 | Release: 1 (R2025A) |
| 11 | Source resolution in tenths of km: 10 |
| 12 | Number of class runs / mixed intervals, uint32 |
| 16 | Global / face mixed-cell count, uint32 |
| 20 | Global cell count: 20 × 4^level, uint32 |
| 24 | Sum of decoded section bytes, uint32 |
| 28 | Source-raster SHA-256, 32 bytes |
| 60 | Build identity SHA-256, 32 bytes |
| 92 | Section directory: (compressed bytes, decoded bytes), uint32 pairs |

The directory has two entries for core and four for details. Independent
zlib streams immediately follow the directory in that order. Empty sections
are valid zlib-compressed empty strings. Decoded total size is limited to
256 MiB. Unknown flags, incomplete coverage, invalid counts/slots/intervals,
truncated or oversized streams, trailing bytes and nonzero bit padding are
rejected. Runtime metadata currently accepts only the pinned 2025 release.

The shared build identity hashes, in order: raster SHA bytes, level byte,
core length stream, core slot stream, original mixed-run starts and ends as
little-endian uint32 arrays, and the original interleaved share/flag bytes.
This binds class and detail outputs from one deterministic build, including
boundary values. It is not a signature: distribution integrity checksums are
also published in the manifests. Any future format change must update this
document and fixtures together while this version is under development.

## Core (.tfdg)

1. Positive run lengths, unsigned LEB128 (at most five bytes, uint32).
2. One byte per run: slot in `[10,11,12,13,21,22,23,30,255]`. Slot 8 is nodata.

Runs cover every canonical index from zero without gaps. Adjacent equal
classes merge regardless of boundary status. Readers retain uint32 run ends
and one-byte codes; they do not allocate a global mixed-cell index.

## Details (.details/face-NN.tfdd)

1. Sparse mixed intervals as alternating unsigned LEB128 `(gap, length)`.
   Gap is relative to the preceding end, initially zero within this face.
2. One uint8 dominant share per mixed cell, divided by 255 at lookup.
3. Water/non-water mixture bits, most-significant bit first.
4. Valid/nodata mixture bits, most-significant bit first.

The final two streams have `ceil(mixed_count/8)` bytes; unused trailing bits
are zero. Intervals merge across adjacent mixed cells even when their dominant
classes differ. Share/bit order follows ascending mixed-cell index. Local
indexes range from zero through `4^level-1`. Missing intervals mean homogeneous
**only after this complete, matching face shard has loaded**.

The core file and its sibling `.details` directory are separate distribution
units. Python wheels, sdists and the npm core package omit detail files; the
repository and generated demo host them for explicit download. A custom
loader can use another application-controlled source. Default Python loading
is local-only; URL-based JS loading requests the corresponding sibling shard.

## API and caching

- `class_code`/`classCode`, `settlement`, `is_urban`/`isUrban`, and
  `settlement_batch`/`settlementBatch` never load boundary data.
- `classify` returns class/provenance with `details_loaded=false` /
  `detailsLoaded=false`. Unknown boundary booleans, share, and surface are
  null; dominant nodata still returns `surface="unknown"`.
- Python `check` lazily reads the matching local shard or calls the configured
  `details_loader(face)`. Missing details raise `DetailsNotLoadedError`.
- JS `await checkAsync` loads lazily. Synchronous `check` requires the face to
  be cached, otherwise it raises `DetailsNotLoadedError`. `await loadDetails`
  preloads one face explicitly; `checkBatchAsync` groups work by face.
- Default cache size is two faces, configurable in 1..20. Failed loads do not
  poison the cache. JS deduplicates in-flight same-face requests. Explicit
  `unload_details`/`unloadDetails` releases cached shards.

Code-only methods work even when every optional details request fails. The
demo retains its 6,500-triangle rendering limit independently of data size.
