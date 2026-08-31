from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CLOCK_SKEW = timedelta(minutes=5)
APPROVAL_SCHEMA = "eucons.ai4work_explicit_user_approval_receipt.v0.1"
APPROVAL_SOURCE = "HUMAN_EXPLICIT_USER_APPROVAL"
APPROVAL_ACTION = "REAL_COLLECTION_PROD_ACTIVATION_ONLY"
REQUIRED_BOUND_ARTIFACTS = {
    "need_analysis_plan": HERE / "NEED_ANALYSIS_PLAN_DRAFT.json",
    "collection_frame": HERE / "COLLECTION_FRAME_DRAFT.json",
    "form_contract": HERE / "form_contract.json",
    "invitation_catalog": HERE / "RESEARCH_INVITATION_CATALOG_DRAFT.json",
    "collection_channel_register": HERE / "COLLECTION_CHANNEL_REGISTER_DRAFT.json",
}


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


def _parse_utc_z(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def explicit_user_approval_errors(*, manifest: dict[str, Any], research_id: str) -> list[str]:
    errors: list[str] = []
    reference = manifest.get("explicit_user_approval_reference")
    if not isinstance(reference, str) or not reference.strip():
        return ["explicit_user_approval_missing"]

    digest = manifest.get("explicit_user_approval_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        errors.append("explicit_user_approval_sha256_missing_or_invalid")
        return errors

    receipt_path = _resolve_local_reference(reference)
    if receipt_path is None or receipt_path.suffix.lower() != ".json":
        errors.append("explicit_user_approval_receipt_reference_invalid")
        return errors
    if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != digest:
        errors.append("explicit_user_approval_receipt_hash_mismatch")
        return errors

    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("explicit_user_approval_receipt_unreadable")
        return errors
    if not isinstance(receipt, dict):
        return ["explicit_user_approval_receipt_shape_invalid"]

    if receipt.get("schema_version") != APPROVAL_SCHEMA:
        errors.append("explicit_user_approval_receipt_schema_invalid")
    if receipt.get("research_id") != research_id:
        errors.append("explicit_user_approval_research_id_mismatch")
    if receipt.get("status") != "APPROVED":
        errors.append("explicit_user_approval_receipt_not_approved")
    if receipt.get("approval_source") != APPROVAL_SOURCE:
        errors.append("explicit_user_approval_source_invalid")
    if receipt.get("authorized_action") != APPROVAL_ACTION:
        errors.append("explicit_user_approval_scope_invalid")
    if receipt.get("synthetic") is not False:
        errors.append("explicit_user_approval_synthetic_or_unresolved")
    if receipt.get("approved") is not True:
        errors.append("explicit_user_approval_flag_false")
    if receipt.get("real_collection_authorized") is not True:
        errors.append("explicit_user_approval_real_collection_false")
    if receipt.get("merge_authorized") is not False:
        errors.append("explicit_user_approval_merge_scope_escalated")
    if receipt.get("deploy_authorized") is not False:
        errors.append("explicit_user_approval_deploy_scope_escalated")
    if receipt.get("canonicalization_authorized") is not False:
        errors.append("explicit_user_approval_canonicalization_scope_escalated")

    approved_at = receipt.get("approved_at")
    parsed = _parse_utc_z(approved_at)
    if parsed is None:
        errors.append("explicit_user_approval_timestamp_invalid")
    elif parsed > datetime.now(timezone.utc) + CLOCK_SKEW:
        errors.append("explicit_user_approval_timestamp_future")
    if manifest.get("approval_timestamp") != approved_at:
        errors.append("explicit_user_approval_timestamp_manifest_mismatch")

    bindings = receipt.get("bound_artifacts")
    if not isinstance(bindings, dict):
        errors.append("explicit_user_approval_bindings_missing")
        return errors
    expected_keys = set(REQUIRED_BOUND_ARTIFACTS)
    if set(bindings) != expected_keys:
        errors.append("explicit_user_approval_binding_keys_mismatch")
        return errors

    for key, path in REQUIRED_BOUND_ARTIFACTS.items():
        entry = bindings.get(key)
        if not isinstance(entry, dict):
            errors.append(f"explicit_user_approval_binding_invalid:{key}")
            continue
        entry_reference = entry.get("reference")
        entry_digest = entry.get("sha256")
        if entry_reference != path.name:
            errors.append(f"explicit_user_approval_binding_invalid:{key}")
            continue
        if not isinstance(entry_digest, str) or not SHA256_RE.fullmatch(entry_digest):
            errors.append(f"explicit_user_approval_binding_invalid:{key}")
            continue
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry_digest:
            errors.append(f"explicit_user_approval_binding_invalid:{key}")

    return errors
