# GHS-WUP-DEGURBA data notice

The bundled `.tfdg` core and optional `.tfdd` boundary shards are derived from the European Commission Joint
Research Centre's **GHS-WUP-DEGURBA R2025A, epoch 2025** raster, licensed
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Recommended source citation: European Commission, Joint Research Centre
(JRC), *GHS-WUP Projections Data Package 2025*, product DOI
[`10.2905/1c049178-ab00-4bbc-b638-3e3c19daaacb`](https://doi.org/10.2905/1c049178-ab00-4bbc-b638-3e3c19daaacb).

Methodology report: Schiavina, M., Melchiorri, M., Mari Rivero, I., Florio, P.,
Freire, S. et al., *GHSL WUP Projections Data Package 2025 — Public release
GHS-WUP R2025*, Publications Office of the European Union, Luxembourg, 2025,
JRC144209, DOI
[`10.2760/2416436`](https://data.europa.eu/doi/10.2760/2416436).

Change notice: Trifold transfers the final categorical 1 km Mollweide raster
to a hierarchical triangular grid. It stores the dominant equal-area class
and boundary diagnostics. It does not alter or re-run the DEGURBA method.
The library source code is MIT licensed; that does not replace the data
artifact's CC BY 4.0 terms.

The split WIP v1 rebuild corrects numerical outside/nodata-area detection and
high-latitude projection convergence. Classification and boundary files share
a build identity and retain 8-bit dominant-area shares. Optional detail
delivery changes storage/loading, not the DEGURBA scientific algorithm.
