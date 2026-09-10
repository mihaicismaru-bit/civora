from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
CONTROLLER_PATH = HERE / "CONTROLLER_DETERMINATION_DRAFT.json"
DPIA_SCREENING_PATH = HERE / "GDPR_DPIA_SCREENING_DRAFT.json"

EXPECTED_SCHEMA = "eucons.ai4work_gdpr_dpia_screening.v0.3"
EXPECTED_EVIDENCE_KEY = "dpia_screening_or_completed_dpia"
EXPECTED_TEST_TWIN_POLICY = "TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_PREFIXES = ("TO_BE_", "OPEN_", "UNRESOLVED_", "TBD", "TODO")
APPROVED_CONCLUSIONS = {
    "DPIA_NOT_REQUIRED_APPROVED",
    "DPIA_REQUIRED_COMPLETED_AND_APPROVED",
}


class DpiaScreeningControlError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bound(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().upper()
    return not normalized.startswith(PLACEHOLDER_PREFIXES)


def _non_future_date(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    raw = value.strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        try:
            parsed_dt = datetime.fromisoformat(raw[:-1] + "+00:00") if raw.endswith("Z") else datetime.fromisoformat(raw)
        except ValueError:
            return False
        if parsed_dt.tzinfo is None:
            return False
        parsed = parsed_dt.astimezone(timezone.utc).date()
    return parsed <= datetime.now(timezone.utc).date()


def dpia_screening_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    controller: dict[str, Any],
    screening: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    research_ids = {
        contract.get("research_id"),
        manifest.get("research_id"),
        controller.get("research_id"),
        screening.get("research_id"),
    }
    if len(research_ids) != 1 or None in research_ids:
        errors.append("research_id_mismatch")

    if screening.get("schema_version") != EXPECTED_SCHEMA:
        errors.append("dpia_schema_invalid")
    if screening.get("evidence_binding_key") != EXPECTED_EVIDENCE_KEY:
        errors.append("dpia_evidence_binding_key_invalid")
    if screening.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        errors.append("dpia_evidence_class_invalid")
    if screening.get("synthetic") is not False:
        errors.append("dpia_must_not_be_synthetic")

    controller_identity = controller.get("controller") if isinstance(controller.get("controller"), dict) else {}
    screening_controller = screening.get("controller") if isinstance(screening.get("controller"), dict) else {}
    for key in ("legal_name", "cui"):
        if not _bound(screening_controller.get(key)) or screening_controller.get(key) != controller_identity.get(key):
            errors.append(f"dpia_controller_identity_mismatch:{key}")

    facts = screening.get("processing_design_facts")
    if not isinstance(facts, dict):
        errors.append("dpia_processing_design_facts_invalid")
        facts = {}
    expected_exact = {
        "direct_identifiers": "FORBIDDEN_BY_CONTRACT",
        "special_category_data": "FORBIDDEN_BY_CONTRACT",
        "criminal_conviction_data": "FORBIDDEN_BY_CONTRACT",
        "crm_or_contact_dataset_matching": "FORBIDDEN",
        "device_fingerprinting": "FORBIDDEN",
        "commercial_tracking": "FORBIDDEN",
        "individual_employment_decisions": "FORBIDDEN",
        "respondent_level_results_to_employers": "FORBIDDEN",
        "analytical_free_text": "FORBIDDEN_BY_CONTRACT",
        "test_twin_policy": EXPECTED_TEST_TWIN_POLICY,
    }
    for key, expected in expected_exact.items():
        if facts.get(key) != expected:
            errors.append(f"dpia_processing_safeguard_invalid:{key}")
    for key in (
        "systematic_public_area_monitoring",
        "profiling_or_person_level_scoring",
        "automated_decisions_with_legal_or_similarly_significant_effect",
        "participation_tied_to_employment_or_service",
    ):
        if facts.get(key) is not False:
            errors.append(f"dpia_high_risk_feature_not_forbidden:{key}")
    if facts.get("research_store_separate_from_crm") is not True:
        errors.append("dpia_research_store_not_separate")

    if contract.get("crm_integration") != "FORBIDDEN":
        errors.append("dpia_contract_crm_not_forbidden")
    if contract.get("commercial_analytics") != "FORBIDDEN":
        errors.append("dpia_contract_commercial_analytics_not_forbidden")
    if contract.get("special_category_data_forbidden") is not True:
        errors.append("dpia_contract_special_category_not_forbidden")
    tracking = contract.get("tracking") if isinstance(contract.get("tracking"), dict) else {}
    for key in ("advertising", "marketing_pixels", "fingerprinting", "cross_site_tracking", "analytics_default"):
        if tracking.get(key) is not False:
            errors.append(f"dpia_contract_tracking_not_disabled:{key}")
    for form_key in ("adult_form", "employer_form"):
        form = contract.get(form_key) if isinstance(contract.get(form_key), dict) else {}
        if form.get("free_text_fields") != []:
            errors.append(f"dpia_contract_free_text_not_forbidden:{form_key}")

    criteria = screening.get("edpb_screening_criteria")
    if not isinstance(criteria, dict):
        errors.append("dpia_edpb_criteria_invalid")
        criteria = {}
    no_trigger_keys = (
        "evaluation_or_scoring",
        "automated_decision_with_legal_or_similar_effect",
        "systematic_monitoring",
        "sensitive_or_highly_personal_data",
        "matching_or_combining_datasets",
        "prevents_right_or_service_or_contract",
    )
    for key in no_trigger_keys:
        entry = criteria.get(key) if isinstance(criteria.get(key), dict) else {}
        if entry.get("state") != "NOT_TRIGGERED_BY_CURRENT_DESIGN":
            errors.append(f"dpia_edpb_criterion_unresolved:{key}")
    large_scale = criteria.get("large_scale_processing") if isinstance(criteria.get("large_scale_processing"), dict) else {}
    if large_scale.get("state") != "NOT_TRIGGERED_BY_CURRENT_DOCUMENTED_METHOD_SCOPE":
        errors.append("dpia_large_scale_criterion_unresolved")
    vulnerable = criteria.get("vulnerable_data_subjects") if isinstance(criteria.get("vulnerable_data_subjects"), dict) else {}
    if vulnerable.get("state") != "SAFEGUARDED_NOT_TRIGGERING_MANDATORY_DPIA_ON_CURRENT_DESIGN":
        errors.append("dpia_vulnerable_subjects_criterion_unresolved")
    innovative = criteria.get("innovative_technology_or_organisational_solution") if isinstance(criteria.get("innovative_technology_or_organisational_solution"), dict) else {}
    if innovative.get("state") != "NOT_TRIGGERED_BY_CURRENT_PROCESSING":
        errors.append("dpia_innovative_processing_criterion_unresolved")

    anspdcp = screening.get("anspdcp_decision_174_2018_check")
    if not isinstance(anspdcp, dict):
        errors.append("dpia_anspdcp_check_invalid")
        anspdcp = {}
    if anspdcp.get("technical_check_complete") is not True:
        errors.append("dpia_anspdcp_technical_check_incomplete")
    for key in (
        "systematic_automated_personal_evaluation_with_significant_effect",
        "large_scale_special_category_or_criminal_data",
        "large_scale_public_area_monitoring",
        "large_scale_vulnerable_person_data_with_systematic_monitoring_or_recording",
        "large_scale_innovative_technology_limiting_rights",
        "large_scale_iot_sensor_data",
        "large_scale_or_systematic_traffic_or_location_data",
    ):
        if anspdcp.get(key) is not False:
            errors.append(f"dpia_anspdcp_trigger_present:{key}")

    assessment = screening.get("technical_assessment")
    if not isinstance(assessment, dict):
        errors.append("dpia_technical_assessment_invalid")
        assessment = {}
    if assessment.get("recommendation") not in {"DPIA_NOT_REQUIRED_ON_CURRENT_DESIGN", "DPIA_REQUIRED"}:
        errors.append("dpia_technical_recommendation_invalid")
    if assessment.get("controller_acceptance_required") is not True:
        errors.append("dpia_controller_acceptance_boundary_missing")

    trigger_text = "\n".join(str(item).lower() for item in screening.get("re_screen_triggers", []))
    for token in ("special-category", "profiling", "crm", "employer", "biometric", "retention", "security"):
        if token not in trigger_text:
            errors.append(f"dpia_rescreen_trigger_missing:{token}")

    if screening.get("merge_authorized") is not False:
        errors.append("dpia_merge_authority_escalated")
    if screening.get("deploy_authorized") is not False:
        errors.append("dpia_deploy_authority_escalated")
    if screening.get("real_collection_authorized") is not False:
        errors.append("dpia_must_not_independently_authorize_collection")

    activation_claimed = any(
        (
            contract.get("production_enabled") is True,
            manifest.get("approved_for_prod") is True,
            manifest.get("collection_enabled") is True,
            manifest.get("real_collection_authorized") is True,
        )
    )
    if activation_claimed:
        if screening.get("status") != "APPROVED_FOR_PROD":
            errors.append("dpia_not_approved_for_prod")
        if screening.get("approved") is not True:
            errors.append("dpia_approval_missing")
        if screening.get("collection_enabled") is not True:
            errors.append("dpia_collection_not_enabled")
        conclusion = screening.get("screening_conclusion")
        if conclusion not in APPROVED_CONCLUSIONS:
            errors.append("dpia_conclusion_not_final")

        mandatory = screening.get("mandatory_before_prod") if isinstance(screening.get("mandatory_before_prod"), dict) else {}
        if mandatory.get("controller_determination_approved") is not True:
            errors.append("dpia_controller_determination_not_approved")
        if not _bound(mandatory.get("privacy_contact_or_dpo_review_reference")):
            errors.append("dpia_privacy_review_reference_missing")
        if not _bound(mandatory.get("final_large_scale_assessment")):
            errors.append("dpia_final_large_scale_assessment_missing")
        if mandatory.get("employee_power_imbalance_safeguards_approved") is not True:
            errors.append("dpia_employee_safeguards_not_approved")
        if mandatory.get("anspdcp_decision_174_2018_final_check") is not True:
            errors.append("dpia_anspdcp_final_check_missing")
        if not _bound(mandatory.get("final_dpia_decision")):
            errors.append("dpia_final_decision_missing")
        if mandatory.get("if_residual_high_risk_prior_consultation_assessed") is not True:
            errors.append("dpia_article36_assessment_missing")

        acceptance = screening.get("controller_acceptance")
        if not isinstance(acceptance, dict):
            errors.append("dpia_controller_acceptance_missing")
            acceptance = {}
        if acceptance.get("approved") is not True:
            errors.append("dpia_controller_acceptance_not_approved")
        if acceptance.get("legal_entity_name") != controller_identity.get("legal_name"):
            errors.append("dpia_controller_acceptance_entity_mismatch")
        if not _bound(acceptance.get("approver_name_or_role")):
            errors.append("dpia_controller_approver_missing")
        if not _non_future_date(acceptance.get("approved_at")):
            errors.append("dpia_controller_approval_date_invalid")
        if not _bound(acceptance.get("privacy_contact_or_dpo_review_reference")):
            errors.append("dpia_controller_privacy_review_binding_missing")

        if conclusion == "DPIA_NOT_REQUIRED_APPROVED":
            if mandatory.get("final_dpia_decision") != "DPIA_NOT_REQUIRED_APPROVED":
                errors.append("dpia_not_required_decision_binding_mismatch")
        elif conclusion == "DPIA_REQUIRED_COMPLETED_AND_APPROVED":
            completed_ref = mandatory.get("if_dpia_required_completed_dpia_reference")
            if not _bound(completed_ref):
                errors.append("completed_dpia_reference_missing")
            completed_sha = mandatory.get("if_dpia_required_completed_dpia_sha256")
            if not isinstance(completed_sha, str) or not SHA256_RE.fullmatch(completed_sha):
                errors.append("completed_dpia_sha256_missing_or_invalid")
            if mandatory.get("final_dpia_decision") != "DPIA_REQUIRED_COMPLETED_AND_APPROVED":
                errors.append("completed_dpia_decision_binding_mismatch")

    return errors


def evaluate_repository_dpia(
    *,
    contract_path: Path = CONTRACT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    controller_path: Path = CONTROLLER_PATH,
    screening_path: Path = DPIA_SCREENING_PATH,
) -> tuple[bool, list[str]]:
    errors = dpia_screening_errors(
        contract=_load(contract_path),
        manifest=_load(manifest_path),
        controller=_load(controller_path),
        screening=_load(screening_path),
    )
    return not errors, errors


def assert_repository_dpia_safe() -> None:
    ready, errors = evaluate_repository_dpia()
    if not ready:
        raise DpiaScreeningControlError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_dpia_safe()
    except (OSError, json.JSONDecodeError, DpiaScreeningControlError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print("PASS: AI4WORK DPIA screening control is structurally valid and remains fail-closed until explicit controller acceptance and live pre-collection gates are complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
