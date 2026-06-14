-- Build public.countries_coastal: country polygons with accurate (OSM-derived)
-- borders from the timezone-boundary-builder "with oceans" dataset, carrying
-- GADM level-0 attributes.
--
-- Why this exists: GADM level-0 boundaries are noticeably noisy and offset from
-- the true (OSM) line. The geo-tz-countries-with-oceans polygons follow the
-- accurate borders and already extend each country into its nearby territorial
-- water, but they carry only a tzid, no country attributes. So we take the tz
-- geometry for the shape and join GADM only for identity (gid_0, names) and the
-- ISO codes from public.countries.
--
-- Timezones are a global partition, so the per-country tz geometries are
-- naturally non-overlapping. The only fix-up needed is the handful of countries
-- that share a tzid with a neighbour and therefore get no own tz polygon
-- (Kosovo inside Europe/Belgrade, Akrotiri inside Asia/Nicosia, the Caspian Sea
-- pseudo-entity, and a few remote islands): those keep their GADM land and are
-- carved out of the neighbour whose tz polygon swallowed them.
--
-- Run:  psql -d jaak -f sql/build_countries_coastal.sql
-- Produces public.countries_coastal_v2 for validation; the final block renames
-- it over public.countries_coastal (commented out — enable when satisfied).
--
-- Post-step: the raw timezone polygons carry small "antenna" artifacts (a vertex
-- poking out perpendicular to the border and returning, plus a few degenerate
-- near-zero-area / constant-latitude rings). After exporting the geojson, run
-- `scripts/despike_countries.py` to remove them (surgical, ~0.02% of vertices,
-- no measurable area change), then reload the cleaned geometry back here with:
--   ogr2ogr -f PostgreSQL PG:... countries_coastal.geojson \
--           -nln countries_coastal_despiked_stg -nlt MULTIPOLYGON -overwrite
--   UPDATE countries_coastal c SET geom = ST_Multi(ST_CollectionExtract(
--     ST_MakeValid(s.geom),3)) FROM countries_coastal_despiked_stg s
--     WHERE c.gid_0 = s.gid_0;

\set ON_ERROR_STOP on
\timing on

BEGIN;

DROP TABLE IF EXISTS public.countries_coastal_v2;

-- 1. Explode every non-Etc timezone polygon into connected components. A single
--    tzid can hold land from more than one country as separate pieces (e.g.
--    northern Vietnam sits in Asia/Bangkok while the south is Asia/Ho_Chi_Minh),
--    so assignment must happen per piece, not per tzid, or a country loses the
--    land that shares a neighbour's zone.
CREATE TEMP TABLE tz_comp ON COMMIT DROP AS
SELECT row_number() OVER () AS cid, tz.tzid, d.geom
FROM public."geo-tz-countries-with-oceans" AS tz
CROSS JOIN LATERAL ST_Dump(ST_CollectionExtract(tz.geom, 3)) AS d
WHERE tz.tzid !~ '^Etc/';
CREATE INDEX tz_comp_geom_gix ON tz_comp USING gist (geom);

-- 2. Assign each component to the GADM country it covers most on land
--    (equal-area EPSG:6933); components with no land overlap (open-water pieces)
--    go to the nearest country so territorial water is not dropped. Union the
--    components per country.
CREATE TEMP TABLE comp_assign ON COMMIT DROP AS
WITH overlap AS (
    SELECT c.cid, c.tzid, g.gid_0,
           ST_Area(ST_Transform(
               ST_CollectionExtract(ST_Intersection(c.geom, g.geom), 3), 6933)) AS m2
    FROM tz_comp AS c
    JOIN public.gadm_level0 AS g ON ST_Intersects(c.geom, g.geom)
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY cid ORDER BY m2 DESC, gid_0) AS rk
    FROM overlap WHERE m2 > 0
)
SELECT cid, tzid, gid_0 FROM ranked WHERE rk = 1;

INSERT INTO comp_assign
SELECT c.cid, c.tzid,
       (SELECT g.gid_0 FROM public.gadm_level0 AS g
        ORDER BY c.geom <-> g.geom LIMIT 1) AS gid_0
FROM tz_comp AS c
WHERE c.cid NOT IN (SELECT cid FROM comp_assign);

CREATE TEMP TABLE tz_country ON COMMIT DROP AS
SELECT a.gid_0,
       array_agg(DISTINCT a.tzid ORDER BY a.tzid) AS tzids,
       ST_MakeValid(ST_UnaryUnion(ST_Collect(c.geom))) AS tz_geom
FROM comp_assign AS a
JOIN tz_comp AS c USING (cid)
GROUP BY a.gid_0;
CREATE INDEX tz_country_gid_idx ON tz_country (gid_0);

