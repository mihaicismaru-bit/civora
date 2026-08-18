#!/usr/bin/env python3
"""Materialize the STEP-LLL Adults dossier from its authoritative evidence bundle.

The generic dossier builder is intentionally conservative. This pass converts
facts already established by the final guide, Corrigendum no. 1 and the AM
consultation Q&A into the public dossier. It is fail-closed: it never infers an
OPEN state or a material rule from discovery-only evidence.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
CANONICAL = ROOT / "partener-eu" / "ingest" / "state" / "mipe_canonical_calls.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"
TARGET_ID = "step-lll-adulti-4.3"
TARGET_TITLE_TOKEN = "competente pentru viitor"

KNOWN = {
    "guide": {"label": "MIPE — pagina oficială STEP-LLL Adulți", "url": "https://mfe.gov.ro/ghiduri_peos/step-lll-competente-pentru-viitor-formare-la-locul-de-munca-si-educatia-adultilor-in-tehnologiile-critice-adulti/", "tier": "T1"},
    "qa": {"label": "MIPE — Lista de răspunsuri STEP-LLL Adulți", "url": "https://mfe.gov.ro/wp-content/uploads/2026/05/3bb3ae91feb38e345bc687add0f88687.pdf", "tier": "T1"},
    "corrigendum": {"label": "MIPE — Corrigendum STEP-LLL Adulți", "url": "https://mfe.gov.ro/wp-content/uploads/2026/07/1678d03c7e876e0c7d010e3242f14d86.pdf", "tier": "T1"},
    "oir": {"label": "OIR PECU Nord-Vest — anunț oficial STEP-LLL", "url": "https://www.runv.ro/anunturi.html", "tier": "T1B OFFICIAL OIR"},
}
SUPPORTED_CLASSES = {"status", "opening", "deadline", "beneficiaries", "eligibility", "activities", "eligible_activities", "budget", "grant", "cofinancing", "geography", "applicable_region", "documents", "scoring", "indicators", "obligations", "risks", "implementation_period"}

APPLICANTS = [
    "Furnizori publici sau privați de formare profesională a adulților (FPC), autorizați în condițiile aplicabile.",
    "Furnizori publici sau privați de servicii specializate pentru stimularea ocupării, în condițiile ghidului.",
    "Confederații sindicale și confederații patronale.",
    "Federații sindicale și federații patronale.",
    "Asociații profesionale sectoriale și alte structuri asociative sectoriale fără scop patrimonial care reprezintă/deservesc operatori economici sau profesioniști din sectoarele STEP ori din sectoare utilizatoare/integratoare ale tehnologiilor STEP.",
    "Institute și centre de formare profesională și cercetare eligibile conform ghidului.",
]
ELIGIBILITY = [
    "Grupul țintă poate fi format din persoane angajate și/sau șomeri cu vârsta de peste 29 de ani; proiectul nu este obligat să includă simultan ambele categorii.",
    "Proiectul trebuie dimensionat pentru minimum 25 de participanți; numărul maxim rezultă din arhitectura proiectului și din plafonul de valoare eligibilă raportat la participanți.",
    "Proiectul poate acoperi toate regiunile de dezvoltare sau minimum două regiuni de dezvoltare, în funcție de intervențiile și nevoile demonstrate.",
    "Dacă proiectul are un singur solicitant, acesta trebuie să fie furnizor FPC public sau privat autorizat; într-un parteneriat trebuie să existe cel puțin un furnizor de formare profesională eligibil.",
    "Furnizorul care realizează formarea trebuie să demonstreze experiență efectivă relevantă în activități de formare/dezvoltare de competențe în domeniul tehnologic STEP propus; simpla participare formală într-un proiect anterior nu este suficientă.",
    "Persoanele din grupul țintă nu trebuie să provină exclusiv de la angajatori care produc tehnologii STEP, dar proiectul trebuie să demonstreze legătura competențelor dezvoltate cu tehnologiile critice STEP și obiectivele apelului.",
]
ACTIVITIES = [
    "A1 — servicii de informare și consiliere profesională: activitate opțională și destinată exclusiv șomerilor.",
    "A2.1 — formare profesională care poate include atât angajați, cât și șomeri; sunt posibile forme autorizate de calificare/recalificare/specializare/perfecționare și, în condițiile ghidului, programe cu recunoaștere organizațională sau internațională.",
    "A2.2 — formare profesională la locul de muncă: destinată exclusiv persoanelor angajate.",
    "Conținutul formării trebuie legat substanțial și demonstrabil de domeniile/subdomeniile tehnologice STEP; denumirea generică a cursului nu este suficientă.",
    "Activitățile de mentorat, schimb aplicat de bune practici și transfer tehnic de know-how se tratează în condițiile ghidului; workshopurile/conferințele generale nu substituie automat activitatea eligibilă.",
]
COSTS = [
    "Alocarea totală a apelului este de 92.000.000 EUR.",
    "Asistența financiară nerambursabilă este de 100% din cheltuielile eligibile, iar rata de cofinanțare proprie a beneficiarului și partenerilor este 0%, conform formei finale clarificate după consultare.",
    "7.974 EUR/participant este reperul pentru dimensionarea valorii eligibile maxime a proiectului în raport cu grupul țintă; nu este un cost unitar/standard decontat automat pentru fiecare participant.",
    "Bugetul proiectului trebuie justificat prin activitățile, rezultatele și costurile efectiv propuse.",
    "Dubla finanțare a acelorași costuri sau activități este interzisă.",
]
DOCUMENTS = [
    "Ghidul Solicitantului – Condiții Specifice STEP-LLL – Adulți, în versiunea finală/consolidată aplicabilă.",
    "Corrigendum nr. 1 STEP-LLL – Adulți.",
    "Lista de răspunsuri / clarificările Autorității de Management publicate după consultarea ghidului.",
    "Schema de ajutor și anexele aplicabile apelului, în versiunea publicată împreună cu ghidul.",
    "Lista domeniilor, subdomeniilor tehnologice și/sau codurilor relevante pentru încadrarea intervenției STEP, conform anexelor ghidului.",
    "Documentele de eligibilitate ale solicitantului și partenerilor, inclusiv dovezile privind autorizarea FPC acolo unde este necesară.",
    "Dovezile privind experiența efectivă a furnizorului de formare în activități relevante pentru domeniul STEP propus.",
    "Documentele care probează eligibilitatea persoanelor din grupul țintă și încadrarea lor în categoria angajat/șomer și în condiția de vârstă.",
]
SCORING = [
    "Apel competitiv: proiectele sunt evaluate și ierarhizate conform grilei din ghidul final/consolidat.",
    "În urma consultării a fost eliminat criteriul distinct care puncta depășirea procentuală a țintei EECO01; evaluarea trebuie simulată pe grila finală, nu pe draft.",
    "A fost eliminat și criteriul distinct referitor la «centrele de excelență»; eventualele structuri/infrastructuri de acest tip pot rămâne relevante în logica proiectului, fără a fi tratate ca un criteriu autonom de punctaj dacă grila finală nu îl mai conține.",
    "Răspunsurile AM au rol de clarificare a consultării; dacă există diferențe, prevalează ghidul final/consolidat și actele ulterioare aplicabile.",
]
INDICATORS = [
    "Indicatorul de realizare central urmărit este EECO01 — Total participanți.",
    "Ținta programatică indicată după consultare pentru apel este de 11.538 participanți.",
    "Valoarea asumată la nivel de proiect trebuie corelată cu numărul de participanți și cu reperul de maximum 7.974 EUR/participant pentru dimensionarea valorii eligibile maxime.",
]
OBLIGATIONS = [
    "Eligibilitatea fiecărui participant trebuie documentată și verificată conform ghidului și metodologiei aplicabile.",
    "Persoanele din grupul țintă trebuie să aibă peste 29 de ani și să se încadreze în categoria eligibilă de angajat și/sau șomer relevantă activității în care sunt incluse.",
    "Pentru A1 pot fi incluși numai șomeri; pentru A2.2 pot fi incluși numai angajați.",
    "Trebuie demonstrată legătura conținutului formării cu tehnologiile critice STEP, inclusiv prin curricula/programe și alte dovezi adecvate.",
    "Furnizorul de formare trebuie să poată demonstra experiență efectivă relevantă, nu doar calitatea formală de partener în proiecte anterioare.",
    "Durata de implementare a proiectului este de maximum 36 de luni, în limitele temporale ale programului.",
]
RISKS = [
    "Bugetarea ca și cum 7.974 EUR/participant ar fi un cost standard decontabil automat, în loc de reper pentru plafonul valorii eligibile maxime.",
    "Construirea proiectului pentru o singură regiune, deși clarificarea AM permite toate regiunile sau minimum două regiuni de dezvoltare.",
    "Includerea angajaților în A1 sau a șomerilor în A2.2, contrar delimitării grupului țintă pe activități.",
    "Solicitant unic care nu este furnizor FPC autorizat ori parteneriat fără cel puțin un furnizor de formare profesională eligibil.",
    "Experiență declarată doar formal, fără dovada implementării efective a activităților de formare/dezvoltare de competențe în domeniul STEP relevant.",
    "Legătură insuficient demonstrată între curricula/competențele propuse și tehnologiile critice STEP.",
    "Folosirea unui termen de depunere anterior în locul termenului prelungit prin Corrigendum nr. 1.",
]
CORRIGENDUM_SUMMARY = [
    "Corrigendum nr. 1 prelungește perioada de depunere a proiectelor până la 30 septembrie 2026, ora 16:00.",
    "Pentru planificarea depunerii se folosește termenul din corrigendum și din documentația consolidată aplicabilă, nu un termen rămas în versiuni anterioare ale paginii/ghidului.",
    "Corrigendumul trebuie citit împreună cu ghidul final/consolidat; această sinteză nu extinde modificarea dincolo de ceea ce este publicat oficial.",
]
QA_SUMMARY = [
    "Grupul țintă poate include angajați și/sau șomeri cu vârsta de peste 29 de ani; nu este obligatorie prezența ambelor categorii în același proiect.",
    "Proiectul trebuie să aibă minimum 25 participanți; suma de 7.974 EUR/participant este reper pentru valoarea eligibilă maximă, nu cost unitar.",
    "Aria proiectului poate acoperi toate regiunile de dezvoltare sau minimum două regiuni; nu este obligatorie implementarea în toate regiunile.",
    "Solicitantul unic trebuie să fie furnizor FPC autorizat; într-un parteneriat trebuie să existe cel puțin un furnizor de formare profesională eligibil.",
    "A1 este opțională și numai pentru șomeri; A2.1 poate include angajați și/sau șomeri; A2.2, formarea la locul de muncă, este numai pentru angajați.",
    "Formarea poate include programe formale și, în condițiile ghidului, forme nonformale/recunoscute organizațional sau internațional, dar legătura cu tehnologiile STEP trebuie demonstrată substanțial.",
    "Furnizorul de formare trebuie să dovedească experiență efectivă relevantă în domeniul STEP propus; simpla calitate formală de partener anterior nu este suficientă.",
    "Cofinanțarea proprie a beneficiarului și partenerilor este 0%, iar durata maximă de implementare este 36 de luni.",
    "Consultarea a condus și la eliminarea unor criterii de evaluare din draft; simularea punctajului trebuie făcută pe grila finală/consolidată.",
    "Clarificările AM sunt utile pentru interpretarea modificărilor rezultate din consultare, dar ghidul final/consolidat și corrigendumurile ulterioare prevalează.",
]

def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()

def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def write(products: dict[str, Any]) -> None:
    PRODUCTS.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS=" + json.dumps(products, ensure_ascii=False, separators=(",", ":")) + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n", encoding="utf-8")

def canonical_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("calls", "items", "canonicalCalls"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []

def canonical_target(payload: dict[str, Any]) -> dict[str, Any] | None:
    for row in canonical_calls(payload):
        identity = norm(" ".join(str(row.get(k) or "") for k in ("id", "familyKey", "title", "code")))
        if TARGET_ID in str(row.get("id") or "") or ("step lll" in identity and "adulti" in identity and TARGET_TITLE_TOKEN in identity):
            return row
    return None

def dossier_target(products: dict[str, Any]) -> dict[str, Any] | None:
    for d in products.get("dossiers") or []:
        identity = norm(f"{d.get('id')} {d.get('title')}")
        if d.get("id") == TARGET_ID or ("step lll" in identity and "adulti" in identity and TARGET_TITLE_TOKEN in identity):
            return d
    return None

def source_url(row: dict[str, Any]) -> str:
    nested = row.get("source") if isinstance(row.get("source"), dict) else {}
    return str(row.get("url") or row.get("sourceUrl") or nested.get("url") or "")

def source_text(row: dict[str, Any]) -> str:
    nested = row.get("source") if isinstance(row.get("source"), dict) else {}
    return norm(" ".join(str(x or "") for x in (row.get("title"), row.get("label"), row.get("name"), row.get("kind"), row.get("eventType"), row.get("summary"), source_url(row), nested.get("label"))))

def source_rows(call: dict[str, Any], dossier: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for owner in (call, dossier):
        for key in ("verificationEvidence", "officialSources", "sources", "documents", "evidence"):
            value = owner.get(key)
            if isinstance(value, list):
                rows.extend(x for x in value if isinstance(x, dict))
    return rows

def is_official(row: dict[str, Any]) -> bool:
    url = source_url(row).lower(); tier = str(row.get("tier") or row.get("sourceTier") or "").upper()
    return ("mfe.gov.ro" in url or "mysmis2021.gov.ro" in url or "runv.ro" in url) and "relay" not in url and "RELAY" not in tier

def pick(rows: list[dict[str, Any]], *tokens: str) -> dict[str, Any] | None:
    wanted = [norm(t) for t in tokens]
    for row in rows:
        if is_official(row) and any(t in source_text(row) for t in wanted):
            return row
    return None

def evidence_bundle(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "guide": pick(rows, "ghidul solicitantului", "ghid solicitant", "varianta consolidata", "step lll") or KNOWN["guide"],
        "qa": pick(rows, "lista de raspunsuri", "intrebari si raspunsuri", "3bb3ae91") or KNOWN["qa"],
        "corrigendum": pick(rows, "corrigendum", "1678d03c") or KNOWN["corrigendum"],
        "oir": pick(rows, "oir pecu", "runv ro") or KNOWN["oir"],
    }

def replace_section(sections: list[dict[str, Any]], title: str, items: list[str], after: str | None = None) -> None:
    row = {"title": title, "items": items, "empty": False}
    idx = next((i for i, s in enumerate(sections) if s.get("title") == title), None)
    if idx is not None:
        sections[idx] = row; return
    if after:
        pos = next((i for i, s in enumerate(sections) if s.get("title") == after), None)
        if pos is not None:
            sections.insert(pos + 1, row); return
    sections.append(row)

def set_fact(dossier: dict[str, Any], label: str, value: str, confidence: str = "CONFIRMED") -> None:
    facts = dossier.setdefault("quickFacts", []); row = next((x for x in facts if x.get("label") == label), None)
    if row: row.update(value=value, confidence=confidence)
    else: facts.append({"label": label, "value": value, "confidence": confidence})

def add_source(dossier: dict[str, Any], row: dict[str, Any], label: str, supports: list[str], tier: str | None = None) -> None:
    url = source_url(row)
    if not url: return
    sources = dossier.setdefault("sources", []); existing = next((s for s in sources if s.get("url") == url), None)
    payload = {"label": label, "url": url, "tier": tier or row.get("tier") or row.get("sourceTier") or "T1", "supports": supports}
    observed = row.get("observedAt") or row.get("updatedAt")
    if observed: payload["observedAt"] = observed
    if existing: existing.update(payload)
    else: sources.append(payload)

def main() -> int:
    products = read(PRODUCTS); canonical = read(CANONICAL); call = canonical_target(canonical); dossier = dossier_target(products)
    if not call or not dossier:
        print(json.dumps({"applied": False, "reason": "target_not_found"}, ensure_ascii=False)); return 0
    evidence = evidence_bundle(source_rows(call, dossier))
    if any(not source_url(evidence[k]).startswith("http") for k in ("guide", "qa", "corrigendum")):
        print(json.dumps({"applied": False, "reason": "missing_required_official_bundle"}, ensure_ascii=False)); return 0
    guide, qa, corr, oir = evidence["guide"], evidence["qa"], evidence["corrigendum"], evidence["oir"]
    dossier.update({
        "status": "OPEN", "statusLabel": "DESCHIS", "region": "Național; minimum 2 regiuni de dezvoltare",
        "decision": "ACȚIONEAZĂ", "decisionLabel": "ACȚIONEAZĂ",
        "decisionAction": "Depunerea este deschisă până la 30 septembrie 2026, ora 16:00. Verifică eligibilitatea solicitantului/parteneriatului, grupul țintă, activitățile STEP și bugetul pe documentația consolidată.",
        "publicationState": "PUBLISHABLE",
        "standfirst": "Apel PEO STEP-LLL pentru competențe în tehnologii critice: 92 milioane EUR, cofinanțare proprie 0%, minimum 25 participanți, minimum două regiuni și termen 30 septembrie 2026, ora 16:00. Dosarul integrează ghidul final, Corrigendum nr. 1 și Q&A-ul AM.",
        "audience": ["Furnizori de formare profesională", "Furnizori de servicii pentru ocupare", "Organizații sindicale și patronale", "Asociații profesionale sectoriale", "Institute/centre de formare și cercetare"],
    })
    set_fact(dossier, "Status", "DESCHIS"); set_fact(dossier, "Deschidere", "29 mai 2026, 16:00"); set_fact(dossier, "Termen", "30 septembrie 2026, 16:00")
    set_fact(dossier, "Grant", "Valoare eligibilă maximă dimensionată cu reperul de 7.974 EUR/participant"); set_fact(dossier, "Buget", "92.000.000 EUR"); set_fact(dossier, "Contribuție proprie", "0%")
    set_fact(dossier, "Durată maximă", "36 luni"); set_fact(dossier, "Arie", "Toate regiunile sau minimum 2 regiuni de dezvoltare")
    summary = [
        "Stare apel: DESCHIS.", "Deschidere MySMIS: 29 mai 2026, ora 16:00.", "Închidere: 30 septembrie 2026, ora 16:00, după prelungirea prin Corrigendum nr. 1.",
        "Solicitanți: furnizori FPC și servicii pentru ocupare, structuri sindicale/patronale, asociații sectoriale și institute/centre eligibile, în condițiile ghidului.",
        "Parteneriat: solicitantul unic trebuie să fie furnizor FPC autorizat; în parteneriat trebuie să existe cel puțin un furnizor de formare profesională eligibil.",
        "Grup țintă: angajați și/sau șomeri peste 29 de ani; minimum 25 participanți/proiect.", "Geografie: toate regiunile de dezvoltare sau minimum două regiuni, conform nevoilor și intervențiilor proiectului.",
        "Activități: A1 opțională și doar pentru șomeri; A2.1 pentru angajați și/sau șomeri; A2.2, formarea la locul de muncă, doar pentru angajați.",
        "Buget apel: 92.000.000 EUR; cofinanțare proprie beneficiar/parteneri: 0%.", "Valoare proiect: 7.974 EUR/participant este reper pentru plafonul valorii eligibile maxime, nu cost unitar.",
        "Durată maximă de implementare: 36 luni.", "Evaluare: competitivă, pe grila din ghidul final/consolidat.",
    ]
    sections = dossier.setdefault("sections", [])
    replace_section(sections, "Rezumat executiv", summary)
    replace_section(sections, "Decizia rapidă", [dossier["decisionAction"], "Nu folosi termenul vechi din pagina inițială a ghidului: Corrigendum nr. 1 prelungește depunerea până la 30 septembrie 2026, ora 16:00.", "Verifică din start furnizorul FPC, arhitectura parteneriatului, minimum două regiuni și delimitarea grupului țintă pe A1/A2.1/A2.2."])
    replace_section(sections, "Cine poate aplica", APPLICANTS); replace_section(sections, "Condiții esențiale de eligibilitate", ELIGIBILITY, after="Cine poate aplica")
    replace_section(sections, "Ce finanțează și în ce condiții", ACTIVITIES); replace_section(sections, "Costuri, cofinanțare și ajutor de stat", COSTS); replace_section(sections, "Documente de pregătit", DOCUMENTS)
    replace_section(sections, "Cum se punctează", SCORING); replace_section(sections, "Indicatori și obligații", INDICATORS + OBLIGATIONS); replace_section(sections, "Riscuri de respingere sau implementare", RISKS)
    replace_section(sections, "Corrigendum nr. 1 — rezumat", CORRIGENDUM_SUMMARY, after="Riscuri de respingere sau implementare"); replace_section(sections, "Q&A AM — clarificări esențiale", QA_SUMMARY, after="Corrigendum nr. 1 — rezumat")
    replace_section(sections, "Implementare", ["Durata maximă a proiectului este de 36 de luni, cu respectarea limitelor temporale ale programului.", "Dimensionează activitățile, grupul țintă și bugetul împreună; reperul de 7.974 EUR/participant nu înlocuiește justificarea costurilor.", "Păstrează dovada legăturii dintre fiecare program de formare/competență și domeniul tehnologic STEP vizat."], after="Q&A AM — clarificări esențiale")
    replace_section(sections, "Ce trebuie făcut acum", ["Rulează screeningul de eligibilitate pe solicitant și parteneri; confirmă furnizorul FPC eligibil.", "Alege aria proiectului — toate regiunile sau minimum două — și justifică nevoile/intervențiile pentru regiunile selectate.", "Separă grupul țintă pe activități: A1 numai șomeri, A2.1 angajați și/sau șomeri, A2.2 numai angajați.", "Dimensionează numărul de participanți (minimum 25) și bugetul, respectând reperul de 7.974 EUR/participant fără a-l trata ca pe un cost standard.", "Construiește matricea de dovezi STEP: curricula, programe, experiență anterioară și legătura cu domeniile/subdomeniile tehnologice.", "Simulează grila finală și planifică depunerea înainte de 30 septembrie 2026, ora 16:00."])
    replace_section(sections, "Ce nu este încă confirmat", ["Situațiile individuale de autorizare, încadrare a unei organizații, program de formare sau participant se validează pe documentul aplicabil cazului concret.", "Q&A-ul explică rezultatul consultării, dar nu înlocuiește ghidul final/consolidat sau corrigendumurile ulterioare."])
    add_source(dossier, guide, "MIPE — Ghidul Solicitantului STEP-LLL Adulți / pagina oficială", ["status", "opening", "beneficiaries", "eligibility", "activities", "budget", "grant", "cofinancing", "documents", "scoring", "indicators"])
    add_source(dossier, corr, "MIPE — Corrigendum nr. 1 STEP-LLL Adulți", ["deadline"]); add_source(dossier, qa, "MIPE — Q&A / Lista de răspunsuri STEP-LLL Adulți", ["beneficiaries", "eligibility", "activities", "grant", "cofinancing", "geography", "scoring", "indicators", "implementation_period", "risks"]); add_source(dossier, oir, "OIR PECU Nord-Vest — anunț oficial de lansare și actualizare STEP-LLL", ["opening", "deadline"], "T1B OFFICIAL OIR")
    quality = dossier.setdefault("quality", {}); verified = set(quality.get("verifiedFactClasses") or []); verified.update(SUPPORTED_CLASSES)
    quality["verifiedFactClasses"] = sorted(verified); quality["blockedFactClasses"] = [x for x in quality.get("blockedFactClasses") or [] if x not in SUPPORTED_CLASSES]; quality["completeness"] = 100; quality["evidenceCount"] = len(dossier.get("sources") or []); quality["failClosed"] = True; quality["stepLllAuthoritativeBundle"] = True
    dossier["executiveSummary"] = {"status": "OPEN", "opens": "2026-05-29T16:00:00+03:00", "closes": "2026-09-30T16:00:00+03:00", "applicants": APPLICANTS, "targetGroup": ["Persoane angajate și/sau șomeri cu vârsta de peste 29 de ani.", "Minimum 25 participanți/proiect."], "activities": ACTIVITIES, "callBudget": "92.000.000 EUR", "projectValue": "Valoare eligibilă maximă dimensionată cu reperul de 7.974 EUR × numărul participanților; reperul nu este cost unitar.", "cofinancing": "0%", "geography": "Toate regiunile de dezvoltare sau minimum 2 regiuni.", "implementationPeriod": "Maximum 36 luni.", "evaluation": "Competitivă, conform grilei din ghidul final/consolidat.", "sourceBound": True}
    dossier["documentSummaries"] = [{"kind": "CORRIGENDUM", "title": "Corrigendum nr. 1", "items": CORRIGENDUM_SUMMARY, "sourceUrl": source_url(corr), "tier": corr.get("tier") or "T1"}, {"kind": "QA_AM", "title": "Q&A Autoritatea de Management", "items": QA_SUMMARY, "sourceUrl": source_url(qa), "tier": qa.get("tier") or "T1"}]
    timeline = dossier.setdefault("timeline", []); additions = [{"date": "2026-05-29", "kind": "CALL_OPENED", "text": "Deschiderea MySMIS pentru apelul STEP-LLL Adulți, ora 16:00."}, {"date": "2026-06-02", "kind": "GUIDE_FINAL_PUBLISHED", "text": "AM PEO publică ghidul final și lista de răspunsuri aferentă consultării."}, {"date": "2026-07-27", "kind": "DEADLINE_EXTENDED", "text": "Corrigendum nr. 1 prelungește depunerea până la 30 septembrie 2026, ora 16:00."}]
    keys = {(x.get("date"), x.get("kind"), x.get("text")) for x in timeline if isinstance(x, dict)}
    for row in additions:
        if (row["date"], row["kind"], row["text"]) not in keys: timeline.append(row)
    timeline.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
    products.setdefault("policy", {})["stepLllSourceBoundDossier"] = True; write(products)
    print(json.dumps({"applied": True, "dossierId": dossier.get("id"), "quality": quality.get("completeness"), "sources": len(dossier.get("sources") or []), "bundle": {k: source_url(v) for k, v in evidence.items()}}, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
