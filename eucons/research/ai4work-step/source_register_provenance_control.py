from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from research_storage import RESEARCH_ID, canonical_json_bytes

SCHEMA = "eucons.ai4work_source_register_provenance_manifest.v0.1"
SOURCE_REGISTER_SCHEMA = "eucons.ai4work_source_register_snapshot.v0.1"
PROD_MODE = "PROD_REAL_EVIDENCE"
TEST_MODE = "TEST_TWIN_NON_EVIDENCE"
PROD_STATUS = "VERIFIED_FOR_FINAL_PACKAGE"
TEST_STATUS = "TEST_TWIN_NON_EVIDENCE"
PROD_PROVENANCE_STATUS = "VERIFIED_REAL_SOURCE"
TEST_PROVENANCE_STATUS = "TEST_TWIN_NON_EVIDENCE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_ID_RE = re.compile(r"^S\d{2,}$")
ALLOWED_SOURCE_TYPES = {
    "OFFICIAL_PUBLIC_AUTHORITY",
    "OFFICIAL_STATISTICAL_OR_EU_INSTITUTION",
    "INSTITUTIONAL_RESEARCH_OR_EVALUATION",
    "FIRST_PARTY_CONTROLLED_ARTIFACT",
    "METHOD_OR_GDPR_CONTROL_ARTIFACT",
}


