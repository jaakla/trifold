"""Tests for the landcheck Python library (run from repo root: pytest landcheck/tests)."""
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
from landcheck import LandCheck, LandResult  # noqa: E402
from _fastloc import locate_index  # noqa: E402

FIXTURE = Path(__file__).parent / "points.json"


@pytest.fixture(scope="module")
def lc():
    return LandCheck()


def test_stats(lc):
    s = lc.stats
    assert s["level"] == 10
    assert s["has_fractions"]
    assert s["coastal_cells"] > 100_000
    assert s["interior_cells"] > 1_000_000


def test_known_points(lc):
    assert lc.is_land(24.7536, 59.4370)        # Tallinn
    assert lc.is_land(-0.1276, 51.5072)        # London
    assert not lc.is_land(-30.0, 30.0)         # mid-Atlantic
    assert not lc.is_land(0.0, 89.99)          # Arctic ocean
    assert lc.is_land(0.0, -89.99)             # Antarctica


def test_result_semantics(lc):
    sea = lc.check(-30.0, 30.0)
    assert sea == LandResult(False, "sea", 1.0, 0.0, None)
    land = lc.check(10.0, 25.0)                # Sahara
    assert land.kind == "land" and land.confidence == 1.0
    assert land.cell and land.cell.startswith("T")
    coast = lc.check(0.0, -89.99)              # Antarctic coast cell
    assert coast.kind == "coast"
    assert coast.land_fraction is not None
    assert 0.0 < coast.land_fraction < 1.0
    assert coast.confidence == max(coast.land_fraction, 1 - coast.land_fraction)


def test_input_validation(lc):
    with pytest.raises(ValueError):
        lc.check(181.0, 0.0)
    with pytest.raises(ValueError):
        lc.check(0.0, 91.0)


def test_fixture(lc):
    points = json.loads(FIXTURE.read_text())
    for p in points:
        r = lc.check(p["lon"], p["lat"])
        assert r.land == p["land"], p["name"]
        assert r.kind == p["kind"], p["name"]
        assert r.cell == p["cell"], p["name"]
        assert round(r.confidence, 6) == p["confidence"], p["name"]


def test_fast_locate_matches_sdk(lc):
    """The pure-float locate must agree with the trifold SDK exactly."""
    tg = pytest.importorskip("trifold.api")
    rng = random.Random(99)
    for _ in range(2000):
        lon = rng.uniform(-180.0, 180.0)
        lat = rng.uniform(-90.0, 90.0)
        assert locate_index(lon, lat, 10) == tg.locate_address(lon, lat, 10) >> 39


def test_compact_address_matches_sdk(lc):
    tg = pytest.importorskip("trifold.api")
    r = lc.check(24.7536, 59.4370)
    assert r.cell == tg.to_compact(tg.locate_address(24.7536, 59.4370, 10))


def test_refined_fixture():
    """Refined coastal answers (requires the optional TFLR dataset)."""
    tflr = Path(__file__).resolve().parent.parent / "data" / "coastal_osm_L10.tflr"
    fixture = Path(__file__).parent / "refined_points.json"
    if not tflr.exists() or not fixture.exists():
        pytest.skip("coastal refinement dataset not built")
    lc = LandCheck(refine_path=tflr)
    points = json.loads(fixture.read_text())
    n_refined = 0
    for p in points:
        r = lc.check(p["lon"], p["lat"])
        assert r.land == p["land"]
        assert r.kind == p["kind"]
        assert r.refined == p["refined"]
        assert r.cell == p["cell"]
        assert round(r.confidence, 6) == p["confidence"]
        n_refined += r.refined
    assert n_refined > len(points) * 0.9


def test_refinement_overrides_base_land_near_tallinn():
    """OSM coastline cells can override a Natural Earth interior-land cell."""
    tflr = Path(__file__).resolve().parent.parent / "data" / "coastal_osm_L10.tflr"
    if not tflr.exists():
        pytest.skip("coastal refinement dataset not built")
    lc = LandCheck(refine_path=tflr)
    result = lc.check(24.8156, 59.4756)
    assert result.kind == "coast"
    assert result.refined
    assert not result.land
    assert result.cell == "TFAVKGZ"


def test_refined_batch_matches_scalar():
    np = pytest.importorskip("numpy")
    pytest.importorskip("trifold.api")
    tflr = Path(__file__).resolve().parent.parent / "data" / "coastal_osm_L10.tflr"
    if not tflr.exists():
        pytest.skip("coastal refinement dataset not built")
    lc = LandCheck(refine_path=tflr)
    points = [(24.8156, 59.4756), (24.7536, 59.4370), (-30.0, 30.0)]
    lons = np.array([p[0] for p in points])
    lats = np.array([p[1] for p in points])
    assert list(lc.is_land_batch(lons, lats)) == [lc.is_land(*p) for p in points]


def test_polyline_sea_to_land(lc):
    # mid-Atlantic into the Iberian peninsula: starts at sea, reaches land
    coords = [(-30.0, 40.0), (0.0, 40.0)]
    res = lc.check_polyline(coords, step_km=50)
    assert res.segments[0].land is False
    assert res.segments[0].kind in ("sea", "coast")
    assert any(s.land for s in res.segments)
    # consecutive segments alternate land/sea (merge by identity, not kind)
    assert all(a.land != b.land
               for a, b in zip(res.segments, res.segments[1:]))
    # distances and fractions are consistent
    assert abs(sum(s.fraction for s in res.segments) - 1.0) < 1e-9
    assert abs(sum(s.distance_km for s in res.segments) - res.total_distance_km) < 1e-6
    assert res.stats["land_km"] + res.stats["sea_km"] == pytest.approx(res.total_distance_km)
    assert res.stats["land_fraction"] == pytest.approx(
        res.stats["land_km"] / res.total_distance_km)


def test_polyline_all_sea(lc):
    # a short line in the open mid-Atlantic -> single sea segment
    coords = [(-30.0, 30.0), (-29.5, 30.0)]
    res = lc.check_polyline(coords, step_km=3.5)
    assert len(res.segments) == 1
    assert res.segments[0].land is False
    assert res.segments[0].fraction == pytest.approx(1.0)


def test_is_land_polyline_returns_segments(lc):
    coords = [(-30.0, 40.0), (0.0, 40.0)]
    segs = lc.is_land_polyline(coords, step_km=50)
    assert segs == lc.check_polyline(coords, step_km=50).segments


def test_polyline_requires_two_vertices(lc):
    with pytest.raises(ValueError):
        lc.check_polyline([(0.0, 0.0)])


def test_batch_matches_scalar(lc):
    np = pytest.importorskip("numpy")
    pytest.importorskip("trifold.api")
    rng = random.Random(123)
    pts = [(rng.uniform(-180, 180), rng.uniform(-90, 90)) for _ in range(5000)]
    lons = np.array([p[0] for p in pts])
    lats = np.array([p[1] for p in pts])
    mask = lc.is_land_batch(lons, lats)
    for (lon, lat), m in zip(pts, mask):
        assert bool(m) == lc.is_land(lon, lat)
