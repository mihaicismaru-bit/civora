#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu'/'web'
INDEX=WEB/'index.html'
JS=WEB/'home-concierge-vnext.js'
CSS=WEB/'home-concierge-vnext.css'

index=INDEX.read_text(encoding='utf-8')
js=JS.read_text(encoding='utf-8')
css=CSS.read_text(encoding='utf-8')

assert 'home-concierge-vnext.css' in index
assert 'home-concierge-vnext.js' in index
assert index.index('home-concierge-vnext.css') > index.index('ux-card-scannability-v4.css')
assert index.index('home-concierge-vnext.js') > index.index('ux-mobile-density-v3.js')

# Superseded homepage renderers must not remain on the active boot path.
for retired in (
    'daily-brief.js', 'daily-brief.css',
    'home-novice-v1.js', 'home-novice-v1.css',
    'home-go-to-v2.js', 'home-go-to-v2.css',
):
    assert retired not in index, retired

for marker in (
    'Ce vrei să finanțezi?',
    'Descrie investiția în câteva cuvinte',
    'PARTENER.EU · finanțări explicate simplu',
):
    assert marker in index, marker

for token in (
    "currentStatus(d)!=='OPEN'",
    "publicationState||''",
    "confirmed(d,'Status')",
    "confirmed(d,'Termen')",
    "parsed.getTime()>=Date.now()",
    "String(d.publicationState||'').toUpperCase()==='PUBLISHABLE'",
    'Deschise acum',
    'Se pregătesc',
    'Ce s-a schimbat',
    'De ce poți avea încredere în PARTENER.EU',
    'Găsește finanțări',
    "['Firmă / IMM','firmă IMM']",
    "['ONG','ONG']",
    "['Primărie','primărie']",
    "['Agricultură','agricultură']",
    "['Educație','educație']",
    'window.PARTENER_DECISION_UI?.openDossier',
):
    assert token in js, token

# The public home surface reads the canonical decision product only. It must not
# fetch, persist, infer or mutate canonical data independently.
for forbidden in (
    'fetch(', 'localStorage', 'sessionStorage',
    'window.PARTENER_DATA=', 'window.PARTENER_DECISION_PRODUCTS=',
    'Math.random(',
):
    assert forbidden not in js, forbidden

for token in (
    '.conciergeHero', '.conciergeSearch', '.conciergeSection',
    '.conciergeGrid', '.conciergeNews', '.conciergeTrust',
    '@media(max-width:650px)',
):
    assert token in css, token

assert 'id="boot-fallback"' in index
assert '<script src="app.js?' in index
print('PARTENER.EU Funding Concierge vNext static contract: PASS')
