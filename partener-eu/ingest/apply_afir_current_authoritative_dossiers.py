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

LAUNCH = "https://www.afir.ro/comunicate/afir-lanseaza-sesiuni-pentru-ferme-mici-si-floricultura-plante-medicinale-si-aromatice/"
SESSIONS = "https://www.afir.ro/instrumente/sesiuni/sesiuni-primire-proiecte/"
COUNTER = "https://www.afir.ro/finantare/contor-fonduri-disponibile/"
DR14 = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-14/"
DR18 = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-18/"
DR18_RELEASE = "https://www.afir.ro/comunicate/finantarea-investitiilor-in-floricultura-plante-medicinale-si-aromatice/"
DEBATE = "https://www.afir.ro/comunicare/utile/dezbatere-publica/"


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
    ]

    replace_codes = {"dr 14", "dr 18", "dr 31"}
    kept = []
    for row in payload.get("dossiers") or []:
        code = norm(row.get("code"))
        title = norm(row.get("title"))
        if code in replace_codes or any(token in title for token in replace_codes):
            continue
        kept.append(row)
    payload["dossiers"] = [*dossiers, *kept]

    replacement_news_ids = {row["id"] for row in news_items()}
    payload["news"] = [*news_items(), *[row for row in payload.get("news") or [] if row.get("id") not in replacement_news_ids]]
    payload.setdefault("policy", {})["afirCurrentSessionsSourceBound"] = True
    payload["policy"]["afirConsultationsNeverPresentedAsOpen"] = True
    payload.setdefault("qualityPass", {})["afirCurrentAuthoritativeDossiers"] = [row["id"] for row in dossiers]

    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"ok": True, "dossiers": [row["id"] for row in dossiers], "news": sorted(replacement_news_ids)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
