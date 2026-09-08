# Trifold documentation site (#20)

The supported entry point is still `scripts/make_site.py`. Run from the repository
root, with the site build extras installed:

```sh
uv pip install --python .venv/bin/python -e '.[site]'
.venv/bin/python scripts/make_site.py
```

The scientific artifacts are copied, not rebuilt. A clean checkout reuses the
comparison page's embedded payload and hosted PMTiles inventory. Keep the
generated `docs/index.html` when rebuilding without the optional grid products.

## Ownership

- `templates/`: authored overview, landcheck and countrycheck content and tools.
- `../settlementcheck.template.html`: settlement content and tools; its existing
  editing entry point is preserved.
- `../site_builder.py`: `PageSpec`, shared shell, navigation, heading/anchor
  normalization, authored introduction placement, and Markdown rendering.
- `docs/sdk-api.md` and `docs/t3-technical-reference.md`: canonical reference
  content, rendered to matching HTML with repaired links.
- `assets/site.css` / `site.js`: documentation tokens, responsive navigation,
  accessible disclosure/menu behavior, code-copy controls and tables.
- `assets/map-demo.mjs` / `map-demo.css`: MapLibre lifecycle, keyed CARTO vector
  style, Globe/Mercator URL state, coordinate validation, selection marker,
  inspector, presets/reset, layer visibility/opacity, copy/clear, bounded point
  uploads, generation cancellation, status and cleanup.
- `assets/*-demo.mjs`: SDK-specific adapters and specialized demonstrators.
  They do not define new scientific APIs or change the data artifacts.

The runtime contract is `createMapDemo({container, initialView, adapter, limits})`.
An adapter supplies `id`, `layers`, `presets`, `queryPoint`, and optionally
`describeResult`, `queryBatch`, `pointColor`, `acceptClick`, `clearSelection`,
`setVisible` and `dispose`. Shared `task(name)` / `cancel(name)` generation guards
prevent stale rendering; `setPaint` preserves scientific expressions when the
user changes opacity. `loadWithRetry` handles recoverable core loading.

Lookup pages share the point-dataset control (CSV or GeoJSON, 2 MB / 5,000 rows,
invalid-row count, yielding, sample, cancellation/clear). Existing richer route
and benchmark tools remain under **Layers and tools**. Benchmarks still classify
their requested point count, but upload at most 5,000 displayed point features.
Settlement retains its 6,500-cell limit, two-face detail cache and opt-in details.
The separate coverage demo retains its own drawing controls and bounded output.

All maps use MapLibre 5.6.2 and CARTO Positron vectors. The shared request hook
adds the public browser key only to CARTO hosts, preserving other protocols such
as `pmtiles://` exactly. Override `TRIFOLD_CARTO_BASEMAP_KEY` for another host.
This is browser configuration, not a server secret: requests expose it to users.
Equal Earth is explicitly deferred; no alternate renderer is loaded.

Projection uses `?projection=globe|mercator`; the second coverage view uses
`?covermap-projection=...`. Unknown values use each map's documented initial
projection (globe for comparison/land/country, Mercator for settlement/coverage).
Changing projection never changes analytical coordinates or lookup semantics.

## Verification

```sh
.venv/bin/python -m pytest tests/test_site.py -q
node --test scripts/site/tests/test_map_demo.mjs
TRIFOLD_PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
  node scripts/site/tests/browser.mjs
```

Browser plugin was unavailable in the implementation environment, so the browser
suite uses Playwright. It resolves an existing installation rather than adding
a browser dependency to the shipped library. `TRIFOLD_PYTHON` can override the
fixture builder's Python interpreter. `QA_PAGES` selects a comma-separated subset.

The browser suite serves a **synthetic UI-only** three-run L12 fixture and limits
coverage geometry to one real SDK-generated triangle per request. Comparison
switching uses a one-cell fixture, and refinement toggles use an empty valid
refinement file. These are UI tests, not scientific accuracy evidence. They run
pages sequentially, close promptly, and never render a global L12 dataset or
run the 100k benchmark. Production CARTO tiles are exercised without fixtures.
Expected 503 responses test recovery. Screenshots are written to a temporary
directory, never to the deployed site.

The real SDK regression suites separately test class/coordinate/refinement and
binary-format semantics. Static checks preserve section anchors, internal links,
navigation destinations, the settlement cap and generated asset placeholders.

The hosted comparison PMTiles allow the production GitHub Pages origin. A local
server may receive a CORS error for those optional remote overlays; the browser
suite uses a tiny fixture instead. Do not weaken remote access policy in this
site refactor. `TRIFOLD_PMTILES_BASE_URL` supports a suitably configured host.

One bounded run reached map source readiness in 1,007 ms (settlement fixture),
1,322 ms (landcheck), 1,167 ms (countrycheck), and 2,333 ms (comparison fixture).
Reference-page load events completed in 49 / 23 ms. These single-run local
measurements include live CARTO/CDN access where applicable; they are not a
performance guarantee or a like-for-like scientific dataset benchmark.

Regeneration is deterministic. During implementation the shared CSS/JS weighed
about 37 KB raw / 11 KB gzip (sum of four assets, excluding MapLibre,
SDKs and scientific payloads), below the issue's 30 KB gzip target. HTML byte
counts: index 11,284,997; landcheck 259,473; countrycheck 450,349;
settlementcheck 8,462; SDK API 11,857; technical reference 15,280. HTML savings
mostly reflect extracting cacheable runtime code, not shrinking scientific data.

Review concepts and the visual comparison ledger live in `design/issue-20/`.
No automatic publish or merge step is part of this work.
