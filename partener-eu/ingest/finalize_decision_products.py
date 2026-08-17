#!/usr/bin/env python3
"""Final deterministic cleanup for PARTENER.EU decision products.

Product contract enforced here:
- "Cine poate aplica" contains only applicant/partner entities explicitly
  authorized by official guide-backed beneficiary evidence.
- every funding dossier starts with a deterministic "Rezumat executiv".
- missing material facts remain visibly unconfirmed; no heuristic promotion.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"
P11 = ROOT / "partener-eu" / "web" / "p11-public-data.js"
MIPE_CANONICAL = ROOT / "partener-eu" / "ingest" / "state" / "mipe_canonical_calls.json"

UNKNOWN = "Neconfirmat în ghidul structurat."
WHO_UNKNOWN = "Neconfirmat — lista solicitanților eligibili nu este încă extrasă cu evidență explicită din ghidul oficial."

NON_APPLICANT_MARKERS = (
    "target scope",
    "target group",
    "grup tinta",
    "public tinta",
    "beneficiari finali",
    "persoane vizate",
    "excluded",
    "excluderi",
    "ineligible",
    "neeligibil",
    "nu sunt eligibile",
    "nu este eligibil",
    "nu pot aplica",
)

TARGET_MARKERS = (
    "target scope",
    "target group",
    "grup tinta",
    "public tinta",
    "beneficiari finali",
    "persoane vizate",
)

PLACEHOLDER_MARKERS = (
    "nu sunt inca",
    "nu este inca",
    "trebuie verific",
    "neconfirmat",
    "in verificare",
)


def norm(value: Any) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", text).lower()).strip()


def urls(dossier: dict[str, Any]) -> set[str]:
    return {source.get("url") for source in dossier.get("sources") or [] if source.get("url")}


def merge(target: dict[str, Any], duplicate: dict[str, Any]) -> None:
    seen = urls(target)
    for source in duplicate.get("sources") or []:
        if source.get("url") and source["url"] not in seen:
            target.setdefault("sources", []).append(source)
            seen.add(source["url"])
    timeline_seen = {(row.get("date"), row.get("kind"), row.get("text")) for row in target.get("timeline") or []}
    for row in duplicate.get("timeline") or []:
        key = (row.get("date"), row.get("kind"), row.get("text"))
        if key not in timeline_seen:
            target.setdefault("timeline", []).append(row)
            timeline_seen.add(key)
    target.setdefault("sourceLinks", []).extend(duplicate.get("sourceLinks") or [])


def same_opportunity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if urls(a) & urls(b):
        return True
    title_a, title_b = norm(a.get("title")), norm(b.get("title"))
    if title_a == "schema de energie" and all(token in title_b for token in ("energie", "autoconsum")):
        return True
    if title_b == "schema de energie" and all(token in title_a for token in ("energie", "autoconsum")):
        return True
    code_a, code_b = norm(a.get("code")), norm(b.get("code"))
    if code_a and code_b and code_a not in {"—", ""} and code_a == code_b:
        return True
    return False


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_p11() -> dict[str, Any]:
    try:
        raw = P11.read_text(encoding="utf-8")
    except Exception:
        return {}
    match = re.search(r"window\.PARTENER_P11\s*=\s*(\{.*\})\s*;?\s*$", raw, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except Exception:
        return {}


def collect_strings(value: Any, *, limit: int = 40) -> list[str]:
    out: list[str] = []

    def walk(node: Any) -> None:
        if len(out) >= limit or node in (None, "", [], {}):
            return
        if isinstance(node, str):
            text = re.sub(r"\s+", " ", node).strip()
            if text:
                out.append(text)
            return
        if isinstance(node, (int, float, bool)):
            out.append(str(node))
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for row in out:
        key = norm(row)
        if key and key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped[:limit]


def fact_authorized(source: dict[str, Any] | None, fact: str) -> bool:
    if not source:
        return False
    verified = set(source.get("verifiedFactClasses") or [])
    if fact not in verified:
        return False
    evidence = source.get("verificationEvidence") or []
    return any(
        fact in set(row.get("supportedFactClasses") or [])
        and bool(row.get("sourceUrl"))
        for row in evidence
        if isinstance(row, dict)
    )


def non_applicant(value: str) -> bool:
    folded = norm(value)
    return any(norm(marker) in folded for marker in NON_APPLICANT_MARKERS)


def target_line(value: str) -> bool:
    folded = norm(value)
    return any(norm(marker) in folded for marker in TARGET_MARKERS)


def explicit_applicants(source: dict[str, Any] | None) -> list[str]:
    if not fact_authorized(source, "beneficiaries"):
        return []
    facts = source.get("materialFacts") or {}
    candidates = collect_strings(facts.get("beneficiaries"), limit=30)
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if non_applicant(candidate):
            continue
        key = norm(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def extract_target_groups(source: dict[str, Any] | None, old_audience: Iterable[str]) -> list[str]:
    out: list[str] = []
    if source:
        facts = source.get("materialFacts") or {}
        beneficiaries = collect_strings(facts.get("beneficiaries"), limit=30)
        out.extend(row for row in beneficiaries if target_line(row))

        def walk(node: Any, key_hint: str = "") -> None:
            if len(out) >= 12:
                return
            if isinstance(node, dict):
                for key, value in node.items():
                    folded = norm(key)
                    if any(norm(marker) in folded for marker in TARGET_MARKERS):
                        out.extend(collect_strings(value, limit=8))
                    else:
                        walk(value, key)
            elif isinstance(node, list):
                for value in node:
                    walk(value, key_hint)

        walk(facts)

    out.extend(row for row in old_audience if target_line(str(row)))
    deduped: list[str] = []
    seen: set[str] = set()
    for row in out:
        text = re.sub(r"\s+", " ", str(row or "")).strip()
        key = norm(text)
        if key and key not in seen:
            seen.add(key)
            deduped.append(text)
    return deduped[:6]


def source_maps() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    p11 = load_p11()
    p11_rows = {
        row.get("id"): row
        for row in p11.get("opportunities") or []
        if isinstance(row, dict) and row.get("id")
    }
    mipe = read_json(MIPE_CANONICAL, {})
    mipe_rows = {
        row.get("id"): row
        for row in mipe.get("calls") or []
        if isinstance(row, dict) and row.get("id")
    }
    by_title: dict[str, dict[str, Any]] = {}
    collisions: set[str] = set()
    for row in [*p11_rows.values(), *mipe_rows.values()]:
        key = norm(row.get("title"))
        if not key:
            continue
        if key in by_title:
            collisions.add(key)
        else:
            by_title[key] = row
    for key in collisions:
        by_title.pop(key, None)
    return p11_rows, mipe_rows, by_title


def source_for_dossier(
    dossier: dict[str, Any],
    p11_rows: dict[str, dict[str, Any]],
    mipe_rows: dict[str, dict[str, Any]],
    by_title: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    dossier_id = dossier.get("id")
    if dossier_id in p11_rows:
        return p11_rows[dossier_id]
    if dossier_id in mipe_rows:
        return mipe_rows[dossier_id]
    return by_title.get(norm(dossier.get("title")))


def find_section(dossier: dict[str, Any], title: str) -> dict[str, Any] | None:
    wanted = norm(title)
    return next((row for row in dossier.get("sections") or [] if norm(row.get("title")) == wanted), None)


def safe_section_items(section: dict[str, Any] | None) -> list[str]:
    if not section:
        return []
    out: list[str] = []
    for row in section.get("items") or []:
        text = re.sub(r"\s+", " ", str(row or "")).strip()
        if not text:
            continue
        folded = norm(text)
        if any(norm(marker) in folded for marker in PLACEHOLDER_MARKERS):
            continue
        out.append(text)
    return out


def replace_section(dossier: dict[str, Any], title: str, replacement: dict[str, Any]) -> None:
    wanted = norm(title)
    sections = dossier.setdefault("sections", [])
    for index, row in enumerate(sections):
        if norm(row.get("title")) == wanted:
            sections[index] = replacement
            return
    sections.append(replacement)


def remove_section(dossier: dict[str, Any], title: str) -> None:
    wanted = norm(title)
    dossier["sections"] = [row for row in dossier.get("sections") or [] if norm(row.get("title")) != wanted]


def format_number(value: Any) -> str:
    if isinstance(value, bool):
        return "Da" if value else "Nu"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")
    return str(value)


def money(value: Any, currency: str = "EUR") -> str:
    return f"{format_number(value)} {currency}"


def deadline_parts(source: dict[str, Any] | None) -> tuple[str, str, str | None]:
    if not source or not fact_authorized(source, "deadline"):
        return UNKNOWN, UNKNOWN, None
    value = (source.get("materialFacts") or {}).get("deadline")
    if isinstance(value, str):
        return UNKNOWN, value, None
    if not isinstance(value, dict):
        return UNKNOWN, UNKNOWN, None
    opens = next((value.get(key) for key in ("opens_at", "opens", "open", "submission_start", "start") if value.get(key)), None)
    closes = next((value.get(key) for key in ("closes_at", "closes", "close", "deadline_at", "submission_end", "end") if value.get(key)), None)
    system = next((value.get(key) for key in ("submission_system", "system", "platform") if value.get(key)), None)
    return str(opens or UNKNOWN), str(closes or UNKNOWN), str(system) if system else None


def budget_summary(source: dict[str, Any] | None) -> str:
    if not source or not fact_authorized(source, "budget"):
        return UNKNOWN
    value = (source.get("materialFacts") or {}).get("budget")
    if isinstance(value, (str, int, float)):
        return str(value)
    if not isinstance(value, dict):
        return UNKNOWN
    preferred = (
        ("session_total_eur", "EUR"),
        ("total_eur", "EUR"),
        ("callBudgetRon", "RON"),
        ("total_ron", "RON"),
    )
    for key, currency in preferred:
        if value.get(key) is not None:
            return money(value[key], currency)
    rows = []
    for key, item in value.items():
        if isinstance(item, (int, float)):
            currency = "EUR" if "eur" in key.lower() else "RON" if "ron" in key.lower() else ""
            rows.append(f"{key.replace('_', ' ')}: {format_number(item)}{(' ' + currency) if currency else ''}")
        if len(rows) >= 3:
            break
    return " · ".join(rows) if rows else UNKNOWN


def project_value_summary(source: dict[str, Any] | None) -> str:
    if not source or not fact_authorized(source, "grant"):
        return UNKNOWN
    grant = (source.get("materialFacts") or {}).get("grant")
    if isinstance(grant, (str, int, float)):
        return str(grant)
    if not isinstance(grant, dict):
        return UNKNOWN
    if grant.get("minimum_eur") is not None or grant.get("maximum_eur") is not None:
        parts = []
        if grant.get("minimum_eur") is not None:
            parts.append(f"min. {money(grant['minimum_eur'])}")
        if grant.get("maximum_eur") is not None:
            parts.append(f"max. {money(grant['maximum_eur'])}")
        return " · ".join(parts)
    for key, label in (
        ("maximum_total_project_value_eur", "max."),
        ("cap_eur_per_beneficiary", "max. per beneficiar"),
        ("cap_eur_per_project", "max. per proiect"),
    ):
        if grant.get(key) is not None:
            return f"{label} {money(grant[key])}"
    evidence = collect_strings(grant.get("evidence"), limit=3)
    if evidence:
        return " · ".join(evidence)
    return UNKNOWN


def cofinancing_summary(source: dict[str, Any] | None) -> str:
    if not source or not fact_authorized(source, "grant"):
        return UNKNOWN
    facts = source.get("materialFacts") or {}
    grant = facts.get("grant")
    if isinstance(grant, dict):
        if grant.get("applicant_minimum_contribution_percent") is not None:
            return f"minimum {format_number(grant['applicant_minimum_contribution_percent'])}% contribuție proprie"
        if grant.get("cofinancing_rule"):
            values = collect_strings(grant.get("cofinancing_rule"), limit=4)
            if values:
                return " · ".join(values)
        if grant.get("p7_fse_plus_minimum_own_contribution_percent") is not None:
            values = collect_strings(grant.get("p7_fse_plus_minimum_own_contribution_percent"), limit=6)
            if values:
                return " · ".join(values)
        if grant.get("eligible_cost_intensity_percent") is not None:
            return f"intensitate nerambursabilă {format_number(grant['eligible_cost_intensity_percent'])}%"
        if grant.get("programme_contribution_percent") is not None:
            return f"contribuție program {format_number(grant['programme_contribution_percent'])}%"
    values = collect_strings(facts.get("cofinancing"), limit=4)
    return " · ".join(values) if values else UNKNOWN


def activity_summary(source: dict[str, Any] | None, dossier: dict[str, Any]) -> list[str]:
    if not source:
        return []
    verified = set(source.get("verifiedFactClasses") or [])
    facts = source.get("materialFacts") or {}
    direct = []
    for key in ("activities", "eligible_activities"):
        direct.extend(collect_strings(facts.get(key), limit=8))
    if direct and ("eligibility" in verified or "activities" in verified):
        return direct[:5]
    if "eligibility" not in verified:
        return []
    section = find_section(dossier, "Ce finanțează și în ce condiții")
    candidates = []
    for row in safe_section_items(section):
        folded = norm(row)
        if any(token in folded for token in ("activit", "investit", "finant", "servici", "achiz", "sprijin")):
            candidates.append(row)
    return candidates[:5]


def scoring_summary(source: dict[str, Any] | None) -> str | None:
    if not source or not fact_authorized(source, "scoring"):
        return None
    scoring = (source.get("materialFacts") or {}).get("scoring")
    if not isinstance(scoring, dict):
        return None
    parts = []
    if scoring.get("competitive") is not None:
        parts.append(f"competitiv: {'da' if scoring.get('competitive') else 'nu'}")
    for key in ("minimum_project_points", "minimum_total_points", "minimum_points"):
        if scoring.get(key) is not None:
            parts.append(f"prag minim: {format_number(scoring[key])} puncte")
            break
    return " · ".join(parts) if parts else None


def eligibility_conditions_from_old_section(old_items: list[str], applicants: list[str], target_groups: list[str]) -> list[str]:
    applicant_norm = {norm(row) for row in applicants}
    target_norm = {norm(row) for row in target_groups}
    out: list[str] = []
    seen: set[str] = set()
    for row in old_items:
        folded = norm(row)
        if not folded or folded in applicant_norm or folded in target_norm:
            continue
        if any(norm(marker) in folded for marker in PLACEHOLDER_MARKERS):
            continue
        if target_line(row):
            continue
        if folded in seen:
            continue
        seen.add(folded)
        out.append(row)
    return out[:24]


def executive_summary(
    dossier: dict[str, Any],
    source: dict[str, Any] | None,
    applicants: list[str],
    target_groups: list[str],
) -> dict[str, Any]:
    opens, closes, submission_system = deadline_parts(source)
    activities = activity_summary(source, dossier)
    call_budget = budget_summary(source)
    project_value = project_value_summary(source)
    cofinancing = cofinancing_summary(source)
    status = dossier.get("statusLabel") or dossier.get("status") or "ÎN VERIFICARE"

    summary = {
        "status": status,
        "opens": opens,
        "closes": closes,
        "applicants": applicants,
        "targetGroup": target_groups,
        "activities": activities,
        "callBudget": call_budget,
        "projectValue": project_value,
        "cofinancing": cofinancing,
        "region": dossier.get("region") or "România",
        "submissionSystem": submission_system,
        "scoring": scoring_summary(source),
        "sourcePolicy": "GUIDE_EXPLICIT_ONLY",
    }

    items = [
        f"Stare apel: {status}.",
        f"Deschidere: {opens}.",
        f"Închidere: {closes}.",
    ]
    if applicants:
        items.extend(f"Cine poate aplica: {row}" for row in applicants)
    else:
        items.append(f"Cine poate aplica: {WHO_UNKNOWN}")
    if target_groups:
        items.extend(f"Grup țintă: {row}" for row in target_groups)
    if activities:
        items.extend(f"Activități finanțate: {row}" for row in activities)
    else:
        items.append(f"Activități finanțate: {UNKNOWN}")
    items.extend([
        f"Valoarea apelului: {call_budget}.",
        f"Valoarea proiectului individual: {project_value}.",
        f"Cofinanțare / contribuție proprie: {cofinancing}.",
        f"Arie geografică: {summary['region']}.",
    ])
    if submission_system:
        items.append(f"Sistem de depunere: {submission_system}.")
    if summary["scoring"]:
        items.append(f"Evaluare: {summary['scoring']}.")

    summary["items"] = items
    return summary


def enforce_dossier_contract(
    dossier: dict[str, Any],
    source: dict[str, Any] | None,
) -> None:
    old_who = find_section(dossier, "Cine poate aplica")
    old_who_items = [str(row) for row in (old_who or {}).get("items") or []]
    old_audience = [str(row) for row in dossier.get("audience") or []]

    applicants = explicit_applicants(source)
    targets = extract_target_groups(source, [*old_audience, *old_who_items])
    conditions = eligibility_conditions_from_old_section(old_who_items, applicants, targets)

    dossier["audience"] = applicants
    dossier.setdefault("quality", {})["applicantListPolicy"] = "GUIDE_EXPLICIT_ONLY"
    dossier["quality"]["applicantEvidenceAuthorized"] = bool(applicants)
    dossier["quality"]["executiveSummaryPresent"] = True

    replace_section(
        dossier,
        "Cine poate aplica",
        {
            "title": "Cine poate aplica",
            "items": applicants or [WHO_UNKNOWN],
            "empty": not bool(applicants),
            "policy": "GUIDE_EXPLICIT_ONLY",
        },
    )

    remove_section(dossier, "Condiții esențiale de eligibilitate")
    if conditions:
        sections = dossier.setdefault("sections", [])
        who_index = next((i for i, row in enumerate(sections) if norm(row.get("title")) == norm("Cine poate aplica")), 0)
        sections.insert(
            who_index + 1,
            {
                "title": "Condiții esențiale de eligibilitate",
                "items": conditions,
                "empty": False,
            },
        )

    summary = executive_summary(dossier, source, applicants, targets)
    dossier["executiveSummary"] = {key: value for key, value in summary.items() if key != "items"}
    remove_section(dossier, "Rezumat executiv")
    dossier.setdefault("sections", []).insert(
        0,
        {
            "title": "Rezumat executiv",
            "items": summary["items"],
            "empty": False,
            "schemaVersion": 1,
        },
    )


def write(payload: dict[str, Any]) -> None:
    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    dossiers = payload.get("dossiers") or []
    canonical = [row for row in dossiers if not row.get("sourceType", "").endswith("PROVISIONAL")]
    provisional = [row for row in dossiers if row.get("sourceType", "").endswith("PROVISIONAL")]
    kept = list(canonical)
    merged_ids: list[str] = []

    for candidate in provisional:
        target = next((row for row in canonical if same_opportunity(candidate, row)), None)
        if target:
            merge(target, candidate)
            merged_ids.append(candidate.get("id"))
        else:
            kept.append(candidate)

    p11_rows, mipe_rows, by_title = source_maps()
    for dossier in kept:
        enforce_dossier_contract(
            dossier,
            source_for_dossier(dossier, p11_rows, mipe_rows, by_title),
        )

    rank = {"OPEN": 0, "EXPECTED": 1, "PUBLIC_CONSULTATION": 2, "REVIEW": 3, "CLOSED": 6}
    kept.sort(key=lambda row: (rank.get(row.get("status"), 4), -(row.get("quality", {}).get("completeness") or 0), row.get("title") or ""))
    valid = {row.get("id") for row in kept}
    news = [row for row in payload.get("news") or [] if not row.get("dossierId") or row.get("dossierId") in valid]

    payload["dossiers"] = kept
    payload["news"] = news
    quality = payload.setdefault("qualityPass", {})
    previous = set(quality.get("mergedIds") or [])
    previous.update(merged_ids)
    quality["mergedIds"] = sorted(previous)
    quality["duplicateDossiersMerged"] = len(previous)
    quality["executiveSummaryCoverage"] = sum(1 for row in kept if row.get("executiveSummary"))
    quality["strictApplicantListCoverage"] = sum(
        1 for row in kept if row.get("quality", {}).get("applicantListPolicy") == "GUIDE_EXPLICIT_ONLY"
    )
    payload.setdefault("coverage", {}).setdefault("afir", {})["mergedDuplicates"] = len(previous)
    payload["coverage"]["afir"]["publishedDossiers"] = sum(
        1
        for row in kept
        if row.get("sourceType", "").startswith("AFIR_")
        or any("afir.ro" in str(source.get("url")) for source in row.get("sources") or [])
    )
    payload.setdefault("summary", {}).update({
        "dossierCount": len(kept),
        "openCount": sum(1 for row in kept if row.get("status") == "OPEN"),
        "prepareCount": sum(1 for row in kept if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}),
        "newsCount": len(news),
        "highCompletenessCount": sum(1 for row in kept if row.get("quality", {}).get("completeness", 0) >= 70),
    })
    payload["home"] = {
        "openDossierIds": [row["id"] for row in kept if row.get("status") == "OPEN" and row.get("quality", {}).get("completeness", 0) >= 40][:8],
        "prepareDossierIds": [row["id"] for row in kept if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}][:8],
        "changeNewsIds": [row["id"] for row in news[:8]],
    }
    policy = payload.setdefault("policy", {})
    policy["whoCanApplyOfficialGuideOnly"] = True
    policy["executiveSummaryRequiredForEveryDossier"] = True
    policy["executiveSummarySchemaVersion"] = 1
    policy["unknownExecutiveFactsRemainVisible"] = True

    write(payload)
    print(json.dumps({
        "dossiers": len(kept),
        "merged": merged_ids,
        "executiveSummaries": quality["executiveSummaryCoverage"],
        "strictApplicantLists": quality["strictApplicantListCoverage"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
