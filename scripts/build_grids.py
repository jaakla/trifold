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

from trifold.api import (area_km2, build_compacted, cell_geometry_ring,
                         edge_km, expand_to_base, from_path, hex_id,
                         rhombus64, rhombus_id, to_compact, to_path)

DEFAULT_LAND = 'natural-earth-vector/geojson/ne_50m_land.geojson'
LAND_URL = ('https://maps.goplex.ee/osm/osm_simplified_land_polygons.geojson')
LAND_SHA256 = 'e7543aeb9a15c51fcba4983fe7f5353db4d11eb98d71a08105a20a6e5735919e'


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
                'rhombus_id': rhombus_id(addr),
                'rhombus_hilbert': str(rhombus64(addr)),
                'hex_id': hex_id(addr),
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


def add_derived_properties(features):
    """Add projection keys to existing triangle features in place."""
    for feature in features:
        props = feature['properties']
        addr = from_path(props['path'])
        props['rhombus_id'] = rhombus_id(addr)
        props['rhombus_hilbert'] = str(rhombus64(addr))
        props['hex_id'] = hex_id(addr)
    return features


def dissolve_features(features, group_by):
    """Dissolve triangle features by a derived display-group key."""
    from collections import defaultdict

    from shapely import affinity
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    property_name = f'{group_by}_id'
    groups = defaultdict(list)
    for feature in features:
        groups[feature['properties'][property_name]].append(feature)

    dissolved = []
    for group_id, members in groups.items():
        geometries = [shape(member['geometry']) for member in members]
        reference = sum(geometries[0].bounds[::2]) / 2
        aligned = []
        for geometry in geometries:
            center = sum(geometry.bounds[::2]) / 2
            aligned.append(affinity.translate(
                geometry, xoff=360 * round((reference - center) / 360)))
        geometry = unary_union(aligned)
        center = sum(geometry.bounds[::2]) / 2
        geometry = affinity.translate(geometry, xoff=-360 * round(center / 360))

        first = members[0]['properties']
        props = {
            'id': group_id,
            property_name: group_id,
            'level': first['level'],
            'triangle_count': len(members),
            'interior': all(member['properties']['interior'] for member in members),
            'area_km2': round(sum(member['properties']['area_km2']
                                  for member in members), 0),
            'pole': next((member['properties']['pole'] for member in members
                          if member['properties']['pole']), ''),
            'xam': geometry.bounds[0] < -180 or geometry.bounds[2] > 180,
        }
        if group_by == 'rhombus':
            props['rhombus_hilbert'] = first['rhombus_hilbert']
        dissolved.append({
            'type': 'Feature',
            'properties': props,
            'geometry': mapping(geometry),
        })
    return dissolved


def write_collection(features, path, topojson_enabled=True):
    fc = {'type': 'FeatureCollection', 'features': features}
    with open(path, 'w') as f:
        json.dump(fc, f, separators=(',', ':'))
    line = f"  {path}: {len(features)} cells, {os.path.getsize(path) / 1e6:.1f} MB"
    if topojson_enabled:
        import topojson
        topo = topojson.Topology(fc, prequantize=1e6)
        topo_path = path.replace('.geojson', '.topojson')
        with open(topo_path, 'w') as f:
            f.write(topo.to_json())
        line += f" | topojson {os.path.getsize(topo_path) / 1e6:.1f} MB"
    print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--levels', type=int, nargs='+', default=[4, 5, 6])
    ap.add_argument('--land', default=DEFAULT_LAND)
    ap.add_argument('--out', default='data')
    ap.add_argument('--topojson', action=argparse.BooleanOptionalAction,
                    default=True)
    ap.add_argument('--group-by', nargs='+', choices=('rhombus', 'hex'),
                    default=[], help='also export dissolved display groups')
    ap.add_argument('--group-existing', action='store_true',
                    help='enrich existing triangle GeoJSON and derive groups')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.group_existing:
        if not args.group_by:
            ap.error('--group-existing requires --group-by')
        for base in args.levels:
            for mode in ('compacted', 'uncompacted'):
                path = os.path.join(args.out, f'global_tri_L{base}_{mode}.geojson')
                if not os.path.isfile(path):
                    raise FileNotFoundError(f'existing grid not found: {path}')
                with open(path) as src:
                    features = add_derived_properties(json.load(src)['features'])
                has_pmtiles = os.path.isfile(path.replace('.geojson', '.pmtiles'))
                write_collection(features, path, args.topojson and not has_pmtiles)
                for group_by in args.group_by:
                    grouped = dissolve_features(features, group_by)
                    grouped_path = path.replace('.geojson', f'_{group_by}.geojson')
                    write_collection(grouped, grouped_path, args.topojson)
        return

    ensure_land(args.land, args.land == DEFAULT_LAND)
    import geopandas as gpd
    from trifold.land import LandClassifier
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
            gj = os.path.join(args.out, f'global_tri_L{base}_{mode}.geojson')
            write_collection(feats, gj, args.topojson)
            for group_by in args.group_by:
                grouped = dissolve_features(feats, group_by)
                grouped_path = gj.replace('.geojson', f'_{group_by}.geojson')
                write_collection(grouped, grouped_path, args.topojson)


if __name__ == '__main__':
    main()
