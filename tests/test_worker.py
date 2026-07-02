import json
from pathlib import Path
import shutil
import subprocess

import pytest

from trifold import (build_export_ring, cell_triangle, densified_ring_xyz,
                     bbox_cover, children64, cover_ranges, decode_rhombus64,
                     encode64, from_compact, hex_id, hilbert_ranges, locate,
                     parent64, polyfill, rhombus64, rhombus_id, to_compact,
                     to_path)


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
            'rhombus_id': rhombus_id(addr),
            'rhombus_hilbert': str(rhombus64(addr)),
            'hex_id': hex_id(addr),
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
        'rhombus_id': rhombus_id(addr),
        'rhombus_hilbert': str(rhombus64(addr)),
        'hex_id': hex_id(addr),
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
  children64, decodeRhombus64, fromCompact, hexId, isAncestor,
  locateAddress, parent64, rhombus64, rhombusId, toCompact, toPath,
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
  rhombusId: rhombusId(london),
  rhombus64: rhombus64(london).toString(),
  rhombusDecoded: decodeRhombus64(rhombus64(london)),
  hexId: hexId(london),
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
        'rhombusId': rhombus_id(addr),
        'rhombus64': str(rhombus64(addr)),
        'rhombusDecoded': dict(zip(
            ('diamond', 'level', 'x', 'y'),
            decode_rhombus64(rhombus64(addr)))),
        'hexId': hex_id(addr),
    }


@pytest.mark.skipif(NODE is None, reason='node is required for JavaScript SDK test')
def test_javascript_cover_helpers_match_python():
    polygon = {
        'type': 'Polygon',
        'coordinates': [[
            [-1.0, 51.0],
            [0.5, 51.0],
            [0.5, 52.0],
            [-1.0, 52.0],
            [-1.0, 51.0],
        ]],
    }
    script = """
import { bboxCover, coverRanges, hilbertRanges, polyfill } from %s;
const polygon = %s;
const bboxCells = bboxCover(-1.0, 51.0, 0.5, 52.0, 5);
const anti = bboxCover(179.0, -1.0, -179.0, 1.0, 5);
const polar = bboxCover(-180.0, 84.0, 180.0, 90.0, 5);
const polygonCells = polyfill(polygon, 5);
const ranges = coverRanges(bboxCells);
const asPairs = pairs => pairs.map(([low, high]) => [low.toString(), high.toString()]);
console.log(JSON.stringify({
  bbox: bboxCells.map(String),
  anti: anti.map(String),
  polygon: polygonCells.map(String),
  ranges: asPairs(ranges),
  hilbert: asPairs(hilbertRanges(bboxCells)),
  hilbertAnti: asPairs(hilbertRanges(anti)),
  hilbertPolar: asPairs(hilbertRanges(polar)),
  hilbertPolygon: asPairs(hilbertRanges(polygonCells)),
}));
""" % (json.dumps(SDK.as_uri()), json.dumps(polygon))
    result = subprocess.run(
        [NODE, '--input-type=module', '--eval', script],
        check=True, capture_output=True, text=True)
    actual = json.loads(result.stdout)

    bbox_cells = bbox_cover(-1.0, 51.0, 0.5, 52.0, 5)
    def as_pairs(pairs):
        return [[str(low), str(high)] for low, high in pairs]
    assert actual == {
        'bbox': [str(cell) for cell in bbox_cells],
        'anti': [str(cell) for cell in bbox_cover(179.0, -1.0, -179.0, 1.0, 5)],
        'polygon': [str(cell) for cell in polyfill(polygon, 5)],
        'ranges': as_pairs(cover_ranges(bbox_cells)),
        'hilbert': as_pairs(hilbert_ranges(bbox_cells)),
        'hilbertAnti': as_pairs(hilbert_ranges(
            bbox_cover(179.0, -1.0, -179.0, 1.0, 5))),
        'hilbertPolar': as_pairs(hilbert_ranges(
            bbox_cover(-180.0, 84.0, 180.0, 90.0, 5))),
        'hilbertPolygon': as_pairs(hilbert_ranges(polyfill(polygon, 5))),
    }
