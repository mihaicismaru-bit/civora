#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "prospects" / "client_finder_operator_triage_contract.json"

DISABLED_ACTION_FLAGS = (
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
)

PROVENANCE_TOP_LEVEL_FIELDS = {
    "schema_version", "contract_id", "source_contract_id", "view_state", "semantics",
    "eligibility_state", "maximum_next_state", "summary", "rows", "human_review_required",
    *DISABLED_ACTION_FLAGS,
}
PROVENANCE_SUMMARY_FIELDS = {
    "review_queue_rows", "distinct_source_as_of_values", "source_as_of_ties_present",
    "oldest_source_as_of", "newest_source_as_of", "threshold_applied", "source_age_classification",
}
PROVENANCE_ROW_FIELDS = {
    "queue_rank", "prospect_id", "organization_key", "opportunity_id", "selected_service_id",
    "source_as_of", "relative_source_age_cue", "source_projection_sha256_present",
    "verification_evidence_count", "explanation_reasons", "operator_next_step", "threshold_applied",
    "source_age_classification", "eligibility_state", "maximum_next_state", "human_review_required",
    *DISABLED_ACTION_FLAGS,
}

MATCH_TOP_LEVEL_FIELDS = {
    "schema_version", "view_id", "view_state", "match_semantics", "priority_score_semantics",
    "eligibility_state", "maximum_next_state", "summary", "results", "human_review_required",
    *DISABLED_ACTION_FLAGS,
}
MATCH_SUMMARY_FIELDS = {"evaluated", "matched", "requires_verification", "held", "suppressed"}
MATCH_RESULT_FIELDS = {
    "organization_key", "prospect_id", "state", "priority_state", "priority_score",
    "priority_score_semantics", "score_breakdown", "recommended_service_id", "selected_service_id",
    "selected_service_support", "selected_opportunity", "reason_codes", "verification_questions",
    "source_ref_count", "signal_ids", "operator_next_step", "official_source_reverification_required",
    "material_claims_verified", "eligibility_state", "maximum_next_state", "human_review_required",
    *DISABLED_ACTION_FLAGS, "evidence_label",
}
SELECTED_OPPORTUNITY_FIELDS = {
    "opportunity_id", "title", "programme", "relevance_score", "relevance_semantics", "confidence",
    "verified_fact_classes", "matching_explanations",
}
SELECTED_SERVICE_SUPPORT_FIELDS = {"service_id", "supporting_signal_ids", "support_count", "support_ratio"}
SCORE_BREAKDOWN_FIELDS = {"score", "gross_score", "components", "penalties", "semantics"}
SCORE_COMPONENT_FIELDS = {"source_quality", "freshness", "signal_strength", "service_coherence", "actionability"}
SCORE_PENALTY_FIELDS = {"unknown_assertions", "low_confidence_inferences", "total"}
MATCH_STATES = {
    "MATCHED_RESEARCH_CANDIDATE", "REQUIRES_VERIFICATION", "NO_CURRENT_OPPORTUNITY",
    "HOLD_SOURCE_STATE", "HOLD_CONFLICT", "SUPPRESSED",
}
RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def recursive_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from recursive_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_keys(child)


def _assert_no_forbidden_fields(value: Any, contract: dict[str, Any]) -> None:
    policy = contract["output_policy"]
    forbidden = set(policy["raw_fields_forbidden"]) | set(policy["inference_fields_forbidden"])
    leaked = forbidden & set(recursive_keys(value))
    if leaked:
        raise ValueError(f"forbidden field present: {sorted(leaked)[0]}")