-- 3. Countries that received no tz polygon keep their GADM land; for each tz
--    country, collect any such fallback land that its tz polygon swallowed, so
--    it can be carved back out.
CREATE TEMP TABLE fallback AS
SELECT g.gid_0, g.geom
FROM public.gadm_level0 AS g
LEFT JOIN tz_country AS t USING (gid_0)
WHERE t.gid_0 IS NULL;
CREATE INDEX fallback_geom_gix ON fallback USING gist (geom);

CREATE TEMP TABLE carve ON COMMIT DROP AS
SELECT t.gid_0, ST_UnaryUnion(ST_Collect(f.geom)) AS carve_geom
FROM tz_country AS t
JOIN fallback AS f ON ST_Intersects(t.tz_geom, f.geom)
GROUP BY t.gid_0;

-- 4. Assemble: tz geometry (minus carved fallback land) for tz countries; GADM
--    land for the fallbacks. Then derive attributes and areas.
CREATE TABLE public.countries_coastal_v2 AS
WITH built AS (
    SELECT
        g.fid, g.gid_0, g.name_0, g.name_0 AS name_en,
        c.code::character(2) AS iso2,
        c.iso3::character(3) AS iso3,
        c.number::character(3) AS iso_numeric,
        COALESCE(t.tzids, ARRAY[]::text[]) AS tzids,
        g.geom AS gadm_geom,
        g.geog AS gadm_geog,
        CASE
            WHEN t.tz_geom IS NULL OR ST_IsEmpty(t.tz_geom)
                THEN ST_Multi(ST_CollectionExtract(ST_MakeValid(g.geom), 3))
            WHEN cv.carve_geom IS NULL
                THEN ST_Multi(ST_CollectionExtract(ST_MakeValid(t.tz_geom), 3))
            ELSE ST_Multi(ST_CollectionExtract(
                     ST_MakeValid(ST_Difference(t.tz_geom, cv.carve_geom)), 3))
        END::geometry(MultiPolygon, 4326) AS geom
    FROM public.gadm_level0 AS g
    LEFT JOIN public.countries AS c ON c.iso3 = g.gid_0
    LEFT JOIN tz_country AS t USING (gid_0)
    LEFT JOIN carve AS cv USING (gid_0)
), with_water AS (
    SELECT b.*,
           GREATEST(ST_Area(ST_Difference(b.geom, b.gadm_geom)::geography) / 1e6, 0)
               AS added_water_area_km2
    FROM built AS b
)
SELECT
    fid, gid_0, name_0, name_en, iso2, iso3, iso_numeric, tzids,
    cardinality(tzids)::smallint AS timezone_count,
    added_water_area_km2 > 1.0 AS has_coastal_extension,
    ST_Area(gadm_geog) / 1e6 AS land_area_km2,
    added_water_area_km2,
    geom
FROM with_water;

ALTER TABLE public.countries_coastal_v2
    ADD CONSTRAINT countries_coastal_v2_pkey PRIMARY KEY (fid),
    ADD CONSTRAINT countries_coastal_v2_gid_0_key UNIQUE (gid_0),
    ADD CONSTRAINT countries_coastal_v2_geom_valid CHECK (ST_IsValid(geom)),
    ADD CONSTRAINT countries_coastal_v2_geom_srid CHECK (ST_SRID(geom) = 4326);
CREATE INDEX countries_coastal_v2_geom_gix ON public.countries_coastal_v2 USING gist (geom);
ANALYZE public.countries_coastal_v2;

COMMIT;

-- Swap the corrected table into place, keeping the old GADM-bordered table as a
-- backup. Run this block once countries_coastal_v2 is validated. The old table's
-- index/constraint names must move aside first or they collide with the names
-- the new table wants.
--
-- BEGIN;
-- ALTER TABLE public.countries_coastal RENAME TO countries_coastal_gadm_borders;
-- ALTER INDEX public.countries_coastal_pkey      RENAME TO countries_coastal_gadm_pkey;
-- ALTER INDEX public.countries_coastal_gid_0_key RENAME TO countries_coastal_gadm_gid_0_key;
-- ALTER INDEX public.countries_coastal_iso3_uidx RENAME TO countries_coastal_gadm_iso3_uidx;
-- ALTER INDEX public.countries_coastal_geom_gix  RENAME TO countries_coastal_gadm_geom_gix;
-- ALTER TABLE public.countries_coastal_v2 RENAME TO countries_coastal;
-- ALTER INDEX public.countries_coastal_v2_geom_gix RENAME TO countries_coastal_geom_gix;
-- ALTER TABLE public.countries_coastal RENAME CONSTRAINT countries_coastal_v2_pkey      TO countries_coastal_pkey;
-- ALTER TABLE public.countries_coastal RENAME CONSTRAINT countries_coastal_v2_gid_0_key TO countries_coastal_gid_0_key;
-- COMMIT;
