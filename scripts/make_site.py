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
JS_SDK = 'js/trifold.js'
DOCS_SDK = 'docs/sdk/trifold.js'
GH = 'https://github.com/jaakla/trifold'

EMBED = {
    'tri_L4_compacted':   'global_tri_L4_compacted.topojson',
    'tri_L4_uncompacted': 'global_tri_L4_uncompacted.topojson',
    'tri_L5_compacted':   'global_tri_L5_compacted.topojson',
    'tri_L5_uncompacted': 'global_tri_L5_uncompacted.topojson',
    'tri_L6_compacted':   'global_tri_L6_compacted.topojson',
    'tri_L6_uncompacted': 'global_tri_L6_uncompacted.topojson',
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
        pmtiles[key] = {'url': f'https://pub-7e631bea93414a488b6a0fec7a7225e5.r2.dev/data/{pm_name}', 'sourceLayer': 'cells'}

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
<title>Trifold (T3) — exact-nesting triangular DGGS</title>
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
  nav .gh{margin-left:auto;background:var(--ink);color:#fff;padding:5px 12px;border-radius:6px}
  section{max-width:1020px;margin:0 auto;padding:44px 22px}
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
  <a href="t3-technical-reference.md">Tech reference</a>
  <a class="gh" href="__GH__" target="_blank">GitHub ↗</a>
</nav>

<section class="hero">
  <h1>Trifold <span class="t3">(T3)</span><br>triangles that nest <em>exactly</em></h1>
  <p class="lede">A hierarchical triangular discrete global grid system on the icosahedron.
  Every parent cell is <b>bit-for-bit the union of its four children</b> — something neither
  hexagons nor pentagons can offer — with a 6-character address for a ~110&nbsp;km cell.</p>
  <a class="cta primary" href="#demo">Launch the comparison demo</a>
  <a class="cta ghost" href="__GH__" target="_blank">Source on GitHub</a>
  <p class="muted">7 grid systems side by side · globe ↔ flat · click any cell for its address</p>
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
      digit path for teaching, sortable uint64 for compute — subtree = contiguous range.</p></div>
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
  to carry 2 bits. Crockford base32 packs 5 bits/char with no ambiguous I/L/O/U — same path
  bits, 40% of the length, URL-safe.</p>
</section>

<section id="demo">
  <div class="inner">
    <h2>Live demo — 7 grid systems, one map</h2>
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
    <tr><td>aperture / nesting</td><td class="good">4, exact congruent</td>
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
      <li><b>Lossless multi-resolution aggregation</b> — level-9 sums roll into level-6 cells
        exactly; no slivers, no overlap weighting.</li>
      <li><b>Variable-resolution coverage</b> — compacted tilings retain shared boundaries; any subtree
        is one uint64 range scan.</li>
      <li><b>Simplicial pipelines</b> — FEM/FVM meshes, TINs, barycentric interpolation,
        subdivision surfaces plug in directly.</li>
      <li><b>Geodesic properties</b> — no polar singularity; ~±20% smooth area variation
        worldwide vs 17× collapse for lon/lat at 80°N.</li>
      <li><b>Survey/sampling designs</b> where hierarchy beats neighbour traversal.</li>
    </ul></div>
    <div class="card"><b>Limitations</b><ul>
      <li><b>Neighbour-heavy algorithms</b> — 3 edge + 9 vertex neighbours with alternating
        orientation; hexagonal grids provide 6 uniform neighbours.</li>
      <li><b>General-audience choropleths</b> — triangle boundaries can be visually prominent.</li>
      <li><b>Orientation-sensitive statistics</b> — up/down cells are congruent but rotated 60°.</li>
      <li><b>City-scale local work</b> — a projected CRS and planar grid may be simpler.</li>
    </ul></div>
  </div>
</section>

<section id="serving">
  <h2>Serving at scale</h2>
  <div class="cards">
    <div class="card"><b>Automatic source selection</b><p>This page uses PMTiles from
      <code>docs/data/</code> when available and falls back to embedded, gzip-compressed
      TopoJSON for other datasets.</p></div>
    <div class="card"><b>PMTiles</b><p><code>scripts/make_pmtiles.sh</code> tiles any product
      with tippecanoe into a single static file; host on anything with HTTP Range support.
      Suitable for full-grid display at level 7 and above.</p></div>
    <div class="card"><b>Cloudflare Worker</b><p><code>worker/cell-server.js</code> — zero
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
 rhpx:'rHEALPix res 4 (~12,950 km², aperture 9 — 3×3 children, exact nesting). Near-exact '+
    'equal area with polar cap and dart cells. The grid is included in the OGC DGGS standard.',
 htm:'HTM-style octahedral triangles, level 6 (~15,570 km²), based on the astronomy grid '+
    'and generated here on an octahedron. Its 90° faces produce more shape deformation than '+
    'the T3 icosahedron.',
 rect:'Plain lon/lat quadtree, level 7 (~15,500 km² at the equator, shrinking toward the '+
    'poles). Globe view shows the convergence of meridians at the poles.',
};

let state={sys:'tri',level:'6',mode:'compacted',proj:'globe'};
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
    feature.properties.addr64=feature.properties.addr64||
      fromPath(feature.properties.path).toString();
  cache[key]=gj;return gj;
}
function dataKey(){
  return state.sys==='tri'?`tri_L${state.level}_${state.mode}`:`${state.sys}_${state.mode}`;
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
  document.getElementById('stats').innerHTML=
    `<b>${n.toLocaleString()}</b> cells · ${nInt.toLocaleString()} interior · `+
    `${(n-nInt).toLocaleString()} coastal`;
  document.getElementById('legend').innerHTML=
    Object.keys(byLevel).sort((a,b)=>a-b).map(L=>
      `<i style="background:${LEVEL_COLORS[L]||'#ccc'}"></i>level ${L}: `+
      `${byLevel[L].toLocaleString()}`).join('<br>')+
    `<br><i style="background:${COASTAL}"></i>coastal (mixed)`;
  document.getElementById('sysnote').innerHTML=SYS_NOTES[state.sys];
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
wireSeg('seg-mode','mode',refresh);
wireSeg('seg-proj','proj',()=>{
  try{map.setProjection({type:state.proj});}catch(e){console.warn(e);}
});
</script>
</body>
</html>
"""

os.makedirs('docs', exist_ok=True)
os.makedirs(os.path.dirname(DOCS_SDK), exist_ok=True)
shutil.copy2(JS_SDK, DOCS_SDK)
with open(OUT, 'w') as f:
    f.write(html.replace('__DATA__', data_js).replace('__GH__', GH))
print(f"{OUT}: {os.path.getsize(OUT)/1e6:.1f} MB")
