#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu/web'
ui=(WEB/'public-product-v3.js').read_text(encoding='utf-8')
people=(WEB/'people-policy-v1.js').read_text(encoding='utf-8')
index=(WEB/'index.html').read_text(encoding='utf-8')

assert 'PARTENER_DECISION_PRODUCTS' in ui
assert 'Nu afișăm apeluri aleatoriu' in ui
assert 'D.calls.slice(0,2)' not in ui
assert "[data-r=\"changes\"]" in ui
assert 'placeholder="Ex.: Sunt IMM' in ui
assert 'value="Am firmă din industria alimentară' not in ui
assert 'isHome()' in people
assert "document.querySelector('.main .hero')" in people
assert 'document.addEventListener(\'click\'' not in people
assert 'data-peopleall' not in people
assert 'Sursa oficială' in people
assert 'public-product-v3.js' in index
assert 'public-product-v3.css' in index
print('PARTENER.EU public product v3: PASS')
