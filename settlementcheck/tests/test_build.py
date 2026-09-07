from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[1] / "build.py"
SPEC = importlib.util.spec_from_file_location("settlementcheck_build", BUILD)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)

import sys
sys.path.insert(0, str(BUILD.parent / "python"))
from _fastloc import index_to_triangle, locate_index  # noqa: E402


@pytest.mark.parametrize(
    "triangle,expected",
    [
        ([(0, 0), (2, 0), (0, 2)], 1.0),
        ([(-2, 0), (2, 0), (0, 2)], 1.0),
        ([(2, 2), (3, 2), (2, 3)], 0.0),
    ],
)
def test_exact_axis_aligned_pixel_clipping(triangle, expected):
    area = build.RasterClassifier._rectangle_intersection_area(
        triangle, 0, 0, 1, 1)
    assert area == pytest.approx(expected)


def test_run_writer_is_deterministic_and_merges_homogeneous_runs(tmp_path):
    first = build.RunWriter(2)
    first.add(0, 8, 10)
    first.add(8, 8, 10)
    first.add(16, 1, 30, True, 0.75)
    assert list(first.records()) == [(0, 16, 10, 0), (16, 1, 30, 1)]
    assert first.mixed == bytes([round(0.75 * 255), 0])

    # Complete the canonical space and ensure repeated writes are byte-equal.
    first.add(17, 20 * 4 ** 2 - 17, 11)
    a, b = tmp_path / "a.tfdg", tmp_path / "b.tfdg"
    digest = "00" * 32
    build.write_dataset(a, first, digest)
    build.write_dataset(b, first, digest)
    assert a.read_bytes() == b.read_bytes()


def test_mollweide_projection_and_antimeridian_split():
    classifier = object.__new__(build.RasterClassifier)
    x, y = classifier._project_lonlat(24.75, 59.44)
    assert x == pytest.approx(1622421.1397538062, abs=1e-5)
    assert y == pytest.approx(6823096.578590776, abs=1e-5)
    index = locate_index(180, 0, 12)
    parts = classifier.projected_parts(index_to_triangle(index, 12), 12)
    assert len(parts) == 2
    assert all(max(x for x, _ in part) - min(x for x, _ in part) < 2_000
               for part in parts)


@pytest.mark.parametrize('lat', [89, -89, 89.9, -89.9, 89.99, 89.999])
def test_projection_converges_near_poles(lat):
    from pyproj import Transformer
    expected = Transformer.from_crs('EPSG:4326', 'ESRI:54009', always_xy=True).transform(180, lat)
    assert build.RasterClassifier._project_lonlat(180, lat) == pytest.approx(expected, abs=0.2)


def test_valid_pixels_do_not_create_phantom_nodata():
    import numpy as np
    from affine import Affine
    from types import SimpleNamespace
    classifier = object.__new__(build.RasterClassifier)
    classifier.dataset = SimpleNamespace(
        transform=Affine(1000, 0, 10000000, 0, -1000, 5000000), width=4, height=4)
    classifier.values = np.full((4, 4), 11, dtype=np.uint8)
    classifier.values[:, 2:] = 12
    triangle = [(10000126.321002154, 4996780.51872087),
                (10000726.7044114, 4997855.440056229),
                (10002254.613741664, 4997817.255050581)]
    code, share, mixed, water, nodata = classifier.exact([triangle])
    assert (code, mixed, water, nodata) == (11, True, False, False)
    assert share == pytest.approx(0.98006415117)
    classifier.values[:] = 11
    assert classifier.exact([triangle])[2:] == (False, False, False)
    # Real outside coverage and real source nodata must still be retained.
    outside = [(9999500, 4999000), (10000500, 4999000), (10000500, 4998000)]
    assert classifier.exact([outside])[-1] is True
    classifier.values[:, 2:] = 255
    assert classifier.exact([triangle])[-1] is True
