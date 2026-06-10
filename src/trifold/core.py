"""
trifold.core — spherical geometry of the icosahedral triangular grid.

Special-case handling:
  * Antimeridian: cell rings are unwrapped to continuous longitudes (may
    exceed +/-180); classification of such cells runs against land copies
    translated by +/-360 deg.
  * Poles: the icosahedron is oriented with no vertex at the poles, so each
    pole lies INSIDE one triangle per level. Pole-containing or near-polar
    cells are classified in a polar azimuthal-equidistant frame (AEQD),
    where their rings are ordinary polygons. For export, pole cells get a
    polar-cap ring representation.
  * The icosahedron is rotated +7.3 deg in longitude so no vertex sits
    exactly on the +/-180 meridian (avoids atan2 sign instability).
"""
import numpy as np

EARTH_R = 6371.0088  # km
LON_ROT = np.radians(7.3)


# ---------------------------------------------------------------- basics
def _norm(p):
    return p / np.linalg.norm(p)


def icosahedron():
    phi = (1 + np.sqrt(5)) / 2
    v = np.array([
        [-1,  phi, 0], [1,  phi, 0], [-1, -phi, 0], [1, -phi, 0],
        [0, -1,  phi], [0, 1,  phi], [0, -1, -phi], [0, 1, -phi],
        [ phi, 0, -1], [ phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1],
    ], dtype=float)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    # rotate about z by LON_ROT to move vertices off the +/-180 meridian
    c, s = np.cos(LON_ROT), np.sin(LON_ROT)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    v = v @ R.T
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    return v, faces


def slerp(p, q, t):
    dot = np.clip(np.dot(p, q), -1, 1)
    om = np.arccos(dot)
    if om < 1e-12:
        return p.copy()
    return (np.sin((1 - t) * om) * p + np.sin(t * om) * q) / np.sin(om)


def xyz_to_lonlat(p):
    return (np.degrees(np.arctan2(p[1], p[0])),
            np.degrees(np.arcsin(np.clip(p[2], -1, 1))))


def subdivide(tri):
    v0, v1, v2 = tri
    m01, m12, m20 = _norm(v0 + v1), _norm(v1 + v2), _norm(v2 + v0)
    return [(v0, m01, m20), (m01, v1, m12), (m20, m12, v2), (m01, m12, m20)]


def edge_km(tri):
    v0, v1, v2 = tri
    a = [np.arccos(np.clip(np.dot(x, y), -1, 1))
         for x, y in ((v0, v1), (v1, v2), (v2, v0))]
    return float(np.mean(a)) * EARTH_R


def area_km2(tri):
    """Spherical excess (L'Huilier-free: via angles between edge planes)."""
    v0, v1, v2 = tri
    def ang(a, b, c):
        # angle at vertex a between great circles a-b and a-c
        n1 = np.cross(a, b); n2 = np.cross(a, c)
        return np.arccos(np.clip(np.dot(n1, n2) /
                                 (np.linalg.norm(n1) * np.linalg.norm(n2)),
                                 -1, 1))
    E = ang(v0, v1, v2) + ang(v1, v2, v0) + ang(v2, v0, v1) - np.pi
    return float(E) * EARTH_R ** 2


def contains_point(tri, p):
    """Exact point-in-spherical-triangle via plane-side tests."""
    v0, v1, v2 = tri
    d0 = np.dot(np.cross(v0, v1), p)
    d1 = np.dot(np.cross(v1, v2), p)
    d2 = np.dot(np.cross(v2, v0), p)
    return (d0 >= -1e-14 and d1 >= -1e-14 and d2 >= -1e-14)


NORTH = np.array([0.0, 0.0, 1.0])
SOUTH = np.array([0.0, 0.0, -1.0])


# ---------------------------------------------------------------- rings
EXPORT_DEPTH = 8  # densify all edges to the level-8 sub-lattice (~27 km segs)


def _edge_points(a, b, n_halvings):
    """Recursive normalized-midpoint subdivision of geodesic edge a->b.
    Produces the exact sub-lattice points, bitwise-consistent across
    cells of different levels sharing (part of) the edge."""
    if n_halvings <= 0:
        return [a]
    m = _norm(a + b)
    return _edge_points(a, m, n_halvings - 1) + _edge_points(m, b, n_halvings - 1)


def densified_ring_xyz(tri, level=None, depth=EXPORT_DEPTH, max_seg_deg=0.75):
    """Closed ring of unit vectors along geodesic edges.
    If `level` is given, edges are subdivided (depth - level) times using
    the recursive midpoint scheme, so adjacent cells of different levels
    share identical intermediate points (exact TopoJSON arc sharing).
    Otherwise falls back to uniform slerp densification."""
    pts = []
    edges = ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))
    if level is not None:
        n_halvings = max(0, depth - level)
        for a, b in edges:
            pts.extend(_edge_points(a, b, n_halvings))
        return pts
    for a, b in edges:
        arc = np.degrees(np.arccos(np.clip(np.dot(a, b), -1, 1)))
        n = max(2, int(np.ceil(arc / max_seg_deg)) + 1)
        for t in np.linspace(0, 1, n, endpoint=False):
            pts.append(slerp(a, b, t))
    return pts


