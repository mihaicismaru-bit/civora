#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

EUCONS = Path(__file__).resolve().parents[1]
ADAPTER_CONTRACT_PATH = EUCONS / "leads" / "public_intake_profile_adapter_contract.json"
INBOUND_CONTRACT_PATH = EUCONS / "leads" / "inbound_runtime_contract.json"
JTBD_CONTRACT_PATH = EUCONS / "web" / "jtbd_ux_contract.json"
PUBLIC_GUARD_PATH = EUCONS / "web" / "public_intake_progressive_disclosure_contract.json"

EXPECTED_ADAPTER_ID = "EUCONS-R05-PUBLIC-INTAKE-PROFILE-ADAPTER-001"
EXPECTED_GUARD_ID = "EUCONS-R04-PUBLIC-INTAKE-PROGRESSIVE-DISCLOSURE-001"
EXPECTED_JTBD_ID = "R04-JTBD-UX-001"
EXPECTED_INBOUND_ID = "R05-INBOUND-001"
EXPECTED_NEXT_GATE = "R05_CANONICAL_RUNTIME_REMAINS_SEPARATELY_GATED"
EMAIL_LIKE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
PHONE_LIKE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){9,}(?!\d)")


class AdapterError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"{path.name} must contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AdapterError(message)


def _journey_index(jtbd: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = jtbd.get("journeys")
    require(isinstance(rows, list) and rows, "R04 journeys missing")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), "R04 journey must be an object")
        journey_id = row.get("id")
        require(isinstance(journey_id, str) and journey_id, "R04 journey id missing")
        require(journey_id not in result, f"duplicate R04 journey: {journey_id}")
        result[journey_id] = row
    return result


def _guard_journey_index(guard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = guard.get("journeys")
    require(isinstance(rows, list) and rows, "public guard journeys missing")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), "public guard journey must be an object")
        journey_id = row.get("journey_id")
        require(isinstance(journey_id, str) and journey_id, "public guard journey_id missing")
        require(journey_id not in result, f"duplicate public guard journey: {journey_id}")
        result[journey_id] = row
    return result


def validate_configuration(
    adapter: dict[str, Any],
    guard: dict[str, Any],
    jtbd: dict[str, Any],
    inbound: dict[str, Any],
) -> None:
    require(adapter.get("schema_version") == 1, "unsupported adapter schema")
    require(adapter.get("id") == EXPECTED_ADAPTER_ID, "unexpected adapter id")
    require(adapter.get("status") == "DRAFT_FAIL_CLOSED", "adapter must remain fail-closed draft")
    require(guard.get("id") == EXPECTED_GUARD_ID and guard.get("status") == "DRAFT_FAIL_CLOSED", "public guard drift")
    require(jtbd.get("id") == EXPECTED_JTBD_ID and jtbd.get("status") == "CANONICAL", "R04 JTBD drift")
    require(inbound.get("id") == EXPECTED_INBOUND_ID and inbound.get("status") == "CANONICAL", "R05 inbound drift")
    require(inbound.get("production_collection_enabled") is False, "R05 production collection unexpectedly enabled")

    bindings = adapter.get("source_bindings")
    require(isinstance(bindings, dict), "source bindings missing")
    require(bindings.get("public_intake_guard_id") == guard.get("id"), "public guard binding drift")
    require(bindings.get("jtbd_contract_id") == jtbd.get("id"), "JTBD binding drift")
    require(bindings.get("inbound_runtime_contract_id") == inbound.get("id"), "R05 binding drift")
    require(bindings.get("required_guard_decision") == guard.get("decision", {}).get("state") == "PASS_CROSS_CONTRACT_GUARD_ONLY", "guard decision drift")
    require(bindings.get("required_runtime_stage") == "PROFILE", "adapter may materialize PROFILE only")

    require(inbound.get("lifecycle", [None])[0] == "PROFILE", "R05 PROFILE lifecycle drift")
    request_contract = inbound.get("request_contract")
    anti_abuse = inbound.get("anti_abuse")
    require(isinstance(request_contract, dict) and isinstance(anti_abuse, dict), "R05 request/anti-abuse contracts missing")
    require(request_contract.get("contact_before_contact_step_forbidden") is True, "R05 early-contact guard disabled")
    require(request_contract.get("out_of_step_fields_forbidden") is True, "R05 out-of-step guard disabled")

    guard_policy = guard.get("profile_stage_policy")
    guard_runtime = guard.get("runtime_boundaries")
    require(isinstance(guard_policy, dict) and isinstance(guard_runtime, dict), "public guard boundary sections missing")
    require(guard_policy.get("runtime_stage") == "PROFILE", "public guard PROFILE stage drift")
    require(guard_policy.get("person_level_pii_allowed") is False, "public guard permits person-level PII")
    require(guard_policy.get("contact_details_allowed") is False, "public guard permits contact details")
    require(guard_runtime.get("production_binding_enabled") is False, "public guard production binding enabled")
    require(guard_runtime.get("production_collection_enabled") is False, "public guard production collection enabled")
    require(guard_runtime.get("repository_pii_writes_forbidden") is True, "public guard repository PII writes not forbidden")

    journeys = _journey_index(jtbd)
    guard_journeys = _guard_journey_index(guard)
    form_map = inbound.get("journey_form_map")
    require(isinstance(form_map, dict), "R05 journey form map missing")
    require(set(journeys) == set(guard_journeys) == set(form_map), "R04/public-guard/R05 journey coverage drift")
    for journey_id, journey in journeys.items():
        first_step = journey.get("first_step_fields")
        require(isinstance(first_step, list) and first_step, f"{journey_id}: first-step fields missing")
        require(guard_journeys[journey_id].get("allowed_profile_fields") == first_step, f"{journey_id}: guard first-step binding drift")

    output = adapter.get("output_contract")
    decision = adapter.get("decision")
    action_guards = adapter.get("action_guards")
    require(isinstance(output, dict) and isinstance(decision, dict) and isinstance(action_guards, dict), "adapter output/decision guards missing")
    require(output.get("state") == "LOCAL_PROFILE_ENVELOPE_READY_REVIEW_REQUIRED", "adapter output state drift")
    require(output.get("route_sink") == "LOCAL_ONLY_NO_SUBMIT", "adapter must remain local-only")
    require(output.get("request_step") == "PROFILE", "adapter output may target PROFILE only")
    require(output.get("repository_persistence_allowed") is False, "adapter repository persistence enabled")
    require(output.get("browser_local_storage_allowed") is False, "raw intake local-storage retention enabled")
    require(output.get("telemetry_payload_values_allowed") is False, "raw intake telemetry values enabled")
    require(output.get("eligibility_state") == "NOT_ASSESSED", "adapter cannot assess eligibility")
    require(output.get("next_gate") == EXPECTED_NEXT_GATE, "adapter next gate drift")
    require(action_guards and all(value is False for value in action_guards.values()), "all adapter external-action guards must remain false")
    require(decision.get("state") == "LOCAL_ENVELOPE_ONLY", "adapter decision drift")
    require(decision.get("runtime_acceptance_authorized") is False, "adapter cannot authorize runtime acceptance")
    require(decision.get("production_collection_authorized") is False, "adapter cannot authorize production collection")
    require(decision.get("external_action_authorized") is False, "adapter cannot authorize external action")
    require(decision.get("next_gate") == EXPECTED_NEXT_GATE, "adapter decision next gate drift")


