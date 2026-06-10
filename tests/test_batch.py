"""Tests for vectorised batch locate — must agree with scalar locate."""
import numpy as np
import pytest

import trifold.api as tg


class TestLocateAddressBatch:
    """locate_address_batch must match locate_address point-for-point."""

    def test_matches_scalar_random(self):
        """1 000 random points at level 9 — batch == scalar."""
        rng = np.random.default_rng(42)
        N = 1000
        lons = rng.uniform(-180, 180, N)
        lats = rng.uniform(-90, 90, N)
        level = 9

        batch = tg.locate_address_batch(lons, lats, level)

        mismatches = []
        for i in range(N):
            scalar = tg.locate_address(float(lons[i]), float(lats[i]), level)
            if int(batch[i]) != scalar:
                mismatches.append(
                    f"  [{i}] ({lons[i]:.6f}, {lats[i]:.6f}): "
                    f"batch={tg.to_compact(int(batch[i]))} "
                    f"scalar={tg.to_compact(scalar)}")
        assert not mismatches, (
            f"{len(mismatches)} mismatches:\n" + "\n".join(mismatches[:20]))

    def test_known_london(self):
        """London at level 6 → TF6958."""
        addr = tg.locate_address_batch([-0.1276], [51.5072], 6)
        assert tg.to_compact(int(addr[0])) == "TF6958"

    def test_known_cities(self):
        """Multiple cities at level 6 — batch == scalar."""
        cities = [
            (-0.1276, 51.5072),    # London
            (24.7536, 59.4370),    # Tallinn
            (139.6917, 35.6895),   # Tokyo
            (-73.9857, 40.7484),   # New York
            (151.2093, -33.8688),  # Sydney
        ]
        lons = [c[0] for c in cities]
        lats = [c[1] for c in cities]
        batch = tg.locate_address_batch(lons, lats, 6)
        for i, (lon, lat) in enumerate(cities):
            scalar = tg.locate_address(lon, lat, 6)
            assert int(batch[i]) == scalar, (
                f"{lon},{lat}: {tg.to_compact(int(batch[i]))} != "
                f"{tg.to_compact(scalar)}")

    def test_poles(self):
        """Poles resolve correctly and match scalar."""
        lons = [0.0, 0.0]
        lats = [90.0, -90.0]
        batch = tg.locate_address_batch(lons, lats, 6)
        for i in range(2):
            scalar = tg.locate_address(lons[i], lats[i], 6)
            assert int(batch[i]) == scalar

    def test_antimeridian(self):
        """Points near ±180° match scalar."""
        lons = [179.9, -179.9, 180.0, -180.0]
        lats = [0.0, 0.0, 0.0, 0.0]
        batch = tg.locate_address_batch(lons, lats, 6)
        for i in range(4):
            scalar = tg.locate_address(lons[i], lats[i], 6)
            assert int(batch[i]) == scalar

    def test_multiple_levels(self):
        """Various levels produce matching results."""
        lons = [-0.1276, 24.7536, 139.6917]
        lats = [51.5072, 59.4370, 35.6895]
        for level in [0, 1, 3, 6, 9, 12, 15]:
            batch = tg.locate_address_batch(lons, lats, level)
            for i in range(3):
                scalar = tg.locate_address(lons[i], lats[i], level)
                assert int(batch[i]) == scalar, (
                    f"level={level}, point {i}")

    def test_empty_input(self):
        """Empty arrays → empty result."""
        addr = tg.locate_address_batch([], [], 6)
        assert len(addr) == 0
        assert addr.dtype == np.uint64

    def test_chunking_invariance(self):
        """Results must be identical regardless of chunk size."""
        rng = np.random.default_rng(99)
        N = 500
        lons = rng.uniform(-180, 180, N)
        lats = rng.uniform(-90, 90, N)
        level = 6

        big = tg.locate_address_batch(lons, lats, level, chunk_size=N)
        small = tg.locate_address_batch(lons, lats, level, chunk_size=73)
        np.testing.assert_array_equal(big, small)

    def test_output_dtype(self):
        """Output must be uint64."""
        addr = tg.locate_address_batch([0.0], [0.0], 6)
        assert addr.dtype == np.uint64

    def test_large_batch(self):
        """50 k points at level 9 should complete without error."""
        rng = np.random.default_rng(123)
        N = 50_000
        lons = rng.uniform(-180, 180, N)
        lats = rng.uniform(-90, 90, N)
        addr = tg.locate_address_batch(lons, lats, 9, chunk_size=10_000)
        assert len(addr) == N
        assert addr.dtype == np.uint64
        # spot-check a handful
        for i in [0, N // 4, N // 2, 3 * N // 4, N - 1]:
            scalar = tg.locate_address(float(lons[i]), float(lats[i]), 9)
            assert int(addr[i]) == scalar


class TestLocateBatchRaw:
    """Lower-level locate_batch returning (faces, path_bits)."""

    def test_faces_in_range(self):
        rng = np.random.default_rng(7)
        lons = rng.uniform(-180, 180, 200)
        lats = rng.uniform(-90, 90, 200)
        faces, _ = tg.locate_batch(lons, lats, 6)
        assert faces.dtype == np.int32
        assert np.all((faces >= 0) & (faces < 20))

    def test_path_bits_width(self):
        """path_bits should fit within 2*level bits."""
        _, path_bits = tg.locate_batch([0.0], [0.0], 6)
        max_val = (1 << 12) - 1  # 2*6 = 12 bits
        assert int(path_bits[0]) <= max_val
