#!/usr/bin/env python3
"""Hash all decoded release arrays in Python and Node, one detail face at a time."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'settlementcheck/python'))
from settlementcheck import SettlementCheck


def main():
    path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'settlementcheck/data/degurba_R2025A_E2025_L12.tfdg'
    lookup = SettlementCheck(path, cache_faces=1)
    digest = hashlib.sha256()

    def update(value):
        if hasattr(value, 'byteswap') and sys.byteorder != 'little':
            value = value[:]
            value.byteswap()
        digest.update(value)

    update(lookup._ends)
    update(lookup._codes)
    for face in range(20):
        for value in lookup._load_face(face):
            update(value)
    expected = digest.hexdigest()
    script = """
import {createHash} from 'node:crypto';
import {SettlementCheck} from './settlementcheck/js/settlementcheck.mjs';
const lookup = await SettlementCheck.fromFile(process.argv[1], {cacheFaces: 1});
const hash = createHash('sha256');
function update(value) {
  if (value instanceof Uint32Array) {
    const bytes = Buffer.allocUnsafe(value.length * 4);
    for (let i = 0; i < value.length; i++) bytes.writeUInt32LE(value[i], i * 4);
    hash.update(bytes);
  } else hash.update(value);
}
update(lookup.ends); update(lookup.codes);
for (let face = 0; face < 20; face++) {
  const shard = await lookup._loadFace(face);
  for (const key of ['starts', 'ends', 'before', 'shares', 'water', 'nodata']) update(shard[key]);
}
console.log(hash.digest('hex'));
"""
    actual = subprocess.check_output(['node', '--input-type=module', '-e', script, str(path)], cwd=ROOT, text=True).strip()
    if actual != expected:
        raise SystemExit(f'Python/JavaScript mismatch: {expected} != {actual}')
    print(json.dumps({'decoded_sha256': expected, 'faces': 20, 'class_runs': len(lookup._ends), 'parity': True}))


if __name__ == '__main__':
    main()
