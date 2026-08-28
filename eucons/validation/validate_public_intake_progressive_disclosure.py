#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "web" / "public_intake_progressive_disclosure_contract.json"
JTBD_PATH = ROOT / "web" / "jtbd_ux_contract.json"
IA_PATH = ROOT / "web" / "information_architecture.json"

EXPECTED_ID = "EUCONS-R04-PUBLIC-INTAKE-PROGRESSIVE-DISCLOSURE-001"
EXPECTED_JTBD_ID = "R04-JTBD-UX-001"
EXPECTED_IA_PHASE = "E06"
EXPECTED_JOURNEYS = {
    "JRN-FUNDING-FIT",
    "JRN-PROJECT-REVIEW",
    "JRN-IMPLEMENTATION",
    "JRN-RECOVERY",
}
FALSE_BOUNDARIES = {
    "network_submission_enabled",
    "persistence_enabled",
    "analytics_transport_enabled",
    "crm_write_enabled",
    "provider_write_enabled",
    "external_message_enabled",
    "offer_send_enabled",
    "file_upload_enabled",
    "automatic_contact_enabled",
}
FORBIDDEN_FIRST_STAGE = {
    "contact_details",
    "contact_name",
    "first_name",
    "last_name",
    "email",
    "phone",
    "telephone",
    "mobile",
    "cnp",
    "personal_id",
    "person_address",
    "recipient",
    "attachment",
    "attachments",
    "file",
    "files",
    "document_upload",
}


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path.name} must contain a JSON object")
    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def index_unique(rows: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    require(isinstance(rows, list) and rows, f"{label} must be a non-empty list")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), f"{label} entries must be objects")
        value = row.get(key)
        require(isinstance(value, str) and value, f"{label} entry missing {key}")
        require(value not in indexed, f"duplicate {label} {key}: {value}")
        indexed[value] = row
    return indexed


