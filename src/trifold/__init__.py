"""Trifold Python SDK.

The supported public API is defined in :mod:`trifold.api` and re-exported
here for concise imports.  Land classification is available separately as
``trifold.land.LandClassifier``.
"""
__version__ = "0.1.0"

from .api import *
from .api import __all__ as _api_all

__all__ = ["__version__", *_api_all]
