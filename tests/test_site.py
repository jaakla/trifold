"""Small static regressions. No scientific dataset rebuild or browser stress test."""
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index', 'landcheck', 'countrycheck', 'settlementcheck', 'sdk-api', 't3-technical-reference')


def test_site_navigation_and_anchors():
    documents = {name: BeautifulSoup((ROOT / f'docs/{name}.html').read_text(), 'html.parser') for name in PAGES}
    for name, soup in documents.items():
        ids = [n['id'] for n in soup.select('[id]')]
        assert len(ids) == len(set(ids)), name
        assert len(soup.select('main')) == 1
        assert soup.select_one(f'#product-nav a[aria-current="page"][href="{name}.html"]')
        assert len(soup.select('#product-nav a')) == 6
        for link in soup.select('a[href]'):
            href = urlsplit(link['href'])
            if href.scheme or href.netloc:
                continue
            if not href.path:
                if href.fragment:
                    assert soup.find(id=unquote(href.fragment)), (name, link['href'])
            elif href.path.endswith('.html'):
                dest = documents.get(href.path[:-5])
                assert dest is not None, (name, link['href'])
                if href.fragment:
                    assert dest.find(id=unquote(href.fragment)), (name, link['href'])
            else:
                assert (ROOT / 'docs' / href.path).exists(), (name, link['href'])


def test_preserve_original_section_anchors():
    baseline = {
        'index': ('libraries', 'concept', 'addressing', 'demo', 'coverage', 'compare', 'usecases'),
        'landcheck': ('demo', 'guide', 'tech', 'benchmark'),
        'countrycheck': ('demo', 'guide', 'tech', 'accuracy', 'benchmark'),
        'settlementcheck': (),
    }
    for name, anchors in baseline.items():
        current = BeautifulSoup((ROOT / f'docs/{name}.html').read_text(), 'html.parser')
        for anchor in anchors:
            assert current.find(id=anchor), (name, anchor)


def test_safety_and_asset_contract():
    runtime = (ROOT / 'docs/assets/settlementcheck-demo.mjs').read_text()
    assert 'CELL_CAP=6500' in runtime
    assert 'addresses.length>CELL_CAP' in runtime
    assert "document.getElementById('mixed').checked?await sc.checkAsync" in runtime
    assert 'loadWithRetry' in runtime
    for name in PAGES:
        text = (ROOT / f'docs/{name}.html').read_text()
        assert not re.search(r'__[A-Z][A-Z_]+__', text)
        assert 'Equal Earth' not in text
        soup = BeautifulSoup(text, 'html.parser')
        assert not soup.find('style')
        assert 'LOCAL_NAV' not in soup.get_text()
        if name in PAGES[:4]:
            assert soup.select_one('.local-toc nav a')
    for path in (ROOT / 'docs/assets').glob('*.mjs'):
        assert not re.search(r'__[A-Z][A-Z_]+__', path.read_text())
