-- ============================================================================
-- Trifold DuckDB Macros
-- ============================================================================
--
-- Pure-SQL macros for working with Trifold addr64 values (UBIGINT).
-- No extensions, no UDFs — just bit operations.
--
-- Usage:
--   .read sql/trifold_duckdb.sql
--
-- addr64 bit layout (64 bits):
--   bits 63..59   face   (5 bits, 0..19)
--   bits 58..5    path   (54 bits, base-4 digits left-aligned)
--   bits  4..0    level  (5 bits, 0..27)
--
-- Example — aggregate level-9 measurements to level-6 cells:
--
--   SELECT trifold_compact(trifold_parent_at(addr64, 6))  AS cell,
--          SUM(value)                                      AS total,
--          COUNT(*)                                        AS n
--   FROM   measurements
--   GROUP  BY 1
--   ORDER  BY 1;
--
-- ============================================================================


-- ────────────────────────────────────────────────────────────────────────────
-- Internal helpers (prefixed with _ to signal they are private)
-- ────────────────────────────────────────────────────────────────────────────

-- Crockford base-32 character from a 0..31 value.
CREATE OR REPLACE MACRO _tf_b32(n) AS
    substr('0123456789ABCDEFGHJKMNPQRSTVWXYZ', 1 + (n::INT & 31), 1);

-- Crockford base-32 value from a single character (strict, no I/L/O/U leniency).
CREATE OR REPLACE MACRO _tf_b32inv(c) AS
    (position(upper(c::VARCHAR) IN '0123456789ABCDEFGHJKMNPQRSTVWXYZ') - 1);


-- ────────────────────────────────────────────────────────────────────────────
-- 1. Field extraction
-- ────────────────────────────────────────────────────────────────────────────

-- Subdivision level (0..27).
CREATE OR REPLACE MACRO trifold_level(addr) AS
    (addr::UBIGINT & 31::UBIGINT)::INT;

-- Icosahedron face index (0..19).
CREATE OR REPLACE MACRO trifold_face(addr) AS
    ((addr::UBIGINT >> 59) & 31::UBIGINT)::INT;


-- ────────────────────────────────────────────────────────────────────────────
-- 2. Hierarchy traversal
-- ────────────────────────────────────────────────────────────────────────────

-- Roll up to a coarser level.  This is THE key operation for hierarchical
-- aggregation:  GROUP BY trifold_parent_at(addr64, 6)
--
-- How it works: clear all path bits below target_level and reset the level
-- field.  The mask ~((1 << (59 - 2*target_level)) - 1) zeroes bits
-- (58-2*target_level) down to 0, which covers both the unwanted path
-- digits and the old level field.
CREATE OR REPLACE MACRO trifold_parent_at(addr, target_level) AS (
    (addr::UBIGINT
        & ~((1::UBIGINT << (59::UBIGINT - 2::UBIGINT * target_level::UBIGINT))
            - 1::UBIGINT))
    | target_level::UBIGINT
);

-- Immediate parent (one level up).
CREATE OR REPLACE MACRO trifold_parent(addr) AS
    trifold_parent_at(addr, (addr::UBIGINT & 31::UBIGINT) - 1::UBIGINT);

-- Single child by digit (0..3).  Appends one path digit and increments
-- the level.  The digit occupies addr64 bits (58-2L) and (57-2L) where
-- L is the current level; these bits are always zero before the call
-- (left-alignment guarantee), so a plain OR suffices.
CREATE OR REPLACE MACRO trifold_child(addr, d) AS (
    ((addr::UBIGINT & ~31::UBIGINT)
     | (d::UBIGINT << (57::UBIGINT - 2::UBIGINT * (addr::UBIGINT & 31::UBIGINT))))
    | ((addr::UBIGINT & 31::UBIGINT) + 1::UBIGINT)
);

-- All four children as a list.
CREATE OR REPLACE MACRO trifold_children(addr) AS
    [trifold_child(addr, 0), trifold_child(addr, 1),
     trifold_child(addr, 2), trifold_child(addr, 3)];


