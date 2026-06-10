import random
from collections import Counter, defaultdict
from itertools import product
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trifold.address import (encode64, decode64, to_compact, from_compact,
                             to_path, from_path, parent64, children64,
                             is_ancestor, descendant_range, hex_id,
                             rhombus64, decode_rhombus64, rhombus_coords,
                             rhombus_id, MAX_LEVEL)


def test_roundtrips():
    rng = random.Random(42)
    for _ in range(5000):
        face = rng.randrange(20)
        level = rng.randrange(0, MAX_LEVEL + 1)
        digits = tuple(rng.randrange(4) for _ in range(level))
        a = encode64(face, digits)
        assert decode64(a) == (face, digits)
        assert from_compact(to_compact(a)) == a
        assert from_path(to_path(a)) == a
        if digits:
            assert parent64(a) == encode64(face, digits[:-1])
        if level < MAX_LEVEL:
            assert children64(a) == [encode64(face, digits + (d,))
                                     for d in range(4)]


def test_hierarchy():
    a = encode64(7, (3, 1, 2, 0))
    p = parent64(a)
    assert decode64(p) == (7, (3, 1, 2))
    assert a in children64(p)
    assert is_ancestor(p, a) and not is_ancestor(a, p)
    assert is_ancestor(a, a)
    assert not is_ancestor(encode64(8, (3, 1, 2)), a)


def test_sort_is_hierarchical():
    """Numeric sort of addr64 within a face == depth-first tree order."""
    cells = []
    def gen(digits, level):
        cells.append(encode64(4, tuple(digits)))
        if level < 3:
            for d in range(4):
                gen(digits + [d], level + 1)
    gen([], 0)
    df_order = cells[:]                 # generation order is depth-first
    assert sorted(cells) == df_order


def test_descendants_form_one_integer_range():
    cells = []
    for face in (3, 4):
        def gen(digits):
            cells.append(encode64(face, tuple(digits)))
            if len(digits) < 4:
                for d in range(4):
                    gen(digits + [d])
        gen([])

    for a in cells:
        low, high = descendant_range(a)
        assert low == a
        for b in cells:
            assert (low <= b <= high) == is_ancestor(a, b)


def test_compact_examples():
    a = encode64(9, (3, 1, 2, 0, 1, 2))   # level 6
    c = to_compact(a)
    assert len(c) == 6                     # 'T' + face + level + 3 path chars
    assert c.startswith('T96')
    assert from_compact(c.lower()) == a    # case-insensitive

    london = from_compact('TF6958')
    assert london == 8811996358392152070
    assert to_path(london) == 'F15-102111'


def test_rhombus_projection_is_exact_and_hierarchical():
    for level in range(5):
        groups = defaultdict(list)
        for face in range(20):
            for digits in product(range(4), repeat=level):
                addr = encode64(face, digits)
                coords = rhombus_coords(addr)
                key = rhombus64(addr)
                assert decode_rhombus64(key) == coords[:4]
                groups[rhombus_id(addr)].append((coords, key))
                if level:
                    parent = rhombus_coords(parent64(addr))
                    assert coords[:2] == (parent[0], level)
                    assert coords[2] // 2 == parent[2]
                    assert coords[3] // 2 == parent[3]

        assert len(groups) == 10 * 4 ** level
        assert all(len(members) == 2 for members in groups.values())
        assert all({coords[4] for coords, _ in members} == {0, 1}
                   for members in groups.values())
        assert all(len({key for _, key in members}) == 1
                   for members in groups.values())


def test_hex_projection_has_six_triangle_face_interiors():
    counts = Counter()
    for face in range(20):
        for digits in product(range(4), repeat=4):
            counts[hex_id(encode64(face, digits))] += 1

    assert counts
    assert all(count == 6 for key, count in counts.items()
               if key.startswith('HF'))
    assert {count for key, count in counts.items() if key.startswith('HE')} == {3, 6}


if __name__ == '__main__':
    test_roundtrips(); test_hierarchy()
    test_sort_is_hierarchical(); test_descendants_form_one_integer_range()
    test_compact_examples()
    print("all address tests passed")
