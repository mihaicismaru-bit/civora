#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_provenance_triage_explainability_contract.json"

DISABLED_ACTION_FLAGS = (
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
)

FORBIDDEN_PERSON_KEYS = {
    "person_name",
    "personal_name",
    "personal_email",
    "personal_phone",
    "home_address",
    "personal_social_profile",
    "personal_identifier",
    "date_of_birth",
    "private_contact",
    "contact_name",
    "email",
    "phone",
    "cnp",
}

EXPECTED_SOURCE_TOP_LEVEL_FIELDS = {
    "schema_version",
    "contract_id",
    "source_contract_id",
    "view_state",
    "semantics",
    "eligibility_state",
    "maximum_next_state",
    "summary",
    "rows",
    "human_review_required",
    *DISABLED_ACTION_FLAGS,
}

EXPECTED_SOURCE_SUMMARY_FIELDS = {
    "matched_source_rows",
    "oldest_source_as_of",
    "newest_source_as_of",
    "stale_threshold_applied",
}

EXPECTED_SOURCE_ROW_FIELDS = {
    "prospect_id",
    "organization_key",
    "opportunity_id",
    "selected_service_id",
    "source_as_of",
    "source_projection_sha256",
    "verification_evidence_count",
    "ordering_semantics",
    "human_review_required",
    "freshness_rank",
    *DISABLED_ACTION_FLAGS,
}

EXPECTED_RELATIVE_AGE_CUES = [
    "ONLY_MATCHED_SOURCE_SNAPSHOT",
    "ALL_MATCHED_SNAPSHOTS_SHARE_SOURCE_AS_OF",
    "EARLIEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
    "LATEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
    "INTERMEDIATE_SOURCE_SNAPSHOT_IN_CURRENT_SET",
    "TIED_EARLIEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
    "TIED_LATEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
    "TIED_INTERMEDIATE_SOURCE_SNAPSHOT_IN_CURRENT_SET",
]

EXPECTED_EXPLANATION_REASONS = [
    "RELATIVE_SOURCE_AS_OF_ORDER_ONLY",
    "OFFICIAL_SOURCE_REVERIFICATION_REQUIRED_BEFORE_MATERIAL_CLAIM",
    "VERIFICATION_REFERENCE_COUNT_PRESENT",
    "SOURCE_PROJECTION_HASH_AVAILABLE",
    "SOURCE_PROJECTION_HASH_NOT_AVAILABLE",
]

RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def parse_source_as_of(value: Any) -> datetime:
    require(
        isinstance(value, str) and RFC3339_UTC_Z.fullmatch(value) is not None,
        "source_as_of must be RFC3339 UTC with Z suffix",
    )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid source_as_of timestamp") from exc
    require(
        parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
        "source_as_of must resolve to UTC",
    )
    return parsed


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "explainability contract schema version drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-PROVENANCE-TRIAGE-EXPLAINABILITY-001",
        "explainability contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "explainability contract is not canonical")
    require(
        contract.get("source_contract_id") == "EUCONS-R07-CLIENT-FINDER-PROVENANCE-FRESHNESS-001",
        "explainability source contract drift",
    )
    require(
        contract.get("required_source_view_state") == "CLIENT_FINDER_PROVENANCE_FRESHNESS_VIEW",
        "explainability source view drift",
    )
    require(
        contract.get("required_source_semantics") == "OBSERVABILITY_ONLY_NO_STALE_THRESHOLD",
        "explainability source semantics drift",
    )
    require(
        contract.get("required_eligibility_state") == "NOT_ASSESSED",
        "explainability eligibility boundary drift",
    )
    require(
        contract.get("required_maximum_next_state") == "RESEARCH_READY",
        "explainability research boundary drift",
    )

    thresholds = contract.get("thresholds") or {}
    require(set(thresholds) == {"stale_after_hours", "fresh_after_hours"}, "threshold field drift")
    require(thresholds.get("stale_after_hours") is None, "explainability invented a stale threshold")
    require(thresholds.get("fresh_after_hours") is None, "explainability invented a fresh threshold")

    triage = contract.get("triage") or {}
    require(triage.get("queue_order") == "OLDEST_SOURCE_AS_OF_FIRST", "triage queue order drift")
    require(
        triage.get("operator_next_step") == "REVERIFY_OFFICIAL_SOURCE_BEFORE_MATERIAL_CLAIM",
        "operator next-step drift",
    )
    require(triage.get("source_age_classification") == "NOT_CLASSIFIED", "source age classification failed open")
    require(triage.get("allowed_relative_age_cues") == EXPECTED_RELATIVE_AGE_CUES, "relative age cue allowlist drift")
    require(
        triage.get("allowed_explanation_reasons") == EXPECTED_EXPLANATION_REASONS,
        "explanation reason allowlist drift",
    )
    require(
        triage.get("reason_semantics")
        == "FACTUAL_OPERATOR_CUES_NOT_QUALITY_STALENESS_ELIGIBILITY_OR_BUYING_INTENT_VERDICTS",
        "explanation reason semantics drift",
    )

    output = contract.get("output") or {}
    require(
        output.get("view_state") == "CLIENT_FINDER_PROVENANCE_TRIAGE_EXPLAINABILITY_VIEW",
        "explainability output view drift",
    )
    require(output.get("semantics") == "REVERIFICATION_QUEUE_EXPLAINABILITY_ONLY", "output semantics drift")
    require(output.get("eligibility_state") == "NOT_ASSESSED", "output eligibility failed open")
    require(output.get("maximum_next_state") == "RESEARCH_READY", "output research boundary failed open")
    require(output.get("human_review_required") is True, "human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"explainability {flag} must remain disabled")

    rules = contract.get("rules") or {}
    for name in (
        "matched_source_rows_only",
        "strict_rfc3339_utc_source_as_of",
        "freshness_rank_must_be_contiguous_and_oldest_first",
        "relative_age_cues_are_current_set_comparisons_only",
        "no_stale_or_fresh_classification",
        "no_source_quality_inference_from_age_hash_or_evidence_count",
        "official_source_reverification_before_material_claim",
        "never_expose_person_level_fields",
        "raw_verification_evidence_never_exposed",
        "safe_output_whitelist_only",
        "no_external_action_or_persistence",
    ):
        require(rules.get(name) is True, f"explainability rule failed open: {name}")


def _validate_projection_sha(value: Any) -> None:
    require(
        value is None
        or (
            isinstance(value, str)
            and len(value) == 64
            and all(char in "0123456789abcdef" for char in value.lower())
        ),
        "invalid source projection hash",
    )


def _validate_source(
    freshness_result: dict[str, Any],
    contract: dict[str, Any],
) -> list[tuple[datetime, dict[str, Any]]]:
    require(isinstance(freshness_result, dict), "freshness result must be an object")
    require(set(freshness_result) == EXPECTED_SOURCE_TOP_LEVEL_FIELDS, "freshness source top-level allowlist drift")
    if FORBIDDEN_PERSON_KEYS & set(recursive_keys(freshness_result)):
        raise ValueError("person-level field entered provenance triage explainability")

    require(freshness_result.get("schema_version") == 1, "freshness source schema version drift")
    require(freshness_result.get("contract_id") == contract["source_contract_id"], "freshness source contract mismatch")
    require(
        freshness_result.get("source_contract_id") == "EUCONS-R07-CLIENT-FINDER-TRIAGE-VIEW-002",
        "freshness upstream source contract drift",
    )
    require(
        freshness_result.get("view_state") == contract["required_source_view_state"],
        "freshness source view mismatch",
    )
    require(
        freshness_result.get("semantics") == contract["required_source_semantics"],
        "freshness source semantics mismatch",
    )
    require(
        freshness_result.get("eligibility_state") == contract["required_eligibility_state"],
        "freshness source eligibility failed open",
    )
    require(
        freshness_result.get("maximum_next_state") == contract["required_maximum_next_state"],
        "freshness source research boundary failed open",
    )
    require(freshness_result.get("human_review_required") is True, "freshness source human review missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(freshness_result.get(flag) is False, f"freshness source {flag} failed open")

    summary = freshness_result.get("summary")
    require(isinstance(summary, dict), "freshness source summary must be an object")
    require(set(summary) == EXPECTED_SOURCE_SUMMARY_FIELDS, "freshness source summary allowlist drift")
    require(summary.get("stale_threshold_applied") is False, "freshness source applied a stale threshold")

    rows = freshness_result.get("rows")
    require(isinstance(rows, list), "freshness source rows must be a list")
    require(summary.get("matched_source_rows") == len(rows), "freshness source row count mismatch")

    validated: list[tuple[datetime, dict[str, Any]]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for expected_rank, row in enumerate(rows, start=1):
        require(isinstance(row, dict), "freshness source row must be an object")
        require(set(row) == EXPECTED_SOURCE_ROW_FIELDS, "freshness source row allowlist drift")
        require(row.get("freshness_rank") == expected_rank, "freshness rank must be contiguous")
        require(
            row.get("ordering_semantics") == "OLDEST_SOURCE_AS_OF_FIRST_NOT_A_STALE_CLAIM",
            "freshness ordering semantics drift",
        )
        require(row.get("human_review_required") is True, "freshness row human review missing")
        for flag in DISABLED_ACTION_FLAGS:
            require(row.get(flag) is False, f"freshness row {flag} failed open")

        prospect_id = row.get("prospect_id")
        organization_key = row.get("organization_key")
        opportunity_id = row.get("opportunity_id")
        selected_service_id = row.get("selected_service_id")
        require(isinstance(prospect_id, str) and prospect_id.strip(), "prospect id missing")
        require(isinstance(organization_key, str) and organization_key.strip(), "organization key missing")
        require(isinstance(opportunity_id, str) and opportunity_id.strip(), "opportunity id missing")
        require(isinstance(selected_service_id, str) and selected_service_id.strip(), "selected service id missing")
        pair = (prospect_id, opportunity_id)
        require(pair not in seen_pairs, "duplicate prospect-opportunity pair")
        seen_pairs.add(pair)

        parsed = parse_source_as_of(row.get("source_as_of"))
        _validate_projection_sha(row.get("source_projection_sha256"))
        evidence_count = row.get("verification_evidence_count")
        require(
            isinstance(evidence_count, int) and not isinstance(evidence_count, bool) and evidence_count > 0,
            "verification evidence count must be a positive integer",
        )
        validated.append((parsed, row))

    actual_order = [
        (parsed, row["prospect_id"], row["opportunity_id"])
        for parsed, row in validated
    ]
    require(actual_order == sorted(actual_order), "freshness source rows are not oldest-source-first")

    if validated:
        require(summary.get("oldest_source_as_of") == validated[0][1]["source_as_of"], "oldest source summary drift")
        require(summary.get("newest_source_as_of") == validated[-1][1]["source_as_of"], "newest source summary drift")
    else:
        require(summary.get("oldest_source_as_of") is None, "empty source must not expose oldest timestamp")
        require(summary.get("newest_source_as_of") is None, "empty source must not expose newest timestamp")
    return validated


def _relative_age_cue(
    parsed: datetime,
    counts: Counter[datetime],
    minimum: datetime,
    maximum: datetime,
    total: int,
) -> str:
    if total == 1:
        return "ONLY_MATCHED_SOURCE_SNAPSHOT"
    if len(counts) == 1:
        return "ALL_MATCHED_SNAPSHOTS_SHARE_SOURCE_AS_OF"
    tied = counts[parsed] > 1
    if parsed == minimum:
        return "TIED_EARLIEST_SOURCE_SNAPSHOT_IN_CURRENT_SET" if tied else "EARLIEST_SOURCE_SNAPSHOT_IN_CURRENT_SET"
    if parsed == maximum:
        return "TIED_LATEST_SOURCE_SNAPSHOT_IN_CURRENT_SET" if tied else "LATEST_SOURCE_SNAPSHOT_IN_CURRENT_SET"
    return "TIED_INTERMEDIATE_SOURCE_SNAPSHOT_IN_CURRENT_SET" if tied else "INTERMEDIATE_SOURCE_SNAPSHOT_IN_CURRENT_SET"


def build_provenance_triage_explainability_view(
    freshness_result: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT_PATH)
    validate_contract(contract)
    validated = _validate_source(freshness_result, contract)

    counts: Counter[datetime] = Counter(parsed for parsed, _ in validated)
    minimum = min(counts) if counts else None
    maximum = max(counts) if counts else None
    rows: list[dict[str, Any]] = []
    for parsed, source_row in validated:
        require(minimum is not None and maximum is not None, "non-empty source lost timestamp bounds")
        projection_hash_present = source_row["source_projection_sha256"] is not None
        reasons = [
            "RELATIVE_SOURCE_AS_OF_ORDER_ONLY",
            "OFFICIAL_SOURCE_REVERIFICATION_REQUIRED_BEFORE_MATERIAL_CLAIM",
            "VERIFICATION_REFERENCE_COUNT_PRESENT",
            "SOURCE_PROJECTION_HASH_AVAILABLE" if projection_hash_present else "SOURCE_PROJECTION_HASH_NOT_AVAILABLE",
        ]
        require(set(reasons) <= set(contract["triage"]["allowed_explanation_reasons"]), "explanation reason escaped allowlist")
        cue = _relative_age_cue(parsed, counts, minimum, maximum, len(validated))
        require(cue in contract["triage"]["allowed_relative_age_cues"], "relative age cue escaped allowlist")
        rows.append({
            "queue_rank": source_row["freshness_rank"],
            "prospect_id": source_row["prospect_id"],
            "organization_key": source_row["organization_key"],
            "opportunity_id": source_row["opportunity_id"],
            "selected_service_id": source_row["selected_service_id"],
            "source_as_of": source_row["source_as_of"],
            "relative_source_age_cue": cue,
            "source_projection_sha256_present": projection_hash_present,
            "verification_evidence_count": source_row["verification_evidence_count"],
            "explanation_reasons": reasons,
            "operator_next_step": contract["triage"]["operator_next_step"],
            "threshold_applied": False,
            "source_age_classification": contract["triage"]["source_age_classification"],
            "eligibility_state": "NOT_ASSESSED",
            "maximum_next_state": "RESEARCH_READY",
            "human_review_required": True,
            "external_contact_enabled": False,
            "automatic_offer_enabled": False,
            "automatic_send_enabled": False,
            "crm_write_enabled": False,
            "pipeline_write_enabled": False,
        })

    output = contract["output"]
    source_times = [row["source_as_of"] for row in rows]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "source_contract_id": contract["source_contract_id"],
        "view_state": output["view_state"],
        "semantics": output["semantics"],
        "eligibility_state": output["eligibility_state"],
        "maximum_next_state": output["maximum_next_state"],
        "summary": {
            "review_queue_rows": len(rows),
            "distinct_source_as_of_values": len(counts),
            "source_as_of_ties_present": any(count > 1 for count in counts.values()),
            "oldest_source_as_of": source_times[0] if source_times else None,
            "newest_source_as_of": source_times[-1] if source_times else None,
            "threshold_applied": False,
            "source_age_classification": contract["triage"]["source_age_classification"],
        },
        "rows": rows,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build a non-writing Client Finder provenance re-verification explainability queue"
    )
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    result = build_provenance_triage_explainability_view(load_json(args.input))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
