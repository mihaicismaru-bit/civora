#!/usr/bin/env python3
"""Project the current AFIR DR-14, DR-18 and DR-31 facts into public dossiers.

The generic AFIR crawler intentionally fails closed and cannot infer an OPEN
session from a guide page.  This deterministic overlay binds material facts to
the official launch notice, live session counter and intervention pages.  It
also replaces page-level provisional records so one intervention has one
canonical public dossier.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"
LIVE_FUNDS = ROOT / "partener-eu" / "ingest" / "state" / "afir_live_funds.json"

LAUNCH = "https://www.afir.ro/comunicate/afir-lanseaza-sesiuni-pentru-ferme-mici-si-floricultura-plante-medicinale-si-aromatice/"
SESSIONS = "https://www.afir.ro/instrumente/sesiuni/sesiuni-primire-proiecte/"
COUNTER = "https://www.afir.ro/finantare/contor-fonduri-disponibile/"
DR14 = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-14/"
DR18 = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-18/"
DR18_RELEASE = "https://www.afir.ro/comunicate/finantarea-investitiilor-in-floricultura-plante-medicinale-si-aromatice/"
DEBATE = "https://www.afir.ro/comunicare/utile/dezbatere-publica/"
ENERGY_PUBLIC_IN_PROGRESS = "https://www.afir.ro/comunicate/depunere-in-curs-a-proiectelor-in-energie-a-entitatilor-publice/"
ENERGY_CONDITIONS = "https://www.afir.ro/comunicate/conditiile-finantarii-acordate-entitatilor-publice-pentru-producerea-si-stocarea-energiei-electrice/"
ENERGY_OPENING = "https://www.afir.ro/info-la-zi/deschidere-sesiuni-proiecte-energie-regenerabila-beneficiari-publici/"
ENERGY_AUTOCONSUM = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-producere-energie-pentru-autoconsum-beneficiari-publici/"
ENERGY_STORAGE = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-stocare-energie-regenerabila-beneficiari-publici/"
DR12 = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-12/"
DR12_RELEASE = "https://www.afir.ro/comunicate/170-de-milioane-euro-pentru-exploatatiile-tinerilor-fermieri/"
DR12_NOTICE = "https://www.afir.ro/info-la-zi/sesiune-depunere-de-proiecte-dr-12/"
DR12_NOTE = "https://www.afir.ro/info-la-zi/nota-de-indrumare-pentru-fisa-evaluare-proiect-dr-12/"
CURRENT_OBSERVED = "2026-10-04T14:30:00+00:00"


def norm(value: Any) -> str:
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(ch)
    ).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def section(title: str, items: list[str], **extra: Any) -> dict[str, Any]:
    return {"title": title, "items": items, "empty": False, **extra}


def source(label: str, url: str, supports: list[str], observed: str) -> dict[str, Any]:
    return {
        "label": label,
        "url": url,
        "tier": "T1",
        "observedAt": observed,
        "supports": supports,
    }


def facts(rows: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [{"label": label, "value": value, "confidence": confidence} for label, value, confidence in rows]


def dr12_live_submission_evidence() -> tuple[bool, str]:
    try:
        payload = json.loads(LIVE_FUNDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, CURRENT_OBSERVED
    policy = payload.get("policy") or {}
    fingerprint_admissible = (
        payload.get("sourceFingerprintMatchesCorpus") is True
        or payload.get("sourceFingerprintReconciledFromCanonicalLiveFetch") is True
    )
    if payload.get("status") != "PASS" or not fingerprint_admissible or policy.get("publishableDedicatedSnapshot") is not True:
        return False, CURRENT_OBSERVED
    rows = [row for row in payload.get("rows") or [] if str(row.get("interventionCode") or "").upper() == "DR-12"]
    submitted = any(int(row.get("submittedProjectCount") or 0) > 0 for row in rows)
    return submitted, str(payload.get("sourceObservedAt") or CURRENT_OBSERVED)


def open_dossier(
    *, dossier_id: str, title: str, code: str, applicants: list[str], activities: list[str],
    budget: str, project_value: str, cofinancing: str, scoring: list[str], documents: list[str],
    risks: list[str], sources: list[dict[str, Any]], standfirst: str,
) -> dict[str, Any]:
    summary = [
        "Stare apel: DESCHIS.",
        "Deschidere: 1 septembrie 2026, ora 09:00.",
        "Închidere: 31 octombrie 2026, ora 16:00; sesiunea se poate închide mai devreme dacă se epuizează alocarea.",
        f"Cine poate aplica: {'; '.join(applicants)}",
        f"Activități finanțate: {activities[0]}",
        f"Valoarea apelului: {budget}.",
        f"Valoarea proiectului individual: {project_value}.",
        f"Cofinanțare / contribuție proprie: {cofinancing}.",
        "Regiune: România.",
    ]
    decision = "Depunerea este deschisă. Verifică încadrarea exploatației, componenta, punctajul și folosește ultima versiune a cererii înainte de încărcarea online."
    verified = [
        "status", "opening", "deadline", "beneficiaries", "eligibility", "activities",
        "budget", "grant", "cofinancing", "documents", "scoring", "risks",
    ]
    return {
        "id": dossier_id,
        "sourceType": "AFIR_CANONICAL",
        "title": title,
        "slug": dossier_id,
        "programme": "AFIR / Planul Strategic PAC 2023-2027",
        "code": code,
        "region": "România",
        "status": "OPEN",
        "statusLabel": "DESCHIS",
        "decision": "ACȚIONEAZĂ",
        "decisionLabel": "ACȚIONEAZĂ",
        "decisionAction": decision,
        "publicationState": "PUBLISHABLE",
        "standfirst": standfirst,
        "audience": applicants,
        "quickFacts": facts([
            ("Status", "DESCHIS", "CONFIRMED"),
            ("Deschidere", "1 septembrie 2026, 09:00", "CONFIRMED"),
            ("Termen", "31 octombrie 2026, 16:00", "CONFIRMED"),
            ("Grant", project_value, "CONFIRMED"),
            ("Buget", budget, "CONFIRMED"),
            ("Contribuție proprie", cofinancing, "CONFIRMED"),
            ("Completitudine critică", "100%", "SYSTEM"),
        ]),
        "sections": [
            section("Rezumat executiv", summary, schemaVersion=1),
            section("Decizia rapidă", [decision, "Nu amâna depunerea până la termenul final: AFIR poate închide sesiunea anticipat la epuizarea fondurilor."]),
            section("Cine poate aplica", applicants, policy="GUIDE_EXPLICIT_ONLY"),
            section("Condiții esențiale de eligibilitate", ["Încadrarea exactă a solicitantului și a exploatației se validează în Ghidul solicitantului și anexele oficiale aplicabile.", "Proiectul se încadrează în intervenția și componenta aleasă, fără creare de condiții artificiale."]),
            section("Ce finanțează și în ce condiții", activities),
            section("Costuri, cofinanțare și ajutor de stat", [f"Alocarea sesiunii este {budget}.", f"Sprijinul pe proiect este {project_value}.", f"Contribuția proprie rezultată din intensitatea maximă este {cofinancing}, la care se adaugă costurile neeligibile."]),
            section("Documente de pregătit", documents),
            section("Cum se punctează", scoring),
            section("Indicatori și obligații", ["Indicatorii, rezultatele și obligațiile de durabilitate se preiau din Ghidul solicitantului și contractul de finanțare.", "Păstrează trasabilitatea documentelor și a versiunii cererii încărcate în sistem."]),
            section("Riscuri de respingere sau implementare", risks),
            section("Ce trebuie făcut acum", ["Rulează screeningul de eligibilitate pe forma juridică și dimensiunea economică a exploatației.", "Alege componenta și simulează punctajul pentru etapa lunară aplicabilă.", "Construiește bugetul și dovada cofinanțării.", "Completează exclusiv ultima versiune a cererii publicate de AFIR și depune înainte de epuizarea alocării."]),
            section("Ce nu este confirmat", ["Verdictul pentru o exploatație concretă nu poate fi stabilit fără datele solicitantului și verificarea integrală a ghidului și anexelor aplicabile."]),
        ],
        "timeline": [
            {"date": "2026-09-01T09:00:00+03:00", "kind": "CALL_OPENED", "text": "AFIR deschide sesiunea online."},
            {"date": "2026-08-14T11:00:00+03:00", "kind": "SESSION_ANNOUNCED", "text": "AFIR publică anunțul oficial de lansare."},
        ],
        "sources": sources,
        "quality": {
            "completeness": 100,
            "depthCompleteness": 100,
            "dossierLevel": "DOSAR COMPLET",
            "verifiedFactClasses": verified,
            "blockedFactClasses": [],
            "evidenceCount": len(sources),
            "failClosed": True,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "applicantEvidenceAuthorized": True,
            "executiveSummaryPresent": True,
            "afirCurrentSessionBundle": True,
        },
        "updatedAt": "2026-09-01T18:45:00+03:00",
        "canonicalLinks": [row["url"] for row in sources],
        "executiveSummary": {
            "status": "OPEN",
            "opens": "2026-09-01T09:00:00+03:00",
            "closes": "2026-10-31T16:00:00+02:00",
            "applicants": applicants,
            "targetGroup": [],
            "activities": activities,
            "callBudget": budget,
            "projectValue": project_value,
            "cofinancing": cofinancing,
            "region": "România",
            "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
            "sourceBound": True,
        },
        "dossierConstruction": {
            "autonomous": True,
            "depthCompleteness": 100,
            "level": "DOSAR COMPLET",
            "missing": [],
            "nextPass": "MONITOR_LIFECYCLE_AND_AVAILABLE_FUNDS",
        },
    }


def _section_by_title(dossier: dict[str, Any], title: str) -> dict[str, Any] | None:
    return next((row for row in dossier.get("sections") or [] if row.get("title") == title), None)


def _set_fact(dossier: dict[str, Any], label: str, value: str, confidence: str = "CONFIRMED") -> None:
    for row in dossier.get("quickFacts") or []:
        if row.get("label") == label:
            row["value"] = value
            row["confidence"] = confidence
            return
    dossier.setdefault("quickFacts", []).append({"label": label, "value": value, "confidence": confidence})


def promote_energy_open(dossier: dict[str, Any]) -> dict[str, Any]:
    """Promote only the two canonical public-energy dossiers on explicit post-launch AFIR evidence."""
    dossier = json.loads(json.dumps(dossier, ensure_ascii=False))
    dossier["status"] = "OPEN"
    dossier["statusLabel"] = "DESCHIS"
    dossier["decision"] = "ACȚIONEAZĂ"
    dossier["decisionLabel"] = "ACȚIONEAZĂ"
    dossier["decisionAction"] = (
        "Depunerea este deschisă. Folosește exclusiv formularul AFIR publicat pentru sesiunea curentă "
        "și verifică eligibilitatea, bugetul și anexele înainte de încărcarea online."
    )
    dossier["publicationState"] = "PUBLISHABLE"
    dossier["standfirst"] = (
        "Sesiune în derulare pentru entități publice: depunerea este deschisă din 28 septembrie 2026, "
        "ora 10:00, până la 20 noiembrie 2026, ora 23:59."
    )
    _set_fact(dossier, "Status", "DESCHIS")
    _set_fact(dossier, "Deschidere", "28 septembrie 2026, 10:00")
    _set_fact(dossier, "Termen", "20 noiembrie 2026, 23:59")

    summary = _section_by_title(dossier, "Rezumat executiv")
    if summary is not None:
        retained = [
            item for item in summary.get("items") or []
            if not any(token in norm(item) for token in (
                "stare apel", "deschidere", "inchidere", "nu este inca open", "nu este open"
            ))
        ]
        summary["items"] = [
            "Stare apel: DESCHIS.",
            "Deschidere: 28 septembrie 2026, ora 10:00.",
            "Închidere: 20 noiembrie 2026, ora 23:59.",
            *retained,
        ]
        summary["schemaVersion"] = 1

    rapid = _section_by_title(dossier, "Decizia rapidă")
    if rapid is not None:
        rapid["items"] = [
            dossier["decisionAction"],
            "Nu folosi versiuni vechi ale formularului: AFIR a introdus validări pentru formularul autorizat al sesiunii curente.",
        ]

    now_section = _section_by_title(dossier, "Ce trebuie făcut acum")
    if now_section is not None:
        existing = [
            item for item in now_section.get("items") or []
            if "asteapta deschiderea" not in norm(item) and "monitorizeaza lansarea" not in norm(item)
        ]
        now_section["items"] = [
            "Verifică eligibilitatea solicitantului și investiției în ghidul oficial curent.",
            "Descarcă și completează exclusiv formularul AFIR autorizat pentru sesiunea lansată la 28 septembrie 2026.",
            "Pregătește anexele și depune în sistemul AFIR înainte de 20 noiembrie 2026, ora 23:59.",
            *existing,
        ]

    unknown = _section_by_title(dossier, "Ce nu este confirmat")
    if unknown is not None:
        unknown["items"] = [
            item for item in unknown.get("items") or []
            if not any(token in norm(item) for token in ("data lansarii", "status apel", "apelul nu este", "deschiderea apelului"))
        ] or ["Eligibilitatea și valoarea finanțării pentru un proiect concret se stabilesc numai după verificarea ghidului și a datelor solicitantului."]

    evidence = source(
        "AFIR — depunere în curs a proiectelor în energie ale entităților publice",
        ENERGY_PUBLIC_IN_PROGRESS,
        ["status", "opening", "deadline", "source_event"],
        CURRENT_OBSERVED,
    )
    sources = dossier.setdefault("sources", [])
    if not any(row.get("url") == ENERGY_PUBLIC_IN_PROGRESS for row in sources if isinstance(row, dict)):
        sources.append(evidence)
    dossier["canonicalLinks"] = list(dict.fromkeys([*(dossier.get("canonicalLinks") or []), ENERGY_PUBLIC_IN_PROGRESS]))

    executive = dossier.setdefault("executiveSummary", {})
    executive["status"] = "OPEN"
    executive["opens"] = "2026-09-28T10:00:00+03:00"
    executive["closes"] = "2026-11-20T23:59:00+02:00"
    executive["sourceBound"] = True

    quality = dossier.setdefault("quality", {})
    verified = list(quality.get("verifiedFactClasses") or [])
    for fact_class in ("status", "opening", "deadline"):
        if fact_class not in verified:
            verified.append(fact_class)
    quality["verifiedFactClasses"] = verified
    quality["evidenceCount"] = len(sources)
    quality["failClosed"] = True
    quality["afirEnergyPostLaunchEvidence"] = True
    dossier.setdefault("dossierConstruction", {})["nextPass"] = "MONITOR_LIFECYCLE_AND_SOURCE_CHANGES"
    dossier["updatedAt"] = CURRENT_OBSERVED
    return dossier


def energy_public_dossier(*, storage: bool) -> dict[str, Any]:
    dossier_id = "afir-fm-public-storage-2026" if storage else "afir-fm-public-autoconsum-2026"
    title = (
        "Fondul pentru Modernizare — Stocarea energiei regenerabile pentru entități publice"
        if storage else
        "Fondul pentru Modernizare — Producerea energiei regenerabile pentru autoconsum — entități publice"
    )
    budget = "150.000.000 EUR" if storage else "500.000.000 EUR"
    project_cap = (
        "maximum 10.000.000 EUR/beneficiar și maximum 200.000 EUR/MWh de stocare instalat"
        if storage else
        "maximum 10.000.000 EUR/beneficiar; maximum 900.000 EUR/MW sau 1.100.000 EUR/MW dacă proiectul include pompe de căldură"
    )
    activity = (
        "Capacități noi de stocare în spatele contorului, conectate la instalații existente de producere a energiei din surse regenerabile, pentru autoconsum și optimizarea consumului."
        if storage else
        "Capacități noi de producere a energiei electrice din surse regenerabile solare, cu capacități de stocare integrate, pentru autoconsumul entității publice."
    )
    details_url = ENERGY_STORAGE if storage else ENERGY_AUTOCONSUM
    applicants = [
        "Primării și consilii județene.",
        "Spitale publice și universități de stat.",
        "Unități de apărare și ordine publică.",
        "Unități de cult, institute de cercetare, instituții de învățământ superior și alte instituții publice eligibile.",
        "Parteneriate între entitățile eligibile, în condițiile ghidului.",
    ]
    decision = (
        "Depunerea este deschisă. Verifică eligibilitatea entității și investiției, folosește exclusiv formularul AFIR al sesiunii curente "
        "și depune înainte de 20 noiembrie 2026, ora 23:59."
    )
    sources = [
        source("AFIR — depunere în curs pentru energia entităților publice", ENERGY_PUBLIC_IN_PROGRESS, ["status", "opening", "deadline", "source_event"], CURRENT_OBSERVED),
        source("AFIR — condițiile finanțării pentru entități publice", ENERGY_CONDITIONS, ["beneficiaries", "budget", "grant", "cofinancing"], CURRENT_OBSERVED),
        source("AFIR — deschidere sesiuni energie beneficiari publici", ENERGY_OPENING, ["opening", "deadline", "documents"], CURRENT_OBSERVED),
        source("AFIR — ghid și anexe linie energie", details_url, ["beneficiaries", "eligibility", "activities", "documents"], CURRENT_OBSERVED),
    ]
    return {
        "id": dossier_id,
        "sourceType": "AFIR_CANONICAL",
        "title": title,
        "slug": dossier_id,
        "programme": "Fondul pentru Modernizare / AFIR",
        "code": "FM-ENERGIE-STOCARE-PUBLICI-2026" if storage else "FM-ENERGIE-AUTOCONSUM-PUBLICI-2026",
        "region": "România",
        "status": "OPEN",
        "statusLabel": "DESCHIS",
        "decision": "ACȚIONEAZĂ",
        "decisionLabel": "ACȚIONEAZĂ",
        "decisionAction": decision,
        "publicationState": "PUBLISHABLE",
        "standfirst": (
            f"Sesiune deschisă pentru entități publice din 28 septembrie 2026, ora 10:00, până la 20 noiembrie 2026, ora 23:59. "
            f"Alocare: {budget}; finanțarea poate acoperi până la 100% din cheltuielile eligibile, în limitele ghidului."
        ),
        "audience": applicants,
        "quickFacts": facts([
            ("Status", "DESCHIS", "CONFIRMED"),
            ("Deschidere", "28 septembrie 2026, 10:00", "CONFIRMED"),
            ("Termen", "20 noiembrie 2026, 23:59", "CONFIRMED"),
            ("Grant", project_cap, "CONFIRMED"),
            ("Buget", budget, "CONFIRMED"),
            ("Intensitate", "până la 100% din cheltuielile eligibile", "CONFIRMED"),
            ("Completitudine critică", "93%", "SYSTEM"),
        ]),
        "sections": [
            section("Rezumat executiv", [
                "Stare apel: DESCHIS.",
                "Deschidere: 28 septembrie 2026, ora 10:00.",
                "Închidere: 20 noiembrie 2026, ora 23:59.",
                f"Cine poate aplica: {'; '.join(applicants)}",
                f"Activități finanțate: {activity}",
                f"Valoarea apelului: {budget}.",
                f"Valoarea proiectului individual: {project_cap}.",
                "Cofinanțare / contribuție proprie: finanțarea poate acoperi până la 100% din cheltuielile eligibile, în limitele ghidului.",
                "Regiune: România.",
            ], schemaVersion=1),
            section("Decizia rapidă", [
                decision,
                "Nu folosi formulare vechi: AFIR validează formularul autorizat pentru sesiunea lansată la 28 septembrie 2026.",
            ]),
            section("Cine poate aplica", applicants, policy="GUIDE_EXPLICIT_ONLY"),
            section("Condiții esențiale de eligibilitate", [
                "Solicitantul și investiția trebuie să se încadreze în categoriile și condițiile prevăzute de Ghidul solicitantului.",
                "Verdictul pentru o entitate și o investiție concretă se stabilește numai după verificarea integrală a ghidului și anexelor curente.",
            ]),
            section("Ce finanțează și în ce condiții", [activity]),
            section("Costuri, cofinanțare și ajutor de stat", [
                f"Alocarea liniei este {budget}.",
                f"Plafonul sprijinului: {project_cap}.",
                "Finanțarea poate acoperi până la 100% din cheltuielile eligibile, în limitele schemei și ghidului.",
            ]),
            section("Documente de pregătit", [
                "Ghidul solicitantului și anexele liniei de finanțare.",
                "Cererea de finanțare în formatul editabil autorizat de AFIR pentru sesiunea curentă.",
                "Documentele tehnice, juridice și financiare cerute de ghid pentru solicitant și investiție.",
            ]),
            section("Cum se punctează", [
                "Procesul de evaluare și selecție se aplică potrivit Ghidului solicitantului; nu proiectăm un punctaj numeric fără dovada oficială specifică.",
            ]),
            section("Indicatori și obligații", [
                "Capacitatea instalată și rezultatele energetice asumate trebuie susținute de documentația tehnică și urmărite în implementare.",
                "Păstrează trasabilitatea versiunii formularului și anexelor încărcate în sistem.",
            ]),
            section("Riscuri de respingere sau implementare", [
                "Utilizarea unui formular neautorizat sau a unei versiuni vechi.",
                "Încadrarea greșită a solicitantului ori investiției față de ghid.",
                "Bugetarea peste plafoanele specifice liniei de finanțare.",
            ]),
            section("Ce trebuie făcut acum", [
                "Verifică eligibilitatea entității și a investiției în Ghidul solicitantului.",
                "Descarcă exclusiv formularul AFIR autorizat pentru sesiunea curentă.",
                "Finalizează anexele tehnice și financiare și depune înainte de 20 noiembrie 2026, ora 23:59.",
            ]),
            section("Ce nu este confirmat", [
                "Eligibilitatea și valoarea finanțării pentru un proiect concret nu pot fi stabilite fără datele solicitantului și verificarea integrală a documentației oficiale.",
            ]),
        ],
        "timeline": [
            {"date": "2026-09-11T20:55:00+03:00", "kind": "FINAL_GUIDE_PUBLISHED", "text": "AFIR publică ghidurile și condițiile de finanțare."},
            {"date": "2026-09-28T10:00:00+03:00", "kind": "CALL_OPENED", "text": "AFIR deschide sesiunea online."},
            {"date": "2026-09-29T10:15:00+03:00", "kind": "POST_LAUNCH_CONFIRMED", "text": "AFIR confirmă explicit că sesiunea este în derulare."},
        ],
        "sources": sources,
        "quality": {
            "completeness": 93,
            "depthCompleteness": 93,
            "dossierLevel": "DOSAR AVANSAT",
            "verifiedFactClasses": ["status", "opening", "deadline", "beneficiaries", "activities", "budget", "grant", "cofinancing", "documents", "risks"],
            "blockedFactClasses": ["project_specific_eligibility", "scoring_specific"],
            "evidenceCount": len(sources),
            "failClosed": True,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "applicantEvidenceAuthorized": True,
            "executiveSummaryPresent": True,
            "afirEnergyPostLaunchEvidence": True,
        },
        "updatedAt": CURRENT_OBSERVED,
        "canonicalLinks": [row["url"] for row in sources],
        "executiveSummary": {
            "status": "OPEN",
            "opens": "2026-09-28T10:00:00+03:00",
            "closes": "2026-11-20T23:59:00+02:00",
            "applicants": applicants,
            "targetGroup": [],
            "activities": [activity],
            "callBudget": budget,
            "projectValue": project_cap,
            "cofinancing": "până la 100% din cheltuielile eligibile",
            "region": "România",
            "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
            "sourceBound": True,
        },
        "dossierConstruction": {
            "autonomous": True,
            "depthCompleteness": 93,
            "level": "DOSAR AVANSAT",
            "missing": ["project_specific_eligibility", "scoring_specific"],
            "nextPass": "MONITOR_LIFECYCLE_AND_SOURCE_CHANGES",
        },
    }


def dr12_dossier() -> dict[str, Any]:
    post_launch_evidence, observed = dr12_live_submission_evidence()
    status = "OPEN" if post_launch_evidence else "UPCOMING"
    status_label = "DESCHIS" if post_launch_evidence else "SE DESCHIDE ÎN CURÂND"
    decision_label = "ACȚIONEAZĂ" if post_launch_evidence else "PREGĂTEȘTE"
    applicants = [
        "Fermieri care sunt șefi ai exploatației și au cel mult 40 de ani la depunere.",
        "Beneficiari ai submăsurii 6.1 PNDR, indiferent de vârsta la momentul depunerii.",
        "Fermieri cu vârsta de cel mult 45 de ani la depunere, în condițiile ghidului.",
    ]
    activities = [
        "Consolidarea exploatațiilor tinerilor fermieri instalați și a fermierilor cu vârsta de până la 45 de ani.",
        "Condiționare și depozitare corelate cu producția fermei; înființarea și modernizarea fermelor pomicole.",
        "Procesare la nivelul fermei ca activitate secundară și achiziția de utilaje, remorci, semiremorci tehnologice și echipamente agricole eligibile.",
    ]
    sources = [
        source("AFIR — comunicat lansare DR-12", DR12_RELEASE, ["status", "opening", "deadline", "budget", "beneficiaries", "grant", "cofinancing", "activities", "scoring"], CURRENT_OBSERVED),
        source("AFIR — Detalii și Anexe DR-12", DR12, ["beneficiaries", "eligibility", "activities", "grant", "cofinancing", "documents"], CURRENT_OBSERVED),
        source("AFIR — anunț sesiune DR-12", DR12_NOTICE, ["status", "opening", "deadline"], CURRENT_OBSERVED),
        source("AFIR — Notă de îndrumare E1.2 DR-12", DR12_NOTE, ["documents", "eligibility", "risks"], CURRENT_OBSERVED),
        source("AFIR — contor fonduri disponibile", COUNTER, ["status", "opening", "deadline", "budget"] if post_launch_evidence else ["opening", "deadline", "budget"], observed),
    ]
    decision = (
        "Depunerea este deschisă. Verifică imediat încadrarea, punctajul etapei curente și ultima versiune a ghidului și anexelor."
        if post_launch_evidence else
        "Pregătește dosarul acum pentru deschiderea din 6 octombrie 2026, ora 09:00; verifică punctajul pentru etapa curentă și folosește ultima versiune a ghidului și anexelor."
    )
    return {
        "id": "afir-dr12-2026",
        "sourceType": "AFIR_CANONICAL",
        "title": "DR-12 — Investiții în consolidarea exploatațiilor tinerilor fermieri",
        "slug": "afir-dr12-2026",
        "programme": "AFIR / Planul Strategic PAC 2023-2027",
        "code": "DR-12",
        "region": "România",
        "status": status,
        "statusLabel": status_label,
        "decision": decision_label,
        "decisionLabel": decision_label,
        "decisionAction": decision,
        "publicationState": "PUBLISHABLE",
        "standfirst": (
            "Sesiunea DR-12 este deschisă pentru depunere, cu 169.589.647 EUR alocare totală și finanțare de până la 200.000 EUR/proiect."
            if post_launch_evidence
            else "Sesiunea DR-12 se deschide la 6 octombrie 2026, ora 09:00, cu 169.589.647 EUR disponibili și finanțare de până la 200.000 EUR/proiect."
        ),
        "audience": applicants,
        "quickFacts": facts([
            ("Status", status_label, "CONFIRMED"),
            ("Deschidere", "6 octombrie 2026, 09:00", "CONFIRMED"),
            ("Termen", "2 decembrie 2026, 16:00", "CONFIRMED"),
            ("Grant", "maximum 200.000 EUR/proiect", "CONFIRMED"),
            ("Buget", "169.589.647 EUR", "CONFIRMED"),
            ("Intensitate", "maximum 80% pentru tinerii fermieri de până la 40 de ani; maximum 65% pentru celelalte categorii", "CONFIRMED"),
            ("Completitudine critică", "92%", "SYSTEM"),
        ]),
        "sections": [
            section("Rezumat executiv", [
                f"Stare apel: {status_label}.",
                "Deschidere: 6 octombrie 2026, ora 09:00.",
                "Închidere: 2 decembrie 2026, ora 16:00.",
                f"Cine poate aplica: {'; '.join(applicants)}",
                f"Activități finanțate: {activities[0]}",
                "Valoarea apelului: 169.589.647 EUR, împărțită egal între sectorul zootehnic și alte sectoare.",
                "Valoarea proiectului individual: maximum 200.000 EUR/proiect.",
                "Cofinanțare / contribuție proprie: intensitate maximum 80% pentru tinerii fermieri de până la 40 de ani și maximum 65% pentru celelalte categorii.",
                "Regiune: România.",
            ], schemaVersion=1),
            section("Decizia rapidă", [decision, "Depune numai după verificarea finală a eligibilității, punctajului și documentelor curente." if post_launch_evidence else "Nu depune înainte de deschiderea oficială; pregătește acum documentele și punctajul."]),
            section("Cine poate aplica", applicants, policy="GUIDE_EXPLICIT_ONLY"),
            section("Condiții esențiale de eligibilitate", [
                "Solicitantul trebuie să se încadreze într-una dintre categoriile de beneficiari prevăzute de ghid și să fie șef al exploatației acolo unde ghidul impune această condiție.",
                "Persoanele fizice neautorizate nu sunt eligibile.",
                "Verdictul final de eligibilitate se stabilește numai pe datele solicitantului și anexele oficiale curente.",
            ]),
            section("Ce finanțează și în ce condiții", activities),
            section("Costuri, cofinanțare și ajutor de stat", [
                "Alocarea totală este 169.589.647 EUR: 84.794.823,5 EUR pentru sectorul zootehnic și 84.794.823,5 EUR pentru alte sectoare.",
                "Sprijinul poate ajunge la 200.000 EUR/proiect.",
                "Intensitatea maximă este 80% pentru tinerii fermieri de până la 40 de ani și 65% pentru celelalte categorii eligibile.",
            ]),
            section("Documente de pregătit", [
                "Ghidul solicitantului DR-12 și anexele oficiale publicate de AFIR.",
                "Cererea de finanțare și documentele tehnico-economice aplicabile investiției.",
                "Fișa E1.2 și Nota de îndrumare AFIR din 2 octombrie 2026.",
            ]),
            section("Cum se punctează", [
                "Prag de calitate: 80 puncte în perioada 6 octombrie – 5 noiembrie 2026.",
                "Prag de calitate: 45 puncte în perioada 6 noiembrie – 2 decembrie 2026.",
            ]),
            section("Indicatori și obligații", [
                "Indicatorii și obligațiile contractuale se verifică în ghidul și contractul de finanțare aplicabile proiectului concret.",
                "Păstrează trasabilitatea versiunii documentelor folosite la depunere.",
            ]),
            section("Riscuri de respingere sau implementare", [
                "Punctaj sub pragul etapei lunare aplicabile.",
                "Încadrare greșită a solicitantului sau investiției față de condițiile ghidului.",
                "Pentru Fișa E1.2, punctul 3.7 privind ponderea achizițiilor simple într-un proiect complex nu este aplicabil la DR-12 și se marchează «NU ESTE CAZUL», conform notei AFIR din 2 octombrie 2026.",
            ]),
            section("Ce trebuie făcut acum", [
                "Confirmă forma juridică, vârsta și istoricul instalării solicitantului.",
                "Simulează punctajul pentru pragul de 80 de puncte al primei etape.",
                "Fixează investițiile eligibile, bugetul și dovada contribuției proprii.",
                "Descarcă ultima versiune a ghidului, cererii și anexelor și pregătește depunerea imediată." if post_launch_evidence else "Descarcă ultima versiune a ghidului, cererii și anexelor și pregătește depunerea pentru 6 octombrie, ora 09:00.",
            ]),
            section("Ce nu este confirmat", [
                "Eligibilitatea unui solicitant și punctajul unui proiect concret nu pot fi stabilite fără datele sale și verificarea integrală a documentației oficiale.",
            ]),
        ],
        "timeline": [
            {"date": "2026-09-29T13:00:00+03:00", "kind": "SESSION_ANNOUNCED", "text": "AFIR anunță sesiunea DR-12."},
            {"date": "2026-10-02T12:30:00+03:00", "kind": "GUIDANCE_UPDATED", "text": "AFIR clarifică aplicarea Fișei E1.2 pentru DR-12."},
            {"date": "2026-10-06T09:00:00+03:00", "kind": "CALL_OPENS", "text": "Începe sesiunea de depunere DR-12."},
        ],
        "sources": sources,
        "quality": {
            "completeness": 92,
            "depthCompleteness": 92,
            "dossierLevel": "DOSAR AVANSAT",
            "verifiedFactClasses": ["status", "opening", "deadline", "beneficiaries", "activities", "budget", "grant", "cofinancing", "documents", "scoring", "risks"],
            "blockedFactClasses": ["project_specific_eligibility"],
            "evidenceCount": len(sources),
            "failClosed": True,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "applicantEvidenceAuthorized": True,
            "executiveSummaryPresent": True,
            "afirCurrentUpcomingBundle": not post_launch_evidence,
            "afirCurrentOpenBundle": post_launch_evidence,
            "afirPostLaunchSubmissionEvidence": post_launch_evidence,
        },
        "updatedAt": observed,
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
            "cofinancing": "intensitate maximum 80% / 65%, în funcție de categoria beneficiarului",
            "region": "România",
            "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
            "sourceBound": True,
        },
        "dossierConstruction": {
            "autonomous": True,
            "depthCompleteness": 92,
            "level": "DOSAR AVANSAT",
            "missing": ["project_specific_eligibility"],
            "nextPass": "MONITOR_LIFECYCLE_AND_FUNDS" if post_launch_evidence else "MONITOR_OPENING_AND_FIRST_SUBMISSIONS",
        },
    }


def dr31_dossier() -> dict[str, Any]:
    summary = [
        "Stare apel: CONSULTARE PUBLICĂ — nu este sesiune deschisă pentru depunere.",
        "Deschidere: 28 august 2026.",
        "Închidere: consultarea durează 10 zile calendaristice de la publicare; ora-limită nu este precizată pe pagină.",
        "Cine poate aplica: Neconfirmat în pagina de consultare; se verifică în ghidul consultativ curent.",
        "Activități finanțate: contribuții financiare la plata primelor de asigurare.",
        "Valoarea apelului: Neconfirmat în pagina de consultare.",
        "Valoarea proiectului individual: Neconfirmat în pagina de consultare.",
        "Cofinanțare / contribuție proprie: Neconfirmat în pagina de consultare.",
    ]
    return {
        "id": "afir-dr31-2026-2027",
        "sourceType": "AFIR_CANONICAL",
        "title": "DR-31 — Contribuții financiare la plata primelor de asigurare",
        "slug": "afir-dr31-2026-2027",
        "programme": "AFIR / Planul Strategic PAC 2023-2027",
        "code": "DR-31",
        "region": "România",
        "status": "PUBLIC_CONSULTATION",
        "statusLabel": "CONSULTARE PUBLICĂ",
        "decision": "PREGĂTEȘTE",
        "decisionLabel": "PREGĂTEȘTE",
        "decisionAction": "Analizează numai ediția curentă pentru anul agricol 2026-2027 și transmite observații în fereastra de 10 zile; nu trata consultarea ca sesiune de depunere.",
        "publicationState": "PUBLISHABLE",
        "standfirst": "AFIR a publicat în consultare ghidul DR-31 pentru anul agricol 2026-2027 și avertizează că versiunea din iunie 2026 a fost publicată eronat. Consultarea durează 10 zile calendaristice de la 28 august 2026.",
        "audience": [],
        "quickFacts": facts([
            ("Status", "CONSULTARE PUBLICĂ", "CONFIRMED"),
            ("Termen", "10 zile calendaristice de la 28 august 2026; ora-limită neprecizată", "CONFIRMED"),
            ("Grant", "Neconfirmat", "UNKNOWN"),
            ("Buget", "Neconfirmat", "UNKNOWN"),
            ("Contribuție proprie", "Neconfirmat", "UNKNOWN"),
            ("Completitudine critică", "29%", "SYSTEM"),
        ]),
        "sections": [
            section("Rezumat executiv", summary, schemaVersion=1),
            section("Decizia rapidă", ["Folosește Ediția I, revizia 0 — anul agricol 2026-2027.", "Ignoră versiunea Ediția I, revizia 0 — iunie 2026, indicată de AFIR ca publicată eronat."]),
            section("Cine poate aplica", ["Neconfirmat în pagina de consultare; verifică lista din ghidul consultativ curent."], policy="GUIDE_EXPLICIT_ONLY"),
            section("Condiții esențiale de eligibilitate", ["Condițiile sunt în analiză publică și nu autorizează încă depunerea unei cereri de finanțare."]),
            section("Ce finanțează și în ce condiții", ["Intervenția vizează contribuții financiare la plata primelor de asigurare; detaliile se verifică în ghidul consultativ curent."]),
            section("Costuri, cofinanțare și ajutor de stat", ["Neconfirmat în pagina de consultare; nu proiecta valori înaintea verificării ghidului și a formei finale."]),
            section("Documente de pregătit", ["Ghidul Solicitantului DR-31 — Ediția I, revizia 0, anul agricol 2026-2027.", "Observațiile argumentate pentru consultare."]),
            section("Cum se punctează", ["Neconfirmat în pagina de consultare; criteriile se citesc din versiunea curentă a ghidului."]),
            section("Indicatori și obligații", ["Neconfirmat până la aprobarea formei finale."]),
            section("Riscuri de respingere sau implementare", ["Utilizarea versiunii din iunie 2026, publicată eronat.", "Prezentarea consultării ca apel deschis.", "Fixarea unor condiții înaintea publicării formei finale."]),
            section("Ce trebuie făcut acum", ["Descarcă versiunea curentă și compar-o cu nevoia solicitantului.", "Transmite observații către AFIR în perioada de consultare.", "Monitorizează publicarea formei finale și anunțul unei eventuale sesiuni."]),
            section("Ce nu este confirmat", ["Deschiderea unei sesiuni, bugetul, plafonul pe proiect și lista finală a beneficiarilor nu sunt confirmate de pagina de consultare."]),
        ],
        "timeline": [{"date": "2026-08-28T14:10:00+03:00", "kind": "CONSULTATION_OPENED", "text": "AFIR publică versiunea consultativă curentă DR-31."}],
        "sources": [source("AFIR — Dezbatere publică DR-31", DEBATE, ["status", "deadline", "documents", "source_event"], "2026-09-01T18:45:00+03:00")],
        "quality": {
            "completeness": 29,
            "verifiedFactClasses": ["status", "deadline", "documents", "source_event"],
            "blockedFactClasses": ["beneficiaries", "eligibility", "grant", "budget", "scoring"],
            "evidenceCount": 1,
            "failClosed": True,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "applicantEvidenceAuthorized": False,
            "executiveSummaryPresent": True,
            "afirCurrentConsultationBundle": True,
        },
        "updatedAt": "2026-09-01T18:45:00+03:00",
        "canonicalLinks": [DEBATE],
        "executiveSummary": {
            "status": "PUBLIC_CONSULTATION",
            "opens": "2026-08-28",
            "closes": "10 zile calendaristice de la 28 august 2026; ora-limită neprecizată",
            "applicants": [],
            "targetGroup": [],
            "activities": ["Contribuții financiare la plata primelor de asigurare."],
            "callBudget": "Neconfirmat",
            "projectValue": "Neconfirmat",
            "cofinancing": "Neconfirmat",
            "region": "România",
            "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
            "sourceBound": True,
        },
        "dossierConstruction": {"autonomous": True, "depthCompleteness": 29, "level": "DOSAR DE IDENTIFICARE", "missing": ["beneficiaries", "eligibility", "grant", "budget", "scoring"], "nextPass": "MONITOR_FINAL_GUIDE"},
    }


def news_items() -> list[dict[str, Any]]:
    return [
        {
            "id": "news-afir-dr14-dr18-open-2026-09-01", "kind": "CALL_OPENED",
            "programme": "AFIR / PS PAC 2023-2027", "date": "2026-09-01T09:00:00+03:00",
            "headline": "DR-14 și DR-18 sunt deschise pentru depunere",
            "standfirst": "AFIR a deschis la 1 septembrie 2026, ora 09:00, sesiunile pentru ferme mici și pentru floricultură, plante medicinale și aromatice. Termenul anunțat este 31 octombrie 2026, ora 16:00, cu posibilitatea închiderii anticipate la epuizarea fondurilor.",
            "meaning": "Solicitanții pot depune acum; pregătirea trebuie prioritizată pe eligibilitate, componentă, punctaj și ultima versiune a cererii.",
            "audience": ["fermieri și forme asociative eligibile, conform intervenției aplicabile"],
            "confirmed": ["DR-14: 108.000.000 EUR și maximum 50.000 EUR/proiect.", "DR-18: 5.000.000 EUR și maximum 100.000 EUR/proiect.", "Ambele sesiuni: 1 septembrie 2026, 09:00 — 31 octombrie 2026, 16:00."],
            "notConfirmed": ["Eligibilitatea unui solicitant concret se stabilește numai după verificarea integrală a ghidului și anexelor intervenției."],
            "actions": ["Deschide dosarul DR-14 sau DR-18.", "Verifică punctajul și componenta.", "Depune înainte de epuizarea alocării."],
            "dossierId": "afir-dr18-2026",
            "source": {"label": "AFIR — anunț oficial de lansare DR-14 și DR-18", "url": LAUNCH, "tier": "T1"},
            "utilityScore": 100,
        },
        {
            "id": "news-afir-dr31-consultation-2026-08-28", "kind": "CONSULTATION_OPENED",
            "programme": "AFIR / PS PAC 2023-2027", "date": "2026-08-28T14:10:00+03:00",
            "headline": "DR-31: AFIR a deschis consultarea pentru anul agricol 2026-2027",
            "standfirst": "AFIR indică drept versiune curentă Ediția I, revizia 0 — anul agricol 2026-2027 și avertizează că versiunea din iunie 2026 a fost publicată eronat.",
            "meaning": "Este momentul pentru analiză și observații, nu pentru depunere.",
            "audience": ["persoane și organizații interesate de intervenția DR-31"],
            "confirmed": ["Consultarea a început la 28 august 2026 și durează 10 zile calendaristice.", "Versiunea din iunie 2026 nu trebuie folosită."],
            "notConfirmed": ["Sesiunea de depunere, bugetul și condițiile finale nu sunt confirmate."],
            "actions": ["Folosește ghidul curent.", "Transmite observații în perioada de consultare.", "Monitorizează forma finală."],
            "dossierId": "afir-dr31-2026-2027",
            "source": {"label": "AFIR — Dezbatere publică DR-31", "url": DEBATE, "tier": "T1"},
            "utilityScore": 90,
        },
    ]


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    applicants14 = ["Fermieri, cu excepția persoanelor fizice."]
    applicants18 = [
        "Fermieri, cu excepția persoanelor fizice.",
        "Cooperative agricole și societăți cooperative care reprezintă interesele membrilor fermieri.",
        "Grupuri și organizații de producători constituite conform legislației și recunoscute de MADR.",
    ]
    common_sources = [
        source("AFIR — anunț oficial de lansare DR-14 și DR-18", LAUNCH, ["status", "opening", "deadline", "budget", "grant", "scoring", "risks"], "2026-09-01T18:45:00+03:00"),
        source("AFIR — sesiuni primire proiecte", SESSIONS, ["status", "documents"], "2026-09-01T18:45:00+03:00"),
        source("AFIR — contor fonduri disponibile", COUNTER, ["status", "opening", "deadline", "budget"], "2026-09-01T18:45:00+03:00"),
    ]
    dossiers = [
        open_dossier(
            dossier_id="afir-dr14-2026", title="DR-14 — Investiții în fermele de mici dimensiuni", code="DR-14",
            applicants=applicants14,
            activities=["Investiții tangibile și intangibile legate de modernizarea exploatațiilor agricole mici.", "Componente: zootehnic, legumicultură, alte sectoare și achiziții simple."],
            budget="108.000.000 EUR", project_value="maximum 50.000 EUR/proiect; intensitate de maximum 85%", cofinancing="minimum 15%",
            scoring=["Prag minim 80 puncte în septembrie.", "Prag minim 40 puncte în octombrie."],
            documents=["Ghidul Solicitantului DR-14.", "Cererea de finanțare DR-14 — versiunea 1.1 din 2026.", "Fișa de evaluare E1.2 și anexele oficiale aplicabile componentei."],
            risks=["Sesiunea se poate închide înainte de termen la epuizarea fondurilor.", "O versiune veche a cererii nu poate fi încărcată în sistem.", "Încadrarea greșită pe componentă sau un punctaj sub pragul lunar blochează depunerea utilă."],
            sources=[*common_sources, source("AFIR — Detalii și Anexe DR-14", DR14, ["beneficiaries", "eligibility", "activities", "grant", "cofinancing", "documents", "scoring"], "2026-09-01T18:45:00+03:00")],
            standfirst="Sesiune deschisă pentru modernizarea fermelor mici: 108 milioane EUR în patru componente, maximum 50.000 EUR/proiect, intensitate de maximum 85% și termen 31 octombrie 2026, ora 16:00.",
        ),
        open_dossier(
            dossier_id="afir-dr18-2026", title="DR-18 — Investiții în floricultură, plante medicinale și aromatice", code="DR-18",
            applicants=applicants18,
            activities=["Înființarea, extinderea și modernizarea exploatațiilor specializate în flori, plante ornamentale, medicinale și aromatice, în câmp sau spații protejate.", "Utilaje și echipamente, condiționare și depozitare; procesarea, irigațiile și comercializarea la nivelul fermei pot fi componente secundare în condițiile ghidului."],
            budget="5.000.000 EUR", project_value="maximum 100.000 EUR/proiect; intensitate de 85% sau 65%, în funcție de dimensiunea economică", cofinancing="minimum 15% sau 35%, după dimensiunea economică",
            scoring=["Prag minim 70 puncte în septembrie.", "Prag minim 40 puncte în octombrie."],
            documents=["Ghidul Solicitantului DR-18.", "Cererea de finanțare DR-18 și anexele economico-financiare.", "Fișa de evaluare E1.2 și anexele oficiale aplicabile."],
            risks=["Sesiunea se poate închide înainte de termen la epuizarea fondurilor.", "Intensitatea diferă în funcție de dimensiunea economică a exploatației.", "Activitățile secundare trebuie păstrate în limitele și condițiile ghidului."],
            sources=[*common_sources, source("AFIR — Detalii și Anexe DR-18", DR18, ["beneficiaries", "eligibility", "activities", "grant", "cofinancing", "documents", "scoring"], "2026-09-01T18:45:00+03:00"), source("AFIR — comunicat ghid final DR-18", DR18_RELEASE, ["beneficiaries", "activities", "grant", "cofinancing"], "2026-09-01T18:45:00+03:00")],
            standfirst="Sesiune deschisă pentru floricultură, plante medicinale, aromatice și ornamentale: 5 milioane EUR, maximum 100.000 EUR/proiect și termen 31 octombrie 2026, ora 16:00.",
        ),
        dr31_dossier(),
        dr12_dossier(),
        energy_public_dossier(storage=False),
        energy_public_dossier(storage=True),
    ]

    replace_codes = {"dr 12", "dr 14", "dr 18", "dr 31"}
    kept = []
    for row in payload.get("dossiers") or []:
        code = norm(row.get("code"))
        title = norm(row.get("title"))
        if code in replace_codes or any(token in title for token in replace_codes):
            continue
        kept.append(row)

    energy_ids = {"afir-fm-public-autoconsum-2026", "afir-fm-public-storage-2026"}
    filtered_kept = []
    for row in kept:
        title = norm(row.get("title"))
        is_public_energy_duplicate = (
            row.get("id") in energy_ids
            or ("entitati publice" in title and ("autoconsum" in title or "stocare" in title))
        )
        if not is_public_energy_duplicate:
            filtered_kept.append(row)
    payload["dossiers"] = [*dossiers, *filtered_kept]

    replacement_news_ids = {row["id"] for row in news_items()}
    payload["news"] = [*news_items(), *[row for row in payload.get("news") or [] if row.get("id") not in replacement_news_ids]]
    payload.setdefault("policy", {})["afirCurrentSessionsSourceBound"] = True
    payload["policy"]["afirConsultationsNeverPresentedAsOpen"] = True
    payload["policy"]["afirEnergyPostLaunchEvidenceSourceBound"] = True
    dr12_open = next(row for row in dossiers if row.get("id") == "afir-dr12-2026").get("status") == "OPEN"
    payload["policy"]["afirDr12UpcomingSourceBound"] = not dr12_open
    payload["policy"]["afirDr12PostLaunchSourceBound"] = dr12_open
    payload.setdefault("qualityPass", {})["afirCurrentAuthoritativeDossiers"] = [row["id"] for row in dossiers]

    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"ok": True, "dossiers": [row["id"] for row in dossiers], "news": sorted(replacement_news_ids)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
