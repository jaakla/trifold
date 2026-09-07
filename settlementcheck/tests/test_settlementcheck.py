from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))
from settlementcheck import CLASSES, SettlementCheck  # noqa: E402
from settlementcheck import DetailsNotLoadedError


@pytest.fixture(scope="module")
def checker():
    return SettlementCheck(HERE / "fixture_L2.tfdg")


def test_all_classes_and_nodata(checker):
    points = json.loads((HERE / "points.json").read_text())
    for point in points[:9]:
        result = checker.check(point["lon"], point["lat"])
        assert result.code == point["code"]
        assert result.status == ("no_data" if point["code"] is None else "classified")
        if result.code is not None:
            assert result.settlement_class == CLASSES[result.code][0]


def test_hierarchy_surface_and_urban_semantics(checker):
    points = json.loads((HERE / "points.json").read_text())
    by_code = {point["code"]: point for point in points[:9]}
    water = checker.check(by_code[10]["lon"], by_code[10]["lat"])
    assert water.surface == "water"
    assert water.level1_code == 1
    assert water.level1_class == "rural_grid_cell"
    assert checker.is_urban(by_code[30]["lon"], by_code[30]["lat"]) is True
    assert checker.is_urban(by_code[11]["lon"], by_code[11]["lat"]) is False
    assert checker.is_urban(by_code[None]["lon"], by_code[None]["lat"]) is None


def test_mixed_share_and_batch(checker):
    point = next(p for p in json.loads((HERE / "points.json").read_text()) if p["mixed"])
    result = checker.check(point["lon"], point["lat"])
    assert result.mixed is True
    assert result.surface == "mixed"
    assert result.class_share == pytest.approx(round(0.6 * 255) / 255)
    assert checker.settlement_batch([point["lon"]], [point["lat"]]) == [result.settlement_class]
    with pytest.raises(ValueError, match="same length"):
        checker.check_batch([0, 1], [0])


@pytest.mark.parametrize("lon,lat", [(-181, 0), (181, 0), (0, -91), (0, 91)])
def test_invalid_coordinates(checker, lon, lat):
    with pytest.raises(ValueError):
        checker.check(lon, lat)


def test_format_rejections(tmp_path):
    source = (HERE / "fixture_L2.tfdg").read_bytes()
    for name, data, pattern in (
        ("short", source[:20], "truncated"),
        ("magic", b"NOPE" + source[4:], "not a TFDG"),
        ("version", source[:4] + b"\x02" + source[5:], "unsupported"),
        ("payload", source[:-4], "payload"),
    ):
        path = tmp_path / f"{name}.tfdg"
        path.write_bytes(data)
        with pytest.raises(ValueError, match=pattern):
            SettlementCheck(path)


def test_bundled_release_covers_every_class_and_edge_cases():
    release = SettlementCheck()
    points = {
        30: (7.051499, 5.782409), 23: (108.115816, -6.357873),
        22: (-81.996672, 33.446253), 21: (73.86796, 23.58543),
        13: (78.153074, 22.917153), 12: (35.467945, 0.764294),
        11: (-52.399346, 73.336005), 10: (177.99118, 38.087252),
    }
    assert {release.class_code(*point) for point in points.values()} == set(CLASSES)
    assert release.class_code(24.7536, 59.4370) == 30  # Tallinn
    assert release.class_code(-0.1276, 51.5072) == 30  # London
    assert release.check(0, 90).status == "no_data"
    assert release.check(180, 0) == release.check(-180, 0)


def test_core_only_is_honest_and_does_not_read_details(tmp_path):
    core = tmp_path / 'core.tfdg'
    core.write_bytes((HERE / 'fixture_L2.tfdg').read_bytes())
    sc = SettlementCheck(core)
    p = json.loads((HERE / 'points.json').read_text())[0]
    result = sc.classify(p['lon'], p['lat'])
    assert result.code == 10 and result.details_loaded is False
    assert result.mixed is None and result.nodata_mixed is None
    assert result.surface is None and result.class_share is None
    assert sc.settlement_batch([p['lon']], [p['lat']]) == ['water']
    assert sc.stats['details_faces'] == []
    with pytest.raises(DetailsNotLoadedError, match='optional'):
        sc.check(p['lon'], p['lat'])


