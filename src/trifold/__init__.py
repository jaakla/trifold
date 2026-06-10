"""trifold — hierarchical triangular DGGS on the icosahedron."""
__version__ = "0.1.0"

from .address import (encode64, decode64, to_compact, from_compact,
                      to_path, from_path, parent64, children64,
                      is_ancestor, level_of, face_of, path_of, MAX_LEVEL)
from .core import (icosahedron, subdivide, locate, cell_triangle,
                   edge_km, area_km2, densified_ring_xyz,
                   build_export_ring, EARTH_R)
from .classify import LandClassifier
from .grid import build_compacted, expand_to_base, cell_geometry_ring
