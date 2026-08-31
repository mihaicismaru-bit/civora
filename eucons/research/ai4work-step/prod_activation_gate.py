from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from explicit_user_approval_control import explicit_user_approval_errors

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
CONTROLLER_PATH = HERE / "CONTROLLER_DETERMINATION_DRAFT.json"
COLLECTION_FRAME_PATH = HERE / "COLLECTION_FRAME_DRAFT.json"
DPIA_SCREENING_PATH = HERE / "GDPR_DPIA_SCREENING_DRAFT.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
APPROVED_EXTERNAL_STATUSES = {"APPROVED", "PASS", "FROZEN"}
SEMANTIC_ATTESTATION_STATUSES = {"APPROVED", "PASS"}
NON_EVIDENCE_MARKERS = ("TEST_TWIN", "NON_EVIDENCE", "SYNTHETIC")
REQUIRED_EXTERNAL_KEYS = {
    "privacy_notice",
    "lawful_basis_or_lia",
    "processor_chain",
    "provider_account_role_reconciliation",
    "live_hosting_service_mapping",
    "live_public_privacy_surface_reconciliation",
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


def _resolve_local_reference(reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.strip():
        return None
    reference = reference.strip()
    if "://" in reference or reference.startswith(("gdrive:", "gmail:", "http:", "https:")):
        return None
    raw = Path(reference)
    if raw.is_absolute():
        return None
    candidate = (HERE / raw).resolve()
    try:
        candidate.relative_to(HERE.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _valid_promoted_local_binding(*, key: str, value: dict[str, Any], research_id: str) -> bool:
    """Activation itself must verify immutable and semantically relevant evidence.

    A separate CI evidence-binding workflow is useful defence in depth, but PROD activation
    must not depend on that workflow having run. Every promoted external/operational gate is
    therefore re-checked here. FROZEN documentary/provider context needs an exact local hash;
    PASS/APPROVED additionally needs a JSON attestation bound to this research run and exact
    evidence key, and TEST TWIN / NON-EVIDENCE / SYNTHETIC artifacts are never promotable.
    """
    candidate = _resolve_local_reference(value.get("reference"))
    digest = value.get("sha256")
    if candidate is None or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        return False
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
        return False

    if value.get("status") not in SEMANTIC_ATTESTATION_STATUSES:
        return True
    if candidate.suffix.lower() != ".json":
        return False
    try:
        artifact = _load(candidate)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(artifact, dict):
        return False
    if artifact.get("research_id") != research_id:
        return False
    if artifact.get("evidence_binding_key") != key:
        return False
    if artifact.get("synthetic") is True:
        return False
    for field in ("evidence_class", "mode", "artifact_class"):
        marker_value = artifact.get(field)
        if isinstance(marker_value, str):
            normalized = marker_value.upper()
            if any(marker in normalized for marker in NON_EVIDENCE_MARKERS):
                return False
    return True


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
    research_id = manifest.get("research_id") if isinstance(manifest.get("research_id"), str) else ""

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
    errors.extend(explicit_user_approval_errors(manifest=manifest, research_id=research_id))
    if manifest.get("merge_authorized") is not False:
        errors.append("merge_authority_must_remain_false_for_collection_activation")
    if manifest.get("deploy_authorized") is not False:
        errors.append("deploy_authority_must_remain_false_for_collection_activation")
    if manifest.get("canonicalization_authorized") is not False:
        errors.append("canonicalization_authority_must_remain_false_for_collection_activation")

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
            elif not _valid_promoted_local_binding(
                key=key,
                value=evidence[key],
                research_id=research_id,
            ):
                errors.append(f"external_evidence_binding_invalid:{key}")

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