def test_lazy_cache_identity_retry_and_sparse_gaps():
    calls = []
    corrupt = True
    def loader(face):
        calls.append(face)
        raw = bytearray((HERE / 'fixture_L2.details' / f'face-{face:02d}.tfdd').read_bytes())
        if corrupt:
            raw[60] ^= 1
        return raw
    sc = SettlementCheck(HERE / 'fixture_L2.tfdg', details_loader=loader, cache_faces=1)
    from _fastloc import index_to_triangle
    import math
    def centre(index):
        xyz = [sum(v[i] for v in index_to_triangle(index, 2)) for i in range(3)]
        return math.degrees(math.atan2(xyz[1], xyz[0])), math.degrees(math.atan2(xyz[2], math.hypot(*xyz[:2])))
    with pytest.raises(ValueError, match='match'):
        sc.check(*centre(23))
    assert sc.stats['details_faces'] == []
    corrupt = False
    # Exhaustive fixture parity, including gaps before/after sparse mixed runs.
    for i in range(320):
        r = sc.check(*centre(i))
        assert r.details_loaded
        assert r.mixed == (i in (23, 24, 26))
        assert r.nodata_mixed == (i in (24, 26))
        assert r.code == ([10, 11, 12, 13, 21, 22, 23, 30, None][i % 9])
        assert len(sc.stats['details_faces']) == 1
    sc.unload_details()
    assert sc.stats['details_faces'] == []


def test_reject_sparse_obsolete_profile_and_invalid_core(tmp_path):
    source = (HERE / 'fixture_L2.tfdg').read_bytes()
    for offset, value in [(6, 0), (6, 1), (7, 1), (5, 14)]:
        raw = bytearray(source); raw[offset] = value
        path = tmp_path / 'bad.tfdg'; path.write_bytes(raw)
        with pytest.raises(ValueError):
            SettlementCheck(path)


def test_corrupt_sections_and_detail_padding(tmp_path):
    import struct
    import zlib

    def repack(raw, block_index, mutate, trailing=False):
        count = 2 if raw[:4] == b'TFDG' else 4
        position = 92 + 8 * count
        blocks = []
        for i in range(count):
            size, _ = struct.unpack_from('<II', raw, 92 + 8 * i)
            blocks.append(zlib.decompress(raw[position:position + size]))
            position += size
        blocks[block_index] = mutate(blocks[block_index])
        packed = [zlib.compress(b) for b in blocks]
        if trailing:
            packed[block_index] += b'junk'
        head = bytearray(raw[:92])
        struct.pack_into('<I', head, 24, sum(map(len, blocks)))
        return head + b''.join(struct.pack('<II', len(p), len(b)) for p, b in zip(packed, blocks)) + b''.join(packed)

    core = (HERE / 'fixture_L2.tfdg').read_bytes()
    for index, mutate, trailing in [
        (0, lambda b: b'\x00' + b[1:], False),  # zero-length run
        (1, lambda b: b'\x09' + b[1:], False),  # invalid class slot
        (0, lambda b: b, True),  # bytes after a valid zlib stream
    ]:
        path = tmp_path / 'bad.tfdg'
        path.write_bytes(repack(core, index, mutate, trailing))
        with pytest.raises(ValueError):
            SettlementCheck(path)
    shard = (HERE / 'fixture_L2.details/face-01.tfdd').read_bytes()
    bad = repack(shard, 2, lambda b: b[:-1] + bytes([b[-1] | 1]))
    sc = SettlementCheck(HERE / 'fixture_L2.tfdg', details_loader=lambda face: bad)
    with pytest.raises(ValueError, match='padding'):
        sc._load_face(1)
    assert sc.stats['details_faces'] == []
