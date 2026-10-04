#!/usr/bin/env python3
"""Project authoritative late-September 2026 AFIR funding signals fail-closed.

This layer covers material AFIR opportunities that are already evidenced by exact
official pages but are not yet represented as distinct public dossiers:
- DR-21, public consultation opened 18 September 2026;
- two Modernisation Fund calls for public entities, announced to open 28 September.

The layer never auto-promotes a scheduled launch to OPEN. Once a scheduled launch
or consultation window has elapsed, the dossier moves to REVIEW until a fresh
current authoritative observation explicitly confirms the next lifecycle state.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"
RO = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime.now(dt.timezone.utc).astimezone(RO)
OBSERVED_AT = "2026-10-04T08:39:43.430876+00:00"

DR21_RELEASE = "https://www.afir.ro/comunicate/consultare-publica-privind-finantarea-investitiilor-dr-21/"
DR21_DEBATE = "https://www.afir.ro/comunicare/utile/dezbatere-publica/"
ENERGY_SESSION = "https://www.afir.ro/info-la-zi/informatii-sesiune-energie-regenerabila-solicitanti-publici/"
ENERGY_AUTOCONSUM = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-producere-energie-pentru-autoconsum-beneficiari-publici/"
ENERGY_STORAGE = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-stocare-energie-beneficiari-publici/"
ENERGY_IN_PROGRESS = "https://www.afir.ro/comunicate/depunere-in-curs-a-proiectelor-in-energie-a-entitatilor-publice/"
DR12_RELEASE = "https://www.afir.ro/comunicate/170-de-milioane-euro-pentru-exploatatiile-tinerilor-fermieri/"
DR12_INFO = "https://www.afir.ro/info-la-zi/sesiune-depunere-de-proiecte-dr-12/"
DR12_NOTE = "https://www.afir.ro/info-la-zi/nota-de-indrumare-pentru-fisa-evaluare-proiect-dr-12/"
DR12_GUIDE = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-12/"

DR21_END = dt.datetime(2026, 9, 29, 23, 59, tzinfo=RO)
ENERGY_PLANNED_OPEN = dt.datetime(2026, 9, 28, 10, 0, tzinfo=RO)
ENERGY_PLANNED_CLOSE = dt.datetime(2026, 11, 20, 23, 59, tzinfo=RO)
DR12_PLANNED_OPEN = dt.datetime(2026, 10, 6, 9, 0, tzinfo=RO)
DR12_PLANNED_CLOSE = dt.datetime(2026, 12, 2, 16, 0, tzinfo=RO)


def norm(value: Any) -> str:
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(ch)
    ).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def section(title: str, items: list[str], **extra: Any) -> dict[str, Any]:
    return {"title": title, "items": items, "empty": False, **extra}


def source(label: str, url: str, supports: list[str]) -> dict[str, Any]:
    return {
        "label": label,
        "url": url,
        "tier": "T1",
        "observedAt": OBSERVED_AT,
        "supports": supports,
    }


def facts(rows: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [{"label": label, "value": value, "confidence": confidence} for label, value, confidence in rows]


def status_fact(status: str) -> str:
    return {
        "PUBLIC_CONSULTATION": "CONSULTARE PUBLICĂ",
        "UPCOMING": "ÎN PREGĂTIRE",
        "REVIEW": "ÎN VERIFICARE",
        "OPEN": "DESCHIS",
    }[status]


def dr21_dossier() -> dict[str, Any]:
    active = NOW <= DR21_END
    status = "PUBLIC_CONSULTATION" if active else "REVIEW"
    status_label = status_fact(status)
    decision_action = (
        "Analizează ghidul consultativ și transmite observații până la 29 septembrie 2026; nu trata consultarea ca sesiune de depunere."
        if active else
        "Fereastra de consultare anunțată a ajuns la termen. Reverifică pagina oficială AFIR înainte de a folosi condițiile ca formă finală sau de a presupune deschiderea unei sesiuni."
    )
    applicants = ["Fermieri care dețin o exploatație zootehnică."]
    activities = [
        "Echipamente și instalații de decontaminare, dezinfecție și dezinsecție pentru mijloace de transport, personal, suprafețe și aer.",
        "Instalații și echipamente pentru filtrul sanitar-veterinar.",
        "Garduri de protecție sau delimitare și sisteme de delimitare, izolare sau carantinare pentru animale.",
        "Sisteme pentru controlul accesului în exploatație.",
    ]
    summary = [
        f"Stare apel: {status_label}; nu este sesiune deschisă pentru depunere.",
        "Deschidere: consultarea publică a fost publicată la 18 septembrie 2026.",
        "Închidere: 29 septembrie 2026; ora-limită nu este precizată de comunicatul AFIR.",
        f"Cine poate aplica: {applicants[0]}",
        f"Activități finanțate: {activities[0]}",
        "Valoarea apelului: Neconfirmat în comunicatul de consultare.",
        "Valoarea proiectului individual: maximum 50.000 EUR/beneficiar, conform versiunii consultative.",
        "Cofinanțare / contribuție proprie: minimum 10% din costurile eligibile la intensitatea maximă de 90%.",
        "Regiune: România.",
    ]
    sources = [
        source("AFIR — consultare publică DR-21", DR21_RELEASE, ["status", "deadline", "beneficiaries", "eligibility", "activities", "grant", "cofinancing", "documents"]),
        source("AFIR — dezbatere publică DR-21", DR21_DEBATE, ["status", "deadline", "documents"]),
    ]
    return {
        "id": "afir-dr21-consultation-2026",
        "sourceType": "AFIR_CANONICAL",
        "title": "DR-21 — Investiții pentru prevenirea răspândirii epizootiilor în exploatațiile zootehnice",
        "slug": "afir-dr21-consultation-2026",
        "programme": "AFIR / Planul Strategic PAC 2023-2027",
        "code": "DR-21",
        "region": "România",
        "status": status,
        "statusLabel": status_label,
        "decision": "PREGĂTEȘTE" if active else "VERIFY",
        "decisionLabel": "PREGĂTEȘTE" if active else "VERIFICĂ STAREA",
        "decisionAction": decision_action,
        "publicationState": "PUBLISHABLE",
        "standfirst": "AFIR a publicat versiunea consultativă DR-21 pentru biosecuritatea exploatațiilor zootehnice: maximum 50.000 EUR/beneficiar, intensitate de maximum 90%; consultarea se încheie la 29 septembrie 2026.",
        "audience": applicants,
        "quickFacts": facts([
            ("Status", status_label, "CONFIRMED" if active else "FAIL_CLOSED"),
            ("Termen", "29 septembrie 2026; ora-limită neprecizată", "CONFIRMED"),
            ("Grant", "maximum 50.000 EUR/beneficiar", "CONFIRMED"),
            ("Buget", "Neconfirmat", "UNKNOWN"),
            ("Contribuție proprie", "minimum 10% la intensitatea maximă de 90%", "CONFIRMED"),
            ("Completitudine critică", "78%", "SYSTEM"),
        ]),
        "sections": [
            section("Rezumat executiv", summary, schemaVersion=1),
            section("Decizia rapidă", [decision_action, "Consultarea publică nu autorizează depunerea unei cereri de finanțare."]),
            section("Cine poate aplica", applicants, policy="GUIDE_EXPLICIT_ONLY"),
            section("Condiții esențiale de eligibilitate", ["Solicitantul trebuie să fie fermier și să dețină o exploatație zootehnică; condițiile detaliate rămân cele din ghidul consultativ și forma finală ulterioară."]),
            section("Ce finanțează și în ce condiții", activities),
            section("Costuri, cofinanțare și ajutor de stat", ["Sprijinul public prevăzut în versiunea consultativă este de maximum 50.000 EUR/beneficiar.", "Intensitatea maximă este 90% din costurile eligibile; contribuția proprie rezultată este de minimum 10%, plus costurile neeligibile.", "Bugetul total al viitorului apel nu este confirmat în comunicatul AFIR analizat."]),
            section("Documente de pregătit", ["Ghidul solicitantului DR-21 — versiunea consultativă din 17/18 septembrie 2026.", "Observații și propuneri argumentate pentru consultare."]),
            section("Cum se punctează", ["Neconfirmat pentru forma finală; nu transforma criteriile consultative într-un verdict de finanțare."]),
            section("Indicatori și obligații", ["Indicatorii și obligațiile finale se vor verifica după publicarea formei finale a ghidului și a unei eventuale sesiuni."]),
            section("Riscuri de respingere sau implementare", ["Confundarea consultării cu un apel deschis.", "Folosirea condițiilor consultative ca și cum ar fi forma finală.", "Omiterea cerințelor sanitar-veterinare și de biosecuritate aplicabile investiției." ]),
            section("Ce trebuie făcut acum", ["Verifică dacă solicitantul este fermier cu exploatație zootehnică.", "Mapează investițiile de biosecuritate pe lista consultativă de cheltuieli eligibile.", "Pregătește observații pentru AFIR până la 29 septembrie 2026.", "Monitorizează forma finală și anunțul unei sesiuni; nu depune înainte de deschiderea oficială."]),
            section("Ce nu este confirmat", ["Bugetul total al viitorului apel, punctajul final și data unei sesiuni de depunere nu sunt confirmate de comunicatul de consultare."]),
        ],
        "timeline": [
            {"date": "2026-09-18T08:50:00+03:00", "kind": "CONSULTATION_OPENED", "text": "AFIR publică consultarea DR-21."},
            {"date": "2026-09-29", "kind": "CONSULTATION_DEADLINE", "text": "Termenul comunicat pentru transmiterea observațiilor."},
        ],
        "sources": sources,
        "quality": {
            "completeness": 78,
            "depthCompleteness": 78,
            "dossierLevel": "DOSAR DE CONSULTARE",
            "verifiedFactClasses": ["status", "deadline", "beneficiaries", "eligibility", "activities", "grant", "cofinancing", "documents"],
            "blockedFactClasses": ["budget", "scoring", "open_status"],
            "evidenceCount": len(sources),
            "failClosed": True,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "applicantEvidenceAuthorized": True,
            "executiveSummaryPresent": True,
            "afirSeptember2026Coverage": True,
        },
        "updatedAt": OBSERVED_AT,
        "canonicalLinks": [row["url"] for row in sources],
        "executiveSummary": {
            "status": status,
            "opens": "2026-09-18",
            "closes": "2026-09-29; ora-limită neprecizată",
            "applicants": applicants,
            "targetGroup": [],
            "activities": activities,
            "callBudget": "Neconfirmat",
            "projectValue": "maximum 50.000 EUR/beneficiar",
            "cofinancing": "minimum 10% la intensitatea maximă de 90%",
            "region": "România",
            "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
            "sourceBound": True,
        },
        "dossierConstruction": {"autonomous": True, "depthCompleteness": 78, "level": "DOSAR DE CONSULTARE", "missing": ["budget", "scoring", "open_status"], "nextPass": "MONITOR_FINAL_GUIDE_AND_SESSION"},
    }


def energy_dossier(*, storage: bool) -> dict[str, Any]:
    before_launch = NOW < ENERGY_PLANNED_OPEN
    in_open_window = ENERGY_PLANNED_OPEN <= NOW <= ENERGY_PLANNED_CLOSE
    status = "UPCOMING" if before_launch else ("OPEN" if in_open_window else "REVIEW")
    status_label = status_fact(status)
    if storage:
        dossier_id = "afir-fm-public-storage-2026"
        title = "Fondul pentru Modernizare — stocare energie regenerabilă pentru entități publice"
        code = "FM-ENERGIE-PUBLICI-STOCARE"
        guide = ENERGY_STORAGE
        budget = "150.000.000 EUR"
        grant = "maximum 10.000.000 EUR/beneficiar; maximum 200.000 EUR/MWh de stocare instalat"
        activity = "Capacitate nouă de stocare în spatele contorului, conectată la o instalație existentă de producere a energiei din surse regenerabile, pentru autoconsum/optimizarea consumului."
        applicants = [
            "Unități administrativ-teritoriale și subdiviziuni ale acestora.",
            "Unități și subunități din sistemul național de apărare, ordine publică și siguranță națională.",
            "Unități din sistemul administrației penitenciare.",
            "Spitale finanțate integral din fonduri publice.",
            "Instituții publice definite de Legea nr. 500/2002, inclusiv entități publice subordonate sau coordonate, cu excluderile prevăzute de ghid.",
            "Culte recunoscute oficial și unități de cult eligibile conform Legii nr. 489/2006.",
            "Instituții de învățământ superior de stat.",
            "Institute, centre și stațiuni de cercetare-dezvoltare de drept public eligibile conform ghidului.",
            "Asociații de Dezvoltare Intercomunitară.",
            "Centre sociale și centre de îngrijiri paliative finanțate integral din fonduri publice.",
            "Agenția Națională pentru Sport și instituțiile subordonate.",
            "Comitetul Olimpic și Sportiv Român și instituțiile subordonate.",
        ]
    else:
        dossier_id = "afir-fm-public-autoconsum-2026"
        title = "Fondul pentru Modernizare — producere solară cu stocare pentru autoconsum, entități publice"
        code = "FM-ENERGIE-PUBLICI-AUTOCONSUM"
        guide = ENERGY_AUTOCONSUM
        budget = "500.000.000 EUR"
        grant = "maximum 10.000.000 EUR/beneficiar; maximum 900.000 EUR/MW sau 1.100.000 EUR/MW dacă proiectul include pompe de căldură"
        activity = "Noi capacități de producere a energiei electrice din surse solare, cu capacități de stocare integrate, pentru autoconsumul entităților publice."
        applicants = [
            "Unități administrativ-teritoriale și subdiviziuni ale acestora.",
            "Unități și subunități din sistemul național de apărare, ordine publică și siguranță națională.",
            "Unități din sistemul administrației penitenciare.",
            "Agenția Națională pentru Sport și instituțiile subordonate.",
            "Comitetul Olimpic și Sportiv Român și instituțiile subordonate.",
        ]

    if before_launch:
        decision = "PREGĂTEȘTE"
        decision_label = "PREGĂTEȘTE"
        decision_action = "Pregătește dosarul pentru fereastra anunțată 28 septembrie 2026, ora 10:00 — 20 noiembrie 2026, ora 23:59; apelul nu este încă OPEN."
        status_summary = "AFIR a anunțat deschiderea pentru 28 septembrie 2026, ora 10:00."
        opening_text = "28 septembrie 2026, 10:00 — programată oficial"
    elif in_open_window:
        decision = "ACȚIONEAZĂ"
        decision_label = "ACȚIONEAZĂ"
        decision_action = "Sesiunea este deschisă. Verifică ultima versiune a cererii și anexelor, apoi pregătește și depune proiectul în sistemul AFIR înainte de termen."
        status_summary = "AFIR a confirmat post-lansare că sesiunea este în derulare din 28 septembrie 2026, ora 10:00."
        opening_text = "28 septembrie 2026, 10:00 — OPEN confirmat post-lansare de AFIR"
    else:
        decision = "VERIFICĂ"
        decision_label = "VERIFICĂ STAREA"
        decision_action = "Fereastra oficială s-a încheiat. Reverifică AFIR pentru o eventuală prelungire, relansare sau rezultat; nu presupune că depunerea mai este deschisă."
        status_summary = "Fereastra anunțată 28 septembrie — 20 noiembrie 2026 a ajuns la termen."
        opening_text = "28 septembrie 2026, 10:00"

    summary = [
        f"Stare apel: {status_label}; {status_summary}",
        f"Deschidere: {opening_text}.",
        "Închidere: 20 noiembrie 2026, ora 23:59.",
        f"Cine poate aplica: {'; '.join(applicants)}",
        f"Activități finanțate: {activity}",
        f"Valoarea apelului: {budget}.",
        f"Valoarea proiectului individual: {grant}.",
        "Cofinanțare / contribuție proprie: 0% pentru cheltuielile eligibile la intensitatea de 100%; costurile neeligibile rămân în sarcina beneficiarului.",
        "Regiune: România.",
    ]
    sources = [
        source("AFIR — informații sesiune energie regenerabilă pentru solicitanți publici", ENERGY_SESSION, ["opening", "deadline", "budget", "grant", "cofinancing", "source_event"]),
        source("AFIR — depunere în curs pentru proiectele de energie ale entităților publice", ENERGY_IN_PROGRESS, ["status", "opening", "deadline", "source_event"]),
        source("AFIR — ghid și anexe energie pentru entități publice", guide, ["beneficiaries", "eligibility", "activities", "grant", "cofinancing", "documents"]),
    ]
    blocked = ["approval_probability"] if status == "OPEN" else ["open_status", "approval_probability"]
    missing = [] if status == "OPEN" else ["open_status"]
    return {
        "id": dossier_id,
        "sourceType": "AFIR_CANONICAL",
        "title": title,
        "slug": dossier_id,
        "programme": "AFIR / Fondul pentru Modernizare",
        "code": code,
        "region": "România",
        "status": status,
        "statusLabel": status_label,
        "decision": decision,
        "decisionLabel": decision_label,
        "decisionAction": decision_action,
        "publicationState": "PUBLISHABLE",
        "standfirst": f"Sesiune AFIR pentru entități publice: 28 septembrie 2026, ora 10:00 — 20 noiembrie 2026, ora 23:59. Alocare {budget}; sprijin de până la 100% din cheltuielile eligibile și maximum 10 milioane EUR/beneficiar.",
        "audience": applicants,
        "quickFacts": facts([
            ("Status", status_label, "CONFIRMED" if status in {"OPEN", "UPCOMING"} else "FAIL_CLOSED"),
            ("Deschidere", opening_text, "CONFIRMED"),
            ("Termen", "20 noiembrie 2026, 23:59", "CONFIRMED"),
            ("Grant", grant, "CONFIRMED"),
            ("Buget", budget, "CONFIRMED"),
            ("Contribuție proprie", "0% din cheltuielile eligibile la intensitatea de 100%", "CONFIRMED"),
            ("Completitudine critică", "93%", "SYSTEM"),
        ]),
        "sections": [
            section("Rezumat executiv", summary, schemaVersion=1),
            section("Decizia rapidă", [decision_action, "Folosește exclusiv ultima versiune a cererii și anexelor publicate de AFIR."]),
            section("Cine poate aplica", applicants, policy="GUIDE_EXPLICIT_ONLY"),
            section("Condiții esențiale de eligibilitate", ["Solicitantul trebuie să se încadreze exact într-una dintre categoriile prevăzute de ghidul oficial.", "Investiția trebuie să respecte condițiile tehnice, de autoconsum/stocare și regulile Fondului pentru Modernizare prevăzute în ghid și anexe."]),
            section("Ce finanțează și în ce condiții", [activity]),
            section("Costuri, cofinanțare și ajutor de stat", [f"Alocarea apelului este {budget}.", f"Sprijinul este {grant}.", "Finanțarea acoperă până la 100% din cheltuielile eligibile; costurile neeligibile rămân în sarcina beneficiarului."]),
            section("Documente de pregătit", ["Ghidul solicitantului publicat de AFIR.", "Cererea de finanțare și anexele oficiale disponibile pe pagina dedicată.", "Documentele tehnice și administrative cerute de grila oficială de verificare."]),
            section("Cum se punctează", ["AFIR precizează evaluarea în ordinea cronologică a depunerii; criteriile și grila aplicabilă se verifică în ghid și anexele oficiale. Nu transformăm ordinea depunerii într-o probabilitate de aprobare."]),
            section("Indicatori și obligații", ["Capacitatea instalată, autoconsumul/stocarea și celelalte rezultate se dimensionează și se probează conform ghidului și documentației tehnice aplicabile."]),
            section("Riscuri de respingere sau implementare", ["Folosirea unei versiuni vechi a cererii sau anexelor.", "Încadrarea greșită a solicitantului ori a parametrilor tehnici în plafonul de sprijin.", "Depunerea după expirarea ferestrei oficiale sau fără documentele obligatorii."]),
            section("Ce trebuie făcut acum", ["Confirmă categoria de solicitant și dreptul de a aplica.", "Închide configurația tehnică și bugetul în limitele ghidului.", "Verifică ultima versiune a cererii și anexelor.", "Depune înainte de 20 noiembrie 2026, ora 23:59, cât timp sesiunea rămâne deschisă."] if status == "OPEN" else ["Confirmă categoria de solicitant și dreptul de a aplica.", "Închide configurația tehnică și bugetul în limitele ghidului.", "Monitorizează starea oficială AFIR înainte de orice depunere."]),
            section("Ce nu este confirmat", ["Probabilitatea de aprobare nu poate fi dedusă din statutul OPEN, ordinea depunerii sau completitudinea dosarului."]),
        ],
        "timeline": [
            {"date": "2026-09-22T15:50:00+03:00", "kind": "SESSION_CONFIRMED_UPCOMING", "text": "AFIR reconfirmă perioada și alocarea sesiunii pentru entități publice."},
            {"date": "2026-09-28T10:00:00+03:00", "kind": "CALL_OPENED", "text": "Începe fereastra oficială de depunere."},
            {"date": "2026-09-29T10:15:00+03:00", "kind": "OPEN_CONFIRMED", "text": "AFIR confirmă post-lansare că sesiunea este în derulare."},
            {"date": "2026-11-20T23:59:00+02:00", "kind": "ANNOUNCED_DEADLINE", "text": "Termenul anunțat de AFIR."},
        ],
        "sources": sources,
        "quality": {
            "completeness": 93,
            "depthCompleteness": 93,
            "dossierLevel": "DOSAR DE ACȚIUNE" if status == "OPEN" else "DOSAR DE PREGĂTIRE",
            "verifiedFactClasses": ["status", "opening", "deadline", "beneficiaries", "eligibility", "activities", "budget", "grant", "cofinancing", "documents"],
            "blockedFactClasses": blocked,
            "evidenceCount": len(sources),
            "failClosed": True,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "applicantEvidenceAuthorized": True,
            "executiveSummaryPresent": True,
            "afirSeptember2026Coverage": True,
            "openStatusSourceBound": status == "OPEN",
        },
        "updatedAt": OBSERVED_AT,
        "canonicalLinks": [row["url"] for row in sources],
        "executiveSummary": {
            "status": status,
            "opens": "2026-09-28T10:00:00+03:00",
            "closes": "2026-11-20T23:59:00+02:00",
            "applicants": applicants,
            "targetGroup": [],
            "activities": [activity],
            "callBudget": budget,
            "projectValue": grant,
            "cofinancing": "0% din cheltuielile eligibile la intensitatea de 100%",
            "region": "România",
            "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
            "sourceBound": True,
        },
        "dossierConstruction": {"autonomous": True, "depthCompleteness": 93, "level": "DOSAR DE ACȚIUNE" if status == "OPEN" else "DOSAR DE PREGĂTIRE", "missing": missing, "nextPass": "MONITOR_LIFECYCLE" if status == "OPEN" else "CONFIRM_LIFECYCLE"},
    }


def dr12_dossier() -> dict[str, Any]:
    before_launch = NOW < DR12_PLANNED_OPEN
    status = "UPCOMING" if before_launch else "REVIEW"
    status_label = status_fact(status)
    applicants = [
        "Fermieri șefi ai exploatației, de cel mult 40 de ani la depunerea cererii, în condițiile ghidului.",
        "Fermieri care au beneficiat de sprijin prin submăsura 6.1 PNDR, indiferent de vârsta la depunerea cererii, în condițiile ghidului.",
        "Fermieri cu vârsta de cel mult 45 de ani la depunerea cererii, în condițiile ghidului.",
    ]
    activities = [
        "Investiții pentru consolidarea exploatațiilor agricole ale categoriilor eligibile.",
        "Condiționare și depozitare dimensionate la capacitatea de producție a fermei.",
        "Înființarea, extinderea și/sau modernizarea plantațiilor pomicole.",
        "Procesare la nivelul fermei ca activitate secundară investiției principale, în condițiile ghidului.",
        "Utilaje și echipamente agricole eligibile conform documentației oficiale.",
    ]
    decision_action = (
        "Sesiunea începe la 6 octombrie 2026, ora 09:00. Finalizează eligibilitatea, punctajul, bugetul și anexele, dar nu depune înainte de deschiderea oficială."
        if before_launch else
        "Momentul programat pentru lansare a sosit. Reverifică sursa oficială AFIR înainte de a trata sesiunea ca OPEN."
    )
    sources = [
        source("AFIR — 170 milioane EUR pentru exploatațiile tinerilor fermieri", DR12_RELEASE, ["status", "opening", "deadline", "beneficiaries", "activities", "budget", "grant", "cofinancing", "scoring"]),
        source("AFIR — sesiune depunere proiecte DR-12", DR12_INFO, ["status", "opening", "deadline", "source_event"]),
        source("AFIR — notă de îndrumare pentru fișa E1.2 DR-12", DR12_NOTE, ["documents", "eligibility", "clarification"]),
        source("AFIR — detalii și anexe DR-12", DR12_GUIDE, ["beneficiaries", "eligibility", "activities", "documents"]),
    ]
    return {
        "id": "afir-dr12-2026",
        "sourceType": "AFIR_CANONICAL",
        "title": "DR-12 — Investiții în consolidarea exploatațiilor tinerilor fermieri instalați și a fermierilor cu vârsta de până la 45 de ani",
        "slug": "afir-dr12-2026",
        "programme": "AFIR / Planul Strategic PAC 2023-2027",
        "code": "DR-12",
        "region": "România",
        "status": status,
        "statusLabel": status_label,
        "decision": "PREGĂTEȘTE" if before_launch else "VERIFICĂ",
        "decisionLabel": "PREGĂTEȘTE" if before_launch else "VERIFICĂ STAREA",
        "decisionAction": decision_action,
        "publicationState": "PUBLISHABLE",
        "standfirst": "AFIR a anunțat sesiunea DR-12 pentru 6 octombrie 2026, ora 09:00 — 2 decembrie 2026, ora 16:00, cu o alocare totală de 169.589.647 EUR și sprijin de până la 200.000 EUR/proiect.",
        "audience": applicants,
        "quickFacts": facts([
            ("Status", status_label, "CONFIRMED" if before_launch else "FAIL_CLOSED"),
            ("Deschidere", "6 octombrie 2026, 09:00", "CONFIRMED"),
            ("Termen", "2 decembrie 2026, 16:00", "CONFIRMED"),
            ("Grant", "maximum 200.000 EUR/proiect", "CONFIRMED"),
            ("Buget", "169.589.647 EUR", "CONFIRMED"),
            ("Intensitate maximă", "80% pentru tinerii fermieri de până la 40 de ani; 65% pentru celelalte categorii eligibile", "CONFIRMED"),
            ("Completitudine critică", "86%", "SYSTEM"),
        ]),
        "sections": [
            section("Rezumat executiv", [
                f"Stare apel: {status_label}.",
                "Deschidere: 6 octombrie 2026, ora 09:00.",
                "Închidere: 2 decembrie 2026, ora 16:00.",
                f"Cine poate aplica: {'; '.join(applicants)}",
                f"Activități finanțate: {activities[0]}",
                "Valoarea apelului: 169.589.647 EUR, împărțită în două componente egale de câte 84.794.823,50 EUR.",
                "Valoarea proiectului individual: maximum 200.000 EUR/proiect.",
                "Intensitate maximă: 80% pentru tinerii fermieri de până la 40 de ani și 65% pentru celelalte categorii eligibile.",
                "Regiune: România.",
            ], schemaVersion=1),
            section("Decizia rapidă", [decision_action, "Prima etapă are prag de calitate de 80 puncte; a doua etapă are prag de 45 puncte."]),
            section("Cine poate aplica", applicants, policy="GUIDE_EXPLICIT_ONLY"),
            section("Condiții esențiale de eligibilitate", ["Solicitantul și exploatația trebuie să respecte integral condițiile Ghidului DR-12.", "Nota AFIR din 2 octombrie 2026 precizează că punctul 3.7 din fișa E1.2 privind ponderea achizițiilor simple într-un proiect complex nu este aplicabil și se marchează «NU ESTE CAZUL»."]),
            section("Ce finanțează și în ce condiții", activities),
            section("Costuri, cofinanțare și ajutor de stat", ["Alocarea totală este 169.589.647 EUR.", "Sprijinul public poate ajunge la maximum 200.000 EUR/proiect.", "Intensitatea maximă este 80% pentru tinerii fermieri de până la 40 de ani și 65% pentru celelalte categorii eligibile.", "AFIR precizează că nu există plafoane diferențiate ale sprijinului public pe proiect în funcție de tipologia simplă/complexă."]),
            section("Documente de pregătit", ["Ghidul solicitantului DR-12 și anexele oficiale.", "Fișa de evaluare E1.2, aplicată conform notei de îndrumare AFIR din 2 octombrie 2026.", "Documentele privind solicitantul, exploatația, investiția, bugetul și cofinanțarea cerute de ghid."]),
            section("Cum se punctează", ["Prag minim 80 puncte în etapa 6 octombrie — 5 noiembrie 2026.", "Prag minim 45 puncte în etapa 6 noiembrie — 2 decembrie 2026."]),
            section("Indicatori și obligații", ["Indicatorii și obligațiile contractuale se verifică în Ghidul DR-12 și anexele aplicabile proiectului concret."]),
            section("Riscuri de respingere sau implementare", ["Punctaj sub pragul etapei aplicabile.", "Încadrarea greșită a solicitantului într-o categorie eligibilă.", "Aplicarea eronată a punctului 3.7 din fișa E1.2 în contradicție cu nota AFIR din 2 octombrie.", "Buget sau investiții care nu respectă limitele și condițiile ghidului."]),
            section("Ce trebuie făcut acum", ["Confirmă categoria de solicitant și condițiile exploatației.", "Simulează punctajul pentru etapa de 80 puncte.", "Închide bugetul, cofinanțarea și anexele.", "Folosește nota E1.2 din 2 octombrie pentru verificarea proiectului.", "Reconfirmă OPEN în AFIR la 6 octombrie înainte de depunere."]),
            section("Ce nu este confirmat", ["Statusul OPEN înainte de 6 octombrie 2026, ora 09:00 nu poate fi dedus din calendar; după acel moment este necesar readback oficial curent."]),
        ],
        "timeline": [
            {"date": "2026-10-01", "kind": "SESSION_ANNOUNCED", "text": "AFIR publică perioada, alocarea și principalele condiții DR-12."},
            {"date": "2026-10-02", "kind": "CLARIFICATION", "text": "AFIR publică nota de îndrumare pentru fișa E1.2."},
            {"date": "2026-10-06T09:00:00+03:00", "kind": "PLANNED_OPEN", "text": "Momentul de deschidere anunțat pentru sesiunea DR-12."},
            {"date": "2026-12-02T16:00:00+02:00", "kind": "ANNOUNCED_DEADLINE", "text": "Termenul anunțat pentru sesiunea DR-12."},
        ],
        "sources": sources,
        "quality": {
            "completeness": 86,
            "depthCompleteness": 86,
            "dossierLevel": "DOSAR DE PREGĂTIRE",
            "verifiedFactClasses": ["status", "opening", "deadline", "beneficiaries", "activities", "budget", "grant", "cofinancing", "scoring", "documents", "clarification"],
            "blockedFactClasses": ["open_status", "approval_probability"],
            "evidenceCount": len(sources),
            "failClosed": True,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "applicantEvidenceAuthorized": True,
            "executiveSummaryPresent": True,
            "afirSeptember2026Coverage": True,
        },
        "updatedAt": OBSERVED_AT,
        "canonicalLinks": [row["url"] for row in sources],
        "executiveSummary": {
            "status": status,
            "opens": "2026-10-06T09:00:00+03:00",
            "closes": "2026-12-02T16:00:00+02:00",
            "applicants": applicants,
            "targetGroup": [],
            "activities": activities,
            "callBudget": "169.589.647 EUR",
            "projectValue": "maximum 200.000 EUR/proiect",
            "cofinancing": "intensitate maximă 80% pentru tinerii fermieri de până la 40 de ani; 65% pentru celelalte categorii eligibile",
            "region": "România",
            "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
            "sourceBound": True,
        },
        "dossierConstruction": {"autonomous": True, "depthCompleteness": 86, "level": "DOSAR DE PREGĂTIRE", "missing": ["open_status"], "nextPass": "CONFIRM_LIVE_OPENING_AFTER_2026-10-06T09:00+03:00"},
    }


def news_items() -> list[dict[str, Any]]:
    return [
        {
            "id": "news-afir-dr21-consultation-2026-09-18",
            "kind": "CONSULTATION_OPENED",
            "programme": "AFIR / PS PAC 2023-2027",
            "date": "2026-09-18T08:50:00+03:00",
            "headline": "DR-21: consultare pentru investiții de biosecuritate în exploatațiile zootehnice",
            "standfirst": "AFIR a publicat în consultare DR-21, cu maximum 50.000 EUR/beneficiar și intensitate de maximum 90%; observațiile sunt primite până la 29 septembrie 2026.",
            "meaning": "Este o fereastră de pregătire și feedback, nu o sesiune deschisă pentru depunere.",
            "audience": ["fermieri cu exploatații zootehnice"],
            "confirmed": ["Consultare până la 29 septembrie 2026.", "Maximum 50.000 EUR/beneficiar.", "Intensitate de maximum 90%."],
            "notConfirmed": ["Bugetul total și data unei sesiuni de depunere nu sunt confirmate de comunicatul de consultare."],
            "actions": ["Analizează ghidul consultativ.", "Transmite observații.", "Monitorizează forma finală."],
            "dossierId": "afir-dr21-consultation-2026",
            "source": {"label": "AFIR — consultare publică DR-21", "url": DR21_RELEASE, "tier": "T1"},
            "utilityScore": 94,
        },
        {
            "id": "news-afir-energy-public-open-2026-09-29",
            "kind": "CALL_OPENED",
            "programme": "AFIR / Fondul pentru Modernizare",
            "date": "2026-09-29T10:15:00+03:00",
            "headline": "AFIR confirmă că apelurile de energie pentru entități publice sunt în derulare",
            "standfirst": "AFIR confirmă post-lansare că depunerea pentru producere solară cu stocare și pentru stocare este în curs din 28 septembrie 2026, ora 10:00, până la 20 noiembrie 2026, ora 23:59.",
            "meaning": "Apelurile sunt OPEN pe dovadă autoritativă post-lansare; solicitanții eligibili pot trece de la pregătire la depunere.",
            "audience": ["entități publice eligibile conform ghidurilor AFIR"],
            "confirmed": ["OPEN confirmat post-lansare de AFIR.", "Termen: 20 noiembrie 2026, 23:59.", "Alocări: 500 milioane EUR + 150 milioane EUR."],
            "notConfirmed": ["Probabilitatea de aprobare nu poate fi dedusă din statusul OPEN sau ordinea depunerii."],
            "actions": ["Verifică ultima versiune a cererii și anexelor.", "Închide eligibilitatea, configurația tehnică și bugetul.", "Depune înainte de termen."],
            "dossierId": "afir-fm-public-autoconsum-2026",
            "source": {"label": "AFIR — depunere în curs proiecte energie entități publice", "url": ENERGY_IN_PROGRESS, "tier": "T1"},
            "utilityScore": 100,
        },
        {
            "id": "news-afir-dr12-upcoming-2026-10-01",
            "kind": "SESSION_ANNOUNCED",
            "programme": "AFIR / PS PAC 2023-2027",
            "date": "2026-10-01",
            "headline": "DR-12: 169,59 milioane EUR pentru consolidarea exploatațiilor fermierilor eligibili",
            "standfirst": "AFIR a anunțat sesiunea 6 octombrie — 2 decembrie 2026, cu maximum 200.000 EUR/proiect și praguri de 80 și 45 puncte.",
            "meaning": "Dosarul poate fi finalizat înainte de deschidere, fără a prezenta apelul ca OPEN înainte de 6 octombrie, ora 09:00.",
            "audience": ["fermieri eligibili conform Ghidului DR-12"],
            "confirmed": ["Deschidere programată: 6 octombrie 2026, 09:00.", "Termen: 2 decembrie 2026, 16:00.", "Alocare: 169.589.647 EUR.", "Grant: maximum 200.000 EUR/proiect."],
            "notConfirmed": ["OPEN efectiv se reconfirmă la lansare."],
            "actions": ["Verifică eligibilitatea.", "Simulează pragul de 80 puncte.", "Pregătește bugetul și anexele."],
            "dossierId": "afir-dr12-2026",
            "source": {"label": "AFIR — anunț sesiune DR-12", "url": DR12_RELEASE, "tier": "T1"},
            "utilityScore": 99,
        },
        {
            "id": "news-afir-energy-public-upcoming-2026-09-22",
            "kind": "SESSION_ANNOUNCED",
            "programme": "AFIR / Fondul pentru Modernizare",
            "date": "2026-09-22T15:50:00+03:00",
            "headline": "650 milioane EUR pentru energie regenerabilă: două apeluri pentru entități publice pornesc la 28 septembrie",
            "standfirst": "AFIR a anunțat 500 milioane EUR pentru producere solară cu stocare pentru autoconsum și 150 milioane EUR pentru stocare; depunerea este programată 28 septembrie — 20 noiembrie 2026.",
            "meaning": "Instituțiile publice eligibile pot închide pregătirea dosarelor acum, fără a confunda lansarea programată cu un apel deja deschis.",
            "audience": ["entități publice eligibile conform ghidurilor AFIR"],
            "confirmed": ["Deschidere programată: 28 septembrie 2026, 10:00.", "Termen anunțat: 20 noiembrie 2026, 23:59.", "Alocări: 500 milioane EUR + 150 milioane EUR."],
            "notConfirmed": ["OPEN efectiv trebuie reconfirmat după momentul lansării; nu este autopromovat din calendar."],
            "actions": ["Verifică încadrarea solicitantului.", "Finalizează configurația tehnică și bugetul.", "Reconfirmă OPEN în AFIR la lansare."],
            "dossierId": "afir-fm-public-autoconsum-2026",
            "source": {"label": "AFIR — informații sesiune energie solicitanți publici", "url": ENERGY_SESSION, "tier": "T1"},
            "utilityScore": 100,
        },
    ]


def should_replace(row: dict[str, Any], target_ids: set[str]) -> bool:
    if str(row.get("id") or "") in target_ids:
        return True
    code = norm(row.get("code"))
    title = norm(row.get("title"))
    if code in {"dr 21", "dr 12"} or "prevenirea raspandirii epizootiilor" in title:
        return True
    if "entitati publice" in title and "energie" in title and ("stocare" in title or "autoconsum" in title):
        return True
    return False


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    dossiers = [dr21_dossier(), energy_dossier(storage=False), energy_dossier(storage=True), dr12_dossier()]
    target_ids = {row["id"] for row in dossiers}
    kept = [row for row in payload.get("dossiers") or [] if not should_replace(row, target_ids)]
    payload["dossiers"] = [*dossiers, *kept]

    replacement_news = news_items()
    news_ids = {row["id"] for row in replacement_news}
    payload["news"] = [*replacement_news, *[row for row in payload.get("news") or [] if row.get("id") not in news_ids]]

    payload.setdefault("policy", {})["afirSeptember2026OfficialCoverage"] = True
    payload["policy"]["scheduledLaunchNeverAutoPromotedToOpen"] = True
    payload.setdefault("qualityPass", {})["afirSeptember2026AuthoritativeDossiers"] = sorted(target_ids)

    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"ok": True, "dossiers": sorted(target_ids), "news": sorted(news_ids), "statusAt": NOW.isoformat()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
