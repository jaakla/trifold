"""Command-line interface: encode/decode/locate/geometry."""
import argparse
import json
import sys

from . import (encode64, to_compact, from_compact, to_path, from_path,
               locate, cell_triangle, parent64, children64,
               build_export_ring, densified_ring_xyz, decode64,
               edge_km, area_km2, level_of)


def _parse_any(s):
    s = s.strip()
    return from_path(s) if s.upper().startswith('F') else from_compact(s)


def main(argv=None):
    p = argparse.ArgumentParser(prog='trifold')
    sub = p.add_subparsers(dest='cmd', required=True)

    q = sub.add_parser('locate', help='lon lat level -> address')
    q.add_argument('lon', type=float); q.add_argument('lat', type=float)
    q.add_argument('level', type=int)

    q = sub.add_parser('show', help='address -> all encodings + stats')
    q.add_argument('addr')

    q = sub.add_parser('geom', help='address -> GeoJSON Feature')
    q.add_argument('addr')

    q = sub.add_parser('parent', help='address -> parent address')
    q.add_argument('addr')

    q = sub.add_parser('children', help='address -> 4 child addresses')
    q.add_argument('addr')

    a = p.parse_args(argv)

    if a.cmd == 'locate':
        face, digits = locate(a.lon, a.lat, a.level)
        addr = encode64(face, digits)
        print(to_compact(addr))
        return

    addr = _parse_any(a.addr)

    if a.cmd == 'show':
        face, digits = decode64(addr)
        tri = cell_triangle(face, digits)
        print(f"compact : {to_compact(addr)}")
        print(f"path    : {to_path(addr)}")
        print(f"addr64  : {addr} (0x{addr:016X})")
        print(f"level   : {len(digits)}")
        print(f"edge_km : {edge_km(tri):.1f}")
        print(f"area_km2: {area_km2(tri):.0f}")
    elif a.cmd == 'geom':
        face, digits = decode64(addr)
        tri = cell_triangle(face, digits)
        ring, pole = build_export_ring(
            densified_ring_xyz(tri, level=len(digits)), tri)
        ring = [[round(x, 6), round(y, 6)] for x, y in ring]
        ring.append(ring[0])
        json.dump({'type': 'Feature',
                   'properties': {'compact': to_compact(addr),
                                  'path': to_path(addr),
                                  'level': len(digits), 'pole': pole},
                   'geometry': {'type': 'Polygon', 'coordinates': [ring]}},
                  sys.stdout)
        print()
    elif a.cmd == 'parent':
        print(to_compact(parent64(addr)))
    elif a.cmd == 'children':
        for c in children64(addr):
            print(to_compact(c))


if __name__ == '__main__':
    main()
