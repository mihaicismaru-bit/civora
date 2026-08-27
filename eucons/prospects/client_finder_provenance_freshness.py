#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_provenance_freshness_contract.json"

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

DISABLED_ACTION_FLAGS = (
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
)

EXPECTED_SOURCE_TRACE_FIELDS = {
    "source_product",
    "source_opportunity_id",
    "source_as_of",
    "source_projection_sha256",
    "verification_evidence_count",
}

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
    require(isinstance(value, str) and RFC3339_UTC_Z.fullmatch(value) is not None,
            "source_as_of must be RFC3339 UTC with Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid source_as_of timestamp") from exc
    require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
            "source_as_of must resolve to UTC")
    return parsed


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "freshness contract schema version drift")
    require(contract.get("id") == "EUCONS-R07-CLIENT-FINDER-PROVENANCE-FRESHNESS-001",
            "freshness contract id drift")
    require(contract.get("status") == "CANONICAL", "freshness contract is not canonical")
    require(contract.get("source_contract_id") == "EUCONS-R07-CLIENT-FINDER-TRIAGE-VIEW-002",
            "freshness source contract drift")
    require(contract.get("required_source_view_state") == "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW",
            "freshness source view drift")
    require(contract.get("required_eligibility_state") == "NOT_ASSESSED",
            "freshness eligibility boundary drift")
    require(contract.get("required_maximum_next_state") == "RESEARCH_READY",
            "freshness research boundary drift")

    provenance = contract.get("provenance") or {}
    require(provenance.get("required_source_product") == "PARTENER.EU",
            "freshness provenance product drift")
    require(set(provenance.get("required_source_trace_fields") or []) == EXPECTED_SOURCE_TRACE_FIELDS,
            "freshness provenance field allowlist drift")
    require(provenance.get("source_as_of_format") == "RFC3339_UTC_Z",
            "freshness timestamp format drift")
    require(provenance.get("stale_after_hours") is None,
            "freshness contract invented a stale-after threshold")
    require(provenance.get("future_freshness_threshold") is None,
            "freshness contract invented a future threshold")
    require(provenance.get("raw_verification_evidence_exposed") is False,
            "freshness contract exposed raw verification evidence")

    ordering = contract.get("ordering") or {}
    require(ordering.get("mode") == "OLDEST_SOURCE_AS_OF_FIRST", "freshness ordering drift")
    require(ordering.get("tie_breakers") == ["prospect_id", "opportunity_id"],
            "freshness tie-breaker drift")

    output = contract.get("output") or {}
    require(output.get("view_state") == "CLIENT_FINDER_PROVENANCE_FRESHNESS_VIEW",
            "freshness output view drift")
    require(output.get("semantics") == "OBSERVABILITY_ONLY_NO_STALE_THRESHOLD",
            "freshness semantics drift")
    require(output.get("eligibility_state") == "NOT_ASSESSED",
            "freshness output eligibility failed open")
    require(output.get("maximum_next_state") == "RESEARCH_READY",
            "freshness output research boundary failed open")
    require(output.get("human_review_required") is True,
            "freshness human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"freshness {flag} must remain disabled")

    rules = contract.get("rules") or {}
    for name in (
        "matched_cards_only",
        "strict_rfc3339_utc_source_as_of",
        "oldest_source_first_is_ordering_not_staleness",
        "no_freshness_threshold_or_stale_claim",
        "never_expose_person_level_fields",
        "raw_verification_evidence_never_exposed",
        "safe_output_whitelist_only",
        "no_external_action_or_persistence",
    ):
        require(rules.get(name) is True, f"freshness rule failed open: {name}")


def _validate_source_trace(
    source_trace: Any,
    selected: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[dict[str, Any], datetime]:
    require(isinstance(source_trace, dict), "matched triage card missing source trace")
    require(set(source_trace) == EXPECTED_SOURCE_TRACE_FIELDS,
            "freshness source trace is not the minimized allowlist")
    provenance = contract["provenance"]
    require(source_trace.get("source_product") == provenance["required_source_product"],
            "freshness source product drift")
    opportunity_id = selected.get("opportunity_id")
    require(isinstance(opportunity_id, str) and opportunity_id.strip(),
            "freshness selected opportunity id missing")
    require(source_trace.get("source_opportunity_id") == opportunity_id,
            "freshness source opportunity id mismatch")
    parsed = parse_source_as_of(source_trace.get("source_as_of"))
    projection_sha = source_trace.get("source_projection_sha256")
    require(projection_sha is None or (
        isinstance(projection_sha, str)
        and len(projection_sha) == 64
        and all(char in "0123456789abcdef" for char in projection_sha.lower())
    ), "invalid freshness source projection hash")
    evidence_count = source_trace.get("verification_evidence_count")
    require(isinstance(evidence_count, int) and not isinstance(evidence_count, bool) and evidence_count > 0,
            "invalid freshness verification evidence count")
    return {
        "source_product": provenance["required_source_product"],
        "source_opportunity_id": opportunity_id,
        "source_as_of": source_trace["source_as_of"],
        "source_projection_sha256": projection_sha,
        "verification_evidence_count": evidence_count,
    }, parsed


def build_provenance_freshness_view(
    triage_result: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT_PATH)
    validate_contract(contract)
    require(isinstance(triage_result, dict), "triage result must be an object")
    require(triage_result.get("contract_id") == contract["source_contract_id"],
            "freshness source contract mismatch")
    require(triage_result.get("view_state") == contract["required_source_view_state"],
            "freshness source view mismatch")
    require(triage_result.get("eligibility_state") == contract["required_eligibility_state"],
            "freshness source eligibility failed open")
    require(triage_result.get("maximum_next_state") == contract["required_maximum_next_state"],
            "freshness source research boundary failed open")
    require(triage_result.get("human_review_required") is True,
            "freshness source human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(triage_result.get(flag) is False, f"freshness source {flag} failed open")

    cards = triage_result.get("cards")
    require(isinstance(cards, list), "freshness source cards must be a list")
    if FORBIDDEN_PERSON_KEYS & set(recursive_keys(cards)):
        raise ValueError("person-level field entered provenance freshness view")

    rows: list[tuple[datetime, dict[str, Any]]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for card in cards:
        require(isinstance(card, dict), "freshness source card must be an object")
        for flag in DISABLED_ACTION_FLAGS:
            require(card.get(flag) is False, f"freshness card {flag} failed open")
        selected = card.get("selected_opportunity")
        selected_service_id = card.get("selected_service_id")
        if selected is None:
            require(selected_service_id is None,
                    "freshness unmatched card retained selected service")
            continue
        require(isinstance(selected, dict), "freshness selected opportunity must be an object")
        require(isinstance(selected_service_id, str) and selected_service_id.strip(),
                "freshness matched card missing selected service")
        require(selected.get("selected_service_id") == selected_service_id,
                "freshness selected service mismatch")
        prospect_id = card.get("prospect_id")
        organization_key = card.get("organization_key")
        require(isinstance(prospect_id, str) and prospect_id.strip(), "freshness prospect id missing")
        require(isinstance(organization_key, str) and organization_key.strip(),
                "freshness organization key missing")
        opportunity_id = selected.get("opportunity_id")
        require(isinstance(opportunity_id, str) and opportunity_id.strip(),
                "freshness opportunity id missing")
        pair = (prospect_id, opportunity_id)
        require(pair not in seen_pairs, "duplicate freshness prospect-opportunity pair")
        seen_pairs.add(pair)
        safe_trace, parsed = _validate_source_trace(selected.get("source_trace"), selected, contract)
        rows.append((parsed, {
            "prospect_id": prospect_id,
            "organization_key": organization_key,
            "opportunity_id": opportunity_id,
            "selected_service_id": selected_service_id,
            "source_as_of": safe_trace["source_as_of"],
            "source_projection_sha256": safe_trace["source_projection_sha256"],
            "verification_evidence_count": safe_trace["verification_evidence_count"],
            "ordering_semantics": "OLDEST_SOURCE_AS_OF_FIRST_NOT_A_STALE_CLAIM",
            "human_review_required": True,
            "external_contact_enabled": False,
            "automatic_offer_enabled": False,
            "automatic_send_enabled": False,
            "crm_write_enabled": False,
            "pipeline_write_enabled": False,
        }))

    rows.sort(key=lambda item: (item[0], item[1]["prospect_id"], item[1]["opportunity_id"]))
    visible_rows: list[dict[str, Any]] = []
    for freshness_rank, (_, row) in enumerate(rows, start=1):
        row["freshness_rank"] = freshness_rank
        visible_rows.append(row)

    output = contract["output"]
    source_times = [row["source_as_of"] for row in visible_rows]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "source_contract_id": contract["source_contract_id"],
        "view_state": output["view_state"],
        "semantics": output["semantics"],
        "eligibility_state": output["eligibility_state"],
        "maximum_next_state": output["maximum_next_state"],
        "summary": {
            "matched_source_rows": len(visible_rows),
            "oldest_source_as_of": source_times[0] if source_times else None,
            "newest_source_as_of": source_times[-1] if source_times else None,
            "stale_threshold_applied": False,
        },
        "rows": visible_rows,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build a non-writing Client Finder provenance freshness observability view")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_provenance_freshness_view(load_json(args.input))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
