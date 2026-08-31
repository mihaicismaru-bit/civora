from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SNAPSHOT_PATH = HERE / "ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json"
FRAME_PATH = HERE / "COLLECTION_FRAME_DRAFT.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
NF06_CONTRACT_PATH = HERE / "NF06_PREINGEST_CONTRACT.json"

PROMOTED_STATUSES = {"APPROVED", "PASS"}
NON_EVIDENCE_MARKERS = ("TEST_TWIN", "NON_EVIDENCE", "SYNTHETIC")


class PrivacyNoticeNF06BindingError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_sha256(path: Path = SNAPSHOT_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding_errors(
    *,
    snapshot: dict[str, Any],
    collection_frame: dict[str, Any],
    manifest: dict[str, Any],
    nf06_contract: dict[str, Any],
    snapshot_sha256: str,
) -> list[str]:
    errors: list[str] = []
    research_ids = {
        snapshot.get("research_id"),
        collection_frame.get("research_id"),
        manifest.get("research_id"),
        nf06_contract.get("research_id"),
    }
    if len(research_ids) != 1 or None in research_ids:
        errors.append("research_id_mismatch")

    if snapshot.get("evidence_binding_key") != "privacy_notice":
        errors.append("snapshot_binding_key_invalid")
    if snapshot.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        errors.append("snapshot_evidence_class_invalid")
    if snapshot.get("synthetic") is not False:
        errors.append("snapshot_must_be_non_synthetic_control_artifact")
    if not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64:
        errors.append("snapshot_sha256_invalid")

    prod_requirements = nf06_contract.get("prod_requirements") or []
    if "privacy notice version is present" not in prod_requirements:
        errors.append("nf06_contract_privacy_notice_requirement_missing")
    prod_fields = nf06_contract.get("prod_only_required_fields") or []
    if "privacy_notice_version" not in prod_fields:
        errors.append("nf06_contract_privacy_notice_field_missing")

    external = manifest.get("required_external_or_operational_evidence") or {}
    binding = external.get("privacy_notice")
    if not isinstance(binding, dict):
        errors.append("manifest_privacy_notice_binding_missing")
        binding = {}

    frame_approval = collection_frame.get("approval") or {}
    frame_version = frame_approval.get("privacy_notice_version")
    promoted = binding.get("status") in PROMOTED_STATUSES
    activation_requested = any(
        (
            manifest.get("approved_for_prod") is True,
            manifest.get("collection_enabled") is True,
            manifest.get("real_collection_authorized") is True,
            collection_frame.get("frame_status") == "APPROVED_FOR_PROD",
            collection_frame.get("collection_enabled") is True,
        )
    )

    if promoted:
        if binding.get("reference") != SNAPSHOT_PATH.name:
            errors.append("privacy_notice_reference_not_exact_snapshot")
        if binding.get("sha256") != snapshot_sha256:
            errors.append("privacy_notice_sha256_mismatch")
        if snapshot.get("status") != "APPROVED_FOR_PROD":
            errors.append("privacy_notice_snapshot_not_approved_for_prod")
        if snapshot.get("approved") is not True:
            errors.append("privacy_notice_snapshot_approval_false")
        approval = snapshot.get("approval") or {}
        if approval.get("controller_approved") is not True:
            errors.append("privacy_notice_controller_approval_missing")
        expected_version = snapshot.get("schema_version")
        if not isinstance(expected_version, str) or not expected_version.strip():
            errors.append("privacy_notice_snapshot_version_missing")
        elif frame_version != expected_version:
            errors.append("collection_frame_privacy_notice_version_mismatch")
        for field in ("evidence_class", "artifact_class", "mode"):
            value = snapshot.get(field)
            if isinstance(value, str):
                upper = value.upper()
                if any(marker in upper for marker in NON_EVIDENCE_MARKERS):
                    errors.append("privacy_notice_promoted_from_non_evidence_artifact")
    else:
        # Fail-closed draft state is valid only while collection remains disabled.
        if activation_requested:
            errors.append("privacy_notice_not_promoted_before_prod_activation")
        if binding.get("status") != "OPEN":
            errors.append("unpromoted_privacy_notice_status_must_be_open")
        if binding.get("reference") not in (None, ""):
            errors.append("open_privacy_notice_reference_must_be_empty")
        if binding.get("sha256") not in (None, ""):
            errors.append("open_privacy_notice_sha256_must_be_empty")
        if frame_version not in (None, ""):
            errors.append("draft_collection_frame_privacy_notice_version_must_be_empty")

    return errors


def evaluate_repository_binding() -> tuple[bool, list[str], bool]:
    snapshot = _load(SNAPSHOT_PATH)
    frame = _load(FRAME_PATH)
    manifest = _load(MANIFEST_PATH)
    nf06_contract = _load(NF06_CONTRACT_PATH)
    errors = binding_errors(
        snapshot=snapshot,
        collection_frame=frame,
        manifest=manifest,
        nf06_contract=nf06_contract,
        snapshot_sha256=_snapshot_sha256(),
    )
    promoted = (
        (manifest.get("required_external_or_operational_evidence") or {})
        .get("privacy_notice", {})
        .get("status")
        in PROMOTED_STATUSES
    )
    return not errors, errors, promoted


def assert_repository_binding() -> None:
    valid, errors, _promoted = evaluate_repository_binding()
    if not valid:
        raise PrivacyNoticeNF06BindingError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_binding()
    except (OSError, json.JSONDecodeError, PrivacyNoticeNF06BindingError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    _valid, _errors, promoted = evaluate_repository_binding()
    if promoted:
        print("PASS: Article 13 snapshot is SHA-256-bound to the approved PROD collection frame/NF06 boundary")
    else:
        print("PASS: Article 13 -> NF06 binding remains fail-closed; no privacy notice is promoted for PROD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
