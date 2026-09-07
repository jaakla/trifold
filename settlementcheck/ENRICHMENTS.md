# Optional enrichment assessment

These are candidate independent, lazy additions, not fields hidden inside the
TFDD boundary files. None is downloaded by the core library or demo today.
The population/multi-resolution implementation plan remains in [#19](https://github.com/jaakla/trifold/issues/19),
with the broader population API in [#15](https://github.com/jaakla/trifold/issues/15).

| Enhancement | Open source candidate | Meaning and implementation constraint |
|---|---|---|
| Named places | [GeoNames](https://www.geonames.org/export/) (CC BY) | Place names and IDs; a nearby point name is not proof of containment in a named settlement. Use bounded spatial tiles and distinguish nearest-place labels from matched polygon names. |
| Settlement entities and population totals | [GHS-WUP-DEGURBA R2025A entities](https://human-settlement.emergency.copernicus.eu/ghs_wup_degurba_r2025a.php) (GHSL attribution) | The pinned archive already includes UC/DUC/SDUC/RC polygons. The inspected UC table has `Unique_ID`, `UNLocID`, `AREA_km2`, `POP_2025`, built-up area and centroids, but no settlement-name field. Population is an entity total, not the selected triangle's population. Match by polygon containment and preserve entity ID/source. |
| Administrative regions | [geoBoundaries gbOpen](https://www.geoboundaries.org/api.html) (CC BY 4.0 compliant) | Prefer pinned per-country ADM0/1/2 files with each source's attribution. Load only the requested country/level and index polygons. Preserve overlaps, disputed boundaries and unknown coverage explicitly. |
| Triangle population and density | [GHS-WUP-POP R2025A](https://human-settlement.emergency.copernicus.eu/ghs_wup_pop_r2025a.php), 2025, 1 km | Build population counts from source-pixel overlap, not DEGURBA class thresholds. Sum counts across levels and divide by actual triangle area for full-cell density. Keep the numeric artifact optional and separately versioned. |

The [GADM license](https://gadm.org/license.html) does not generally permit
redistribution or commercial use without permission. It is therefore not a
suitable default bundled enhancement for this open library. No new GADM
files are included by this change.

Recommended architecture: independent manifests and loaders for entities,
names, administration and numeric population. Fetch only on an explicit
enrichment action, cache bounded spatial chunks, and return source, vintage,
matched geometry/ID, coverage and value semantics beside every result. Their
failures must leave classification and boundary details usable. Do not add
unbounded reverse-geocoding requests or a mandatory global numeric download.

Before including an enrichment, pin the source/hash/attribution, benchmark
download/decode and renderer memory, and validate containment and totals.
This assessment deliberately avoids presenting a nearest place as a city
boundary or an urban-centre total as population inside one T3 triangle.
