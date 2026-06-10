import math
import random

import numpy as np

from trifold import EARTH_R, area_km2, cell_triangle, icosahedron, locate
from trifold.core import contains_point, subdivide


def _point(lon, lat):
    lam, phi = np.radians([lon, lat])
    return np.array([np.cos(phi) * np.cos(lam),
                     np.cos(phi) * np.sin(lam),
                     np.sin(phi)])


def test_level_zero_covers_sphere_area():
    area = sum(area_km2(cell_triangle(face, ())) for face in range(20))
    sphere = 4 * math.pi * EARTH_R ** 2
    assert math.isclose(area, sphere, rel_tol=1e-14)


def test_children_preserve_parent_area():
    rng = random.Random(42)
    for _ in range(200):
        face = rng.randrange(20)
        digits = tuple(rng.randrange(4) for _ in range(rng.randrange(10)))
        parent = cell_triangle(face, digits)
        child_area = sum(area_km2(child) for child in subdivide(parent))
        assert math.isclose(child_area, area_km2(parent), rel_tol=1e-7)


def test_locate_returns_a_containing_cell():
    rng = random.Random(43)
    for _ in range(500):
        lon = rng.uniform(-180, 180)
        lat = math.degrees(math.asin(rng.uniform(-1, 1)))
        level = rng.randrange(13)
        face, digits = locate(lon, lat, level)
        assert contains_point(cell_triangle(face, digits), _point(lon, lat))


def test_icosahedron_has_expected_shape():
    vertices, faces = icosahedron()
    assert vertices.shape == (12, 3)
    assert len(faces) == 20
    assert np.allclose(np.linalg.norm(vertices, axis=1), 1.0)
