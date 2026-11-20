from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
PROCEDURE_PATH = HERE / "GDPR_SECURITY_INCIDENT_RESPONSE_DRAFT.json"

PLACEHOLDER_PREFIXES = ("TO_BE_", "OPEN_", "UNRESOLVED_", "DE_")
REQUIRED_SEQUENCE = {
    "DETECT_AND_RECORD_INITIAL_SIGNAL",
    "CONTAIN_WITHOUT_DESTROYING_NECESSARY_AUDIT_EVIDENCE",
    "ESTABLISH_AWARENESS_TIMESTAMP_WHEN_REASONABLE_CERTAINTY_EXISTS",
    "ASSESS_CONFIDENTIALITY_INTEGRITY_AVAILABILITY_AND_DATA_SUBJECT_RISK",
    "NOTIFY_CONTROLLER_WITHOUT_UNDUE_DELAY_IF_DETECTED_BY_PROCESSOR_OR_SERVICE_PROVIDER",
    "DOCUMENT_DECISION_FOR_EVERY_PERSONAL_DATA_BREACH_IN_BREACH_REGISTER",
    "IF_RISK_IS_NOT_UNLIKELY_PREPARE_AND_ESCALATE_SUPERVISORY_AUTHORITY_NOTIFICATION_FOR_CONTROLLER_ACTION_WITHIN_72_HOURS_WHERE_FEASIBLE",
    "IF_HIGH_RISK_PREPARE_AND_ESCALATE_DATA_SUBJECT_COMMUNICATION_WITHOUT_UNDUE_DELAY_UNLESS_AN_ARTICLE_34_EXCEPTION_IS_DOCUMENTED",
    "REMEDIATE_VALIDATE_RECOVERY_AND_RECORD_CLOSURE",
    "TRIGGER_CONTROL_REASSESSMENT_BEFORE_COLLECTION_RESUMES_WHERE_THE_INCIDENT_AFFECTS_PROD_ASSUMPTIONS",
}
REQUIRED_BREACH_REGISTER_FIELDS = {
    "incident_id",
    "detected_at",
    "controller_awareness_at",
    "facts_and_nature_of_breach",
    "affected_data_categories",
    "approximate_data_subject_count_if_known",
    "approximate_record_count_if_known",
    "effects_and_likely_consequences",
    "risk_assessment_and_rationale",
    "containment_and_remedial_actions",
    "dpa_notification_required_and_rationale",
    "dpa_notification_timestamp_or_delay_reason_if_applicable",
    "data_subject_communication_required_and_rationale",
    "data_subject_communication_timestamp_if_applicable",
    "processor_notifications_and_timestamps_if_applicable",
    "recovery_validation",
    "closure_and_follow_up_actions",
}
MANDATORY_BEFORE_PROD_KEYS = {
    "controller_approval",
    "privacy_contact_bound",
    "incident_owner_assigned",
    "breach_register_location_bound",
    "anspdcp_notification_route_live_verified",
    "processor_escalation_route_bound",
    "restore_and_recovery_control_live_verified",
    "access_and_logging_control_live_verified",
    "provider_breach_notification_contract_path_verified",
}


