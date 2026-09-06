#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "web" / "public_intake_progressive_disclosure_contract.json"
JTBD_PATH = ROOT / "web" / "jtbd_ux_contract.json"
IA_PATH = ROOT / "web" / "information_architecture.json"
INBOUND_PATH = ROOT / "leads" / "inbound_runtime_contract.json"

EXPECTED_ID = "EUCONS-R04-PUBLIC-INTAKE-PROGRESSIVE-DISCLOSURE-001"
EXPECTED_JTBD_ID = "R04-JTBD-UX-001"
EXPECTED_IA_PHASE = "E06"
EXPECTED_INBOUND_ID = "R05-INBOUND-001"
EXPECTED_JOURNEYS = {"JRN-FUNDING-FIT", "JRN-PROJECT-REVIEW", "JRN-IMPLEMENTATION", "JRN-RECOVERY"}
FORBIDDEN_PROFILE_FIELDS = {
    "contact_details", "contact_name", "first_name", "last_name", "email", "phone", "telephone", "mobile",
    "cnp", "personal_id", "person_address", "recipient", "attachment", "attachments", "file", "files", "document_upload",
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
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), f"{label} entries must be objects")
        value = row.get(key)
        require(isinstance(value, str) and value, f"{label} entry missing {key}")
        require(value not in result, f"duplicate {label} {key}: {value}")
        result[value] = row
    return result


