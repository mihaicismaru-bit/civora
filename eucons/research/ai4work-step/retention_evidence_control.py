from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
SCHEDULE_PATH = HERE / "GDPR_RETENTION_SCHEDULE_DRAFT.json"
RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
EVIDENCE_KEY = "retention_and_deletion"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROMOTED_STATUSES = {"PASS", "APPROVED"}
NON_EVIDENCE_MARKERS = ("TEST_TWIN", "NON_EVIDENCE", "SYNTHETIC")
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_LOG_RETENTION_DAYS = 7
MAX_LIVE_DELETE_DAYS_AFTER_CLOSE = 180
MAX_REPLAY_MARKER_HOURS = 24


class RetentionEvidenceError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _contains_non_evidence_marker(value: Any) -> bool:
    if isinstance(value, str):
        upper = value.upper()
        return any(marker in upper for marker in NON_EVIDENCE_MARKERS)
    if isinstance(value, dict):
        return any(_contains_non_evidence_marker(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_non_evidence_marker(v) for v in value)
    return False


def retention_attestation_errors(
    artifact: Any,
    *,
    schedule_path: Path = SCHEDULE_PATH,
    now_utc: datetime | None = None,
) -> list[str]:
    """Validate the minimum semantics required from a promoted live retention attestation.

    This validates evidence shape and immutable policy binding only. It does not manufacture
    provider evidence: a real PASS/APPROVED artifact must be produced from the live eucons.ro
    account/provider configuration and remain synthetic=false.
    """
    if not isinstance(artifact, dict):
        return ["retention_attestation_not_object"]

    errors: list[str] = []
    if artifact.get("schema_version") != "eucons.ai4work_retention_deletion_attestation.v0.1":
        errors.append("retention_attestation_schema_invalid")
    if artifact.get("research_id") != RESEARCH_ID:
        errors.append("retention_attestation_research_id_mismatch")
    if artifact.get("evidence_binding_key") != EVIDENCE_KEY:
        errors.append("retention_attestation_evidence_key_mismatch")
    if artifact.get("evidence_class") != "OPERATIONAL_EVIDENCE":
        errors.append("retention_attestation_evidence_class_invalid")
    if artifact.get("synthetic") is not False:
        errors.append("retention_attestation_must_be_real")
    if _contains_non_evidence_marker(artifact):
        errors.append("retention_attestation_contains_non_evidence_marker")
    if artifact.get("account_specific") is not True:
        errors.append("retention_attestation_not_account_specific")
    if artifact.get("provider_bound") is not True:
        errors.append("retention_attestation_not_provider_bound")

    verified_at = _parse_utc(artifact.get("verified_at"))
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise RetentionEvidenceError("validation clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if verified_at is None:
        errors.append("retention_attestation_verified_at_invalid")
    elif verified_at > now + MAX_CLOCK_SKEW:
        errors.append("retention_attestation_future_dated")

    expected_schedule_sha = hashlib.sha256(schedule_path.read_bytes()).hexdigest()
    if artifact.get("retention_schedule_reference") != schedule_path.name:
        errors.append("retention_schedule_reference_mismatch")
    if artifact.get("retention_schedule_sha256") != expected_schedule_sha:
        errors.append("retention_schedule_sha256_mismatch")

    facts = artifact.get("verified_facts")
    if not isinstance(facts, dict):
        return errors + ["retention_verified_facts_missing"]

    log_days = facts.get("application_log_retention_days")
    if not isinstance(log_days, int) or isinstance(log_days, bool) or log_days < 0 or log_days > MAX_LOG_RETENTION_DAYS:
        errors.append("application_log_retention_exceeds_policy")
    for key in ("request_bodies_logged", "form_answers_logged", "raw_idempotency_key_logged"):
        if facts.get(key) is not False:
            errors.append(f"forbidden_log_content_not_proven_absent:{key}")

    live_days = facts.get("live_research_delete_deadline_days_after_collection_close")
    if not isinstance(live_days, int) or isinstance(live_days, bool) or live_days < 0 or live_days > MAX_LIVE_DELETE_DAYS_AFTER_CLOSE:
        errors.append("live_research_delete_deadline_exceeds_policy")

    replay_hours = facts.get("replay_marker_max_hours")
    if not isinstance(replay_hours, int) or isinstance(replay_hours, bool) or replay_hours < 0 or replay_hours > MAX_REPLAY_MARKER_HOURS:
        errors.append("replay_marker_retention_exceeds_policy")

    required_true = (
        "backup_rotation_verified",
        "backup_retention_non_renewing",
        "deletion_receipt_capability_verified",
        "deletion_counts_before_after_verified",
        "replay_marker_auto_purge_verified",
        "research_analytics_store_checked",
        "optional_contact_store_checked",
    )
    for key in required_true:
        if facts.get(key) is not True:
            errors.append(f"retention_fact_not_verified:{key}")
    if facts.get("ordinary_restore_recreates_deleted_records") is not False:
        errors.append("deleted_records_restore_behavior_not_safe")

    provider_reference = artifact.get("provider_account_service_reference")
    if not isinstance(provider_reference, str) or not provider_reference.strip():
        errors.append("provider_account_service_reference_missing")
    deletion_reference = artifact.get("deletion_control_reference")
    if not isinstance(deletion_reference, str) or not deletion_reference.strip():
        errors.append("deletion_control_reference_missing")

    return errors


def repository_retention_evidence_errors(
    manifest_path: Path = MANIFEST_PATH,
    schedule_path: Path = SCHEDULE_PATH,
) -> list[str]:
    manifest = _load(manifest_path)
    if manifest.get("research_id") != RESEARCH_ID:
        return ["manifest_research_id_mismatch"]
    evidence = manifest.get("required_external_or_operational_evidence")
    if not isinstance(evidence, dict):
        return ["external_evidence_map_missing"]
    item = evidence.get(EVIDENCE_KEY)
    if not isinstance(item, dict):
        return ["retention_evidence_item_missing"]

    status = item.get("status")
    reference = item.get("reference")
    digest = item.get("sha256")
    if status == "OPEN":
        if reference is None and digest is None:
            return []
        return ["open_retention_evidence_must_not_claim_partial_promotion"]
    if status not in PROMOTED_STATUSES:
        return ["retention_evidence_status_not_promotable"]
    if not isinstance(reference, str) or not reference.strip():
        return ["retention_evidence_reference_missing"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        return ["retention_evidence_sha256_invalid"]

    raw = Path(reference)
    if raw.is_absolute() or "://" in reference:
        return ["retention_evidence_reference_not_repo_local"]
    candidate = (HERE / raw).resolve()
    try:
        candidate.relative_to(HERE.resolve())
    except ValueError:
        return ["retention_evidence_reference_path_escape"]
    if not candidate.is_file():
        return ["retention_evidence_reference_missing_file"]
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
        return ["retention_evidence_sha256_mismatch"]
    if candidate.suffix.lower() != ".json":
        return ["retention_evidence_attestation_not_json"]
    try:
        artifact = _load(candidate)
    except (OSError, json.JSONDecodeError):
        return ["retention_evidence_attestation_invalid_json"]
    return retention_attestation_errors(artifact, schedule_path=schedule_path)


def main() -> int:
    errors = repository_retention_evidence_errors()
    if errors:
        raise SystemExit("REJECTED: " + "; ".join(errors))
    manifest = _load(MANIFEST_PATH)
    status = manifest["required_external_or_operational_evidence"][EVIDENCE_KEY]["status"]
    if status == "OPEN":
        print("PASS: retention/deletion remains explicitly OPEN and non-promoted; no live evidence is inferred")
    else:
        print("PASS: promoted retention/deletion evidence is immutable, account-specific, provider-bound and semantically policy-bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
