import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'build_grids.py'
SPEC = importlib.util.spec_from_file_location('build_grids', SCRIPT)
build_grids = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_grids)


def test_download_land_validates_and_installs_atomically(tmp_path):
    payload = json.dumps({
        'type': 'FeatureCollection',
        'features': [{'type': 'Feature', 'properties': {},
                      'geometry': {'type': 'Polygon', 'coordinates': []}}],
    }).encode()
    source = tmp_path / 'source.geojson'
    source.write_bytes(payload)
    target = tmp_path / 'nested' / 'land.geojson'

    build_grids.download_land(
        target, source.as_uri(), hashlib.sha256(payload).hexdigest())

    assert target.read_bytes() == payload
    assert not list(target.parent.glob('.ne_50m_land-*'))


def test_download_land_rejects_bad_checksum(tmp_path):
    source = tmp_path / 'source.geojson'
    source.write_text('{"type":"FeatureCollection","features":[{}]}')
    target = tmp_path / 'land.geojson'

    with pytest.raises(RuntimeError, match='checksum mismatch'):
        build_grids.download_land(target, source.as_uri(), '0' * 64)

    assert not target.exists()


def test_custom_missing_land_path_is_not_downloaded(tmp_path):
    path = tmp_path / 'custom.geojson'
    with pytest.raises(FileNotFoundError, match='Omit --land'):
        build_grids.ensure_land(path, is_default=False)


def test_dissolve_features_groups_without_recomputing_cells():
    features = [
        {
            'type': 'Feature',
            'properties': {
                'rhombus_id': 'R00-01-0-0', 'rhombus_hilbert': '1',
                'hex_id': 'HF00-01-1-0-1', 'level': 1,
                'interior': True, 'area_km2': 2, 'pole': '', 'xam': False,
            },
            'geometry': {'type': 'Polygon', 'coordinates': [[
                [0, 0], [1, 0], [0, 1], [0, 0],
            ]]},
        },
        {
            'type': 'Feature',
            'properties': {
                'rhombus_id': 'R00-01-0-0', 'rhombus_hilbert': '1',
                'hex_id': 'HF00-01-1-0-0', 'level': 1,
                'interior': False, 'area_km2': 3, 'pole': '', 'xam': False,
            },
            'geometry': {'type': 'Polygon', 'coordinates': [[
                [1, 0], [1, 1], [0, 1], [1, 0],
            ]]},
        },
    ]

    grouped = build_grids.dissolve_features(features, 'rhombus')

    assert len(grouped) == 1
    assert grouped[0]['properties']['triangle_count'] == 2
    assert grouped[0]['properties']['area_km2'] == 5
    assert grouped[0]['properties']['interior'] is False
    assert grouped[0]['geometry']['type'] == 'Polygon'