class SourceRegisterProvenanceError(ValueError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_utc_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SourceRegisterProvenanceError(f"{field} must be a non-empty ISO-8601 timestamp")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SourceRegisterProvenanceError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise SourceRegisterProvenanceError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _assert_source_register_basics(source_register: dict[str, Any], *, evidence_mode: str) -> list[dict[str, Any]]:
    if not isinstance(source_register, dict):
        raise SourceRegisterProvenanceError("source register must be an object")
    if source_register.get("schema_version") != SOURCE_REGISTER_SCHEMA:
        raise SourceRegisterProvenanceError("unsupported source-register schema")
    if source_register.get("research_id") != RESEARCH_ID:
        raise SourceRegisterProvenanceError("source-register research mismatch")
    expected_status = PROD_STATUS if evidence_mode == PROD_MODE else TEST_STATUS
    if source_register.get("status") != expected_status:
        raise SourceRegisterProvenanceError("source-register status does not match evidence mode")
    if source_register.get("test_twin_evidence_eligible") is not False:
        raise SourceRegisterProvenanceError("TEST TWIN evidence eligibility must remain false")

    entries = source_register.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SourceRegisterProvenanceError("source register must contain entries")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SourceRegisterProvenanceError(f"source[{index}] must be an object")
        source_id = entry.get("source_id")
        if not isinstance(source_id, str) or SOURCE_ID_RE.fullmatch(source_id) is None:
            raise SourceRegisterProvenanceError(f"source[{index}] invalid source_id")
        if source_id in seen:
            raise SourceRegisterProvenanceError("duplicate source_id")
        seen.add(source_id)
        if entry.get("h1_h5_numeric_points") != 0:
            raise SourceRegisterProvenanceError("secondary/source-register material cannot add H1-H5 numeric points")
        if entry.get("project_activity_as_need_evidence") is not False:
            raise SourceRegisterProvenanceError("project activity cannot be promoted as evidence of need")
        if entry.get("numeric_rank_eligible") is not False:
            raise SourceRegisterProvenanceError("source-register entries cannot alter H1-H5 ranking")
    return entries


def verify_source_register_provenance(
    source_register: dict[str, Any],
    provenance_manifest: dict[str, Any],
    *,
    snapshot_bytes_by_source_id: Mapping[str, bytes],
    evidence_mode: str,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Verify immutable provenance for every source-register row before final packaging.

    PROD requires an exact one-to-one source/provenance census and the actual captured
    source bytes for each row. A declared SHA-256 is never trusted without recomputing
    it over those bytes. TEST TWIN may exercise the same mechanics but is permanently
    NON-EVIDENCE and non-promotable.
    """
    if evidence_mode not in {PROD_MODE, TEST_MODE}:
        raise SourceRegisterProvenanceError("unsupported evidence mode")
    if not isinstance(provenance_manifest, dict):
        raise SourceRegisterProvenanceError("provenance manifest must be an object")
    if provenance_manifest.get("schema_version") != SCHEMA:
        raise SourceRegisterProvenanceError("unsupported provenance manifest schema")
    if provenance_manifest.get("research_id") != RESEARCH_ID:
        raise SourceRegisterProvenanceError("provenance research mismatch")
    if provenance_manifest.get("source_register_sha256") != _sha(source_register):
        raise SourceRegisterProvenanceError("source-register SHA-256 binding mismatch")
    if provenance_manifest.get("test_twin_evidence_eligible") is not False:
        raise SourceRegisterProvenanceError("provenance manifest must reject TEST TWIN promotion")

    source_entries = _assert_source_register_basics(source_register, evidence_mode=evidence_mode)
    source_ids = {entry["source_id"] for entry in source_entries}
    provenance_entries = provenance_manifest.get("entries")
    if not isinstance(provenance_entries, list) or not provenance_entries:
        raise SourceRegisterProvenanceError("provenance manifest must contain entries")

    by_id: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(provenance_entries):
        if not isinstance(entry, dict):
            raise SourceRegisterProvenanceError(f"provenance[{index}] must be an object")
        source_id = entry.get("source_id")
        if not isinstance(source_id, str) or SOURCE_ID_RE.fullmatch(source_id) is None:
            raise SourceRegisterProvenanceError(f"provenance[{index}] invalid source_id")
        if source_id in by_id:
            raise SourceRegisterProvenanceError("duplicate provenance source_id")
        by_id[source_id] = entry

    if set(by_id) != source_ids:
        missing = sorted(source_ids - set(by_id))
        orphan = sorted(set(by_id) - source_ids)
        raise SourceRegisterProvenanceError(
            f"source/provenance census mismatch; missing={missing}; orphan={orphan}"
        )
    if set(snapshot_bytes_by_source_id) != source_ids:
        missing = sorted(source_ids - set(snapshot_bytes_by_source_id))
        orphan = sorted(set(snapshot_bytes_by_source_id) - source_ids)
        raise SourceRegisterProvenanceError(
            f"source/snapshot census mismatch; missing={missing}; orphan={orphan}"
        )

    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    verified: list[dict[str, Any]] = []
    for source_id in sorted(source_ids):
        entry = by_id[source_id]
        source_type = entry.get("source_type")
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise SourceRegisterProvenanceError(f"{source_id} unsupported source_type")
        reference = entry.get("source_reference")
        if not isinstance(reference, str) or not reference.strip():
            raise SourceRegisterProvenanceError(f"{source_id} missing source_reference")
        declared_sha = entry.get("snapshot_sha256")
        if not isinstance(declared_sha, str) or SHA256_RE.fullmatch(declared_sha) is None:
            raise SourceRegisterProvenanceError(f"{source_id} invalid snapshot_sha256")
        payload = snapshot_bytes_by_source_id[source_id]
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise SourceRegisterProvenanceError(f"{source_id} source snapshot bytes required")
        actual_sha = hashlib.sha256(bytes(payload)).hexdigest()
        if actual_sha != declared_sha:
            raise SourceRegisterProvenanceError(f"{source_id} source snapshot SHA-256 mismatch")
        verified_at = _parse_utc_timestamp(entry.get("verified_at"), field=f"{source_id}.verified_at")
        if verified_at > now:
            raise SourceRegisterProvenanceError(f"{source_id} verified_at cannot be in the future")

        if evidence_mode == PROD_MODE:
            if entry.get("status") != PROD_PROVENANCE_STATUS:
                raise SourceRegisterProvenanceError(f"{source_id} PROD source provenance is not verified")
            if entry.get("synthetic") is not False:
                raise SourceRegisterProvenanceError(f"{source_id} PROD source provenance must be real")
            if entry.get("evidence_eligible") is not True:
                raise SourceRegisterProvenanceError(f"{source_id} PROD source provenance must be evidence-eligible")
        else:
            if entry.get("status") != TEST_PROVENANCE_STATUS:
                raise SourceRegisterProvenanceError(f"{source_id} TEST TWIN provenance must be NON-EVIDENCE")
            if entry.get("synthetic") is not True:
                raise SourceRegisterProvenanceError(f"{source_id} TEST TWIN provenance must be synthetic")
            if entry.get("evidence_eligible") is not False:
                raise SourceRegisterProvenanceError(f"{source_id} TEST TWIN provenance cannot be evidence-eligible")

        verified.append(
            {
                "source_id": source_id,
                "source_type": source_type,
                "source_reference": reference,
                "snapshot_sha256": actual_sha,
                "verified_at": verified_at.isoformat(),
            }
        )

    return {
        "schema_version": SCHEMA,
        "research_id": RESEARCH_ID,
        "evidence_mode": evidence_mode,
        "verification_status": "PASS" if evidence_mode == PROD_MODE else TEST_MODE,
        "source_register_sha256": _sha(source_register),
        "verified_source_count": len(verified),
        "verified_sources": verified,
        "secondary_evidence_numeric_points": 0,
        "project_activity_numeric_points": 0,
        "test_twin_evidence_eligible": False,
        "prod_promotion_allowed": evidence_mode == PROD_MODE,
    }
