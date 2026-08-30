from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

import canonical_export_integrity as EXPORT_INTEGRITY
import nf06_preingest as NF06
from research_storage import RESEARCH_ID

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _validated_rights_hold_snapshot(response_ids: Iterable[str] | None) -> tuple[frozenset[str], str]:
    """Validate and hash the authoritative rights-hold snapshot used for export.

    The caller must supply the complete set of opaque response receipts currently
    restricted/objected in the live research-rights store. ``None`` is rejected so
    PROD handoff cannot silently bypass the rights check. The snapshot hash is safe
    to carry as a control binding; the receipt list itself must remain inside the
    restricted research/privacy boundary.
    """
    if response_ids is None:
        raise NF06PersistedHandoffError(
            "authoritative rights-hold snapshot is required before NF06 PROD handoff"
        )
    if isinstance(response_ids, (str, bytes, bytearray)):
        raise NF06PersistedHandoffError("rights-hold snapshot must be an iterable of opaque response ids")

    validated: set[str] = set()
    try:
        values = list(response_ids)
    except TypeError as exc:
        raise NF06PersistedHandoffError("rights-hold snapshot must be iterable") from exc

    for index, value in enumerate(values):
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise NF06PersistedHandoffError(
                f"rights-hold snapshot response_id[{index}] must be lowercase SHA-256 hex"
            )
        if value in validated:
            raise NF06PersistedHandoffError("rights-hold snapshot contains duplicate response_id")
        validated.add(value)

    canonical = json.dumps(sorted(validated), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return frozenset(validated), hashlib.sha256(canonical).hexdigest()


def build_prod_preingest_from_persisted_bundles(
    bundles: list[dict[str, Any]],
    *,
    collection_frame: dict[str, Any],
    rights_hold_response_ids: Iterable[str] | None,
) -> tuple[bytes, dict[str, Any]]:
    """Canonical eucons persisted-storage -> NF06 PROD pre-ingest handoff.

    The returned bytes contain real questionnaire records and must remain inside the
    research-only processing boundary. The returned manifest is the control artifact.
    A complete authoritative snapshot of currently restricted/objected response ids is
    mandatory, and any held record fails closed before export. This function does not
    authorise collection, synthesis, population claims, merge or deploy.
    """
    records = _validated_sorted_records(bundles)
    held_response_ids, hold_snapshot_sha = _validated_rights_hold_snapshot(
        rights_hold_response_ids
    )
    exported_response_ids = {str(record.get("response_id", "")) for record in records}
    held_in_export = sorted(exported_response_ids & held_response_ids)
    if held_in_export:
        raise NF06PersistedHandoffError(
            "persisted PROD handoff contains response(s) under rights analysis hold"
        )

    try:
        source_bytes = EXPORT_INTEGRITY.canonical_export_bytes_from_persisted_bundles(bundles)
        manifest = NF06.build_preingest_manifest(
            records,
            collection_frame=collection_frame,
            source_bytes=source_bytes,
            prod=True,
        )
    except (EXPORT_INTEGRITY.CanonicalExportIntegrityError, NF06.NF06PreingestError) as exc:
        raise NF06PersistedHandoffError(str(exc)) from exc

    source_sha = hashlib.sha256(source_bytes).hexdigest()
    if manifest.get("research_id") != RESEARCH_ID:
        raise NF06PersistedHandoffError("NF06 manifest research_id mismatch")
    if manifest.get("evidence_class") != NF06.PROD_EVIDENCE_CLASS:
        raise NF06PersistedHandoffError("NF06 manifest evidence_class mismatch")
    if manifest.get("source_export_sha256") != source_sha:
        raise NF06PersistedHandoffError("NF06 manifest is not bound to validated persisted export bytes")
    if manifest.get("record_count") != len(records):
        raise NF06PersistedHandoffError("NF06 manifest record_count mismatch after persisted validation")

    manifest = dict(manifest)
    manifest["rights_hold_snapshot_checked"] = True
    manifest["rights_hold_snapshot_sha256"] = hold_snapshot_sha
    manifest["rights_hold_count_at_export"] = len(held_response_ids)
    manifest["held_responses_excluded_from_export"] = True
    manifest["rights_hold_scope_boundary"] = (
        "This binding proves only that the supplied authoritative rights-hold snapshot "
        "was checked and that none of its opaque response ids entered the canonical PROD export. "
        "The live operator remains responsible for sourcing a complete current snapshot from the "
        "separate research/privacy rights store; this hash is a control artifact, not need evidence."
    )

    return source_bytes, manifest