def _assert_action_boundaries(value: dict[str, Any], label: str) -> None:
    require(value.get("human_review_required") is True, f"{label} human review boundary failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(value.get(flag) is False, f"{label} {flag} failed open")


def _assert_qualification_boundaries(value: dict[str, Any], contract: dict[str, Any], label: str) -> None:
    boundaries = contract["required_boundaries"]
    require(value.get("eligibility_state") == boundaries["eligibility_state"], f"{label} eligibility boundary drift")
    require(value.get("maximum_next_state") == boundaries["maximum_next_state"], f"{label} next-state boundary drift")
    _assert_action_boundaries(value, label)


def _parse_source_as_of(value: Any) -> datetime:
    require(isinstance(value, str) and RFC3339_UTC_Z.fullmatch(value) is not None, "source_as_of must be RFC3339 UTC-Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("source_as_of timestamp invalid") from exc
    require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0, "source_as_of must resolve to UTC")
    return parsed


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "operator triage contract schema drift")
    require(contract.get("id") == "EUCONS-R07-CLIENT-FINDER-OPERATOR-TRIAGE-SYNTHESIS-001", "operator triage contract id drift")
    require(contract.get("status") == "CANONICAL", "operator triage contract must be canonical")

    expected_source = {
        "provenance_contract_id": "EUCONS-R07-CLIENT-FINDER-PROVENANCE-TRIAGE-EXPLAINABILITY-001",
        "provenance_view_state": "CLIENT_FINDER_PROVENANCE_TRIAGE_EXPLAINABILITY_VIEW",
        "provenance_semantics": "REVERIFICATION_QUEUE_EXPLAINABILITY_ONLY",
        "match_view_id": "EUCONS-R07-CLIENT-FINDER-MATCH-EXPLAINABILITY-001",
        "match_view_state": "CLIENT_FINDER_MATCH_EXPLAINABILITY_VIEW",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "priority_score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
    }
    require(contract.get("source_views") == expected_source, "operator triage source-view contract drift")

    expected_boundaries = {
        "eligibility_state": "NOT_ASSESSED", "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True, "external_contact_enabled": False,
        "automatic_offer_enabled": False, "automatic_send_enabled": False,
        "crm_write_enabled": False, "pipeline_write_enabled": False,
    }
    require(contract.get("required_boundaries") == expected_boundaries, "operator triage boundary drift")

    join = contract.get("join") or {}
    require(join.get("keys") == ["organization_key", "prospect_id", "opportunity_id", "selected_service_id"], "operator triage join-key drift")
    require(join.get("required_match_state") == "MATCHED_RESEARCH_CANDIDATE", "operator triage matched-state drift")
    require(join.get("matched_result_set_must_equal_provenance_queue") is True, "operator triage set reconciliation disabled")
    require(join.get("one_to_one_join_required") is True, "operator triage one-to-one join disabled")

    triage = contract.get("triage") or {}
    require(triage.get("queue_order") == "PROVENANCE_QUEUE_RANK_ASC", "operator triage queue order drift")
    require(triage.get("source_age_classification") == "NOT_CLASSIFIED", "operator triage source-age boundary failed open")
    require(triage.get("threshold_applied") is False, "operator triage freshness threshold failed open")
    require(triage.get("operator_next_step") == "REVERIFY_OFFICIAL_SOURCE_AND_VALIDATE_MATCH_BEFORE_OUTREACH", "operator triage next-step drift")
    require(triage.get("official_source_reverification_required") is True, "operator triage source reverification disabled")
    require(triage.get("material_claims_verified") is False, "operator triage material-claim boundary failed open")
    require(triage.get("required_provenance_operator_next_step") == "REVERIFY_OFFICIAL_SOURCE_BEFORE_MATERIAL_CLAIM", "provenance next-step drift")
    require(triage.get("required_provenance_explanation_reason") == "OFFICIAL_SOURCE_REVERIFICATION_REQUIRED_BEFORE_MATERIAL_CLAIM", "provenance reason drift")
    cues = triage.get("allowed_relative_age_cues") or []
    require(len(cues) == len(set(cues)) == 8, "relative source-age cue allowlist drift")

    output = contract.get("output_policy") or {}
    require(output.get("view_state") == "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW", "operator triage output state drift")
    require(output.get("semantics") == "OPERATOR_REVERIFICATION_AND_MATCH_REVIEW_ONLY", "operator triage output semantics drift")
    for key in (
        "include_provenance_relative_age_cue", "include_priority_score_breakdown",
        "include_selected_opportunity_minimized", "include_selected_service_support",
        "include_verification_questions",
    ):
        require(output.get(key) is True, f"operator triage output policy disabled: {key}")

    rules = contract.get("rules") or {}
    for name in (
        "provenance_rank_is_primary_queue_order", "never_reorder_by_priority_score",
        "matched_identity_must_reconcile_across_views", "never_classify_source_age",
        "never_apply_freshness_threshold", "official_source_reverification_before_material_claim",
        "match_validation_before_outreach", "never_treat_score_as_probability",
        "never_infer_eligibility_award_conversion_or_buying_intent",
        "never_expose_raw_provenance_hash_evidence_or_material_deadline",
        "never_generate_person_level_output", "safe_output_whitelist_only",
        "never_enable_external_action_or_persistence",
    ):
        require(rules.get(name) is True, f"operator triage safety rule failed open: {name}")


