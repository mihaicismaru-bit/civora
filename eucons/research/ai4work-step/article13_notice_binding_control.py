from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
SCHEMA_PATH = HERE / "forms_definition.json"
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
RAW_PLACEHOLDER_PREFIXES = (
    "TO_BE_",
    "OPEN_",
    "UNRESOLVED_",
    "DRAFT_",
)
VISIBLE_PLACEHOLDER_PREFIXES = (
    "DE APROBAT ",
    "DE COMPLETAT ",
    "DE STABILIT ",
)


class Article13BindingError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_unfrozen(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text.startswith(("TO_BE_", "OPEN_", "UNRESOLVED_"))


def _visible_value(pre_notice: dict[str, Any], key: str, fallback: str = "DE APROBAT ÎNAINTE DE ACTIVAREA COLECTĂRII") -> str:
    value = pre_notice.get(key)
    return fallback if _raw_unfrozen(value) else str(value)


def rendered_surface(contract: dict[str, Any], schema: dict[str, Any]) -> dict[str, str]:
    notice = contract.get("pre_form_notice") or {}
    common_notice = schema.get("common_notice") or {}
    return {
        "title": str(common_notice.get("title") or ""),
        "operator_legal_name": _visible_value(notice, "operator_legal_name", "DE STABILIT ÎNAINTE DE ACTIVAREA COLECTĂRII"),
        "operator_contact_details": _visible_value(notice, "operator_contact_details"),
        "privacy_contact": _visible_value(notice, "privacy_contact", "DE COMPLETAT ÎNAINTE DE ACTIVAREA COLECTĂRII"),
        "purpose_summary": _visible_value(notice, "purpose_summary"),
        "legal_basis": _visible_value(notice, "legal_basis"),
        "legitimate_interest_summary": _visible_value(notice, "legitimate_interest_summary"),
        "recipients_summary": _visible_value(notice, "recipients_summary"),
        "international_transfer_summary": _visible_value(notice, "international_transfer_summary"),
        "retention_summary": _visible_value(notice, "retention_summary"),
        "rights_summary": _visible_value(notice, "rights_summary"),
        "complaint_summary": _visible_value(notice, "complaint_summary"),
        "provision_consequence_summary": _visible_value(notice, "provision_consequence_summary"),
        "automated_decision_summary": _visible_value(notice, "automated_decision_summary"),
    }


def _placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    return (
        not text
        or text.startswith(RAW_PLACEHOLDER_PREFIXES)
        or text.startswith(VISIBLE_PLACEHOLDER_PREFIXES)
        or "[PRIVACY_CONTACT_REQUIRED" in text
    )


def binding_errors(
    *,
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    require_approved: bool,
    schema: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if schema is None:
        schema = _load(SCHEMA_PATH)
    if contract.get("research_id") != snapshot.get("research_id"):
        errors.append("research_id_mismatch")
    if snapshot.get("evidence_binding_key") != "privacy_notice":
        errors.append("evidence_binding_key_invalid")
    if snapshot.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        errors.append("evidence_class_invalid")
    if snapshot.get("synthetic") is not False:
        errors.append("snapshot_must_be_non_synthetic_control_artifact")

    surface = snapshot.get("surface_fields")
    if not isinstance(contract.get("pre_form_notice"), dict):
        errors.append("contract_pre_form_notice_missing")
    if not isinstance(schema.get("common_notice"), dict):
        errors.append("schema_common_notice_missing")
    if not isinstance(surface, dict):
        errors.append("snapshot_surface_fields_missing")
        surface = {}

    missing = REQUIRED_SURFACE_FIELDS - set(surface)
    unexpected = set(surface) - REQUIRED_SURFACE_FIELDS
    if missing:
        errors.append("surface_fields_missing:" + ",".join(sorted(missing)))
    if unexpected:
        errors.append("surface_fields_unexpected:" + ",".join(sorted(unexpected)))

    expected = rendered_surface(contract, schema)
    for key in sorted(REQUIRED_SURFACE_FIELDS):
        if key in surface and surface.get(key) != expected.get(key):
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
    schema_path: Path = SCHEMA_PATH,
    snapshot_path: Path = SNAPSHOT_PATH,
) -> tuple[bool, list[str]]:
    contract = _load(contract_path)
    schema = _load(schema_path)
    snapshot = _load(snapshot_path)
    errors = binding_errors(
        contract=contract,
        snapshot=snapshot,
        require_approved=contract.get("production_enabled") is True,
        schema=schema,
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
    print("PASS: Article 13 visible surface is frozen against renderer inputs; PROD approval remains separately fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
