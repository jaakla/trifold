"""Emit the full global T3 grid at a given level as GeoJSON.

Every level-L cell (20 faces x 4**L) becomes a Feature whose properties
include rhombus_hilbert. Not land-clipped -- this is the whole sphere.

Usage:  python scripts/global_grid_geojson.py [LEVEL] [OUT.geojson]
"""
import json
import sys
from itertools import product

from trifold import cell_feature, encode64


def main():
    level = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    out = sys.argv[2] if len(sys.argv) > 2 else f"t3_L{level}_global.geojson"

    features = []
    for face in range(20):
        for digits in product(range(4), repeat=level):
            features.append(cell_feature(encode64(face, digits)))

    with open(out, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)
    print(f"wrote {len(features)} cells (level {level}) -> {out}")


if __name__ == "__main__":
    main()
