#!/usr/bin/env python
"""Build docs/index.html — Trifold T3 landing page with embedded
interactive 7-system DGGS comparison viewer (GitHub Pages ready).
"""
import base64
import gzip
import json
import os
import re
import shutil

DATA = 'data'
OUT = 'docs/index.html'


# --- benchmark bars rendered from the markdown docs (single source of truth) ---
def _bench_rows(md_path, section_substr, value_header):
    """Parse the first markdown table under the heading containing
    `section_substr`, returning [(label, value_float)] for rows whose
    `value_header` column holds a number. Non-numeric rows (TODO, not run)
    are skipped."""
    lines = open(md_path, encoding='utf-8').read().splitlines()
    start = next(i for i, l in enumerate(lines)
                 if l.startswith('#') and section_substr.lower() in l.lower())
    table = []
    for l in lines[start + 1:]:
        if l.lstrip().startswith('|'):
            table.append(l)
        elif table:
            break
    cells = lambda row: [c.strip() for c in row.strip().strip('|').split('|')]
    header = [h.lower() for h in cells(table[0])]
    vcol = next(i for i, h in enumerate(header) if value_header.lower() in h)
    rows = []
    for row in table[2:]:                       # skip header + |---| separator
        c = cells(row)
        label = re.sub(r'\*\*', '', c[0]).strip()
        m = re.search(r'[\d][\d,]*(?:\.\d+)?', re.sub(r'\*\*', '', c[vcol]))
        if not m:
            continue                            # TODO / not run / managed
        rows.append((label, float(m.group(0).replace(',', ''))))
    return rows


def _clean_label(label):
    """Shorten a benchmark row label for the narrow bar column: drop
    parentheticals, version tokens, and transport/mode qualifiers."""
    label = re.sub(r'\([^)]*\)', '', label)                 # (amd64 emulated)
    label = label.split(',')[0]                             # ", uncached" tail
    label = re.sub(r'\b\d[\d.]*(?:\s*/\s*\d[\d.]*)*\b', '', label)  # 1.5.4, 16 / 3.4
    for noise in (' over localhost/Docker', ' scalar', ' on-demand'):
        label = label.replace(noise, '')
    return re.sub(r'\s{2,}', ' ', label).strip()


def render_bench(md_path, section_substr, value_header, unit, title=None):
    """Render `.bench` bars from a markdown table (single source of truth).
    With `title`, prepends an `<h3>`; without, emits only the bar rows."""
    rows = sorted(_bench_rows(md_path, section_substr, value_header),
                  key=lambda r: -r[1])
    top = rows[0][1] if rows else 1.0
    out = [f'<h3>{title}</h3>'] if title else []
    for i, (label, val) in enumerate(rows):
        name = _clean_label(label)
        tf = ' tf' if name.lower().startswith('trifold') else ''
        width = max(val / top * 100, 0.4)
        shown = f'{val:,.0f}{(" " + unit) if i == 0 else ""}'
        out.append(
            f'<div class="brow"><span class="bname">{name}</span>'
            f'<div class="btrack"><div class="bfill{tf}" style="width:{width:.3g}%">'
            f'</div></div><span class="bval">{shown}</span></div>')
    return '\n      '.join(out)
