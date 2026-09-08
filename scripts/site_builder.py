"""Shared static documentation shell. Canonical copy remains in templates/Markdown."""
from dataclasses import dataclass
from html import escape
from pathlib import Path
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import markdown

ROOT = Path('scripts/site')
PAGES = [('index', 'Overview'), ('sdk-api', 'SDK API'),
         ('t3-technical-reference', 'Technical reference'),
         ('landcheck', 'landcheck'), ('countrycheck', 'countrycheck'),
         ('settlementcheck', 'settlementcheck')]
TITLES = {'index': ('Trifold T3', 'A hierarchical triangular grid for the world.'),
          'landcheck': ('landcheck', 'Offline land and sea lookup.'),
          'countrycheck': ('countrycheck', 'Offline country lookup.'),
          'settlementcheck': ('settlementcheck', 'Settlement context, globally.')}


@dataclass
class PageSpec:
    id: str
    title: str
    body: str
    head_assets: str = ''
    description: str = ''
    sections: tuple = ()


def render_page(spec):
    nav = []
    for i, (key, label) in enumerate(PAGES):
        if i in (0, 3):
            nav.append(f'<p>{"Trifold" if i == 0 else "Libraries"}</p>')
        active = ' aria-current="page"' if key == spec.id else ''
        nav.append(f'<a href="{key}.html"{active}>{label}</a>')
    toc = ''.join(f'<a href="#{escape(key)}">{escape(label)}</a>' for key, label in spec.sections)
    body = spec.body.replace('<!--LOCAL_NAV-->', f'<details class="local-toc" open><summary>On this page</summary><nav aria-label="On this page">{toc}</nav></details>')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(spec.title)} · Trifold documentation</title>
<meta name="description" content="{escape(spec.description, quote=True)}">
{spec.head_assets}
<link rel="stylesheet" href="assets/site.css"><link rel="stylesheet" href="assets/map-demo.css">
<script src="assets/site.js" defer></script></head>
<body class="page-{spec.id}"><a class="skip-link" href="#main">Skip to content</a>
<header class="site-header"><a class="site-brand" href="index.html">Trifold T3</a>
<span class="site-label">Documentation</span><a class="source-link" href="https://github.com/jaakla/trifold">GitHub</a>
<button class="menu-toggle" aria-controls="product-nav" aria-expanded="false">Menu</button></header>
<div class="doc-frame"><nav id="product-nav" class="product-nav" aria-label="Documentation">{''.join(nav)}</nav>
<main id="main" tabindex="-1">{body}</main>
<aside class="page-toc"><details open><summary>On this page</summary><nav aria-label="On this page">{toc}</nav></details></aside></div>
<footer class="site-footer">Trifold T3 · <a href="https://github.com/jaakla/trifold">Source on GitHub</a> · Code MIT. See each library’s data attribution.</footer>
</body></html>'''


def normalize_document(page, source):
    soup = BeautifulSoup(source, 'html.parser')
    head = ''.join(str(n) for n in soup.head.find_all(['script', 'link'], recursive=False))
    head = head.replace('maplibre-gl@5.6.0', 'maplibre-gl@5.6.2')
    body = soup.body
    for footer in body.find_all('footer', recursive=False):
        footer.name = 'p'
        footer['class'] = ['small', 'page-source-note']
    for node in body.find_all('nav', recursive=False):
        node.decompose()
    hero = body.select_one('.hero')
    title, subtitle = TITLES[page]
    # Keep the authored introduction; compact only its heading and navigation.
    if hero:
        heading = hero.find('h1')
        heading.clear()
        heading.string = title
        for node in hero.select('.eyebrow'):
            node.decompose()
        desc = soup.new_tag('p', attrs={'class':'page-subtitle'})
        desc.string = subtitle
        heading.insert_after(desc)
        for cta in hero.select('.cta'):
            cta.decompose()
        actions = BeautifulSoup('<div class="page-actions"><a href="#quickstart">Quickstart</a><a href="#demo">Try demo</a></div>', 'html.parser')
        if page == 'index':
            hero.append(actions)
        from bs4 import Comment
        hero.insert_after(Comment('LOCAL_NAV'))
        if page in ('landcheck', 'countrycheck'):
            # Long original introduction remains in the technical section.
            for paragraph in list(hero.find_all('p', recursive=False)):
                if 'page-subtitle' not in paragraph.get('class', []):
                    body.select_one('#tech h2').insert_after(paragraph.extract())
    for main in body.find_all('main'):
        main.unwrap()
    # Old sections/anchors are retained, including guide and technical links.
    guide = body.select_one('#guide')
    if guide:
        guide.insert(0, BeautifulSoup('<span id="quickstart"></span>', 'html.parser'))
    if page == 'index':
        hero.insert_after(BeautifulSoup('''<section id="library-index"><h2>Libraries</h2><table>