def _clean_required_text(value: Any, field: str, limit: int) -> str:
    require(isinstance(value, str), f"{field} must be text")
    text = re.sub(r"\s+", " ", value).strip()
    require(bool(text), f"{field} is required")
    require(len(text) <= limit, f"{field} exceeds {limit} characters")
    return text


def _contains_contact_like_token(value: Any) -> bool:
    if isinstance(value, str):
        return bool(EMAIL_LIKE.search(value) or PHONE_LIKE.search(value))
    if isinstance(value, list):
        return any(_contains_contact_like_token(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_contact_like_token(item) for item in value.values())
    return False


def build_profile_envelope(
    payload: dict[str, Any],
    adapter: dict[str, Any] | None = None,
    guard: dict[str, Any] | None = None,
    jtbd: dict[str, Any] | None = None,
    inbound: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapter = copy.deepcopy(adapter or load_json(ADAPTER_CONTRACT_PATH))
    guard = copy.deepcopy(guard or load_json(PUBLIC_GUARD_PATH))
    jtbd = copy.deepcopy(jtbd or load_json(JTBD_CONTRACT_PATH))
    inbound = copy.deepcopy(inbound or load_json(INBOUND_CONTRACT_PATH))
    validate_configuration(adapter, guard, jtbd, inbound)

    require(isinstance(payload, dict), "payload must be an object")
    input_contract = adapter["input_contract"]
    required_fields = set(input_contract["required_fields"])
    require(set(payload) == required_fields, f"payload fields must equal {sorted(required_fields)}")

    anti_abuse = inbound["anti_abuse"]
    session_id = _clean_required_text(payload.get("session_id"), "session_id", 200)
    request_id = _clean_required_text(payload.get("request_id"), "request_id", int(anti_abuse["request_id_max_length"]))
    journey_id = _clean_required_text(payload.get("journey_id"), "journey_id", 100)
    require(isinstance(payload.get("website"), str), "website must be text")
    require(not payload["website"].strip(), "spam honeypot triggered")
    age = payload.get("submission_age_ms")
    require(isinstance(age, (int, float)) and not isinstance(age, bool), "submission_age_ms must be numeric")
    require(anti_abuse["minimum_submission_age_ms"] <= age <= anti_abuse["maximum_submission_age_ms"], "submission_age_ms outside R05 anti-abuse window")

    journeys = _journey_index(jtbd)
    journey = journeys.get(journey_id)
    require(isinstance(journey, dict), "unknown journey_id")
    answers = payload.get("answers")
    require(isinstance(answers, dict), "answers must be an object")
    expected_fields = set(journey["first_step_fields"])
    require(set(answers) == expected_fields, f"PROFILE answers must equal {sorted(expected_fields)}")

    forbidden_fields = set(guard["profile_stage_policy"].get("forbidden_fields") or [])
    require(not (set(answers) & forbidden_fields), "contact/person/upload field leaked into PROFILE")
    for field, value in answers.items():
        require(value not in (None, "", []), f"PROFILE field required: {field}")
        if field == "message":
            require(not _contains_contact_like_token(value), "contact-like token detected in PROFILE free text")

    form_id = inbound["journey_form_map"].get(journey_id)
    require(isinstance(form_id, str) and form_id, "R05 form mapping unavailable")
    output_contract = adapter["output_contract"]
    return {
        "contract_id": adapter["id"],
        "state": output_contract["state"],
        "route_sink": output_contract["route_sink"],
        "session_id": session_id,
        "journey_id": journey_id,
        "form_id": form_id,
        "request": {
            "request_id": request_id,
            "submission_age_ms": age,
            "website": "",
            "step": "PROFILE",
            "answers": copy.deepcopy(answers),
        },
        "eligibility_state": output_contract["eligibility_state"],
        "funding_claim_state": output_contract["funding_claim_state"],
        "runtime_acceptance": "NOT_EXECUTED",
        "next_gate": output_contract["next_gate"],
        "transient_data_rule": "DO_NOT_PERSIST_OR_LOG_RAW_ANSWERS",
        "action_guards": copy.deepcopy(adapter["action_guards"]),
    }
