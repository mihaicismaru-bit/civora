from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import canonical_export_integrity as EXPORT_INTEGRITY
import collection_close_export_freeze as FREEZE
import nf06_preingest as NF06
from research_storage import RESEARCH_ID

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RIGHTS_HOLD_SNAPSHOT_SCHEMA = "eucons.ai4work_rights_hold_snapshot.v0.1"
RIGHTS_HOLD_SOURCE_CLASS = "EUCONS_RESEARCH_RIGHTS_STORE"
RIGHTS_HOLD_ARTIFACT_CLASS = "RIGHTS_CONTROL_SNAPSHOT_NOT_NEED_EVIDENCE"
MAX_RIGHTS_HOLD_SNAPSHOT_AGE = timedelta(minutes=15)
MAX_RIGHTS_HOLD_CLOCK_SKEW = timedelta(minutes=5)
RIGHTS_HOLD_SNAPSHOT_KEYS = {
    "schema_version",
    "research_id",
    "source_class",
    "artifact_class",
    "captured_at",
    "complete_current_snapshot",
    "response_ids",
}


class NF06PersistedHandoffError(ValueError):
    pass


def _validated_sorted_records(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(bundles, list) or not bundles:
        raise NF06PersistedHandoffError("persisted bundle list must be non-empty")

    records: list[dict[str, Any]] = []
    response_ids: set[str] = set()
    for index, bundle in enumerate(bundles):
        try:
            record = EXPORT_INTEGRITY.validate_persisted_bundle(bundle)
        except EXPORT_INTEGRITY.CanonicalExportIntegrityError as exc:
            raise NF06PersistedHandoffError(
                f"persisted bundle[{index}] failed integrity validation: {exc}"
            ) from exc
        response_id = str(record.get("response_id", ""))
        if response_id in response_ids:
            raise NF06PersistedHandoffError("duplicate response_id in persisted handoff")
        response_ids.add(response_id)
        records.append(record)

    records.sort(
        key=lambda row: (
            str(row.get("form_id", "")),
            str(row.get("received_at", "")),
            str(row.get("response_id", "")),
        )
    )
    return records


def _parse_time(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NF06PersistedHandoffError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NF06PersistedHandoffError(
            f"{field} must be a timezone-aware ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise NF06PersistedHandoffError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _validated_rights_hold_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    records: list[dict[str, Any]],
    collection_frame: dict[str, Any],
) -> tuple[frozenset[str], dict[str, Any]]:
    """Validate a structured, complete rights-hold snapshot before PROD export.

    The snapshot is a control artifact only. It contains opaque response receipts
    and bounded control metadata, never respondent identity or case narrative. A
    plain iterable is intentionally rejected: the handoff must know which live
    rights-store class produced the snapshot, that it was declared complete at
    capture time, and when it was captured.
    """
    if snapshot is None:
        raise NF06PersistedHandoffError(
            "authoritative rights-hold snapshot object is required before NF06 PROD handoff"
        )
    if not isinstance(snapshot, dict):
        raise NF06PersistedHandoffError("rights-hold snapshot must be an object")

    actual_keys = set(snapshot)
    if actual_keys != RIGHTS_HOLD_SNAPSHOT_KEYS:
        missing = sorted(RIGHTS_HOLD_SNAPSHOT_KEYS - actual_keys)
        unexpected = sorted(actual_keys - RIGHTS_HOLD_SNAPSHOT_KEYS)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise NF06PersistedHandoffError(
            "rights-hold snapshot exact field allowlist mismatch"
            + (": " + "; ".join(details) if details else "")
        )

    if snapshot.get("schema_version") != RIGHTS_HOLD_SNAPSHOT_SCHEMA:
        raise NF06PersistedHandoffError("rights-hold snapshot schema_version mismatch")
    if snapshot.get("research_id") != RESEARCH_ID:
        raise NF06PersistedHandoffError("rights-hold snapshot research_id mismatch")
    if snapshot.get("source_class") != RIGHTS_HOLD_SOURCE_CLASS:
        raise NF06PersistedHandoffError("rights-hold snapshot source_class mismatch")
    if snapshot.get("artifact_class") != RIGHTS_HOLD_ARTIFACT_CLASS:
        raise NF06PersistedHandoffError("rights-hold snapshot artifact_class mismatch")
    if snapshot.get("complete_current_snapshot") is not True:
        raise NF06PersistedHandoffError(
            "rights-hold snapshot must declare complete_current_snapshot=true"
        )

    response_ids = snapshot.get("response_ids")
    if not isinstance(response_ids, list):
        raise NF06PersistedHandoffError(
            "rights-hold snapshot response_ids must be a list of opaque response ids"
        )

    validated: set[str] = set()
    for index, value in enumerate(response_ids):
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise NF06PersistedHandoffError(
                f"rights-hold snapshot response_id[{index}] must be lowercase SHA-256 hex"
            )
        if value in validated:
            raise NF06PersistedHandoffError(
                "rights-hold snapshot contains duplicate response_id"
            )
        validated.add(value)

    captured_at = _parse_time(snapshot.get("captured_at"), field="rights-hold snapshot captured_at")
    if not records:
        raise NF06PersistedHandoffError(
            "rights-hold snapshot cannot be validated against an empty candidate batch"
        )
    latest_record_at = max(
        _parse_time(record.get("received_at"), field="candidate record received_at")
        for record in records
    )
    collection_closed_at = _parse_time(
        collection_frame.get("collection_closed_at"),
        field="collection_frame.collection_closed_at",
    )
    if captured_at < latest_record_at:
        raise NF06PersistedHandoffError(
            "rights-hold snapshot captured_at predates latest candidate record"
        )
    if captured_at < collection_closed_at:
        raise NF06PersistedHandoffError(
            "rights-hold snapshot captured_at predates collection close"
        )

    validation_now = datetime.now(timezone.utc)
    if captured_at > validation_now + MAX_RIGHTS_HOLD_CLOCK_SKEW:
        raise NF06PersistedHandoffError(
            "rights-hold snapshot captured_at is in the future beyond allowed clock skew"
        )
    if validation_now - captured_at > MAX_RIGHTS_HOLD_SNAPSHOT_AGE:
        raise NF06PersistedHandoffError(
            "rights-hold snapshot is stale at NF06 persisted handoff"
        )

    canonical_snapshot = (
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    canonical_receipts = json.dumps(
        sorted(validated),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    metadata = {
        "schema_version": RIGHTS_HOLD_SNAPSHOT_SCHEMA,
        "source_class": RIGHTS_HOLD_SOURCE_CLASS,
        "captured_at": snapshot["captured_at"],
        "snapshot_sha256": hashlib.sha256(canonical_snapshot).hexdigest(),
        "receipt_set_sha256": hashlib.sha256(canonical_receipts).hexdigest(),
        "hold_count": len(validated),
    }
    return frozenset(validated), metadata


def build_prod_preingest_from_persisted_bundles(
    bundles: list[dict[str, Any]],
    *,
    collection_frame: dict[str, Any],
    rights_hold_snapshot: dict[str, Any] | None,
    collection_freeze_receipt: dict[str, Any] | None,
) -> tuple[bytes, dict[str, Any]]:
    """Canonical eucons persisted-storage -> NF06 PROD pre-ingest handoff.

    The returned bytes contain real questionnaire records and must remain inside
    the research-only processing boundary. The returned manifest is a control
    artifact. A structured, complete and temporally fresh authoritative rights
    snapshot is mandatory, any held record fails closed before export, and the
    exact collection close/export freeze receipt must bind the closed collection
    window to the canonical export and retention policy. This function does not
    authorise collection, synthesis, population claims, merge or deploy.
    """
    records = _validated_sorted_records(bundles)
    held_response_ids, rights_snapshot_meta = _validated_rights_hold_snapshot(
        rights_hold_snapshot,
        records=records,
        collection_frame=collection_frame,
    )
    exported_response_ids = {str(record.get("response_id", "")) for record in records}
    held_in_export = sorted(exported_response_ids & held_response_ids)
    if held_in_export:
        raise NF06PersistedHandoffError(
            "persisted PROD handoff contains response(s) under rights analysis hold"
        )

    try:
        source_bytes = EXPORT_INTEGRITY.canonical_export_bytes_from_persisted_bundles(
            bundles
        )
        latest_record_at = max(str(record.get("received_at", "")) for record in records)
        freeze_meta = FREEZE.validate_collection_freeze_receipt(
            collection_freeze_receipt,
            collection_frame=collection_frame,
            source_bytes=source_bytes,
            record_count=len(records),
            latest_record_at=latest_record_at,
            rights_hold_snapshot_sha256=rights_snapshot_meta["snapshot_sha256"],
        )
        manifest = NF06.build_preingest_manifest(
            records,
            collection_frame=collection_frame,
            source_bytes=source_bytes,
            prod=True,
        )
    except (
        EXPORT_INTEGRITY.CanonicalExportIntegrityError,
        FREEZE.CollectionCloseExportFreezeError,
        NF06.NF06PreingestError,
    ) as exc:
        raise NF06PersistedHandoffError(str(exc)) from exc

    source_sha = hashlib.sha256(source_bytes).hexdigest()
    if manifest.get("research_id") != RESEARCH_ID:
        raise NF06PersistedHandoffError("NF06 manifest research_id mismatch")
    if manifest.get("evidence_class") != NF06.PROD_EVIDENCE_CLASS:
        raise NF06PersistedHandoffError("NF06 manifest evidence_class mismatch")
    if manifest.get("source_export_sha256") != source_sha:
        raise NF06PersistedHandoffError(
            "NF06 manifest is not bound to validated persisted export bytes"
        )
    if manifest.get("record_count") != len(records):
        raise NF06PersistedHandoffError(
            "NF06 manifest record_count mismatch after persisted validation"
        )

    manifest = dict(manifest)
    manifest["rights_hold_snapshot_checked"] = True
    manifest["rights_hold_snapshot_schema"] = rights_snapshot_meta["schema_version"]
    manifest["rights_hold_snapshot_source_class"] = rights_snapshot_meta["source_class"]
    manifest["rights_hold_snapshot_captured_at"] = rights_snapshot_meta["captured_at"]
    manifest["rights_hold_snapshot_sha256"] = rights_snapshot_meta["snapshot_sha256"]
    manifest["rights_hold_receipt_set_sha256"] = rights_snapshot_meta[
        "receipt_set_sha256"
    ]
    manifest["rights_hold_count_at_export"] = rights_snapshot_meta["hold_count"]
    manifest["held_responses_excluded_from_export"] = True
    manifest["rights_hold_scope_boundary"] = (
        "This binding proves that the supplied structured rights-hold snapshot used "
        "the frozen schema/source class, declared itself complete at capture time, "
        "was not older than the collection close or latest candidate record, was "
        "fresh at handoff, and that none of its opaque response ids entered the "
        "canonical PROD export. The live operator must still prove that the deployed "
        "snapshot producer is bound to the actual separate research/privacy rights "
        "store. Snapshot hashes are control artifacts, never evidence of need."
    )
    manifest["collection_close_export_freeze_checked"] = True
    manifest["collection_close_export_freeze_schema"] = freeze_meta["schema_version"]
    manifest["collection_close_export_freeze_artifact_class"] = freeze_meta[
        "artifact_class"
    ]
    manifest["collection_close_export_freeze_status"] = freeze_meta["freeze_status"]
    manifest["collection_closed_at"] = freeze_meta["collection_closed_at"]
    manifest["runtime_acceptance_disabled_at"] = freeze_meta[
        "runtime_acceptance_disabled_at"
    ]
    manifest["export_frozen_at"] = freeze_meta["export_frozen_at"]
    manifest["collection_close_retention_schedule_sha256"] = freeze_meta[
        "retention_schedule_sha256"
    ]
    manifest["collection_close_post_close_accepted_record_count"] = freeze_meta[
        "post_close_accepted_record_count"
    ]
    manifest["collection_close_control_not_need_evidence"] = True
    manifest["collection_close_receipt_is_authorization"] = False
    manifest["collection_close_scope_boundary"] = (
        "This binding proves only the mechanical close/freeze state supplied to the "
        "NF06 handoff: the declared collection close, acceptance disable time, zero "
        "post-close accepted records, exact canonical export SHA-256, exact rights-hold "
        "snapshot SHA-256, exact channel-register SHA-256 and exact retention-schedule "
        "SHA-256 are mutually bound. It is CONTROL metadata, not evidence of need and "
        "not controller, deployment or publication authorization."
    )

    return source_bytes, manifest
