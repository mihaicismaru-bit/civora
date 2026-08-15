#!/usr/bin/env python3
"""Romanian editorial normalization for PARTENER.EU decision products.

This runs after dossier generation and before publication. It prevents internal
schema objects / English field names from leaking into the public interface,
normalizes decision labels, fixes regional display geography, and keeps useful
financial facts concise on mobile.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"

DECISIONS = {
    "ACT NOW": "ACȚIONEAZĂ",
    "PREPARE": "PREGĂTEȘTE",
    "CONTRIBUTE / PREPARE": "ANALIZEAZĂ / PREGĂTEȘTE",
    "REFERENCE": "REFERINȚĂ",
    "WAIT": "AȘTEAPTĂ",
    "VERIFY": "VERIFICĂ",
    "MONITOR": "MONITORIZEAZĂ",
}
STATUS_LABELS = {
    "OPEN": "DESCHIS",
    "EXPECTED": "ÎN PREGĂTIRE",
    "ANNOUNCED": "ANUNȚAT",
    "PUBLIC_CONSULTATION": "ÎN CONSULTARE",
    "REVIEW": "ÎN VERIFICARE",
    "CLOSED": "ÎNCHIS",
    "CANCELLED": "ANULAT",
    "SUSPENDED": "SUSPENDAT",
    "FINALIZAT": "ÎNCHIS",
}
PREFIXES = {
    "Eligible applicant:": "Solicitant eligibil:",
    "Eligible applicants:": "Solicitanți eligibili:",
    "Mandatory institutional partner:": "Partener instituțional obligatoriu:",
    "Institutional partner:": "Partener instituțional:",
    "Applicant:": "Solicitant:",
    "Applicants:": "Solicitanți:",
    "Partnership:": "Parteneriat:",
    "Excluded:": "Excluderi:",
    "Competitive:": "Competitiv:",
    "Maximum points:": "Punctaj maxim:",
    "Minimum quality points:": "Prag minim de calitate:",
    "Minimum project points:": "Prag minim al proiectului:",
    "Number of criteria:": "Număr de criterii:",
    "Ranking:": "Clasament:",
    "Tie breaker:": "Criteriu de departajare:",
    "Individual applicant:": "Solicitant individual:",
}
KEY_LABELS = {
    "form": "Formă finanțare",
    "maximum_total_project_value_eur": "Valoare maximă proiect",
    "minimum_total_project_value_eur": "Valoare minimă proiect",
    "project_budget_currency": "Monedă buget proiect",
    "cofinancing_rule": "Regula cofinanțării",
    "p7_fse_plus_minimum_own_contribution_percent": "Contribuție proprie minimă FSE+",
    "public_own_revenue_or_local_budget_entity": "Entitate publică finanțată din venituri proprii / buget local",
    "state_budget_credit_authorizer_or_fully_budgeted_subordinate_entity": "Ordonator de credite / entitate finanțată integral de la bugetul de stat",
    "private_nonprofit_legal_entity": "Persoană juridică privată fără scop patrimonial",
    "less_developed_regions": "Regiuni mai puțin dezvoltate",
    "developed_region": "Regiune dezvoltată",
    "eligible_applicant": "Solicitant eligibil",
    "mandatory_institutional_partner": "Partener instituțional obligatoriu",
    "minimum_eur": "Grant minim",
    "maximum_eur": "Grant maxim",
    "total_eur": "Buget total",
    "session_total_eur": "Buget sesiune",
    "eligible_cost_intensity_percent": "Intensitate nerambursabilă",
    "applicant_minimum_contribution_percent": "Contribuție proprie minimă",
    "callBudgetRon": "Buget apel",
}
REGION_RULES = [
    (r"regiunea\s+centru|regional\s+centru", "Regiunea Centru"),
    (r"nord[- ]est", "Regiunea Nord-Est"),
    (r"sud[- ]est", "Regiunea Sud-Est"),
    (r"sud[- ]muntenia", "Regiunea Sud-Muntenia"),
    (r"sud[- ]vest\s+oltenia", "Regiunea Sud-Vest Oltenia"),
    (r"nord[- ]vest", "Regiunea Nord-Vest"),
    (r"bucure[șs]ti[- ]ilfov", "Regiunea București-Ilfov"),
    (r"programul\s+regional\s+vest|regiunea\s+vest", "Regiunea Vest"),
]


def fmt_number(value: Any) -> str:
    if isinstance(value, bool):
        return "Da" if value else "Nu"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")
    return str(value)


def maybe_object(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return value
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, (dict, list, tuple)) else value
    except Exception:
        return value


def money(value: Any, currency: str = "EUR") -> str:
    return f"{fmt_number(value)} {currency}" if value not in (None, "") else ""


def contribution_summary(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts: list[str] = []
    for entity_key, entity_value in value.items():
        if not isinstance(entity_value, dict):
            continue
        label = KEY_LABELS.get(entity_key, entity_key.replace("_", " "))
        region_bits = []
        for region_key, percent in entity_value.items():
            region_label = KEY_LABELS.get(region_key, region_key.replace("_", " "))
            region_bits.append(f"{region_label}: {fmt_number(percent)}%")
        if region_bits:
            parts.append(f"{label} — {', '.join(region_bits)}")
    return "; ".join(parts[:3])


def compact_financial(label: str, raw: Any) -> tuple[str, str]:
    value = maybe_object(raw)
    if not isinstance(value, dict):
        return label, str(raw) if raw not in (None, "") else "Neconfirmat"

    currency = str(value.get("project_budget_currency") or value.get("currency") or "EUR")
    if label == "Grant":
        if value.get("maximum_eur") is not None or value.get("minimum_eur") is not None:
            bits = []
            if value.get("minimum_eur") is not None:
                bits.append(f"min. {money(value['minimum_eur'], 'EUR')}")
            if value.get("maximum_eur") is not None:
                bits.append(f"max. {money(value['maximum_eur'], 'EUR')}")
            if value.get("eligible_cost_intensity_percent") is not None:
                bits.append(f"până la {fmt_number(value['eligible_cost_intensity_percent'])}%")
            return "Grant", " · ".join(bits)
        if value.get("maximum_total_project_value_eur") is not None:
            return "Valoare proiect", f"max. {money(value['maximum_total_project_value_eur'], currency)}"
        if value.get("form"):
            return "Finanțare", localize_text(str(value.get("form")))
    if label == "Buget":
        for key in ("session_total_eur", "total_eur", "callBudgetRon"):
            if value.get(key) is not None:
                return "Buget", money(value[key], "RON" if key == "callBudgetRon" else "EUR")
    if label == "Contribuție proprie":
        rule = value.get("cofinancing_rule")
        own = value.get("p7_fse_plus_minimum_own_contribution_percent")
        bits = []
        if isinstance(rule, str) and rule.strip():
            bits.append(localize_text(rule.strip()))
        detail = contribution_summary(own)
        if detail:
            bits.append(detail)
        if bits:
            return label, " ".join(bits)[:420]

    # Generic compact fallback: never expose Python/JSON object syntax.
    bits = []
    for key, item in value.items():
        if isinstance(item, (str, int, float, bool)):
            bits.append(f"{KEY_LABELS.get(key, key.replace('_', ' ').capitalize())}: {fmt_number(item)}")
        if len(bits) >= 3:
            break
    return label, " · ".join(bits) if bits else "Detalii în dosarul complet"


def localize_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for old, new in PREFIXES.items():
        if text.lower().startswith(old.lower()):
            text = new + text[len(old):]
            break
    replacements = {
        "less developed regions": "regiuni mai puțin dezvoltate",
        "developed region": "regiune dezvoltată",
        "public own revenue or local budget entity": "entitate publică finanțată din venituri proprii / buget local",
        "private nonprofit legal entity": "persoană juridică privată fără scop patrimonial",
        "state budget credit authorizer or fully budgeted subordinate entity": "ordonator de credite / entitate finanțată integral de la bugetul de stat",
        "grant nerambursabil": "grant nerambursabil",
        "true": "Da",
        "false": "Nu",
    }
    for old, new in replacements.items():
        text = re.sub(re.escape(old), new, text, flags=re.I)
    return text


def infer_region(programme: str, current: str) -> str:
    if current and current not in {"România", "Romania", "Național", "National"}:
        return current
    hay = programme or ""
    for pattern, label in REGION_RULES:
        if re.search(pattern, hay, re.I):
            return label
    return "România" if current in {None, "", "Romania"} else current


def clean_dossier(dossier: dict[str, Any]) -> None:
    dossier["statusLabel"] = STATUS_LABELS.get(str(dossier.get("status") or "").upper(), localize_text(dossier.get("statusLabel") or "ÎN VERIFICARE"))
    dossier["decision"] = DECISIONS.get(str(dossier.get("decision") or "").upper(), localize_text(dossier.get("decision") or "VERIFICĂ"))
    dossier["region"] = infer_region(str(dossier.get("programme") or ""), str(dossier.get("region") or ""))
    dossier["audience"] = [localize_text(row) for row in dossier.get("audience") or []]
    dossier["standfirst"] = localize_text(dossier.get("standfirst"))
    dossier["decisionAction"] = localize_text(dossier.get("decisionAction"))

    quick = []
    for fact in dossier.get("quickFacts") or []:
        row = dict(fact)
        label, value = compact_financial(str(row.get("label") or ""), row.get("value"))
        row["label"] = label
        row["value"] = localize_text(value)
        quick.append(row)
    dossier["quickFacts"] = quick

    for section in dossier.get("sections") or []:
        section["items"] = [localize_text(row) for row in section.get("items") or []]
    for row in dossier.get("timeline") or []:
        row["text"] = localize_text(row.get("text"))


def clean_news(story: dict[str, Any]) -> None:
    for key in ("headline", "standfirst", "meaning"):
        story[key] = localize_text(story.get(key))
    for key in ("confirmed", "notConfirmed", "actions", "audience"):
        story[key] = [localize_text(row) for row in story.get(key) or []]


def write(payload: dict[str, Any]) -> None:
    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    for dossier in payload.get("dossiers") or []:
        clean_dossier(dossier)
    for story in payload.get("news") or []:
        clean_news(story)
    payload.setdefault("policy", {})["romanianPublicLanguage"] = True
    payload["policy"]["rawStructuredObjectsVisible"] = False
    write(payload)
    print(json.dumps({
        "dossiers": len(payload.get("dossiers") or []),
        "news": len(payload.get("news") or []),
        "romanianPublicLanguage": True,
        "rawStructuredObjectsVisible": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
