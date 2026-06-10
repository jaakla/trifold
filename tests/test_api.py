import pytest

from trifold.api import (
    cell_feature,
    cell_metrics,
    cell_ring,
    locate_address,
    parse_address,
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
