#!/usr/bin/env bash
# Convert grid GeoJSON to PMTiles for serverless vector-tile serving.
#
# Requires: tippecanoe >= 2.17 (https://github.com/felt/tippecanoe)
#   macOS:  brew install tippecanoe
#   Linux:  build from source, or use the docker image
#
# PMTiles = single-file tile archive, served as static HTTP range requests.
# Archives are built in data/ and copied to docs/data/ for GitHub Pages.
# The viewer loads them with the PMTiles JS protocol:
# https://github.com/protomaps/PMTiles
#
# Usage:
#   make_pmtiles.sh [--levels RANGE] [--force]
#
#   --levels, -l RANGE   Restrict to a level range. Accepts:
#                          N      single level (e.g. 7)
#                          N-M    inclusive range (e.g. 4-8)
#                          N-     N and up
#                          -M     up to and including M
#                        Default: all levels found in data/.
#   --force, -f          Rebuild archives even if the .pmtiles already exists.
#                        Default: skip grids whose .pmtiles is already present.
#   --help, -h           Show this help.
#
# All data/global_tri_L<level>_*.geojson products are discovered automatically;
# nothing is hardcoded. Run scripts/build_grids.py first to generate inputs.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$ROOT_DIR/data"
DOCS_DATA_DIR="$ROOT_DIR/docs/data"

FORCE=0
LEVEL_MIN=0
LEVEL_MAX=999

usage() {
  sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
}

parse_levels() {
  # Accepts N, N-M, N-, or -M and sets LEVEL_MIN / LEVEL_MAX.
  local spec="$1"
  if [[ "$spec" =~ ^([0-9]+)$ ]]; then
    LEVEL_MIN="${BASH_REMATCH[1]}"; LEVEL_MAX="${BASH_REMATCH[1]}"
  elif [[ "$spec" =~ ^([0-9]+)-([0-9]+)$ ]]; then
    LEVEL_MIN="${BASH_REMATCH[1]}"; LEVEL_MAX="${BASH_REMATCH[2]}"
  elif [[ "$spec" =~ ^([0-9]+)-$ ]]; then
    LEVEL_MIN="${BASH_REMATCH[1]}"
  elif [[ "$spec" =~ ^-([0-9]+)$ ]]; then
    LEVEL_MAX="${BASH_REMATCH[1]}"
  else
    echo "error: invalid --levels value '$spec' (expected N, N-M, N-, or -M)" >&2
    exit 1
  fi
  if ((LEVEL_MIN > LEVEL_MAX)); then
    echo "error: --levels min ($LEVEL_MIN) is greater than max ($LEVEL_MAX)" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--force) FORCE=1; shift;;
    -l|--levels)
      [[ $# -ge 2 ]] || { echo "error: $1 requires a value" >&2; exit 1; }
      parse_levels "$2"; shift 2;;
    --levels=*) parse_levels "${1#*=}"; shift;;
    -h|--help) usage; exit 0;;
    *) echo "error: unknown argument '$1'" >&2; usage; exit 1;;
  esac
done

if ! command -v tippecanoe >/dev/null 2>&1; then
  cat >&2 <<'ERROR'
error: tippecanoe is not installed or is not on PATH.

macOS: brew install tippecanoe
Linux: https://github.com/felt/tippecanoe#installation
ERROR
  exit 1
fi

# Discover every triangle-grid product, then keep those within the level range.
shopt -s nullglob
GRIDS=()
for f in "$DATA_DIR"/global_tri_L*_*.geojson; do
  base="$(basename "${f%.geojson}")"
  [[ "$base" =~ ^global_tri_L([0-9]+)_ ]] || continue
  level="${BASH_REMATCH[1]}"
  ((10#$level >= LEVEL_MIN && 10#$level <= LEVEL_MAX)) || continue
  GRIDS+=("$base")
done
shopt -u nullglob

if ((${#GRIDS[@]} == 0)); then
  printf 'error: no data/global_tri_L*_*.geojson inputs matched' >&2
  if ((LEVEL_MIN > 0 || LEVEL_MAX < 999)); then
    printf ' for levels %s-%s' "$LEVEL_MIN" "$LEVEL_MAX" >&2
  fi
  printf '.\n' >&2
  cat >&2 <<'ERROR'

Generate inputs first:
  python scripts/build_grids.py --levels 6

The grid builder downloads the pinned Natural Earth input automatically.
ERROR
  exit 1
fi

cd "$DATA_DIR"
mkdir -p "$DOCS_DATA_DIR"

built=0 skipped=0
for f in "${GRIDS[@]}"; do
  if ((FORCE == 0)) && [[ -f "${f}.pmtiles" ]]; then
    echo "skip data/${f}.pmtiles (exists; pass --force to rebuild)"
    ((skipped++)) || true
    continue
  fi
  tippecanoe -o "${f}.pmtiles" \
    --layer=cells \
    --minimum-zoom=0 --maximum-zoom=8 \
    --no-tile-size-limit \
    --detect-shared-borders \
    --coalesce-densest-as-needed \
    --no-progress-indicator \
    --force \
    "${f}.geojson"
  cp "${f}.pmtiles" "$DOCS_DATA_DIR/${f}.pmtiles"
  echo "wrote data/${f}.pmtiles and docs/data/${f}.pmtiles"
  ((built++)) || true
done

echo "done: ${built} built, ${skipped} skipped (of ${#GRIDS[@]} matched)"

cat <<'NOTE'
Viewer usage (replace the embedded-TopoJSON source):

  <script src="https://unpkg.com/pmtiles@3/dist/pmtiles.js"></script>
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', protocol.tile);
  map.addSource('grid', {
    type: 'vector',
    url: 'pmtiles://https://YOUR_HOST/data/global_tri_L6_compacted.pmtiles'
  });
  map.addLayer({ id:'grid-fill', type:'fill', source:'grid',
                 'source-layer':'cells', paint:{...} });

For deeper levels (L7 ≈ 55 km: ~110k land cells, L8 ≈ 28 km: ~440k),
generate with scripts/build_grids.py --levels 7 and tile the result;
PMTiles handles millions of features without a tile server.
NOTE