def validate_data(contract: dict[str, Any], jtbd: dict[str, Any], ia: dict[str, Any], inbound: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "unsupported guard schema")
    require(contract.get("id") == EXPECTED_ID, "unexpected guard id")
    require(contract.get("status") == "DRAFT_FAIL_CLOSED", "guard must remain fail-closed draft")

    bindings = contract.get("source_bindings")
    require(isinstance(bindings, dict), "source_bindings missing")
    require(jtbd.get("id") == EXPECTED_JTBD_ID and jtbd.get("status") == "CANONICAL", "canonical R04 JTBD drift")
    require(ia.get("phase") == EXPECTED_IA_PHASE, "canonical IA phase drift")
    require(inbound.get("id") == EXPECTED_INBOUND_ID and inbound.get("status") == "CANONICAL", "canonical R05 inbound drift")
    require(bindings.get("jtbd_contract_id") == jtbd.get("id"), "R04 binding drift")
    require(bindings.get("information_architecture_phase") == ia.get("phase"), "IA binding drift")
    require(bindings.get("inbound_runtime_contract_id") == inbound.get("id"), "R05 binding drift")

    rules = jtbd.get("global_rules")
    require(isinstance(rules, dict), "R04 global_rules missing")
    require(rules.get("progressive_data_minimization") is True, "progressive data minimization disabled upstream")
    require(rules.get("inferred_eligibility_forbidden") is True, "inferred eligibility boundary disabled upstream")

    policy = contract.get("profile_stage_policy")
    require(isinstance(policy, dict), "profile_stage_policy missing")
    require(policy.get("runtime_stage") == "PROFILE", "profile stage identity drift")
    require(policy.get("internal_runtime_progression_allowed") is True, "canonical internal R05 progression must remain allowed")
    require(policy.get("production_collection_allowed") is False, "profile guard cannot activate production collection")
    require(policy.get("repository_pii_write_allowed") is False, "repository PII writes must remain forbidden")
    require(policy.get("person_level_pii_allowed") is False, "person-level PII leaked into PROFILE")
    require(policy.get("contact_details_allowed") is False, "contact details leaked into PROFILE")
    require(policy.get("attachments_allowed") is False, "attachments leaked into PROFILE")
    require(policy.get("material_claims_allowed") is False, "PROFILE cannot emit material claims")
    require(policy.get("eligibility_state") == "NOT_ASSESSED", "PROFILE cannot assess eligibility")
    require(policy.get("funding_claim_state") == "NO_PROGRAMME_CLAIM_WITHOUT_VERIFIED_MATCH", "funding claim boundary drift")
    require(set(policy.get("forbidden_fields", [])) == FORBIDDEN_PROFILE_FIELDS, "forbidden PROFILE field set drift")
    require(policy.get("free_text_fields") == ["message"], "free-text policy drift")
    require(policy.get("free_text_rule") == "NO_PERSON_LEVEL_PII_OR_CONTACT_DETAILS", "free-text PII rule drift")

    lifecycle = inbound.get("lifecycle")
    require(lifecycle == ["PROFILE", "CONTEXT", "CONTACT", "COMPLETED"], "R05 lifecycle drift")
    request_contract = inbound.get("request_contract")
    require(isinstance(request_contract, dict), "R05 request_contract missing")
    require(request_contract.get("contact_before_contact_step_forbidden") is True, "R05 early-contact boundary disabled")
    contact_fields = set(request_contract.get("contact_fields", []))
    require({"contact_name", "email", "phone", "privacy_ack", "marketing_consent", "submitted_at"}.issubset(contact_fields), "R05 contact field contract drift")

    source_journeys = index_unique(jtbd.get("journeys"), "id", "R04 journeys")
    guard_journeys = index_unique(contract.get("journeys"), "journey_id", "guard journeys")
    require(set(guard_journeys) == EXPECTED_JOURNEYS == set(inbound.get("journey_form_map", {})), "R04/R05 journey coverage drift")
    require(EXPECTED_JOURNEYS.issubset(source_journeys), "R04 canonical journey missing")
    core_routes = index_unique(ia.get("core_routes"), "id", "core routes")

    for journey_id in sorted(EXPECTED_JOURNEYS):
        source = source_journeys[journey_id]
        guard = guard_journeys[journey_id]
        fields = source.get("first_step_fields")
        require(isinstance(fields, list) and fields, f"{journey_id}: first_step_fields missing")
        require(all(isinstance(field, str) and field for field in fields), f"{journey_id}: invalid first_step_fields")
        require(not (set(fields) & FORBIDDEN_PROFILE_FIELDS), f"{journey_id}: person/contact/upload field leaked into PROFILE")
        require(guard.get("allowed_profile_fields") == fields, f"{journey_id}: PROFILE field binding drift")
        require(guard.get("route_id") == source.get("route_id") and guard.get("path") == source.get("path"), f"{journey_id}: R04 route/path drift")
        route = core_routes.get(source.get("route_id"))
        require(isinstance(route, dict), f"{journey_id}: canonical IA route missing")
        require(route.get("surface") == bindings.get("journey_surface") == "JTBD_JOURNEY", f"{journey_id}: IA surface drift")
        require(route.get("journey_id") == journey_id and route.get("path") == source.get("path"), f"{journey_id}: IA identity/path drift")

    contact = contract.get("contact_boundary")
    require(isinstance(contact, dict), "contact_boundary missing")
    require(contact.get("contact_stage") == "CONTACT", "contact stage drift")
    require(contact.get("contact_before_contact_stage_forbidden") is True, "early contact must remain forbidden")
    require(contact.get("privacy_ack_required_at_contact") is True, "privacy acknowledgement boundary drift")
    require(contact.get("marketing_consent_default") is False, "marketing consent cannot default true")
    require(contact.get("marketing_never_conditions_operational_response") is True, "marketing/operational separation drift")
    require(contact.get("raw_contact_removed_from_resumable_session_after_handoff") is True, "raw contact minimization drift")
    require(contact.get("contact_before_contact_stage_forbidden") == request_contract.get("contact_before_contact_step_forbidden"), "guard/R05 early-contact mismatch")
    require(contact.get("privacy_ack_required_at_contact") == request_contract.get("privacy_ack_required_at_contact"), "guard/R05 privacy acknowledgement mismatch")
    require(contact.get("marketing_consent_default") == request_contract.get("marketing_consent_default"), "guard/R05 marketing default mismatch")

    privacy = inbound.get("privacy_and_purpose")
    storage = inbound.get("storage")
    telemetry = inbound.get("telemetry")
    public_form = inbound.get("public_form_contract")
    require(all(isinstance(x, dict) for x in (privacy, storage, telemetry, public_form)), "R05 boundary sections missing")
    runtime = contract.get("runtime_boundaries")
    require(isinstance(runtime, dict), "runtime_boundaries missing")
    require(runtime.get("production_binding_enabled") is False and public_form.get("endpoint", {}).get("production_binding_enabled") is False, "production endpoint binding enabled")
    require(runtime.get("production_collection_enabled") is False and inbound.get("production_collection_enabled") is False, "production collection enabled")
    require(runtime.get("provider_adapter_required_for_persistence") is True and privacy.get("provider_adapter_required_for_persistence") is True, "provider persistence gate drift")
    require(runtime.get("repository_runtime_storage") is False and storage.get("repository_runtime_storage") is False, "repository runtime storage enabled")
    require(runtime.get("repository_pii_writes_forbidden") is True and privacy.get("repository_pii_writes_forbidden") is True, "repository PII boundary drift")
    require(runtime.get("telemetry_payload_values_forbidden") is True and telemetry.get("payload_values_forbidden") is True, "telemetry payload boundary drift")
    require(runtime.get("telemetry_raw_contact_forbidden") is True and telemetry.get("raw_contact_forbidden") is True, "telemetry raw-contact boundary drift")
    require(runtime.get("telemetry_production_transport_enabled") is False and telemetry.get("production_transport_enabled") is False, "production telemetry transport enabled")
    require(runtime.get("research_crm_separation") is True, "research/CRM separation must remain explicit")

    decision = contract.get("decision")
    require(isinstance(decision, dict), "decision missing")
    require(decision.get("state") == "PASS_CROSS_CONTRACT_GUARD_ONLY", "decision state drift")
    require(decision.get("runtime_materialization_authorized") is False, "guard cannot authorize runtime materialization")
    require(decision.get("production_activation_authorized") is False, "guard cannot authorize production activation")
    require(decision.get("external_action_authorized") is False, "guard cannot authorize external action")
    require(decision.get("next_gate") == "R05_CANONICAL_RUNTIME_REMAINS_SEPARATELY_GATED", "R05 separate gate drift")


def validate(contract_path: Path = CONTRACT_PATH, jtbd_path: Path = JTBD_PATH, ia_path: Path = IA_PATH, inbound_path: Path = INBOUND_PATH) -> None:
    validate_data(load_json(contract_path), load_json(jtbd_path), load_json(ia_path), load_json(inbound_path))


def main() -> int:
    try:
        validate()
    except ValidationError as exc:
        print(json.dumps({"status": "FAIL", "phase": "R04_PUBLIC_INTAKE_GUARD", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "phase": "R04_PUBLIC_INTAKE_GUARD", "r05_runtime": "SEPARATELY_GATED"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
