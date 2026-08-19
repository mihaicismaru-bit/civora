#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu/web'
ui=(WEB/'public-product-v3.js').read_text(encoding='utf-8')
askui=(WEB/'ask-partener-v2.js').read_text(encoding='utf-8')
people=(WEB/'people-policy-v1.js').read_text(encoding='utf-8')
decision=(WEB/'decision-intelligence-v2.js').read_text(encoding='utf-8')
app=(WEB/'app.js').read_text(encoding='utf-8')
index=(WEB/'index.html').read_text(encoding='utf-8')


def function_chunk(source: str, name: str) -> str:
    start=source.index(f'function {name}(')
    end=source.find('\nfunction ',start+1)
    return source[start:] if end<0 else source[start:end]


# public-product-v3 owns generic public polish only; Ask has one dedicated enhancement owner.
assert "[data-r=\"changes\"]" in ui
assert 'function humanizeEvents(' in ui
assert 'function enhanceAsk(' not in ui
assert 'PARTENER_DECISION_PRODUCTS' not in ui
assert '#aq' not in ui
assert 'askV3' not in ui

# Dedicated Ask enhancement is canonical-data-only, explainable and fail-closed.
assert 'PARTENER_DECISION_PRODUCTS' in askui
assert 'P.dossiers' in askui
assert 'D.calls.slice(0,2)' not in askui
assert 'value="Am firmă din industria alimentară' not in askui
assert "placeholder='Ex.: IMM din Vâlcea" in askui
assert "x.d.status!=='CLOSED'" in askui
assert 'De ce apare:' in askui
assert 'Cine poate aplica' in askui
assert 'Încă neconfirmat' in askui
assert 'sourceEvidence' in askui
assert "kind:'OFFICIAL'" in askui
assert "kind:'PUBLIC_EVIDENCE'" in askui
assert 'Sursa oficială ↗' in askui
assert 'Evidență publică ↗' in askui
assert 'Nu este clasificată T1/T1B' in askui
assert "if(ev.kind==='OFFICIAL')" in askui
assert 'provenanceBlock(d)' in askui
assert 'Proveniență' in askui
assert 'Deschide dosarul verificat' in askui
assert 'openDossier(d.id)' in askui
assert 'openDossier(d.id,d.title)' not in askui
assert "addEventListener('keydown'" in askui
assert "e.key==='Enter'" in askui
assert 'Nu îți afișăm apeluri aleatorii' in askui

# Ask routes directly through the decision-product UI contract; no timed DOM choreography.
assert 'PARTENER_DECISION_UI' in askui
assert 'PARTENER_DECISION_UI' in decision
assert "openHub:(tab='news')" in decision
assert 'openDossier:id=>' in decision
assert 'byDossier.has(id)' in decision
open_hub_chunk=function_chunk(askui,'openHub')
open_dossier_chunk=function_chunk(askui,'openDossier')
assert "ui.openHub('dossiers')" in open_hub_chunk
assert 'ui.openDossier(id)' in open_dossier_chunk
assert 'setTimeout' not in open_hub_chunk
assert 'setTimeout' not in open_dossier_chunk
assert '[data-decisionnav]' not in open_hub_chunk
assert '[data-decisionnav]' not in open_dossier_chunk
assert '[data-di-dossier' not in open_dossier_chunk

# Full articles/dossiers must never upgrade weak or missing provenance to official/T1.
source_meta_chunk=function_chunk(decision,'sourceMeta')
source_list_chunk=function_chunk(decision,'sourceList')
assert "tier||'tier neclasificat'" in source_meta_chunk
assert "official=/^T1(?:B)?" in source_meta_chunk
assert "genericOfficial=/^sursă oficială$/i" in source_meta_chunk
assert "official?'Sursă oficială':'Evidență publică'" in source_meta_chunk
assert "sourceAvailable===false?'sursa indisponibilă':'sursă disponibilă'" in source_list_chunk
assert 'nu este clasificată T1/T1B' in source_list_chunk
assert "s.label||'Sursă oficială'" not in source_list_chunk
assert "s.tier||'T1'" not in source_list_chunk

# Baseline public shell must remain useful and fail-closed without progressive enhancements.
nav_chunk=function_chunk(app,'nav')
ask_chunk=function_chunk(app,'ask')
answer_chunk=function_chunk(app,'answer')
assert 'data-r="changes"' not in nav_chunk
assert 'value="Am firmă din industria alimentară' not in ask_chunk
assert 'autocomplete="off"' in ask_chunk
assert 'placeholder="Ex.: IMM din Vâlcea' in ask_chunk
assert 'D.calls.slice(0,2)' not in answer_chunk
assert 'Nu afișăm apeluri aleatoriu' in answer_chunk
assert 'De ce apare:' in answer_chunk
assert 'Eligibilitate cunoscută:' in answer_chunk
assert 'Vezi dosarul' in answer_chunk

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
assert 'ask-partener-v2.js' in index
assert 'public-product-v3.js' in index
assert 'public-product-v3.css' in index
print('PARTENER.EU public product v3: PASS')
