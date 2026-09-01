from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
CONTROLLER_PATH = HERE / "CONTROLLER_DETERMINATION_DRAFT.json"
LIA_PATH = HERE / "GDPR_LIA_DRAFT.json"

EXPECTED_SCHEMA = "eucons.ai4work_gdpr_lia.v0.6"
EXPECTED_EVIDENCE_KEY = "lawful_basis_or_lia"
EXPECTED_BASIS_CODE = "GDPR_ARTICLE_6_1_F_LEGITIMATE_INTERESTS"
PLACEHOLDER_PREFIXES = ("TO_BE_", "OPEN_", "UNRESOLVED_", "DE_", "TBD", "TODO")


class LawfulBasisLiaError(ValueError):
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


def lawful_basis_lia_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    controller: dict[str, Any],
    lia: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    research_ids = {
        contract.get("research_id"),
        manifest.get("research_id"),
        controller.get("research_id"),
        lia.get("research_id"),
    }
    if len(research_ids) != 1 or None in research_ids:
        errors.append("research_id_mismatch")

    if lia.get("schema_version") != EXPECTED_SCHEMA:
        errors.append("lia_schema_invalid")
    if lia.get("evidence_binding_key") != EXPECTED_EVIDENCE_KEY:
        errors.append("lia_evidence_binding_key_invalid")
    if lia.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        errors.append("lia_evidence_class_invalid")
    if lia.get("synthetic") is not False:
        errors.append("lia_must_not_be_synthetic")

    controller_identity = controller.get("controller") or {}
    lia_controller = lia.get("controller") or {}
    for key in ("legal_name", "cui"):
        if not _bound(lia_controller.get(key)) or lia_controller.get(key) != controller_identity.get(key):
            errors.append(f"lia_controller_identity_mismatch:{key}")

    basis = str(lia.get("candidate_legal_basis") or "").lower()
    if "article 6(1)(f)" not in basis or "legitimate interest" not in basis:
        errors.append("lia_candidate_basis_not_article_6_1_f")

    purpose = lia.get("purpose_test") or {}
    for key in ("legitimate", "specific", "present_and_non_speculative"):
        if purpose.get(key) is not True:
            errors.append(f"lia_purpose_test_not_satisfied:{key}")
    if purpose.get("commercial_marketing_or_lead_generation") is not False:
        errors.append("lia_commercial_marketing_not_forbidden")
    if purpose.get("controller_attribution") != controller_identity.get("legal_name"):
        errors.append("lia_purpose_controller_attribution_mismatch")

    necessity = lia.get("necessity_test") or {}
    less_intrusive = " ".join(str(item).lower() for item in (necessity.get("less_intrusive_design") or []))
    required_design_markers = {
        "no_direct_identifiers": "no names, contact details, cnp",
        "no_free_text": "no analytical free-text",
        "no_tracking": "no login, files, cookies, fingerprinting or cross-site tracking",
        "no_crm": "no crm or commercial analytics integration",
        "no_special_category": "no special-category data",
    }
    for key, marker in required_design_markers.items():
        if marker not in less_intrusive:
            errors.append(f"lia_minimisation_safeguard_missing:{key}")

    balancing = lia.get("balancing_test") or {}
    safeguards = " ".join(str(item).lower() for item in (balancing.get("safeguards") or []))
    for key, marker in {
        "right_to_object": "right-to-object",
        "research_store": "research-only",
        "no_automated_decisions": "no automated decisions",
        "no_external_llm_raw": "no raw respondent-level response use with external llm",
    }.items():
        if marker not in safeguards:
            errors.append(f"lia_balancing_safeguard_missing:{key}")

    if lia.get("merge_authorized") is not False:
        errors.append("lia_merge_authority_escalated")
    if lia.get("deploy_authorized") is not False:
        errors.append("lia_deploy_authority_escalated")
    if lia.get("real_collection_authorized") is not False:
        errors.append("lia_must_not_independently_authorize_collection")

    activation_claimed = any(
        (
            contract.get("production_enabled") is True,
            manifest.get("approved_for_prod") is True,
            manifest.get("collection_enabled") is True,
            manifest.get("real_collection_authorized") is True,
        )
    )
    if activation_claimed:
        if lia.get("status") != "APPROVED_FOR_PROD":
            errors.append("lia_not_approved_for_prod")
        if lia.get("prod_eligible") is not True:
            errors.append("lia_not_prod_eligible")

        signoff = lia.get("controller_signoff_fields") or {}
        if signoff.get("approved") is not True:
            errors.append("lia_controller_signoff_missing")
        if signoff.get("legal_entity_name") != controller_identity.get("legal_name"):
            errors.append("lia_signoff_legal_entity_mismatch")
        if not _bound(signoff.get("approver_name_or_role")):
            errors.append("lia_approver_missing")
        if not _non_future_date(signoff.get("approval_date")):
            errors.append("lia_approval_date_missing_or_invalid")
        if not _bound(signoff.get("privacy_contact")):
            errors.append("lia_privacy_contact_missing")

        approval = lia.get("prod_approval") or {}
        if approval.get("state") != "APPROVED_FOR_PROD":
            errors.append("lia_prod_approval_state_invalid")
        if approval.get("lawful_basis_code") != EXPECTED_BASIS_CODE:
            errors.append("lia_prod_basis_code_invalid")
        for key in (
            "purpose_test_approved",
            "necessity_test_approved",
            "balancing_test_approved",
            "right_to_object_operational",
            "article13_basis_disclosure_confirmed",
            "employee_no_disadvantage_safeguard_approved",
            "processor_chain_review_complete",
            "logging_linkability_review_complete",
            "retention_executable_confirmed",
        ):
            if approval.get(key) is not True:
                errors.append(f"lia_prod_approval_not_satisfied:{key}")
        if not _bound(approval.get("privacy_contact")):
            errors.append("lia_prod_privacy_contact_missing")
        if not _bound(approval.get("approver_name_or_role")):
            errors.append("lia_prod_approver_missing")
        if not _non_future_date(approval.get("approved_at")):
            errors.append("lia_prod_approved_at_missing_or_invalid")
        if approval.get("privacy_contact") != signoff.get("privacy_contact"):
            errors.append("lia_privacy_contact_binding_mismatch")
        if approval.get("approver_name_or_role") != signoff.get("approver_name_or_role"):
            errors.append("lia_approver_binding_mismatch")
        if approval.get("approved_at") != signoff.get("approval_date"):
            errors.append("lia_approval_date_binding_mismatch")

        # A PROD-approved LIA must no longer describe its basis/outcome as merely provisional.
        if "candidate only" in basis or "signoff is still required" in basis:
            errors.append("lia_candidate_wording_not_finalized")
        provisional = str(balancing.get("provisional_outcome") or "").upper()
        if "UNAPPROVED" in provisional or "REMAINS_UNAPPROVED" in provisional:
            errors.append("lia_balancing_outcome_still_provisional")

    return errors


def evaluate_repository_lia(
    *,
    contract_path: Path = CONTRACT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    controller_path: Path = CONTROLLER_PATH,
    lia_path: Path = LIA_PATH,
) -> tuple[bool, list[str]]:
    contract = _load(contract_path)
    manifest = _load(manifest_path)
    controller = _load(controller_path)
    lia = _load(lia_path)
    errors = lawful_basis_lia_errors(contract=contract, manifest=manifest, controller=controller, lia=lia)
    return not errors, errors


def assert_repository_lia_safe() -> None:
    ready, errors = evaluate_repository_lia()
    if not ready:
        raise LawfulBasisLiaError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_lia_safe()
    except (OSError, json.JSONDecodeError, LawfulBasisLiaError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print("PASS: AI4WORK lawful-basis/LIA control is structurally valid and remains fail-closed until explicit controller approval and live privacy/data-handling gates are complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
