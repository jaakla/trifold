"""Optional land-coverage extension for the Trifold Python SDK.

This module depends on Shapely and PyProj.  Core address, location, geometry,
and GeoJSON operations are available from :mod:`trifold.api` without using a
land dataset.
"""

from .classify import LandClassifier

__all__ = ["LandClassifier"]
