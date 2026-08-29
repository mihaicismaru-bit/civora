from __future__ import annotations

import hashlib
from typing import Any

import canonical_export_integrity as EXPORT_INTEGRITY
import nf06_preingest as NF06
from research_storage import RESEARCH_ID


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


def build_prod_preingest_from_persisted_bundles(
    bundles: list[dict[str, Any]],
    *,
    collection_frame: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    """Canonical eucons persisted-storage -> NF06 PROD pre-ingest handoff.

    The returned bytes contain real questionnaire records and must remain inside the
    research-only processing boundary. The returned manifest is the control artifact.
    This function does not authorise collection, synthesis, population claims, merge or deploy.
    """
    records = _validated_sorted_records(bundles)
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

    return source_bytes, manifest
