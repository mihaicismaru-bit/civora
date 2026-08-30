from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
SNAPSHOT_PATH = HERE / "ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json"

REQUIRED_SURFACE_FIELDS = {
    "title",
    "operator_legal_name",
    "operator_contact_details",
    "privacy_contact",
    "purpose_summary",
    "legal_basis",
    "legitimate_interest_summary",
    "recipients_summary",
    "international_transfer_summary",
    "retention_summary",
    "rights_summary",
    "complaint_summary",
    "provision_consequence_summary",
    "automated_decision_summary",
}
PLACEHOLDER_PREFIXES = (
    "TO_BE_",
    "OPEN_",
    "UNRESOLVED_",
    "DRAFT_",
)


class Article13BindingError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text.startswith(PLACEHOLDER_PREFIXES) or "[PRIVACY_CONTACT_REQUIRED" in text


def binding_errors(
    *,
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    require_approved: bool,
) -> list[str]:
    errors: list[str] = []
    if contract.get("research_id") != snapshot.get("research_id"):
        errors.append("research_id_mismatch")
    if snapshot.get("evidence_binding_key") != "privacy_notice":
        errors.append("evidence_binding_key_invalid")
    if snapshot.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        errors.append("evidence_class_invalid")
    if snapshot.get("synthetic") is not False:
        errors.append("snapshot_must_be_non_synthetic_control_artifact")

    notice = contract.get("pre_form_notice")
    surface = snapshot.get("surface_fields")
    if not isinstance(notice, dict):
        errors.append("contract_pre_form_notice_missing")
        notice = {}
    if not isinstance(surface, dict):
        errors.append("snapshot_surface_fields_missing")
        surface = {}

    missing = REQUIRED_SURFACE_FIELDS - set(surface)
    unexpected = set(surface) - REQUIRED_SURFACE_FIELDS
    if missing:
        errors.append("surface_fields_missing:" + ",".join(sorted(missing)))
    if unexpected:
        errors.append("surface_fields_unexpected:" + ",".join(sorted(unexpected)))
    for key in sorted(REQUIRED_SURFACE_FIELDS):
        if key in surface and surface.get(key) != notice.get(key):
            errors.append(f"surface_drift:{key}")

    if require_approved:
        if snapshot.get("status") != "APPROVED_FOR_PROD":
            errors.append("snapshot_not_approved_for_prod")
        if snapshot.get("approved") is not True:
            errors.append("snapshot_approval_false")
        if snapshot.get("collection_enabled") is not True:
            errors.append("snapshot_collection_disabled")
        approval = snapshot.get("approval") or {}
        if approval.get("controller_approved") is not True:
            errors.append("controller_approval_missing")
        for key in ("approved_by", "approved_at", "approval_reference"):
            if _placeholder(approval.get(key)):
                errors.append(f"approval_{key}_missing")
        for key in ("operator_contact_details", "privacy_contact", "legal_basis"):
            if _placeholder(surface.get(key)):
                errors.append(f"approved_surface_placeholder:{key}")

    return errors


def evaluate_repository_notice_binding(
    *,
    contract_path: Path = CONTRACT_PATH,
    snapshot_path: Path = SNAPSHOT_PATH,
) -> tuple[bool, list[str]]:
    contract = _load(contract_path)
    snapshot = _load(snapshot_path)
    errors = binding_errors(
        contract=contract,
        snapshot=snapshot,
        require_approved=contract.get("production_enabled") is True,
    )
    return not errors, errors


def assert_repository_notice_binding() -> None:
    ready, errors = evaluate_repository_notice_binding()
    if not ready:
        raise Article13BindingError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_notice_binding()
    except (OSError, json.JSONDecodeError, Article13BindingError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print("PASS: Article 13 rendered surface is bound to the canonical draft snapshot; PROD approval remains separately fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
