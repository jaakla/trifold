import pytest

import trifold.api as tg


def _rectangle(min_lon, min_lat, max_lon, max_lat):
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lon, min_lat],
            [max_lon, min_lat],
            [max_lon, max_lat],
            [min_lon, max_lat],
            [min_lon, min_lat],
        ]],
    }


def test_bbox_cover_includes_located_points_inside_bbox():
    bbox = (-0.3, 51.4, 0.1, 51.6)
    cells = tg.bbox_cover(*bbox, level=6)
    samples = [
        (-0.1276, 51.5072),
        (-0.25, 51.45),
        (0.05, 51.55),
    ]

    assert cells == sorted(cells)
    assert len(cells) == len(set(cells))
    for lon, lat in samples:
        assert tg.locate_address(lon, lat, 6) in cells


def test_bbox_cover_world_at_level_zero_returns_all_faces():
    cells = tg.bbox_cover(-180, -90, 180, 90, level=0)

    assert [tg.face_of(cell) for cell in cells] == list(range(20))
    assert all(tg.level_of(cell) == 0 for cell in cells)


def test_bbox_cover_handles_antimeridian_crossing_query():
    cells = tg.bbox_cover(179.0, -1.0, -179.0, 1.0, level=5)

    assert tg.locate_address(179.5, 0.0, 5) in cells
    assert tg.locate_address(-179.5, 0.0, 5) in cells


def test_polyfill_rectangle_matches_bbox_cover():
    bbox = (-1.0, 51.0, 0.5, 52.0)
    polygon = _rectangle(*bbox)

    assert tg.polyfill(polygon, level=5) == tg.bbox_cover(*bbox, level=5)


def test_polyfill_accepts_feature_and_feature_collection():
    polygon = _rectangle(-0.3, 51.4, 0.1, 51.6)
    feature = {"type": "Feature", "properties": {}, "geometry": polygon}
    collection = {"type": "FeatureCollection", "features": [feature]}

    assert tg.polyfill(feature, level=6) == tg.polyfill(polygon, level=6)
    assert tg.polyfill(collection, level=6) == tg.polyfill(polygon, level=6)


def test_centroid_mode_is_subset_of_intersects_mode_for_bbox():
    bbox = (-5.0, 50.0, 5.0, 55.0)
    intersects = set(tg.bbox_cover(*bbox, level=5))
    centroid = set(tg.bbox_cover(*bbox, level=5, mode="centroid"))

    assert centroid
    assert centroid <= intersects


def test_cover_ranges_wraps_descendant_ranges_in_order():
    cells = tg.bbox_cover(-0.3, 51.4, 0.1, 51.6, level=6)
    ranges = tg.cover_ranges(reversed(cells))

    assert ranges == sorted(ranges)
    for low, high in ranges:
        assert low <= high
    assert all(any(low <= cell <= high for low, high in ranges)
               for cell in cells)


def test_cover_helpers_validate_inputs():
    with pytest.raises(ValueError, match="level"):
        tg.bbox_cover(-1, 0, 1, 1, 28)
    with pytest.raises(ValueError, match="mode"):
        tg.bbox_cover(-1, 0, 1, 1, 5, mode="within")
    with pytest.raises(ValueError, match="latitudes"):
        tg.polyfill(_rectangle(-1, -91, 1, 1), level=5)
    with pytest.raises(ValueError, match="geometry"):
        tg.polyfill({"type": "LineString", "coordinates": []}, level=5)
