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


# ------------------------------------------------------- batch locate
def _batch_plane_side(a, b, pts):
    """Vectorised scalar triple product  dot(cross(a, b), pts).

    All inputs shape ``[N, 3]``.  Returns shape ``[N]``.
    Inlined to avoid allocating the intermediate cross-product array.
    """
    return ((a[:, 1] * b[:, 2] - a[:, 2] * b[:, 1]) * pts[:, 0] +
            (a[:, 2] * b[:, 0] - a[:, 0] * b[:, 2]) * pts[:, 1] +
            (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * pts[:, 2])


def _locate_chunk(points, level, face_tris, edge_normals):
    """Locate a chunk of *N* unit-vector points on the sphere.

    Parameters
    ----------
    points : ndarray [N, 3]
        Unit vectors (pre-converted from lon/lat).
    level : int
        Subdivision depth.
    face_tris : ndarray [20, 3, 3]
        Precomputed icosahedron face vertices.
    edge_normals : ndarray [20, 3, 3]
        Precomputed ``cross(v_i, v_j)`` for each face edge.

    Returns
    -------
    faces : ndarray int32 [N]
        Icosahedron face index (0..19).
    path_bits : ndarray uint64 [N]
        Base-4 path digits, right-aligned (``2 * level`` significant bits).
    """
    N = len(points)

    # ---- face assignment: test all points against all 20 faces ----
    # dots[n, f, e] = dot(edge_normals[f, e], points[n])
    dots = np.einsum('fej,nj->nfe', edge_normals, points)   # [N, 20, 3]
    inside = (dots >= -1e-14).all(axis=2)                    # [N, 20]
    has_match = inside.any(axis=1)
    # argmax on boolean returns index of first True
    faces = np.where(has_match,
                     np.argmax(inside, axis=1), 0).astype(np.int32)

    # fallback: nearest face centroid for numeric edge cases
    no_match = ~has_match
    if np.any(no_match):
        centroids = face_tris.mean(axis=1)                   # [20, 3]
        centroids /= np.linalg.norm(centroids, axis=1, keepdims=True)
        faces[no_match] = np.argmax(
            points[no_match] @ centroids.T, axis=1).astype(np.int32)

    # ---- initialise per-point triangle vertices ----
    v0 = face_tris[faces, 0].copy()                          # [N, 3]
    v1 = face_tris[faces, 1].copy()
    v2 = face_tris[faces, 2].copy()

    # ---- descend through subdivision levels ----
    path_bits = np.zeros(N, dtype=np.uint64)

    for _ in range(level):
        # midpoints (normalised: great-circle midpoint on the sphere)
        m01 = v0 + v1
        m01 /= np.linalg.norm(m01, axis=1, keepdims=True)
        m12 = v1 + v2
        m12 /= np.linalg.norm(m12, axis=1, keepdims=True)
        m20 = v2 + v0
        m20 /= np.linalg.norm(m20, axis=1, keepdims=True)

        # four children: same vertex order as scalar subdivide()
        ch_a = (v0,  m01, m20, m01)
        ch_b = (m01, v1,  m12, m12)
        ch_c = (m20, m12, v2,  m20)

        digit = np.full(N, -1, dtype=np.int32)
        best_margin = np.full(N, -np.inf)
        best_d = np.zeros(N, dtype=np.int32)
        nv0 = np.empty_like(v0)
        nv1 = np.empty_like(v1)
        nv2 = np.empty_like(v2)

        for d in range(4):
            a, b, c = ch_a[d], ch_b[d], ch_c[d]
            s0 = _batch_plane_side(a, b, points)
            s1 = _batch_plane_side(b, c, points)
            s2 = _batch_plane_side(c, a, points)

            ok = (s0 >= -1e-14) & (s1 >= -1e-14) & (s2 >= -1e-14)
            margin = np.minimum(np.minimum(s0, s1), s2)

            # track best margin for tolerance fallback
            better = margin > best_margin
            best_margin[better] = margin[better]
            best_d[better] = d

            # first match wins (same tie-break as scalar locate)
            assign = ok & (digit < 0)
            digit[assign] = d
            nv0[assign] = a[assign]
            nv1[assign] = b[assign]
            nv2[assign] = c[assign]

        # fallback: choose child with highest minimum margin
        fb = digit < 0
        if np.any(fb):
            digit[fb] = best_d[fb]
            for d in range(4):
                sel = fb & (best_d == d)
                if np.any(sel):
                    nv0[sel] = ch_a[d][sel]
                    nv1[sel] = ch_b[d][sel]
                    nv2[sel] = ch_c[d][sel]

        v0, v1, v2 = nv0, nv1, nv2
        path_bits = (path_bits << np.uint64(2)) | digit.astype(np.uint64)

    return faces, path_bits


def locate_batch(lons, lats, level, chunk_size=1_000_000):
    """Vectorised point location for arrays of coordinates.

    Equivalent to calling :func:`locate` on every element, but processes
    the full array with numpy — typically **100–1000× faster** than a
    Python loop.

    Parameters
    ----------
    lons, lats : array-like of float
        Longitude (−180 .. 180) and latitude (−90 .. 90).
    level : int
        Subdivision level (0 .. 27).
    chunk_size : int, optional
        Maximum points per processing chunk.  Controls peak memory;
        ~300 MB per 1 M points.

    Returns
    -------
    faces : ndarray of int32
        Icosahedron face index (0 .. 19) per point.
    path_bits : ndarray of uint64
        Base-4 path digits, right-aligned (``2 × level`` significant
        bits).  Left-align for the addr64 path field with
        ``path_bits << (2 * (27 - level))``.
    """
    lons = np.asarray(lons, dtype=np.float64).ravel()
    lats = np.asarray(lats, dtype=np.float64).ravel()
    if len(lons) != len(lats):
        raise ValueError("lons and lats must have the same length")
    if not 0 <= level <= 27:
        raise ValueError("level must be in 0..27")
    N = len(lons)
    if N == 0:
        return np.array([], dtype=np.int32), np.array([], dtype=np.uint64)

    # precompute icosahedron geometry (once per call)
    verts, faces_list = icosahedron()
    face_tris = np.array([[verts[i], verts[j], verts[k]]
                          for i, j, k in faces_list])        # [20, 3, 3]
    edge_normals = np.empty((20, 3, 3))
    for f in range(20):
        a, b, c = face_tris[f]
        edge_normals[f, 0] = np.cross(a, b)
        edge_normals[f, 1] = np.cross(b, c)
        edge_normals[f, 2] = np.cross(c, a)

    # convert lon/lat → unit vectors
    lam = np.radians(lons)
    phi = np.radians(lats)
    cos_phi = np.cos(phi)
    points = np.column_stack([cos_phi * np.cos(lam),
                              cos_phi * np.sin(lam),
                              np.sin(phi)])                  # [N, 3]

    all_faces = np.empty(N, dtype=np.int32)
    all_paths = np.empty(N, dtype=np.uint64)
    for start in range(0, N, chunk_size):
        end = min(start + chunk_size, N)
        f, p = _locate_chunk(points[start:end], level,
                             face_tris, edge_normals)
        all_faces[start:end] = f
        all_paths[start:end] = p

    return all_faces, all_paths
