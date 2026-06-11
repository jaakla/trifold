#!/usr/bin/env python
"""Build docs/index.html — Trifold (T3) landing page with embedded
interactive 7-system DGGS comparison viewer (GitHub Pages ready).
"""
import base64
import gzip
import json
import os
import shutil

DATA = 'data'
OUT = 'docs/index.html'
OUT_LANDCHECK = 'docs/landcheck.html'
JS_SDK = 'js/trifold.js'
DOCS_SDK = 'docs/sdk/trifold.js'
LANDCHECK_SDK = 'landcheck/js/landcheck.mjs'
DOCS_LANDCHECK_SDK = 'docs/sdk/landcheck.mjs'
LANDCHECK_TFLS = 'landcheck/data/landsea_L10.tfls'
GH = 'https://github.com/jaakla/trifold'
PMTILES_BASE_URL = os.environ.get('TRIFOLD_PMTILES_BASE_URL', 'https://maps.goplex.ee/data').rstrip('/')

EMBED = {
    'a5_compacted':       'cmp_a5_compacted.topojson',
    'a5_uncompacted':     'cmp_a5_uncompacted.topojson',
    'h3_compacted':       'cmp_h3_compacted.topojson',
    'h3_uncompacted':     'cmp_h3_uncompacted.topojson',
    's2_compacted':       'cmp_s2_compacted.topojson',
    's2_uncompacted':     'cmp_s2_uncompacted.topojson',
    'rhpx_compacted':     'cmp_rhealpix_compacted.topojson',
    'rhpx_uncompacted':   'cmp_rhealpix_uncompacted.topojson',
    'htm_compacted':      'cmp_htm_compacted.topojson',
    'htm_uncompacted':    'cmp_htm_uncompacted.topojson',
    'rect_compacted':     'cmp_rectquad_compacted.topojson',
    'rect_uncompacted':   'cmp_rectquad_uncompacted.topojson',
}
for level in range(4, 11):
    for mode in ('compacted', 'uncompacted'):
        for group in ('triangle', 'rhombus', 'hex'):
            suffix = '' if group == 'triangle' else f'_{group}'
            key = f'tri_L{level}_{mode}{suffix}'
            EMBED[key] = f'global_tri_L{level}_{mode}{suffix}.topojson'

datasets = {}
pmtiles = {}
dataset_stats = {}
total = 0
for key, fn in EMBED.items():
    stem = fn.removesuffix('.topojson')
    pm_name = f'{stem}.pmtiles'
    pm_src = os.path.join(DATA, pm_name)
    if os.path.isfile(pm_src):
        # PMTiles served from Cloudflare R2, no local copy needed
        pmtiles[key] = {'url': f'{PMTILES_BASE_URL}/{pm_name}', 'sourceLayer': 'cells'}

        geojson_path = os.path.join(DATA, f'{stem}.geojson')
        if not os.path.isfile(geojson_path):
            raise FileNotFoundError(
                f'{pm_src} exists but {geojson_path} is needed for viewer stats')
        with open(geojson_path) as src:
            features = json.load(src)['features']
        by_level = {}
        interior = 0
        for feature in features:
            props = feature['properties']
            level = str(props['level'])
            by_level[level] = by_level.get(level, 0) + 1
            interior += bool(props.get('interior'))
        dataset_stats[key] = {
            'count': len(features),
            'interior': interior,
            'byLevel': by_level,
        }
        print(f"pmtiles: {key} -> {pmtiles[key]['url']}")
        continue

    raw = open(os.path.join(DATA, fn), 'rb').read()
    gz = gzip.compress(raw, 9, mtime=0)
    datasets[key] = base64.b64encode(gz).decode()
    total += len(datasets[key])
print(f"embedded payload: {total/1e6:.1f} MB b64 across {len(datasets)} datasets")

data_js = (
    "const DATASETS = {\n" + ",\n".join(
        f'  {json.dumps(k)}: {json.dumps(v)}' for k, v in datasets.items()) +
    "\n};\n" +
    f"const PMTILES_DATASETS = {json.dumps(pmtiles, separators=(',', ':'))};\n" +
    f"const DATASET_STATS = {json.dumps(dataset_stats, separators=(',', ':'))};")

