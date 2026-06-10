"""
trifold.address — three equivalent encodings of one cell identity.

A cell is (face, path) where face in 0..19 and path is a sequence of
base-4 digits (one per subdivision level): 0,1,2 = corner children
(toward parent vertices 0,1,2), 3 = central (orientation-flipped) child.

Encodings
---------
1. addr64 (uint64)  — for compute.
     bits 63..59  face   (5 bits, 0..19)
     bits 58..5   path digits, 2 bits each, LEFT-aligned (d1 at bits 58..57)
     bits 4..0    level  (5 bits, 0..27)
   Properties: numeric sort == hierarchical (Z-order) sort within a face;
   descendants occupy one integer range; ancestor test is a shift+compare.

2. compact (string) — for humans, URLs, labels.  'T' + base32(face) +
   base32(level) + base32(path bits, right-padded to 5-bit chars).
   Crockford base32 alphabet (no I, L, O, U). A level-6 cell is 6 chars,
   e.g. 'T96QXZ'; max (level 27) is 14 chars.

3. path (string)    — for teaching/debugging: 'F09-312012' shows the
   tree descent digit by digit. Level == number of digits.
"""
from __future__ import annotations

B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford
B32_INV = {c: i for i, c in enumerate(B32)}
for _c, _i in [('I', 1), ('L', 1), ('O', 0), ('U', 27)]:  # leniency
    B32_INV[_c] = _i

MAX_LEVEL = 27
LEVEL_BITS = 5
PATH_BITS = 2 * MAX_LEVEL
PATH_MASK = (1 << PATH_BITS) - 1

__all__ = ['encode64', 'decode64', 'to_compact', 'from_compact',
           'to_path', 'from_path', 'parent64', 'children64', 'level_of',
           'face_of', 'path_of', 'is_ancestor', 'descendant_range',
           'lattice_triangle', 'rhombus_coords', 'rhombus_id',
           'rhombus64', 'decode_rhombus64', 'hex_id', 'MAX_LEVEL']

# Ten fixed pairs of adjacent icosahedron faces.  Each pair is a base
# diamond.  The edge endpoints are global icosahedron vertex indexes and
# define a common coordinate direction on both halves of the diamond.
DIAMONDS = (
    (0, 1, (0, 5)), (2, 3, (0, 7)), (4, 7, (10, 11)),
    (5, 15, (5, 9)), (6, 16, (4, 11)), (8, 17, (6, 10)),
    (9, 18, (7, 8)), (10, 11, (3, 4)), (12, 13, (3, 6)),
    (14, 19, (8, 9)),
)