def _validate_score_breakdown(value: Any, expected_semantics: str) -> None:
    if value is None:
        return
    require(isinstance(value, dict) and set(value) == SCORE_BREAKDOWN_FIELDS, "score breakdown allowlist drift")
    require(set(value.get("components") or {}) == SCORE_COMPONENT_FIELDS, "score component allowlist drift")
    require(set(value.get("penalties") or {}) == SCORE_PENALTY_FIELDS, "score penalty allowlist drift")
    require(value.get("semantics") == expected_semantics, "score breakdown semantics drift")
    score, gross, penalties = value.get("score"), value.get("gross_score"), value["penalties"]
    require(isinstance(score, int) and not isinstance(score, bool), "score breakdown score must be integer")
    require(isinstance(gross, int) and not isinstance(gross, bool), "score breakdown gross score must be integer")
    require(all(isinstance(v, int) and not isinstance(v, bool) for v in value["components"].values()), "score component must be integer")
    require(all(isinstance(v, int) and not isinstance(v, bool) for v in penalties.values()), "score penalty must be integer")
    require(sum(value["components"].values()) == gross, "score breakdown gross score mismatch")
    require(penalties["unknown_assertions"] + penalties["low_confidence_inferences"] == penalties["total"], "score penalty total mismatch")
    require(max(0, gross - penalties["total"]) == score, "score breakdown net score mismatch")


