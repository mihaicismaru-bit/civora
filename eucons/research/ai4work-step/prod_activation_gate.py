from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
CONTROLLER_PATH = HERE / "CONTROLLER_DETERMINATION_DRAFT.json"
COLLECTION_FRAME_PATH = HERE / "COLLECTION_FRAME_DRAFT.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
APPROVED_EXTERNAL_STATUSES = {"APPROVED", "PASS", "FROZEN"}
REQUIRED_EXTERNAL_KEYS = {
    "privacy_notice",
    "lawful_basis_or_lia",
    "processor_chain",
    "provider_annex_4_5",
    "server_logging_profile",
    "retention_and_deletion",
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


def activation_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    controller: dict[str, Any],
    collection_frame: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    research_ids = {
        contract.get("research_id"),
        manifest.get("research_id"),
        controller.get("research_id"),
        collection_frame.get("research_id"),
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

    if manifest.get("real_collection_authorized") is not True:
        errors.append("real_collection_not_authorized")
    return errors


def evaluate_repository_activation(
    *,
    contract_path: Path = CONTRACT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    controller_path: Path = CONTROLLER_PATH,
    collection_frame_path: Path = COLLECTION_FRAME_PATH,
) -> tuple[bool, list[str]]:
    contract = _load(contract_path)
    manifest = _load(manifest_path)
    controller = _load(controller_path)
    collection_frame = _load(collection_frame_path)
    errors = activation_errors(
        contract=contract,
        manifest=manifest,
        controller=controller,
        collection_frame=collection_frame,
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
