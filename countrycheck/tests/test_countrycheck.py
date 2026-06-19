"""Tests for the countrycheck Python library (run from repo root: pytest countrycheck/tests)."""
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
from countrycheck import CountryCheck, CountryResult  # noqa: E402
from _fastloc import locate_index  # noqa: E402

FIXTURE = Path(__file__).parent / "points.json"


@pytest.fixture(scope="module")
def cc():
    return CountryCheck()


def test_stats(cc):
    s = cc.stats
    assert s["level"] == 10
    assert s["countries"] == 256
    assert s["has_shares"]
    assert s["border_cells"] > 100_000
    assert s["interior_cells"] > 1_000_000


def test_country_table(cc):
    codes = [c["code"] for c in cc.countries]
    assert codes == sorted(codes)
    assert "EST" in codes and "XKO" in codes
    est = next(c for c in cc.countries if c["code"] == "EST")
    assert est["iso2"] == "EE" and est["name"] == "Estonia"
    xko = next(c for c in cc.countries if c["code"] == "XKO")
    assert xko["iso2"] == ""  # X-coded territories have no ISO code


def test_known_points(cc):
    assert cc.country(24.7536, 59.4370) == "EST"   # Tallinn
    assert cc.country(-0.1276, 51.5072) == "GBR"   # London
    assert cc.country(-30.0, 30.0) is None         # mid-Atlantic
    assert cc.country(0.0, 89.99) is None          # Arctic ocean
    assert cc.country(0.0, -89.99) == "ATA"        # Antarctica
    assert cc.country(20.9, 42.6) == "XKO"         # Kosovo
    assert cc.iso2(24.7536, 59.4370) == "EE"
    assert cc.iso2(20.9, 42.6) is None             # no ISO code


def test_result_semantics(cc):
    none = cc.check(-30.0, 30.0)
    assert none == CountryResult(None, None, None, "none", 1.0, 0.0, None)
    interior = cc.check(13.4, 52.52)               # Berlin
    assert interior.kind == "country" and interior.confidence == 1.0
    assert interior.country == "DEU" and interior.iso2 == "DE"
    assert interior.cell and interior.cell.startswith("T")
    border = cc.check(24.3, 59.6)                  # Estonian coastal waters
    assert border.kind == "border"
    assert border.share is not None
    assert 0.0 < border.share <= 1.0
    assert border.confidence == border.share


def test_input_validation(cc):
    with pytest.raises(ValueError):
        cc.check(181.0, 0.0)
    with pytest.raises(ValueError):
        cc.check(0.0, 91.0)


def test_fixture(cc):
    points = json.loads(FIXTURE.read_text())
    for p in points:
        r = cc.check(p["lon"], p["lat"])
        assert r.country == p["country"], p["name"]
        assert r.iso2 == p["iso2"], p["name"]
        assert r.kind == p["kind"], p["name"]
        assert r.cell == p["cell"], p["name"]
        assert round(r.confidence, 6) == p["confidence"], p["name"]


def test_fast_locate_matches_sdk(cc):
    """The pure-float locate must agree with the trifold SDK exactly."""
    tg = pytest.importorskip("trifold.api")
    rng = random.Random(99)
    for _ in range(2000):
        lon = rng.uniform(-180.0, 180.0)
        lat = rng.uniform(-90.0, 90.0)
        assert locate_index(lon, lat, 10) == tg.locate_address(lon, lat, 10) >> 39


def test_batch_matches_scalar(cc):
    np = pytest.importorskip("numpy")
    pytest.importorskip("trifold.api")
    rng = random.Random(123)
    pts = [(rng.uniform(-180, 180), rng.uniform(-90, 90)) for _ in range(5000)]
    lons = np.array([p[0] for p in pts])
    lats = np.array([p[1] for p in pts])
    batch = cc.country_batch(lons, lats)
    for (lon, lat), code in zip(pts, batch):
        assert code == cc.country(lon, lat)