def validate_data(contract: dict[str, Any], jtbd: dict[str, Any], ia: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "unsupported intake contract schema")
    require(contract.get("id") == EXPECTED_ID, "unexpected intake contract id")
    require(contract.get("status") == "DRAFT_FAIL_CLOSED", "intake contract must remain fail-closed draft")

    bindings = contract.get("source_bindings")
    require(isinstance(bindings, dict), "source_bindings missing")
    require(jtbd.get("id") == EXPECTED_JTBD_ID, "canonical JTBD contract id drift")
    require(bindings.get("jtbd_contract_id") == jtbd.get("id"), "JTBD source binding drift")
    require(jtbd.get("status") == "CANONICAL", "JTBD source is not canonical")
    require(ia.get("phase") == EXPECTED_IA_PHASE, "information architecture phase drift")
    require(bindings.get("information_architecture_phase") == ia.get("phase"), "IA source binding drift")

    global_rules = jtbd.get("global_rules")
    require(isinstance(global_rules, dict), "JTBD global_rules missing")
    require(global_rules.get("progressive_data_minimization") is True, "progressive data minimization disabled upstream")
    require(global_rules.get("inferred_eligibility_forbidden") is True, "upstream inferred eligibility boundary disabled")
    require(global_rules.get("unavailable_submission_state_must_be_explicit") is True, "upstream unavailable-submit boundary disabled")

    policy = contract.get("first_stage_policy")
    require(isinstance(policy, dict), "first_stage_policy missing")
    require(policy.get("mode") == "LOCAL_CONTEXT_CAPTURE_ONLY", "first stage must remain local context capture")
    require(policy.get("submission_enabled") is False, "first-stage submission must remain disabled")
    require(policy.get("persistence_enabled") is False, "first-stage persistence must remain disabled")
    require(policy.get("person_level_pii_allowed") is False, "person-level PII must remain forbidden in first stage")
    require(policy.get("contact_details_allowed") is False, "contact details must remain forbidden in first stage")
    require(policy.get("attachments_allowed") is False, "attachments must remain forbidden in first stage")
    require(policy.get("material_claims_allowed") is False, "first stage cannot emit material claims")
    require(policy.get("eligibility_state") == "NOT_ASSESSED", "first stage cannot assess eligibility")
    require(policy.get("outcome") == "LOCAL_ROUTE_SELECTION_ONLY", "first-stage outcome drift")
    require(policy.get("external_action") == "NO_EXTERNAL_ACTION", "first stage cannot authorize external action")
    require(set(policy.get("forbidden_fields", [])) == FORBIDDEN_FIRST_STAGE, "forbidden first-stage field set drift")
    require(policy.get("free_text_fields") == ["message"], "free-text field policy drift")
    require(policy.get("free_text_rule") == "NO_PERSON_LEVEL_PII_OR_CONTACT_DETAILS", "free-text PII rule drift")

    source_journeys = index_unique(jtbd.get("journeys"), "id", "JTBD journeys")
    contract_journeys = index_unique(contract.get("journeys"), "journey_id", "intake journeys")
    require(set(contract_journeys) == EXPECTED_JOURNEYS, "intake journey coverage drift")
    require(EXPECTED_JOURNEYS.issubset(source_journeys), "canonical JTBD journey missing")

    core_routes = index_unique(ia.get("core_routes"), "id", "core routes")
    cta_destinations = index_unique(ia.get("cta_destinations"), "cta_id", "CTA destinations")

    for journey_id in sorted(EXPECTED_JOURNEYS):
        source = source_journeys[journey_id]
        bound = contract_journeys[journey_id]
        source_fields = source.get("first_step_fields")
        require(isinstance(source_fields, list) and source_fields, f"{journey_id}: first_step_fields missing")
        require(all(isinstance(field, str) and field for field in source_fields), f"{journey_id}: invalid first_step_fields")
        require(not (set(source_fields) & FORBIDDEN_FIRST_STAGE), f"{journey_id}: person/contact/upload field leaked into first stage")
        require(bound.get("allowed_first_stage_fields") == source_fields, f"{journey_id}: first-stage field binding drift")
        require(bound.get("route_id") == source.get("route_id"), f"{journey_id}: route id drift")
        require(bound.get("path") == source.get("path"), f"{journey_id}: path drift")

        route_id = source.get("route_id")
        require(route_id in core_routes, f"{journey_id}: canonical journey route missing")
        route = core_routes[route_id]
        require(route.get("surface") == bindings.get("journey_surface") == "JTBD_JOURNEY", f"{journey_id}: route surface drift")
        require(route.get("journey_id") == journey_id, f"{journey_id}: IA journey identity drift")
        require(route.get("path") == source.get("path"), f"{journey_id}: IA path drift")

        cta_id = source.get("cta_id")
        require(cta_id in cta_destinations, f"{journey_id}: CTA destination missing")
        require(cta_destinations[cta_id].get("path") == bindings.get("lead_handoff_path"), f"{journey_id}: CTA bypasses separate lead handoff")

    handoff = contract.get("contact_handoff")
    require(isinstance(handoff, dict), "contact_handoff missing")
    require(handoff.get("required") is True, "separate contact handoff must remain required")
    require(handoff.get("mode") == "SEPARATE_HUMAN_CONTACT_HANDOFF_REQUIRED", "contact handoff must remain human-gated")
    require(handoff.get("automatic") is False, "automatic contact handoff forbidden")
    require(handoff.get("contact_details_allowed_only_after_handoff") is True, "contact details cannot move before handoff")
    require(handoff.get("lead_route_id") == bindings.get("lead_handoff_route_id"), "lead route binding drift")
    require(handoff.get("lead_path") == bindings.get("lead_handoff_path"), "lead path binding drift")
    lead_route = core_routes.get(bindings.get("lead_handoff_route_id"))
    require(isinstance(lead_route, dict), "lead handoff route missing from IA")
    require(lead_route.get("surface") == "LEAD_JOURNEY", "lead handoff must remain a LEAD_JOURNEY")
    require(lead_route.get("path") == bindings.get("lead_handoff_path"), "lead handoff canonical path drift")

    boundaries = contract.get("boundaries")
    require(isinstance(boundaries, dict), "boundaries missing")
    for key in sorted(FALSE_BOUNDARIES):
        require(boundaries.get(key) is False, f"external/write boundary enabled: {key}")
    require(boundaries.get("research_crm_separation") is True, "research/CRM separation must remain explicit")

    decision = contract.get("decision")
    require(isinstance(decision, dict), "decision missing")
    require(decision.get("state") == "PASS_POLICY_GUARD_ONLY", "decision state drift")
    require(decision.get("runtime_materialization_authorized") is False, "guard cannot authorize runtime materialization")
    require(decision.get("external_action_authorized") is False, "guard cannot authorize external action")
    require(decision.get("next_gate") == "SEPARATE_PUBLIC_INTAKE_RUNTIME_IMPLEMENTATION_REVIEW_REQUIRED", "separate runtime gate missing")


def validate(
    contract_path: Path = CONTRACT_PATH,
    jtbd_path: Path = JTBD_PATH,
    ia_path: Path = IA_PATH,
) -> None:
    validate_data(load_json(contract_path), load_json(jtbd_path), load_json(ia_path))


def main() -> int:
    try:
        validate()
    except ValidationError as exc:
        print(json.dumps({"status": "FAIL", "phase": "R04_PUBLIC_INTAKE", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "phase": "R04_PUBLIC_INTAKE", "external_action": "NO_EXTERNAL_ACTION"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
