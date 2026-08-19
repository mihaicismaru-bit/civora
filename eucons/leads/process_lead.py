#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "lead_contract.json"
DEFAULT_FORMS = EUCONS / "leads" / "forms.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        raise ValueError(f"text exceeds {limit} characters")
    return text


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", clean_text(value, 4000).lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def normalize_list(value: Any, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected list")
    normalized = []
    for item in value:
        text = clean_text(item, limit)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def forms_by_id(forms_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {form["id"]: form for form in forms_doc.get("forms") or []}


def validate_and_normalize(payload: dict[str, Any], contract: dict[str, Any], forms_doc: dict[str, Any]) -> dict[str, Any]:
    allowed = set(contract["allowed_fields"])
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported lead fields: {sorted(unknown)}")
    for field in contract["required_global_fields"]:
        if field not in payload or payload[field] in (None, ""):
            raise ValueError(f"required field missing: {field}")

    anti = contract["anti_spam"]
    if anti["honeypot_must_be_blank"] and clean_text(payload.get(anti["honeypot_field"], ""), 300):
        raise ValueError("spam honeypot triggered")
    age = payload.get("submission_age_ms")
    if not isinstance(age, (int, float)) or not (anti["minimum_submission_age_ms"] <= age <= anti["maximum_submission_age_ms"]):
        raise ValueError("invalid submission_age_ms")
    if payload.get("privacy_ack") is not True:
        raise ValueError("privacy acknowledgement required")

    forms = forms_by_id(forms_doc)
    form_id = clean_text(payload["form_id"], 100)
    if form_id not in forms:
        raise ValueError(f"unknown form_id: {form_id}")
    form = forms[form_id]
    for field in form.get("required") or []:
        value = payload.get(field)
        if value in (None, "", []):
            raise ValueError(f"form field required: {field}")

    limits = contract["validation"]
    email = clean_text(payload["email"], limits["max_short_text_length"]).lower()
    if not re.match(limits["email_pattern"], email):
        raise ValueError("invalid email")
    audience = clean_text(payload.get("audience_id"), 100)
    if audience and audience not in limits["allowed_audiences"]:
        raise ValueError("invalid audience_id")
    timeline = clean_text(payload.get("timeline", "unknown"), 100) or "unknown"
    if timeline not in limits["allowed_timelines"]:
        raise ValueError("invalid timeline")
    project_stage = clean_text(payload.get("project_stage", "unknown"), 100) or "unknown"
    if project_stage not in limits["allowed_project_stages"]:
        raise ValueError("invalid project_stage")
    requested = payload.get("requested_grant_eur")
    if requested is not None and (not isinstance(requested, (int, float)) or requested <= 0):
        raise ValueError("requested_grant_eur must be positive")

    short = limits["max_short_text_length"]
    long = limits["max_text_length"]
    normalized = {
        "form_id": form_id,
        "submission_id": clean_text(payload["submission_id"], short),
        "submitted_at": clean_text(payload.get("submitted_at", ""), short),
        "privacy_ack": True,
        "marketing_consent": payload.get("marketing_consent") is True,
        "contact_name": clean_text(payload["contact_name"], short),
        "email": email,
        "phone": clean_text(payload.get("phone", ""), short),
        "organization_name": clean_text(payload.get("organization_name", ""), short),
        "audience_id": audience,
        "organization_labels": normalize_list(payload.get("organization_labels"), short),
        "activity_codes": normalize_list(payload.get("activity_codes"), short),
        "county": clean_text(payload.get("county", ""), short),
        "region_terms": normalize_list(payload.get("region_terms"), short),
        "investment_terms": normalize_list(payload.get("investment_terms"), short),
        "requested_grant_eur": float(requested) if requested is not None else None,
        "project_stage": project_stage,
        "timeline": timeline,
        "message": clean_text(payload.get("message", ""), long),
    }
    return normalized


def matching_profile(lead: dict[str, Any]) -> dict[str, Any]:
    region_terms = list(lead["region_terms"])
    if lead.get("county") and lead["county"] not in region_terms:
        region_terms.append(lead["county"])
    labels = list(lead["organization_labels"])
    if lead.get("organization_name"):
        labels.append(lead["organization_name"])
    profile = {
        "profile_id": "lead:" + lead["submission_id"],
        "audience_id": lead.get("audience_id", ""),
        "organization_labels": labels,
        "activity_codes": lead["activity_codes"],
        "region_terms": region_terms,
        "investment_terms": lead["investment_terms"],
    }
    if lead.get("requested_grant_eur") is not None:
        profile["requested_grant_eur"] = lead["requested_grant_eur"]
    return profile


def dedupe_key(lead: dict[str, Any]) -> str:
    basis = "|".join([lead["email"].lower(), fold(lead.get("organization_name", ""))])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def matching_counts(matching_result: dict[str, Any] | None) -> tuple[int, int]:
    if not matching_result:
        return 0, 0
    summary = matching_result.get("summary") or {}
    return int(summary.get("candidates") or 0), int(summary.get("requires_data") or 0)


def score_lead(lead: dict[str, Any], matching_result: dict[str, Any] | None, contract: dict[str, Any]) -> dict[str, Any]:
    scoring = contract["scoring"]
    completeness_fields = ["organization_name", "audience_id", "investment_terms", "activity_codes", "county", "message"]
    populated = sum(bool(lead.get(field)) for field in completeness_fields)
    completeness = round(scoring["completeness_max"] * populated / len(completeness_fields))
    intent = int(scoring["form_intent"].get(lead["form_id"], 0))
    urgency = int(scoring["timeline_urgency"].get(lead["timeline"], 0))
    candidates, requires_data = matching_counts(matching_result)
    match_bonus = scoring["matching_candidate_bonus"] if candidates else (scoring["matching_requires_data_bonus"] if requires_data else 0)
    total = min(int(scoring["lead_score_max"]), completeness + intent + urgency + int(match_bonus))
    intent_score = round(100 * intent / max(scoring["form_intent"].values())) if intent else 0
    urgency_score = round(100 * urgency / max(scoring["timeline_urgency"].values())) if urgency else 0
    return {
        "lead_score": total,
        "intent_score": intent_score,
        "urgency_score": urgency_score,
        "completeness_score": completeness,
        "matching_candidate_count": candidates,
        "matching_requires_data_count": requires_data,
    }


def next_action(lead: dict[str, Any], scores: dict[str, Any], contract: dict[str, Any]) -> str:
    actions = contract["next_actions"]
    if lead["form_id"] == "project_recovery":
        return actions["project_recovery"]
    if scores["lead_score"] >= 70:
        return actions["high_score"]
    if scores["matching_candidate_count"]:
        return actions["matching_candidate"]
    return actions["default"]


def process(payload: dict[str, Any], contract: dict[str, Any], forms_doc: dict[str, Any], matching_result: dict[str, Any] | None = None) -> dict[str, Any]:
    lead = validate_and_normalize(payload, contract, forms_doc)
    scores = score_lead(lead, matching_result, contract)
    return {
        "schema_version": 1,
        "engine_id": contract["engine_id"],
        "record_state": "QUALIFIED_INTAKE",
        "dedupe_key": dedupe_key(lead),
        "lead": lead,
        "matching_profile": matching_profile(lead),
        "scores": scores,
        "next_action": next_action(lead, scores, contract),
        "consent": {
            "privacy_ack": True,
            "marketing_consent": lead["marketing_consent"],
            "marketing_allowed": lead["marketing_consent"] is True,
        },
        "storage_state": "PROVIDER_ADAPTER_REQUIRED",
    }


def assert_output_path_safe(path: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("PII-bearing lead output cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--matching", default=None)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--forms", default=str(DEFAULT_FORMS))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    matching = load_json(Path(args.matching)) if args.matching else None
    result = process(load_json(Path(args.input)), load_json(Path(args.contract)), load_json(Path(args.forms)), matching)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