def test_refined_batch_matches_scalar():
    np = pytest.importorskip("numpy")
    pytest.importorskip("trifold.api")
    tfcr = Path(__file__).resolve().parent.parent / "data" / "borders_L10.tfcr"
    if not tfcr.exists():
        pytest.skip("border refinement dataset not built")
    cc = CountryCheck(refine_path=tfcr)
    points = [(24.3, 59.6), (24.7536, 59.4370), (-30.0, 30.0), (6.10, 46.255)]
    lons = np.array([p[0] for p in points])
    lats = np.array([p[1] for p in points])
    assert cc.country_batch(lons, lats) == [cc.country(*p) for p in points]


def test_refined_fixture():
    """Refined border answers (requires the optional TFCR dataset)."""
    tfcr = Path(__file__).resolve().parent.parent / "data" / "borders_L10.tfcr"
    fixture = Path(__file__).parent / "refined_points.json"
    if not tfcr.exists() or not fixture.exists():
        pytest.skip("border refinement dataset not built")
    cc = CountryCheck(refine_path=tfcr)
    points = json.loads(fixture.read_text())
    n_refined = 0
    for p in points:
        r = cc.check(p["lon"], p["lat"])
        assert r.country == p["country"]
        assert r.kind == p["kind"]
        assert r.refined == p["refined"]
        assert r.cell == p["cell"]
        assert round(r.confidence, 6) == p["confidence"]
        n_refined += r.refined
    assert n_refined > len(points) * 0.9


def test_polyline_segments(cc):
    # Berlin -> Warsaw -> Vilnius crosses DEU, POL and ends in LTU
    coords = [(13.4, 52.5), (21.0, 52.2), (25.3, 54.7)]
    res = cc.check_polyline(coords, step_km=25)
    countries = [s.country for s in res.segments]
    assert countries[0] == "DEU"
    assert "POL" in countries
    assert countries[-1] == "LTU"
    # segments are ordered and directed (no cross-segment merging)
    assert res.stats["n_segments"] == len(res.segments)
    # fractions sum to ~1, distances sum to total
    assert abs(sum(s.fraction for s in res.segments) - 1.0) < 1e-9
    assert abs(sum(s.distance_km for s in res.segments) - res.total_distance_km) < 1e-6
    assert res.total_distance_km > 0


def test_polyline_vertex_mode(cc):
    coords = [(13.4, 52.5), (21.0, 52.2)]
    res = cc.check_polyline(coords, mode="vertex")
    # only two vertices sampled, both in-country -> distinct/merged by country
    assert res.total_distance_km > 0
    assert all(0.0 <= s.fraction <= 1.0 for s in res.segments)


def test_country_polyline_returns_segments(cc):
    coords = [(13.4, 52.5), (21.0, 52.2), (25.3, 54.7)]
    segs = cc.country_polyline(coords, step_km=25)
    assert segs == cc.check_polyline(coords, step_km=25).segments


def test_polyline_short_line_in_one_country(cc):
    # a short line entirely inside Germany -> single country segment
    coords = [(13.40, 52.50), (13.45, 52.52)]
    res = cc.check_polyline(coords, step_km=3.5)
    assert len(res.segments) == 1
    assert res.segments[0].country == "DEU"
    assert res.segments[0].fraction == pytest.approx(1.0)


def test_polyline_requires_two_vertices(cc):
    with pytest.raises(ValueError):
        cc.check_polyline([(13.4, 52.5)])


def test_refinement_changes_border_answer():
    """A border cell's bundled best call can differ from the exact polygon."""
    tfcr = Path(__file__).resolve().parent.parent / "data" / "borders_L10.tfcr"
    if not tfcr.exists():
        pytest.skip("border refinement dataset not built")
    base = CountryCheck()
    ref = CountryCheck(refine_path=tfcr)
    rng = random.Random(4242)
    flipped = 0
    checked = 0
    while checked < 500:
        lon = rng.uniform(-180.0, 180.0)
        lat = rng.uniform(-90.0, 90.0)
        rb = base.check(lon, lat)
        if rb.kind != "border":
            continue
        checked += 1
        rr = ref.check(lon, lat)
        assert rr.refined
        flipped += rr.country != rb.country
    assert flipped > 0  # refinement must actually correct some calls
