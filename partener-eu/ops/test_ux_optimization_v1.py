#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu'/'web'
INDEX=WEB/'index.html'
CSS=WEB/'ux-optimization-v1.css'
JS=WEB/'ux-optimization-v1.js'

index=INDEX.read_text(encoding='utf-8')
css=CSS.read_text(encoding='utf-8')
js=JS.read_text(encoding='utf-8')

assert 'ux-optimization-v1.css' in index
assert 'ux-optimization-v1.js' in index
assert index.index('ux-optimization-v1.css') > index.index('ask-partener-v2.css')
assert index.index('ux-optimization-v1.js') > index.index('public-product-v3.js')

for token in (
    '--ux-tap:44px',
    ':focus-visible',
    '@media(max-width:900px)',
    '.navlinks{display:flex!important',
    '@media(prefers-reduced-motion:reduce)',
):
    assert token in css, token

for token in (
    "OPEN:'Deschis'",
    "PUBLIC_CONSULTATION:'În consultare'",
    "new MutationObserver(schedule)",
    "link.textContent='Sari la conținut'",
    "aria-label",
    "aria-live",
    "data-ux-keyboard",
    "event.key!=='Enter'&&event.key!==' '",
):
    assert token in js, token

for forbidden in ('window.PARTENER_DATA=', 'fetch(', 'localStorage.setItem', 'sessionStorage.setItem'):
    assert forbidden not in js, forbidden

assert 'id="boot-fallback"' in index
assert '<script src="app.js?' in index
print('PARTENER.EU UX optimization v1 contract: PASS')
