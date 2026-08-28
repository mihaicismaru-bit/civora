from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
CONTROLLER_PATH = HERE / "CONTROLLER_DETERMINATION_DRAFT.json"
COLLECTION_FRAME_PATH = HERE / "COLLECTION_FRAME_DRAFT.json"
DPIA_SCREENING_PATH = HERE / "GDPR_DPIA_SCREENING_DRAFT.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
APPROVED_EXTERNAL_STATUSES = {"APPROVED", "PASS", "FROZEN"}
REQUIRED_EXTERNAL_KEYS = {
    "privacy_notice",
    "lawful_basis_or_lia",
    "processor_chain",
    "provider_annex_4_5",
    "provider_server_logging_profile",
    "account_server_logging_binding",
    "retention_and_deletion",
    "data_subject_rights_procedure",
    "dpia_screening_or_completed_dpia",
    "research_only_store_binding",
    "provider_bound_test_twin_smoke",
}


class ProductionActivationError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_external_reference(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    status = value.get("status")
    reference = value.get("reference")
    digest = value.get("sha256")
    return (
        status in APPROVED_EXTERNAL_STATUSES
        and isinstance(reference, str)
        and bool(reference.strip())
        and isinstance(digest, str)
        and bool(SHA256_RE.fullmatch(digest))
    )


def _valid_frozen_local_binding(value: dict[str, Any]) -> bool:
    """FROZEN repo-local bindings must exist under HERE and match their declared SHA-256."""
    if value.get("status") != "FROZEN":
        return True
    reference = str(value.get("reference") or "").strip()
    digest = str(value.get("sha256") or "").strip()
    if not reference or not SHA256_RE.fullmatch(digest):
        return False
    candidate = (HERE / reference).resolve()
    try:
        candidate.relative_to(HERE.resolve())
    except ValueError:
        return False
    if not candidate.is_file():
        return False
    return hashlib.sha256(candidate.read_bytes()).hexdigest() == digest


def activation_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    controller: dict[str, Any],
    collection_frame: dict[str, Any],
    dpia_screening: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    research_ids = {
        contract.get("research_id"),
        manifest.get("research_id"),
        controller.get("research_id"),
        collection_frame.get("research_id"),
        dpia_screening.get("research_id"),
    }
    if len(research_ids) != 1 or None in research_ids:
        errors.append("research_id_mismatch")

    if contract.get("production_enabled") is not True:
        errors.append("form_contract_production_disabled")
    if contract.get("crm_integration") != "FORBIDDEN":
        errors.append("crm_integration_not_forbidden")
    if contract.get("commercial_analytics") != "FORBIDDEN":
        errors.append("commercial_analytics_not_forbidden")

    if manifest.get("state") != "APPROVED_FOR_PROD":
        errors.append("activation_manifest_not_approved")
    if manifest.get("approved_for_prod") is not True:
        errors.append("activation_manifest_approval_false")
    if manifest.get("collection_enabled") is not True:
        errors.append("activation_manifest_collection_disabled")
    if manifest.get("activation_mode") != "PROD_REAL_EVIDENCE_ONLY":
        errors.append("activation_mode_not_real_evidence_only")
    if manifest.get("test_twin_policy") != "TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE":
        errors.append("test_twin_policy_not_fail_closed")
    user_approval = manifest.get("explicit_user_approval_reference")
    if not isinstance(user_approval, str) or not user_approval.strip():
        errors.append("explicit_user_approval_missing")
    approval_timestamp = manifest.get("approval_timestamp")
    if not isinstance(approval_timestamp, str) or not approval_timestamp.strip():
        errors.append("approval_timestamp_missing")

    if controller.get("controller") in (None, ""):
        errors.append("controller_unresolved")
    if controller.get("approved") is not True:
        errors.append("controller_not_approved")
    if controller.get("collection_enabled") is not True:
        errors.append("controller_collection_disabled")
    if controller.get("nf06_reference_eligible") is not True:
        errors.append("controller_not_nf06_eligible")

    if collection_frame.get("frame_status") != "APPROVED_FOR_PROD":
        errors.append("collection_frame_not_approved")
    if collection_frame.get("collection_enabled") is not True:
        errors.append("collection_frame_collection_disabled")
    approval = collection_frame.get("approval") or {}
    if approval.get("approved") is not True or approval.get("approved_for_prod") is not True:
        errors.append("collection_frame_approval_false")
    nf06_handoff = collection_frame.get("nf06_handoff") or {}
    if nf06_handoff.get("eligible_now") is not True:
        errors.append("collection_frame_not_nf06_eligible")

    if dpia_screening.get("approved") is not True:
        errors.append("dpia_screening_not_approved")
    if dpia_screening.get("collection_enabled") is not True:
        errors.append("dpia_screening_collection_disabled")
    if dpia_screening.get("screening_conclusion") not in {
        "DPIA_NOT_REQUIRED_APPROVED",
        "DPIA_REQUIRED_COMPLETED_AND_APPROVED",
    }:
        errors.append("dpia_screening_conclusion_unresolved")
    mandatory = dpia_screening.get("mandatory_before_prod") or {}
    if mandatory.get("controller_determination_approved") is not True:
        errors.append("dpia_controller_determination_not_approved")
    if not isinstance(mandatory.get("privacy_contact_or_dpo_review_reference"), str) or not mandatory.get("privacy_contact_or_dpo_review_reference", "").strip():
        errors.append("dpia_privacy_review_reference_missing")
    if not isinstance(mandatory.get("final_large_scale_assessment"), str) or not mandatory.get("final_large_scale_assessment", "").strip():
        errors.append("dpia_large_scale_assessment_missing")
    if mandatory.get("employee_power_imbalance_safeguards_approved") is not True:
        errors.append("dpia_employee_safeguards_not_approved")
    if mandatory.get("anspdcp_decision_174_2018_final_check") is not True:
        errors.append("dpia_anspdcp_check_not_approved")
    if not isinstance(mandatory.get("final_dpia_decision"), str) or not mandatory.get("final_dpia_decision", "").strip():
        errors.append("dpia_final_decision_missing")
    if mandatory.get("if_residual_high_risk_prior_consultation_assessed") is not True:
        errors.append("dpia_prior_consultation_assessment_missing")
    if dpia_screening.get("screening_conclusion") == "DPIA_REQUIRED_COMPLETED_AND_APPROVED":
        completed_ref = mandatory.get("if_dpia_required_completed_dpia_reference")
        if not isinstance(completed_ref, str) or not completed_ref.strip():
            errors.append("completed_dpia_reference_missing")

    evidence = manifest.get("required_external_or_operational_evidence")
    if not isinstance(evidence, dict):
        errors.append("external_evidence_map_missing")
    else:
        missing = REQUIRED_EXTERNAL_KEYS - set(evidence)
        unexpected = set(evidence) - REQUIRED_EXTERNAL_KEYS
        if missing:
            errors.append("external_evidence_keys_missing:" + ",".join(sorted(missing)))
        if unexpected:
            errors.append("external_evidence_keys_unexpected:" + ",".join(sorted(unexpected)))
        for key in sorted(REQUIRED_EXTERNAL_KEYS):
            if key not in evidence or not _valid_external_reference(evidence[key]):
                errors.append(f"external_evidence_not_frozen:{key}")
            elif not _valid_frozen_local_binding(evidence[key]):
                errors.append(f"external_evidence_frozen_hash_mismatch:{key}")

    if manifest.get("real_collection_authorized") is not True:
        errors.append("real_collection_not_authorized")
    return errors


def evaluate_repository_activation(
    *,
    contract_path: Path = CONTRACT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    controller_path: Path = CONTROLLER_PATH,
    collection_frame_path: Path = COLLECTION_FRAME_PATH,
    dpia_screening_path: Path = DPIA_SCREENING_PATH,
) -> tuple[bool, list[str]]:
    contract = _load(contract_path)
    manifest = _load(manifest_path)
    controller = _load(controller_path)
    collection_frame = _load(collection_frame_path)
    dpia_screening = _load(dpia_screening_path)
    errors = activation_errors(
        contract=contract,
        manifest=manifest,
        controller=controller,
        collection_frame=collection_frame,
        dpia_screening=dpia_screening,
    )
    return not errors, errors


def assert_repository_fail_closed_or_approved() -> None:
    contract = _load(CONTRACT_PATH)
    ready, errors = evaluate_repository_activation()
    if contract.get("production_enabled") is True and not ready:
        raise ProductionActivationError(
            "AI4WORK production_enabled=true while PROD activation gate is not satisfied: "
            + "; ".join(errors)
        )
    if contract.get("production_enabled") is not True and ready:
        raise ProductionActivationError("inconsistent activation state: gate ready while production is disabled")


def main() -> int:
    try:
        assert_repository_fail_closed_or_approved()
    except (OSError, json.JSONDecodeError, ProductionActivationError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    ready, errors = evaluate_repository_activation()
    if ready:
        print("PASS: AI4WORK PROD activation gate is fully approved")
    else:
        print("PASS: AI4WORK remains fail-closed; unresolved gates: " + ", ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
