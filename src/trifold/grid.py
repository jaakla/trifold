"""trifold.grid — quadtree compaction, expansion, export rings."""
import numpy as np
from .core import (icosahedron, subdivide, densified_ring_xyz,
                   contains_point, NORTH, SOUTH, build_export_ring,
                   edge_km, area_km2)

# ---------------------------------------------------------------- gridder
def build_compacted(classifier, base_level, min_level=0, verts_faces=None):
    """
    Quadtree compaction: emit interior cells at the coarsest wholly-inside
    level (>= min_level), boundary cells at base_level.
    Returns list of cell dicts.
    """
    verts, faces = verts_faces if verts_faces else icosahedron()
    out = []

    def face_tri(f):
        i, j, k = faces[f]
        return (verts[i], verts[j], verts[k])

    def recurse(tri, cid, level):
        cls, meta = classifier.classify(tri)
        if cls == 'sea':
            return
        if cls == 'interior' and level >= min_level:
            out.append(_cell(tri, cid, level, True, meta))
            return
        if level == base_level:
            out.append(_cell(tri, cid, level, cls == 'interior', meta))
            return
        for ci, ch in enumerate(subdivide(tri)):
            recurse(ch, f"{cid}{ci}", level + 1)

    for f in range(len(faces)):
        recurse(face_tri(f), f"F{f:02d}-", 0)
    return out


def expand_to_base(cells, base_level, classifier):
    """Uncompacted grid: expand every interior cell to its base_level
    descendants (all of which are interior by exactness of nesting)."""
    out = []
    for c in cells:
        if c['level'] == base_level:
            out.append(c)
            continue
        stack = [(c['tri'], c['cell_id'], c['level'])]
        while stack:
            tri, cid, lvl = stack.pop()
            if lvl == base_level:
                # interior by construction; rebuild ring/meta for export
                _, meta = ('interior',
                           {'pole': 'N' if contains_point(tri, NORTH) else
                                    ('S' if contains_point(tri, SOUTH) else ''),
                            'pts': densified_ring_xyz(tri)})
                out.append(_cell(tri, cid, lvl, True, meta))
                continue
            for ci, ch in enumerate(subdivide(tri)):
                stack.append((ch, f"{cid}{ci}", lvl + 1))
    return out


def _cell(tri, cid, level, interior, meta):
    return {'cell_id': cid, 'level': level, 'tri': tri,
            'interior': interior, 'meta': meta}


def cell_geometry_ring(cell):
    """Final lon/lat ring for export (pole wedge/cap + unwrap handling).
    Returns (ring, pole_flag)."""
    meta = cell['meta']
    pts = densified_ring_xyz(cell['tri'], level=cell['level'])
    return build_export_ring(pts, cell['tri'])