<tr><td><a href="landcheck.html">landcheck</a></td><td>Offline land and sea lookup</td></tr>
<tr><td><a href="countrycheck.html">countrycheck</a></td><td>Offline country lookup</td></tr>
<tr><td><a href="settlementcheck.html">settlementcheck</a></td><td>Offline settlement classification</td></tr></table></section>
<section id="quickstart"><h2>Quickstart</h2>
<div class="twocol"><div><h3>Python</h3><pre><code>pip install t3grid

from trifold import locate_address, to_compact
print(to_compact(locate_address(24.7536, 59.4370, 12)))</code></pre></div>
<div><h3>JavaScript</h3><pre><code>npm install t3grid

import { locateAddress, toCompact } from 't3grid';
console.log(toCompact(locateAddress(24.7536, 59.4370, 12)));</code></pre></div></div>
<p><a href="sdk-api.html">SDK API</a> · <a href="t3-technical-reference.html">Technical reference</a></p></section>''', 'html.parser'))
        preview = body.select_one('#libraries img')
        if preview:
            preview.parent.decompose()
        body.select_one('#libraries .twocol')['class'] = ['library-notes']
        body.select_one('#libraries h2').string = 'Library implementations and benchmarks'
    # Keep instructions and benchmark caveats, but give every demo the same
    # heading → shared workspace → explanation structure.
    for demo_section in body.select('section#demo, section#coverage'):
        frame = demo_section.select_one('.viewerwrap,.coverwrap')
        inner = demo_section.select_one('.inner')
        if frame and inner:
            for paragraph in reversed(inner.find_all('p', recursive=False)):
                frame.insert_after(paragraph.extract())
    if page == 'settlementcheck':
        workbench = body.select_one('.workbench')
        workbench['id'] = 'demo'
        workbench.insert(0, BeautifulSoup('<h2>Interactive demo</h2>', 'html.parser'))
        # Explicit semantics and loading documentation, no inferred population.
        docs = body.select_one('.docs')
        for paragraph in list(hero.find_all('p', recursive=False)):
            if 'page-subtitle' not in paragraph.get('class', []):
                docs.find('h2').insert_after(paragraph.extract())
        hero.append(BeautifulSoup('<p>Offline Degree of Urbanisation lookup.</p>', 'html.parser'))
        docs.append(BeautifulSoup('''<h2 id="data">Data and loading</h2>
