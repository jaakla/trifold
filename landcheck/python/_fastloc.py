"""Fast scalar point location for landcheck.

A dependency-free, pure-float re-statement of ``trifold.core.locate``,
returning the canonical level-L cell index ``(face << 2L) | path_bits``
directly.  The arithmetic (normalized-sum midpoints, plane-side tests
with the -1e-14 tolerance, first-match child order, max-margin fallback)
is bit-identical to the SDK implementation — the test suite cross-checks
the two on a large random sample.  Roughly 20x faster per point than the
numpy-scalar SDK path; for bulk work prefer
``trifold.api.locate_address_batch``.
"""
from __future__ import annotations

from math import sqrt, radians, cos, sin

_EPS = -1e-14
_LON_ROT = radians(7.3)

_FACE_INDEXES = (
    (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
    (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
    (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
    (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
)


def _build_faces():
    phi = (1.0 + sqrt(5.0)) / 2.0
    raw = [
        (-1.0, phi, 0.0), (1.0, phi, 0.0), (-1.0, -phi, 0.0), (1.0, -phi, 0.0),
        (0.0, -1.0, phi), (0.0, 1.0, phi), (0.0, -1.0, -phi), (0.0, 1.0, -phi),
        (phi, 0.0, -1.0), (phi, 0.0, 1.0), (-phi, 0.0, -1.0), (-phi, 0.0, 1.0),
    ]
    c, s = cos(_LON_ROT), sin(_LON_ROT)
    verts = []
    for x, y, z in raw:
        n = sqrt(x * x + y * y + z * z)
        x, y, z = x / n, y / n, z / n
        verts.append((c * x - s * y, s * x + c * y, z))
    faces = [(verts[i], verts[j], verts[k]) for i, j, k in _FACE_INDEXES]
    cents = []
    for v0, v1, v2 in faces:
        cx, cy, cz = v0[0] + v1[0] + v2[0], v0[1] + v1[1] + v2[1], v0[2] + v1[2] + v2[2]
        n = sqrt(cx * cx + cy * cy + cz * cz)
        cents.append((cx / n, cy / n, cz / n))
    return faces, cents


_FACES, _CENTROIDS = _build_faces()


def _mid(a, b):
    x, y, z = a[0] + b[0], a[1] + b[1], a[2] + b[2]
    n = sqrt(x * x + y * y + z * z)
    return (x / n, y / n, z / n)


def _side(a, b, p):
    """dot(cross(a, b), p)"""
    return ((a[1] * b[2] - a[2] * b[1]) * p[0]
            + (a[2] * b[0] - a[0] * b[2]) * p[1]
            + (a[0] * b[1] - a[1] * b[0]) * p[2])


def locate_index(lon: float, lat: float, level: int) -> int:
    """Canonical cell index ``(face << 2*level) | path_bits`` for a point."""
    lam, phi = radians(lon), radians(lat)
    cp = cos(phi)
    p = (cp * cos(lam), cp * sin(lam), sin(phi))

    tri = None
    face = -1
    for f, t in enumerate(_FACES):
        v0, v1, v2 = t
        if (_side(v0, v1, p) >= _EPS and _side(v1, v2, p) >= _EPS
                and _side(v2, v0, p) >= _EPS):
            face, tri = f, t
            break
    if tri is None:  # numeric edge case: nearest face centroid
        best = -2.0
        for f, c in enumerate(_CENTROIDS):
            d = c[0] * p[0] + c[1] * p[1] + c[2] * p[2]
            if d > best:
                best, face = d, f
        tri = _FACES[face]

    path = 0
    v0, v1, v2 = tri
    for _ in range(level):
        m01, m12, m20 = _mid(v0, v1), _mid(v1, v2), _mid(v2, v0)
        children = ((v0, m01, m20), (m01, v1, m12), (m20, m12, v2), (m01, m12, m20))
        digit = -1
        for d, (c0, c1, c2) in enumerate(children):
            if (_side(c0, c1, p) >= _EPS and _side(c1, c2, p) >= _EPS
                    and _side(c2, c0, p) >= _EPS):
                digit = d
                break
        if digit < 0:  # tolerance fallback: max min-margin, first max
            best = None
            for d, (c0, c1, c2) in enumerate(children):
                m = min(_side(c0, c1, p), _side(c1, c2, p), _side(c2, c0, p))
                if best is None or m > best:
                    best, digit = m, d
        v0, v1, v2 = children[digit]
        path = (path << 2) | digit
    return (face << (2 * level)) | path


def index_to_triangle(index: int, level: int):
    """Unit-sphere vertices ``(v0, v1, v2)`` of a canonical cell index."""
    face = index >> (2 * level)
    path = index & ((1 << (2 * level)) - 1)
    v0, v1, v2 = _FACES[face]
    for shift in range(2 * (level - 1), -1, -2):
        digit = (path >> shift) & 3
        m01, m12, m20 = _mid(v0, v1), _mid(v1, v2), _mid(v2, v0)
        if digit == 0:
            v0, v1, v2 = v0, m01, m20
        elif digit == 1:
            v0, v1, v2 = m01, v1, m12
        elif digit == 2:
            v0, v1, v2 = m20, m12, v2
        else:
            v0, v1, v2 = m01, m12, m20
    return v0, v1, v2


def index_to_lonlat_ring(index: int, level: int):
    """Triangle ring in degrees, antimeridian-unwrapped to continuous
    longitudes (may exceed 180), matching the grid GeoJSON convention."""
    from math import atan2, asin, degrees

    ring = []
    for x, y, z in index_to_triangle(index, level):
        ring.append((degrees(atan2(y, x)), degrees(asin(max(-1.0, min(1.0, z))))))
    lons = [lon for lon, _ in ring]
    if max(lons) - min(lons) > 180.0:  # antimeridian crossing: unwrap east
        ring = [(lon + 360.0 if lon < 0.0 else lon, lat) for lon, lat in ring]
    return ring
