#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "research_evaluation_handoff_contract.json"

FORBIDDEN_PERSON_LEVEL_KEYS = {
    "person_name",
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
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _iter_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_keys(child)


def _safe_id(value: Any, field: str) -> str:
    _require(isinstance(value, str) and 0 < len(value.strip()) <= 240, f"invalid {field}")
    normalized = value.strip()
    _require("@" not in normalized and "\n" not in normalized and "\r" not in normalized, f"unsafe {field}")
    return normalized


def validate_contract(contract: dict[str, Any]) -> None:
    _require(contract.get("id") == "EUCONS-E11-R07-EVALUATION-HANDOFF-001", "evaluation handoff contract id drift")
    _require(contract.get("status") == "CANONICAL", "evaluation handoff contract is not canonical")
    _require(contract.get("source_match_contract") == "R07-PROSPECT-MATCH-001", "source match contract drift")
    _require(
        contract.get("source_match_semantics") == "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "source match semantics failed open",
    )
    _require(contract.get("required_source_state") == "MATCHED_RESEARCH_CANDIDATE", "source state drift")
    _require(contract.get("required_eligibility_state") == "NOT_ASSESSED", "eligibility boundary drift")
    _require(contract.get("required_maximum_next_state") == "RESEARCH_READY", "research boundary drift")
    output = contract.get("output") or {}
    _require(output.get("record_state") == "RESEARCH_EVALUATION_PENDING_HUMAN_REVIEW", "evaluation state drift")
    _require(output.get("human_review_required") is True, "human review boundary failed open")
    for field in ("external_contact_enabled", "automatic_offer_enabled", "crm_write_enabled"):
        _require(output.get(field) is False, f"{field} must remain disabled")
    rules = contract.get("rules") or {}
    for field in (
        "selected_opportunity_required",
        "selected_service_required",
        "selected_pair_must_exist_in_opportunity_matches",
        "source_external_actions_must_be_disabled",
        "person_level_fields_forbidden",
        "never_claim_eligibility_award_probability_or_buying_intent",
    ):
        _require(rules.get(field) is True, f"missing fail-closed rule: {field}")


def _selected_pair(match_record: dict[str, Any], opportunity_id: str, service_id: str) -> dict[str, Any]:
    matches = match_record.get("opportunity_matches")
    _require(isinstance(matches, list), "opportunity_matches must be a list")
    for row in matches:
        if not isinstance(row, dict) or str(row.get("opportunity_id")) != opportunity_id:
            continue
        aligned = row.get("aligned_service_ids")
        _require(isinstance(aligned, list), "aligned_service_ids must be a list")
        _require(service_id in aligned, "selected service is not aligned to selected opportunity")
        _require(row.get("selected_service_id") == service_id, "selected service pair drift")
        return row
    raise ValueError("selected opportunity/service pair not found")


def build_evaluation_handoff(match_record: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    _require(isinstance(match_record, dict), "match record must be an object")
    if FORBIDDEN_PERSON_LEVEL_KEYS & set(_iter_keys(match_record)):
        raise ValueError("person-level field entered research evaluation handoff")

    _require(match_record.get("state") == contract["required_source_state"], "source match is not evaluation-ready")
    _require(match_record.get("match_semantics") == contract["source_match_semantics"], "match semantics drift")
    _require(match_record.get("eligibility_state") == contract["required_eligibility_state"], "eligibility was assessed upstream")
    _require(match_record.get("maximum_next_state") == contract["required_maximum_next_state"], "source crossed research boundary")
    _require(match_record.get("external_contact_enabled") is False, "source enabled external contact")
    _require(match_record.get("automatic_offer_enabled") is False, "source enabled automatic offer")

    prospect_id = _safe_id(match_record.get("prospect_id"), "prospect_id")
    opportunity_id = _safe_id(match_record.get("selected_opportunity_id"), "selected_opportunity_id")
    service_id = _safe_id(match_record.get("selected_service_id"), "selected_service_id")
    pair = _selected_pair(match_record, opportunity_id, service_id)

    basis = "|".join((prospect_id, opportunity_id, service_id))
    evaluation_id = "EVAL-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "evaluation_id": evaluation_id,
        "record_state": output["record_state"],
        "prospect_id": prospect_id,
        "selected_opportunity_id": opportunity_id,
        "selected_service_id": service_id,
        "match_semantics": contract["source_match_semantics"],
        "eligibility_state": contract["required_eligibility_state"],
        "maximum_next_state": contract["required_maximum_next_state"],
        "source_provenance": pair.get("source_provenance") or {},
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "crm_write_enabled": False,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    args = parser.parse_args()
    result = build_evaluation_handoff(load_json(Path(args.input)), load_json(Path(args.contract)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
