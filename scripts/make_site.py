#!/usr/bin/env python
"""Build the Trifold documentation and separate live demo (GitHub Pages ready)."""
import base64
import gzip
import json
import os
import re
import shutil
from pathlib import Path
from site_builder import build_site

DATA = 'data'
OUT = 'docs/index.html'
OUT_DEMO = 'docs/demo.html'


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
OUT_SETTLEMENTCHECK = 'docs/settlementcheck.html'
JS_SDK = 'js/trifold.js'
DOCS_SDK = 'docs/sdk/trifold.js'
LANDCHECK_SDK = 'landcheck/js/landcheck.mjs'
DOCS_LANDCHECK_SDK = 'docs/sdk/landcheck.mjs'
LANDCHECK_TFLS = 'landcheck/data/landsea_L10.tfls'
COUNTRYCHECK_SDK = 'countrycheck/js/countrycheck.mjs'
DOCS_COUNTRYCHECK_SDK = 'docs/sdk/countrycheck.mjs'
COUNTRYCHECK_TFCS = 'countrycheck/data/countries_L10.tfcs'
SETTLEMENTCHECK_SDK = 'settlementcheck/js/settlementcheck.mjs'
DOCS_SETTLEMENTCHECK_SDK = 'docs/sdk/settlementcheck.mjs'
SETTLEMENTCHECK_TFDG = 'settlementcheck/data/degurba_R2025A_E2025_L12.tfdg'
SETTLEMENTCHECK_TEMPLATE = 'scripts/settlementcheck.template.html'
GH = 'https://github.com/jaakla/trifold'
PMTILES_BASE_URL = os.environ.get('TRIFOLD_PMTILES_BASE_URL', 'https://maps.goplex.ee/data').rstrip('/')
# Public browser basemap key for these demos; override when hosting elsewhere.
CARTO_BASEMAP_KEY = os.environ.get('TRIFOLD_CARTO_BASEMAP_KEY',
                                'cb1_2zu5_1_1f6393489af4f16ddf97b334')

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
existing_payload = existing_pmtiles = existing_stats = {}
for existing_page in (OUT_DEMO, OUT):
    if not os.path.isfile(existing_page):
        continue
    existing_html = Path(existing_page).read_text()
    def _existing_json(name):
        match = re.search(rf'const {name} = (.*?);\n', existing_html, re.S)
        return json.loads(match.group(1)) if match else {}
    existing_payload = _existing_json('DATASETS')
    existing_pmtiles = _existing_json('PMTILES_DATASETS')
    existing_stats = _existing_json('DATASET_STATS')
    if existing_payload or existing_pmtiles:
        break
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

    source_path = os.path.join(DATA, fn)
    if not os.path.isfile(source_path):
        # A clean checkout intentionally omits generated grid products. Reuse
        # the generated page's embedded/hosted payload while rebuilding docs.
        if key in existing_payload:
            datasets[key] = existing_payload[key]
            total += len(datasets[key])
            continue
        if key in existing_pmtiles:
            pmtiles[key] = existing_pmtiles[key]
            dataset_stats[key] = existing_stats[key]
            continue
        raise FileNotFoundError(f'{source_path} is missing and has no generated-doc fallback')
    raw = open(source_path, 'rb').read()
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

html = Path("scripts/site/templates/index.html").read_text()
demo_html = Path("scripts/site/templates/demo.html").read_text()

landcheck_html = Path("scripts/site/templates/landcheck.html").read_text()

countrycheck_html = Path("scripts/site/templates/countrycheck.html").read_text()


os.makedirs('docs', exist_ok=True)
os.makedirs(os.path.dirname(DOCS_SDK), exist_ok=True)
shutil.copy2(JS_SDK, DOCS_SDK)
with open(OUT, 'w') as f:
    f.write(html.replace('__GH__', GH)
            .replace('__INDEX_BENCH__',
                     render_bench('benchmark.md', 'Batch: 100,000', 'points/s', 'pts/s')))
print(f"{OUT}: {os.path.getsize(OUT)/1e6:.1f} MB")
Path(OUT_DEMO).write_text(demo_html.replace('__DATA__', data_js))
print(f"{OUT_DEMO}: {os.path.getsize(OUT_DEMO)/1e6:.1f} MB")

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
            .replace('__GH__', GH))
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
            .replace('__GH__', GH))
print(f"{OUT_COUNTRYCHECK}: {os.path.getsize(OUT_COUNTRYCHECK)/1e6:.1f} MB "
      f"(incl. {len(tfcs_b64)/1e3:.0f} KB b64 dataset)")

shutil.copy2(SETTLEMENTCHECK_SDK, DOCS_SETTLEMENTCHECK_SDK)
os.makedirs('docs/data', exist_ok=True)
shutil.copy2(SETTLEMENTCHECK_TFDG,
             'docs/data/degurba_R2025A_E2025_L12.tfdg')
shutil.copytree(SETTLEMENTCHECK_TFDG.removesuffix('.tfdg') + '.details',
                'docs/data/degurba_R2025A_E2025_L12.details', dirs_exist_ok=True)
with open(SETTLEMENTCHECK_TEMPLATE, encoding='utf-8') as f:
    settlementcheck_html = f.read()
with open(OUT_SETTLEMENTCHECK, 'w', encoding='utf-8') as f:
    f.write(settlementcheck_html.replace('__GH__', GH))
print(f"{OUT_SETTLEMENTCHECK}: {os.path.getsize(OUT_SETTLEMENTCHECK)/1e6:.1f} MB "
      f"(+ {os.path.getsize(SETTLEMENTCHECK_TFDG)/1e6:.1f} MB data)")

build_site(GH, CARTO_BASEMAP_KEY, PMTILES_BASE_URL)
