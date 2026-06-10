#!/usr/bin/env python
"""Build global land-adaptive grids (GeoJSON + TopoJSON) with full addressing.

Usage:  python scripts/build_grids.py [--levels 4 5 6] [--land PATH] [--out data/]
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trifold import (LandClassifier, build_compacted, expand_to_base,
                     cell_geometry_ring, edge_km, area_km2,
                     encode64, to_compact, to_path)
from trifold.address import from_path

DEFAULT_LAND = 'natural-earth-vector/geojson/ne_50m_land.geojson'
LAND_URL = ('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/'
            'v5.1.2/geojson/ne_50m_land.geojson')
LAND_SHA256 = 'e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b'


def download_land(path, url=LAND_URL, sha256=LAND_SHA256):
    """Download and validate the pinned Natural Earth land GeoJSON."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.ne_50m_land-', suffix='.geojson',
                               dir=parent)
    os.close(fd)
    try:
        print(f"land data not found; downloading Natural Earth v5.1.2\n  {url}")
        request = Request(url, headers={'User-Agent': 'trifold/0.1.0'})
        digest = hashlib.sha256()
        with urlopen(request, timeout=60) as response, open(tmp, 'wb') as out:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sha256:
            raise RuntimeError('Natural Earth download checksum mismatch')
        with open(tmp) as src:
            data = json.load(src)
        if data.get('type') != 'FeatureCollection' or not data.get('features'):
            raise RuntimeError('Natural Earth download is not a GeoJSON FeatureCollection')
        os.replace(tmp, path)
        print(f"downloaded {path} ({os.path.getsize(path) / 1e6:.1f} MB)")
    except (OSError, URLError, ValueError) as exc:
        raise RuntimeError(
            f"could not download Natural Earth land data: {exc}\n"
            f"Download {url} manually to {path}, or pass --land PATH.") from exc
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ensure_land(path, is_default):
    if os.path.isfile(path):
        return
    if is_default:
        download_land(path)
        return
    raise FileNotFoundError(
        f"land dataset not found: {path}\n"
        f"Omit --land to download Natural Earth automatically, or pass an existing file.")


def cells_to_features(cells):
    feats = []
    for c in cells:
        # cell ids from the gridder are 'F{face:02d}-{digits}' path strings
        addr = from_path(c['cell_id'])
        ring, pole_flag = cell_geometry_ring(c)
        lons = [p[0] for p in ring]
        coords = [[round(x, 5), round(y, 5)] for x, y in ring]
        coords.append(coords[0])
        feats.append({
            'type': 'Feature',
            'properties': {
                'id': to_compact(addr),            # primary key (compact b32)
                'path': to_path(addr),             # teaching form
                'addr64': str(addr),               # uint64 (string: JSON-safe)
                'level': c['level'],
                'interior': bool(c['interior']),
                'edge_km': round(edge_km(c['tri']), 1),
                'area_km2': round(area_km2(c['tri']), 0),
                'pole': pole_flag,
                'xam': bool(max(lons) > 180 or min(lons) < -180),
            },
            'geometry': {'type': 'Polygon', 'coordinates': [coords]},
        })
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--levels', type=int, nargs='+', default=[4, 5, 6])
    ap.add_argument('--land', default=DEFAULT_LAND)
    ap.add_argument('--out', default='data')
    ap.add_argument('--topojson', action='store_true', default=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    ensure_land(args.land, args.land == DEFAULT_LAND)
    import geopandas as gpd
    land = gpd.read_file(args.land)
    clf = LandClassifier(land)
    print(f"classifier ready ({len(clf.pieces)} land pieces)")

    for base in args.levels:
        t0 = time.time()
        comp = build_compacted(clf, base_level=base)
        unc = expand_to_base(comp, base, clf)
        print(f"L{base}: compacted {len(comp)} / uncompacted {len(unc)} "
              f"({time.time()-t0:.0f}s)")
        for mode, cells in (('compacted', comp), ('uncompacted', unc)):
            feats = cells_to_features(cells)
            fc = {'type': 'FeatureCollection', 'features': feats}
            gj = os.path.join(args.out, f'global_tri_L{base}_{mode}.geojson')
            with open(gj, 'w') as f:
                json.dump(fc, f, separators=(',', ':'))
            sz = os.path.getsize(gj) / 1e6
            line = f"  {gj}: {len(feats)} cells, {sz:.1f} MB"
            if args.topojson:
                import topojson
                topo = topojson.Topology(fc, prequantize=1e6)
                tj = gj.replace('.geojson', '.topojson')
                with open(tj, 'w') as f:
                    f.write(topo.to_json())
                line += f" | topojson {os.path.getsize(tj)/1e6:.1f} MB"
            print(line)


if __name__ == '__main__':
    main()
