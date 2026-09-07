# data/

Generated grid products live here and are **not committed** (see root
`.gitignore`) except small samples.

Regenerate everything. `build_grids.py` automatically downloads the pinned
Natural Earth v5.1.2 land GeoJSON if the default path is missing:

```bash
python scripts/build_grids.py --levels 4 5 6      # trigrid products (required before PMTiles)
python scripts/build_comparison_dggs.py           # H3 / cube / rect layers
python scripts/build_a5_layer.py                  # A5 pentagon layer
python scripts/build_more_dggs.py                 # S2 / rHEALPix / HTM layers
bash   scripts/make_pmtiles.sh                    # PMTiles for all global_tri_L* in data/ + docs/data/
#      scripts/make_pmtiles.sh --levels 6 --force  # restrict levels (N, N-M, N-, -M); --force rebuilds existing
python scripts/make_site.py                       # prefers matching PMTiles, embeds fallbacks
```

| file pattern | contents |
|---|---|
| `global_tri_L{n}_{mode}.{geo,topo}json` | triangular grid, base level *n*, `compacted` or `uncompacted` |
| `cmp_{h3,a5,s2,rhealpix,htm,cubequad,rectquad}_{mode}.*`   | comparison DGGS layers |
| `*.pmtiles` | single-file vector tile archives (after `make_pmtiles.sh`) |

`make_site.py` checks for a PMTiles file matching each TopoJSON dataset.
Matches are copied to `docs/data/` and used by the viewer; unmatched
datasets remain embedded as compressed TopoJSON.

The separately packaged `settlementcheck/data/*.tfdg` artifact is generated
from the checksum-pinned GHS-WUP-DEGURBA source raster, not from these Natural
Earth grid products. Its provenance, source URL, verified nodata value and
license are recorded in `settlementcheck/data/manifest.json`; rebuild it with
`settlementcheck/build.py`.
