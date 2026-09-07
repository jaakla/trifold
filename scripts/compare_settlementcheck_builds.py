#!/usr/bin/env python
"""Compare old monolithic WIP v1 and current split v1 over every L12 cell.

Uses bounded chunks, not a 335-million-element dense global array. This is a
migration diagnostic; the library deliberately rejects the obsolete layout.
"""
import argparse
import json
import math
import struct
import sys
import zlib
from array import array
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'settlementcheck/python'))
from settlementcheck import SettlementCheck
from _fastloc import index_to_triangle


def old_tables(path):
    raw = path.read_bytes()
    h = struct.unpack_from('<4sBBBBHBBIIII32s', raw)
    assert h[0] == b'TFDG' and h[1] == 1 and h[3] == 1
    body = zlib.decompress(raw[60:])
    del raw
    ends, before = array('I'), array('I')
    codes, mixed = bytearray(), bytearray()
    position = cursor = seen = 0
    def read():
        nonlocal position
        result = shift = 0
        while True:
            byte = body[position]; position += 1
            result |= (byte & 127) << shift
            if not byte & 128:
                return result
            shift += 7
    for _ in range(h[8]):
        assert read() == 0
        cursor += read()
        code, mix = body[position:position + 2]; position += 2
        before.append(seen)
        if mix:
            seen += cursor - (ends[-1] if ends else 0)
        ends.append(cursor); codes.append(code); mixed.append(mix)
    values = body[position:]
    assert seen == h[9] and len(values) == 2 * seen and cursor == h[10]
    return h, np.asarray(ends), np.frombuffer(codes, 'u1'), np.frombuffer(mixed, 'u1'), np.asarray(before), np.frombuffer(values, 'u1').reshape(-1, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    header, old_ends, old_codes, old_mixed, old_before, old_values = old_tables(args.original)
    current = SettlementCheck(args.current, cache_faces=1)
    assert header[2] == current.level and header[-1].hex() == current.raster_sha256
    new_ends, new_codes = np.asarray(current._ends), np.frombuffer(current._codes, 'u1')
    counts = dict(cells=0, class_changed=0, mixed_changed=0, nodata_mixed_changed=0,
                  water_mixed_changed=0, share_byte_changed=0, old_nodata_mixed=0,
                  new_nodata_mixed=0)
    span = 4 ** current.level
    for face in range(20):
        tri = index_to_triangle(face * span, current.level)
        x, y, z = [sum(v[i] for v in tri) for i in range(3)]
        lon, lat = math.degrees(math.atan2(y, x)), math.degrees(math.atan2(z, math.hypot(x, y)))
        starts, ends, before, shares, water, nodata = current.load_details(lon, lat)
        starts, ends, before = np.asarray(starts), np.asarray(ends), np.asarray(before)
        shares = np.frombuffer(shares, 'u1')
        water, nodata = np.frombuffer(water, 'u1'), np.frombuffer(nodata, 'u1')
        for start in range(0, span, 262144):
            local = np.arange(start, min(start + 262144, span), dtype=np.uint32)
            indexes = local + face * span
            old_runs = np.searchsorted(old_ends, indexes, side='right')
            old_c = old_codes[old_runs]
            old_m = old_mixed[old_runs].astype(bool)
            old_s, old_f = np.full(len(local), 255, dtype='u1'), np.zeros(len(local), dtype='u1')
            old_starts = np.where(old_runs == 0, 0, old_ends[np.maximum(old_runs - 1, 0)])
            offsets = (old_before[old_runs] + indexes - old_starts)[old_m]
            old_s[old_m], old_f[old_m] = old_values[offsets, 0], old_values[offsets, 1]
            new_c = new_codes[np.searchsorted(new_ends, indexes, side='right')]
            new_s, new_f = np.full(len(local), 255, dtype='u1'), np.zeros(len(local), dtype='u1')
            new_m = np.zeros(len(local), dtype=bool)
            if len(ends):
                runs = np.searchsorted(ends, local, side='right')
                new_m = (runs < len(ends)) & (local >= starts[np.minimum(runs, len(ends) - 1)])
                offsets = before[runs[new_m]] + local[new_m] - starts[runs[new_m]]
                new_s[new_m] = shares[offsets]
                new_f[new_m] = ((water[offsets // 8] >> (7 - offsets % 8)) & 1) | (((nodata[offsets // 8] >> (7 - offsets % 8)) & 1) << 1)
            counts['cells'] += len(local)
            for key, values in [('class_changed', old_c != new_c), ('mixed_changed', old_m != new_m),
                                ('nodata_mixed_changed', (old_f & 2) != (new_f & 2)),
                                ('water_mixed_changed', (old_f & 1) != (new_f & 1)),
                                ('share_byte_changed', old_s != new_s),
                                ('old_nodata_mixed', old_f & 2), ('new_nodata_mixed', new_f & 2)]:
                counts[key] += int(np.count_nonzero(values))
        print(f'compared face {face:02d}', flush=True)
    assert counts['cells'] == current._n_cells
    print(json.dumps(counts, indent=2))
    if args.out:
        args.out.write_text(json.dumps(counts, indent=2) + '\n')


if __name__ == '__main__':
    main()
