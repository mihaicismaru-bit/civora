#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'partener-eu' / 'web'
index = (WEB / 'index.html').read_text(encoding='utf-8')
js = (WEB / 'ask-partener-v2.js').read_text(encoding='utf-8')
css = (WEB / 'ask-partener-v2.css').read_text(encoding='utf-8')

assert 'ask-partener-v2.css' in index
assert 'ask-partener-v2.js' in index
assert index.index('decision-products.js') < index.index('ask-partener-v2.js')
assert 'window.PARTENER_DECISION_PRODUCTS' in js
assert 'P.dossiers.map' in js
assert 'quality?.completeness' in js
assert 'Nu am găsit încă o potrivire suficient de sigură' in js
assert 'Nu îți afișăm apeluri aleatorii' in js
assert 'Încă neconfirmat' in js
assert 'Deschide dosarul verificat' in js
assert 'window.PARTENER_DATA.calls' not in js
assert 'D.calls.slice(0,2)' not in js
assert 'fetch(' not in js and 'XMLHttpRequest' not in js
assert '.askV2Grid' in css and '@media(max-width:760px)' in css
print('Ask PARTENER v2 canonical dossier-search contract: PASS')
