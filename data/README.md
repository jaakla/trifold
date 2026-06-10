# data/

Generated grid products live here and are **not committed** (see root
`.gitignore`) except small samples.

Regenerate everything:

```bash
# land source (sparse clone, ~30 MB)
git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/nvkelso/natural-earth-vector.git
cd natural-earth-vector && git sparse-checkout set --skip-checks \
    geojson/ne_50m_land.geojson && cd ..

python scripts/build_grids.py --levels 4 5 6      # trigrid products
python scripts/build_comparison_dggs.py           # H3 / cube / rect layers
python scripts/build_a5_layer.py                  # A5 pentagon layer
python scripts/build_more_dggs.py                 # S2 / rHEALPix / HTM layers
python scripts/make_site.py                       # docs/index.html landing+demo
bash   scripts/make_pmtiles.sh                    # optional: vector tiles
```

| file pattern | contents |
|---|---|
| `global_tri_L{n}_{mode}.{geo,topo}json` | triangular grid, base level *n*, `compacted` or `uncompacted` |
| `cmp_{h3,a5,s2,rhealpix,htm,cubequad,rectquad}_{mode}.*`   | comparison DGGS layers |
| `*.pmtiles` | single-file vector tile archives (after `make_pmtiles.sh`) |