html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trifold (T3): a triangular DGGS with exact nesting</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Trifold (T3): a hierarchical triangular discrete global grid system with exact aperture-4 nesting, compact base32 addressing, and an interactive 7-system DGGS comparison.">
<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<link href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/topojson-client@3/dist/topojson-client.min.js"></script>
<script src="https://unpkg.com/pmtiles@3/dist/pmtiles.js"></script>
<style>
  :root{--ink:#1c2733;--mut:#5b6b7b;--acc:#2b6f9a;--warm:#d94e2f;--bg:#fbfaf7;--card:#fff}
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);
    background:var(--bg);line-height:1.55}
  nav{position:sticky;top:0;z-index:50;background:rgba(251,250,247,.92);backdrop-filter:blur(6px);
    border-bottom:1px solid #e4e0d6;display:flex;gap:18px;align-items:center;padding:10px 22px;
    flex-wrap:wrap}
  nav .brand{font-weight:800;font-size:17px;letter-spacing:.01em}
  nav .brand .t3{color:var(--warm)}
  nav a{color:var(--mut);text-decoration:none;font-size:13.5px}
  nav a:hover{color:var(--acc)}
  nav .libs{margin-left:auto;display:flex;align-items:center;gap:7px}
  nav .libslabel{font-size:10px;font-weight:700;text-transform:uppercase;
    letter-spacing:.08em;color:var(--mut)}
  nav .applink{border:1.5px solid var(--acc);color:var(--acc);padding:3px 11px;
    border-radius:999px;font-weight:600}
  nav a.applink:hover{background:var(--acc);color:#fff}
  nav .applink .tag{font-size:10px;font-weight:700;text-transform:uppercase;
    letter-spacing:.06em;opacity:.7;margin-left:4px}
  nav .applink.soon{border-style:dashed;opacity:.55;cursor:default;font-weight:500}
  nav .gh{display:flex;align-items:center;gap:6px;background:var(--ink);color:#fff;
    padding:6px 9px;border-radius:8px;line-height:0}
  section{max-width:1020px;margin:0 auto;padding:44px 22px;scroll-margin-top:64px}
  .hero{text-align:center;padding-top:64px}
  .hero h1{font-size:clamp(28px,5vw,46px);margin:0 0 10px;letter-spacing:-.02em}
  .hero h1 .t3{color:var(--warm)}
  .hero p.lede{font-size:clamp(15px,2.2vw,19px);color:var(--mut);max-width:760px;margin:0 auto 26px}
  .cta{display:inline-block;margin:6px;padding:11px 22px;border-radius:8px;text-decoration:none;
    font-weight:600;font-size:15px}
  .cta.primary{background:var(--warm);color:#fff}
  .cta.ghost{border:1.5px solid var(--ink);color:var(--ink)}
  h2{font-size:26px;margin:0 0 14px;letter-spacing:-.01em}
  h3{font-size:18px;margin:22px 0 8px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:18px}
  .card{background:var(--card);border:1px solid #e7e2d8;border-radius:10px;padding:16px 18px}
  .card b{display:block;margin-bottom:6px;font-size:15px}
  .card p{margin:0;font-size:13.5px;color:var(--mut)}
  table{border-collapse:collapse;width:100%;font-size:13px;margin:14px 0;background:var(--card)}
  th,td{border:1px solid #e2ddd2;padding:7px 9px;text-align:left;vertical-align:top}
  th{background:#f2efe7}
  td b,th b{color:var(--ink)}
  .good{color:#176b3a;font-weight:600}
  .bad{color:#a23b1e;font-weight:600}
  code,.mono{font-family:ui-monospace,SFMono-Regular,monospace;font-size:.92em;background:#f1ede3;
    padding:1px 5px;border-radius:4px}
  pre{background:#22282f;color:#e8e6df;padding:14px 16px;border-radius:8px;overflow-x:auto;
    font-size:12.5px;line-height:1.5}
  pre code{background:none;color:inherit;padding:0}
  .twocol{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:760px){.twocol{grid-template-columns:1fr}}
  ul{padding-left:20px}li{margin:5px 0;font-size:14px}
  .muted{color:var(--mut);font-size:13px}
  .bitbox{font-family:ui-monospace,monospace;font-size:12px;background:#22282f;color:#e8e6df;
    padding:12px;border-radius:8px;overflow-x:auto;white-space:pre}
  /* viewer */
  #demo{max-width:none;padding:44px 0 0}
  #demo .inner{max-width:1020px;margin:0 auto;padding:0 22px}
  .viewerwrap{position:relative;height:82vh;min-height:520px;margin-top:18px;
    border-top:1px solid #ddd;border-bottom:1px solid #ddd}
  #map{position:absolute;inset:0}
  .panel{position:absolute;top:12px;left:12px;z-index:10;background:rgba(255,255,255,.96);
    padding:12px 14px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.22);
    font-size:13px;width:292px;max-height:calc(82vh - 30px);overflow:auto}
  .row{margin:7px 0}
  .row label{font-weight:600;display:block;margin-bottom:3px;font-size:11px;color:#333;
    text-transform:uppercase;letter-spacing:.05em}
  .seg{display:flex;border:1px solid #999;border-radius:6px;overflow:hidden;flex-wrap:wrap}
  .seg button{flex:1 1 auto;border:0;background:#fff;padding:6px 4px;cursor:pointer;font-size:11.5px;
    min-width:52px}
  .seg button.on{background:var(--acc);color:#fff}
  #stats{color:#444;font-size:12px;margin-top:7px;line-height:1.5}
  #loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
    background:rgba(255,255,255,.7);z-index:20;font-size:15px}
  .legend{margin-top:7px;font-size:11px;line-height:1.7}
  .legend i{display:inline-block;width:12px;height:12px;border-radius:2px;
    vertical-align:middle;margin-right:5px;border:1px solid #555}
  .note{font-size:11px;color:#777;margin-top:7px;line-height:1.45}
  footer{border-top:1px solid #e4e0d6;margin-top:50px;padding:26px 22px;text-align:center;
    color:var(--mut);font-size:13px}
  footer a{color:var(--acc)}
</style>
</head>
<body>

<nav>
  <span class="brand">Trifold <span class="t3">(T3)</span></span>
  <a href="#concept">Concept</a>
  <a href="#addressing">Addressing</a>
  <a href="#demo">Live demo</a>
  <a href="#compare">Comparison</a>
  <a href="#usecases">Use cases</a>
  <a href="#serving">Serving</a>
  <a href="https://github.com/jaakla/trifold/blob/main/docs/t3-technical-reference.md" target="_blank" rel="noopener">Tech reference</a>
  <span class="libs"><span class="libslabel">libraries</span>
    <a class="applink" href="landcheck.html">landcheck</a>
    <span class="applink soon" title="on the roadmap: offline country lookup, same approach">countrycheck<span class="tag">soon</span></span>
  </span>
  <a class="gh" href="__GH__" target="_blank" aria-label="GitHub" title="GitHub">__GHICON__</a>
</nav>

<section class="hero">
  <h1>Trifold <span class="t3">(T3)</span><br>triangles that nest <em>exactly</em></h1>
  <p class="lede">A hierarchical triangular discrete global grid system on the icosahedron.
  Every parent cell is <b>bit-for-bit the union of its four children</b>, something neither
  hexagons nor pentagons can offer. A ~110&nbsp;km cell has a 6-character address.</p>
  <a class="cta primary" href="#demo">Launch the comparison demo</a>
</section>

<section id="libraries">
  <h2>Built on Trifold: ready-to-use libraries</h2>
  <div class="twocol" style="align-items:center">
    <div>
      <h3 style="margin-top:0">▲ landcheck: offline land/sea lookup</h3>
      <p>The first practical proof of concept of exact nesting: the level-10 land
      classification (~6.15M land-touching cells) collapses into 153,884
      run-length intervals: a <b>182&nbsp;KB</b> dataset that answers
      <i>"is this point on land?"</i> in microseconds, fully offline, in Python
      and JavaScript, with a confidence value for every answer. Optional OSM
      refinement sharpens coastal answers to a near-exact polygon test.</p>
      <p><a class="cta primary" style="padding:9px 18px;font-size:14px"
        href="landcheck.html">Try the interactive demo</a></p>
      <p class="muted">Next on the roadmap is <b>countrycheck</b>, an offline country
      lookup using the same run-length approach with border-cell polygons.</p>
    </div>
    <a href="landcheck.html" style="display:block">
      <img src="img/landcheck_demo.jpg" alt="landcheck demo: points classified as land, coast and sea on a world map"
        style="width:100%;border:1px solid #e0dbd0;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.08)">
    </a>
  </div>
</section>

<section id="concept">
  <h2>The idea in 30 seconds</h2>
  <p>Start from the icosahedron: 20 spherical triangles covering the Earth. Split every
  triangle into 4 by connecting the great-circle midpoints of its edges. Repeat. Each level
  halves the edge length and quadruples the cell count (<i>aperture&nbsp;4</i>). Because
  children are built from the parent's own vertices plus edge midpoints, a parent cell is
  exactly the union of its children: aggregating data up the hierarchy or drilling down loses
  nothing and double-counts nothing.</p>
  <table>
    <tr><th>level</th><th>mean edge</th><th>mean area</th><th>cells (global)</th></tr>
    <tr><td>0</td><td>7,054 km</td><td>25.5M km²</td><td>20</td></tr>
    <tr><td>3</td><td>882 km</td><td>399k km²</td><td>1,280</td></tr>
    <tr><td>6</td><td>110 km</td><td>6,226 km²</td><td>81,920</td></tr>
    <tr><td>9</td><td>13.8 km</td><td>97 km²</td><td>5.2M</td></tr>
    <tr><td>12</td><td>1.7 km</td><td>1.5 km²</td><td>336M</td></tr>
    <tr><td>15</td><td>215 m</td><td>24 ha</td><td>21.5B</td></tr>
  </table>
  <div class="cards">
    <div class="card"><b>Exact nesting</b><p>Parent = union of 4 children, verified to
      floating-point noise (10⁻¹⁹ of cell area). Lossless multi-resolution aggregation.</p></div>
    <div class="card"><b>Poles and antimeridian</b><p>Both poles are lattice vertices:
      six meridian wedges meet at exactly ±90°. Antimeridian cells use continuous longitudes
      and are flagged. Classification uses polygon geometry.</p></div>
    <div class="card"><b>Compacted coverage</b><p>Interior cells merge up the quadtree as far
      as they stay wholly on land; coastlines stay fine. 27,614 → 10,046 cells at level 6,
      identical 171.1M km² coverage.</p></div>
    <div class="card"><b>Three address forms</b><p>One identity: compact base32 for humans,
      digit path for teaching, and a sortable uint64 for compute where a subtree is one contiguous range.</p></div>
  </div>
</section>

<section id="addressing">
  <h2>Addressing: one identity, three encodings</h2>
  <p>A cell is <code>(face, path)</code>: one of 20 icosahedron faces plus a base-4 digit per
  subdivision level (<code>0,1,2</code> = corner children, <code>3</code> = central flipped
  child). London at level 6:</p>
  <table>
    <tr><th>form</th><th>example</th><th>for</th><th>size</th></tr>
    <tr><td><b>compact</b></td><td><code>TF6958</code></td><td>humans, URLs, labels</td>
      <td>3 + ⌈2L/5⌉ chars</td></tr>
    <tr><td><b>path</b></td><td><code>F15-102111</code></td><td>teaching, debugging</td>
      <td>4 + L chars</td></tr>
    <tr><td><b>addr64</b></td><td><code>8811996358392152070</code></td><td>compute: sort, join, mask</td>
      <td>8 bytes</td></tr>
  </table>
  <p>Each triangle also carries two derived grouping keys. <code>rhombus_id</code> pairs
  triangles exactly; <code>rhombus_hilbert</code> orders those pairs spatially within ten
  base diamonds. <code>hex_id</code> provides six-triangle groups inside each icosahedron
  face, with documented seam and vertex exceptions. These keys do not replace
  <code>addr64</code> or change the source geometry.</p>
  <div class="bitbox"> 63       59                                                       5     0
 ┌─────────┬────────────────────────────────────────────────────────┬─────┐
 │ face:5  │ path digits, 2 bits each, left-aligned                 │ L:5 │
 └─────────┴────────────────────────────────────────────────────────┴─────┘
 numeric sort = hierarchical order · ancestor test = shift + compare
 descendant_range(cell) = inclusive subtree interval</div>
  <pre><code>$ pip install -e . &amp;&amp; trifold locate -0.1276 51.5072 6
TF6958
$ trifold show TF6958        # → path F15-102111 · edge ~117 km · area 5,864 km²
$ curl https://YOUR-WORKER.workers.dev/locate/-0.1276,51.5072?level=6
{"id":"TF6958","path":"F15-102111","addr64":"8811996358392152070","level":6}</code></pre>
  <p class="muted">Why base32 instead of digits 0–3? A digit string spends 8 bits per character
  to carry 2 bits. Crockford base32 packs 5 bits/char with no ambiguous I/L/O/U: same path
  bits at 40% of the length, URL-safe.</p>
</section>

<section id="demo">
  <div class="inner">
    <h2>Live demo: 7 grid systems, one map</h2>
    <p>Trifold triangles vs <a href="https://a5geo.org" target="_blank">A5</a> pentagons,
    H3 hexagons, S2 quads, rHEALPix, HTM (a related octahedral grid) and a plain lon/lat
    grid. Each layer uses the same land mask and styling. Toggle <b>globe ↔ flat</b> to compare
    the globe and Mercator projections; click any cell for its address and properties.</p>
  </div>
  <div class="viewerwrap">
    <div id="map"></div>
    <div id="loading">Loading grid data…</div>
    <div class="panel">
      <div class="row"><label>System</label>
        <div class="seg" id="seg-sys">
          <button data-v="tri" class="on">T3 ▲</button>
          <button data-v="a5">A5 ⬠</button>
          <button data-v="h3">H3 ⬡</button>
          <button data-v="s2">S2 ◻</button>
          <button data-v="rhpx">rHPX</button>
          <button data-v="htm">HTM</button>
          <button data-v="rect">lon/lat</button>
        </div></div>
      <div class="row" id="row-level"><label>T3 base resolution</label>
        <div class="seg" id="seg-level">
          <button data-v="4">~440 km</button>
          <button data-v="5">~220 km</button>
          <button data-v="6" class="on">~110 km</button>
          <button data-v="7">~55 km</button>
          <button data-v="8">~28 km</button>
          <button data-v="9">~14 km</button>
          <button data-v="10">~7 km</button>
        </div></div>
      <div class="row" id="row-group"><label>Group as</label>
        <div class="seg" id="seg-group">
          <button data-v="triangle" class="on">Triangle ▲</button>
          <button data-v="rhombus">Rhombus ◆</button>
          <button data-v="hex">Hex group ⬡</button>
        </div></div>
      <div class="row"><label>Hierarchy</label>
        <div class="seg" id="seg-mode">
          <button data-v="compacted" class="on">Compacted</button>
          <button data-v="uncompacted">Uncompacted</button>
        </div></div>
      <div class="row"><label>Projection</label>
        <div class="seg" id="seg-proj">
          <button data-v="globe" class="on">Globe</button>
          <button data-v="mercator">Flat</button>
        </div></div>
      <div class="legend" id="legend"></div>
      <div id="stats"></div>
      <div class="note" id="sysnote"></div>
    </div>
  </div>
</section>

<section id="compare">
  <h2>Grid system comparison</h2>
  <table>
    <tr><th></th><th><b>T3</b> (this)</th><th>A5</th><th>H3</th><th>S2</th><th>rHEALPix</th><th>HTM/QTM</th></tr>
    <tr><td>base solid</td><td>icosahedron</td><td>dodecahedron</td><td>icosahedron</td>
        <td>cube</td><td>cube (HEALPix)</td><td>octahedron</td></tr>
    <tr><td>cell shape</td><td>triangle</td><td>pentagon</td><td>hexagon (+12 pentagons)</td>
        <td>quad</td><td>quad (+caps/darts)</td><td>triangle</td></tr>
    <tr><td>aperture / nesting</td><td class="good">4, exact</td>
        <td>4, logical only</td><td class="bad">7, approximate</td>
        <td class="good">4, exact</td><td class="good">9, exact</td><td class="good">4, exact</td></tr>
    <tr><td>equal area</td><td>~±20%, smooth</td><td class="good">exact per level</td>
        <td>~2× max/min</td><td>up to ~2×</td><td class="good">near-exact</td>
        <td class="bad">larger deformation</td></tr>
    <tr><td>edge neighbours</td><td>3 (+9 vertex)</td><td>5</td>
        <td class="good">6 uniform</td><td>4</td><td>4</td><td>3 (+vertex)</td></tr>
    <tr><td>index</td><td>uint64, prefix=subtree</td><td>uint64, Hilbert</td>
        <td>uint64</td><td>uint64, Hilbert</td><td>string</td><td>quadtree string</td></tr>
    <tr><td>ecosystem</td><td>this repository (2026)</td><td>introduced in 2025</td>
        <td class="good">widely used</td><td class="good">widely used</td>
        <td>academic / OGC</td><td>astronomy</td></tr>
  </table>
  <p>Selection depends on the application. <b>H3</b> provides uniform neighbour traversal and
  a mature ecosystem; <b>S2</b> focuses on spatial indexing; <b>rHEALPix</b> and
  <a href="https://a5geo.org" target="_blank"><b>A5</b></a> provide equal-area cells. T3
  focuses on exact hierarchical aggregation, variable-resolution tilings, and pipelines based
  on triangular geometry. Full analysis:
  <a href="t3-technical-reference.md">technical reference</a>.</p>
</section>

<section id="usecases">
  <h2>Suitable uses and limitations</h2>
  <div class="twocol">
    <div class="card"><b>Suitable uses</b><ul>
      <li><b>Lossless multi-resolution aggregation</b>: level-9 sums roll into level-6 cells
        exactly; no slivers, no overlap weighting.</li>
      <li><b>Variable-resolution coverage</b>: compacted tilings retain shared boundaries; any subtree
        is one uint64 range scan.</li>
      <li><b>Simplicial pipelines</b>: FEM/FVM meshes, TINs, barycentric interpolation,
        subdivision surfaces plug in directly.</li>
      <li><b>Geodesic properties</b>: no polar singularity; ~±20% smooth area variation
        worldwide vs 17× collapse for lon/lat at 80°N.</li>
      <li><b>Survey/sampling designs</b> where hierarchy beats neighbour traversal.</li>
    </ul></div>
    <div class="card"><b>Limitations</b><ul>
      <li><b>Neighbour-heavy algorithms</b>: 3 edge + 9 vertex neighbours with alternating
        orientation; hexagonal grids provide 6 uniform neighbours.</li>
      <li><b>General-audience choropleths</b>: triangle boundaries can be visually prominent.</li>
      <li><b>Orientation-sensitive statistics</b>: up/down cells are congruent but rotated 60°.</li>
      <li><b>City-scale local work</b>: a projected CRS and planar grid may be simpler.</li>
    </ul></div>
  </div>
</section>

<section id="serving">
  <h2>Serving at scale</h2>
  <div class="cards">
    <div class="card"><b>Automatic source selection</b><p>This page uses PMTiles when a
      matching archive exists in <code>data/</code> and falls back to embedded, gzip-compressed
      TopoJSON for other datasets.</p></div>
    <div class="card"><b>PMTiles</b><p><code>scripts/make_pmtiles.sh</code> tiles any product
      with tippecanoe into a single static file; host on anything with HTTP Range support.
      Suitable for full-grid display at level 7 and above.</p></div>
    <div class="card"><b>Cloudflare Worker</b><p><code>worker/cell-server.js</code> serves with zero
      stored data, cells regenerated from geometry and edge-cached. Suitable for retrieving
      selected cells, including addresses produced by a database join on addr64.</p></div>
  </div>
</section>

<footer>
  Trifold (T3) · MIT license · <a href="__GH__" target="_blank">github.com/jaakla/trifold</a> ·
  <a href="t3-technical-reference.md">technical reference</a> ·
  land data <a href="https://www.naturalearthdata.com/" target="_blank">Natural Earth</a> ·
  comparison layers via pya5, h3-py, s2sphere, rhealpixdggs ·
  built with MapLibre GL &amp; topojson-client
</footer>

<script type="module">
import {fromPath} from './sdk/trifold.js';
__DATA__

const LEVEL_COLORS={0:'#3f0008',1:'#67000d',2:'#a50f15',3:'#cb181d',4:'#ef3b2c',
  5:'#fb6a4a',6:'#fc9272',7:'#fcbba1',8:'#fee0d2'};
const COASTAL='#74a9cf';

const SYS_NOTES={
 tri:'Trifold (T3): icosahedral triangles, exact aperture-4 nesting. Click a cell for its '+
     'compact base32 address, digit path and uint64. Pole cells are meridian wedges reaching '+
     '±90°. Mercator clips them; Globe displays the complete geometry.',
 a5:'<a href="https://a5geo.org" target="_blank">A5</a> (Felix Palmer, 2025): dodecahedral '+
    'pentagons, res 6 (~8,300 km²), with equal area within each level. '+
    'Aperture-4 hierarchy is <i>logical</i>: parents only approximately cover children. '+
    'Compacted via native a5.compact.',
 h3:'Uber H3, res 3 hexagons (~12,400 km²), with 12 pentagons globally. Aperture-7 '+
    'parents only approximately contain children; compacted via native h3.compact_cells.',
 s2:'Google S2 (via s2sphere), level 6 (~20,750 km²). Cube-sphere quadtree with exact '+
    'aperture-4 nesting and Hilbert indexing; cell areas vary ~2× face-centre to '+
    'corner. The pole sits at a cube-face centre = shared corner of 4 cells.',
 rhpx:'rHEALPix res 4 (~12,950 km², aperture 9: 3×3 children with exact nesting). Near-exact '+
    'equal area with polar cap and dart cells. The grid is included in the OGC DGGS standard.',
 htm:'HTM-style octahedral triangles, level 6 (~15,570 km²), based on the astronomy grid '+
    'and generated here on an octahedron. Its 90° faces produce more shape deformation than '+
    'the T3 icosahedron.',
 rect:'Plain lon/lat quadtree, level 7 (~15,500 km² at the equator, shrinking toward the '+
    'poles). Globe view shows the convergence of meridians at the poles.',
};
const GROUP_NOTES={
 triangle:' The triangle layer is the source geometry and exact accounting unit.',
 rhombus:' Full-grid rhombi are exact two-triangle groups with a nested Hilbert-addressed diamond hierarchy. Land-filtered layers may show partial groups.',
 hex:' Hex groups contain six triangles in face interiors. Icosahedron seams and vertices have smaller or phase-shifted groups.',
};

let state={sys:'tri',level:'6',mode:'compacted',group:'triangle',proj:'globe'};
const cache={};
const protocol=new pmtiles.Protocol();
maplibregl.addProtocol('pmtiles',protocol.tile);

async function decode(key){
  if(cache[key])return cache[key];
  const b=Uint8Array.from(atob(DATASETS[key]),c=>c.charCodeAt(0));
  const stream=new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip'));
  const topo=JSON.parse(await new Response(stream).text());
  const gj=topojson.feature(topo,topo.objects[Object.keys(topo.objects)[0]]);
  if(key.startsWith('tri_'))for(const feature of gj.features)
    if(feature.properties.path&&!feature.properties.addr64)
      feature.properties.addr64=fromPath(feature.properties.path).toString();
  cache[key]=gj;return gj;
}
function dataKey(){
  if(state.sys!=='tri')return `${state.sys}_${state.mode}`;
  const suffix=state.group==='triangle'?'':`_${state.group}`;
  return `tri_L${state.level}_${state.mode}${suffix}`;
}

const fillPaint={
  'fill-color':['case',['!',['get','interior']],COASTAL,
    ['match',['get','level'],0,LEVEL_COLORS[0],1,LEVEL_COLORS[1],2,LEVEL_COLORS[2],
     3,LEVEL_COLORS[3],4,LEVEL_COLORS[4],5,LEVEL_COLORS[5],6,LEVEL_COLORS[6],
     7,LEVEL_COLORS[7],LEVEL_COLORS[8]]],
  'fill-opacity':0.55};
function addGridLayers(sourceLayer){
  const sourceSpec={source:'grid'};
  if(sourceLayer)sourceSpec['source-layer']=sourceLayer;
  map.addLayer({id:'grid-fill',type:'fill',...sourceSpec,paint:fillPaint});
  map.addLayer({id:'grid-line',type:'line',...sourceSpec,
    paint:{'line-color':'#333','line-width':0.5,'line-opacity':0.7}});
}
function replaceGridSource(source,sourceLayer){
  if(map.getLayer('grid-line'))map.removeLayer('grid-line');
  if(map.getLayer('grid-fill'))map.removeLayer('grid-fill');
  if(map.getSource('grid'))map.removeSource('grid');
  map.addSource('grid',source);
  addGridLayers(sourceLayer);
}

const map=new maplibregl.Map({
  container:'map',
  style:{version:8,projection:{type:'globe'},
    sources:{carto:{type:'raster',
      tiles:['https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',
             'https://b.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png'],
      tileSize:256,attribution:'© OpenStreetMap © CARTO · Trifold (T3) demo'}},
    layers:[{id:'bg',type:'background',paint:{'background-color':'#cfe3ef'}},
            {id:'base',type:'raster',source:'carto'}]},
  center:[10,30],zoom:1.6});
map.addControl(new maplibregl.NavigationControl());

map.on('load',async()=>{
  map.addSource('grid',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
  addGridLayers();
  map.on('click','grid-fill',e=>{
    const p=e.features[0].properties;
    let html=`<b>${p.id}</b><br>level ${p.level}`;
    if(p.path)html+=`<br>path <span style="font-family:monospace">${p.path}</span>`+
      `<br>uint64 <span style="font-family:monospace">${p.addr64}</span>`;
    if(p.rhombus_id)html+=`<br>rhombus <span style="font-family:monospace">${p.rhombus_id}</span>`;
    if(p.rhombus_hilbert)html+=`<br>Hilbert <span style="font-family:monospace">${p.rhombus_hilbert}</span>`;
    if(p.hex_id)html+=`<br>hex group <span style="font-family:monospace">${p.hex_id}</span>`;
    if(p.triangle_count)html+=`<br>${p.triangle_count} source triangle${p.triangle_count===1?'':'s'}`;
    if(p.edge_km)html+=`<br>edge ~${p.edge_km} km`;
    if(p.area_km2)html+=`<br>area ${Number(p.area_km2).toLocaleString()} km²`;
    html+=`<br>${p.interior?'interior':'coastal (mixed)'}`;
    if(p.pole)html+=`<br>pole: ${p.pole}`;
    if(p.xam)html+='<br>crosses antimeridian';
    if(p.pent)html+='<br><b>pentagon!</b>';
    if(p.shape&&p.shape!=='quad')html+=`<br>shape: ${p.shape}`;
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(html).addTo(map);
  });
  map.on('mouseenter','grid-fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','grid-fill',()=>map.getCanvas().style.cursor='');
  await refresh();
});

async function refresh(){
  document.getElementById('loading').style.display='flex';
  document.getElementById('row-level').style.display=state.sys==='tri'?'block':'none';
  document.getElementById('row-group').style.display=state.sys==='tri'?'block':'none';
  const key=dataKey();
  let byLevel={},nInt=0,n=0;
  if(PMTILES_DATASETS[key]){
    const spec=PMTILES_DATASETS[key];
    const url=new URL(spec.url,window.location.href).href;
    replaceGridSource({type:'vector',url:`pmtiles://${url}`},spec.sourceLayer);
    const stats=DATASET_STATS[key];
    byLevel=stats.byLevel;nInt=stats.interior;n=stats.count;
  }else{
    const gj=await decode(key);
    replaceGridSource({type:'geojson',data:gj});
    for(const f of gj.features){
      byLevel[f.properties.level]=(byLevel[f.properties.level]||0)+1;
      if(f.properties.interior)nInt++;
    }
    n=gj.features.length;
  }
  const unit=state.sys==='tri'&&state.group!=='triangle'?'groups':'cells';
  document.getElementById('stats').innerHTML=
    `<b>${n.toLocaleString()}</b> ${unit} · ${nInt.toLocaleString()} interior · `+
    `${(n-nInt).toLocaleString()} coastal`;
  document.getElementById('legend').innerHTML=
    Object.keys(byLevel).sort((a,b)=>a-b).map(L=>
      `<i style="background:${LEVEL_COLORS[L]||'#ccc'}"></i>level ${L}: `+
      `${byLevel[L].toLocaleString()}`).join('<br>')+
    `<br><i style="background:${COASTAL}"></i>coastal (mixed)`;
  document.getElementById('sysnote').innerHTML=SYS_NOTES[state.sys]+
    (state.sys==='tri'?GROUP_NOTES[state.group]:'');
  document.getElementById('loading').style.display='none';
}
function wireSeg(id,prop,cb){
  const seg=document.getElementById(id);
  seg.querySelectorAll('button').forEach(b=>{b.onclick=()=>{
    seg.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');state[prop]=b.dataset.v;cb();};});
}
wireSeg('seg-sys','sys',refresh);
wireSeg('seg-level','level',refresh);
wireSeg('seg-group','group',refresh);
wireSeg('seg-mode','mode',refresh);
wireSeg('seg-proj','proj',()=>{
  try{map.setProjection({type:state.proj});}catch(e){console.warn(e);}
});
</script>
</body>
</html>
"""

landcheck_html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>landcheck: offline land/sea lookup (a Trifold library)</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="landcheck: offline land/sea point lookup built on the Trifold (T3) triangular DGGS. 182 KB dataset, microsecond lookups, confidence per answer. Interactive in-browser demo.">
<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<link href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css" rel="stylesheet">
<style>
  :root{--ink:#1c2733;--mut:#5b6b7b;--acc:#2b6f9a;--warm:#d94e2f;--bg:#fbfaf7;--card:#fff;
    --land:#1d7a3f;--coast:#e08a1e;--sea:#2b6f9a}
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);
    background:var(--bg);line-height:1.55}
  nav{position:sticky;top:0;z-index:50;background:rgba(251,250,247,.92);backdrop-filter:blur(6px);
    border-bottom:1px solid #e4e0d6;display:flex;gap:18px;align-items:center;padding:10px 22px;
    flex-wrap:wrap}
  nav .brand{font-weight:800;font-size:17px;display:flex;align-items:baseline;gap:8px;
    flex-wrap:wrap}
  nav .brand .t3{color:var(--warm)}
  nav .brand .sub{font-weight:400;font-size:12px;color:var(--mut)}
  nav .brand .sub a{font-size:12px}
  nav a{color:var(--mut);text-decoration:none;font-size:13.5px}
  nav a:hover{color:var(--acc)}
  nav a.on,nav a:focus-visible{color:var(--acc);font-weight:600}
  nav .gh{margin-left:auto;display:flex;align-items:center;background:var(--ink);color:#fff;
    padding:6px 9px;border-radius:8px;line-height:0}
  section{max-width:1020px;margin:0 auto;padding:38px 22px;scroll-margin-top:64px}
  .hero{text-align:center;padding-top:50px}
  .hero h1{font-size:clamp(26px,4.5vw,40px);margin:0 0 10px;letter-spacing:-.02em}
  .hero p.lede{font-size:clamp(15px,2.1vw,18px);color:var(--mut);max-width:780px;margin:0 auto 22px}
  h2{font-size:24px;margin:0 0 12px;letter-spacing:-.01em}
  h3{font-size:17px;margin:20px 0 8px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:16px}
  .card{background:var(--card);border:1px solid #e7e2d8;border-radius:10px;padding:15px 17px}
  .card b{display:block;margin-bottom:5px;font-size:15px}
  .card p{margin:0;font-size:13.5px;color:var(--mut)}
  table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0;background:var(--card)}
  th,td{border:1px solid #e2ddd2;padding:7px 9px;text-align:left;vertical-align:top}
  th{background:#f2efe7}
  code,.mono{font-family:ui-monospace,SFMono-Regular,monospace;font-size:.92em;background:#f1ede3;
    padding:1px 5px;border-radius:4px}
  pre{background:#22282f;color:#e8e6df;padding:13px 15px;border-radius:8px;overflow-x:auto;
    font-size:12.5px;line-height:1.5}
  pre code{background:none;color:inherit;padding:0}
  .twocol{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:760px){.twocol{grid-template-columns:1fr}}
  ul{padding-left:20px}li{margin:4px 0;font-size:14px}
  .muted{color:var(--mut);font-size:13px}
  /* demo */
  #demo{max-width:none;padding:38px 0 0}
  #demo .inner{max-width:1020px;margin:0 auto;padding:0 22px}
  .viewerwrap{position:relative;height:74vh;min-height:480px;margin-top:16px;
    border-top:1px solid #ddd;border-bottom:1px solid #ddd}
  #map{position:absolute;inset:0}
  .panel{position:absolute;top:12px;left:12px;z-index:10;background:rgba(255,255,255,.96);
    padding:12px 14px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.22);
    font-size:13px;width:280px;max-height:calc(74vh - 30px);overflow:auto}
  .row{margin:7px 0}
  .row label{font-weight:600;display:block;margin-bottom:3px;font-size:11px;color:#333;
    text-transform:uppercase;letter-spacing:.05em}
  .btns{display:flex;gap:6px;flex-wrap:wrap}
  .btns button,.btns .filelabel{border:1px solid #999;background:#fff;border-radius:6px;
    padding:6px 9px;cursor:pointer;font-size:12px}
  .btns button:hover,.btns .filelabel:hover{background:#eef4f8}
  .seg{display:flex;border:1px solid #999;border-radius:6px;overflow:hidden}
  .seg button{flex:1;border:0;background:#fff;padding:6px 4px;cursor:pointer;font-size:11.5px}
  .seg button.on{background:var(--acc);color:#fff}
  #perf{background:#f4f8f4;border:1px solid #cfe0cf;border-radius:8px;padding:9px 11px;
    margin-top:9px;font-size:12.5px;line-height:1.6;display:none}
  #perf b{font-size:15px}
  .legend{margin-top:8px;font-size:12px;line-height:1.8}
  .legend i{display:inline-block;width:11px;height:11px;border-radius:50%;
    vertical-align:middle;margin-right:5px;border:1px solid rgba(0,0,0,.35)}
  .note{font-size:11px;color:#777;margin-top:7px;line-height:1.45}
  #droperr{color:#a23b1e;font-size:12px;margin-top:5px}
  footer{border-top:1px solid #e4e0d6;margin-top:46px;padding:24px 22px;text-align:center;
    color:var(--mut);font-size:13px}
  footer a{color:var(--acc)}
</style>
</head>
<body>

<nav>
  <span class="brand">▲ landcheck
    <span class="sub">offline land/sea lookup, a
      <a href="index.html">Trifold <span class="t3">(T3)</span></a> library</span>
  </span>
  <a href="#demo">Demo</a>
  <a href="#guide">User guide</a>
  <a href="#tech">Technical</a>
  <a href="index.html">← Trifold home</a>
  <a class="gh" href="__GH__/tree/main/landcheck" target="_blank" aria-label="Source on GitHub" title="Source on GitHub">__GHICON__</a>
</nav>

<section class="hero">
  <h1>landcheck: is this point on <span style="color:var(--land)">land</span> or in the <span style="color:var(--sea)">sea</span>?</h1>
  <p class="lede">An offline lookup library built on the Trifold grid. Thanks to exact
  aperture-4 nesting, the level-10 grid (~7&nbsp;km cells) classified against Natural Earth
  collapses into a <b>182&nbsp;KB</b> dataset that answers anywhere on Earth in microseconds,
  with a confidence value for every answer. Python and JavaScript give identical results.
  <b>This page runs the real JS library in your browser</b>; the dataset is embedded right
  in this HTML file.</p>
  <a class="cta" href="#demo" style="display:inline-block;padding:11px 22px;border-radius:8px;
    background:var(--warm);color:#fff;text-decoration:none;font-weight:600">Try it on the map</a>
</section>

<section id="demo">
  <div class="inner">
    <h2>Interactive demo</h2>
    <p>Load sample points or your own file (CSV <code>lon,lat</code> or GeoJSON points), and
    every point is classified <b>in your browser</b> by the bundled library, with no server
    and no network call per lookup. The lookups-per-second figure is measured tightly around
    the classification loop on <i>your</i> machine (map rendering and file parsing excluded),
    so it is the real library throughput. Use the 100k-random button for a stable number.</p>
  </div>
  <div class="viewerwrap">
    <div id="map"></div>
    <div class="panel">
      <div class="row"><label>Sample points</label>
        <div class="btns">
          <button id="b-cities">World cities + tricky spots</button>
          <button id="b-r1">1k random</button>
          <button id="b-r10">10k random</button>
          <button id="b-r100">100k random</button>
        </div></div>
      <div class="row"><label>Your own points</label>
        <div class="btns">
          <label class="filelabel">Open CSV / GeoJSON…
            <input type="file" id="fileinput" accept=".csv,.txt,.json,.geojson" style="display:none">
          </label>
        </div>
        <div id="droperr"></div>
        <div class="note">CSV: <code>lon,lat[,name]</code> per line (or a header naming
        <code>lat</code>/<code>lon</code> columns in either order). GeoJSON: any
        FeatureCollection of Points. Files stay on your machine.</div></div>
      <div class="row"><label>OSM coastal refinement</label>
        <label style="display:flex;gap:7px;align-items:flex-start;cursor:pointer;font-size:12.5px;
            font-weight:400;text-transform:none;letter-spacing:0;color:var(--ink)">
          <input type="checkbox" id="refinecb" style="margin-top:2px">
          <span>exact OSM polygon test wherever the coastline crosses a cell
            (downloads once)</span></label>
        <div class="note" id="refinenote">Off: coastal answers use the bundled
        land-area fraction. On: near-exact coastline. Watch how the counts,
        confidence and lookup rate change.</div></div>
      <div class="row"><label>Debug layers</label>
        <label style="display:flex;gap:7px;align-items:flex-start;cursor:pointer;font-size:12.5px;
            font-weight:400;text-transform:none;letter-spacing:0;color:var(--ink)">
          <input type="checkbox" id="coastcb" style="margin-top:2px">
          <span>source coastline (<b id="coastsrc">NE</b>, follows the
            refinement setting)</span></label>
        <div class="note" id="coastnote">Click anywhere on the map to see the
        level-10 triangle and its classification.</div></div>
      <div class="row"><label>Projection</label>
        <div class="seg" id="seg-proj">
          <button data-v="globe" class="on">Globe</button>
          <button data-v="mercator">Flat</button>
        </div></div>
      <div id="perf"></div>
      <div class="legend">
        <i style="background:#22c55e"></i>land: certain (confidence 1.0)<br>
        <i style="background:#f59e0b"></i>coast: mixed cell<br>
        <i style="background:#16277e"></i>sea: certain (confidence 1.0)<br>
        <i style="background:#fff;border:2px solid #c2185b"></i>answer flipped by OSM refinement
      </div>
      <div class="note" id="loadnote">Loading dataset…</div>
    </div>
  </div>
  <div class="inner">
    <p class="muted" style="margin-top:10px">Click any classified point for its full answer:
    cell address (computed on the fly for sea points, whose cells are not stored), kind,
    confidence and land fraction. Note the Natural Earth 1:50m caveats: lakes count as land
    and islets below its resolution are missing. Switching on the <b>OSM coastal
    refinement</b> makes OSM authoritative in cells crossed by either source coastline. Try the
    cities sample with it on and off and compare the answers near coasts.</p>
  </div>
</section>

<section id="guide">
  <h2>User guide</h2>
  <div class="twocol">
    <div>
      <h3>JavaScript (browser or Node)</h3>
      <pre><code>import { LandCheck } from "./landcheck.mjs";

// Node: bundled file · browser: fetch the 182 KB dataset
const lc = await LandCheck.fromFile();              // Node
const lc = await LandCheck.fromUrl("landsea_L10.tfls"); // browser

lc.isLand(24.7536, 59.437);   // true  (lon, lat)
lc.check(-0.1276, 51.5072);
// { land: true, kind: 'land', confidence: 1,
//   landFraction: 1, cell: 'TFA95BM', refined: false }</code></pre>
    </div>
    <div>
      <h3>Python (stdlib only)</h3>
      <pre><code>from landcheck import LandCheck

lc = LandCheck()                       # bundled data
lc.is_land(24.7536, 59.4370)           # True
lc.check(-0.1276, 51.5072)
# LandResult(land=True, kind='land', confidence=1.0,
#   land_fraction=1.0, cell='TFA95BM', refined=False)

# vectorised: ~2.8 µs/point with numpy
lc.is_land_batch(lons, lats)</code></pre>
    </div>
  </div>
  <h3>What the answer means</h3>
  <table>
    <tr><th>kind</th><th>meaning</th><th><code>land</code></th><th><code>confidence</code></th></tr>
    <tr><td><b>land</b></td><td>cell wholly inside land</td><td>true</td><td>1.0</td></tr>
    <tr><td><b>sea</b></td><td>cell absent from the dataset</td><td>false</td><td>1.0</td></tr>
    <tr><td><b>coast</b></td><td>mixed cell; bundled land-area fraction decides</td>
      <td>fraction ≥ 0.5</td><td>max(f, 1−f)</td></tr>
    <tr><td><b>coast</b> + refined</td><td>decided by the optional OSM polygon layer</td>
      <td>exact</td><td>0.99</td></tr>
  </table>
  <p class="muted">Measured accuracy: 99.82% agreement with exact polygon containment on
  30,000 uniform random points. The <code>land</code> and <code>sea</code> answers were 100%
  correct; all residual error lives in <code>coast</code> answers, which self-report lower
  confidence.
  With the OSM refinement loaded, coastal answers reach 99.95%.</p>
  <h3>Command line</h3>
  <pre><code>$ python landcheck/python/landcheck.py 24.7536 59.4370
LAND  kind=land  confidence=1.000  land_fraction=1.0  cell=TFAVKGR  refined=False</code></pre>
</section>

<section id="tech">
  <h2>Technical info</h2>
  <div class="cards">
    <div class="card"><b>Canonical index</b><p>Any Trifold cell at level ≤ 10 maps to
      <code>addr64 &gt;&gt; 39</code>, a 25-bit integer where a level-l cell covers exactly
      4<sup>10−l</sup> consecutive indices. The whole classification becomes run-length
      intervals.</p></div>
    <div class="card"><b>TFLS format · 182 KB</b><p>153,884 runs as
      <code>varint(gap), varint(len·2|coastal)</code> + a 4-bit land fraction per coastal
      cell, zlib-compressed. Level-agnostic: the same tooling serves an L8 (~30 KB) or
      L12 (~3 MB) variant.</p></div>
    <div class="card"><b>Lookup path</b><p>Pure-float point location (no dependencies,
      bit-identical to the SDK) descends 10 subdivision levels, then one binary search over
      the run starts. ~0.8 µs in Node, ~13 µs in pure Python, ~2.8 µs batched with numpy.</p></div>
    <div class="card"><b>OSM refinement · TFLR</b><p>OSM simplified land polygons clipped
      to every cell crossed by either source coastline, quantized to a cell-local 16-bit grid
      (~0.1 m), with zigzag-varint rings and the even-odd rule. The OSM polygon test can
      override Natural Earth land, sea or fraction answers in those cells.</p></div>
  </div>
  <p style="margin-top:14px">Full documentation, build scripts (<code>build.py</code>,
  <code>refine_build.py</code>) and the cross-language test suite live in
  <a href="__GH__/tree/main/landcheck" target="_blank"><code>landcheck/</code> on GitHub</a>.
  Roadmap: country detection with the same run-length + clipped-border approach, an L12
  variant, published pip/npm packages.</p>
</section>

<footer>
  landcheck · a <a href="index.html">Trifold (T3)</a> application · MIT license ·
  <a href="__GH__/tree/main/landcheck" target="_blank">source</a> ·
  land data <a href="https://www.naturalearthdata.com/" target="_blank">Natural Earth</a> ·
  optional refinement © <a href="https://osmdata.openstreetmap.de/data/land-polygons.html"
  target="_blank">OpenStreetMap contributors</a>
</footer>

<script type="module">
import {LandCheck,locateIndex,indexToCompact,indexToLonLatRing} from './sdk/landcheck.mjs';
const TFLS_B64="__TFLS_B64__";
const TFLR_URLS=['data/coastal_osm_L10.tflr','__TFLR_URL__'];
const NE_URLS=['data/ne_50m_land.geojson','__NE_URL__'];

const KIND_COLOR={land:'#22c55e',coast:'#f59e0b',sea:'#16277e'};
const CITIES=[
 ['Tallinn',24.7536,59.4370],['London',-0.1276,51.5072],['Tokyo',139.6917,35.6895],
 ['New York',-74.006,40.7128],['São Paulo',-46.6333,-23.5505],['Cairo',31.2357,30.0444],
 ['Sydney',151.2093,-33.8688],['Reykjavík',-21.9426,64.1466],['Singapore',103.8198,1.3521],
 ['Mid-Atlantic',-30,30],['South Pacific',-150,-30],['Mariana Trench',142.2,11.35],
 ['Sahara',10,25],['Himalaya',86.92,27.99],['Amazon',-62,-3],
 ['North Pole',0,89.99],['South Pole',0,-89.99],['Antarctica coast',161.69,-79.88],
 ['Fiji (antimeridian)',179.5,-16.6],['Bering Strait',-169.5,65.8],
 ['Venice lagoon',12.34,45.43],['Maldives',73.5,4.2],['Lake Victoria',33,-1],
 ['Gibraltar',-5.35,36.14],['Dover Strait',1.4,51],['Suez',32.55,29.95],
 ['Cape Horn',-67.27,-55.98],['Svalbard',15.6,78.2],['Galápagos',-90.97,-0.74],
 ['Easter Island',-109.35,-27.11]];

// dataset: embedded base64 -> bytes -> LandCheck
const t0=performance.now();
const bytes=Uint8Array.from(atob(TFLS_B64),c=>c.charCodeAt(0));
const lc=await LandCheck.fromBytes(bytes);
const loadMs=performance.now()-t0;
document.getElementById('loadnote').textContent=
  `Dataset: ${(bytes.length/1024).toFixed(0)} KB embedded in this page · `+
  `decoded + indexed in ${loadMs.toFixed(0)} ms · level ${lc.level} `+
  `(${lc.stats.runs.toLocaleString()} runs)`;

function randomPoints(n){
  // uniform on the sphere (not uniform in lat)
  const pts=new Array(n);
  for(let i=0;i<n;i++){
    const lon=Math.random()*360-180;
    const lat=Math.asin(2*Math.random()-1)*180/Math.PI;
    pts[i]=['',lon,lat];
  }
  return pts;
}

// classify: timing measured tightly around the lookup loop only
function classify(pts){
  const results=new Array(pts.length);
  const t0=performance.now();
  for(let i=0;i<pts.length;i++)results[i]=lc.check(pts[i][1],pts[i][2]);
  const ms=performance.now()-t0;
  return {results,ms};
}

let lastPts=null,lastLabel='';
function show(pts,label){
  lastPts=pts;lastLabel=label;
  const {results,ms}=classify(pts);
  let nLand=0,nSea=0,nCoast=0,coastLand=0,nFlipped=0;
  const features=new Array(pts.length);
  for(let i=0;i<pts.length;i++){
    const r=results[i];
    if(r.land)nLand++;else nSea++;
    // a "flip": the OSM polygon test disagrees with the fraction-based guess
    const flipped=r.refined&&r.landFraction!=null&&
      ((r.landFraction>=0.5)!==r.land);
    if(r.kind==='coast'){nCoast++;if(r.land)coastLand++;if(flipped)nFlipped++;}
    features[i]={type:'Feature',
      properties:{name:pts[i][0],kind:r.kind,land:r.land,conf:r.confidence,
        frac:r.landFraction,cell:r.cell,refined:r.refined,flipped,
        color:KIND_COLOR[r.kind]},
      geometry:{type:'Point',coordinates:[pts[i][1],pts[i][2]]}};
  }
  map.getSource('points').setData({type:'FeatureCollection',features});
  const rate=pts.length/(ms/1000);
  const refineOn=document.getElementById('refinecb').checked;
  document.getElementById('perf').style.display='block';
  document.getElementById('perf').innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> lookups/second on this device<br>`+
    `${pts.length.toLocaleString()} points (${label}) classified in ${ms.toFixed(1)} ms `+
    `(${(ms*1000/pts.length).toFixed(2)} µs/point)`+
    `${refineOn?' · <b>OSM refinement on</b>':''}<br>`+
    `answers: <span style="color:${KIND_COLOR.land}">■</span> `+
    `<b>${nLand.toLocaleString()}</b> land · `+
    `<span style="color:${KIND_COLOR.sea}">■</span> <b>${nSea.toLocaleString()}</b> sea<br>`+
    `<span style="color:${KIND_COLOR.coast}">■</span> ${nCoast.toLocaleString()} in coastal `+
    `cells (${coastLand.toLocaleString()} → land, ${(nCoast-coastLand).toLocaleString()} → sea)`+
    `${refineOn?`<br><span style="color:#c2185b">◉</span> <b>${nFlipped.toLocaleString()}</b> `+
      `answer${nFlipped===1?'':'s'} flipped by the OSM polygon test `+
      `(highlighted on the map, click one)`:''}`;
}

function parseCsv(text){
  const lines=text.split(/\\r?\\n/).filter(l=>l.trim());
  if(!lines.length)throw new Error('empty file');
  let lonCol=0,latCol=1,nameCol=2,start=0;
  const head=lines[0].toLowerCase().split(/[;,\\t]/).map(s=>s.trim());
  const latIdx=head.findIndex(h=>/^(lat|latitude|y)$/.test(h));
  const lonIdx=head.findIndex(h=>/^(lon|lng|long|longitude|x)$/.test(h));
  if(latIdx>=0&&lonIdx>=0){
    lonCol=lonIdx;latCol=latIdx;start=1;
    nameCol=head.findIndex(h=>/^(name|label|id|title)$/.test(h));
  }
  const pts=[];
  for(let i=start;i<lines.length;i++){
    const c=lines[i].split(/[;,\\t]/);
    const lon=parseFloat(c[lonCol]),lat=parseFloat(c[latCol]);
    if(!isFinite(lon)||!isFinite(lat))continue;
    if(lon<-180||lon>180||lat<-90||lat>90)continue;
    pts.push([nameCol>=0&&c[nameCol]?c[nameCol].trim():'',lon,lat]);
  }
  if(!pts.length)throw new Error('no valid lon,lat rows found');
  return pts;
}
function parseGeojson(text){
  const gj=JSON.parse(text);
  const features=gj.type==='FeatureCollection'?gj.features:
    gj.type==='Feature'?[gj]:null;
  if(!features)throw new Error('expected a GeoJSON FeatureCollection');
  const pts=[];
  for(const f of features){
    if(!f.geometry)continue;
    const geoms=f.geometry.type==='Point'?[f.geometry.coordinates]:
      f.geometry.type==='MultiPoint'?f.geometry.coordinates:[];
    for(const [lon,lat] of geoms)
      if(isFinite(lon)&&isFinite(lat)&&lon>=-180&&lon<=180&&lat>=-90&&lat<=90)
        pts.push([(f.properties&&(f.properties.name||f.properties.label))||'',lon,lat]);
  }
  if(!pts.length)throw new Error('no Point features found');
  return pts;
}

const map=new maplibregl.Map({
  container:'map',
  style:{version:8,projection:{type:'globe'},
    sources:{carto:{type:'raster',
      tiles:['https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',
             'https://b.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png'],
      tileSize:256,attribution:'© OpenStreetMap © CARTO · Trifold landcheck demo'}},
    layers:[{id:'bg',type:'background',paint:{'background-color':'#cfe3ef'}},
            {id:'base',type:'raster',source:'carto'}]},
  center:[15,30],zoom:1.4,
  canvasContextAttributes:{preserveDrawingBuffer:true}});
map.addControl(new maplibregl.NavigationControl());

// triangle ring (closed, GeoJSON order) of the level-10 cell at a point
function cellRingAt(lon,lat){
  const index=locateIndex(lon,lat,lc.level);
  const ring=indexToLonLatRing(index,lc.level).map(p=>[p[0],p[1]]);
  ring.push(ring[0]);
  return {index,ring};
}
function drawCell(lon,lat){
  const {index,ring}=cellRingAt(lon,lat);
  map.getSource('cell').setData({type:'Feature',properties:{},
    geometry:{type:'Polygon',coordinates:[ring]}});
  return index;
}
function describe(lon,lat,name){
  const r=lc.check(lon,lat);
  let html=name?`<b>${name}</b><br>`:'';
  html+=`<b style="color:${KIND_COLOR[r.kind]}">${r.land?'LAND':'SEA'}</b>`+
    ` · kind <b>${r.kind}</b><br>confidence ${r.confidence.toFixed(3)}`;
  if(r.landFraction!=null)html+=` · land fraction ${r.landFraction.toFixed(3)}`;
  if(r.refined){
    const guess=r.landFraction!=null&&r.landFraction>=0.5;
    html+=(r.landFraction!=null&&guess!==r.land)
      ?`<br><b style="color:#c2185b">flipped by OSM polygon test</b>: the bundled `+
       `fraction (${r.landFraction.toFixed(2)}) would have guessed `+
       `<b>${guess?'LAND':'SEA'}</b>`
      :`<br>decided by OSM polygon test (agrees with the fraction guess)`;
  }
  // sea cells are not stored in the dataset; compute the address on demand
  const cell=r.cell??indexToCompact(locateIndex(lon,lat,lc.level),lc.level);
  html+=`<br>cell <span style="font-family:monospace">${cell}</span>`+
    `${r.cell?'':' <span style="color:#777">(empty = sea)</span>'}`;
  html+=`<br><span style="color:#777;font-size:11px">${lon.toFixed(4)}, ${lat.toFixed(4)}</span>`;
  return html;
}

map.on('load',()=>{
  map.addSource('coast',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'coastline',type:'line',source:'coast',
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':'#7c4a03','line-width':1.4,'line-opacity':0.9}});
  map.addSource('cell',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'cell-fill',type:'fill',source:'cell',
    paint:{'fill-color':'#d94e2f','fill-opacity':0.12}});
  map.addLayer({id:'cell-line',type:'line',source:'cell',
    paint:{'line-color':'#d94e2f','line-width':2}});
  map.addSource('points',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  const flipped=['boolean',['get','flipped'],false];
  map.addLayer({id:'pts',type:'circle',source:'points',paint:{
    'circle-color':['get','color'],
    'circle-radius':['interpolate',['linear'],['zoom'],
      0,['case',flipped,4,2.2],
      4,['case',flipped,5.5,3.5],
      8,['case',flipped,7,5]],
    'circle-opacity':0.85,
    'circle-stroke-width':['case',flipped,2.2,0.6],
    'circle-stroke-color':['case',flipped,'#c2185b','rgba(0,0,0,.4)']}});
  map.on('click',e=>{
    // clicks on a classified point are handled by the 'pts' handler below
    if(map.queryRenderedFeatures(e.point,{layers:['pts']}).length)return;
    let lon=e.lngLat.lng,lat=e.lngLat.lat;
    lon=((lon+180)%360+360)%360-180;
    lat=Math.max(-90,Math.min(90,lat));
    drawCell(lon,lat);
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML(describe(lon,lat,null)).addTo(map);
  });
  map.on('click','pts',e=>{
    const p=e.features[0].properties;
    const [lon,lat]=e.features[0].geometry.coordinates;
    drawCell(lon,lat);
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML(describe(lon,lat,p.name||null)).addTo(map);
  });
  map.on('mouseenter','pts',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','pts',()=>map.getCanvas().style.cursor='');
  map.on('moveend',()=>{if(coastcb.checked&&coastMode()==='osm')updateCoastline();});
  show(CITIES.map(c=>[c[0],c[1],c[2]]),'world cities + tricky spots');
});

document.getElementById('b-cities').onclick=()=>show(CITIES.map(c=>[c[0],c[1],c[2]]),'world cities + tricky spots');
document.getElementById('b-r1').onclick=()=>show(randomPoints(1000),'uniform random on sphere');
document.getElementById('b-r10').onclick=()=>show(randomPoints(10000),'uniform random on sphere');
document.getElementById('b-r100').onclick=()=>show(randomPoints(100000),'uniform random on sphere');
// --- source coastline debug layer (NE polygons / OSM-from-TFLR) ---
const coastcb=document.getElementById('coastcb');
const coastnote=document.getElementById('coastnote');
const coastsrc=document.getElementById('coastsrc');
let neGeojson=null;        // fetched NE land polygons, cached
let cellBoxes=null;        // [index,minx,miny,maxx,maxy] per refined cell, lazy
function coastMode(){return (document.getElementById('refinecb').checked&&refineCells)?'osm':'ne';}

function buildCellBoxes(){
  cellBoxes=[];
  for(const [index,entry] of refineCells){
    if(typeof entry==='number')continue;  // all-land/all-sea: no rings to draw
    const ring=indexToLonLatRing(index,lc.level);
    const lons=ring.map(p=>p[0]),lats=ring.map(p=>p[1]);
    cellBoxes.push([index,Math.min(...lons),Math.min(...lats),
                    Math.max(...lons),Math.max(...lats)]);
  }
}
function osmCoastFeatures(){
  if(!cellBoxes)buildCellBoxes();
  const b=map.getBounds();
  const w=b.getWest(),e=b.getEast(),s=b.getSouth(),n=b.getNorth();
  const lines=[];
  for(const [index,minx,miny,maxx,maxy] of cellBoxes){
    if(maxy<s||miny>n)continue;
    let hit=false;
    for(const off of [-360,0,360]){
      if(maxx+off>=w&&minx+off<=e){hit=true;break;}
    }
    if(!hit)continue;
    const sx=(maxx-minx)/65535,sy=(maxy-miny)/65535;
    // the clipped polygons run along the triangle edges where land continues
    // into the neighbour cell; those segments are clip artifacts, not
    // coastline.  Test vertices against the triangle edges in quantized
    // units and drop segments whose both endpoints lie on the same edge.
    const tri=indexToLonLatRing(index,lc.level)
      .map(p=>[(p[0]-minx)/sx,(p[1]-miny)/sy]);
    const edges=[0,1,2].map(i=>{
      const a=tri[i],c=tri[(i+1)%3];
      const dx=c[0]-a[0],dy=c[1]-a[1];
      return [a[0],a[1],dx,dy,Math.hypot(dx,dy)];
    });
    const EPS=1.5;  // quanta; quantization rounding is at most 0.5
    const onEdge=(x,y,E)=>Math.abs((x-E[0])*E[3]-(y-E[1])*E[2])/E[4]<EPS;
    for(const pts of refineCells.get(index)){
      const m=pts.length/2;
      let current=[];
      for(let i=0;i<m;i++){
        const j=(i+1)%m;
        const x1=pts[2*i],y1=pts[2*i+1],x2=pts[2*j],y2=pts[2*j+1];
        const artifact=edges.some(E=>onEdge(x1,y1,E)&&onEdge(x2,y2,E));
        if(artifact){
          if(current.length>1)lines.push(current);
          current=[];
        }else{
          if(!current.length)current.push([minx+x1*sx,miny+y1*sy]);
          current.push([minx+x2*sx,miny+y2*sy]);
        }
      }
      if(current.length>1)lines.push(current);
    }
    if(lines.length>60000)return null;  // too much detail for this view
  }
  return lines;
}
async function updateCoastline(){
  if(!coastcb.checked){
    map.getSource('coast').setData({type:'FeatureCollection',features:[]});
    return;
  }
  if(coastMode()==='ne'){
    coastsrc.textContent='NE';
    map.setPaintProperty('coastline','line-color','#7c4a03');
    if(!neGeojson){
      coastnote.textContent='Downloading Natural Earth land polygons…';
      for(const url of NE_URLS){
        try{
          const res=await fetch(url);
          if(!res.ok)continue;
          neGeojson=await res.json();
          break;
        }catch(err){console.warn(url,err);}
      }
      if(!neGeojson){
        coastnote.textContent='Could not download the NE land polygons.';
        coastcb.checked=false;return;
      }
    }
    map.getSource('coast').setData(neGeojson);
    coastnote.textContent='Brown line: Natural Earth 1:50m land outlines, the base dataset '+
      'the grid was classified against. Click anywhere for the cell triangle.';
  }else{
    coastsrc.textContent='OSM';
    map.setPaintProperty('coastline','line-color','#8e24aa');
    const lines=osmCoastFeatures();
    if(lines===null){
      map.getSource('coast').setData({type:'FeatureCollection',features:[]});
      coastnote.textContent='OSM refinement geometry: zoom in further to draw it.';
      return;
    }
    map.getSource('coast').setData({type:'Feature',properties:{},
      geometry:{type:'MultiLineString',coordinates:lines}});
    coastnote.textContent=`Purple line: ${lines.length.toLocaleString()} OSM coastline ring(s) `+
      `in view, decoded from the refinement dataset. This is exactly the geometry `+
      `the refined lookup tests against.`;
  }
}
coastcb.onchange=updateCoastline;

// --- OSM coastal refinement toggle ---
let refineCells=null;   // decoded TFLR, kept so the checkbox can flip freely
const refinecb=document.getElementById('refinecb');
const refinenote=document.getElementById('refinenote');
refinecb.onchange=async()=>{
  if(refinecb.checked&&!refineCells){
    refinecb.disabled=true;
    refinenote.textContent='Downloading OSM refinement layer…';
    let loaded=false;
    for(const url of TFLR_URLS){
      try{
        const res=await fetch(url);
        if(!res.ok)continue;
        const buf=await res.arrayBuffer();
        refinenote.textContent=`Decoding ${(buf.byteLength/1e6).toFixed(1)} MB…`;
        await lc.loadRefinement(new Uint8Array(buf));
        refineCells=lc._refine;
        loaded=true;
        refinenote.textContent=`Loaded: ${refineCells.size.toLocaleString()} covered cells with `+
          `OSM polygon detail. Covered answers are now near-exact (confidence 0.99).`;
        break;
      }catch(err){console.warn(url,err);}
    }
    refinecb.disabled=false;
    if(!loaded){
      refinecb.checked=false;
      refinenote.textContent='Could not download the refinement layer, so the bundled fractions stay in use.';
      return;
    }
  }else{
    lc._refine=refinecb.checked?refineCells:null;
    refinenote.textContent=refinecb.checked
      ?'OSM polygon test active in covered coastline cells.'
      :'Off: coastal answers use the bundled land-area fraction.';
  }
  if(lastPts)show(lastPts,lastLabel);   // re-classify so the effect is visible
  updateCoastline();                    // coastline source follows refinement
};
document.getElementById('fileinput').onchange=async e=>{
  const file=e.target.files[0];
  if(!file)return;
  document.getElementById('droperr').textContent='';
  try{
    const text=await file.text();
    const pts=text.trimStart().startsWith('{')?parseGeojson(text):parseCsv(text);
    if(pts.length>500000)throw new Error('too many points (max 500k)');
    show(pts,file.name);
  }catch(err){
    document.getElementById('droperr').textContent=`Could not read ${file.name}: ${err.message}`;
  }
  e.target.value='';
};
document.querySelectorAll('#seg-proj button').forEach(b=>{b.onclick=()=>{
  document.querySelectorAll('#seg-proj button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  try{map.setProjection({type:b.dataset.v});}catch(e){console.warn(e);}
};});
window.__landcheck={map,lc};   // console/debug handle
</script>
</body>
</html>
"""

GH_ICON = ('<svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" '
           'aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 '
           '5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49'
           '-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 '
           '1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78'
           '-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 '
           '0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 '
           '2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07'
           '-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 '
           '.21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>')

os.makedirs('docs', exist_ok=True)
os.makedirs(os.path.dirname(DOCS_SDK), exist_ok=True)
shutil.copy2(JS_SDK, DOCS_SDK)
with open(OUT, 'w') as f:
    f.write(html.replace('__DATA__', data_js).replace('__GH__', GH)
            .replace('__GHICON__', GH_ICON))
print(f"{OUT}: {os.path.getsize(OUT)/1e6:.1f} MB")

shutil.copy2(LANDCHECK_SDK, DOCS_LANDCHECK_SDK)
tfls_b64 = base64.b64encode(open(LANDCHECK_TFLS, 'rb').read()).decode()
# refinement + NE coastline: fetched on demand from the data host in
# production; copy into docs/data/ (gitignored) so the toggles work locally
for src, name in [('landcheck/data/coastal_osm_L10.tflr', 'coastal_osm_L10.tflr'),
                  ('natural-earth-vector/geojson/ne_50m_land.geojson',
                   'ne_50m_land.geojson')]:
    if os.path.isfile(src):
        os.makedirs('docs/data', exist_ok=True)
        shutil.copy2(src, os.path.join('docs/data', name))
with open(OUT_LANDCHECK, 'w') as f:
    f.write(landcheck_html.replace('__TFLS_B64__', tfls_b64)
            .replace('__TFLR_URL__', f'{PMTILES_BASE_URL}/coastal_osm_L10.tflr')
            .replace('__NE_URL__', f'{PMTILES_BASE_URL}/ne_50m_land.geojson')
            .replace('__GH__', GH)
            .replace('__GHICON__', GH_ICON))
print(f"{OUT_LANDCHECK}: {os.path.getsize(OUT_LANDCHECK)/1e6:.1f} MB "
      f"(incl. {len(tfls_b64)/1e3:.0f} KB b64 dataset)")
