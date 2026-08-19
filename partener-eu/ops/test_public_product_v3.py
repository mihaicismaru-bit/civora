#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu/web'
ui=(WEB/'public-product-v3.js').read_text(encoding='utf-8')
people=(WEB/'people-policy-v1.js').read_text(encoding='utf-8')
decision=(WEB/'decision-intelligence-v2.js').read_text(encoding='utf-8')
app=(WEB/'app.js').read_text(encoding='utf-8')
index=(WEB/'index.html').read_text(encoding='utf-8')


def function_chunk(source: str, name: str) -> str:
    start=source.index(f'function {name}(')
    end=source.find('\nfunction ',start+1)
    return source[start:] if end<0 else source[start:end]


assert 'PARTENER_DECISION_PRODUCTS' in ui
assert 'Nu afișăm apeluri aleatoriu' in ui
assert 'D.calls.slice(0,2)' not in ui
assert "[data-r=\"changes\"]" in ui
assert 'placeholder="Ex.: Sunt IMM' in ui
assert 'value="Am firmă din industria alimentară' not in ui

# "Ce spun decidenții" belongs to the explicit decision-home projection only.
assert 'isHome()' in people
assert 'data-decision-home="1"' in people
assert "document.querySelector('.main .hero')" not in people
assert "section.dataset.decisionHome='1'" in function_chunk(decision,'enhanceHome')
assert 'class="hero"' in function_chunk(app,'home')
for route in ('explorer','calendar','ask','workspace','detail'):
    assert 'class="hero"' not in function_chunk(app,route), route
assert 'app.innerHTML=' in function_chunk(app,'render')
for view in ('renderHub','renderNews','renderDossier'):
    chunk=function_chunk(decision,view)
    assert 'main.innerHTML=' in chunk, view
    assert 'data-decision-home' not in chunk, view

assert 'document.addEventListener(\'click\'' not in people
assert 'data-peopleall' not in people
assert 'Sursa oficială' in people
assert 'public-product-v3.js' in index
assert 'public-product-v3.css' in index
print('PARTENER.EU public product v3: PASS')