def _validate_provenance_view(provenance_view: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    require(isinstance(provenance_view, dict), "provenance explainability view must be object")
    require(set(provenance_view) == PROVENANCE_TOP_LEVEL_FIELDS, "provenance explainability top-level allowlist drift")
    _assert_no_forbidden_fields(provenance_view, contract)
    source, triage = contract["source_views"], contract["triage"]
    require(provenance_view.get("schema_version") == 1, "provenance explainability schema drift")
    require(provenance_view.get("contract_id") == source["provenance_contract_id"], "provenance explainability contract mismatch")
    require(provenance_view.get("source_contract_id") == "EUCONS-R07-CLIENT-FINDER-PROVENANCE-FRESHNESS-001", "provenance explainability upstream contract drift")
    require(provenance_view.get("view_state") == source["provenance_view_state"], "provenance explainability view mismatch")
    require(provenance_view.get("semantics") == source["provenance_semantics"], "provenance explainability semantics mismatch")
    _assert_qualification_boundaries(provenance_view, contract, "provenance explainability")

    summary = provenance_view.get("summary")
    require(isinstance(summary, dict) and set(summary) == PROVENANCE_SUMMARY_FIELDS, "provenance summary allowlist drift")
    require(summary.get("threshold_applied") is False, "provenance summary applied a freshness threshold")
    require(summary.get("source_age_classification") == triage["source_age_classification"], "provenance summary classified source age")

    rows = provenance_view.get("rows")
    require(isinstance(rows, list), "provenance queue rows must be list")
    require(summary.get("review_queue_rows") == len(rows), "provenance queue row count mismatch")
    seen: set[tuple[str, str, str, str]] = set()
    parsed_times: list[datetime] = []
    for expected_rank, row in enumerate(rows, start=1):
        require(isinstance(row, dict) and set(row) == PROVENANCE_ROW_FIELDS, "provenance row allowlist drift")
        _assert_qualification_boundaries(row, contract, "provenance row")
        require(row.get("queue_rank") == expected_rank, "provenance queue rank must be contiguous")
        require(row.get("threshold_applied") is False, "provenance row applied a freshness threshold")
        require(row.get("source_age_classification") == triage["source_age_classification"], "provenance row classified source age")
        require(row.get("operator_next_step") == triage["required_provenance_operator_next_step"], "provenance row operator next-step drift")
        require(row.get("relative_source_age_cue") in triage["allowed_relative_age_cues"], "provenance relative source-age cue escaped allowlist")
        reasons = row.get("explanation_reasons")
        require(isinstance(reasons, list) and triage["required_provenance_explanation_reason"] in reasons, "provenance official-source reason missing")
        require(isinstance(row.get("source_projection_sha256_present"), bool), "provenance hash-presence cue must be boolean")
        count = row.get("verification_evidence_count")
        require(isinstance(count, int) and not isinstance(count, bool) and count > 0, "provenance verification reference count invalid")
        parsed_times.append(_parse_source_as_of(row.get("source_as_of")))
        identity = tuple(str(row.get(key) or "") for key in contract["join"]["keys"])
        require(all(identity), "provenance join identity missing")
        require(identity not in seen, "duplicate provenance join identity")
        seen.add(identity)

    require(parsed_times == sorted(parsed_times), "provenance queue lost oldest-source-first ordering")
    if rows:
        require(summary.get("oldest_source_as_of") == rows[0]["source_as_of"], "provenance oldest source summary drift")
        require(summary.get("newest_source_as_of") == rows[-1]["source_as_of"], "provenance newest source summary drift")
    else:
        require(summary.get("oldest_source_as_of") is None and summary.get("newest_source_as_of") is None, "empty provenance queue exposed source bounds")
    return rows


def _match_identity(row: dict[str, Any], contract: dict[str, Any]) -> tuple[str, str, str, str]:
    selected = row.get("selected_opportunity")
    values = {
        "organization_key": row.get("organization_key"),
        "prospect_id": row.get("prospect_id"),
        "opportunity_id": selected.get("opportunity_id") if isinstance(selected, dict) else None,
        "selected_service_id": row.get("selected_service_id"),
    }
    identity = tuple(str(values[key] or "") for key in contract["join"]["keys"])
    require(all(identity), "matched result join identity missing")
    return identity


def _validate_match_view(match_view: dict[str, Any], contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str, str], dict[str, Any]]]:
    require(isinstance(match_view, dict), "match explainability view must be object")
    require(set(match_view) == MATCH_TOP_LEVEL_FIELDS, "match explainability top-level allowlist drift")
    _assert_no_forbidden_fields(match_view, contract)
    source, triage = contract["source_views"], contract["triage"]
    require(match_view.get("schema_version") == 1, "match explainability schema drift")
    require(match_view.get("view_id") == source["match_view_id"], "match explainability view id mismatch")
    require(match_view.get("view_state") == source["match_view_state"], "match explainability view state mismatch")
    require(match_view.get("match_semantics") == source["match_semantics"], "match explainability semantics mismatch")
    require(match_view.get("priority_score_semantics") == source["priority_score_semantics"], "match explainability score semantics mismatch")
    _assert_qualification_boundaries(match_view, contract, "match explainability")

    summary, results = match_view.get("summary"), match_view.get("results")
    require(isinstance(summary, dict) and set(summary) == MATCH_SUMMARY_FIELDS, "match explainability summary allowlist drift")
    require(isinstance(results, list), "match explainability results must be list")
    require(summary.get("evaluated") == len(results), "match explainability evaluated count mismatch")
    states = [row.get("state") for row in results if isinstance(row, dict)]
    require(summary.get("matched") == sum(s == "MATCHED_RESEARCH_CANDIDATE" for s in states), "match summary matched count mismatch")
    require(summary.get("requires_verification") == sum(s == "REQUIRES_VERIFICATION" for s in states), "match summary verification count mismatch")
    require(summary.get("held") == sum(s in {"HOLD_SOURCE_STATE", "HOLD_CONFLICT"} for s in states), "match summary held count mismatch")
    require(summary.get("suppressed") == sum(s == "SUPPRESSED" for s in states), "match summary suppressed count mismatch")

    organizations: set[str] = set()
    matched_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in results:
        require(isinstance(row, dict) and set(row) == MATCH_RESULT_FIELDS, "match explainability result allowlist drift")
        _assert_qualification_boundaries(row, contract, "match result")
        org = row.get("organization_key")
        require(isinstance(org, str) and org.strip(), "match result organization_key missing")
        require(org not in organizations, "duplicate match organization_key")
        organizations.add(org)
        require(row.get("state") in MATCH_STATES, "unknown match explainability state")
        require(row.get("priority_score_semantics") == source["priority_score_semantics"], "match result score semantics drift")
        breakdown = row.get("score_breakdown")
        if row.get("priority_score") is not None:
            require(isinstance(row.get("priority_score"), int) and not isinstance(row.get("priority_score"), bool), "priority score must be integer or null")
            if isinstance(breakdown, dict):
                require(breakdown.get("score") == row["priority_score"], "priority score and breakdown drift")
        _validate_score_breakdown(breakdown, source["priority_score_semantics"])

        if row.get("state") != contract["join"]["required_match_state"]:
            continue
        selected, support = row.get("selected_opportunity"), row.get("selected_service_support")
        require(isinstance(selected, dict) and set(selected) == SELECTED_OPPORTUNITY_FIELDS, "matched selected opportunity allowlist drift")
        require(selected.get("relevance_semantics") == "RELEVANCE_NOT_APPROVAL_PROBABILITY", "selected opportunity relevance semantics failed open")
        require(isinstance(support, dict) and set(support) == SELECTED_SERVICE_SUPPORT_FIELDS, "matched selected service support allowlist drift")
        require(support.get("service_id") == row.get("selected_service_id"), "matched selected service support identity drift")
        require(row.get("operator_next_step") == triage["operator_next_step"], "matched operator next-step drift")
        require(row.get("official_source_reverification_required") is True, "matched source reverification boundary failed open")
        require(row.get("material_claims_verified") is False, "matched material-claim boundary failed open")
        identity = _match_identity(row, contract)
        require(identity not in matched_index, "duplicate matched join identity")
        matched_index[identity] = row
    return results, matched_index