OUT_LANDCHECK = 'docs/landcheck.html'
OUT_COUNTRYCHECK = 'docs/countrycheck.html'
JS_SDK = 'js/trifold.js'
DOCS_SDK = 'docs/sdk/trifold.js'
LANDCHECK_SDK = 'landcheck/js/landcheck.mjs'
DOCS_LANDCHECK_SDK = 'docs/sdk/landcheck.mjs'
LANDCHECK_TFLS = 'landcheck/data/landsea_L10.tfls'
COUNTRYCHECK_SDK = 'countrycheck/js/countrycheck.mjs'
DOCS_COUNTRYCHECK_SDK = 'docs/sdk/countrycheck.mjs'
COUNTRYCHECK_TFCS = 'countrycheck/data/countries_L10.tfcs'
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
<title>Trifold T3: a triangular DGGS with exact nesting</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Trifold T3: a hierarchical triangular discrete global grid system with exact aperture-4 nesting, compact base32 addressing, and an interactive 7-system DGGS comparison.">
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
  /* benchmark teaser bars */
  .bench .brow{display:grid;grid-template-columns:104px 1fr 82px;gap:9px;align-items:center;
    margin:6px 0;font-size:12.5px}
  .bench .bname{text-align:right;white-space:nowrap;overflow:hidden}
  .bench .btrack{min-width:0}
  .bench .bfill{height:15px;border-radius:3px;background:#b9c2cc;min-width:2px}
  .bench .bfill.tf{background:var(--warm)}
  .bench .bval{font-size:11.5px;color:var(--mut);white-space:nowrap}
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
  .phead{display:flex;align-items:center;justify-content:space-between;gap:10px;
    margin:-2px 0 4px;cursor:pointer}
  .phead b{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#333}
  .phead button{border:1px solid #999;background:#fff;border-radius:6px;width:28px;height:24px;
    cursor:pointer;font-size:15px;line-height:1;padding:0;color:#333}
  .panel.min{width:auto;padding:7px 11px}
  .panel.min>:not(.phead){display:none!important}
  .panel.min .phead{margin:0}
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
  /* coverage demo */
  #coverage{max-width:none;padding:44px 0 0}
  #coverage .inner{max-width:1020px;margin:0 auto;padding:0 22px}
  .coverwrap{position:relative;height:74vh;min-height:540px;margin-top:18px;
    border-top:1px solid #ddd;border-bottom:1px solid #ddd;background:#d7e5ed}
  #covermap{position:absolute;inset:0}
  .coverpanel{position:absolute;top:12px;left:12px;z-index:10;background:rgba(255,255,255,.96);
    padding:12px 14px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.22);
    font-size:13px;width:342px;max-height:calc(74vh - 30px);overflow:auto}
  .coverpanel .seg button{min-width:70px}
  .coverpanel.min{width:auto;padding:7px 11px}
  .coverpanel.min>:not(.phead){display:none!important}
  .coverpanel.min .phead{margin:0}
  .coverrange{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center}
  .coverrange input{width:100%}
  .coverlevel{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;color:#333;
    white-space:nowrap}
  .coveractions{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px;margin-top:8px}
  .coveractions button{border:1px solid #999;background:#fff;border-radius:6px;padding:7px 8px;
    cursor:pointer;font-size:12px;font-weight:600;color:#333}
  .coveractions button.primary{background:var(--warm);border-color:var(--warm);color:#fff}
  .coveractions button:hover{filter:brightness(.97)}
  .coverhint{font-size:12px;color:#555;margin:6px 0;line-height:1.4}
  .coverstats{color:#444;font-size:12px;margin-top:8px;line-height:1.5}
  .coverout{max-height:188px;margin:8px 0 0;white-space:pre-wrap;word-break:break-word;
    font-size:11.2px;line-height:1.45}
  @media(max-width:760px){
    .coverwrap{height:82vh;min-height:620px}
    .coverpanel{left:10px;right:10px;top:10px;width:auto;max-height:48vh}
    .coverout{max-height:122px}
  }
  footer{border-top:1px solid #e4e0d6;margin-top:50px;padding:26px 22px;text-align:center;
    color:var(--mut);font-size:13px}
  footer a{color:var(--acc)}
</style>
</head>
<body>

<nav>
  <span class="brand">Trifold <span class="t3">T3</span></span>
  <a href="#concept">Concept</a>
  <a href="#addressing">Addressing</a>
  <a href="#demo">Live demo</a>
  <a href="#coverage">Coverage</a>
  <a href="#compare">Comparison</a>
  <a href="#usecases">Use cases</a>
  <a href="https://github.com/jaakla/trifold/blob/main/docs/t3-technical-reference.md" target="_blank" rel="noopener">Tech reference</a>
  <span class="libs"><span class="libslabel">libraries</span>
    <a class="applink" href="landcheck.html">landcheck</a>
    <a class="applink" href="countrycheck.html"
      title="offline country lookup, same approach">countrycheck<span class="tag">new</span></a>
  </span>
  <a class="gh" href="__GH__" target="_blank" aria-label="GitHub" title="GitHub">__GHICON__</a>
</nav>

<section class="hero">
  <h1>Trifold <span class="t3">T3</span><br>triangles that nest <em>exactly</em></h1>
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
      refinement sharpens coastal answers to a near-exact polygon test. Both
      tools also classify whole <b>routes/polylines</b> into distance-annotated
      segments — try Route mode in either demo.</p>
      <p><a class="cta primary" style="padding:9px 18px;font-size:14px"
        href="landcheck.html">Info and interactive demo</a></p>
      <p class="muted">Its sibling
      <a href="countrycheck.html"><b>countrycheck</b></a> applies the same run-length approach to
      country detection: 256 countries with coastal waters in a 323&nbsp;KB dataset,
      exact border-cell polygons optional.
      <a href="countrycheck.html">Info and interactive demo&nbsp;&rarr;</a></p>
    </div>
    <a href="landcheck.html" style="display:block">
      <img src="img/landcheck_demo.jpg" alt="landcheck demo: points classified as land, coast and sea on a world map"
        style="width:100%;border:1px solid #e0dbd0;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.08)">
    </a>
  </div>
  <div class="bench" style="margin-top:26px">
    <h3>Benchmarked: 3&ndash;30&times; faster than SQL spatial engines</h3>
    <p style="font-size:14px;margin:6px 0 10px">One workload, four engines: classify 100,000
    random points as land or sea against the same OSM land polygons. Trifold-based landcheck
    answered 3&ndash;30&times; faster than BigQuery, PostGIS and DuckDB Spatial in batch mode
    and 40&ndash;100&times; faster called one point at a time &mdash; true to the name, never
    less than a three-fold margin. The same gap should apply to similar
    point-classification problems.</p>
    __INDEX_BENCH__
    <p class="muted" style="margin-top:10px">Batch mode, median of 7 warm runs, Apple M5 Pro,
    June 2026. The SQL engines compute exact polygon containment; landcheck agrees with them
    on 99.5% of points from a far smaller dataset.
    <a href="landcheck.html#benchmark">Full benchmark with methodology and caveats &rarr;</a></p>
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
      <div class="phead"><b>Controls</b>
        <button id="panelmin" aria-label="minimize control panel" title="minimize">–</button></div>
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
  <script>
  (function(){
    var panel=document.querySelector('.panel'),btn=document.getElementById('panelmin');
    function setMin(min){panel.classList.toggle('min',min);btn.textContent=min?'+':'–';
      btn.title=btn.ariaLabel=(min?'expand':'minimize')+' control panel';}
    btn.addEventListener('click',function(e){e.stopPropagation();
      setMin(!panel.classList.contains('min'));});
    panel.querySelector('.phead').addEventListener('click',function(){
      if(panel.classList.contains('min'))setMin(false);});
    if(matchMedia('(max-width:640px)').matches)setMin(true);
  })();
  </script>
</section>

<section id="coverage">
  <div class="inner">
    <h2>Coverage demo: bbox_cover and polyfill</h2>
    <p>Draw a query shape and Trifold returns stable indexes for the triangular cells that overlap it.
    The full output is fixed-level cells; compacted output folds complete sibling sets into variable-level
    parents; ranges are addr64 intervals for subtree scans. Switch on <b>T3 + S2</b> to cover the same
    shape with Google S2 cells (computed live in the browser, area-matched level) and compare how much each
    grid's quadtree <b>compaction</b> folds away.</p>
  </div>
  <div class="coverwrap">
    <div id="covermap"></div>
    <div class="coverpanel">
      <div class="phead"><b>Controls</b>
        <button id="coverpanelmin" aria-label="minimize control panel" title="minimize">–</button></div>
      <div class="row"><label>Draw</label>
        <div class="seg" id="cover-draw">
          <button data-v="bbox" class="on">Bbox</button>
          <button data-v="polygon">Polygon</button>
        </div></div>
      <div class="row"><label>Compare</label>
        <div class="seg" id="cover-compare">
          <button data-v="t3" class="on">T3 &#9650;</button>
          <button data-v="s2">T3 + S2 &#9633;</button>
        </div></div>
      <div class="row"><label>Level</label>
        <div class="coverrange">
          <input id="cover-level" type="range" min="3" max="11" value="6" step="1">
          <span class="coverlevel" id="cover-level-label">L6 ~110 km</span>
        </div></div>
      <div class="row"><label>Selection</label>
        <div class="seg" id="cover-mode">
          <button data-v="intersects" class="on">Intersects</button>
          <button data-v="centroid">Centroid</button>
        </div></div>
      <div class="row"><label>Output</label>
        <div class="seg" id="cover-output">
          <button data-v="full" class="on">Full</button>
          <button data-v="compacted">Compacted</button>
          <button data-v="ranges">Ranges</button>
        </div></div>
      <div class="row"><label>Index</label>
        <div class="seg" id="cover-format">
          <button data-v="compact" class="on">Compact</button>
          <button data-v="addr64">addr64</button>
        </div></div>
      <div class="coveractions">
        <button class="primary" id="cover-run">Run</button>
        <button id="cover-finish">Finish</button>
        <button id="cover-clear">Clear</button>
      </div>
      <div class="coverhint" id="cover-hint">Drag to draw a bbox, or switch to polygon and click vertices.</div>
      <div class="coverstats" id="cover-status">Loading coverage demo...</div>
      <pre class="coverout" id="cover-output-box">[]</pre>
      <div class="note">Coverage is conservative in intersects mode. The index list is T3; S2 is shown on the map
      and in the stats. S2 cells are real Google S2 quads (quadratic projection, Hilbert order); the cover is
      fixed-level to mirror T3's, not S2's variable-level region coverer.</div>
    </div>
  </div>
  <script>
  (function(){
    var panel=document.querySelector('.coverpanel'),btn=document.getElementById('coverpanelmin');
    function setMin(min){panel.classList.toggle('min',min);btn.textContent=min?'+':'–';
      btn.title=btn.ariaLabel=(min?'expand':'minimize')+' control panel';}
    btn.addEventListener('click',function(e){e.stopPropagation();
      setMin(!panel.classList.contains('min'));});
    panel.querySelector('.phead').addEventListener('click',function(){
      if(panel.classList.contains('min'))setMin(false);});
    if(matchMedia('(max-width:640px)').matches)setMin(true);
  })();
  </script>
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

<footer>
  Trifold T3 · MIT license · <a href="__GH__" target="_blank">github.com/jaakla/trifold</a> ·
  <a href="t3-technical-reference.md">technical reference</a> ·
  land data <a href="https://www.naturalearthdata.com/" target="_blank">Natural Earth</a> ·
  comparison layers via pya5, h3-py, s2sphere, rhealpixdggs ·
  built with MapLibre GL &amp; topojson-client
</footer>

<script type="module">
import {
  bboxCover, cellFeature, coverRanges, fromPath, parent64, polyfill, toCompact,
} from './sdk/trifold.js';
import {
  s2Cover, s2Compact, s2CellFeature, s2LevelForT3,
} from './sdk/s2mini.js';
__DATA__

const LEVEL_COLORS={0:'#3f0008',1:'#67000d',2:'#a50f15',3:'#cb181d',4:'#ef3b2c',
  5:'#fb6a4a',6:'#fc9272',7:'#fcbba1',8:'#fee0d2'};
const COASTAL='#74a9cf';

const SYS_NOTES={
 tri:'Trifold T3: icosahedral triangles, exact aperture-4 nesting. Click a cell for its '+
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
      tileSize:256,attribution:'© OpenStreetMap © CARTO · Trifold T3 demo'}},
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

const COVER_LEVEL_LABELS={3:'~880 km',4:'~440 km',5:'~220 km',6:'~110 km',
  7:'~55 km',8:'~28 km',9:'~14 km',10:'~7 km',11:'~3.4 km'};
const COVER_RENDER_LIMIT=1600;
const COVER_OUTPUT_LIMIT=260;
const COVER_RANGE_LIMIT=120;
const COVER_CELL_CAP=50000;
const coverState={
  draw:'bbox',
  level:6,
  mode:'intersects',
  output:'full',
  format:'compact',
  compare:'t3',
  bbox:[-0.55,51.25,0.25,51.75],
  previewBbox:null,
  polygon:[],
  dragging:false,
  dragStart:null,
  cells:[],
  compacted:[],
  ranges:[],
  s2Level:0,
  s2Cells:[],
  s2Compacted:[],
  s2Capped:false,
  elapsedMs:0,
};

const coverMap=new maplibregl.Map({
  container:'covermap',
  style:{version:8,
    sources:{carto:{type:'raster',
      tiles:['https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',
             'https://b.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png'],
      tileSize:256,attribution:'© OpenStreetMap © CARTO · Trifold T3 coverage demo'}},
    layers:[{id:'cover-bg',type:'background',paint:{'background-color':'#cfe3ef'}},
            {id:'cover-base',type:'raster',source:'carto'}]},
  center:[-0.12,51.5],
  zoom:7,
});
coverMap.addControl(new maplibregl.NavigationControl());
coverMap.doubleClickZoom.disable();

function coverCollection(features=[]){return {type:'FeatureCollection',features};}
function compareCoverBigInt(a,b){return a<b?-1:a>b?1:0;}
function normalizeLng(lng){
  const wrapped=((((lng+180)%360)+360)%360)-180;
  return wrapped===-180&&lng>0?180:wrapped;
}
function clampLat(lat){return Math.max(-90,Math.min(90,lat));}
function cleanCoord(coord){return [Number(normalizeLng(coord[0]).toFixed(6)),
  Number(clampLat(coord[1]).toFixed(6))];}
function bboxFromCoords(a,b){
  const lonA=normalizeLng(a[0]),lonB=normalizeLng(b[0]);
  const minLat=Math.min(clampLat(a[1]),clampLat(b[1]));
  const maxLat=Math.max(clampLat(a[1]),clampLat(b[1]));
  const west=Math.min(lonA,lonB),east=Math.max(lonA,lonB);
  return east-west>180?[east,minLat,west,maxLat]:[west,minLat,east,maxLat];
}
function bboxGeometry([minLon,minLat,maxLon,maxLat]){
  if(minLon<=maxLon)return {type:'Polygon',coordinates:[[
    [minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat],[minLon,minLat],
  ]]};
  return {type:'MultiPolygon',coordinates:[
    [[[minLon,minLat],[180,minLat],[180,maxLat],[minLon,maxLat],[minLon,minLat]]],
    [[[-180,minLat],[maxLon,minLat],[maxLon,maxLat],[-180,maxLat],[-180,minLat]]],
  ]};
}
function polygonGeometry(){
  if(coverState.polygon.length<3)return null;
  const ring=coverState.polygon.map(cleanCoord);
  ring.push([...ring[0]]);
  return {type:'Polygon',coordinates:[ring]};
}
// rough query area (km^2), only used to guard against runaway covers
function coverQueryAreaKm2(active){
  let ring;
  if(active.kind==='bbox'){
    const [w,s,e,n]=active.bbox;
    const dLon=Math.abs(e-w>180?360-Math.abs(e-w):e-w);
    const midLat=(s+n)/2;
    return Math.abs(dLon*110.57*Math.cos(midLat*Math.PI/180))*Math.abs((n-s)*110.57);
  }
  ring=active.geometry.coordinates[0];
  let area=0,latSum=0;
  for(let i=0;i<ring.length-1;i++){
    area+=ring[i][0]*ring[i+1][1]-ring[i+1][0]*ring[i][1];
    latSum+=ring[i][1];
  }
  const meanLat=latSum/Math.max(1,ring.length-1);
  const km=110.57;
  return Math.abs(area/2)*km*km*Math.cos(meanLat*Math.PI/180);
}
function renderCoverQuery(){
  const features=[];
  const bbox=coverState.previewBbox||coverState.bbox;
  if(coverState.draw==='bbox'&&bbox){
    features.push({type:'Feature',properties:{kind:'bbox'},geometry:bboxGeometry(bbox)});
  }else if(coverState.draw==='polygon'&&coverState.polygon.length){
    const geom=polygonGeometry();
    if(geom)features.push({type:'Feature',properties:{kind:'polygon'},geometry:geom});
    else if(coverState.polygon.length>1)features.push({
      type:'Feature',
      properties:{kind:'line'},
      geometry:{type:'LineString',coordinates:coverState.polygon.map(cleanCoord)},
    });
    coverState.polygon.forEach((coord,index)=>features.push({
      type:'Feature',
      properties:{kind:'vertex',index},
      geometry:{type:'Point',coordinates:cleanCoord(coord)},
    }));
  }
  const source=coverMap.getSource('cover-query');
  if(source)source.setData(coverCollection(features));
}
function compactCoverCells(cells){
  let current=[...new Set(cells.map(cell=>BigInt(cell)).map(String))]
    .map(BigInt).sort(compareCoverBigInt);
  let changed=true;
  while(changed){
    changed=false;
    const groups=new Map();
    const next=[];
    for(const cell of current){
      let parent;
      try{parent=parent64(cell);}catch(e){next.push(cell);continue;}
      const key=parent.toString();
      if(!groups.has(key))groups.set(key,{parent,children:[]});
      groups.get(key).children.push(cell);
    }
    for(const group of groups.values()){
      if(group.children.length===4){next.push(group.parent);changed=true;}
      else next.push(...group.children);
    }
    current=[...new Set(next.map(String))].map(BigInt).sort(compareCoverBigInt);
  }
  return current;
}
function visibleCoverCells(){
  if(coverState.output==='full')return coverState.cells;
  return coverState.compacted;
}
function renderCoverCells(){
  const source=coverMap.getSource('cover-cells');
  if(source){
    const cells=visibleCoverCells();
    const features=cells.slice(0,COVER_RENDER_LIMIT)
      .map(cell=>cellFeature(cell,{precision:5}));
    source.setData(coverCollection(features));
  }
  const s2source=coverMap.getSource('cover-s2-cells');
  if(s2source){
    const showS2=coverState.compare==='s2';
    const s2cells=coverState.output==='full'?coverState.s2Cells:coverState.s2Compacted;
    const features=showS2
      ? s2cells.slice(0,COVER_RENDER_LIMIT).map(cell=>s2CellFeature(cell,{precision:5}))
      : [];
    s2source.setData(coverCollection(features));
  }
}
function formatCoverCells(cells){
  return coverState.format==='compact'
    ? cells.map(cell=>toCompact(cell))
    : cells.map(cell=>cell.toString());
}
function compactSavings(full,compacted){
  return full>0?(1-compacted/full)*100:0;
}
function renderCoverOutput(){
  const box=document.getElementById('cover-output-box');
  let text='';
  if(coverState.output==='ranges'){
    const rows=coverState.ranges.slice(0,COVER_RANGE_LIMIT)
      .map(([low,high])=>[low.toString(),high.toString()]);
    text=JSON.stringify(rows,null,2);
    if(coverState.ranges.length>COVER_RANGE_LIMIT)
      text+=`\n... ${coverState.ranges.length-COVER_RANGE_LIMIT} more ranges`;
  }else{
    const cells=coverState.output==='compacted'?coverState.compacted:coverState.cells;
    const values=formatCoverCells(cells).slice(0,COVER_OUTPUT_LIMIT);
    text=JSON.stringify(values,null,2);
    if(cells.length>COVER_OUTPUT_LIMIT)
      text+=`\n... ${cells.length-COVER_OUTPUT_LIMIT} more indexes`;
  }
  box.textContent=text;
  const rendered=Math.min(visibleCoverCells().length,COVER_RENDER_LIMIT);
  const renderNote=visibleCoverCells().length>COVER_RENDER_LIMIT
    ? ` · rendered first ${rendered.toLocaleString()}`:'';
  const t3Save=compactSavings(coverState.cells.length,coverState.compacted.length);
  let html=`<b>T3 L${coverState.level}</b>: ${coverState.cells.length.toLocaleString()} cells `+
    `&rarr; ${coverState.compacted.length.toLocaleString()} compacted `+
    `(${t3Save.toFixed(0)}% saved) · ${coverState.ranges.length.toLocaleString()} ranges · `+
    `${coverState.elapsedMs.toFixed(1)} ms${renderNote}`;
  if(coverState.compare==='s2'){
    const s2Save=compactSavings(coverState.s2Cells.length,coverState.s2Compacted.length);
    const t3c=coverState.compacted.length,s2c=coverState.s2Compacted.length;
    let verdict;
    if(t3c===s2c)verdict=`tie (${t3c.toLocaleString()} each)`;
    else{
      const smaller=t3c<s2c?'T3':'S2';
      const pct=(Math.abs(s2c-t3c)/Math.max(t3c,s2c))*100;
      verdict=`<b>${smaller} ${pct.toFixed(0)}% smaller</b>`;
    }
    html+=`<br><b style="color:#1c7c4a">S2 L${coverState.s2Level}</b>: `+
      `${coverState.s2Cells.length.toLocaleString()} cells &rarr; `+
      `${s2c.toLocaleString()} compacted (${s2Save.toFixed(0)}% saved)`+
      (coverState.s2Capped?' · capped':'')+
      `<br>final compacted size: T3 ${t3c.toLocaleString()} vs S2 ${s2c.toLocaleString()} cells `+
      `&mdash; ${verdict}`;
  }
  document.getElementById('cover-status').innerHTML=html;
}
function activeCoverGeometry(){
  if(coverState.draw==='bbox'&&coverState.bbox)return {kind:'bbox',bbox:coverState.bbox};
  if(coverState.draw==='polygon'&&coverState.polygon.length>=3)
    return {kind:'polygon',geometry:polygonGeometry()};
  return null;
}
function runCoverage(){
  const active=activeCoverGeometry();
  if(!active){
    document.getElementById('cover-status').textContent='Draw a bbox or a polygon with at least 3 vertices.';
    document.getElementById('cover-output-box').textContent='[]';
    coverState.cells=[];coverState.compacted=[];coverState.ranges=[];
    coverState.s2Cells=[];coverState.s2Compacted=[];
    renderCoverCells();
    return;
  }
  const estimate=coverQueryAreaKm2(active)/(25.5e6/Math.pow(4,coverState.level));
  if(estimate>COVER_CELL_CAP){
    document.getElementById('cover-status').innerHTML=
      `Area too large for L${coverState.level} (~${Math.round(estimate).toLocaleString()} cells, `+
      `cap ${COVER_CELL_CAP.toLocaleString()}). Draw a smaller shape or lower the level.`;
    document.getElementById('cover-output-box').textContent='[]';
    coverState.cells=[];coverState.compacted=[];coverState.ranges=[];
    coverState.s2Cells=[];coverState.s2Compacted=[];
    renderCoverCells();
    return;
  }
  const started=performance.now();
  try{
    coverState.cells=active.kind==='bbox'
      ? bboxCover(...active.bbox,coverState.level,{mode:coverState.mode})
      : polyfill(active.geometry,coverState.level,{mode:coverState.mode});
    coverState.compacted=compactCoverCells(coverState.cells);
    coverState.ranges=coverRanges(coverState.compacted);
    if(coverState.compare==='s2'){
      coverState.s2Level=s2LevelForT3(coverState.level);
      const query=active.kind==='bbox'
        ? {kind:'bbox',bbox:active.bbox}
        : {kind:'polygon',geometry:active.geometry};
      const result=s2Cover(query,coverState.s2Level,{mode:coverState.mode,cap:COVER_CELL_CAP});
      coverState.s2Cells=result.cells;
      coverState.s2Capped=result.capped;
      coverState.s2Compacted=s2Compact(result.cells);
    }else{
      coverState.s2Cells=[];coverState.s2Compacted=[];coverState.s2Capped=false;
    }
    coverState.elapsedMs=performance.now()-started;
    renderCoverCells();
    renderCoverOutput();
  }catch(err){
    console.error(err);
    document.getElementById('cover-status').textContent=err.message||String(err);
    document.getElementById('cover-output-box').textContent='[]';
  }
}
function updateCoverHint(){
  const hint=coverState.draw==='bbox'
    ? 'Drag on the map to draw a bbox.'
    : 'Click polygon vertices on the map; Finish closes the current shape.';
  document.getElementById('cover-hint').textContent=hint;
  coverMap.getCanvas().style.cursor=coverState.draw==='bbox'?'crosshair':'copy';
}
function wireCoverSeg(id,prop,cb){
  const seg=document.getElementById(id);
  seg.querySelectorAll('button').forEach(button=>{button.onclick=()=>{
    seg.querySelectorAll('button').forEach(other=>other.classList.remove('on'));
    button.classList.add('on');
    coverState[prop]=button.dataset.v;
    cb();
  };});
}

coverMap.on('load',()=>{
  coverMap.addSource('cover-cells',{type:'geojson',data:coverCollection()});
  coverMap.addSource('cover-s2-cells',{type:'geojson',data:coverCollection()});
  coverMap.addSource('cover-query',{type:'geojson',data:coverCollection()});
  coverMap.addLayer({id:'cover-s2-cells-fill',type:'fill',source:'cover-s2-cells',
    paint:{'fill-color':'#1c7c4a','fill-opacity':0.18}});
  coverMap.addLayer({id:'cover-s2-cells-line',type:'line',source:'cover-s2-cells',
    paint:{'line-color':'#13643a','line-width':1,'line-opacity':0.7}});
  coverMap.addLayer({id:'cover-cells-fill',type:'fill',source:'cover-cells',
    paint:{'fill-color':'#d94e2f','fill-opacity':0.24}});
  coverMap.addLayer({id:'cover-cells-line',type:'line',source:'cover-cells',
    paint:{'line-color':'#8b2f1f','line-width':1,'line-opacity':0.78}});
  coverMap.addLayer({id:'cover-query-fill',type:'fill',source:'cover-query',
    filter:['==',['geometry-type'],'Polygon'],
    paint:{'fill-color':'#2b6f9a','fill-opacity':0.16}});
  coverMap.addLayer({id:'cover-query-line',type:'line',source:'cover-query',
    paint:{'line-color':'#12384f','line-width':2.2,'line-opacity':0.95}});
  coverMap.addLayer({id:'cover-query-point',type:'circle',source:'cover-query',
    filter:['==',['geometry-type'],'Point'],
    paint:{'circle-radius':4,'circle-color':'#12384f','circle-stroke-color':'#fff',
      'circle-stroke-width':1.5}});
  renderCoverQuery();
  updateCoverHint();
  runCoverage();
});
coverMap.on('mousedown',e=>{
  if(coverState.draw!=='bbox'||e.originalEvent.button!==0)return;
  e.preventDefault();
  coverState.dragging=true;
  coverState.dragStart=[e.lngLat.lng,e.lngLat.lat];
  coverState.previewBbox=bboxFromCoords(coverState.dragStart,coverState.dragStart);
  coverMap.dragPan.disable();
  renderCoverQuery();
});
coverMap.on('mousemove',e=>{
  if(!coverState.dragging)return;
  coverState.previewBbox=bboxFromCoords(coverState.dragStart,[e.lngLat.lng,e.lngLat.lat]);
  renderCoverQuery();
});
coverMap.on('mouseup',e=>{
  if(!coverState.dragging)return;
  coverState.dragging=false;
  coverMap.dragPan.enable();
  const bbox=bboxFromCoords(coverState.dragStart,[e.lngLat.lng,e.lngLat.lat]);
  coverState.previewBbox=null;
  coverState.bbox=bbox;
  coverState.polygon=[];
  renderCoverQuery();
  runCoverage();
});
coverMap.on('click',e=>{
  if(coverState.draw!=='polygon'||coverState.dragging)return;
  coverState.polygon.push(cleanCoord([e.lngLat.lng,e.lngLat.lat]));
  coverState.bbox=null;
  renderCoverQuery();
  if(coverState.polygon.length>=3)runCoverage();
});
coverMap.on('dblclick',e=>{
  if(coverState.draw!=='polygon')return;
  e.preventDefault();
  if(coverState.polygon.length>=3)runCoverage();
});

wireCoverSeg('cover-draw','draw',()=>{
  updateCoverHint();
  renderCoverQuery();
  if(activeCoverGeometry())runCoverage();
});
wireCoverSeg('cover-compare','compare',runCoverage);
wireCoverSeg('cover-mode','mode',runCoverage);
wireCoverSeg('cover-output','output',()=>{
  renderCoverCells();
  renderCoverOutput();
});
wireCoverSeg('cover-format','format',renderCoverOutput);
document.getElementById('cover-level').addEventListener('input',e=>{
  coverState.level=Number(e.target.value);
  document.getElementById('cover-level-label').textContent=
    `L${coverState.level} ${COVER_LEVEL_LABELS[coverState.level]}`;
});
document.getElementById('cover-level').addEventListener('change',runCoverage);
document.getElementById('cover-run').addEventListener('click',runCoverage);
document.getElementById('cover-finish').addEventListener('click',()=>{
  if(coverState.draw==='polygon'&&coverState.polygon.length>=3)runCoverage();
});
document.getElementById('cover-clear').addEventListener('click',()=>{
  coverState.bbox=null;
  coverState.previewBbox=null;
  coverState.polygon=[];
  coverState.cells=[];
  coverState.compacted=[];
  coverState.ranges=[];
  coverState.s2Cells=[];
  coverState.s2Compacted=[];
  renderCoverQuery();
  renderCoverCells();
  document.getElementById('cover-status').textContent='Draw a bbox or polygon to run coverage.';
  document.getElementById('cover-output-box').textContent='[]';
});
window.trifoldCoverageDemo={state:coverState,runCoverage};
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
<meta name="description" content="landcheck: offline land/sea point lookup built on the Trifold T3 triangular DGGS. 182 KB dataset, microsecond lookups, confidence per answer. Interactive in-browser demo.">
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
  /* benchmark bars */
  .bench .brow{display:grid;grid-template-columns:104px 1fr 82px;gap:9px;align-items:center;
    margin:7px 0;font-size:12.5px}
  .bench .bname{text-align:right;white-space:nowrap;overflow:hidden}
  .bench .btrack{min-width:0}
  .bench .bfill{height:17px;border-radius:3px;background:#b9c2cc;min-width:2px}
  .bench .bfill.tf{background:var(--warm)}
  .bench .bval{font-size:11.5px;color:var(--mut);white-space:nowrap}
  /* demo */
  #demo{max-width:none;padding:38px 0 0}
  #demo .inner{max-width:1020px;margin:0 auto;padding:0 22px}
  .viewerwrap{position:relative;height:74vh;min-height:480px;margin-top:16px;
    border-top:1px solid #ddd;border-bottom:1px solid #ddd}
  #map{position:absolute;inset:0}
  .panel{position:absolute;top:12px;left:12px;z-index:10;background:rgba(255,255,255,.96);
    padding:12px 14px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.22);
    font-size:13px;width:280px;max-height:calc(74vh - 30px);overflow:auto}
  .phead{display:flex;align-items:center;justify-content:space-between;gap:10px;
    margin:-2px 0 4px;cursor:pointer}
  .phead b{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#333}
  .phead button{border:1px solid #999;background:#fff;border-radius:6px;width:28px;height:24px;
    cursor:pointer;font-size:15px;line-height:1;padding:0;color:#333}
  .panel.min{width:auto;padding:7px 11px}
  .panel.min>:not(.phead){display:none!important}
  .panel.min .phead{margin:0}
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
      <a href="index.html">Trifold <span class="t3">T3</span></a> library</span>
  </span>
  <a href="#demo">Demo</a>
  <a href="#guide">User guide</a>
  <a href="#tech">Technical</a>
  <a href="#benchmark">Benchmark</a>
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
    so it is the real library throughput. Use the 100k-random button for a stable number.
    Switch to <b>Route</b> mode to classify a polyline — draw one on the map or pick an
    example — and see the land/coast/sea stretches it crosses, each with its distance.</p>
  </div>
  <div class="viewerwrap">
    <div id="map"></div>
    <div class="panel">
      <div class="phead"><b>Controls</b>
        <button id="panelmin" aria-label="minimize control panel" title="minimize">–</button></div>
      <div class="row"><label>Mode</label>
        <div class="seg" id="seg-mode">
          <button data-v="points" class="on">Points</button>
          <button data-v="route">Route (line)</button>
        </div>
        <div class="note">Points: classify many lon/lat points. Route: classify a
        polyline and see which land/sea stretches it crosses.</div></div>
      <div class="row" id="row-points"><label>Sample points</label>
        <div class="btns">
          <button id="b-cities">World cities + tricky spots</button>
          <button id="b-r1">1k random</button>
          <button id="b-r10">10k random</button>
          <button id="b-r100">100k random</button>
        </div></div>
      <div class="row" id="row-route" style="display:none"><label>Route (polyline)</label>
        <div class="btns">
          <button id="b-route-eu">Tallinn → Stockholm (sea crossing)</button>
          <button id="b-route-med">Barcelona → Algiers</button>
          <button id="b-route-asia">Lisbon → Cairo</button>
        </div>
        <div class="btns" style="margin-top:6px">
          <button id="b-draw">✏️ Draw on map</button>
          <button id="b-route-clear">Clear</button>
        </div>
        <div class="note" id="routenote">Pick an example, or hit <b>Draw on map</b> and
        click to drop points; click <b>Finish</b> (or the button again) to classify.</div>
        <div style="margin-top:9px;display:flex;gap:9px;align-items:center">
          <label style="margin:0">Sampling step</label>
          <div class="seg" id="seg-step">
            <button data-v="1">1 km</button>
            <button data-v="3.5" class="on">3.5 km</button>
            <button data-v="10">10 km</button>
          </div></div></div>
      <div class="row"><label>Your own points / route</label>
        <div class="btns">
          <label class="filelabel">Open CSV / GeoJSON…
            <input type="file" id="fileinput" accept=".csv,.txt,.json,.geojson" style="display:none">
          </label>
        </div>
        <div id="droperr"></div>
        <div class="note">CSV: <code>lon,lat[,name]</code> per line (or a header naming
        <code>lat</code>/<code>lon</code> columns in either order). GeoJSON: a
        FeatureCollection of Points (Points mode) or a LineString (Route mode).
        Files stay on your machine.</div></div>
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
  <script>
  (function(){
    var panel=document.querySelector('.panel'),btn=document.getElementById('panelmin');
    function setMin(min){panel.classList.toggle('min',min);btn.textContent=min?'+':'–';
      btn.title=btn.ariaLabel=(min?'expand':'minimize')+' control panel';}
    btn.addEventListener('click',function(e){e.stopPropagation();
      setMin(!panel.classList.contains('min'));});
    panel.querySelector('.phead').addEventListener('click',function(){
      if(panel.classList.contains('min'))setMin(false);});
    if(matchMedia('(max-width:640px)').matches)setMin(true);
  })();
  </script>
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
//   landFraction: 1, cell: 'TFA95BM', refined: false }

// a whole route: land/sea segments with distances
lc.checkPolyline([[24.75,59.44],[18.07,59.33]]).segments;
// [{land:true,kind:'land',...,distanceKm,fraction}, ...]</code></pre>
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
lc.is_land_batch(lons, lats)

# a whole route: land/sea segments with distances
lc.check_polyline([(24.75, 59.44), (18.07, 59.33)]).segments</code></pre>
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

<section id="benchmark">
  <h2>Benchmark: Trifold vs SQL spatial engines</h2>
  <p>Same job for every engine: classify 100,000 sphere-uniform random points against the same
  OSM simplified land polygons. Median of seven warm runs on an Apple M5 Pro laptop (June 2026);
  BigQuery ran as a managed on-demand service. In batch mode the OSM-refined Trifold was
  3&ndash;4&times; faster than BigQuery and PostGIS and ~30&times; faster than DuckDB Spatial;
  called one point at a time it answered ~86,000 lookups per second, 40&times; the embedded
  DuckDB rate.</p>
  <div class="twocol">
    <div class="bench">
      __LC_BENCH_BATCH__
    </div>
    <div class="bench">
      __LC_BENCH_SINGULAR__
    </div>
  </div>
  <div class="bench" style="margin-top:18px">
    __LC_BENCH_POLYLINE__
  </div>
  <p class="muted">The SQL engines compute exact polygon containment on the loaded OSM snapshot;
  Trifold's compact dataset agrees with that result on 99.5% of points (refined). PostGIS singular
  includes localhost TCP + Docker transport; DuckDB runs embedded in-process. The
  <b>Route (polyline)</b> row is per sampled point — a line query is one point-in-polygon per
  sample for every engine; the live Route mode above reports the same per-sample rate on your
  device. These bars are generated from the benchmark doc at build time. Full methodology,
  dataset manifest and caveats:
  <a href="__GH__/blob/main/benchmark.md" target="_blank"><code>benchmark.md</code></a>.</p>
</section>

<footer>
  landcheck · a <a href="index.html">Trifold T3</a> application · MIT license ·
  <a href="__GH__/tree/main/landcheck" target="_blank">source</a> ·
  land data <a href="https://www.naturalearthdata.com/" target="_blank">Natural Earth</a> ·
  optional refinement © <a href="https://osmdata.openstreetmap.de/data/land-polygons.html"
  target="_blank">OpenStreetMap contributors</a>
</footer>

<script type="module">
import {LandCheck,locateIndex,indexToCompact,indexToLonLatRing,samplePolyline} from './sdk/landcheck.mjs';
const TFLS_B64="__TFLS_B64__";
const TFLR_URLS=['data/coastal_osm_L10.tflr','__TFLR_URL__'];
const NE_URLS=['data/ne_50m_land.geojson','__NE_URL__'];

const KIND_COLOR={land:'#22c55e',coast:'#f59e0b',sea:'#16277e'};
const EMPTY={type:'FeatureCollection',features:[]};
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

function splitCsvLine(l){
  const out=[];let cur='',q=false;
  for(let i=0;i<l.length;i++){const ch=l[i];
    if(q){if(ch==='"'){if(l[i+1]==='"'){cur+='"';i++;}else q=false;}else cur+=ch;}
    else if(ch==='"')q=true;
    else if(ch===','||ch===';'||ch==='\\t'){out.push(cur.trim());cur='';}
    else cur+=ch;}
  out.push(cur.trim());return out;
}
function parseCsv(text){
  const lines=text.split(/\\r?\\n/).filter(l=>l.trim());
  if(!lines.length)throw new Error('empty file');
  let lonCol=0,latCol=1,nameCol=2,start=0;
  const head=splitCsvLine(lines[0].toLowerCase());
  const latIdx=head.findIndex(h=>/^(lat|latitude|y)$/.test(h));
  const lonIdx=head.findIndex(h=>/^(lon|lng|long|longitude|x)$/.test(h));
  if(latIdx>=0&&lonIdx>=0){
    lonCol=lonIdx;latCol=latIdx;start=1;
    nameCol=head.findIndex(h=>/^(name|label|id|title)$/.test(h));
  }
  const pts=[];
  for(let i=start;i<lines.length;i++){
    const c=splitCsvLine(lines[i]);
    const lon=parseFloat(c[lonCol]),lat=parseFloat(c[latCol]);
    if(!isFinite(lon)||!isFinite(lat))continue;
    if(lon<-180||lon>180||lat<-90||lat>90)continue;
    pts.push([nameCol>=0&&c[nameCol]?c[nameCol]:'',lon,lat]);
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
  map.addSource('coastzones',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'coast-zones',type:'fill',source:'coastzones',
    paint:{'fill-color':KIND_COLOR.land,'fill-opacity':0.45,'fill-antialias':false}});
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
  // route (polyline) layers: one coloured line feature per classified segment
  map.addSource('route',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-line',type:'line',source:'route',
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':['get','color'],'line-width':5,'line-opacity':0.9}});
  map.addSource('routeverts',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-verts',type:'circle',source:'routeverts',
    paint:{'circle-color':'#111','circle-radius':4.5,
      'circle-stroke-width':2,'circle-stroke-color':'#fff'}});
  map.on('click',e=>{
    let lon=e.lngLat.lng,lat=e.lngLat.lat;
    lon=((lon+180)%360+360)%360-180;
    lat=Math.max(-90,Math.min(90,lat));
    // route draw mode: each click drops a vertex
    if(mode==='route'&&drawing){addVertex(lon,lat);return;}
    // route segment click: show the segment's classification
    const seg=map.queryRenderedFeatures(e.point,{layers:['route-line']});
    if(mode==='route'&&seg.length){
      const p=seg[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
        `<b style="color:${p.color}">${p.land==='true'||p.land===true?'LAND':'SEA'}</b>`+
        ` · kind <b>${p.kind}</b><br>${(+p.distanceKm).toFixed(1)} km `+
        `(${(100*p.fraction).toFixed(1)}% of route)`).addTo(map);
      return;
    }
    // clicks on a classified point are handled by the 'pts' handler below
    if(map.queryRenderedFeatures(e.point,{layers:['pts']}).length)return;
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
    if(entry===0)continue;  // all-sea: nothing to fill (all-land 1 fills its triangle)
    const ring=indexToLonLatRing(index,lc.level);
    const lons=ring.map(p=>p[0]),lats=ring.map(p=>p[1]);
    cellBoxes.push([index,Math.min(...lons),Math.min(...lats),
                    Math.max(...lons),Math.max(...lats)]);
  }
}
// even-odd ray cast in the cell-local quantized grid (flat [x0,y0,x1,y1,...])
function pointInRingQ(px,py,pts){
  const n=pts.length/2;let inside=false;
  for(let i=0,j=n-1;i<n;j=i++){
    const xi=pts[2*i],yi=pts[2*i+1],xj=pts[2*j],yj=pts[2*j+1];
    if(((yi>py)!==(yj>py))&&(px<(xj-xi)*(py-yi)/((yj-yi)||1e-9)+xi))inside=!inside;
  }
  return inside;
}
function osmCoastZones(){
  if(!cellBoxes)buildCellBoxes();
  const b=map.getBounds();
  const w=b.getWest(),e=b.getEast(),s=b.getSouth(),n=b.getNorth();
  const feats=[];let nverts=0;
  for(const [index,minx,miny,maxx,maxy] of cellBoxes){
    if(maxy<s||miny>n)continue;
    let hit=false;
    for(const off of [-360,0,360]){if(maxx+off>=w&&minx+off<=e){hit=true;break;}}
    if(!hit)continue;
    const sx=(maxx-minx)/65535,sy=(maxy-miny)/65535;
    const entry=refineCells.get(index);
    if(typeof entry==='number'){   // 1 = whole cell is land: fill the triangle
      if(entry===1){
        const tri=indexToLonLatRing(index,lc.level).map(p=>[p[0],p[1]]);
        tri.push(tri[0]);
        feats.push({type:'Feature',properties:{},
          geometry:{type:'Polygon',coordinates:[tri]}});
        nverts+=3;
      }
      if(nverts>120000)return null;
      continue;
    }
    // fill the land part of this coastal cell. The dataset's rings are even-odd
    // (inside = land), so sort by area and nest a ring inside a larger one as a
    // hole (a lake/inlet); disjoint rings become separate polygons. Triangle-edge
    // segments need no filtering here — they are interior to the fill.
    const decoded=entry.map(pts=>{
      const m=pts.length/2,ll=new Array(m+1);
      let a=0;
      for(let i=0;i<m;i++){
        ll[i]=[minx+pts[2*i]*sx,miny+pts[2*i+1]*sy];
        const j=(i+1)%m;a+=pts[2*i]*pts[2*j+1]-pts[2*j]*pts[2*i+1];
      }
      ll[m]=ll[0];
      nverts+=m;
      return {ll,area:Math.abs(a)/2,q:pts};
    }).sort((p,q)=>q.area-p.area);
    const polys=[];
    for(const d of decoded){
      let host=null;
      for(const P of polys)if(pointInRingQ(d.q[0],d.q[1],P.q)){host=P;break;}
      if(host)host.coords.push(d.ll);
      else polys.push({coords:[d.ll],q:d.q});
    }
    for(const P of polys)feats.push({type:'Feature',properties:{},
      geometry:{type:'Polygon',coordinates:P.coords}});
    if(nverts>120000)return null;  // too much detail for this view
  }
  return feats;
}
async function updateCoastline(){
  if(!coastcb.checked){
    map.getSource('coast').setData({type:'FeatureCollection',features:[]});
    map.getSource('coastzones').setData({type:'FeatureCollection',features:[]});
    return;
  }
  if(coastMode()==='ne'){
    coastsrc.textContent='NE';
    map.getSource('coastzones').setData({type:'FeatureCollection',features:[]});
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
    map.getSource('coast').setData({type:'FeatureCollection',features:[]});
    const feats=osmCoastZones();
    if(feats===null){
      map.getSource('coastzones').setData({type:'FeatureCollection',features:[]});
      coastnote.textContent='OSM refinement geometry: zoom in further to draw it.';
      return;
    }
    map.getSource('coastzones').setData({type:'FeatureCollection',features:feats});
    coastnote.textContent=`Green fill: ${feats.length.toLocaleString()} OSM land zone(s) `+
      `in view — the clipped land area of each coastal cell, exactly the geometry `+
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
function parseGeojsonLine(text){
  const gj=JSON.parse(text);
  const feats=gj.type==='FeatureCollection'?gj.features:gj.type==='Feature'?[gj]:[gj];
  for(const f of feats){
    const g=f.geometry||f;
    if(g.type==='LineString')return g.coordinates.map(c=>[c[0],c[1]]);
    if(g.type==='MultiLineString')return g.coordinates[0].map(c=>[c[0],c[1]]);
  }
  throw new Error('no LineString found');
}
document.getElementById('fileinput').onchange=async e=>{
  const file=e.target.files[0];
  if(!file)return;
  document.getElementById('droperr').textContent='';
  try{
    const text=await file.text();
    const isJson=text.trimStart().startsWith('{');
    if(mode==='route'){
      const coords=isJson?parseGeojsonLine(text)
        :parseCsv(text).map(p=>[p[1],p[2]]);
      if(coords.length<2)throw new Error('need at least two vertices');
      if(coords.length>100000)throw new Error('too many vertices (max 100k)');
      loadRoute(coords);
    }else{
      const pts=isJson?parseGeojson(text):parseCsv(text);
      if(pts.length>500000)throw new Error('too many points (max 500k)');
      show(pts,file.name);
    }
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

// ---- Route (polyline) mode ----
let mode='points',drawing=false,routePts=[];
const perf=document.getElementById('perf');
const routenote=document.getElementById('routenote');
const bDraw=document.getElementById('b-draw');
const ROUTES={
  eu:[[24.7536,59.4370],[18.0686,59.3293]],          // Tallinn -> Stockholm, over the Baltic
  med:[[2.1734,41.3851],[3.0588,36.7538]],            // Barcelona -> Algiers, over the Med
  long:[[-9.1393,38.7223],[2.3522,48.8566],[31.2357,30.0444]]};  // Lisbon -> Paris -> Cairo
function stepKm(){return parseFloat(document.querySelector('#seg-step .on').dataset.v);}

function classifyRoute(){
  const coords=routePts.slice();
  if(coords.length<2){routenote.textContent='Add at least two points.';return;}
  const step=stepKm();
  const t0=performance.now();
  const res=lc.checkPolyline(coords,{stepKm:step});   // the real library call, timed
  const ms=performance.now()-t0;
  // colour the line: re-sample and group consecutive samples sharing land+kind.
  // segments join at the midpoint between samples (no gaps); stats come from
  // res.segments, whose order matches this grouping one-to-one.
  const {samples}=samplePolyline(coords,step,'uniform');
  const cls=samples.map(s=>lc.check(s[0],s[1]));
  const mid=(p,q)=>[(p[0]+q[0])/2,(p[1]+q[1])/2];
  const feats=[];let i=0,k=0;
  while(i<samples.length){
    const a=cls[i];let j=i;
    while(j+1<samples.length&&cls[j+1].land===a.land)j++;
    const line=samples.slice(i,j+1);
    if(i>0)line.unshift(mid(samples[i-1],samples[i]));
    if(j<samples.length-1)line.push(mid(samples[j],samples[j+1]));
    const seg=res.segments[k++]||{};
    feats.push({type:'Feature',
      properties:{color:KIND_COLOR[a.kind],kind:a.kind,land:a.land,
        distanceKm:seg.distanceKm,fraction:seg.fraction},
      geometry:{type:'LineString',coordinates:line}});
    i=j+1;
  }
  map.getSource('route').setData({type:'FeatureCollection',features:feats});
  map.getSource('routeverts').setData({type:'FeatureCollection',
    features:coords.map(c=>({type:'Feature',properties:{},
      geometry:{type:'Point',coordinates:c}}))});
  map.getSource('points').setData(EMPTY);
  const rate=samples.length/(ms/1000);
  const refineOn=document.getElementById('refinecb').checked;
  let rows='';
  for(const s of res.segments)
    rows+=`<span style="color:${KIND_COLOR[s.kind]}">■</span> `+
      `<b>${s.kind}</b> · ${s.distanceKm.toFixed(0)} km (${(100*s.fraction).toFixed(0)}%)<br>`;
  perf.style.display='block';
  perf.innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> samples/second on this device<br>`+
    `${samples.length.toLocaleString()} samples · `+
    `${res.totalDistanceKm.toFixed(0)} km total · `+
    `${res.segments.length} segment${res.segments.length===1?'':'s'} (step ${step} km)`+
    `${refineOn?' · <b>OSM refinement on</b>':''}<br>`+rows;
  routenote.textContent=`${coords.length} vertices · classified in ${ms.toFixed(1)} ms.`;
}
function addVertex(lon,lat){
  routePts.push([lon,lat]);
  map.getSource('routeverts').setData({type:'FeatureCollection',
    features:routePts.map(c=>({type:'Feature',properties:{},
      geometry:{type:'Point',coordinates:c}}))});
  if(routePts.length>=2)
    map.getSource('route').setData({type:'FeatureCollection',
      features:[{type:'Feature',properties:{color:'#888',kind:'',land:false},
        geometry:{type:'LineString',coordinates:routePts.slice()}}]});
  routenote.textContent=`${routePts.length} point(s) — click to add more, Finish to classify.`;
}
function startDraw(){
  drawing=true;routePts=[];
  map.getSource('route').setData(EMPTY);map.getSource('routeverts').setData(EMPTY);
  perf.style.display='none';bDraw.textContent='✓ Finish';bDraw.classList.add('on');
  map.getCanvas().style.cursor='crosshair';
  routenote.textContent='Click the map to drop route points; click Finish to classify.';
}
function endDraw(){
  drawing=false;bDraw.textContent='✏️ Draw on map';bDraw.classList.remove('on');
  map.getCanvas().style.cursor='';
}
bDraw.onclick=()=>{
  if(drawing){endDraw();if(routePts.length>=2)classifyRoute();
    else routenote.textContent='Need at least two points — pick an example or draw again.';}
  else startDraw();
};
document.getElementById('b-route-clear').onclick=()=>{
  endDraw();routePts=[];map.getSource('route').setData(EMPTY);
  map.getSource('routeverts').setData(EMPTY);perf.style.display='none';
  routenote.textContent='Pick an example, or hit Draw on map.';
};
function loadRoute(coords){
  endDraw();routePts=coords.map(c=>c.slice());classifyRoute();
  const b=new maplibregl.LngLatBounds();for(const c of routePts)b.extend(c);
  map.fitBounds(b,{padding:90,duration:600});
}
document.getElementById('b-route-eu').onclick=()=>loadRoute(ROUTES.eu);
document.getElementById('b-route-med').onclick=()=>loadRoute(ROUTES.med);
document.getElementById('b-route-asia').onclick=()=>loadRoute(ROUTES.long);
document.querySelectorAll('#seg-step button').forEach(b=>{b.onclick=()=>{
  document.querySelectorAll('#seg-step button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  if(mode==='route'&&routePts.length>=2)classifyRoute();
};});
function setMode(m){
  mode=m;
  document.querySelectorAll('#seg-mode button').forEach(x=>x.classList.toggle('on',x.dataset.v===m));
  document.getElementById('row-points').style.display=m==='points'?'':'none';
  document.getElementById('row-route').style.display=m==='route'?'':'none';
  perf.style.display='none';
  if(m==='points'){
    endDraw();routePts=[];
    map.getSource('route').setData(EMPTY);map.getSource('routeverts').setData(EMPTY);
    if(lastPts)show(lastPts,lastLabel);
  }else{
    map.getSource('points').setData(EMPTY);map.getSource('cell').setData(EMPTY);
    routenote.textContent='Pick an example, or hit Draw on map.';
  }
}
document.querySelectorAll('#seg-mode button').forEach(b=>{b.onclick=()=>setMode(b.dataset.v);});

window.__landcheck={map,lc};   // console/debug handle
</script>
</body>
</html>
"""

countrycheck_html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>countrycheck: offline country lookup (a Trifold library)</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="countrycheck: offline 'which country is this point in?' lookup built on the Trifold T3 triangular DGGS. 323 KB dataset, microsecond lookups, confidence per answer, coastal waters included. Interactive in-browser demo.">
<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<link href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css" rel="stylesheet">
<style>
  :root{--ink:#1c2733;--mut:#5b6b7b;--acc:#2b6f9a;--warm:#d94e2f;--bg:#fbfaf7;--card:#fff;
    --country:#6d4ca8;--border:#d97706;--none:#8a93a0}
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
  nav .brand .glob{color:var(--country)}
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
  .hero p.lede{font-size:clamp(15px,2.1vw,18px);color:var(--mut);max-width:790px;margin:0 auto 22px}
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
  /* benchmark bars */
  .bench .brow{display:grid;grid-template-columns:118px 1fr 92px;gap:9px;align-items:center;
    margin:7px 0;font-size:12.5px}
  .bench .bname{text-align:right;white-space:nowrap;overflow:hidden}
  .bench .btrack{min-width:0}
  .bench .bfill{height:17px;border-radius:3px;background:#b9c2cc;min-width:2px}
  .bench .bfill.tf{background:var(--warm)}
  .bench .bval{font-size:11.5px;color:var(--mut);white-space:nowrap}
  /* demo */
  #demo{max-width:none;padding:38px 0 0}
  #demo .inner{max-width:1020px;margin:0 auto;padding:0 22px}
  .viewerwrap{position:relative;height:74vh;min-height:480px;margin-top:16px;
    border-top:1px solid #ddd;border-bottom:1px solid #ddd}
  #map{position:absolute;inset:0}
  .panel{position:absolute;top:12px;left:12px;z-index:10;background:rgba(255,255,255,.96);
    padding:12px 14px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.22);
    font-size:13px;width:280px;max-height:calc(74vh - 30px);overflow:auto}
  .phead{display:flex;align-items:center;justify-content:space-between;gap:10px;
    margin:-2px 0 4px;cursor:pointer}
  .phead b{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#333}
  .phead button{border:1px solid #999;background:#fff;border-radius:6px;width:28px;height:24px;
    cursor:pointer;font-size:15px;line-height:1;padding:0;color:#333}
  .panel.min{width:auto;padding:7px 11px}
  .panel.min>:not(.phead){display:none!important}
  .panel.min .phead{margin:0}
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
  #perf{background:#f5f3fa;border:1px solid #ddd5ec;border-radius:8px;padding:9px 11px;
    margin-top:9px;font-size:12.5px;line-height:1.6;display:none}
  #perf b{font-size:15px}
  .legend{margin-top:8px;font-size:12px;line-height:1.8}
  .legend i{display:inline-block;width:11px;height:11px;border-radius:50%;
    vertical-align:middle;margin-right:5px;border:1px solid rgba(0,0,0,.35)}
  .swatch{display:inline-block;width:30px;height:11px;border-radius:3px;vertical-align:middle;
    margin-right:5px;background:linear-gradient(90deg,#d33,#dd3,#3d6,#39d,#83d)}
  .note{font-size:11px;color:#777;margin-top:7px;line-height:1.45}
  #droperr{color:#a23b1e;font-size:12px;margin-top:5px}
  footer{border-top:1px solid #e4e0d6;margin-top:46px;padding:24px 22px;text-align:center;
    color:var(--mut);font-size:13px}
  footer a{color:var(--acc)}
</style>
</head>
<body>

<nav>
  <span class="brand"><span class="glob">&#9673;</span> countrycheck
    <span class="sub">offline country lookup, a
      <a href="index.html">Trifold <span class="t3">T3</span></a> library</span>
  </span>
  <a href="#demo">Demo</a>
  <a href="#guide">User guide</a>
  <a href="#tech">Technical</a>
  <a href="#accuracy">Accuracy</a>
  <a href="#benchmark">Benchmark</a>
  <a href="landcheck.html">landcheck</a>
  <a href="index.html">&larr; Trifold home</a>
  <a class="gh" href="__GH__/tree/main/countrycheck" target="_blank" aria-label="Source on GitHub" title="Source on GitHub">__GHICON__</a>
</nav>

<section class="hero">
  <h1>countrycheck: which <span style="color:var(--country)">country</span> is this point in?</h1>
  <p class="lede">An offline lookup library built on the Trifold grid. The level-10 grid
  (~7&nbsp;km cells) classified against country polygons with accurate OSM-derived borders &mdash;
  extended with coastal waters and including X-coded territories like Kosovo and the Caspian Sea
  &mdash; collapses into a <b>323&nbsp;KB</b> dataset that names the country anywhere on Earth in
  microseconds, with a confidence value for every answer. Python and JavaScript give identical
  results. <b>This page runs the real JS library in your browser</b>; the dataset is embedded
  right in this HTML file.</p>
  <a class="cta" href="#demo" style="display:inline-block;padding:11px 22px;border-radius:8px;
    background:var(--warm);color:#fff;text-decoration:none;font-weight:600">Try it on the map</a>
</section>

<section id="demo">
  <div class="inner">
    <h2>Interactive demo</h2>
    <p>Load sample points or your own file (CSV <code>lon,lat</code> or GeoJSON points), and
    every point is resolved to a country <b>in your browser</b> by the bundled library, with no
    server and no network call per lookup. Each dot is coloured by the country it lands in; open
    ocean stays grey. The lookups-per-second figure is measured tightly around the classification
    loop on <i>your</i> machine (map rendering and file parsing excluded), so it is the real
    library throughput. Use the 100k-random button for a stable number.
    Switch to <b>Route</b> mode to classify a polyline — draw one on the map or pick an
    example — and see the countries it crosses in order, each with its distance.</p>
  </div>
  <div class="viewerwrap">
    <div id="map"></div>
    <div class="panel">
      <div class="phead"><b>Controls</b>
        <button id="panelmin" aria-label="minimize control panel" title="minimize">&ndash;</button></div>
      <div class="row"><label>Mode</label>
        <div class="seg" id="seg-mode">
          <button data-v="points" class="on">Points</button>
          <button data-v="route">Route (line)</button>
        </div>
        <div class="note">Points: resolve many lon/lat points to a country. Route:
        classify a polyline and see which countries it crosses, in order.</div></div>
      <div class="row" id="row-points"><label>Sample points</label>
        <div class="btns">
          <button id="b-cities">Capitals + tricky spots</button>
          <button id="b-r1">1k random</button>
          <button id="b-r10">10k random</button>
          <button id="b-r100">100k random</button>
        </div></div>
      <div class="row" id="row-route" style="display:none"><label>Route (polyline)</label>
        <div class="btns">
          <button id="b-route-eu">Berlin → Warsaw → Vilnius</button>
          <button id="b-route-med">Madrid → Rome</button>
          <button id="b-route-asia">Istanbul → Tehran → Delhi</button>
        </div>
        <div class="btns" style="margin-top:6px">
          <button id="b-draw">✏️ Draw on map</button>
          <button id="b-route-clear">Clear</button>
        </div>
        <div class="note" id="routenote">Pick an example, or hit <b>Draw on map</b> and
        click to drop points; click <b>Finish</b> (or the button again) to classify.</div>
        <div style="margin-top:9px;display:flex;gap:9px;align-items:center">
          <label style="margin:0">Sampling step</label>
          <div class="seg" id="seg-step">
            <button data-v="1">1 km</button>
            <button data-v="3.5" class="on">3.5 km</button>
            <button data-v="10">10 km</button>
          </div></div></div>
      <div class="row"><label>Your own points / route</label>
        <div class="btns">
          <label class="filelabel">Open CSV / GeoJSON&hellip;
            <input type="file" id="fileinput" accept=".csv,.txt,.json,.geojson" style="display:none">
          </label>
        </div>
        <div id="droperr"></div>
        <div class="note">CSV: <code>lon,lat[,name]</code> per line (or a header naming
        <code>lat</code>/<code>lon</code> columns in either order). GeoJSON: a
        FeatureCollection of Points (Points mode) or a LineString (Route mode).
        Files stay on your machine.</div></div>
      <div class="row"><label>Exact border refinement</label>
        <label style="display:flex;gap:7px;align-items:flex-start;cursor:pointer;font-size:12.5px;
            font-weight:400;text-transform:none;letter-spacing:0;color:var(--ink)">
          <input type="checkbox" id="refinecb" style="margin-top:2px">
          <span>exact polygon test wherever a border crosses a cell
            (downloads ~19&nbsp;MB once)</span></label>
        <div class="note" id="refinenote">Off: border cells use the bundled best-call
        with its area share as confidence. On: exact country/country and coastline
        borders. Watch how the counts, confidence and lookup rate change.</div></div>
      <div class="row"><label>Debug layers</label>
        <label style="display:flex;gap:7px;align-items:flex-start;cursor:pointer;font-size:12.5px;
            font-weight:400;text-transform:none;letter-spacing:0;color:var(--ink)">
          <input type="checkbox" id="bordercb" style="margin-top:2px">
          <span>source border polygons (needs the refinement layer)</span></label>
        <div class="note" id="bordernote">Click anywhere on the map to see the
        level-10 triangle and its country answer.</div></div>
      <div class="row"><label>Projection</label>
        <div class="seg" id="seg-proj">
          <button data-v="globe" class="on">Globe</button>
          <button data-v="mercator">Flat</button>
        </div></div>
      <div id="perf"></div>
      <div class="legend">
        <span class="swatch"></span>one hue per country (256 total)<br>
        <i style="background:#8a93a0"></i>no country: open ocean (confidence 1.0)<br>
        <i style="background:#fff;border:2px solid #1c2733"></i>border cell (mixed)<br>
        <i style="background:#fff;border:2px solid #c2185b"></i>answer changed by refinement
      </div>
      <div class="note" id="loadnote">Loading dataset&hellip;</div>
    </div>
  </div>
  <script>
  (function(){
    var panel=document.querySelector('.panel'),btn=document.getElementById('panelmin');
    function setMin(min){panel.classList.toggle('min',min);btn.textContent=min?'+':'\\u2013';
      btn.title=btn.ariaLabel=(min?'expand':'minimize')+' control panel';}
    btn.addEventListener('click',function(e){e.stopPropagation();
      setMin(!panel.classList.contains('min'));});
    panel.querySelector('.phead').addEventListener('click',function(){
      if(panel.classList.contains('min'))setMin(false);});
    if(matchMedia('(max-width:640px)').matches)setMin(true);
  })();
  </script>
  <div class="inner">
    <p class="muted" style="margin-top:10px">Click any classified point for its full answer:
    country code (GADM <code>gid_0</code>), ISO&nbsp;2, name, kind, confidence, area share and
    cell address (computed on the fly for open-ocean points, whose cells are not stored).
    Switching on <b>exact border refinement</b> makes the source polygons authoritative in every
    cell a border crosses. Caveats inherited from the source data: coastal waters are an
    approximate distance-based assignment, not legal EEZ; disputed territories follow GADM
    (Crimea, Western Sahara&hellip;); lakes belong to their surrounding country, except the
    Caspian Sea, which is its own <code>XCA</code> entry.</p>
  </div>
</section>

<section id="guide">
  <h2>User guide</h2>
  <div class="twocol">
    <div>
      <h3>JavaScript (browser or Node)</h3>
      <pre><code>import { CountryCheck } from "./countrycheck.mjs";

// Node: bundled file &middot; browser: fetch the 323 KB dataset
const cc = await CountryCheck.fromFile();                  // Node
const cc = await CountryCheck.fromUrl("countries_L10.tfcs"); // browser

cc.country(24.7536, 59.437);   // 'EST'  (lon, lat)
cc.check(-0.1276, 51.5072);
// { country: 'GBR', iso2: 'GB', name: 'United Kingdom',
//   kind: 'country', confidence: 1, share: 1,
//   cell: 'TFA95BM', refined: false }

// a whole route: countries crossed, in order
cc.checkPolyline([[13.4,52.5],[21.0,52.2],[25.3,54.7]]).segments;
// [{country:'DEU',...,distanceKm,fraction}, ...]</code></pre>
    </div>
    <div>
      <h3>Python (stdlib only)</h3>
      <pre><code>from countrycheck import CountryCheck

cc = CountryCheck()                    # bundled data
cc.country(24.7536, 59.4370)           # 'EST'
cc.check(-0.1276, 51.5072)
# CountryResult(country='GBR', iso2='GB',
#   name='United Kingdom', kind='country',
#   confidence=1.0, share=1.0, cell='TFA95BM',
#   refined=False)

# a whole route: countries crossed, in order
cc.check_polyline(
  [(13.4, 52.5), (21.0, 52.2), (25.3, 54.7)]).segments</code></pre>
    </div>
  </div>
  <h3>What the answer means</h3>
  <table>
    <tr><th>kind</th><th>meaning</th><th><code>country</code></th><th><code>confidence</code></th></tr>
    <tr><td><b>country</b></td><td>cell wholly inside one country</td><td>that country</td><td>1.0</td></tr>
    <tr><td><b>none</b></td><td>cell absent from the dataset (international waters)</td>
      <td>null</td><td>1.0</td></tr>
    <tr><td><b>border</b></td><td>mixed cell; bundled best call decides (may be none)</td>
      <td>best call</td><td>area share</td></tr>
    <tr><td><b>border</b> + refined</td><td>decided by the exact source polygon</td>
      <td>exact</td><td>0.99</td></tr>
  </table>
  <p class="muted">Measured accuracy: 99.82% agreement with exact polygon containment on
  30,000 uniform random points. The <code>country</code> and <code>none</code> answers were 100%
  correct; all residual error lives in <code>border</code> answers, which self-report lower
  confidence. With the border refinement loaded, agreement reaches <b>100.0%</b> on the same
  sample.</p>
  <h3>Command line</h3>
  <pre><code>$ python countrycheck/python/countrycheck.py 24.7536 59.4370
EST  iso2=EE  name='Estonia'  kind=country  confidence=1.000  share=1.0  cell=TFAVKGR  refined=False</code></pre>
  <p class="muted">The CLI loads the border refinement automatically when
  <code>borders_L10.tfcr</code> is present. Install with <code>pip install countrycheck</code> or
  <code>npm install countrycheck</code>, or run straight from a repo checkout.</p>
</section>

<section id="tech">
  <h2>Technical info</h2>
  <div class="cards">
    <div class="card"><b>Canonical index</b><p>Any Trifold cell at level &le; 10 maps to a
      contiguous range in the level-10 index space (<code>face&middot;4<sup>10</sup> + path</code>):
      a level-l cell covers exactly 4<sup>10&minus;l</sup> consecutive indices. The whole country
      classification becomes run-length intervals.</p></div>
    <div class="card"><b>TFCS format &middot; 323 KB</b><p>222,403 runs as
      <code>varint(gap), varint(len&middot;2|border)</code> &mdash; interior runs carry a country id,
      border runs a best call plus a 4-bit area share &mdash; over a country table of 256
      code/iso2/name strings, all zlib-compressed. Level-agnostic.</p></div>
    <div class="card"><b>Lookup path</b><p>Pure-float point location (no dependencies,
      bit-identical to the SDK) descends 10 subdivision levels, then one binary search over the
      run starts. ~0.6 µs in Node, ~13 µs in pure Python, ~3 µs batched with numpy.</p></div>
    <div class="card"><b>Border refinement &middot; TFCR</b><p>Source country polygons clipped to
      every border cell, quantized to a cell-local 16-bit grid (~0.1 m), one zone per country
      present with zigzag-varint rings and the even-odd rule. A point-in-polygon test then decides
      the exact country (or none) in those cells.</p></div>
  </div>
  <p style="margin-top:14px">The borders come from the timezone-boundary-builder &ldquo;with oceans&rdquo;
  polygons (OSM-derived, already reaching into territorial water); GADM level-0 supplies only the
  country identity and ISO codes, joined by max land overlap. 256 countries and territories, 6.90M
  level-10 cells belonging to some country, of which 195,473 are border cells. Full documentation,
  the one-pass <code>build.py</code>, the PostGIS source build (<code>sql/build_countries_coastal.sql</code>)
  and the cross-language test suite live in
  <a href="__GH__/tree/main/countrycheck" target="_blank"><code>countrycheck/</code> on GitHub</a>.
  Roadmap: an L12 (~1.8&nbsp;km) variant and timezone detection from the same source data.</p>
</section>

<section id="accuracy">
  <h2>Accuracy: tested on 57,501 real airports</h2>
  <p>Ground truth is the <a href="https://ourairports.com/" target="_blank">OurAirports</a> dump
  &mdash; 57,501 points, each tagged with an ISO country code from an unrelated source.
  countrycheck places <b>99.50%</b> of them in the correct country from the bundled 323&nbsp;KB
  data, and <b>99.68%</b> with the border refinement loaded. Interior-country answers are 99.91%
  correct; the refinement works only on the 729 airports that fall in a <i>border cell</i>, and
  there it lifts agreement from 80.66% to <b>95.20%</b> &mdash; the payoff of the accurate
  OSM-derived borders.</p>
  <div class="cards">
    <div class="card"><b>99.50% &rarr; 99.68%</b><p>overall agreement with airport country codes,
      bundled vs. border-refined. The residual is mostly disputed/border territory the sources map
      differently, dependencies coded to a parent state, and offshore or placeholder
      coordinates.</p></div>
    <div class="card"><b>99.995% refined</b><p>against exact SQL point-in-polygon containment over
      the same source polygons (100,000 random points): the refinement resolved all but 5 of the
      168 base-mode border disagreements (those 5 are coastal-overlap tie-breaks). Base mode: 99.83%.</p></div>
  </div>
  <p class="muted">Reproduce with <code>scripts/accuracy_countrycheck_airports.py</code> (airports)
  and <code>scripts/benchmark_countrycheck.py</code> (vs. SQL containment).</p>
</section>

<section id="benchmark">
  <h2>Benchmark: 7&ndash;97&times; faster than SQL spatial engines</h2>
  <p>One workload, four engines: assign a country (<code>gid_0</code>) to 100,000 sphere-uniform
  random points against the same country polygons. Median of seven warm runs, Apple M5 Pro,
  June 2026. The refined Trifold answers reproduce exact polygon containment to 99.995% (see above)
  while running an order of magnitude faster &mdash; ~7&times; PostGIS, ~97&times; DuckDB Spatial.
  Called one point at a time, the gap holds.</p>
  <div class="twocol">
    <div class="bench">
      __CC_BENCH_BATCH__
    </div>
    <div class="bench">
      __CC_BENCH_SINGULAR__
    </div>
  </div>
  <div class="bench" style="margin-top:18px">
    __CC_BENCH_POLYLINE__
  </div>
  <p class="muted" style="margin-top:12px">DuckDB and PostGIS compute exact containment
  and returned byte-identical answers; BigQuery is documented but was not run in this pass. PostGIS
  singular includes localhost TCP + Docker transport; DuckDB runs embedded in-process. The
  <b>Route (polyline)</b> row is per sampled point — a line query is one point-in-polygon per
  sample for every engine; the live figure in the demo panel is the same per-sample throughput
  measured on your own device. These bars are generated from the benchmark doc at build time.
  Full methodology, dataset manifest, the airport test and the BigQuery procedure:
  <a href="__GH__/blob/main/countrycheck_benchmark.md" target="_blank"><code>countrycheck_benchmark.md</code></a>.</p>
</section>

<footer>
  countrycheck &middot; a <a href="index.html">Trifold T3</a> library &middot; MIT license &middot;
  <a href="__GH__/tree/main/countrycheck" target="_blank">source</a> &middot;
  borders from the OSM-based <a href="https://github.com/evansiroky/timezone-boundary-builder"
  target="_blank">timezone-boundary-builder</a>, identity from
  <a href="https://gadm.org/" target="_blank">GADM</a>
</footer>

<script type="module">
import {CountryCheck,locateIndex,indexToCompact,indexToLonLatRing,samplePolyline} from './sdk/countrycheck.mjs';
const TFCS_B64="__TFCS_B64__";
const TFCR_URLS=['data/borders_L10.tfcr','__TFCR_URL__'];

const NONE_COLOR='#8a93a0';
const EMPTY={type:'FeatureCollection',features:[]};
// deterministic, well-spread hue per country id (golden-angle)
function countryColor(cid){
  if(cid==null||cid<0)return NONE_COLOR;
  const h=(cid*137.508)%360;
  const s=cid%2?52:64, l=cid%3?46:56;
  return `hsl(${h.toFixed(1)},${s}%,${l}%)`;
}
const CITIES=[
 ['Tallinn',24.7536,59.4370],['Helsinki',24.9384,60.1699],
 ['St Petersburg',30.3141,59.9386],['London',-0.1276,51.5072],['Paris',2.3522,48.8566],
 ['Vatican City',12.4534,41.9029],['San Marino',12.4578,43.9424],['Berlin',13.405,52.52],
 ['Kaliningrad (RU exclave)',20.5,54.71],['Singapore',103.8198,1.3521],
 ['Johor Bahru (MY)',103.76,1.49],['Hong Kong',114.17,22.32],['Tokyo',139.6917,35.6895],
 ['New York',-74.006,40.7128],['Point Roberts (US exclave)',-123.06,48.98],
 ['Mexico City',-99.1332,19.4326],['Brasília',-47.9292,-15.7801],
 ['Cape Town',18.4241,-33.9249],['Maseru (Lesotho)',27.4869,-29.3142],
 ['Cairo',31.2357,30.0444],['Jerusalem',35.2137,31.7683],['Istanbul',28.9784,41.0082],
 ['Nicosia (CY)',33.3623,35.1656],['N. Nicosia (XNC)',33.3623,35.1923],
 ['Pristina (Kosovo XKO)',21.1655,42.6629],['Caspian Sea (XCA)',51.0,42.0],
 ['Western Sahara',-13.0,24.5],['Simferopol (Crimea)',34.1,44.95],
 ['Gibraltar',-5.3536,36.1408],['Reykjavík',-21.9426,64.1466],['Sydney',151.2093,-33.8688],
 ['Gulf of Finland (EST coastal water)',24.75,59.50],
 ['Mid-Atlantic (ocean)',-30,30],['South Pacific (ocean)',-150,-30],
 ['North Pole (ocean)',0,89.5]];

// dataset: embedded base64 -> bytes -> CountryCheck
const t0=performance.now();
const bytes=Uint8Array.from(atob(TFCS_B64),c=>c.charCodeAt(0));
const cc=await CountryCheck.fromBytes(bytes);
const loadMs=performance.now()-t0;
const codeToCid=new Map(cc.countries.map((c,i)=>[c.code,i]));
document.getElementById('loadnote').textContent=
  `Dataset: ${(bytes.length/1024).toFixed(0)} KB embedded in this page · `+
  `decoded + indexed in ${loadMs.toFixed(0)} ms · level ${cc.level} · `+
  `${cc.countries.length} countries · ${cc.stats.runs.toLocaleString()} runs`;

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
  for(let i=0;i<pts.length;i++)results[i]=cc.check(pts[i][1],pts[i][2]);
  const ms=performance.now()-t0;
  // flips: only computed when refinement is on (cheap second pass, untimed)
  let base=null;
  if(cc._refine){
    const keep=cc._refine; cc._refine=null;
    base=new Array(pts.length);
    for(let i=0;i<pts.length;i++)base[i]=cc.country(pts[i][1],pts[i][2]);
    cc._refine=keep;
  }
  return {results,ms,base};
}

let lastPts=null,lastLabel='';
function show(pts,label){
  lastPts=pts;lastLabel=label;
  const {results,ms,base}=classify(pts);
  let nCountry=0,nBorder=0,nNone=0,nFlipped=0;
  const seen=new Set();
  const features=new Array(pts.length);
  for(let i=0;i<pts.length;i++){
    const r=results[i];
    if(r.kind==='none')nNone++;else if(r.kind==='border')nBorder++;else nCountry++;
    if(r.country)seen.add(r.country);
    const flipped=base!=null&&base[i]!==r.country;
    if(flipped)nFlipped++;
    const cid=r.country==null?-1:codeToCid.get(r.country);
    features[i]={type:'Feature',
      properties:{name:pts[i][0],country:r.country,iso2:r.iso2,cname:r.name,
        kind:r.kind,conf:r.confidence,share:r.share,cell:r.cell,refined:r.refined,
        border:r.kind==='border',flipped,color:countryColor(cid)},
      geometry:{type:'Point',coordinates:[pts[i][1],pts[i][2]]}};
  }
  map.getSource('points').setData({type:'FeatureCollection',features});
  const rate=pts.length/(ms/1000);
  const refineOn=!!cc._refine;
  document.getElementById('perf').style.display='block';
  document.getElementById('perf').innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> lookups/second on this device<br>`+
    `${pts.length.toLocaleString()} points (${label}) classified in ${ms.toFixed(1)} ms `+
    `(${(ms*1000/pts.length).toFixed(2)} µs/point)`+
    `${refineOn?' · <b>refinement on</b>':''}<br>`+
    `answers: <b>${nCountry.toLocaleString()}</b> interior-country · `+
    `<b>${nBorder.toLocaleString()}</b> border · `+
    `<b>${nNone.toLocaleString()}</b> no country<br>`+
    `<b>${seen.size.toLocaleString()}</b> distinct countries hit`+
    `${refineOn?`<br><span style="color:#c2185b">◉</span> <b>${nFlipped.toLocaleString()}</b> `+
      `answer${nFlipped===1?'':'s'} changed by the polygon test `+
      `(ringed on the map, click one)`:''}`;
}

function splitCsvLine(l){
  const out=[];let cur='',q=false;
  for(let i=0;i<l.length;i++){const ch=l[i];
    if(q){if(ch==='"'){if(l[i+1]==='"'){cur+='"';i++;}else q=false;}else cur+=ch;}
    else if(ch==='"')q=true;
    else if(ch===','||ch===';'||ch==='\\t'){out.push(cur.trim());cur='';}
    else cur+=ch;}
  out.push(cur.trim());return out;
}
function parseCsv(text){
  const lines=text.split(/\\r?\\n/).filter(l=>l.trim());
  if(!lines.length)throw new Error('empty file');
  let lonCol=0,latCol=1,nameCol=2,start=0;
  const head=splitCsvLine(lines[0].toLowerCase());
  const latIdx=head.findIndex(h=>/^(lat|latitude|y)$/.test(h));
  const lonIdx=head.findIndex(h=>/^(lon|lng|long|longitude|x)$/.test(h));
  if(latIdx>=0&&lonIdx>=0){
    lonCol=lonIdx;latCol=latIdx;start=1;
    nameCol=head.findIndex(h=>/^(name|label|id|title)$/.test(h));
  }
  const pts=[];
  for(let i=start;i<lines.length;i++){
    const c=splitCsvLine(lines[i]);
    const lon=parseFloat(c[lonCol]),lat=parseFloat(c[latCol]);
    if(!isFinite(lon)||!isFinite(lat))continue;
    if(lon<-180||lon>180||lat<-90||lat>90)continue;
    pts.push([nameCol>=0&&c[nameCol]?c[nameCol]:'',lon,lat]);
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
      tileSize:256,attribution:'© OpenStreetMap © CARTO · Trifold countrycheck demo'}},
    layers:[{id:'bg',type:'background',paint:{'background-color':'#cfe3ef'}},
            {id:'base',type:'raster',source:'carto'}]},
  center:[15,30],zoom:1.4,
  canvasContextAttributes:{preserveDrawingBuffer:true}});
map.addControl(new maplibregl.NavigationControl());

// triangle ring (closed, GeoJSON order) of the level-10 cell at a point
function cellRingAt(lon,lat){
  const index=locateIndex(lon,lat,cc.level);
  const ring=indexToLonLatRing(index,cc.level).map(p=>[p[0],p[1]]);
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
  const r=cc.check(lon,lat);
  const cid=r.country==null?-1:codeToCid.get(r.country);
  let html=name?`<b>${name}</b><br>`:'';
  if(r.country!=null){
    html+=`<b style="color:${countryColor(cid)}">${r.country}</b>`+
      `${r.iso2?` (${r.iso2})`:''} — ${r.name||''}<br>`;
  }else{
    html+=`<b style="color:${NONE_COLOR}">no country</b> (international waters)<br>`;
  }
  html+=`kind <b>${r.kind}</b> · confidence ${r.confidence.toFixed(3)}`;
  if(r.share!=null)html+=` · area share ${Number(r.share).toFixed(3)}`;
  if(r.refined)html+=`<br><span style="color:#6d4ca8">decided by exact polygon test</span>`;
  const cell=r.cell??indexToCompact(locateIndex(lon,lat,cc.level),cc.level);
  html+=`<br>cell <span style="font-family:monospace">${cell}</span>`+
    `${r.cell?'':' <span style="color:#777">(empty = open ocean)</span>'}`;
  html+=`<br><span style="color:#777;font-size:11px">${lon.toFixed(4)}, ${lat.toFixed(4)}</span>`;
  return html;
}

map.on('load',()=>{
  map.addSource('borders',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'borderzones',type:'fill',source:'borders',
    paint:{'fill-color':['get','color'],'fill-opacity':0.5,'fill-antialias':false}});
  map.addSource('cell',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'cell-fill',type:'fill',source:'cell',
    paint:{'fill-color':'#6d4ca8','fill-opacity':0.12}});
  map.addLayer({id:'cell-line',type:'line',source:'cell',
    paint:{'line-color':'#6d4ca8','line-width':2}});
  map.addSource('points',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  const flipped=['boolean',['get','flipped'],false];
  const border=['boolean',['get','border'],false];
  map.addLayer({id:'pts',type:'circle',source:'points',paint:{
    'circle-color':['get','color'],
    'circle-radius':['interpolate',['linear'],['zoom'],
      0,['case',flipped,4,2.2],
      4,['case',flipped,5.5,3.5],
      8,['case',flipped,7,5]],
    'circle-opacity':0.85,
    'circle-stroke-width':['case',flipped,2.2,border,1.4,0.6],
    'circle-stroke-color':['case',flipped,'#c2185b',border,'#1c2733','rgba(0,0,0,.4)']}});
  // route (polyline) layers: one coloured line feature per classified segment
  map.addSource('route',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-line',type:'line',source:'route',
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':['get','color'],'line-width':5,'line-opacity':0.92}});
  map.addSource('routeverts',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-verts',type:'circle',source:'routeverts',
    paint:{'circle-color':'#111','circle-radius':4.5,
      'circle-stroke-width':2,'circle-stroke-color':'#fff'}});
  map.on('click',e=>{
    let lon=e.lngLat.lng,lat=e.lngLat.lat;
    lon=((lon+180)%360+360)%360-180;
    lat=Math.max(-90,Math.min(90,lat));
    if(mode==='route'&&drawing){addVertex(lon,lat);return;}
    const seg=map.queryRenderedFeatures(e.point,{layers:['route-line']});
    if(mode==='route'&&seg.length){
      const p=seg[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
        `<b>${p.cname||p.country||'no country'}</b>`+
        `${p.iso2?' ('+p.iso2+')':''} · kind <b>${p.kind}</b><br>`+
        `${(+p.distanceKm).toFixed(1)} km (${(100*p.fraction).toFixed(1)}% of route)`).addTo(map);
      return;
    }
    if(map.queryRenderedFeatures(e.point,{layers:['pts']}).length)return;
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
  map.on('moveend',()=>{if(bordercb.checked)updateBorders();});
  show(CITIES.map(c=>[c[0],c[1],c[2]]),'capitals + tricky spots');
});

document.getElementById('b-cities').onclick=()=>show(CITIES.map(c=>[c[0],c[1],c[2]]),'capitals + tricky spots');
document.getElementById('b-r1').onclick=()=>show(randomPoints(1000),'uniform random on sphere');
document.getElementById('b-r10').onclick=()=>show(randomPoints(10000),'uniform random on sphere');
document.getElementById('b-r100').onclick=()=>show(randomPoints(100000),'uniform random on sphere');

// --- source border debug layer (zone rings decoded from TFCR) ---
const bordercb=document.getElementById('bordercb');
const bordernote=document.getElementById('bordernote');
let cellBoxes=null;   // [index,minx,miny,maxx,maxy] per refined cell, lazy
function buildCellBoxes(){
  cellBoxes=[];
  for(const [index,zones] of cc._refine){
    let hasRings=false;
    for(const [cid,rings] of zones)if(rings!==null){hasRings=true;break;}
    if(!hasRings)continue;   // whole-cell zones: nothing to draw
    const ring=indexToLonLatRing(index,cc.level);
    const lons=ring.map(p=>p[0]),lats=ring.map(p=>p[1]);
    cellBoxes.push([index,Math.min(...lons),Math.min(...lats),
                    Math.max(...lons),Math.max(...lats)]);
  }
}
// even-odd ray cast in the cell-local quantized grid (flat [x0,y0,x1,y1,...])
function pointInRingQ(px,py,pts){
  const n=pts.length/2;let inside=false;
  for(let i=0,j=n-1;i<n;j=i++){
    const xi=pts[2*i],yi=pts[2*i+1],xj=pts[2*j],yj=pts[2*j+1];
    if(((yi>py)!==(yj>py))&&(px<(xj-xi)*(py-yi)/((yj-yi)||1e-9)+xi))inside=!inside;
  }
  return inside;
}
function borderFeatures(){
  if(!cellBoxes)buildCellBoxes();
  const b=map.getBounds();
  const w=b.getWest(),e=b.getEast(),s=b.getSouth(),n=b.getNorth();
  const feats=[];let nverts=0;
  for(const [index,minx,miny,maxx,maxy] of cellBoxes){
    if(maxy<s||miny>n)continue;
    let hit=false;
    for(const off of [-360,0,360]){if(maxx+off>=w&&minx+off<=e){hit=true;break;}}
    if(!hit)continue;
    const sx=(maxx-minx)/65535,sy=(maxy-miny)/65535;
    // fill each country's zone in this border cell, coloured by country. The
    // dataset's zone rings are even-odd, so sort by area and nest a ring inside
    // a larger one as its hole; disjoint rings become separate polygons.
    for(const [cid,rings] of cc._refine.get(index)){
      if(rings===null)continue;
      const color=countryColor(cid);
      const decoded=rings.map(pts=>{
        const m=pts.length/2,ll=new Array(m+1);
        let a=0;
        for(let i=0;i<m;i++){
          ll[i]=[minx+pts[2*i]*sx,miny+pts[2*i+1]*sy];
          const j=(i+1)%m;a+=pts[2*i]*pts[2*j+1]-pts[2*j]*pts[2*i+1];
        }
        ll[m]=ll[0];
        nverts+=m;
        return {ll,area:Math.abs(a)/2,q:pts};
      }).sort((p,q)=>q.area-p.area);
      const polys=[];
      for(const d of decoded){
        let host=null;
        for(const P of polys)if(pointInRingQ(d.q[0],d.q[1],P.q)){host=P;break;}
        if(host)host.coords.push(d.ll);
        else polys.push({coords:[d.ll],q:d.q});
      }
      for(const P of polys)feats.push({type:'Feature',properties:{color},
        geometry:{type:'Polygon',coordinates:P.coords}});
    }
    if(nverts>120000)return null;   // too much detail for this view
  }
  return feats;
}
function updateBorders(){
  if(!bordercb.checked){
    map.getSource('borders').setData({type:'FeatureCollection',features:[]});
    return;
  }
  if(!cc._refine){
    bordernote.textContent='Turn on exact border refinement first to load the polygons.';
    bordercb.checked=false;return;
  }
  const feats=borderFeatures();
  if(feats===null){
    map.getSource('borders').setData({type:'FeatureCollection',features:[]});
    bordernote.textContent='Source border zones: zoom in further to draw them.';
    return;
  }
  map.getSource('borders').setData({type:'FeatureCollection',features:feats});
  bordernote.textContent=`${feats.length.toLocaleString()} border-cell zone(s) in view, `+
    `filled and coloured by country, decoded from the refinement dataset — exactly the `+
    `geometry the refined lookup tests against.`;
}
bordercb.onchange=updateBorders;

// --- exact border refinement toggle ---
let refineCells=null;   // decoded TFCR, kept so the checkbox can flip freely
const refinecb=document.getElementById('refinecb');
const refinenote=document.getElementById('refinenote');
refinecb.onchange=async()=>{
  if(refinecb.checked&&!refineCells){
    refinecb.disabled=true;
    refinenote.textContent='Downloading border refinement layer…';
    let loaded=false;
    for(const url of TFCR_URLS){
      try{
        const res=await fetch(url);
        if(!res.ok)continue;
        const buf=await res.arrayBuffer();
        refinenote.textContent=`Decoding ${(buf.byteLength/1e6).toFixed(1)} MB…`;
        await cc.loadRefinement(new Uint8Array(buf));
        refineCells=cc._refine;
        loaded=true;
        refinenote.textContent=`Loaded: ${refineCells.size.toLocaleString()} border cells with `+
          `exact polygon detail. Border answers are now near-exact (confidence 0.99).`;
        break;
      }catch(err){console.warn(url,err);}
    }
    refinecb.disabled=false;
    if(!loaded){
      refinecb.checked=false;
      refinenote.textContent='Could not download the refinement layer, so the bundled best calls stay in use.';
      return;
    }
  }else{
    cc._refine=refinecb.checked?refineCells:null;
    refinenote.textContent=refinecb.checked
      ?'Exact polygon test active in border cells.'
      :'Off: border cells use the bundled best call and its area share.';
  }
  if(lastPts)show(lastPts,lastLabel);   // re-classify so the effect is visible
  updateBorders();                      // border layer follows refinement
};
function parseGeojsonLine(text){
  const gj=JSON.parse(text);
  const feats=gj.type==='FeatureCollection'?gj.features:gj.type==='Feature'?[gj]:[gj];
  for(const f of feats){
    const g=f.geometry||f;
    if(g.type==='LineString')return g.coordinates.map(c=>[c[0],c[1]]);
    if(g.type==='MultiLineString')return g.coordinates[0].map(c=>[c[0],c[1]]);
  }
  throw new Error('no LineString found');
}
document.getElementById('fileinput').onchange=async e=>{
  const file=e.target.files[0];
  if(!file)return;
  document.getElementById('droperr').textContent='';
  try{
    const text=await file.text();
    const isJson=text.trimStart().startsWith('{');
    if(mode==='route'){
      const coords=isJson?parseGeojsonLine(text)
        :parseCsv(text).map(p=>[p[1],p[2]]);
      if(coords.length<2)throw new Error('need at least two vertices');
      if(coords.length>100000)throw new Error('too many vertices (max 100k)');
      loadRoute(coords);
      e.target.value='';return;
    }
    const pts=isJson?parseGeojson(text):parseCsv(text);
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

// ---- Route (polyline) mode ----
let mode='points',drawing=false,routePts=[];
const perf=document.getElementById('perf');
const routenote=document.getElementById('routenote');
const bDraw=document.getElementById('b-draw');
const ROUTES={
  eu:[[13.405,52.52],[21.0122,52.2297],[25.2797,54.6872]],   // Berlin -> Warsaw -> Vilnius
  med:[[-3.7038,40.4168],[12.4964,41.9028]],                  // Madrid -> Rome
  asia:[[28.9784,41.0082],[51.3890,35.6892],[77.2090,28.6139]]};  // Istanbul -> Tehran -> Delhi
function stepKm(){return parseFloat(document.querySelector('#seg-step .on').dataset.v);}
function segColor(s){
  return s.country==null?NONE_COLOR:countryColor(codeToCid.get(s.country));
}
function classifyRoute(){
  const coords=routePts.slice();
  if(coords.length<2){routenote.textContent='Add at least two points.';return;}
  const step=stepKm();
  const t0=performance.now();
  const res=cc.checkPolyline(coords,{stepKm:step});   // the real library call, timed
  const ms=performance.now()-t0;
  // colour the line: re-sample and group consecutive samples sharing country+kind.
  // segments join at the midpoint between samples (no gaps); stats come from
  // res.segments, whose order matches this grouping one-to-one.
  const {samples}=samplePolyline(coords,step,'uniform');
  const cls=samples.map(s=>cc.check(s[0],s[1]));
  const mid=(p,q)=>[(p[0]+q[0])/2,(p[1]+q[1])/2];
  const feats=[];let i=0,k=0;
  while(i<samples.length){
    const a=cls[i];let j=i;
    while(j+1<samples.length&&cls[j+1].country===a.country)j++;
    const cid=a.country==null?-1:codeToCid.get(a.country);
    const line=samples.slice(i,j+1);
    if(i>0)line.unshift(mid(samples[i-1],samples[i]));
    if(j<samples.length-1)line.push(mid(samples[j],samples[j+1]));
    const seg=res.segments[k++]||{};
    feats.push({type:'Feature',
      properties:{color:a.country==null?NONE_COLOR:countryColor(cid),
        country:a.country,iso2:a.iso2,cname:a.name,kind:a.kind,
        distanceKm:seg.distanceKm,fraction:seg.fraction},
      geometry:{type:'LineString',coordinates:line}});
    i=j+1;
  }
  map.getSource('route').setData({type:'FeatureCollection',features:feats});
  map.getSource('routeverts').setData({type:'FeatureCollection',
    features:coords.map(c=>({type:'Feature',properties:{},
      geometry:{type:'Point',coordinates:c}}))});
  map.getSource('points').setData(EMPTY);
  const rate=samples.length/(ms/1000);
  const refineOn=!!cc._refine;
  let rows='';
  for(const s of res.segments)
    rows+=`<span style="color:${segColor(s)}">■</span> `+
      `<b>${s.name||s.country||'no country'}</b>${s.iso2?' ('+s.iso2+')':''} · `+
      `${s.distanceKm.toFixed(0)} km (${(100*s.fraction).toFixed(0)}%)<br>`;
  perf.style.display='block';
  perf.innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> samples/second on this device<br>`+
    `${samples.length.toLocaleString()} samples · `+
    `${res.totalDistanceKm.toFixed(0)} km total · `+
    `${res.segments.length} segment${res.segments.length===1?'':'s'} (step ${step} km)`+
    `${refineOn?' · <b>refinement on</b>':''}<br>`+rows;
  routenote.textContent=`${coords.length} vertices · classified in ${ms.toFixed(1)} ms.`;
}
function addVertex(lon,lat){
  routePts.push([lon,lat]);
  map.getSource('routeverts').setData({type:'FeatureCollection',
    features:routePts.map(c=>({type:'Feature',properties:{},
      geometry:{type:'Point',coordinates:c}}))});
  if(routePts.length>=2)
    map.getSource('route').setData({type:'FeatureCollection',
      features:[{type:'Feature',properties:{color:'#888'},
        geometry:{type:'LineString',coordinates:routePts.slice()}}]});
  routenote.textContent=`${routePts.length} point(s) — click to add more, Finish to classify.`;
}
function startDraw(){
  drawing=true;routePts=[];
  map.getSource('route').setData(EMPTY);map.getSource('routeverts').setData(EMPTY);
  perf.style.display='none';bDraw.textContent='✓ Finish';bDraw.classList.add('on');
  map.getCanvas().style.cursor='crosshair';
  routenote.textContent='Click the map to drop route points; click Finish to classify.';
}
function endDraw(){
  drawing=false;bDraw.textContent='✏️ Draw on map';bDraw.classList.remove('on');
  map.getCanvas().style.cursor='';
}
bDraw.onclick=()=>{
  if(drawing){endDraw();if(routePts.length>=2)classifyRoute();
    else routenote.textContent='Need at least two points — pick an example or draw again.';}
  else startDraw();
};
document.getElementById('b-route-clear').onclick=()=>{
  endDraw();routePts=[];map.getSource('route').setData(EMPTY);
  map.getSource('routeverts').setData(EMPTY);perf.style.display='none';
  routenote.textContent='Pick an example, or hit Draw on map.';
};
function loadRoute(coords){
  endDraw();routePts=coords.map(c=>c.slice());classifyRoute();
  const b=new maplibregl.LngLatBounds();for(const c of routePts)b.extend(c);
  map.fitBounds(b,{padding:90,duration:600});
}
document.getElementById('b-route-eu').onclick=()=>loadRoute(ROUTES.eu);
document.getElementById('b-route-med').onclick=()=>loadRoute(ROUTES.med);
document.getElementById('b-route-asia').onclick=()=>loadRoute(ROUTES.asia);
document.querySelectorAll('#seg-step button').forEach(b=>{b.onclick=()=>{
  document.querySelectorAll('#seg-step button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  if(mode==='route'&&routePts.length>=2)classifyRoute();
};});
function setMode(m){
  mode=m;
  document.querySelectorAll('#seg-mode button').forEach(x=>x.classList.toggle('on',x.dataset.v===m));
  document.getElementById('row-points').style.display=m==='points'?'':'none';
  document.getElementById('row-route').style.display=m==='route'?'':'none';
  perf.style.display='none';
  if(m==='points'){
    endDraw();routePts=[];
    map.getSource('route').setData(EMPTY);map.getSource('routeverts').setData(EMPTY);
    if(lastPts)show(lastPts,lastLabel);
  }else{
    map.getSource('points').setData(EMPTY);map.getSource('cell').setData(EMPTY);
    routenote.textContent='Pick an example, or hit Draw on map.';
  }
}
document.querySelectorAll('#seg-mode button').forEach(b=>{b.onclick=()=>setMode(b.dataset.v);});

window.__countrycheck={map,cc};   // console/debug handle
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
            .replace('__GHICON__', GH_ICON)
            .replace('__INDEX_BENCH__',
                     render_bench('benchmark.md', 'Batch: 100,000', 'points/s', 'pts/s')))
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
# benchmark bars are generated from the markdown docs so the page can never
# drift from the recorded numbers (single source of truth)
LC_MD, CC_MD = 'benchmark.md', 'countrycheck_benchmark.md'
BATCH_T = 'Batch &middot; 100,000 points per call'
SING_T = 'Singular &middot; one point per call'
POLY_T = 'Route (polyline) &middot; per sampled point'
bench = {
    '__LC_BENCH_BATCH__': render_bench(LC_MD, 'Batch: 100,000', 'points/s', 'pts/s', BATCH_T),
    '__LC_BENCH_SINGULAR__': render_bench(LC_MD, 'Singular: one point per call', 'queries/s', 'q/s', SING_T),
    '__LC_BENCH_POLYLINE__': render_bench(LC_MD, 'Polyline', 'per-sample rate', 'samples/s', POLY_T),
    '__CC_BENCH_BATCH__': render_bench(CC_MD, 'Batch: 100,000', 'points/s', 'pts/s', BATCH_T),
    '__CC_BENCH_SINGULAR__': render_bench(CC_MD, 'Singular: one point per call', 'queries/s', 'q/s', SING_T),
    '__CC_BENCH_POLYLINE__': render_bench(CC_MD, 'Polyline', 'per-sample rate', 'samples/s', POLY_T),
}
for k, v in bench.items():
    landcheck_html = landcheck_html.replace(k, v)
    countrycheck_html = countrycheck_html.replace(k, v)

with open(OUT_LANDCHECK, 'w') as f:
    f.write(landcheck_html.replace('__TFLS_B64__', tfls_b64)
            .replace('__TFLR_URL__', f'{PMTILES_BASE_URL}/coastal_osm_L10.tflr')
            .replace('__NE_URL__', f'{PMTILES_BASE_URL}/ne_50m_land.geojson')
            .replace('__GH__', GH)
            .replace('__GHICON__', GH_ICON))
print(f"{OUT_LANDCHECK}: {os.path.getsize(OUT_LANDCHECK)/1e6:.1f} MB "
      f"(incl. {len(tfls_b64)/1e3:.0f} KB b64 dataset)")

shutil.copy2(COUNTRYCHECK_SDK, DOCS_COUNTRYCHECK_SDK)
tfcs_b64 = base64.b64encode(open(COUNTRYCHECK_TFCS, 'rb').read()).decode()
# border refinement (TFCR): fetched on demand from the data host in production;
# copy into docs/data/ (gitignored) so the toggle works locally
tfcr_src = 'countrycheck/data/borders_L10.tfcr'
if os.path.isfile(tfcr_src):
    os.makedirs('docs/data', exist_ok=True)
    shutil.copy2(tfcr_src, 'docs/data/borders_L10.tfcr')
with open(OUT_COUNTRYCHECK, 'w') as f:
    f.write(countrycheck_html.replace('__TFCS_B64__', tfcs_b64)
            .replace('__TFCR_URL__', f'{PMTILES_BASE_URL}/borders_L10.tfcr')
            .replace('__GH__', GH)
            .replace('__GHICON__', GH_ICON))
print(f"{OUT_COUNTRYCHECK}: {os.path.getsize(OUT_COUNTRYCHECK)/1e6:.1f} MB "
      f"(incl. {len(tfcs_b64)/1e3:.0f} KB b64 dataset)")