-- ────────────────────────────────────────────────────────────────────────────
-- 3. Subtree range queries
-- ────────────────────────────────────────────────────────────────────────────
--
-- Every cell's descendants occupy one contiguous UBIGINT interval.
-- Use:  WHERE addr64 BETWEEN trifold_descendant_lo(x)
--                        AND trifold_descendant_hi(x)

-- Low bound of the descendant range (the cell itself).
CREATE OR REPLACE MACRO trifold_descendant_lo(addr) AS
    addr::UBIGINT;

-- High bound: fill all remaining path digits with 3 and set level to 27.
-- Method: OR in ones for all bits below the current path digits
-- (positions 58-2L down to 5), then fix the level field to 27.
CREATE OR REPLACE MACRO trifold_descendant_hi(addr) AS (
    ((addr::UBIGINT
      | ((1::UBIGINT << (59::UBIGINT - 2::UBIGINT * (addr::UBIGINT & 31::UBIGINT)))
         - 1::UBIGINT))
     & ~31::UBIGINT)
    | 27::UBIGINT
);

-- Ancestry test using the range property.  True when b (or b itself)
-- is a descendant of a.  Both must be valid addr64 values.
CREATE OR REPLACE MACRO trifold_is_ancestor(a, b) AS (
    b::UBIGINT >= a::UBIGINT
    AND b::UBIGINT <= trifold_descendant_hi(a)
);


-- ────────────────────────────────────────────────────────────────────────────
-- 4. Compact address display   addr64 ↔ string
-- ────────────────────────────────────────────────────────────────────────────

-- Convert addr64 to compact Crockford base-32 string (e.g. 'TF6958').
--
-- Format: 'T' + B32(face) + B32(level) + B32-encoded path digits.
-- The path is read as 5-bit groups from the top of the 54-bit path field.
-- Number of path characters = ceil(2 × level / 5).
-- Characters 0..9 are extracted as (addr >> (54 − 5i)) & 31.
-- Character 10 (levels 26-27 only) needs special handling because the
-- last 5-bit group straddles the path/level boundary.
CREATE OR REPLACE MACRO trifold_compact(addr) AS (
    'T'
    || _tf_b32((addr::UBIGINT >> 59) & 31)
    || _tf_b32(addr::UBIGINT & 31)
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 1
            THEN _tf_b32((addr::UBIGINT >> 54) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 2
            THEN _tf_b32((addr::UBIGINT >> 49) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 3
            THEN _tf_b32((addr::UBIGINT >> 44) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 4
            THEN _tf_b32((addr::UBIGINT >> 39) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 5
            THEN _tf_b32((addr::UBIGINT >> 34) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 6
            THEN _tf_b32((addr::UBIGINT >> 29) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 7
            THEN _tf_b32((addr::UBIGINT >> 24) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 8
            THEN _tf_b32((addr::UBIGINT >> 19) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 9
            THEN _tf_b32((addr::UBIGINT >> 14) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 10
            THEN _tf_b32((addr::UBIGINT >> 9) & 31) ELSE '' END
    || CASE WHEN (2 * (addr::UBIGINT & 31)::INT + 4) / 5 >= 11
            THEN _tf_b32((addr::UBIGINT >> 4) & 30) ELSE '' END
);


-- Parse a compact address string to addr64.
--
-- Each path character contributes 5 bits at a fixed position in the 64-bit
-- word.  Character i (0-indexed) is placed at addr64 bits (58−5i)..(54−5i),
-- except character 10 which drops the padding bit and lands at bits 8..5.
-- Face comes from s[2], level from s[3] (1-indexed).
CREATE OR REPLACE MACRO trifold_from_compact(s) AS (
    -- face (bits 63..59)
    (_tf_b32inv(substr(upper(s::VARCHAR), 2, 1))::UBIGINT << 59)
    -- path characters → addr64 bits  (up to 11 characters at positions 4..14)
    | CASE WHEN length(s::VARCHAR) > 3
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 4, 1))::UBIGINT << 54
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 4
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 5, 1))::UBIGINT << 49
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 5
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 6, 1))::UBIGINT << 44
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 6
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 7, 1))::UBIGINT << 39
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 7
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 8, 1))::UBIGINT << 34
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 8
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 9, 1))::UBIGINT << 29
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 9
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 10, 1))::UBIGINT << 24
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 10
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 11, 1))::UBIGINT << 19
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 11
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 12, 1))::UBIGINT << 14
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 12
           THEN _tf_b32inv(substr(upper(s::VARCHAR), 13, 1))::UBIGINT << 9
           ELSE 0::UBIGINT END
    | CASE WHEN length(s::VARCHAR) > 13
           THEN (_tf_b32inv(substr(upper(s::VARCHAR), 14, 1))::UBIGINT >> 1) << 5
           ELSE 0::UBIGINT END
    -- level (bits 4..0)
    | _tf_b32inv(substr(upper(s::VARCHAR), 3, 1))::UBIGINT
);


