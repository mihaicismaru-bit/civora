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

EXPECTED_SCHEMA = "eucons.ai4work_controller_determination.v0.3"
EXPECTED_RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
EXPECTED_CONTROLLER = {
    "legal_name": "EUROCONSULT SRL",
    "cui": "14250864",
    "role": "GDPR_CONTROLLER",
    "site": "eucons.ro",
}
EXPECTED_TEST_TWIN_POLICY = "TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_PREFIXES = ("TO_BE_", "OPEN_", "UNRESOLVED_", "TBD", "TODO", "DE_COMPLETAT")


class ControllerDeterminationControlError(ValueError):
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


def _matrix_by_ref(controller: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = controller.get("decision_matrix")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("entity_reference"), str):
            result[row["entity_reference"]] = row
    return result


def controller_determination_errors(
    *,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    controller: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    research_ids = {
        contract.get("research_id"),
        manifest.get("research_id"),
        controller.get("research_id"),
    }
    if len(research_ids) != 1 or EXPECTED_RESEARCH_ID not in research_ids:
        errors.append("controller_research_id_mismatch")

    if controller.get("schema_version") != EXPECTED_SCHEMA:
        errors.append("controller_schema_invalid")

    identity = controller.get("controller")
    if not isinstance(identity, dict):
        errors.append("controller_identity_missing")
        identity = {}
    for key, expected in EXPECTED_CONTROLLER.items():
        if identity.get(key) != expected:
            errors.append(f"controller_identity_mismatch:{key}")
    if identity.get("site_ownership_status") != "FIRST_PARTY_CONFIRMED":
        errors.append("controller_site_ownership_not_first_party_confirmed")
    if not _bound(identity.get("determination_reference")):
        errors.append("controller_determination_reference_missing")

    source = controller.get("controller_source")
    if not isinstance(source, dict):
        errors.append("controller_source_missing")
        source = {}
    if source.get("type") != "AUTHENTICATED_FIRST_PARTY_DECLARATION":
        errors.append("controller_source_not_authenticated_first_party")
    source_boundary = str(source.get("boundary", "")).lower()
    for token in ("does not by itself prove", "claus web", "active cpanel configuration", "log retention", "backup execution"):
        if token not in source_boundary:
            errors.append(f"controller_source_boundary_missing:{token.replace(' ', '_')}")

    if controller.get("approved") is not True:
        errors.append("controller_identity_determination_not_approved")
    if controller.get("merge_authorized") is not False:
        errors.append("controller_merge_authority_escalated")
    if controller.get("deploy_authorized") is not False:
        errors.append("controller_deploy_authority_escalated")

    non_determinative = set(controller.get("non_determinative_facts") or [])
    for required in (
        "website_branding_alone",
        "project_leader_status_alone",
        "domain_ownership_alone",
        "hosting_billing_alone",
        "technical_implementation_alone",
    ):
        if required not in non_determinative:
            errors.append(f"controller_non_determinative_fact_missing:{required}")

    matrix = _matrix_by_ref(controller)
    required_refs = {
        "EUROCONSULT_SRL_CONTROLLER",
        "MYSMIS_PROJECT_LEADER_CONTROLLED_REFERENCE",
        "HOSTING_ACCOUNT_HISTORY_CONTROLLED_REFERENCE",
        "CLAUS_WEB_SRL",
    }
    missing_refs = required_refs - set(matrix)
    if missing_refs:
        errors.append("controller_decision_matrix_missing:" + ",".join(sorted(missing_refs)))

    euroconsult = matrix.get("EUROCONSULT_SRL_CONTROLLER", {})
    if euroconsult.get("observed_legal_identity") != EXPECTED_CONTROLLER["legal_name"]:
        errors.append("controller_matrix_euroconsult_identity_mismatch")
    if euroconsult.get("purpose_decision_authority") is not True:
        errors.append("controller_matrix_purpose_authority_missing")
    if euroconsult.get("essential_means_authority") is not True:
        errors.append("controller_matrix_essential_means_authority_missing")
    if euroconsult.get("proposed_role") != "GDPR_CONTROLLER":
        errors.append("controller_matrix_role_invalid")

    project_leader = matrix.get("MYSMIS_PROJECT_LEADER_CONTROLLED_REFERENCE", {})
    if project_leader.get("purpose_decision_authority") is not False:
        errors.append("project_leader_silently_promoted_to_controller")
    if project_leader.get("essential_means_authority") is not False:
        errors.append("project_leader_essential_means_authority_invalid")
    if project_leader.get("proposed_role") != "PROJECT_LEADER_NOT_CONTROLLER_FOR_THIS_RESEARCH":
        errors.append("project_leader_role_boundary_invalid")

    hosting_history = matrix.get("HOSTING_ACCOUNT_HISTORY_CONTROLLED_REFERENCE", {})
    if hosting_history.get("purpose_decision_authority") is not False:
        errors.append("hosting_account_history_promoted_to_controller")
    if hosting_history.get("proposed_role") != "TECHNICAL_ACCOUNT_ROLE_PENDING_BINDING_NOT_CONTROLLER":
        errors.append("hosting_account_history_role_boundary_invalid")

    provider = matrix.get("CLAUS_WEB_SRL", {})
    if provider.get("purpose_decision_authority") is not False:
        errors.append("hosting_provider_promoted_to_controller")
    if provider.get("processor_instruction_authority") is not False:
        errors.append("hosting_provider_instruction_authority_invalid")
    if provider.get("proposed_role") != "PROCESSOR_OR_SUBPROCESSOR_CANDIDATE":
        errors.append("hosting_provider_role_boundary_invalid")

    known = controller.get("known_evidence_boundaries")
    if not isinstance(known, dict):
        errors.append("controller_known_evidence_boundaries_missing")
        known = {}
    history_boundary = str(known.get("hosting_account_history", "")).lower()
    if "mixed" not in history_boundary or "must not be collapsed" not in history_boundary:
        errors.append("hosting_account_history_collapse_guard_missing")

    remaining = "\n".join(str(item).lower() for item in controller.get("remaining_decision_facts", []))
    for token in ("privacy contact", "lawful basis/lia", "article 13", "dpia", "raw access", "research-only", "deletion/backup", "test twin"):
        if token not in remaining:
            errors.append(f"controller_remaining_fact_missing:{token.replace(' ', '_')}")

    activation_claimed = any(
        (
            contract.get("production_enabled") is True,
            manifest.get("approved_for_prod") is True,
            manifest.get("collection_enabled") is True,
            manifest.get("real_collection_authorized") is True,
            controller.get("collection_enabled") is True,
            controller.get("nf06_reference_eligible") is True,
            controller.get("real_collection_authorized") is True,
        )
    )

    if not activation_claimed:
        if controller.get("collection_enabled") is not False:
            errors.append("controller_collection_enabled_without_prod_activation")
        if controller.get("nf06_reference_eligible") is not False:
            errors.append("controller_nf06_eligible_without_prod_activation")
        if controller.get("real_collection_authorized") is not False:
            errors.append("controller_real_collection_authorized_without_prod_activation")
    else:
        if controller.get("status") != "APPROVED_FOR_PROD":
            errors.append("controller_prod_status_not_approved")
        if controller.get("collection_enabled") is not True:
            errors.append("controller_prod_collection_not_enabled")
        if controller.get("nf06_reference_eligible") is not True:
            errors.append("controller_prod_nf06_not_eligible")
        if controller.get("real_collection_authorized") is not True:
            errors.append("controller_prod_real_collection_not_authorized")
        if controller.get("synthetic") is not False:
            errors.append("controller_prod_artifact_must_be_real_non_synthetic")
        if not _bound(controller.get("privacy_contact")):
            errors.append("controller_prod_privacy_contact_missing")

        prod_approval = controller.get("prod_approval")
        if not isinstance(prod_approval, dict):
            errors.append("controller_prod_approval_missing")
            prod_approval = {}
        if prod_approval.get("approved") is not True:
            errors.append("controller_prod_approval_false")
        if prod_approval.get("legal_entity_name") != EXPECTED_CONTROLLER["legal_name"]:
            errors.append("controller_prod_approval_entity_mismatch")
        if not _bound(prod_approval.get("approver_name_or_role")):
            errors.append("controller_prod_approver_missing")
        if not _non_future_date(prod_approval.get("approved_at")):
            errors.append("controller_prod_approval_date_invalid")
        if not _bound(prod_approval.get("approval_reference")):
            errors.append("controller_prod_approval_reference_missing")
        for digest_key in ("method_lock_sha256", "frame_lock_sha256"):
            digest = prod_approval.get(digest_key)
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                errors.append(f"controller_prod_approval_digest_invalid:{digest_key}")

        if manifest.get("test_twin_policy") != EXPECTED_TEST_TWIN_POLICY:
            errors.append("controller_prod_test_twin_policy_weakened")

    return errors


def evaluate_repository_controller_determination(
    *,
    contract_path: Path = CONTRACT_PATH,
    manifest_path: Path = MANIFEST_PATH,
    controller_path: Path = CONTROLLER_PATH,
) -> tuple[bool, list[str]]:
    errors = controller_determination_errors(
        contract=_load(contract_path),
        manifest=_load(manifest_path),
        controller=_load(controller_path),
    )
    return not errors, errors


def assert_repository_controller_determination_safe() -> None:
    ready, errors = evaluate_repository_controller_determination()
    if not ready:
        raise ControllerDeterminationControlError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_controller_determination_safe()
    except (OSError, json.JSONDecodeError, ControllerDeterminationControlError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print("PASS: AI4WORK controller determination semantics are consistent and remain fail-closed until explicit controller PROD approval and live pre-collection gates are complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
