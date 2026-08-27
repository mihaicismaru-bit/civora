#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "prospects" / "client_finder_match_explainability_contract.json"

STATE_PRIORITY = {
    "MATCHED_RESEARCH_CANDIDATE": 0,
    "REQUIRES_VERIFICATION": 1,
    "NO_CURRENT_OPPORTUNITY": 2,
    "HOLD_SOURCE_STATE": 3,
    "HOLD_CONFLICT": 4,
    "SUPPRESSED": 5,
}

UNSAFE_TRUE_KEYS = {
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _assert_no_unsafe_true(value: Any) -> None:
    for key, child in _walk_keys(value):
        if key in UNSAFE_TRUE_KEYS and child is not False:
            raise ValueError(f"unsafe action boundary failed open: {key}")


def _assert_no_forbidden_input_inference(value: Any, contract: dict[str, Any]) -> None:
    forbidden = set(contract["output_policy"]["inference_fields_forbidden"])
    person_fields = {
        key
        for key in contract["output_policy"]["raw_fields_forbidden"]
        if key.startswith("person") or key.startswith("personal") or key in {"home_address", "date_of_birth", "private_contact"}
    }
    for key, _ in _walk_keys(value):
        if key in forbidden:
            raise ValueError(f"forbidden inference field present: {key}")
        if key in person_fields:
            raise ValueError(f"person-level field present: {key}")


def _assert_output_minimized(value: Any, contract: dict[str, Any]) -> None:
    forbidden = set(contract["output_policy"]["raw_fields_forbidden"]) | set(contract["output_policy"]["inference_fields_forbidden"])
    for key, _ in _walk_keys(value):
        if key in forbidden:
            raise AssertionError(f"forbidden output field leaked: {key}")
    _assert_no_unsafe_true(value)


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("id") != "EUCONS-R07-CLIENT-FINDER-MATCH-EXPLAINABILITY-001":
        raise ValueError("match explainability contract id drift")
    if contract.get("status") != "CANONICAL":
        raise ValueError("match explainability contract must be canonical")
    source = contract.get("source_views") or {}
    if source.get("match_engine_id") != "EUCONS_R07_PROSPECT_OPPORTUNITY_SERVICE_MATCH":
        raise ValueError("match source engine drift")
    if source.get("match_semantics") != "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT":
        raise ValueError("match source semantics failed open")
    if source.get("score_engine_id") != "EUCONS_R06_PROSPECT_PRIORITY_SCORING":
        raise ValueError("score source engine drift")
    if source.get("score_semantics") != "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY":
        raise ValueError("score source semantics failed open")
    boundaries = contract.get("required_boundaries") or {}
    required = {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    if any(boundaries.get(key) != expected for key, expected in required.items()):
        raise ValueError("required boundary drift")
    matched = contract.get("matched_requirements") or {}
    if matched.get("match_state") != "MATCHED_RESEARCH_CANDIDATE":
        raise ValueError("matched state drift")
    if matched.get("opportunity_state") != "MATCH_CANDIDATE":
        raise ValueError("opportunity match state drift")
    if matched.get("opportunity_relevance_semantics") != "RELEVANCE_NOT_APPROVAL_PROBABILITY":
        raise ValueError("opportunity relevance semantics drift")
    if matched.get("selected_service_must_be_signal_supported") is not True or matched.get("selected_service_must_be_opportunity_aligned") is not True:
        raise ValueError("service alignment guard missing")
    if matched.get("official_source_reverification_required") is not True or matched.get("material_claims_verified") is not False:
        raise ValueError("material claim boundary failed open")
    reasons = contract.get("state_reason_codes") or {}
    if set(reasons) != set(STATE_PRIORITY):
        raise ValueError("state reason taxonomy incomplete")
    rules = contract.get("rules") or {}
    required_true = {
        "one_to_one_join_by_organization_key",
        "prospect_id_must_match",
        "priority_score_and_state_must_match",
        "recommended_service_must_match",
        "never_treat_score_as_probability",
        "never_infer_eligibility_award_conversion_or_buying_intent",
        "never_expose_raw_provenance_or_material_deadline",
        "never_generate_person_level_output",
        "never_enable_external_action_or_persistence",
    }
    if any(rules.get(key) is not True for key in required_true):
        raise ValueError("match explainability safety rule missing")


def _validate_top_level(match_view: dict[str, Any], score_view: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_views"]
    boundaries = contract["required_boundaries"]
    if match_view.get("engine_id") != source["match_engine_id"] or match_view.get("match_semantics") != source["match_semantics"]:
        raise ValueError("unexpected match view")
    if score_view.get("engine_id") != source["score_engine_id"] or score_view.get("score_semantics") != source["score_semantics"]:
        raise ValueError("unexpected score view")
    for view in (match_view, score_view):
        if view.get("eligibility_state") != boundaries["eligibility_state"]:
            raise ValueError("eligibility state drift")
        if view.get("maximum_next_state") != boundaries["maximum_next_state"]:
            raise ValueError("maximum next state drift")
    _assert_no_unsafe_true(match_view)
    _assert_no_unsafe_true(score_view)
    _assert_no_forbidden_input_inference(match_view, contract)
    _assert_no_forbidden_input_inference(score_view, contract)


def _index_unique(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("organization_key") or "")
        if not key:
            raise ValueError(f"{label} result missing organization_key")
        if key in index:
            raise ValueError(f"duplicate organization_key in {label}: {key}")
        index[key] = row
    return index


def _score_breakdown(score: dict[str, Any]) -> dict[str, Any] | None:
    if score.get("score") is None:
        return None
    components = deepcopy(score.get("components") or {})
    penalties = deepcopy(score.get("penalties") or {})
    if set(components) != {"source_quality", "freshness", "signal_strength", "service_coherence", "actionability"}:
        raise ValueError("score component breakdown incomplete")
    if set(penalties) != {"unknown_assertions", "low_confidence_inferences", "total"}:
        raise ValueError("score penalty breakdown incomplete")
    if sum(int(value) for value in components.values()) != int(score.get("gross_score")):
        raise ValueError("gross score does not equal component sum")
    if max(0, int(score["gross_score"]) - int(penalties["total"])) != int(score["score"]):
        raise ValueError("net score does not reconcile")
    return {
        "score": score["score"],
        "gross_score": score["gross_score"],
        "components": components,
        "penalties": penalties,
        "semantics": score["score_semantics"],
    }


def _service_support(score: dict[str, Any], service_id: str | None) -> dict[str, Any] | None:
    if not service_id:
        return None
    rows = [row for row in score.get("service_ranking") or [] if row.get("service_id") == service_id]
    if len(rows) != 1:
        raise ValueError("selected service support is missing or ambiguous")
    row = rows[0]
    return {
        "service_id": service_id,
        "supporting_signal_ids": sorted(set(row.get("supporting_signal_ids") or [])),
        "support_count": row.get("support_count"),
        "support_ratio": row.get("support_ratio"),
    }


def _selected_opportunity(match: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any] | None:
    matched = contract["matched_requirements"]
    selected_id = match.get("selected_opportunity_id")
    selected_service = match.get("selected_service_id")
    if match.get("state") != matched["match_state"]:
        if selected_id is not None or selected_service is not None:
            raise ValueError("non-matched row cannot expose selected opportunity/service")
        return None
    if not selected_id or not selected_service:
        raise ValueError("matched row missing selected opportunity/service")
    rows = [row for row in match.get("opportunity_matches") or [] if row.get("opportunity_id") == selected_id]
    if len(rows) != 1:
        raise ValueError("selected opportunity missing or ambiguous")
    row = rows[0]
    if row.get("state") != matched["opportunity_state"]:
        raise ValueError("selected opportunity is not a match candidate")
    if row.get("relevance_semantics") != matched["opportunity_relevance_semantics"]:
        raise ValueError("selected opportunity relevance semantics failed open")
    if selected_service not in set(match.get("signal_supported_service_ids") or []):
        raise ValueError("selected service is not prospect signal-supported")
    if selected_service not in set(row.get("aligned_service_ids") or []):
        raise ValueError("selected service is not opportunity-aligned")
    if row.get("selected_service_id") != selected_service:
        raise ValueError("selected service identity drift")
    return {
        "opportunity_id": selected_id,
        "title": row.get("title"),
        "programme": row.get("programme"),
        "relevance_score": row.get("relevance_score"),
        "relevance_semantics": row.get("relevance_semantics"),
        "confidence": row.get("confidence"),
        "verified_fact_classes": sorted(set(row.get("verified_fact_classes") or [])),
        "matching_explanations": list(row.get("explanations") or []),
    }


def _reason_codes(match: dict[str, Any], score: dict[str, Any], selected: dict[str, Any] | None, contract: dict[str, Any]) -> list[str]:
    codes = [contract["state_reason_codes"][match["state"]]]
    if score.get("score") is not None:
        codes.append("PROSPECT_RESEARCH_PRIORITY_SCORED")
    if selected is not None:
        codes.extend(["VERIFIED_OPPORTUNITY_RELEVANCE", "SIGNAL_SUPPORTED_SERVICE_OVERLAP", "OFFICIAL_SOURCE_REVERIFICATION_REQUIRED"])
    if int((score.get("penalties") or {}).get("total") or 0) > 0:
        codes.append("UNCERTAINTY_PENALTY_PRESENT")
    questions = set(match.get("verification_questions") or []) | set(score.get("verification_questions") or [])
    if questions:
        codes.append("HUMAN_VERIFICATION_QUESTIONS_PRESENT")
    return sorted(set(codes))


def _build_row(match: dict[str, Any], score: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    boundaries = contract["required_boundaries"]
    if match.get("prospect_id") != score.get("prospect_id"):
        raise ValueError("prospect_id mismatch between match and score views")
    if match.get("priority_state") != score.get("priority_state"):
        raise ValueError("priority state mismatch between match and score views")
    if match.get("priority_score") != score.get("score"):
        raise ValueError("priority score mismatch between match and score views")
    if match.get("recommended_service_id") != score.get("recommended_service_id"):
        raise ValueError("recommended service mismatch between match and score views")
    if match.get("eligibility_state") != boundaries["eligibility_state"] or match.get("maximum_next_state") != boundaries["maximum_next_state"]:
        raise ValueError("row qualification boundary drift")
    if match.get("state") not in STATE_PRIORITY:
        raise ValueError("unknown match state")

    selected = _selected_opportunity(match, contract)
    selected_service = match.get("selected_service_id")
    support = _service_support(score, selected_service) if selected is not None else None
    questions = sorted({str(q) for q in list(match.get("verification_questions") or []) + list(score.get("verification_questions") or []) if str(q).strip()})
    matched_requirements = contract["matched_requirements"]
    operator_next_step = match.get("next_best_action")
    reverify_required = False
    material_claims_verified = False
    if selected is not None:
        operator_next_step = matched_requirements["operator_next_step"]
        reverify_required = matched_requirements["official_source_reverification_required"]
        material_claims_verified = matched_requirements["material_claims_verified"]

    return {
        "organization_key": match["organization_key"],
        "prospect_id": match.get("prospect_id"),
        "state": match["state"],
        "priority_state": score.get("priority_state"),
        "priority_score": score.get("score"),
        "priority_score_semantics": score.get("score_semantics"),
        "score_breakdown": _score_breakdown(score),
        "recommended_service_id": score.get("recommended_service_id"),
        "selected_service_id": selected_service,
        "selected_service_support": support,
        "selected_opportunity": selected,
        "reason_codes": _reason_codes(match, score, selected, contract),
        "verification_questions": questions,
        "source_ref_count": len(set(match.get("source_refs") or []) | set(score.get("source_refs") or [])),
        "signal_ids": sorted(set(match.get("signal_ids") or []) | set(score.get("signal_ids") or [])),
        "operator_next_step": operator_next_step,
        "official_source_reverification_required": reverify_required,
        "material_claims_verified": material_claims_verified,
        "eligibility_state": boundaries["eligibility_state"],
        "maximum_next_state": boundaries["maximum_next_state"],
        "human_review_required": boundaries["human_review_required"],
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "evidence_label": match.get("evidence_label") or score.get("evidence_label"),
    }


def build_view(match_view: dict[str, Any], score_view: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_json(CONTRACT_PATH)
    validate_contract(contract)
    _validate_top_level(match_view, score_view, contract)
    match_index = _index_unique(list(match_view.get("results") or []), "match")
    score_index = _index_unique(list(score_view.get("results") or []), "score")
    if set(match_index) != set(score_index):
        raise ValueError("match/score organization sets differ")
    rows = [_build_row(match_index[key], score_index[key], contract) for key in sorted(match_index)]
    rows.sort(key=lambda row: (STATE_PRIORITY[row["state"]], row["priority_score"] is None, -(row["priority_score"] or 0), row["organization_key"]))
    boundaries = contract["required_boundaries"]
    result = {
        "schema_version": 1,
        "view_id": contract["id"],
        "view_state": contract["output_policy"]["view_state"],
        "match_semantics": contract["source_views"]["match_semantics"],
        "priority_score_semantics": contract["source_views"]["score_semantics"],
        "eligibility_state": boundaries["eligibility_state"],
        "maximum_next_state": boundaries["maximum_next_state"],
        "summary": {
            "evaluated": len(rows),
            "matched": sum(row["state"] == "MATCHED_RESEARCH_CANDIDATE" for row in rows),
            "requires_verification": sum(row["state"] == "REQUIRES_VERIFICATION" for row in rows),
            "held": sum(row["state"] in {"HOLD_SOURCE_STATE", "HOLD_CONFLICT"} for row in rows),
            "suppressed": sum(row["state"] == "SUPPRESSED" for row in rows),
        },
        "results": rows,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    _assert_output_minimized(result, contract)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS Client Finder prospect/opportunity/service match explainability view")
    parser.add_argument("--match-view", required=True, type=Path)
    parser.add_argument("--score-view", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_view(load_json(args.match_view), load_json(args.score_view))
    write_atomic(args.output, result)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
