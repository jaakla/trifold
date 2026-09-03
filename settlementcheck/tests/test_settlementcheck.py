from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))
from settlementcheck import CLASSES, SettlementCheck  # noqa: E402


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
