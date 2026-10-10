#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
PRIMARY = {
    "AI4WORK_ADULTS_V1": "Q10",
    "AI4WORK_EMPLOYERS_V1": "E03",
}
FORBIDDEN_ID_TOKENS = {
    "name", "email", "phone", "telephone", "address", "cnp", "national_id", "cui",
    "employer_name", "exact_employer", "locality", "exact_locality", "ip", "user_agent",
}


def load_json(name: str) -> dict:
    data = json.loads((ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{name} must contain a JSON object")
    return data


def form_fields(forms: dict) -> tuple[dict[str, set[str]], dict[str, dict[str, dict]]]:
    field_ids: dict[str, set[str]] = {}
    field_defs: dict[str, dict[str, dict]] = {}
    for form in forms.get("forms", []):
        form_id = form.get("id")
        if not isinstance(form_id, str):
            raise RuntimeError("form id missing")
        ids: set[str] = set()
        defs: dict[str, dict] = {}
        for section in ("profile", "questions"):
            for field in form.get(section, []):
                field_id = field.get("id")
                if not isinstance(field_id, str) or not field_id:
                    raise RuntimeError(f"invalid field id in {form_id}")
                if field_id in ids:
                    raise RuntimeError(f"duplicate field id {form_id}:{field_id}")
                ids.add(field_id)
                defs[field_id] = field
        field_ids[form_id] = ids
        field_defs[form_id] = defs
    return field_ids, field_defs


def mapped_fields(control: dict) -> tuple[dict[str, set[str]], dict[str, int], dict[str, bool]]:
    mapped: dict[str, set[str]] = {}
    seen_counts: dict[str, int] = {}
    primary_flags: dict[str, bool] = {}
    for group in control.get("purpose_groups", []):
        purpose = group.get("purpose_id")
        if not isinstance(purpose, str) or not purpose:
            raise RuntimeError("purpose group id missing")
        numeric = group.get("numeric_h1_h5_rank") is True
        for form_id, ids in (group.get("fields") or {}).items():
            if not isinstance(ids, list):
                raise RuntimeError(f"purpose fields must be list: {purpose}:{form_id}")
            mapped.setdefault(form_id, set())
            for field_id in ids:
                if not isinstance(field_id, str):
                    raise RuntimeError(f"non-string field id in {purpose}:{form_id}")
                key = f"{form_id}:{field_id}"
                seen_counts[key] = seen_counts.get(key, 0) + 1
                mapped[form_id].add(field_id)
                primary_flags[key] = numeric
    return mapped, seen_counts, primary_flags


def validate() -> dict[str, object]:
    forms = load_json("forms_definition.json")
    control = load_json("GDPR_DATA_MINIMISATION_CONTROL.json")
    plan = load_json("NEED_ANALYSIS_PLAN_DRAFT.json")
    retention = load_json("GDPR_RETENTION_SCHEDULE_DRAFT.json")

    for doc_name, doc in (("forms", forms), ("control", control), ("plan", plan), ("retention", retention)):
        if doc.get("research_id") != RESEARCH_ID:
            raise RuntimeError(f"research id mismatch in {doc_name}")

    prohibitions = control.get("global_prohibitions", {})
    required_false = (
        "commercial_use_allowed", "crm_linkage_allowed", "marketing_tracking_allowed",
        "individual_decision_use_allowed", "direct_identifiers_allowed", "exact_employer_allowed",
        "exact_locality_allowed", "free_text_allowed", "transport_metadata_for_analysis_allowed",
        "raw_ip_or_user_agent_in_nf06_allowed",
    )
    for key in required_false:
        if prohibitions.get(key) is not False:
            raise RuntimeError(f"minimisation prohibition not fail-closed: {key}")

    forbidden_types = set(control.get("field_type_policy", {}).get("forbidden_types", []))
    if not {"text", "textarea"}.issubset(forbidden_types):
        raise RuntimeError("free-text types must remain forbidden")

    actual, defs = form_fields(forms)
    mapped, counts, numeric_flags = mapped_fields(control)
    if set(actual) != set(mapped):
        raise RuntimeError(f"form coverage mismatch: actual={sorted(actual)} mapped={sorted(mapped)}")
    for form_id, ids in actual.items():
        if ids != mapped.get(form_id, set()):
            missing = sorted(ids - mapped.get(form_id, set()))
            extra = sorted(mapped.get(form_id, set()) - ids)
            raise RuntimeError(f"purpose map mismatch {form_id}: missing={missing} extra={extra}")
        for field_id in sorted(ids):
            key = f"{form_id}:{field_id}"
            if counts.get(key) != 1:
                raise RuntimeError(f"field must map to exactly one purpose: {key}")
            field = defs[form_id][field_id]
            field_type = str(field.get("type", ""))
            if field_type in forbidden_types:
                raise RuntimeError(f"free text is forbidden: {key}")
            lowered = field_id.lower()
            if lowered in FORBIDDEN_ID_TOKENS or any(token == lowered for token in FORBIDDEN_ID_TOKENS):
                raise RuntimeError(f"identifier-like field id forbidden: {key}")

    primary_from_matrix = {
        form_id: next(
            field_id for field_id in ids
            if numeric_flags.get(f"{form_id}:{field_id}") is True
        )
        for form_id, ids in actual.items()
    }
    if primary_from_matrix != PRIMARY:
        raise RuntimeError(f"primary minimisation mapping drift: {primary_from_matrix}")

    core = plan.get("core_skill_ranking", {})
    if core.get("adult_direct_source") != "Q10 perceived-need rating matrix":
        raise RuntimeError("analysis plan adult primary source drift")
    if core.get("employer_direct_source") != "E03 competence-impact rating matrix":
        raise RuntimeError("analysis plan employer primary source drift")
    if core.get("secondary_evidence_can_change_numeric_order") is not False:
        raise RuntimeError("secondary evidence must not alter primary numeric rank")
    if plan.get("project_activity_as_need_evidence") is not False:
        raise RuntimeError("project activity must remain excluded as need evidence")

    employer_e10 = defs["AI4WORK_EMPLOYERS_V1"].get("E10", {})
    note = str(employer_e10.get("note", "")).lower()
    if "nu se colectează date de contact" not in note:
        raise RuntimeError("E10 must retain explicit no-contact constraint")

    schedule_classes = {str(item.get("data_class")) for item in retention.get("schedules", [])}
    expected_class = control.get("retention_binding", {}).get("respondent_level_class")
    if expected_class not in schedule_classes:
        raise RuntimeError("minimisation control is not bound to respondent-level retention class")
    if retention.get("collection_enabled") is not False:
        raise RuntimeError("draft retention schedule must remain collection-disabled before approval")

    return {
        "status": "PASS",
        "classification": "CONTROL_ONLY_NOT_EVIDENCE",
        "research_id": RESEARCH_ID,
        "forms": {form_id: len(ids) for form_id, ids in actual.items()},
        "total_fields": sum(len(ids) for ids in actual.values()),
        "all_fields_single_purpose_mapped": True,
        "free_text_present": False,
        "primary_rank_fields": PRIMARY,
        "crm_linkage_allowed": False,
        "marketing_use_allowed": False,
        "test_twin_evidence_eligible": False,
        "collection_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