-- Digit-path notation (e.g. 'F15-102111').
CREATE OR REPLACE MACRO trifold_path(addr) AS (
    'F'
    || lpad(((addr::UBIGINT >> 59) & 31)::INT::VARCHAR, 2, '0')
    || '-'
    || CASE WHEN (addr::UBIGINT & 31) = 0 THEN ''
       ELSE list_reduce(
           list_transform(
               generate_series(0, (addr::UBIGINT & 31)::INT - 1),
               i -> (((addr::UBIGINT >> 5) >> (52::UBIGINT - 2::UBIGINT * i::UBIGINT)) & 3)::INT::VARCHAR
           ),
           (a, b) -> a || b,
           -- Note: if DuckDB warns about arrow syntax, replace -> above
           ''::VARCHAR
       )
       END
);


-- ────────────────────────────────────────────────────────────────────────────
-- 5. Verification
-- ────────────────────────────────────────────────────────────────────────────
-- All assertions below should return true.  Run after .read to confirm
-- the macros work on your DuckDB version.

SELECT '── Verification ──' AS section;

-- Field extraction
SELECT trifold_level(8811996358392152070) = 6       AS level_ok,
       trifold_face(8811996358392152070)  = 15      AS face_ok;

-- Compact round-trip
SELECT trifold_compact(8811996358392152070)          = 'TF6958'             AS compact_ok,
       trifold_from_compact('TF6958')                = 8811996358392152070  AS from_compact_ok,
       trifold_compact(trifold_from_compact('TF6958')) = 'TF6958'           AS roundtrip_ok;

-- Path notation
SELECT trifold_path(8811996358392152070)             = 'F15-102111'         AS path_ok;

-- Hierarchy: parent
SELECT trifold_compact(trifold_parent(
           trifold_from_compact('TF6958')))          = 'TF595'              AS parent_ok;

-- Hierarchy: parent_at (the GROUP BY key for level rollup)
SELECT trifold_compact(trifold_parent_at(
           trifold_from_compact('TF6958'), 3))       = 'TF390'              AS parent_at_ok;

-- Hierarchy: children
SELECT list_transform(trifold_children(trifold_from_compact('TF6958')),
           c -> trifold_compact(c))
       -- Note: if DuckDB warns about lambda syntax, replace -> with :
       = ['TF7958', 'TF795A', 'TF795C', 'TF795E']                          AS children_ok;

-- Subtree range: child must be inside parent's descendant range
SELECT trifold_is_ancestor(
           trifold_from_compact('TF595'),
           trifold_from_compact('TF6958'))                                   AS ancestor_ok;

-- Subtree range: sibling must NOT be inside
SELECT NOT trifold_is_ancestor(
           trifold_from_compact('TF595'),
           trifold_from_compact('TF6B30'))                                   AS not_ancestor_ok;

-- Level-0 cell
SELECT trifold_compact(trifold_parent_at(
           trifold_from_compact('TF6958'), 0))       = 'TF0'               AS level0_ok;

SELECT '── All checks done ──' AS section;
