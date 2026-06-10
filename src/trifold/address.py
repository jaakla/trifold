"""
trifold.address — three equivalent encodings of one cell identity.

A cell is (face, path) where face in 0..19 and path is a sequence of
base-4 digits (one per subdivision level): 0,1,2 = corner children
(toward parent vertices 0,1,2), 3 = central (orientation-flipped) child.

Encodings
---------
1. addr64 (uint64)  — for compute.
     bits 63..59  face   (5 bits, 0..19)
     bits 58..54  level  (5 bits, 0..27)
     bits 53..0   path digits, 2 bits each, LEFT-aligned (d1 at bits 53..52)
   Properties: numeric sort == hierarchical (Z-order) sort within a face;
   ancestor test is a shift+compare; parent/child are O(1) bit ops.

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

__all__ = ['encode64', 'decode64', 'to_compact', 'from_compact',
           'to_path', 'from_path', 'parent64', 'children64', 'level_of',
           'face_of', 'path_of', 'is_ancestor', 'MAX_LEVEL']


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
    return (face << 59) | (level << 54) | path


def decode64(a: int) -> tuple[int, tuple[int, ...]]:
    face = (a >> 59) & 0x1F
    level = (a >> 54) & 0x1F
    digits = tuple((a >> (54 - 2 * (i + 1))) & 0x3 for i in range(level))
    return face, digits


def face_of(a: int) -> int:
    return (a >> 59) & 0x1F


def level_of(a: int) -> int:
    return (a >> 54) & 0x1F


def path_of(a: int) -> tuple[int, ...]:
    return decode64(a)[1]


def parent64(a: int) -> int:
    face, digits = decode64(a)
    if not digits:
        raise ValueError("level-0 cell has no parent")
    return encode64(face, digits[:-1])


def children64(a: int) -> list[int]:
    face, digits = decode64(a)
    if len(digits) >= MAX_LEVEL:
        raise ValueError("at max level")
    return [encode64(face, tuple(digits) + (d,)) for d in range(4)]


def is_ancestor(a: int, b: int) -> bool:
    """True if a is an ancestor of (or equal to) b."""
    if face_of(a) != face_of(b):
        return False
    la, lb = level_of(a), level_of(b)
    if la > lb:
        return False
    mask_bits = 2 * la
    pa = (a & ((1 << 54) - 1)) >> (54 - mask_bits) if mask_bits else 0
    pb = (b & ((1 << 54) - 1)) >> (54 - mask_bits) if mask_bits else 0
    return pa == pb


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
