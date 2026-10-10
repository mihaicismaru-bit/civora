from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
RIGHTS_PATH = HERE / "GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json"

EXPECTED_SCHEMA = "eucons.ai4work_data_subject_rights.v0.8"
EXPECTED_EVIDENCE_KEY = "data_subject_rights_procedure"
EXPECTED_BASIS_CODE = "GDPR_ARTICLE_6_1_F_LEGITIMATE_INTERESTS"
PLACEHOLDER_PREFIXES = ("TO_BE_", "OPEN_", "UNRESOLVED_", "DE_", "TBD", "TODO", "NOT_IMPLEMENTED")


class DataSubjectRightsControlError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bound(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().upper().replace(" ", "_")
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


def data_subject_rights_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    procedure: dict[str, Any],
) -> list[str]:
    """Validate rights semantics independently of generic SHA/evidence binding.

    The draft is allowed to remain explicitly fail-closed. Once any PROD activation is
    claimed, the exact rights procedure must carry its own operational approval contract;
    a green workflow, an immutable hash, or the collection-only approval receipt cannot
    substitute for operational Article 11/12/15/16/18/21 handling.
    """
    errors: list[str] = []
    research_ids = {contract.get("research_id"), manifest.get("research_id"), procedure.get("research_id")}
    if len(research_ids) != 1 or None in research_ids:
        errors.append("research_id_mismatch")

    if procedure.get("schema_version") != EXPECTED_SCHEMA:
        errors.append("rights_schema_invalid")
    if procedure.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        errors.append("rights_evidence_class_invalid")

    identification = procedure.get("identification_policy")
    if not isinstance(identification, dict):
        errors.append("identification_policy_shape_invalid")
        identification = {}
    for key in ("direct_identity_registry", "crm_or_contact_cross_reference"):
        if identification.get(key) != "FORBIDDEN":
            errors.append(f"identity_linkage_not_forbidden:{key}")
    if identification.get("extra_identity_collection_for_rights_lookup") != "FORBIDDEN_BY_DEFAULT":
        errors.append("extra_identity_collection_not_forbidden_by_default")
    if identification.get("receipt_is_not_identity_proof") is not True:
        errors.append("receipt_misclassified_as_identity_proof")

    operations = procedure.get("research_store_operations")
    if not isinstance(operations, dict):
        errors.append("research_store_operations_shape_invalid")
        operations = {}
    expected_operations = {
        "restriction_or_objection_state_store": "BOUNDED_ENUM_ONLY_NO_CASE_NARRATIVE",
        "erasure_replay_suppression": "OPAQUE_RESPONSE_ID_ONLY_NO_ANSWERS_NO_BODY_DIGEST_NOT_ANALYTICAL",
        "erasure_replay_marker_reference_adapter_boundary": "REQUIRED_FINITE_UTC_NOT_AFTER_NO_DEFAULT",
        "erasure_replay_marker_export": "FORBIDDEN",
        "rectification_reference_adapter": "RECEIPT_KEYED_PRESET_VALUES_ONLY_REVALIDATE_FROZEN_FORM_PRESERVE_TECHNICAL_PROVENANCE",
    }
    for key, expected in expected_operations.items():
        if operations.get(key) != expected:
            errors.append(f"rights_operation_contract_invalid:{key}")
    for key in (
        "held_records_excluded_from_export",
        "erased_records_replay_blocked",
        "rectification_preserves_active_hold",
        "rectification_stale_retry_safe",
    ):
        if operations.get(key) is not True:
            errors.append(f"rights_operation_safeguard_missing:{key}")
    if operations.get("case_narrative_in_research_store") != "FORBIDDEN":
        errors.append("rights_case_narrative_not_forbidden_in_research_store")

    case_logging = procedure.get("rights_case_logging")
    if not isinstance(case_logging, dict) or case_logging.get("store") != "PRIVACY_REQUEST_ADMIN_SEPARATE_FROM_RESEARCH_ANALYTICS":
        errors.append("rights_case_log_not_separate_from_research_analytics")

    test_twin = procedure.get("test_twin")
    if not isinstance(test_twin, dict):
        errors.append("rights_test_twin_shape_invalid")
        test_twin = {}
    if test_twin.get("classification") != "TEST_TWIN_NON_EVIDENCE":
        errors.append("rights_test_twin_not_non_evidence")
    if test_twin.get("synthetic_only") is not True:
        errors.append("rights_test_twin_not_synthetic_only")
    if test_twin.get("prod_promotion_eligible") is not False:
        errors.append("rights_test_twin_promotable")

    activation_claimed = any(
        (
            contract.get("production_enabled") is True,
            manifest.get("approved_for_prod") is True,
            manifest.get("collection_enabled") is True,
            manifest.get("real_collection_authorized") is True,
            procedure.get("controller_approval") is True,
            procedure.get("collection_enabled") is True,
        )
    )
    if not activation_claimed:
        return errors

    if procedure.get("evidence_binding_key") != EXPECTED_EVIDENCE_KEY:
        errors.append("rights_evidence_binding_key_invalid")
    if procedure.get("synthetic") is not False:
        errors.append("rights_procedure_must_not_be_synthetic")
    if procedure.get("status") != "APPROVED_FOR_PROD":
        errors.append("rights_procedure_not_approved_for_prod")
    if procedure.get("controller_approval") is not True:
        errors.append("rights_controller_approval_missing")
    if procedure.get("collection_enabled") is not True:
        errors.append("rights_collection_not_enabled")

    channel = procedure.get("request_channel")
    if not isinstance(channel, dict):
        errors.append("rights_request_channel_shape_invalid")
        channel = {}
    if channel.get("status") != "OPERATIONAL_FOR_PROD":
        errors.append("rights_request_channel_not_operational")
    if not _bound(channel.get("privacy_contact")):
        errors.append("rights_privacy_contact_missing")

    applicability = procedure.get("rights_applicability")
    if not isinstance(applicability, dict):
        errors.append("rights_applicability_shape_invalid")
        applicability = {}
    if applicability.get("lawful_basis_status") != EXPECTED_BASIS_CODE:
        errors.append("rights_final_lawful_basis_not_reconciled")
    if "APPLIES" not in str(applicability.get("objection") or ""):
        errors.append("rights_objection_not_enabled_for_legitimate_interest")
    if not str(applicability.get("portability") or "").startswith("NOT_APPLICABLE"):
        errors.append("rights_portability_not_reconciled_to_legitimate_interest")
    if not str(applicability.get("consent_withdrawal") or "").startswith("NOT_APPLICABLE"):
        errors.append("rights_consent_withdrawal_not_reconciled_to_legitimate_interest")

    if not _bound(operations.get("access_requester_authentication_reference_adapter")):
        errors.append("rights_requester_authentication_not_operational")
    if operations.get("access_controller_context_required") is not True:
        errors.append("rights_article15_controller_context_not_required")

    approval = procedure.get("prod_approval")
    if not isinstance(approval, dict):
        errors.append("rights_prod_approval_shape_invalid")
        approval = {}
    if approval.get("state") != "APPROVED_FOR_PROD" or approval.get("approved") is not True:
        errors.append("rights_prod_approval_missing")
    if approval.get("final_lawful_basis_code") != EXPECTED_BASIS_CODE:
        errors.append("rights_prod_basis_code_invalid")
    for key in (
        "rights_applicability_reconciled",
        "article13_rights_text_reconciled",
        "requester_authentication_operational",
        "article15_confirmation_context_operational",
        "receipt_lookup_operational",
        "rectification_operational",
        "restriction_objection_hold_operational",
        "erasure_operational",
        "replay_marker_retention_approved",
        "provider_bound_test_twin_pass",
    ):
        if approval.get(key) is not True:
            errors.append(f"rights_prod_approval_not_satisfied:{key}")
    if approval.get("portability_decision") != "NOT_APPLICABLE_FINAL_LEGITIMATE_INTEREST_BASIS":
        errors.append("rights_portability_decision_invalid")
    if approval.get("consent_withdrawal_decision") != "NOT_APPLICABLE_FINAL_LEGITIMATE_INTEREST_BASIS":
        errors.append("rights_consent_withdrawal_decision_invalid")
    if not _bound(approval.get("privacy_contact")):
        errors.append("rights_prod_privacy_contact_missing")
    if approval.get("privacy_contact") != channel.get("privacy_contact"):
        errors.append("rights_privacy_contact_binding_mismatch")
    if not _bound(approval.get("approver_name_or_role")):
        errors.append("rights_prod_approver_missing")
    if not _non_future_date(approval.get("approved_at")):
        errors.append("rights_prod_approved_at_missing_or_invalid")

    return errors


def evaluate_repository_rights(
    *,
    contract_path: Path = CONTRACT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    rights_path: Path = RIGHTS_PATH,
) -> tuple[bool, list[str]]:
    contract = _load(contract_path)
    manifest = _load(manifest_path)
    procedure = _load(rights_path)
    errors = data_subject_rights_errors(contract=contract, manifest=manifest, procedure=procedure)
    return not errors, errors


def assert_repository_rights_safe() -> None:
    ready, errors = evaluate_repository_rights()
    if not ready:
        raise DataSubjectRightsControlError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_rights_safe()
    except (OSError, json.JSONDecodeError, DataSubjectRightsControlError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print("PASS: AI4WORK data-subject-rights procedure is structurally safe and remains fail-closed until controller approval and live rights operations are bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
