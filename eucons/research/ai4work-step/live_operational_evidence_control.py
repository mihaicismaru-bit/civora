from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROMOTED_STATUSES = {"PASS", "APPROVED"}
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_RAW_ACCESS_RETENTION_DAYS = 7
MAX_RESIDUAL_BACKUP_DAYS = 92

LIVE_OPERATIONAL_KEYS = {
    "processor_chain",
    "live_public_privacy_surface_reconciliation",
    "account_server_logging_binding",
    "research_only_store_binding",
    "provider_bound_test_twin_smoke",
}

EXPECTED_TEST_TWIN_CLASS = "TEST_TWIN_NON_EVIDENCE"
EXPECTED_OPERATIONAL_CLASS = "OPERATIONAL_EVIDENCE"


class LiveOperationalEvidenceError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _non_placeholder(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    upper = value.strip().upper()
    if "TEST_TWIN" in upper or "NON_EVIDENCE" in upper or "SYNTHETIC" in upper:
        return False
    return not upper.startswith(("OPEN_", "PENDING_", "DRAFT_", "TO_BE_", "UNRESOLVED_"))


def _non_empty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_non_placeholder(item) for item in value)
    )


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _verified_at_errors(artifact: dict[str, Any], *, now_utc: datetime | None = None) -> list[str]:
    verified_at = _parse_utc(artifact.get("verified_at_utc"))
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise LiveOperationalEvidenceError("validation clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if verified_at is None:
        return ["verified_at_utc_invalid"]
    if verified_at > now + MAX_CLOCK_SKEW:
        return ["verified_at_utc_future_dated"]
    return []


def _base_operational_errors(*, key: str, artifact: Any, now_utc: datetime | None = None) -> list[str]:
    if not isinstance(artifact, dict):
        return [f"{key}:attestation_not_object"]
    errors: list[str] = []
    if artifact.get("research_id") != RESEARCH_ID:
        errors.append(f"{key}:research_id_mismatch")
    if artifact.get("evidence_binding_key") != key:
        errors.append(f"{key}:evidence_binding_key_mismatch")
    if artifact.get("synthetic") is not False:
        errors.append(f"{key}:must_be_real")
    if artifact.get("evidence_class") != EXPECTED_OPERATIONAL_CLASS:
        errors.append(f"{key}:evidence_class_invalid")
    if artifact.get("account_specific") is not True:
        errors.append(f"{key}:account_specific_not_verified")
    if artifact.get("provider_bound") is not True:
        errors.append(f"{key}:provider_bound_not_verified")
    if not _non_placeholder(artifact.get("verified_by")):
        errors.append(f"{key}:verified_by_missing")
    errors.extend(f"{key}:{err}" for err in _verified_at_errors(artifact, now_utc=now_utc))
    return errors


def _processor_chain_errors(artifact: Any, *, now_utc: datetime | None = None) -> list[str]:
    key = "processor_chain"
    errors = _base_operational_errors(key=key, artifact=artifact, now_utc=now_utc)
    if not isinstance(artifact, dict):
        return errors

    controller = artifact.get("controller")
    if not isinstance(controller, dict) or not _non_placeholder(controller.get("legal_name")) or not _non_placeholder(controller.get("registration_id")):
        errors.append(f"{key}:controller_identity_missing")
    processor = artifact.get("processor")
    if not isinstance(processor, dict) or not _non_placeholder(processor.get("legal_name")) or not _non_placeholder(processor.get("service")) or not _non_placeholder(processor.get("account_reference")):
        errors.append(f"{key}:processor_account_binding_missing")

    dpa = artifact.get("dpa_binding")
    if not isinstance(dpa, dict) or not _non_placeholder(dpa.get("reference")) or not _sha(dpa.get("sha256")):
        errors.append(f"{key}:dpa_binding_missing_or_invalid")
    if not _non_placeholder(artifact.get("controller_instruction_reference")):
        errors.append(f"{key}:controller_instruction_reference_missing")

    subprocessors = artifact.get("active_subprocessors")
    if not isinstance(subprocessors, list):
        errors.append(f"{key}:active_subprocessors_not_list")
    else:
        seen: set[str] = set()
        for index, subprocessor in enumerate(subprocessors):
            prefix = f"{key}:active_subprocessor_{index}"
            if not isinstance(subprocessor, dict):
                errors.append(f"{prefix}_not_object")
                continue
            name = subprocessor.get("name")
            if not _non_placeholder(name):
                errors.append(f"{prefix}_name_missing")
            elif str(name).casefold() in seen:
                errors.append(f"{prefix}_duplicate")
            else:
                seen.add(str(name).casefold())
            for field in ("purpose", "processing_location", "chapter_v_mechanism"):
                if not _non_placeholder(subprocessor.get(field)):
                    errors.append(f"{prefix}_{field}_missing")

    access = artifact.get("respondent_data_access")
    if not isinstance(access, dict):
        errors.append(f"{key}:respondent_data_access_missing")
    else:
        if not _non_empty_string_list(access.get("authorized_roles")):
            errors.append(f"{key}:authorized_roles_missing")
        if access.get("crm_access_allowed") is not False:
            errors.append(f"{key}:crm_access_must_be_false")
        if access.get("employer_row_level_access_allowed") is not False:
            errors.append(f"{key}:employer_row_level_access_must_be_false")
    return errors


def _privacy_surface_errors(artifact: Any, *, now_utc: datetime | None = None) -> list[str]:
    key = "live_public_privacy_surface_reconciliation"
    errors = _base_operational_errors(key=key, artifact=artifact, now_utc=now_utc)
    if not isinstance(artifact, dict):
        return errors

    if artifact.get("commercial_surface_separate") is not True:
        errors.append(f"{key}:commercial_surface_not_separated")
    if artifact.get("commercial_receiver_used_for_research") is not False:
        errors.append(f"{key}:commercial_receiver_must_not_handle_research")
    if artifact.get("ai4work_article13_surface_live") is not True:
        errors.append(f"{key}:article13_surface_not_live")
    if artifact.get("operational_research_privacy_contact_live") is not True:
        errors.append(f"{key}:privacy_contact_not_live")
    if not _non_placeholder(artifact.get("privacy_contact_reference")):
        errors.append(f"{key}:privacy_contact_reference_missing")
    if not _sha(artifact.get("article13_snapshot_sha256")):
        errors.append(f"{key}:article13_snapshot_sha256_invalid")
    if not _non_empty_string_list(artifact.get("verified_public_routes")):
        errors.append(f"{key}:verified_public_routes_missing")
    return errors


def _logging_errors(artifact: Any, *, now_utc: datetime | None = None) -> list[str]:
    key = "account_server_logging_binding"
    errors = _base_operational_errors(key=key, artifact=artifact, now_utc=now_utc)
    if not isinstance(artifact, dict):
        return errors

    for field in ("provider", "service", "account_reference", "configuration_readback_reference"):
        if not _non_placeholder(artifact.get(field)):
            errors.append(f"{key}:{field}_missing")
    if artifact.get("raw_access_enabled") not in {True, False}:
        errors.append(f"{key}:raw_access_enabled_not_verified")
    retention_days = artifact.get("raw_access_retention_days")
    if not isinstance(retention_days, int) or isinstance(retention_days, bool) or retention_days < 0 or retention_days > MAX_RAW_ACCESS_RETENTION_DAYS:
        errors.append(f"{key}:raw_access_retention_exceeds_approved_7_day_cap")
    if not _non_empty_string_list(artifact.get("authorized_access_roles")):
        errors.append(f"{key}:authorized_access_roles_missing")

    minimisation = artifact.get("log_minimisation")
    if not isinstance(minimisation, dict):
        errors.append(f"{key}:log_minimisation_missing")
    else:
        required_false = (
            "request_bodies_logged",
            "form_answers_logged",
            "raw_idempotency_keys_logged",
            "questionnaire_data_in_query_string",
            "direct_form_identifiers_in_url",
        )
        for field in required_false:
            if minimisation.get(field) is not False:
                errors.append(f"{key}:forbidden_log_content_not_proven_absent:{field}")
        if minimisation.get("raw_access_excluded_from_nf06") is not True:
            errors.append(f"{key}:raw_access_nf06_exclusion_not_verified")
        if minimisation.get("ip_user_agent_excluded_from_analytics") is not True:
            errors.append(f"{key}:ip_user_agent_analytics_exclusion_not_verified")

    cloudflare = artifact.get("cloudflare")
    if not isinstance(cloudflare, dict) or cloudflare.get("effective_state_verified") is not True:
        errors.append(f"{key}:cloudflare_effective_state_not_verified")
    return errors


def _store_errors(artifact: Any, *, now_utc: datetime | None = None) -> list[str]:
    key = "research_only_store_binding"
    errors = _base_operational_errors(key=key, artifact=artifact, now_utc=now_utc)
    if not isinstance(artifact, dict):
        return errors

    for field in ("storage_kind", "canonical_research_location", "canonical_crm_location", "canonical_webroot", "access_control_reference", "deletion_adapter_reference"):
        if not _non_placeholder(artifact.get(field)):
            errors.append(f"{key}:{field}_missing")
    required_true = (
        "canonical_paths_non_overlapping",
        "symlink_alias_check_pass",
        "research_store_separate_from_crm",
        "research_store_outside_webroot",
        "direct_identifiers_forbidden",
        "response_to_contact_link_key_forbidden",
        "commercial_tracking_forbidden",
    )
    for field in required_true:
        if artifact.get(field) is not True:
            errors.append(f"{key}:{field}_not_verified")
    if not _non_empty_string_list(artifact.get("authorized_access_roles")):
        errors.append(f"{key}:authorized_access_roles_missing")

    backup = artifact.get("backup_binding")
    if not isinstance(backup, dict):
        errors.append(f"{key}:backup_binding_missing")
    else:
        days = backup.get("max_residual_days")
        if not isinstance(days, int) or isinstance(days, bool) or days < 0 or days > MAX_RESIDUAL_BACKUP_DAYS:
            errors.append(f"{key}:backup_residual_retention_exceeds_approved_92_day_cap")
        if backup.get("non_renewing_after_deletion") is not True:
            errors.append(f"{key}:backup_non_renewal_not_verified")
        if not _non_placeholder(backup.get("provider_policy_reference")):
            errors.append(f"{key}:backup_provider_policy_reference_missing")
    return errors


def _test_twin_smoke_errors(artifact: Any, *, now_utc: datetime | None = None) -> list[str]:
    key = "provider_bound_test_twin_smoke"
    if not isinstance(artifact, dict):
        return [f"{key}:attestation_not_object"]
    errors: list[str] = []
    if artifact.get("research_id") != RESEARCH_ID:
        errors.append(f"{key}:research_id_mismatch")
    if artifact.get("evidence_binding_key") != key:
        errors.append(f"{key}:evidence_binding_key_mismatch")
    if artifact.get("synthetic") is not True:
        errors.append(f"{key}:must_be_synthetic")
    if artifact.get("evidence_class") != EXPECTED_TEST_TWIN_CLASS:
        errors.append(f"{key}:evidence_class_invalid")
    if artifact.get("prod_promotion_eligible") is not False:
        errors.append(f"{key}:prod_promotion_must_be_false")
    if artifact.get("need_evidence_eligible") is not False:
        errors.append(f"{key}:need_evidence_eligibility_must_be_false")
    if artifact.get("provider_bound") is not True or artifact.get("account_specific") is not True:
        errors.append(f"{key}:provider_account_binding_missing")
    if artifact.get("same_runtime_path_as_prod") is not True:
        errors.append(f"{key}:same_runtime_path_not_verified")
    if artifact.get("writes_prod_need_evidence") is not False:
        errors.append(f"{key}:must_not_write_prod_need_evidence")
    if artifact.get("real_dissemination_performed") is not False:
        errors.append(f"{key}:real_dissemination_must_be_false")
    if not _non_placeholder(artifact.get("verified_by")):
        errors.append(f"{key}:verified_by_missing")
    errors.extend(f"{key}:{err}" for err in _verified_at_errors(artifact, now_utc=now_utc))

    checks = artifact.get("checks")
    required_checks = {
        "submit",
        "canonical_export",
        "rights_hold",
        "rectification",
        "erasure",
        "replay_suppression",
        "retention_expiry",
        "nf06_rejection_as_non_evidence",
    }
    if not isinstance(checks, dict):
        errors.append(f"{key}:checks_missing")
    else:
        missing = required_checks - set(checks)
        if missing:
            errors.append(f"{key}:checks_missing_keys:" + ",".join(sorted(missing)))
        for check in sorted(required_checks & set(checks)):
            if checks.get(check) is not True:
                errors.append(f"{key}:check_not_pass:{check}")
    return errors


def attestation_semantic_errors(*, key: str, artifact: Any, now_utc: datetime | None = None) -> list[str]:
    if key == "processor_chain":
        return _processor_chain_errors(artifact, now_utc=now_utc)
    if key == "live_public_privacy_surface_reconciliation":
        return _privacy_surface_errors(artifact, now_utc=now_utc)
    if key == "account_server_logging_binding":
        return _logging_errors(artifact, now_utc=now_utc)
    if key == "research_only_store_binding":
        return _store_errors(artifact, now_utc=now_utc)
    if key == "provider_bound_test_twin_smoke":
        return _test_twin_smoke_errors(artifact, now_utc=now_utc)
    return [f"unsupported_live_operational_evidence_key:{key}"]


def _resolve_repo_local(reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.strip() or "://" in reference:
        return None
    raw = Path(reference.strip())
    if raw.is_absolute():
        return None
    candidate = (HERE / raw).resolve()
    try:
        candidate.relative_to(HERE.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def repository_live_operational_evidence_errors(
    manifest_path: Path = MANIFEST_PATH,
    *,
    now_utc: datetime | None = None,
) -> list[str]:
    manifest = _load(manifest_path)
    errors: list[str] = []
    if manifest.get("research_id") != RESEARCH_ID:
        errors.append("manifest_research_id_mismatch")
    evidence = manifest.get("required_external_or_operational_evidence")
    if not isinstance(evidence, dict):
        return errors + ["external_evidence_map_missing"]

    missing = LIVE_OPERATIONAL_KEYS - set(evidence)
    if missing:
        errors.append("live_operational_evidence_keys_missing:" + ",".join(sorted(missing)))

    for key in sorted(LIVE_OPERATIONAL_KEYS & set(evidence)):
        item = evidence.get(key)
        if not isinstance(item, dict):
            errors.append(f"{key}:manifest_item_not_object")
            continue
        status = item.get("status")
        reference = item.get("reference")
        digest = item.get("sha256")
        if status == "OPEN":
            # OPEN is the truthful current state. It may cite an immutable draft, but it may not
            # partially claim a PASS/APPROVED operational attestation.
            if reference is None and digest is None:
                continue
            if not isinstance(reference, str) or not reference.strip() or not _sha(digest):
                errors.append(f"{key}:open_binding_partial_or_invalid")
                continue
            candidate = _resolve_repo_local(reference)
            if candidate is None:
                errors.append(f"{key}:open_binding_not_repo_local")
            elif hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
                errors.append(f"{key}:open_binding_sha256_mismatch")
            continue
        if status not in PROMOTED_STATUSES:
            errors.append(f"{key}:status_not_open_or_promoted")
            continue
        if not isinstance(reference, str) or not reference.strip() or not _sha(digest):
            errors.append(f"{key}:promoted_binding_missing_or_invalid")
            continue
        candidate = _resolve_repo_local(reference)
        if candidate is None or candidate.suffix.lower() != ".json":
            errors.append(f"{key}:promoted_attestation_not_repo_local_json")
            continue
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            errors.append(f"{key}:promoted_binding_sha256_mismatch")
            continue
        try:
            artifact = _load(candidate)
        except (OSError, json.JSONDecodeError):
            errors.append(f"{key}:promoted_attestation_invalid_json")
            continue
        errors.extend(attestation_semantic_errors(key=key, artifact=artifact, now_utc=now_utc))
    return errors


def main() -> int:
    errors = repository_live_operational_evidence_errors()
    if errors:
        raise SystemExit("REJECTED: " + "; ".join(errors))
    print(
        "PASS: live operational evidence gates remain truthfully OPEN or, when promoted, "
        "must be immutable and semantically account/provider bound; TEST TWIN remains NON-EVIDENCE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
