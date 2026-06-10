#!/usr/bin/env bash
# Convert grid GeoJSON to PMTiles for serverless vector-tile serving.
#
# Requires: tippecanoe >= 2.17 (https://github.com/felt/tippecanoe)
#   macOS:  brew install tippecanoe
#   Linux:  build from source, or use the docker image
#
# PMTiles = single-file tile archive, served as static HTTP range requests
# (GitHub Pages won't do ranges reliably; use Cloudflare R2/Pages, S3, or
# any static host with Range support). The viewer loads it with the
# pmtiles JS protocol:  https://github.com/protomaps/PMTiles
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$ROOT_DIR/data"
GRIDS=(global_tri_L6_compacted global_tri_L6_uncompacted)

if ! command -v tippecanoe >/dev/null 2>&1; then
  cat >&2 <<'ERROR'
error: tippecanoe is not installed or is not on PATH.

macOS: brew install tippecanoe
Linux: https://github.com/felt/tippecanoe#installation
ERROR
  exit 1
fi

missing=()
for grid in "${GRIDS[@]}"; do
  [[ -f "$DATA_DIR/${grid}.geojson" ]] || missing+=("data/${grid}.geojson")
done

if ((${#missing[@]})); then
  printf 'error: required generated grid input(s) are missing:\n' >&2
  printf '  %s\n' "${missing[@]}" >&2
  cat >&2 <<'ERROR'

Generate them first:
  python scripts/build_grids.py --levels 6

The default build also requires Natural Earth land data at:
  natural-earth-vector/geojson/ne_50m_land.geojson

See data/README.md for the download commands.
ERROR
  exit 1
fi

cd "$DATA_DIR"

for f in "${GRIDS[@]}"; do
  tippecanoe -o "${f}.pmtiles" \
    --layer=cells \
    --minimum-zoom=0 --maximum-zoom=8 \
    --no-tile-size-limit \
    --detect-shared-borders \
    --coalesce-densest-as-needed \
    --force \
    "${f}.geojson"
  echo "wrote ${f}.pmtiles"
done

cat <<'NOTE'
Viewer usage (replace the embedded-TopoJSON source):

  <script src="https://unpkg.com/pmtiles@3/dist/pmtiles.js"></script>
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', protocol.tile);
  map.addSource('grid', {
    type: 'vector',
    url: 'pmtiles://https://YOUR_HOST/global_tri_L6_compacted.pmtiles'
  });
  map.addLayer({ id:'grid-fill', type:'fill', source:'grid',
                 'source-layer':'cells', paint:{...} });

For deeper levels (L7 ≈ 55 km: ~110k land cells, L8 ≈ 28 km: ~440k),
generate with scripts/build_grids.py --levels 7 and tile the result;
PMTiles handles millions of features without a tile server.
NOTE
