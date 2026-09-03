"""Dependency-free scalar T3 point location used by settlementcheck."""
from __future__ import annotations

from math import asin, atan2, cos, degrees, radians, sin, sqrt

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
        (-1.0, phi, 0.0), (1.0, phi, 0.0), (-1.0, -phi, 0.0),
        (1.0, -phi, 0.0), (0.0, -1.0, phi), (0.0, 1.0, phi),
        (0.0, -1.0, -phi), (0.0, 1.0, -phi), (phi, 0.0, -1.0),
        (phi, 0.0, 1.0), (-phi, 0.0, -1.0), (-phi, 0.0, 1.0),
    ]
    c, s = cos(_LON_ROT), sin(_LON_ROT)
    verts = []
    for x, y, z in raw:
        n = sqrt(x * x + y * y + z * z)
        x, y, z = x / n, y / n, z / n
        verts.append((c * x - s * y, s * x + c * y, z))
    faces = [(verts[i], verts[j], verts[k]) for i, j, k in _FACE_INDEXES]
    centroids = []
    for v0, v1, v2 in faces:
        x = v0[0] + v1[0] + v2[0]
        y = v0[1] + v1[1] + v2[1]
        z = v0[2] + v1[2] + v2[2]
        n = sqrt(x * x + y * y + z * z)
        centroids.append((x / n, y / n, z / n))
    return faces, centroids


_FACES, _CENTROIDS = _build_faces()


def _mid(a, b):
    x, y, z = a[0] + b[0], a[1] + b[1], a[2] + b[2]
    n = sqrt(x * x + y * y + z * z)
    return x / n, y / n, z / n


def _side(a, b, p):
    return ((a[1] * b[2] - a[2] * b[1]) * p[0]
            + (a[2] * b[0] - a[0] * b[2]) * p[1]
            + (a[0] * b[1] - a[1] * b[0]) * p[2])


def locate_index(lon: float, lat: float, level: int) -> int:
    """Return ``(face << 2*level) | path`` for WGS84 lon/lat."""
    lam, phi = radians(lon), radians(lat)
    cp = cos(phi)
    point = (cp * cos(lam), cp * sin(lam), sin(phi))
    face, tri = -1, None
    for candidate, value in enumerate(_FACES):
        v0, v1, v2 = value
        if (_side(v0, v1, point) >= _EPS
                and _side(v1, v2, point) >= _EPS
                and _side(v2, v0, point) >= _EPS):
            face, tri = candidate, value
            break
    if tri is None:
        best = -2.0
        for candidate, centre in enumerate(_CENTROIDS):
            dot = sum(a * b for a, b in zip(centre, point))
            if dot > best:
                best, face = dot, candidate
        tri = _FACES[face]

    path = 0
    v0, v1, v2 = tri
    for _ in range(level):
        m01, m12, m20 = _mid(v0, v1), _mid(v1, v2), _mid(v2, v0)
        children = (
            (v0, m01, m20), (m01, v1, m12),
            (m20, m12, v2), (m01, m12, m20),
        )
        digit = -1
        for candidate, child in enumerate(children):
            c0, c1, c2 = child
            if (_side(c0, c1, point) >= _EPS
                    and _side(c1, c2, point) >= _EPS
                    and _side(c2, c0, point) >= _EPS):
                digit = candidate
                break
        if digit < 0:
            margins = [min(_side(a, b, point), _side(b, c, point),
                           _side(c, a, point)) for a, b, c in children]
            digit = max(range(4), key=margins.__getitem__)
        v0, v1, v2 = children[digit]
        path = (path << 2) | digit
    return (face << (2 * level)) | path


def index_to_triangle(index: int, level: int):
    face = index >> (2 * level)
    path = index & ((1 << (2 * level)) - 1)
    v0, v1, v2 = _FACES[face]
    for shift in range(2 * (level - 1), -1, -2):
        digit = (path >> shift) & 3
        m01, m12, m20 = _mid(v0, v1), _mid(v1, v2), _mid(v2, v0)
        children = (
            (v0, m01, m20), (m01, v1, m12),
            (m20, m12, v2), (m01, m12, m20),
        )
        v0, v1, v2 = children[digit]
    return v0, v1, v2


def index_to_lonlat_ring(index: int, level: int):
    ring = [(degrees(atan2(y, x)), degrees(asin(max(-1.0, min(1.0, z)))))
            for x, y, z in index_to_triangle(index, level)]
    if max(p[0] for p in ring) - min(p[0] for p in ring) > 180.0:
        ring = [(lon + 360.0 if lon < 0.0 else lon, lat)
                for lon, lat in ring]
    return ring