def unwrap_ring_lonlat(pts_xyz):
    """lon/lat ring with continuous longitudes (no +/-360 jumps)."""
    ring = []
    prev = None
    off = 0.0
    for p in pts_xyz:
        lon, lat = xyz_to_lonlat(p)
        lon += off
        if prev is not None:
            while lon - prev > 180:
                lon -= 360; off -= 360
            while lon - prev < -180:
                lon += 360; off += 360
        ring.append((lon, lat))
        prev = lon
    # recentre: keep mean lon within (-180, 180]
    mean = np.mean([p[0] for p in ring])
    shift = 0.0
    while mean + shift > 180:
        shift -= 360
    while mean + shift <= -180:
        shift += 360
    return [(lon + shift, lat) for lon, lat in ring]


def build_export_ring(pts_xyz, tri):
    """
    Final lon/lat ring for export. Handles three pole situations:
      * pole is a ring point (vertex/edge of the cell) -> meridian-wedge
        representation: the pole point is replaced by two points at
        lat +/-90 carrying the longitudes of its ring neighbours;
      * pole strictly inside the cell -> polar-cap representation;
      * otherwise -> plain unwrapped ring.
    Returns (ring, pole_flag) with pole_flag in {'', 'vertex', 'interior'}.
    """
    POLE_Z = 1 - 1e-9
    pole_idx = [i for i, p in enumerate(pts_xyz) if abs(p[2]) >= POLE_Z]

    if pole_idx:
        north = pts_xyz[pole_idx[0]][2] > 0
        polelat = 90.0 if north else -90.0
        n = len(pts_xyz)
        # unwrap longitudes of non-pole points in ring order
        lonlat = {}
        prev_lon = None
        off = 0.0
        order = [i for i in range(n) if i not in pole_idx]
        for i in order:
            lon, lat = xyz_to_lonlat(pts_xyz[i])
            lon += off
            if prev_lon is not None:
                while lon - prev_lon > 180:
                    lon -= 360; off -= 360
                while lon - prev_lon < -180:
                    lon += 360; off += 360
            lonlat[i] = (lon, lat)
            prev_lon = lon
        ring = []
        for i in range(n):
            if i in pole_idx:
                iprev = (i - 1) % n
                inext = (i + 1) % n
                while iprev in pole_idx:
                    iprev = (iprev - 1) % n
                while inext in pole_idx:
                    inext = (inext + 1) % n
                ring.append((lonlat[iprev][0], polelat))
                ring.append((lonlat[inext][0], polelat))
            else:
                ring.append(lonlat[i])
        return _recenter(ring), 'vertex'

    if contains_point(tri, NORTH) or contains_point(tri, SOUTH):
        north = contains_point(tri, NORTH)
        polelat = 90.0 if north else -90.0
        ll = sorted((xyz_to_lonlat(p) for p in pts_xyz), key=lambda q: q[0])
        ring = ll + [(180.0, polelat), (-180.0, polelat)]
        return ring, 'interior'

    return unwrap_ring_lonlat(pts_xyz), ''


def _recenter(ring):
    mean = np.mean([p[0] for p in ring])
    shift = 0.0
    while mean + shift > 180:
        shift -= 360
    while mean + shift <= -180:
        shift += 360
    return [(lon + shift, lat) for lon, lat in ring]




# ---------------------------------------------------------------- locate
def locate(lon, lat, level, verts_faces=None):
    """Point location: (lon, lat) -> base-4 digit path at given level.
    Returns (face, digits). Uses exact plane-side tests; ties on shared
    edges resolve to the first matching cell (deterministic)."""
    verts, faces = verts_faces if verts_faces else icosahedron()
    lam, phi = np.radians(lon), np.radians(lat)
    p = np.array([np.cos(phi) * np.cos(lam),
                  np.cos(phi) * np.sin(lam),
                  np.sin(phi)])
    face = None
    tri = None
    for f, (i, j, k) in enumerate(faces):
        t = (verts[i], verts[j], verts[k])
        if contains_point(t, p):
            face, tri = f, t
            break
    if face is None:                       # numeric edge case: nearest face
        cents = [_norm(verts[i] + verts[j] + verts[k]) for i, j, k in faces]
        face = int(np.argmax([np.dot(c, p) for c in cents]))
        i, j, k = faces[face]
        tri = (verts[i], verts[j], verts[k])
    digits = []
    for _ in range(level):
        for d, ch in enumerate(subdivide(tri)):
            if contains_point(ch, p):
                digits.append(d)
                tri = ch
                break
        else:                              # tolerance fallback: max margin
            margins = []
            for ch in subdivide(tri):
                v0, v1, v2 = ch
                m = min(np.dot(np.cross(v0, v1), p),
                        np.dot(np.cross(v1, v2), p),
                        np.dot(np.cross(v2, v0), p))
                margins.append(m)
            d = int(np.argmax(margins))
            digits.append(d)
            tri = subdivide(tri)[d]
    return face, tuple(digits)


def cell_triangle(face, digits, verts_faces=None):
    """Address -> spherical triangle (3 unit vectors)."""
    verts, faces = verts_faces if verts_faces else icosahedron()
    i, j, k = faces[face]
    tri = (verts[i], verts[j], verts[k])
    for d in digits:
        tri = subdivide(tri)[d]
    return tri