def _provenance_identity(row: dict[str, Any], contract: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(key) or "") for key in contract["join"]["keys"])


def _build_queue_row(provenance_row: dict[str, Any], match_row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    triage = contract["triage"]
    output = {
        "queue_rank": provenance_row["queue_rank"],
        "organization_key": match_row["organization_key"],
        "prospect_id": match_row["prospect_id"],
        "priority_state": match_row["priority_state"],
        "priority_score": match_row["priority_score"],
        "priority_score_semantics": match_row["priority_score_semantics"],
        "score_breakdown": deepcopy(match_row["score_breakdown"]),
        "recommended_service_id": match_row["recommended_service_id"],
        "selected_service_id": match_row["selected_service_id"],
        "selected_service_support": deepcopy(match_row["selected_service_support"]),
        "selected_opportunity": deepcopy(match_row["selected_opportunity"]),
        "source_as_of": provenance_row["source_as_of"],
        "relative_source_age_cue": provenance_row["relative_source_age_cue"],
        "source_projection_sha256_present": provenance_row["source_projection_sha256_present"],
        "verification_evidence_count": provenance_row["verification_evidence_count"],
        "provenance_explanation_reasons": list(provenance_row["explanation_reasons"]),
        "match_reason_codes": list(match_row["reason_codes"]),
        "verification_questions": list(match_row["verification_questions"]),
        "source_ref_count": match_row["source_ref_count"],
        "signal_ids": list(match_row["signal_ids"]),
        "operator_next_step": triage["operator_next_step"],
        "official_source_reverification_required": True,
        "material_claims_verified": False,
        "source_age_classification": triage["source_age_classification"],
        "threshold_applied": False,
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "evidence_label": match_row["evidence_label"],
    }
    _assert_no_forbidden_fields(output, contract)
    _assert_qualification_boundaries(output, contract, "operator triage row")
    return output


def build_operator_triage_view(provenance_view: dict[str, Any], match_view: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_json(CONTRACT_PATH)
    validate_contract(contract)
    provenance_rows = _validate_provenance_view(provenance_view, contract)
    match_results, matched_index = _validate_match_view(match_view, contract)

    provenance_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in provenance_rows:
        identity = _provenance_identity(row, contract)
        require(identity not in provenance_index, "duplicate provenance join identity")
        provenance_index[identity] = row
    require(set(provenance_index) == set(matched_index), "matched result/provenance queue sets differ")

    queue = [_build_queue_row(row, matched_index[_provenance_identity(row, contract)], contract) for row in provenance_rows]
    require([row["queue_rank"] for row in queue] == list(range(1, len(queue) + 1)), "operator triage queue rank drift")

    result = {
        "schema_version": 1,
        "view_id": contract["id"],
        "view_state": contract["output_policy"]["view_state"],
        "semantics": contract["output_policy"]["semantics"],
        "match_semantics": contract["source_views"]["match_semantics"],
        "priority_score_semantics": contract["source_views"]["priority_score_semantics"],
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "summary": {
            "queue_rows": len(queue),
            "matched_results": len(matched_index),
            "nonmatched_research_rows_not_in_queue": len(match_results) - len(matched_index),
            "source_as_of_ties_present": provenance_view["summary"]["source_as_of_ties_present"],
            "threshold_applied": False,
            "source_age_classification": contract["triage"]["source_age_classification"],
        },
        "queue": queue,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    _assert_no_forbidden_fields(result, contract)
    _assert_qualification_boundaries(result, contract, "operator triage output")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS Client Finder backend operator triage synthesis")
    parser.add_argument("--provenance-view", required=True, type=Path)
    parser.add_argument("--match-view", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_operator_triage_view(load_json(args.provenance_view), load_json(args.match_view))
    write_atomic(args.output, result)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
