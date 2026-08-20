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

# Dossier/article source rendering must use the same fail-closed provenance contract.
source_chunk=function_chunk(decision,'sourceList')
assert r'^T1(?:B)?\b' in source_chunk
assert "s.tier||'T1'" not in source_chunk
assert "s.label||'Sursă oficială'" not in source_chunk
assert "tier||'tier neprecizat'" in source_chunk
assert "official?'Sursă oficială':'Evidență publică'" in source_chunk
assert "official?'sursă oficială':'evidență publică'" in source_chunk
assert r'surs[ăa]\s+oficial[ăa]' in source_chunk
assert 'sourceList(n.source?[n.source]:[])' in function_chunk(decision,'renderNews')
assert 'sourceList(d.sources)' in function_chunk(decision,'renderDossier')

# News-list fallback action must not imply an official source without T1/T1B provenance.
news_source_action_chunk=function_chunk(decision,'newsSourceAction')
news_row_chunk=function_chunk(decision,'newsRow')
assert r'^T1(?:B)?\b' in news_source_action_chunk
assert "if(!s.url)return 'Verifică proveniența înainte de a acționa.'" in news_source_action_chunk
assert "'Verifică sursa oficială atașată.'" in news_source_action_chunk
assert "'Verifică evidența publică atașată și proveniența.'" in news_source_action_chunk
assert 'n.actions?.[0]||newsSourceAction(n)' in news_row_chunk
assert "'Verifică sursa oficială.'" not in news_row_chunk

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

# "Ce spun decidenții" keeps tier-aware provenance and honors the source-intelligence policy.
assert 'officialIngested' in function_chunk(people,'isMaterial')
official_people_source_chunk=function_chunk(people,'officialSource')
primary_people_source_chunk=function_chunk(people,'primarySource')
people_source_label_chunk=function_chunk(people,'sourceLabel')
people_card_chunk=function_chunk(people,'card')
assert r'^T1(?:B)?(?:\b|_)' in official_people_source_chunk
assert 'function requiresOfficialEvidence(' in people
assert 'official||(!requiresOfficialEvidence()?rows[0]:null)||null' in primary_people_source_chunk
assert "officialSource(s)?'Sursa oficială':'Evidență publică'" in people_source_label_chunk
assert "sourceKind=officialSource(src)?'sursa oficială':'evidența publică'" in people_card_chunk
assert "label=src?sourceLabel(src):'Proveniență neconfirmată'" in people_card_chunk
assert 'deschide ${esc(sourceKind)}' in people_card_chunk
assert 'Vezi semnalul și ${esc(sourceKind)} ↗' in people_card_chunk
assert "x.institution||'Sursă oficială'" not in people_card_chunk
assert "x.person||x.institution||'Sursă oficială'" not in people_card_chunk

# Decision-maker cards must expose unknown context explicitly instead of generic filler.
affected_people_chunk=function_chunk(people,'affectedText')
watch_people_chunk=function_chunk(people,'watchText')
assert 'beneficiarii și proiectele din aria semnalului' not in affected_people_chunk
assert 'Nu este încă suficient structurată în datele verificate.' in affected_people_chunk
assert 'Ghidul, ordinul, corrigendumul, calendarul sau alt act oficial' not in watch_people_chunk
assert 'Faptul oficial lipsă nu este încă identificat suficient de precis în datele verificate.' in watch_people_chunk
assert 'affectedText(x)' in people_card_chunk
assert 'watchText(x)' in people_card_chunk

# Decision-maker promo is fresh and disappears instead of showing an empty/filler module.
assert 'function freshnessDays(' in people
fresh_chunk=function_chunk(people,'isFresh')
assert 'Date.now()' in fresh_chunk
assert 'age>=-1&&age<=freshnessDays()' in fresh_chunk
material_people_chunk=function_chunk(people,'isMaterial')
assert '!x?.officialIngested||!isFresh(x)' in material_people_chunk
inject_people_chunk=function_chunk(people,'inject')
assert 'hideWhenNoFreshOfficialSignals' in inject_people_chunk
assert 'if(!chosen.length' in inject_people_chunk
assert 'removePromo();return' in inject_people_chunk
assert 'Ce fapt oficial lipsește:' in people_card_chunk
assert 'informații proaspete și suficient de concrete' in people

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
assert 'ask-partener-v2.js' in index
assert 'public-product-v3.js' in index
assert 'public-product-v3.css' in index
print('PARTENER.EU public product v3: PASS')