<p>The 4.58 MB class core loads first. Boundary details are optional shards by icosahedron face;
the default cache retains two faces. No detail shard downloads until requested.
Population counts, settlement names and administrative layers are not included.</p>
<table><thead><tr><th>Field (Python)</th><th>Core only</th><th>With details</th></tr></thead><tbody>
<tr><td>class_share</td><td>null</td><td>Dominant source-class area share</td></tr>
<tr><td>mixed / nodata_mixed</td><td>null</td><td>Boundary / nodata mixture flags</td></tr>
<tr><td>details_loaded</td><td>false</td><td>true</td></tr></tbody></table>
<p>JavaScript uses camelCase. Unknown details never imply a homogeneous cell.
Use <code>classify</code> for offline classes, <code>checkAsync</code> for lazy details in JavaScript,
and <code>check</code> for optional local details in Python. Install the core from this repository
with <code>pip install ./settlementcheck</code> or <code>npm install ./settlementcheck</code>.
See the <a href="https://github.com/jaakla/trifold/tree/main/settlementcheck">loading API and optional details setup</a>.</p>''', 'html.parser'))
        python_heading = next(n for n in docs.find_all('h2') if n.get_text() == 'Python')
        python_heading['id'] = 'quickstart'
    # Uniform headings and stable section links; preserve every existing id.
    sections = []
    used = {n['id'] for n in body.select('[id]')}
    for h in body.find_all('h2'):
        parent = h.find_parent('section')
        key = h.get('id') or (parent.get('id') if parent else None)
        if not key:
            key = re.sub(r'[^a-z0-9]+', '-', h.get_text().lower()).strip('-')
            while key in used:
                key += '-section'
            h['id'] = key
            used.add(key)
        if key not in [s[0] for s in sections]:
            labels = {'quickstart':'Quickstart', 'demo':'Demo', 'guide':'Quickstart / API',
                      'results':'API', 'data':'Data', 'source-and-provenance':'Sources',
                      'tech':'Data and technical info', 'benchmark':'Benchmarks',
                      'accuracy':'Accuracy'}
            sections.append((key, labels.get(key, h.get_text(' ', strip=True))))
    for table in body.find_all('table'):
        wrapper = soup.new_tag('div', attrs={'class':'table-scroll', 'tabindex':'0', 'role':'region', 'aria-label':'Scrollable data table'})
        table.wrap(wrapper)
    if page != 'index':
        priority = ['quickstart', 'guide', 'demo', 'results', 'degurba-classes', 'data', 'tech', 'accuracy', 'benchmark', 'source-and-provenance']
        sections.sort(key=lambda item: priority.index(item[0]) if item[0] in priority else len(priority))
    # Technical Markdown is available as matching HTML, not a GitHub detour.
    for link in body.find_all('a', href=True):
        for key in ('sdk-api', 't3-technical-reference'):
            if link['href'].split('#')[0].endswith(key + '.md'):
                fragment = '#' + link['href'].split('#', 1)[1] if '#' in link['href'] else ''
                link['href'] = key + '.html' + fragment
    return PageSpec(page, title, body.decode_contents(), head, subtitle, tuple(sections))


def build_site(github, carto_key, tiles_base):
    out = Path('docs/assets')
    out.mkdir(exist_ok=True)
    tokens = {'__TFLR_URL__': f'{tiles_base}/coastal_osm_L10.tflr',
              '__NE_URL__': f'{tiles_base}/ne_50m_land.geojson',
              '__TFCR_URL__': f'{tiles_base}/borders_L10.tfcr',
              '__CARTO_KEY_JSON__': json.dumps(carto_key)}
    for asset in (ROOT / 'assets').iterdir():
        if not asset.is_file():
            continue
        content = asset.read_text()
        for token, value in tokens.items():
            content = content.replace(token, value)
        (out / asset.name).write_text(content)
    for page in TITLES:
        path = Path(f'docs/{page}.html')
        path.write_text(render_page(normalize_document(page, path.read_text())))
    for page, label in PAGES[1:3]:
        source = Path(f'docs/{page}.md').read_text()
        md = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc'])
        soup = BeautifulSoup(md.convert(source), 'html.parser')
        sections = tuple((h['id'], h.get_text()) for h in soup.find_all('h2'))
        for link in soup.find_all('a', href=True):
            href = link['href']
            if not urlsplit(href).scheme and not href.startswith('#'):
                base, sep, fragment = href.partition('#')
                if base in ('sdk-api.md', 't3-technical-reference.md'):
                    link['href'] = base[:-3] + '.html' + sep + fragment
                else:
                    from posixpath import normpath
                    link['href'] = github + '/blob/main/' + normpath('docs/' + base) + sep + fragment
        for table in soup.find_all('table'):
            table.wrap(soup.new_tag('div', attrs={'class':'table-scroll', 'tabindex':'0'}))
        Path(f'docs/{page}.html').write_text(render_page(PageSpec(page, label, str(soup), sections=sections)))
