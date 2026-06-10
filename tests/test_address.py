import random
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trifold.address import (encode64, decode64, to_compact, from_compact,
                             to_path, from_path, parent64, children64,
                             is_ancestor, level_of, MAX_LEVEL)


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
    # Sorting by (path-aligned bits, level) reproduces DFS preorder:
    by_num = sorted(cells, key=lambda a: (a & ((1 << 54) - 1), level_of(a)))
    assert by_num == df_order


def test_compact_examples():
    a = encode64(9, (3, 1, 2, 0, 1, 2))   # level 6
    c = to_compact(a)
    assert len(c) == 6                     # 'T' + face + level + 3 path chars
    assert c.startswith('T96')
    assert from_compact(c.lower()) == a    # case-insensitive


if __name__ == '__main__':
    test_roundtrips(); test_hierarchy()
    test_sort_is_hierarchical(); test_compact_examples()
    print("all address tests passed")
