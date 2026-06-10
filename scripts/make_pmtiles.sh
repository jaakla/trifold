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
cd "$(dirname "$0")/../data"

for f in global_tri_L6_compacted global_tri_L6_uncompacted; do
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
