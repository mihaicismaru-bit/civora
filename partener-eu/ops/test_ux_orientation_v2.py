#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu'/'web'
INDEX=WEB/'index.html'
CSS=WEB/'ux-orientation-v2.css'
JS=WEB/'ux-orientation-v2.js'

index=INDEX.read_text(encoding='utf-8')
css=CSS.read_text(encoding='utf-8')
js=JS.read_text(encoding='utf-8')

assert 'ux-orientation-v2.css' in index
assert 'ux-orientation-v2.js' in index
assert index.index('ux-optimization-v1.css') < index.index('ux-orientation-v2.css')
assert index.index('ux-optimization-v1.js') < index.index('ux-orientation-v2.js')

for token in (
    "label:'Profil'",
    "label:'Deschise'",
    "label:'Pregătește'",
    "label:'Schimbări'",
    "aria-label','Navigare rapidă în pagina de finanțări'",
    "scrollIntoView",
    "new IntersectionObserver",
    "EXTRA_KEYBOARD='.diNewsCard,.diNewsRow,.diResultDossier'",
    "hint.textContent='Deschide analiza →'",
):
    assert token in js, token

for token in (
    '.uxV2Rail',
    'min-height:44px',
    'position:sticky',
    '--ux-v2-header-height',
    '.uxV2Target',
):
    assert token in css, token

# V2 must improve orientation without suppressing material content or changing data.
for forbidden in (
    'display:none',
    'window.PARTENER_DATA=',
    'fetch(',
    'localStorage.setItem',
    'sessionStorage.setItem',
    '.remove()',
):
    assert forbidden not in js, forbidden

assert 'id="boot-fallback"' in index
assert '<script src="app.js?' in index
print('PARTENER.EU UX orientation v2 contract: PASS')
