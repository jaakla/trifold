import pytest

from trifold.api import (
    cell_feature,
    cell_metrics,
    cell_ring,
    locate_address,
    parse_address,
    sample_polyline,
    to_compact,
    to_path,
)


def test_high_level_api_accepts_all_address_forms():
    addr = locate_address(-0.1276, 51.5072, 6)
    identity = (15, (1, 0, 2, 1, 1, 1))

    assert to_compact(addr) == 'TF6958'
    assert parse_address('TF6958') == addr
    assert parse_address('F15-102111') == addr
    assert parse_address(identity) == addr


def test_cell_helpers_share_one_documented_shape():
    metrics = cell_metrics('TF6958')
    feature = cell_feature('TF6958')
    ring = cell_ring('TF6958', precision=6)

    assert metrics['id'] == 'TF6958'
    assert metrics['path'] == to_path(metrics['addr64'])
    assert metrics['level'] == 6
    assert metrics['rhombus_id'] == feature['properties']['rhombus_id']
    assert str(metrics['rhombus_hilbert']) == feature['properties']['rhombus_hilbert']
    assert metrics['hex_id'] == feature['properties']['hex_id']
    assert feature['properties']['addr64'] == str(metrics['addr64'])
    assert feature['geometry']['coordinates'][0] == ring


@pytest.mark.parametrize('address', [-1, 1 << 64, True, object()])
def test_parse_address_rejects_invalid_types_and_ranges(address):
    with pytest.raises((TypeError, ValueError)):
        parse_address(address)


def test_locate_address_validates_public_inputs():
    with pytest.raises(ValueError, match='longitude'):
        locate_address(181, 0, 6)
    with pytest.raises(ValueError, match='latitude'):
        locate_address(0, 91, 6)
    with pytest.raises(ValueError, match='level'):
        locate_address(0, 0, 28)


def test_sample_polyline_vertex_mode_keeps_vertices():
    coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    samples, cumulative_km, segment_ids = sample_polyline(coords, mode='vertex')
    assert len(samples) == 3
    assert list(segment_ids) == [0, 0, 1]
    # ~111 km per degree along the equator/meridian
    assert cumulative_km[0] == 0.0
    assert cumulative_km[1] == pytest.approx(111.2, abs=0.5)
    assert cumulative_km[2] > cumulative_km[1]


def test_sample_polyline_uniform_densifies_and_is_monotonic():
    coords = [(0.0, 0.0), (1.0, 0.0)]
    samples, cumulative_km, segment_ids = sample_polyline(coords, step_km=20.0)
    assert len(samples) > 2                      # densified between vertices
    assert (cumulative_km[1:] >= cumulative_km[:-1]).all()  # monotonic
    assert tuple(samples[0]) == coords[0]        # endpoints preserved
    assert tuple(samples[-1]) == coords[1]
    assert set(segment_ids.tolist()) == {0}


def test_sample_polyline_rejects_short_or_bad_mode():
    with pytest.raises(ValueError):
        sample_polyline([(0.0, 0.0)])
    with pytest.raises(ValueError):
        sample_polyline([(0.0, 0.0), (1.0, 0.0)], mode='nope')