class SecurityIncidentResponseError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bound(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().upper()
    return not normalized.startswith(PLACEHOLDER_PREFIXES)


def incident_response_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    procedure: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    research_ids = {contract.get("research_id"), manifest.get("research_id"), procedure.get("research_id")}
    if len(research_ids) != 1 or None in research_ids:
        errors.append("research_id_mismatch")

    if procedure.get("evidence_binding_key") != "security_incident_response_procedure":
        errors.append("evidence_binding_key_invalid")
    if procedure.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        errors.append("evidence_class_invalid")
    if procedure.get("synthetic") is not False:
        errors.append("procedure_must_not_be_synthetic")
    if procedure.get("collection_enabled") is not False and procedure.get("status") != "APPROVED_FOR_PROD":
        errors.append("draft_procedure_collection_enabled")

    scope = procedure.get("scope") or {}
    if scope.get("crm_or_commercial_reuse") != "FORBIDDEN":
        errors.append("incident_crm_reuse_not_forbidden")
    if "NON_EVIDENCE" not in str(scope.get("test_twin_policy") or ""):
        errors.append("test_twin_incident_policy_not_non_evidence")

    sequence = set(procedure.get("mandatory_response_sequence") or [])
    missing_sequence = REQUIRED_SEQUENCE - sequence
    if missing_sequence:
        errors.append("mandatory_response_sequence_missing:" + ",".join(sorted(missing_sequence)))

    awareness = procedure.get("awareness_and_clock") or {}
    if "72_HOURS" not in str(awareness.get("supervisory_authority_target") or ""):
        errors.append("supervisory_authority_72_hour_clock_missing")
    if awareness.get("phased_notification_supported") is not True:
        errors.append("phased_notification_not_supported")

    risk = procedure.get("risk_decision") or {}
    if "unlikely" not in str(risk.get("dpa_notification") or "").lower():
        errors.append("dpa_risk_threshold_missing")
    if "high risk" not in str(risk.get("data_subject_communication") or "").lower():
        errors.append("data_subject_high_risk_threshold_missing")

    register_fields = set(procedure.get("breach_register_minimum") or [])
    missing_register = REQUIRED_BREACH_REGISTER_FIELDS - register_fields
    if missing_register:
        errors.append("breach_register_fields_missing:" + ",".join(sorted(missing_register)))

    security = procedure.get("security_and_data_minimisation") or {}
    if security.get("incident_register_separate_from_crm") is not True:
        errors.append("incident_register_not_separate_from_crm")
    if security.get("commercial_tracking_forbidden") is not True:
        errors.append("incident_commercial_tracking_not_forbidden")

    communications = procedure.get("external_communication_boundary") or {}
    if communications.get("automatic_external_notification") is not False:
        errors.append("automatic_external_notification_not_forbidden")

    resume = procedure.get("resume_collection_gate") or {}
    if resume.get("automatic_resume") is not False:
        errors.append("automatic_collection_resume_not_forbidden")

    # A draft procedure is valid as a control artifact while PROD remains fail-closed.
    activation_claimed = any(
        (
            contract.get("production_enabled") is True,
            manifest.get("approved_for_prod") is True,
            manifest.get("collection_enabled") is True,
            manifest.get("real_collection_authorized") is True,
        )
    )
    if activation_claimed:
        if procedure.get("status") != "APPROVED_FOR_PROD":
            errors.append("incident_response_not_approved_for_prod")
        if procedure.get("controller_approval") is not True:
            errors.append("incident_response_controller_approval_missing")
        if procedure.get("prod_eligible") is not True:
            errors.append("incident_response_not_prod_eligible")
        for field in (
            "privacy_contact",
            "incident_owner",
            "breach_register_location",
            "anspdcp_notification_route",
            "processor_escalation_route",
        ):
            if not _bound(procedure.get(field)):
                errors.append(f"incident_response_binding_missing:{field}")
        mandatory = procedure.get("mandatory_before_prod")
        if not isinstance(mandatory, dict):
            errors.append("mandatory_before_prod_missing")
        else:
            missing_keys = MANDATORY_BEFORE_PROD_KEYS - set(mandatory)
            if missing_keys:
                errors.append("mandatory_before_prod_keys_missing:" + ",".join(sorted(missing_keys)))
            for key in sorted(MANDATORY_BEFORE_PROD_KEYS & set(mandatory)):
                if mandatory.get(key) is not True:
                    errors.append(f"mandatory_before_prod_not_satisfied:{key}")

    return errors


def evaluate_repository_incident_response(
    *,
    contract_path: Path = CONTRACT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    procedure_path: Path = PROCEDURE_PATH,
) -> tuple[bool, list[str]]:
    contract = _load(contract_path)
    manifest = _load(manifest_path)
    procedure = _load(procedure_path)
    errors = incident_response_errors(contract=contract, manifest=manifest, procedure=procedure)
    return not errors, errors


def assert_repository_incident_response_safe() -> None:
    ready, errors = evaluate_repository_incident_response()
    if not ready:
        raise SecurityIncidentResponseError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_incident_response_safe()
    except (OSError, json.JSONDecodeError, SecurityIncidentResponseError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print("PASS: AI4WORK GDPR incident-response procedure is structurally complete and PROD remains fail-closed until controller/live bindings are approved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
