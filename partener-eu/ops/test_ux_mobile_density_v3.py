#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu'/'web'
INDEX=WEB/'index.html'
CSS=WEB/'ux-mobile-density-v3.css'
JS=WEB/'ux-mobile-density-v3.js'

index=INDEX.read_text(encoding='utf-8')
css=CSS.read_text(encoding='utf-8')
js=JS.read_text(encoding='utf-8')

assert 'ux-mobile-density-v3.css' in index
assert 'ux-mobile-density-v3.js' in index
assert index.index('ux-orientation-v2.css') < index.index('ux-mobile-density-v3.css')
assert index.index('ux-orientation-v2.js') < index.index('ux-mobile-density-v3.js')

for token in (
    'const LIMIT=3',
    "key:'open'",
    "key:'prepare'",
    "key:'changes'",
    'card.hidden=collapse',
    "button.setAttribute('aria-expanded'",
    "button.setAttribute('aria-controls'",
    'Afișează încă ${extra}',
    'expanded.add(spec.key)',
    'expanded.delete(spec.key)',
):
    assert token in js, token

for token in (
    '.uxV3More',
    'min-height:44px',
    '[data-ux-v3-collapsed="1"]',
    '@media(min-width:721px)',
):
    assert token in css, token

# Disclosure is presentation state only: no data transport, persistence, deletion or reordering.
for forbidden in (
    'window.PARTENER_DATA=',
    'fetch(',
    'localStorage',
    'sessionStorage',
    'removeChild(',
    'appendChild(card',
    'insertBefore(card',
):
    assert forbidden not in js, forbidden

assert '<script src="app.js?' in index
print('PARTENER.EU UX mobile density v3 contract: PASS')
