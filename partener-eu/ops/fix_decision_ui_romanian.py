#!/usr/bin/env python3
"""Idempotently localize the decision UI and prevent raw fact leakage."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "web" / "decision-intelligence-v2.js"
text = PATH.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        "const dateText=v=>{if(!v)return 'Data neconfirmată';try{return new Date(v).toLocaleDateString('ro-RO',{day:'numeric',month:'short',year:'numeric'})}catch{return String(v)}};",
        "const dateText=v=>{if(!v)return 'Data neconfirmată';try{const d=new Date(v);return Number.isNaN(d.getTime())?String(v):d.toLocaleDateString('ro-RO',{day:'numeric',month:'long',year:'numeric'})}catch{return String(v)}};\nconst eventLabels={DEADLINE_EXTENDED:'TERMEN PRELUNGIT',CALL_OPENED:'APEL DESCHIS',GUIDE_MODIFIED:'GHID MODIFICAT',GUIDE_UPDATED_AFTER_CONSULTATION:'GHID ACTUALIZAT',GUIDE_PUBLISHED:'GHID PUBLICAT',CONSULTATION_OPENED:'CONSULTARE DESCHISĂ',CALL_CLOSED:'APEL ÎNCHIS',RESULTS_PUBLISHED:'REZULTATE PUBLICATE',OFFICIAL_UPDATE:'ACTUALIZARE OFICIALĂ'};\nconst eventLabel=v=>eventLabels[String(v||'').toUpperCase()]||String(v||'ACTUALIZARE').replaceAll('_',' ');\nconst statusLabels={OPEN:'DESCHIS',EXPECTED:'ÎN PREGĂTIRE',PUBLIC_CONSULTATION:'ÎN CONSULTARE',REVIEW:'ÎN VERIFICARE',CLOSED:'ÎNCHIS',CANCELLED:'ANULAT',SUSPENDED:'SUSPENDAT'};\nconst statusText=v=>statusLabels[String(v||'').toUpperCase()]||String(v||'ÎN VERIFICARE');\nconst fundingFact=d=>d.quickFacts?.find(x=>x.label==='Grant'||x.label==='Valoare proiect'||x.label==='Finanțare')||{label:'Finanțare',value:'Neconfirmat',confidence:'UNKNOWN'};\nconst displayFact=f=>{const v=String(f?.value??'Neconfirmat');if(/^20\\d{2}-\\d{2}-\\d{2}T/.test(v)){try{return new Date(v).toLocaleString('ro-RO',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})}catch{}}return v};",
        "localized helpers",
    ),
    (
        "function dossierCard(d){const deadline=fact(d,'Termen'),grant=fact(d,'Grant');return `<article class=\"diDossierCard\"",
        "function dossierCard(d){const deadline=fact(d,'Termen'),grant=fundingFact(d);return `<article class=\"diDossierCard\"",
        "funding fact selector card",
    ),
    (
        "<div><small>Termen</small><b>${esc(deadline.value)}</b></div><div><small>Grant</small><b>${esc(grant.value)}</b></div>",
        "<div><small>Termen</small><b>${esc(displayFact(deadline))}</b></div><div><small>${esc(grant.label||'Finanțare')}</small><b>${esc(displayFact(grant))}</b></div>",
        "compact facts card",
    ),
    (
        "${esc(String(n.kind||'UPDATE').replaceAll('_',' '))}",
        "${esc(eventLabel(n.kind))}",
        "news event label",
    ),
    (
        "eyebrow.textContent='Funding intelligence · decizie și acțiune';",
        "eyebrow.textContent='Finanțări europene · decizie și acțiune';",
        "home eyebrow",
    ),
    (
        "function dossierRow(d){const deadline=fact(d,'Termen'),grant=fact(d,'Grant');return `<article class=\"diResultDossier\"",
        "function dossierRow(d){const deadline=fact(d,'Termen'),grant=fundingFact(d);return `<article class=\"diResultDossier\"",
        "funding fact selector row",
    ),
    (
        "<span>Termen: <b>${esc(deadline.value)}</b></span><span>Grant: <b>${esc(grant.value)}</b></span>",
        "<span>Termen: <b>${esc(displayFact(deadline))}</b></span><span>${esc(grant.label||'Finanțare')}: <b>${esc(displayFact(grant))}</b></span>",
        "compact result facts",
    ),
    (
        "<div class=\"eyebrow\">Decision usefulness > content volume</div>",
        "<div class=\"eyebrow\">Utilitate pentru decizie &gt; volum de conținut</div>",
        "hub eyebrow",
    ),
    (
        "<span>${P.summary.openCount} OPEN</span>",
        "<span>${P.summary.openCount} deschise</span>",
        "hub open metric",
    ),
    (
        "${['OPEN','EXPECTED','PUBLIC_CONSULTATION','REVIEW','CLOSED'].map(x=>`<option ${state.status===x?'selected':''}>${x}</option>`).join('')}",
        "${['OPEN','EXPECTED','PUBLIC_CONSULTATION','REVIEW','CLOSED'].map(x=>`<option value=\"${x}\" ${state.status===x?'selected':''}>${statusText(x)}</option>`).join('')}",
        "status filter labels",
    ),
    (
        "${esc(String(n.kind||'UPDATE').replaceAll('_',' '))}",
        "${esc(eventLabel(n.kind))}",
        "article event label",
    ),
    (
        "'public țintă de verificat'",
        "'eligibilitate de verificat'",
        "result audience wording",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"Decision UI {label}: already fixed")
        continue
    if old not in text:
        # Some replacements intentionally target multiple identical fragments;
        # they may already have been replaced by an earlier pass.
        if label in {"news event label", "article event label"} and "eventLabel(n.kind)" in text:
            print(f"Decision UI {label}: already fixed")
            continue
        raise SystemExit(f"Expected decision UI pattern missing for {label}; refusing blind edit")
    text = text.replace(old, new, 1)
    changed = True
    print(f"Decision UI {label}: fixed")

if changed:
    PATH.write_text(text, encoding="utf-8")