ICO_FACES = (
    (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
    (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
    (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
    (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
)

FACE_DIAMOND = {}
for _diamond, (_face_a, _face_b, _edge) in enumerate(DIAMONDS):
    FACE_DIAMOND[_face_a] = (_diamond, 0, _edge)
    FACE_DIAMOND[_face_b] = (_diamond, 1, _edge)


# ----------------------------------------------------------- uint64 core
def encode64(face: int, digits: tuple[int, ...] | list[int]) -> int:
    level = len(digits)
    if not 0 <= face < 20:
        raise ValueError(f"face {face} out of range 0..19")
    if level > MAX_LEVEL:
        raise ValueError(f"level {level} > {MAX_LEVEL}")
    path = 0
    for d in digits:
        if not 0 <= d <= 3:
            raise ValueError(f"path digit {d} out of range 0..3")
        path = (path << 2) | d
    path <<= 2 * (MAX_LEVEL - level)           # left-align
    return (face << 59) | (path << LEVEL_BITS) | level


def decode64(a: int) -> tuple[int, tuple[int, ...]]:
    face = (a >> 59) & 0x1F
    level = a & 0x1F
    path = (a >> LEVEL_BITS) & PATH_MASK
    digits = tuple((path >> (PATH_BITS - 2 * (i + 1))) & 0x3
                   for i in range(level))
    return face, digits


def face_of(a: int) -> int:
    return (a >> 59) & 0x1F


def level_of(a: int) -> int:
    return a & 0x1F


def path_of(a: int) -> tuple[int, ...]:
    return decode64(a)[1]


def parent64(a: int) -> int:
    level = level_of(a)
    if level == 0:
        raise ValueError("level-0 cell has no parent")
    parent_level = level - 1
    shift = PATH_BITS - 2 * parent_level
    path = ((a >> LEVEL_BITS) & PATH_MASK) >> shift << shift
    return (face_of(a) << 59) | (path << LEVEL_BITS) | parent_level


def children64(a: int) -> list[int]:
    level = level_of(a)
    if level >= MAX_LEVEL:
        raise ValueError("at max level")
    child_level = level + 1
    shift = PATH_BITS - 2 * child_level
    path = (a >> LEVEL_BITS) & PATH_MASK
    face = face_of(a) << 59
    return [face | ((path | (d << shift)) << LEVEL_BITS) | child_level
            for d in range(4)]


def is_ancestor(a: int, b: int) -> bool:
    """True if a is an ancestor of (or equal to) b."""
    if face_of(a) != face_of(b):
        return False
    la, lb = level_of(a), level_of(b)
    if la > lb:
        return False
    mask_bits = 2 * la
    if not mask_bits:
        return True
    shift = PATH_BITS - mask_bits
    pa = ((a >> LEVEL_BITS) & PATH_MASK) >> shift
    pb = ((b >> LEVEL_BITS) & PATH_MASK) >> shift
    return pa == pb


def descendant_range(a: int) -> tuple[int, int]:
    """Inclusive range whose valid addresses are exactly this subtree.

    The guarantee applies to valid encoded cells stored in the same uint64
    column; unused integer values may also occur between valid addresses.
    """
    level = level_of(a)
    suffix_bits = PATH_BITS - 2 * level
    path = (a >> LEVEL_BITS) & PATH_MASK
    high_path = path | ((1 << suffix_bits) - 1 if suffix_bits else 0)
    return a, (face_of(a) << 59) | (high_path << LEVEL_BITS) | MAX_LEVEL


# ---------------------------------------------------- derived group indexes
def lattice_triangle(face: int, digits) -> tuple[tuple[int, int, int], ...]:
    """Integer barycentric vertices of a triangle at its subdivision level.

    Each returned triple sums to ``2**level`` and refers to the vertex order
    of ``ICO_FACES[face]``.  This is an exact combinatorial representation;
    no spherical coordinates are involved.
    """
    if not 0 <= face < 20:
        raise ValueError(f"face {face} out of range 0..19")
    vertices = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    for digit in digits:
        if not 0 <= digit <= 3:
            raise ValueError(f"path digit {digit} out of range 0..3")
        v0, v1, v2 = vertices
        doubled = tuple(tuple(2 * value for value in vertex)
                        for vertex in vertices)
        m01 = tuple(a + b for a, b in zip(v0, v1))
        m12 = tuple(a + b for a, b in zip(v1, v2))
        m20 = tuple(a + b for a, b in zip(v2, v0))
        children = (
            (doubled[0], m01, m20),
            (m01, doubled[1], m12),
            (m20, m12, doubled[2]),
            (m01, m12, m20),
        )
        vertices = children[digit]
    return vertices


def _hilbert_xy_to_index(level: int, x: int, y: int) -> int:
    size = 1 << level
    index = 0
    scale = size >> 1
    while scale:
        rx = 1 if x & scale else 0
        ry = 1 if y & scale else 0
        index += scale * scale * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x = scale - 1 - x
                y = scale - 1 - y
            x, y = y, x
        scale >>= 1
    return index


def _hilbert_index_to_xy(level: int, index: int) -> tuple[int, int]:
    size = 1 << level
    x = y = 0
    scale = 1
    value = index
    while scale < size:
        rx = 1 & (value >> 1)
        ry = 1 & (value ^ rx)
        if ry == 0:
            if rx == 1:
                x = scale - 1 - x
                y = scale - 1 - y
            x, y = y, x
        x += scale * rx
        y += scale * ry
        value >>= 2
        scale <<= 1
    return x, y


def rhombus_coords(a: int) -> tuple[int, int, int, int, int]:
    """Return ``(diamond, level, x, y, orientation)`` for a triangle.

    Dropping ``orientation`` maps exactly two triangles to one rhombus.
    Every diamond is a ``2**level`` square array, including rhombi that
    cross the paired base-face seam.
    """
    face, digits = decode64(a)
    level = len(digits)
    size = 1 << level
    diamond, half, edge = FACE_DIAMOND[face]
    face_vertices = ICO_FACES[face]
    edge_indexes = (face_vertices.index(edge[0]), face_vertices.index(edge[1]))
    points = []
    for barycentric in lattice_triangle(face, digits):
        x = barycentric[edge_indexes[0]]
        y = barycentric[edge_indexes[1]]
        if half:
            x, y = size - y, size - x
        points.append((x, y))
    x = min(point[0] for point in points)
    y = min(point[1] for point in points)
    orientation = 0 if (x, y) in points else 1
    return diamond, level, x, y, orientation


def rhombus_id(a: int) -> str:
    """Stable human-readable ID shared by a triangle pair."""
    diamond, level, x, y, _ = rhombus_coords(a)
    return f"R{diamond:02d}-{level:02d}-{x}-{y}"


def rhombus64(a: int) -> int:
    """Hilbert-linearized uint64 key shared by a triangle pair.

    Layout: 4 diamond bits, 54 left-aligned Hilbert bits, 5 level bits.
    """
    diamond, level, x, y, _ = rhombus_coords(a)
    hilbert = _hilbert_xy_to_index(level, x, y)
    hilbert <<= 2 * (MAX_LEVEL - level)
    return (diamond << 59) | (hilbert << LEVEL_BITS) | level


def decode_rhombus64(value: int) -> tuple[int, int, int, int]:
    """Decode a rhombus key to ``(diamond, level, x, y)``."""
    if not 0 <= value < 1 << 63:
        raise ValueError("rhombus64 value outside its 63-bit range")
    diamond = (value >> 59) & 0xF
    level = value & 0x1F
    if diamond >= len(DIAMONDS) or level > MAX_LEVEL:
        raise ValueError("invalid rhombus64 value")
    hilbert = (value >> LEVEL_BITS) & PATH_MASK
    hilbert >>= 2 * (MAX_LEVEL - level)
    x, y = _hilbert_index_to_xy(level, hilbert)
    return diamond, level, x, y


def _canonical_vertex_id(face: int, level: int,
                         barycentric: tuple[int, int, int]) -> str:
    size = 1 << level
    face_vertices = ICO_FACES[face]
    nonzero = [index for index, value in enumerate(barycentric) if value]
    if len(nonzero) == 1:
        return f"HV{face_vertices[nonzero[0]]:02d}-{level:02d}"
    if len(nonzero) == 2:
        first, second = nonzero
        vertex_a, vertex_b = face_vertices[first], face_vertices[second]
        low, high = sorted((vertex_a, vertex_b))
        high_index = first if vertex_a == high else second
        position = barycentric[high_index]
        return f"HE{low:02d}{high:02d}-{level:02d}-{position}"
    a, b, c = barycentric
    return f"HF{face:02d}-{level:02d}-{a}-{b}-{c}"


def hex_id(a: int) -> str:
    """Derived display-group key based on a face-local triangular 3-coloring.

    Face-interior groups contain six triangles.  Keys on icosahedron edges
    and vertices are canonicalized across faces, but aperture-4 does not
    permit a globally uniform hex/pentagon partition of whole triangles;
    seam and vertex groups therefore have documented non-six cardinalities.
    """
    face, digits = decode64(a)
    vertices = lattice_triangle(face, digits)
    centers = [vertex for vertex in vertices
               if (vertex[1] + 2 * vertex[2]) % 3 == 0]
    if len(centers) != 1:
        raise AssertionError("triangle lattice coloring must select one vertex")
    return _canonical_vertex_id(face, len(digits), centers[0])


# ----------------------------------------------------------- compact form
def to_compact(a: int) -> str:
    face, digits = decode64(a)
    level = len(digits)
    bits = 0
    for d in digits:
        bits = (bits << 2) | d
    nbits = 2 * level
    nchars = (nbits + 4) // 5
    bits <<= nchars * 5 - nbits                 # right-pad to 5-bit boundary
    chars = []
    for i in range(nchars):
        chars.append(B32[(bits >> (5 * (nchars - 1 - i))) & 0x1F])
    return 'T' + B32[face] + B32[level] + ''.join(chars)


def from_compact(s: str) -> int:
    s = s.strip().upper()
    if not s.startswith('T') or len(s) < 3:
        raise ValueError(f"bad compact address {s!r}")
    face = B32_INV[s[1]]
    level = B32_INV[s[2]]
    nbits = 2 * level
    nchars = (nbits + 4) // 5
    if len(s) != 3 + nchars:
        raise ValueError(f"{s!r}: expected {nchars} path chars for level {level}")
    bits = 0
    for c in s[3:]:
        bits = (bits << 5) | B32_INV[c]
    bits >>= nchars * 5 - nbits                 # drop right padding
    digits = tuple((bits >> (2 * (level - 1 - i))) & 0x3 for i in range(level))
    return encode64(face, digits)


# ----------------------------------------------------------- path form
def to_path(a: int) -> str:
    face, digits = decode64(a)
    return f"F{face:02d}-" + ''.join(str(d) for d in digits)


def from_path(s: str) -> int:
    s = s.strip().upper()
    if not s.startswith('F'):
        raise ValueError(f"bad path address {s!r}")
    head, _, tail = s.partition('-')
    face = int(head[1:])
    digits = tuple(int(c) for c in tail) if tail else ()
    return encode64(face, digits)
