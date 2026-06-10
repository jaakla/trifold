"""Command-line interface: encode/decode/locate/geometry."""
import argparse
import json
import sys

from .api import (
    cell_feature,
    cell_metrics,
    children64,
    locate_address,
    parent64,
    parse_address,
    to_compact,
)


def _parse_any(s):
    return parse_address(s)


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
        print(to_compact(locate_address(a.lon, a.lat, a.level)))
        return

    addr = _parse_any(a.addr)

    if a.cmd == 'show':
        metrics = cell_metrics(addr)
        print(f"compact : {metrics['id']}")
        print(f"path    : {metrics['path']}")
        print(f"addr64  : {addr} (0x{addr:016X})")
        print(f"rhombus : {metrics['rhombus_id']}")
        print(f"hilbert : {metrics['rhombus_hilbert']}")
        print(f"hex     : {metrics['hex_id']}")
        print(f"level   : {metrics['level']}")
        print(f"edge_km : {metrics['edge_km']:.1f}")
        print(f"area_km2: {metrics['area_km2']:.0f}")
    elif a.cmd == 'geom':
        json.dump(cell_feature(addr), sys.stdout)
        print()
    elif a.cmd == 'parent':
        print(to_compact(parent64(addr)))
    elif a.cmd == 'children':
        for c in children64(addr):
            print(to_compact(c))


if __name__ == '__main__':
    main()
