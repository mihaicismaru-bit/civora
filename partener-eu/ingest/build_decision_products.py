#!/usr/bin/env python3
"""Build decision-useful editorial products for PARTENER.EU.

The public site is not allowed to expose raw ingestion rows as news. This
builder projects the canonical P11 opportunity graph and the latest official
MIPE/AFIR observations into two products:

* a universal, source-grounded dossier for every identified call/opportunity;
* news only when an event changes a decision, action, deadline, guide or status.

Unknown material facts remain visibly unknown. Source-page discovery alone
never becomes an OPEN call. The output is static JSON/JavaScript so the whole
pipeline runs in the site engine and does not depend on a ChatGPT session.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
P11_PATH = ROOT / "partener-eu" / "web" / "p11-public-data.js"
MIPE_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
AFIR_PATH = ROOT / "partener-eu" / "ingest" / "state" / "afir_corpus.json"
OUT_JSON = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"

CRITICAL_FACTS = ["status", "deadline", "beneficiaries", "eligibility", "grant", "budget", "scoring"]
CALL_EVENT_KINDS = {
    "CALL_OPENED", "DEADLINE_EXTENDED", "GUIDE_PUBLISHED", "GUIDE_MODIFIED",
    "CONSULTATION_OPENED", "CALL_CLOSED", "RESULTS_PUBLISHED",
    "GUIDE_UPDATED_AFTER_CONSULTATION",
}
NEWS_EVENT_PRIORITY = {
    "DEADLINE_EXTENDED": 100,
    "CALL_OPENED": 98,
    "GUIDE_MODIFIED": 92,
    "GUIDE_UPDATED_AFTER_CONSULTATION": 90,
    "GUIDE_PUBLISHED": 82,
    "CONSULTATION_OPENED": 72,
    "CALL_CLOSED": 70,
    "RESULTS_PUBLISHED": 64,
    "OFFICIAL_UPDATE": 35,
}
STOPWORDS = {
    "pentru", "privind", "proiecte", "proiect", "apel", "apelul", "ghid", "ghidul",
    "solicitantului", "conditii", "condiții", "specifice", "program", "programul",
    "finantare", "finanțare", "fonduri", "europene", "romania", "românia", "si", "și",
    "din", "prin", "privind", "asupra", "catre", "către", "publicat", "lansat",
    "portalul", "informatii", "informații", "depunere", "online", "oficial", "oficiala",
}
LABELS = {
    "applicant_scope": "Solicitanți eligibili",
    "eligible_classes": "Clase eligibile",
    "applicant_conditions": "Condiții pentru solicitant",
    "partner_eligibility": "Parteneri",
    "project_conditions": "Condiții ale proiectului",
    "building_conditions": "Condiții privind clădirea",
    "technical_scope": "Domeniu tehnic",
    "state_aid_and_cost_rules": "Ajutor de stat și costuri",
    "site_rights": "Drepturi asupra amplasamentului",
    "implementation_period": "Perioadă de implementare",
    "sustainability": "Durabilitate",
    "employment_obligations": "Obligații de ocupare",
    "minimum_points": "Prag minim",
    "minimum_project_points": "Prag minim proiect",
    "maximum_points": "Punctaj maxim",
    "criteria": "Criterii",
    "tie_breaker": "Departajare",
    "eligible_costs": "Costuri eligibile",
    "ineligible_costs": "Costuri neeligibile",
    "beneficiaries": "Beneficiari",
    "minimum_eur": "Grant minim",
    "maximum_eur": "Grant maxim",
    "eligible_cost_intensity_percent": "Intensitate nerambursabilă",
    "applicant_minimum_contribution_percent": "Contribuție minimă solicitant",
    "total_eur": "Buget total",
    "session_total_eur": "Buget sesiune",
    "callBudgetRon": "Buget apel",
}
AUDIENCE_RULES = [
    (r"\bimm\b|microintrepr|microîntrepr|intreprinder|întreprinder", "firme și IMM-uri"),
    (r"\bong\b|asociati|asociați|fundati|fundați", "ONG-uri"),
    (r"furnizor.*formare|\bfpc\b|formare profesional", "furnizori de formare profesională"),
    (r"scoli|școli|unitati de invatamant|unități de învățământ|licee", "școli și unități de învățământ"),
    (r"universit", "universități"),
    (r"uat|autoritati publice|autorități publice|consilii judetene|consilii județene", "autorități publice"),
    (r"fermieri|ferme|exploatatii agricole|exploatații agricole", "fermieri și exploatații agricole"),
    (r"servicii sociale|furnizori social", "furnizori de servicii sociale"),
    (r"tineri neet|\bneet\b", "organizații care lucrează cu tineri NEET"),
    (r"clustere", "clustere"),
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_p11() -> dict[str, Any]:
    raw = P11_PATH.read_text(encoding="utf-8")
    match = re.search(r"window\.PARTENER_P11\s*=\s*(\{.*\})\s*;?\s*$", raw, re.S)
    if not match:
        raise RuntimeError("Cannot parse window.PARTENER_P11 payload")
    return json.loads(match.group(1))


def strip_diacritics(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(ch))


def norm_text(value: Any) -> str:
    text = strip_diacritics(str(value or "")).lower()
    text = re.sub(r"portalul afir.*$", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_title(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"\s*[-–—]\s*Portalul AFIR.*$", "", text, flags=re.I)
    text = re.sub(r"\s*[-–—]\s*Ministerul Investițiilor.*$", "", text, flags=re.I)
    return text.strip(" -–—")


def slug(value: str) -> str:
    text = norm_text(value)
    return re.sub(r"\s+", "-", text).strip("-")[:110] or "dossier"


def deterministic_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("\n".join(str(p or "") for p in parts).encode("utf-8")).hexdigest()[:18]
    return f"{prefix}-{digest}"


def title_tokens(value: str) -> set[str]:
    return {token for token in norm_text(value).split() if len(token) >= 3 and token not in STOPWORDS}


def extract_code(value: str) -> str | None:
    text = str(value or "")
    patterns = [
        r"\bDR\s*[-–]?\s*\d{1,3}\b",
        r"\bSTEP\s*[-–]?\s*(?:LLL|VET|EDU)\b",
        r"\bP\d{1,2}\s*/\s*ESO[\d.]+(?:\s*/\s*[\w.]+)?",
        r"\bPR[A-Z]{0,4}/[\w./-]{4,}\b",
        r"\b\d+(?:\.\d+){1,3}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return re.sub(r"\s+", "", match.group(0)).upper()
    return None


def official_url(url: str) -> bool:
    return bool(re.match(r"^https://(?:www\.)?(?:mfe\.gov\.ro|afir\.ro|reporting\.mysmis2021\.gov\.ro|oir\w*\.ro|runv\.ro)/", str(url or ""), re.I))


def format_number(value: Any) -> str:
    if isinstance(value, bool):
        return "Da" if value else "Nu"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


def label_key(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").strip().capitalize())


def primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def flatten(value: Any, prefix: str = "", limit: int = 24) -> list[str]:
    out: list[str] = []

    def walk(current: Any, path: str) -> None:
        if len(out) >= limit or current in (None, "", [], {}):
            return
        if primitive(current):
            label = path.strip()
            formatted = format_number(current)
            if label:
                if label.lower() in formatted.lower() and len(formatted) > 20:
                    out.append(formatted)
                else:
                    out.append(f"{label}: {formatted}")
            else:
                out.append(formatted)
            return
        if isinstance(current, list):
            for item in current:
                if len(out) >= limit:
                    break
                if primitive(item):
                    out.append(format_number(item))
                else:
                    walk(item, path)
            return
        if isinstance(current, dict):
            for key, item in current.items():
                if len(out) >= limit:
                    break
                next_path = f"{path} · {label_key(key)}" if path else label_key(key)
                walk(item, next_path)

    walk(value, prefix)
    return [re.sub(r"\s+", " ", line).strip() for line in out if str(line).strip()]


def first_scalar(value: Any) -> str | None:
    if primitive(value) and value not in (None, ""):
        return format_number(value)
    if isinstance(value, dict):
        preferred = [
            "maximum_eur", "minimum_eur", "eligible_cost_intensity_percent",
            "total_eur", "session_total_eur", "applicant_minimum_contribution_percent",
            "closes", "closes_at", "deadline_at", "close",
        ]
        parts: list[str] = []
        for key in preferred:
            if key in value and primitive(value[key]):
                suffix = " EUR" if key.endswith("_eur") else "%" if "percent" in key else ""
                parts.append(f"{label_key(key)} {format_number(value[key])}{suffix}")
        if parts:
            return " · ".join(parts[:3])
    return None


def deadline_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("closes_at", "closes", "deadline_at", "close", "end", "submission_end"):
            if value.get(key):
                return str(value[key])
    return None


def audience_from_text(*values: Any) -> list[str]:
    text = " ".join(str(value or "") for value in values)
    normalized = norm_text(text)
    audiences = [label for pattern, label in AUDIENCE_RULES if re.search(pattern, normalized, re.I)]
    return list(dict.fromkeys(audiences))[:6]


def status_view(status: str) -> tuple[str, str, str]:
    value = str(status or "REVIEW").upper()
    if value == "OPEN":
        return "OPEN", "ACT NOW", "Începe screeningul și planul de depunere pe ghidul final aplicabil."
    if value in {"EXPECTED", "ANNOUNCED"}:
        return "ÎN PREGĂTIRE", "PREPARE", "Pregătește profilul, parteneriatul și documentele, dar nu trata data estimată ca termen oficial."
    if value == "PUBLIC_CONSULTATION":
        return "CONSULTARE", "CONTRIBUTE / PREPARE", "Analizează proiectul de ghid și formulează observații; depunerea nu este încă deschisă."
    if value in {"CLOSED", "CANCELLED", "FINALIZAT"}:
        return "ÎNCHIS", "REFERENCE", "Nu mai investi resurse de depunere; folosește dosarul pentru monitorizare sau o eventuală relansare."
    if value in {"SUSPENDED"}:
        return "SUSPENDAT", "WAIT", "Oprește pregătirea ireversibilă și verifică actul oficial de suspendare."
    return "ÎN VERIFICARE", "VERIFY", "Nu lua o decizie materială până la confirmarea ghidului, statusului și termenului."


def fact_card(label: str, value: Any, confidence: str = "CONFIRMED") -> dict[str, str]:
    text = first_scalar(value) or (str(value) if value not in (None, "", {}, []) else "Neconfirmat")
    return {"label": label, "value": text, "confidence": confidence if text != "Neconfirmat" else "UNKNOWN"}


def section(title: str, items: Iterable[str], empty: str) -> dict[str, Any]:
    lines = [str(item).strip() for item in items if str(item).strip()]
    return {"title": title, "items": lines or [empty], "empty": not bool(lines)}


def p11_sources(item: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for evidence in item.get("verificationEvidence") or []:
        url = evidence.get("sourceUrl")
        if not url:
            continue
        sources.append({
            "label": f"Evidență oficială: {', '.join(evidence.get('supportedFactClasses') or ['fapte verificate'])}",
            "url": url,
            "tier": evidence.get("sourceTier") or "T1",
            "observedAt": evidence.get("observedAt"),
            "supports": evidence.get("supportedFactClasses") or [],
        })
    return sources


def build_p11_dossier(item: dict[str, Any], generated_at: str) -> dict[str, Any]:
    facts = item.get("materialFacts") or {}
    verified = set(item.get("verifiedFactClasses") or [])
    blocked = list((item.get("publicationDecision") or {}).get("blockedFactClasses") or [])
    status_label, decision, decision_action = status_view(item.get("status"))
    deadline = deadline_value(facts.get("deadline")) or item.get("deadline_at")
    beneficiaries = flatten(facts.get("beneficiaries"), limit=14)
    eligibility = facts.get("eligibility") or {}
    who = beneficiaries + flatten({k: v for k, v in eligibility.items() if any(token in k for token in ("applicant", "partner", "beneficiar"))}, limit=18)
    project_rules = flatten({k: v for k, v in eligibility.items() if any(token in k for token in ("project", "technical", "building", "activity", "geographic"))}, limit=20)
    technical = flatten(facts.get("technical_scope"), limit=18)
    activities = flatten(facts.get("activities") or facts.get("eligible_activities"), limit=18)
    costs = flatten(facts.get("costs") or facts.get("state_aid_and_cost_rules") or eligibility.get("state_aid_and_cost_rules"), limit=20)
    documents = flatten(facts.get("documents") or facts.get("required_documents"), limit=24)
    scoring = flatten(facts.get("scoring"), limit=24)
    indicators = flatten(facts.get("indicators"), limit=18)
    obligations = flatten({k: v for k, v in facts.items() if any(token in k for token in ("sustain", "ownership", "procurement", "employment", "implementation", "dnsh", "capacity"))}, limit=20)

    unknowns = [f"{label_key(name)} nu este încă autorizat pentru publicare." for name in blocked]
    for fact in CRITICAL_FACTS:
        if fact not in verified and fact not in blocked:
            unknowns.append(f"{label_key(fact)} nu este confirmat în proiecția publică actuală.")
    if not documents:
        unknowns.append("Lista completă a documentelor nu este încă structurată în corpus; se verifică în ghid și anexe.")

    risks = []
    if item.get("status") != "OPEN":
        risks.append("Confundarea unei consultări sau date estimate cu o fereastră oficială de depunere.")
    if "eligibility" not in verified:
        risks.append("Pornirea proiectării înainte de confirmarea clasei solicitantului, partenerilor și teritoriului eligibil.")
    if "deadline" not in verified:
        risks.append("Planificarea pe o dată neconfirmată sau depășită.")
    if "scoring" not in verified:
        risks.append("Decizia GO fără simularea grilei finale de evaluare.")
    risks.extend([
        "Folosirea unei versiuni vechi de ghid sau anexă fără verificarea corrigendumurilor.",
        "Buget și activități necorelate cu indicatorii și obligațiile post-contractuale.",
    ])

    actions = [
        decision_action,
        "Blochează în dosar versiunea ghidului, anexelor și corrigendumurilor folosite.",
        "Construiește o matrice hard-gate: solicitant, teritoriu, activitate, capacitate financiară, proprietate și ajutor de stat.",
        "Transformă cerințele documentare și riscurile în responsabilități și termene interne.",
    ]
    if scoring:
        actions.append("Simulează punctajul înainte de decizia GO/NO-GO și documentează fiecare criteriu.")
    if deadline:
        actions.append(f"Planifică depunerea pornind de la termenul confirmat: {deadline}.")

    sources = p11_sources(item)
    evidence_count = len(sources)
    completeness = round(100 * len(verified & set(CRITICAL_FACTS)) / len(CRITICAL_FACTS))
    audience = beneficiaries[:5] or audience_from_text(item.get("title"), json.dumps(facts, ensure_ascii=False))
    grant = facts.get("grant")
    budget = facts.get("budget")
    cofinance = None
    if isinstance(grant, dict):
        cofinance = grant.get("applicant_minimum_contribution_percent")
    if cofinance is None and isinstance(facts.get("cofinancing"), (dict, str, int, float)):
        cofinance = facts.get("cofinancing")

    confirmed_parts = []
    if item.get("status"):
        confirmed_parts.append(status_label.lower())
    if deadline and "deadline" in verified:
        confirmed_parts.append(f"termen {deadline}")
    grant_scalar = first_scalar(grant)
    if grant_scalar and "grant" in verified:
        confirmed_parts.append(grant_scalar)
    standfirst = (
        f"{item.get('title')}. "
        + ("Sunt confirmate: " + "; ".join(confirmed_parts) + "." if confirmed_parts else "Faptele materiale sunt încă în verificare documentară.")
    )

    return {
        "id": item.get("id"),
        "sourceType": "CANONICAL_P11",
        "title": item.get("title"),
        "slug": slug(f"{item.get('id')} {item.get('title')}"),
        "programme": item.get("programme") or "Program de finanțare",
        "code": item.get("code") or extract_code(item.get("title", "")) or "—",
        "region": item.get("region") or "România",
        "status": item.get("status") or "REVIEW",
        "statusLabel": status_label,
        "decision": decision,
        "decisionAction": decision_action,
        "publicationState": item.get("publicationState") or "REVIEW_REQUIRED",
        "standfirst": standfirst,
        "audience": audience,
        "quickFacts": [
            fact_card("Status", status_label, "CONFIRMED" if "status" in verified else "REVIEW"),
            fact_card("Termen", deadline, "CONFIRMED" if "deadline" in verified else "UNKNOWN"),
            fact_card("Grant", grant, "CONFIRMED" if "grant" in verified else "UNKNOWN"),
            fact_card("Buget", budget, "CONFIRMED" if "budget" in verified else "UNKNOWN"),
            fact_card("Contribuție proprie", cofinance, "CONFIRMED" if cofinance is not None and "grant" in verified else "UNKNOWN"),
            fact_card("Completitudine critică", f"{completeness}%", "SYSTEM"),
        ],
        "sections": [
            section("Decizia rapidă", [decision_action, f"Stare editorială: {item.get('publicationState') or 'REVIEW_REQUIRED'}."], "Decizia necesită verificare."),
            section("Cine poate aplica", who, "Solicitanții eligibili nu sunt încă structurați complet."),
            section("Ce finanțează și în ce condiții", activities + technical + project_rules, "Activitățile și condițiile tehnice trebuie citite în ghidul final."),
            section("Costuri, cofinanțare și ajutor de stat", costs, "Regulile financiare nu sunt încă structurate complet."),
            section("Documente de pregătit", documents, "Lista exactă se verifică în ghid și anexe."),
            section("Cum se punctează", scoring, "Grila finală nu este încă structurată sau autorizată pentru publicare."),
            section("Indicatori și obligații", indicators + obligations, "Indicatorii și obligațiile trebuie verificați în documentația finală."),
            section("Riscuri de respingere sau implementare", risks, "Riscurile specifice sunt în verificare."),
            section("Ce trebuie făcut acum", actions, "Monitorizează sursa oficială."),
            section("Ce nu este încă confirmat", unknowns, "Nu există necunoscute materiale în proiecția curentă."),
        ],
        "timeline": [
            {
                "date": source.get("observedAt") or generated_at,
                "kind": "EVIDENCE_OBSERVED",
                "text": source.get("label"),
            }
            for source in sources
        ],
        "sources": sources,
        "quality": {
            "completeness": completeness,
            "verifiedFactClasses": sorted(verified),
            "blockedFactClasses": blocked,
            "evidenceCount": evidence_count,
            "failClosed": True,
        },
        "updatedAt": item.get("asOf") or generated_at,
    }


def afir_page_class(item: dict[str, Any]) -> str:
    explicit = str(item.get("pageClass") or "").upper()
    if explicit in {"INTERVENTION_OR_CALL", "SESSION", "GUIDE", "CALL_CANDIDATE", "DOCUMENT"}:
        return explicit
    value = norm_text(f"{item.get('title')} {item.get('url')}")
    if re.search(r"\bdr\s*\d{1,3}\b", value) or "schema de energie" in value or "investalim" in value:
        return "INTERVENTION_OR_CALL"
    if any(token in value for token in ("sesiune depunere", "sesiuni primire", "anunturilor de primire")):
        return "SESSION"
    if any(token in value for token in ("ghidul si anexele", "detalii si anexe", "ghid solicitant")):
        return "GUIDE"
    if any(token in value for token in ("apel", "interventie", "transfer de cunostinte")):
        return "CALL_CANDIDATE"
    return "GENERIC_SOURCE_PAGE"


def mipe_call_like(item: dict[str, Any]) -> bool:
    if str(item.get("pageClass") or "").upper() in {"CALL_OR_GUIDE", "INTERVENTION_OR_CALL", "SESSION", "GUIDE", "CALL_CANDIDATE"}:
        return True
    if item.get("kind") in CALL_EVENT_KINDS:
        return True
    value = norm_text(f"{item.get('title')} {item.get('url')}")
    return any(token in value for token in ("apel", "ghid", "step lll", "step vet", "universitati deschise", "interventie"))


def afir_call_like(item: dict[str, Any]) -> bool:
    return afir_page_class(item) != "GENERIC_SOURCE_PAGE"


def dossier_similarity(raw_title: str, raw_code: str | None, dossier: dict[str, Any]) -> float:
    raw_tokens = title_tokens(raw_title)
    dossier_tokens = title_tokens(dossier.get("title", ""))
    code_a = raw_code or extract_code(raw_title)
    code_b = dossier.get("code") or extract_code(dossier.get("title", ""))
    if code_a and code_b and norm_text(code_a) == norm_text(code_b):
        return 1.0
    if not raw_tokens or not dossier_tokens:
        return 0.0
    return len(raw_tokens & dossier_tokens) / len(raw_tokens | dossier_tokens)


def best_match(title: str, dossiers: list[dict[str, Any]], code: str | None = None) -> tuple[dict[str, Any] | None, float]:
    scored = [(dossier_similarity(title, code, dossier), dossier) for dossier in dossiers]
    scored.sort(key=lambda row: row[0], reverse=True)
    if scored and scored[0][0] >= 0.46:
        return scored[0][1], scored[0][0]
    return None, scored[0][0] if scored else 0.0


def event_meaning(kind: str) -> str:
    return {
        "DEADLINE_EXTENDED": "Calendarul de pregătire și toate referințele la termen trebuie actualizate imediat.",
        "CALL_OPENED": "Există o fereastră de depunere activă; screeningul și planul de proiect pot începe numai pe ghidul final.",
        "GUIDE_MODIFIED": "Condițiile folosite anterior pot fi depășite; eligibilitatea, bugetul, punctajul și anexele trebuie comparate cu noua versiune.",
        "GUIDE_UPDATED_AFTER_CONSULTATION": "Forma finală poate diferi material de proiectul consultat; analiza trebuie refăcută pe documentul aprobat.",
        "GUIDE_PUBLISHED": "Pregătirea poate începe, dar ghidul publicat nu dovedește singur că sesiunea este OPEN.",
        "CONSULTATION_OPENED": "Este momentul pentru analiză și observații, nu pentru depunere.",
        "CALL_CLOSED": "Fereastra de depunere s-a închis; rămân relevante rezultatele, contractarea și o eventuală relansare.",
        "RESULTS_PUBLISHED": "Rezultatele permit evaluarea concurenței și a tipului de proiecte selectate, dar nu redeschid apelul.",
    }.get(kind, "Informația trebuie legată de apelul și documentele aplicabile înainte de a produce o decizie.")


def event_actions(kind: str) -> list[str]:
    mapping = {
        "DEADLINE_EXTENDED": ["Actualizează calendarul intern și toate comunicările.", "Verifică dacă prelungirea a venit cu un corrigendum sau alte modificări."],
        "CALL_OPENED": ["Execută screeningul hard-gate al solicitantului și proiectului.", "Descarcă ghidul final și anexele exact în versiunea publicată la lansare.", "Fixează responsabilitățile și termenul intern de depunere."],
        "GUIDE_MODIFIED": ["Compară versiunea nouă cu cea folosită anterior.", "Refă simularea de eligibilitate, buget și punctaj.", "Arhivează versiunea înlocuită, fără suprascriere."],
        "GUIDE_PUBLISHED": ["Citește ghidul și construiește matricea de eligibilitate.", "Așteaptă anunțul oficial al sesiunii dacă depunerea nu este confirmată."],
        "CONSULTATION_OPENED": ["Analizează proiectul de ghid și formulează observații documentate.", "Pregătește datele clientului fără a prezenta apelul ca deschis."],
        "CALL_CLOSED": ["Oprește pregătirea pentru această sesiune.", "Monitorizează rezultatele, contractarea și eventualele realocări."],
    }
    return mapping.get(kind, ["Deschide sursa oficială și stabilește ce obiect canonic trebuie actualizat."])


def provisional_dossier(source: str, item: dict[str, Any], generated_at: str) -> dict[str, Any]:
    title = clean_title(item.get("title")) or "Oportunitate identificată în sursa oficială"
    kind = item.get("kind") or ("GUIDE_PUBLISHED" if afir_page_class(item) == "GUIDE" else "OFFICIAL_UPDATE")
    if kind == "CALL_OPENED":
        status = "OPEN"
    elif kind == "CONSULTATION_OPENED":
        status = "PUBLIC_CONSULTATION"
    elif kind in {"CALL_CLOSED", "RESULTS_PUBLISHED"}:
        status = "CLOSED"
    else:
        status = "REVIEW"
    status_label, decision, decision_action = status_view(status)
    summary = re.sub(r"\s+", " ", str(item.get("summary") or item.get("textPreview") or "")).strip()
    documents = item.get("documents") or item.get("documentLinks") or []
    source_url = item.get("url")
    source_tier = item.get("tier") or "T1"
    audience = audience_from_text(title, summary)
    confirmed = [
        f"Sursa oficială identificată: {source_url}.",
        f"Tipul evenimentului detectat: {kind}.",
    ]
    if item.get("dateLabel"):
        confirmed.append(f"Data afișată/extrasă: {item.get('dateLabel')}.")
    if documents:
        confirmed.append(f"Au fost identificate {len(documents)} documente sau anexe oficiale.")
    unknowns = [
        "Termenul oficial de depunere nu este structurat complet.",
        "Bugetul, grantul și contribuția proprie nu sunt confirmate în acest obiect.",
        "Clasele exacte de solicitanți și parteneri trebuie verificate în ghidul final.",
        "Grila de evaluare, indicatorii și obligațiile post-contractuale trebuie extrase din documentație.",
    ]
    risks = [
        "Confundarea publicării unui ghid sau a unei pagini de intervenție cu deschiderea efectivă a sesiunii.",
        "Luarea unei decizii pe baza titlului paginii fără citirea anexelor.",
        "Folosirea unei copii sau versiuni vechi a documentației.",
    ]
    source_obj = {
        "label": f"{source} — sursă oficială",
        "url": source_url,
        "tier": source_tier,
        "observedAt": item.get("observedAt") or generated_at,
        "supports": ["source_event"],
    }
    doc_sources = [
        {
            "label": doc.get("name") or "Document oficial",
            "url": doc.get("url") or source_url,
            "tier": source_tier,
            "observedAt": item.get("observedAt") or generated_at,
            "supports": ["document"],
        }
        for doc in documents[:30]
        if isinstance(doc, dict)
    ]
    dossier_id = deterministic_id(source.lower(), source_url, title)
    return {
        "id": dossier_id,
        "sourceType": f"{source}_INGESTED_PROVISIONAL",
        "title": title,
        "slug": slug(f"{dossier_id} {title}"),
        "programme": item.get("tag") or ("AFIR / PS PAC 2023-2027" if source == "AFIR" else "MIPE"),
        "code": extract_code(title) or "—",
        "region": "România",
        "status": status,
        "statusLabel": status_label,
        "decision": decision,
        "decisionAction": decision_action,
        "publicationState": "PROVISIONAL_FAIL_CLOSED",
        "standfirst": summary[:900] or f"{title}. Sursa oficială a fost identificată, iar condițiile materiale sunt încă în structurare.",
        "audience": audience,
        "quickFacts": [
            fact_card("Status", status_label, "EVENT_INFERRED" if status != "REVIEW" else "UNKNOWN"),
            fact_card("Termen", None),
            fact_card("Grant", None),
            fact_card("Buget", None),
            fact_card("Documente găsite", len(documents), "SYSTEM"),
            fact_card("Completitudine critică", "14%", "SYSTEM"),
        ],
        "sections": [
            section("Decizia rapidă", [event_meaning(kind), decision_action], "Este necesară verificarea manuală."),
            section("Ce este confirmat", confirmed, "Este confirmată doar existența sursei oficiale."),
            section("Cine poate aplica", [], "Clasele exacte de solicitanți nu sunt încă extrase din ghid."),
            section("Ce finanțează și în ce condiții", [summary] if summary else [], "Activitățile eligibile trebuie extrase din documentația oficială."),
            section("Costuri, cofinanțare și ajutor de stat", [], "Regulile financiare nu sunt încă confirmate."),
            section("Documente de pregătit", [doc.get("name") or doc.get("url") for doc in documents if isinstance(doc, dict)], "Documentele nu sunt încă indexate complet."),
            section("Cum se punctează", [], "Grila de evaluare nu este încă extrasă."),
            section("Indicatori și obligații", [], "Indicatorii și obligațiile nu sunt încă extrase."),
            section("Riscuri de respingere sau implementare", risks, "Riscurile specifice sunt în verificare."),
            section("Ce trebuie făcut acum", event_actions(kind) + ["Deschide documentele oficiale și completează matricea de eligibilitate."], "Monitorizează sursa."),
            section("Ce nu este încă confirmat", unknowns, "Nu există necunoscute."),
        ],
        "timeline": [{"date": item.get("date") or item.get("observedAt") or generated_at, "kind": kind, "text": title}],
        "sources": [source_obj, *doc_sources],
        "quality": {
            "completeness": 14,
            "verifiedFactClasses": ["source_event"],
            "blockedFactClasses": CRITICAL_FACTS,
            "evidenceCount": 1 + len(doc_sources),
            "failClosed": True,
        },
        "updatedAt": item.get("observedAt") or generated_at,
    }


def merge_source_into_dossier(dossier: dict[str, Any], source: str, item: dict[str, Any], score: float) -> None:
    url = item.get("url")
    if url and not any(existing.get("url") == url for existing in dossier.get("sources", [])):
        dossier.setdefault("sources", []).append({
            "label": f"{source} — {clean_title(item.get('title'))}",
            "url": url,
            "tier": item.get("tier") or "T1",
            "observedAt": item.get("observedAt"),
            "supports": ["source_event"],
        })
    for doc in item.get("documents") or item.get("documentLinks") or []:
        if not isinstance(doc, dict) or not doc.get("url"):
            continue
        if any(existing.get("url") == doc.get("url") for existing in dossier.get("sources", [])):
            continue
        dossier.setdefault("sources", []).append({
            "label": doc.get("name") or "Document oficial",
            "url": doc.get("url"),
            "tier": item.get("tier") or "T1",
            "observedAt": item.get("observedAt"),
            "supports": ["document"],
        })
    dossier.setdefault("sourceLinks", []).append({"source": source, "itemId": item.get("id"), "matchScore": round(score, 3)})
    if item.get("kind") in CALL_EVENT_KINDS:
        dossier.setdefault("timeline", []).append({
            "date": item.get("date") or item.get("observedAt"),
            "kind": item.get("kind"),
            "text": clean_title(item.get("title")),
        })


def news_from_mipe(item: dict[str, Any], dossier_id: str | None, generated_at: str) -> dict[str, Any] | None:
    title = clean_title(item.get("title"))
    if not title:
        return None
    kind = item.get("kind") or "OFFICIAL_UPDATE"
    if title.lower().startswith("mysmis official funding registry changed"):
        changes = [part.strip() for part in str(item.get("summary") or "").split(" | ") if part.strip()]
        return {
            "id": deterministic_id("news-mysmis", item.get("observedAt"), title),
            "kind": "REGISTRY_CHANGED",
            "programme": "MySMIS",
            "date": item.get("date") or item.get("observedAt") or generated_at,
            "headline": "MySMIS: raportarea oficială s-a modificat pentru mai multe apeluri",
            "standfirst": f"Au fost detectate modificări în raportarea contractelor sau bugetelor pentru {max(1, len(changes))} apeluri. Acestea sunt semnale de implementare și contractare, nu lansări noi.",
            "meaning": "Schimbările arată evoluția portofoliului raportat în MySMIS. Ele nu modifică singure eligibilitatea, deadline-ul sau statusul juridic al unui apel.",
            "audience": ["beneficiari și consultanți care urmăresc contractarea"],
            "confirmed": changes[:6] or ["Registrul oficial MySMIS a publicat valori diferite față de snapshotul anterior."],
            "notConfirmed": ["Nu rezultă automat un apel nou sau o redeschidere.", "Statusul fiecărui apel rămâne cel afișat literal de sursa oficială."],
            "actions": ["Deschide dosarul apelului relevant înainte de orice concluzie.", "Folosește modificarea ca semnal de monitorizare, nu ca verdict de eligibilitate."],
            "dossierId": dossier_id,
            "source": {"label": "Registrul oficial MySMIS", "url": item.get("url"), "tier": item.get("tier") or "T1"},
            "utilityScore": 68,
        }
    if kind not in CALL_EVENT_KINDS:
        return None
    audience = audience_from_text(title, item.get("summary"))
    meaning = event_meaning(kind)
    actions = event_actions(kind)
    summary = str(item.get("summary") or "").strip()
    headline_templates = {
        "DEADLINE_EXTENDED": f"{title}: termenul a fost prelungit",
        "CALL_OPENED": f"{title}: apelul a fost lansat",
        "GUIDE_MODIFIED": f"{title}: documentația a fost modificată",
        "GUIDE_UPDATED_AFTER_CONSULTATION": f"{title}: forma finală diferă de versiunea consultată",
        "GUIDE_PUBLISHED": f"{title}: ghidul a fost publicat",
        "CONSULTATION_OPENED": f"{title}: consultarea publică a început",
        "CALL_CLOSED": f"{title}: sesiunea s-a închis",
        "RESULTS_PUBLISHED": f"{title}: au fost publicate rezultate",
    }
    return {
        "id": deterministic_id("news-mipe", item.get("url"), kind, item.get("date")),
        "kind": kind,
        "programme": item.get("tag") or "MIPE",
        "date": item.get("date") or item.get("observedAt") or generated_at,
        "headline": headline_templates.get(kind, title),
        "standfirst": summary[:700] or meaning,
        "meaning": meaning,
        "audience": audience or ["solicitanții și partenerii eligibili ai apelului"],
        "confirmed": [f"Eveniment oficial: {kind.replace('_', ' ')}.", f"Sursa canonică: {item.get('url')}."],
        "notConfirmed": ["Condițiile care nu apar explicit în sursă rămân neconfirmate și trebuie verificate în ghid/anexe."],
        "actions": actions,
        "dossierId": dossier_id,
        "source": {"label": f"MIPE — {title}", "url": item.get("url"), "tier": item.get("tier") or "T1"},
        "utilityScore": NEWS_EVENT_PRIORITY.get(kind, 50),
    }


def news_from_afir(item: dict[str, Any], dossier_id: str | None, generated_at: str) -> dict[str, Any] | None:
    if not item.get("changedFromPrevious"):
        return None
    title = clean_title(item.get("title"))
    material = bool(item.get("materialChangeCandidate"))
    return {
        "id": deterministic_id("news-afir", item.get("url"), item.get("sha256")),
        "kind": "MATERIAL_PAGE_CHANGED" if material else "SOURCE_PAGE_CHANGED",
        "programme": "AFIR",
        "date": item.get("observedAt") or generated_at,
        "headline": f"AFIR a modificat pagina „{title}”" + (": condițiile trebuie reverificate" if material else ""),
        "standfirst": "A fost detectată o versiune diferită a paginii oficiale. Sistemul nu transformă diferența de hash într-o schimbare de eligibilitate sau termen fără verificarea conținutului.",
        "meaning": "Documentația folosită într-un proiect poate fi depășită. Versiunea curentă trebuie comparată înainte de continuarea pregătirii.",
        "audience": audience_from_text(title) or ["beneficiarii și consultanții care folosesc această intervenție"],
        "confirmed": ["Conținutul oficial are un fingerprint diferit de rularea anterioară.", f"Acțiune materială automată: {item.get('materialFactAction') or 'NONE'}."],
        "notConfirmed": ["Nu este confirmat automat că s-au schimbat deadline-ul, bugetul, eligibilitatea sau punctajul."],
        "actions": ["Deschide pagina și documentele curente.", "Compară faptele materiale cu versiunea arhivată.", "Actualizează dosarul numai după confirmare."],
        "dossierId": dossier_id,
        "source": {"label": f"AFIR — {title}", "url": item.get("url"), "tier": "T1"},
        "utilityScore": 88 if material else 58,
    }


def dedupe_news(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for item in sorted(items, key=lambda row: (row.get("date") or "", row.get("utilityScore") or 0), reverse=True):
        key = norm_text(f"{item.get('headline')} {item.get('kind')}")
        if key in seen:
            continue
        seen.add(key)
        if (item.get("utilityScore") or 0) < 60:
            continue
        if not item.get("meaning") or not item.get("actions") or not item.get("source", {}).get("url"):
            continue
        out.append(item)
    return out[:60]


def stable_generated_at(p11: dict[str, Any], mipe: dict[str, Any], afir: dict[str, Any]) -> str:
    """Return a deterministic product version from source snapshot times."""
    candidates = [
        p11.get("asOf"),
        (mipe.get("lastRun") or {}).get("observedAt"),
        mipe.get("observedAt"),
        afir.get("observedAt"),
    ]
    for item in mipe.get("items") or []:
        candidates.append(item.get("observedAt") or item.get("date"))
    for item in afir.get("items") or []:
        candidates.append(item.get("observedAt"))

    parsed: list[dt.datetime] = []
    for value in candidates:
        if not value:
            continue
        try:
            stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=dt.timezone.utc)
            parsed.append(stamp.astimezone(dt.timezone.utc))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return "1970-01-01T00:00:00Z"
    return max(parsed).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    p11 = load_p11()
    mipe = read_json(MIPE_PATH, {"items": []})
    afir = read_json(AFIR_PATH, {"items": []})
    generated_at = stable_generated_at(p11, mipe, afir)

    dossiers = [build_p11_dossier(item, generated_at) for item in p11.get("opportunities") or []]
    coverage = {
        "p11": {"candidates": len(p11.get("opportunities") or []), "dossiers": len(dossiers)},
        "mipe": {"candidates": 0, "matched": 0, "provisional": 0},
        "afir": {"candidates": 0, "matched": 0, "provisional": 0},
    }
    news: list[dict[str, Any]] = []

    for item in mipe.get("items") or []:
        call_like = mipe_call_like(item)
        if call_like:
            coverage["mipe"]["candidates"] += 1
            match, score = best_match(clean_title(item.get("title")), dossiers, extract_code(item.get("title", "")))
            if match:
                coverage["mipe"]["matched"] += 1
                merge_source_into_dossier(match, "MIPE", item, score)
                dossier_id = match["id"]
            else:
                dossier = provisional_dossier("MIPE", item, generated_at)
                dossiers.append(dossier)
                coverage["mipe"]["provisional"] += 1
                dossier_id = dossier["id"]
        else:
            dossier_id = None
        story = news_from_mipe(item, dossier_id, generated_at)
        if story:
            news.append(story)

    for item in afir.get("items") or []:
        if not afir_call_like(item):
            continue
        coverage["afir"]["candidates"] += 1
        title = clean_title(item.get("title"))
        match, score = best_match(title, dossiers, extract_code(title))
        if match:
            coverage["afir"]["matched"] += 1
            merge_source_into_dossier(match, "AFIR", item, score)
            dossier_id = match["id"]
        else:
            dossier = provisional_dossier("AFIR", item, generated_at)
            dossiers.append(dossier)
            coverage["afir"]["provisional"] += 1
            dossier_id = dossier["id"]
        story = news_from_afir(item, dossier_id, generated_at)
        if story:
            news.append(story)

    # Deterministic ordering and source deduplication.
    dossier_by_id: dict[str, dict[str, Any]] = {}
    for dossier in dossiers:
        sources = []
        source_seen = set()
        for source in dossier.get("sources") or []:
            url = source.get("url")
            if not url or url in source_seen:
                continue
            source_seen.add(url)
            sources.append(source)
        dossier["sources"] = sources
        dossier["timeline"] = sorted(
            [row for row in dossier.get("timeline") or [] if row.get("date")],
            key=lambda row: str(row.get("date")),
            reverse=True,
        )[:40]
        dossier_by_id[dossier["id"]] = dossier
    dossiers = list(dossier_by_id.values())
    rank = {"OPEN": 0, "EXPECTED": 1, "PUBLIC_CONSULTATION": 2, "REVIEW": 3, "CLOSED": 6}
    dossiers.sort(key=lambda row: (rank.get(row.get("status"), 4), -(row.get("quality", {}).get("completeness") or 0), row.get("title") or ""))
    news = dedupe_news(news)

    open_ids = [row["id"] for row in dossiers if row.get("status") == "OPEN" and row.get("quality", {}).get("completeness", 0) >= 40][:8]
    prepare_ids = [row["id"] for row in dossiers if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}][:8]
    change_ids = [row["id"] for row in news[:8]]
    output = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "policy": {
            "decisionUsefulnessOverVolume": True,
            "rawIngestionRowsAreNews": False,
            "everyIdentifiedCallGetsDossier": True,
            "openRequiresAuthoritativeEvidence": True,
            "unknownFactsRemainVisible": True,
            "failClosed": True,
        },
        "summary": {
            "dossierCount": len(dossiers),
            "openCount": sum(1 for row in dossiers if row.get("status") == "OPEN"),
            "prepareCount": sum(1 for row in dossiers if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}),
            "newsCount": len(news),
            "highCompletenessCount": sum(1 for row in dossiers if row.get("quality", {}).get("completeness", 0) >= 70),
        },
        "coverage": coverage,
        "home": {"openDossierIds": open_ids, "prepareDossierIds": prepare_ids, "changeNewsIds": change_ids},
        "dossiers": dossiers,
        "news": news,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS="
        + json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )
    print(json.dumps({"summary": output["summary"], "coverage": coverage}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
