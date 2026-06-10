import json
from pathlib import Path
import shutil
import subprocess

import pytest

from trifold import (build_export_ring, cell_triangle, densified_ring_xyz,
                     children64, encode64, from_compact, locate, parent64,
                     to_compact, to_path)


NODE = shutil.which('node')
WORKER = Path(__file__).parents[1] / 'worker' / 'cell-server.js'
SDK = Path(__file__).parents[1] / 'js' / 'trifold.js'


def _worker_fetch(tmp_path, urls):
    script = """
import worker from %s;
const urls = %s;
const out = [];
for (const url of urls) {
  const response = await worker.fetch(new Request(url));
  out.push(await response.json());
}
console.log(JSON.stringify(out));
""" % (json.dumps(WORKER.as_uri()), json.dumps(urls))
    result = subprocess.run(
        [NODE, '--input-type=module', '--eval', script],
        check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason='node is required for Worker cross-test')
def test_python_and_worker_addresses_agree(tmp_path):
    points = [
        (-0.1276, 51.5072, 6),
        (24.7536, 59.4370, 9),
        (179.999, 0.0, 12),
        (0.0, 90.0, 4),
        (0.0, -90.0, 4),
    ]
    urls = [f"https://test/locate/{lon},{lat}?level={level}"
            for lon, lat, level in points]
    actual = _worker_fetch(tmp_path, urls)

    expected = []
    for lon, lat, level in points:
        face, digits = locate(lon, lat, level)
        addr = encode64(face, digits)
        expected.append({
            'id': to_compact(addr),
            'path': to_path(addr),
            'addr64': str(addr),
            'level': level,
        })

    assert actual == expected


@pytest.mark.skipif(NODE is None, reason='node is required for Worker cross-test')
def test_python_and_worker_geometry_agree(tmp_path):
    compact = 'TF6958'
    actual = _worker_fetch(tmp_path, [f'https://test/cell/{compact}'])[0]

    addr = from_compact(compact)
    face, digits = locate(-0.1276, 51.5072, 6)
    assert encode64(face, digits) == addr
    tri = cell_triangle(face, digits)
    ring, _ = build_export_ring(
        densified_ring_xyz(tri, level=len(digits)), tri)
    expected_ring = [[round(lon, 6), round(lat, 6)] for lon, lat in ring]
    expected_ring.append(expected_ring[0])

    assert actual['properties'] == {
        'id': compact,
        'path': to_path(addr),
        'addr64': str(addr),
        'level': len(digits),
        'pole': '',
    }
    assert actual['geometry'] == {
        'type': 'Polygon',
        'coordinates': [expected_ring],
    }


@pytest.mark.skipif(NODE is None, reason='node is required for JavaScript SDK test')
def test_javascript_sdk_is_importable_and_reusable():
    script = """
import {
  children64, fromCompact, isAncestor, locateAddress, parent64,
  toCompact, toPath,
} from %s;
const london = locateAddress(-0.1276, 51.5072, 6);
const parent = parent64(london);
console.log(JSON.stringify({
  compact: toCompact(london),
  path: toPath(london),
  roundtrip: fromCompact(toCompact(london)).toString(),
  parent: toCompact(parent),
  children: children64(parent).map(toCompact),
  ancestor: isAncestor(parent, london),
}));
""" % json.dumps(SDK.as_uri())
    result = subprocess.run(
        [NODE, '--input-type=module', '--eval', script],
        check=True, capture_output=True, text=True)
    actual = json.loads(result.stdout)
    addr = from_compact('TF6958')
    parent = parent64(addr)
    assert actual == {
        'compact': 'TF6958',
        'path': to_path(addr),
        'roundtrip': str(addr),
        'parent': to_compact(parent),
        'children': [to_compact(child) for child in children64(parent)],
        'ancestor': True,
    }
