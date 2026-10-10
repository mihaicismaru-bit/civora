from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

import nf06_preingest as NF06
from research_storage import RESEARCH_ID, canonical_json_bytes


class ResponseIntegrityControlError(ValueError):
    pass


def _signature_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "form_id": record.get("form_id"),
        "profile": record.get("profile"),
        "answers": record.get("answers", {}),
    }


def assert_response_integrity_control(
    records: list[dict[str, Any]],
    *,
    source_export_sha256: str,
) -> dict[str, Any]:
    """Surface structurally identical real responses without fingerprinting people.

    The collection frame explicitly acknowledges that same-person independent
    resubmissions cannot be reliably detected without identity/device linkage.
    This control therefore does not infer identity and does not delete records.
    It binds diagnostics to the exact frozen export and surfaces exact repeated
    analytical signatures for adversarial QA.
    """
    if not records:
        raise ResponseIntegrityControlError("response integrity control requires a non-empty real batch")
    canonical_export_sha = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    if source_export_sha256 != canonical_export_sha:
        raise ResponseIntegrityControlError("response integrity control source export SHA-256 mismatch")

    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ResponseIntegrityControlError(f"record[{index}] must be an object")
        if record.get("research_id") != RESEARCH_ID:
            raise ResponseIntegrityControlError(f"record[{index}] research_id mismatch")
        if record.get("synthetic") is not False:
            raise ResponseIntegrityControlError("response integrity control accepts only synthetic=false PROD records")
        response_id = record.get("response_id")
        if not isinstance(response_id, str) or not NF06.SHA256_RE.fullmatch(response_id):
            raise ResponseIntegrityControlError(f"record[{index}] response_id must be a lowercase 64-hex opaque receipt")
        payload = _signature_payload(record)
        signature_sha = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        clusters[signature_sha].append(
            {
                "response_id": response_id,
                "form_id": record.get("form_id"),
                "region": (record.get("profile") or {}).get("region") if isinstance(record.get("profile"), dict) else None,
                "recruitment_channel_id": record.get("recruitment_channel_id"),
                "received_at": record.get("received_at"),
            }
        )

    repeated = []
    repeated_record_count = 0
    for signature_sha, members in sorted(clusters.items()):
        if len(members) < 2:
            continue
        repeated_record_count += len(members)
        repeated.append(
            {
                "analytical_signature_sha256": signature_sha,
                "record_count": len(members),
                "form_ids": sorted({str(member["form_id"]) for member in members}),
                "regions": sorted({str(member["region"]) for member in members}),
                "recruitment_channel_ids": sorted({str(member["recruitment_channel_id"]) for member in members}),
                "first_received_at": min(str(member["received_at"]) for member in members),
                "last_received_at": max(str(member["received_at"]) for member in members),
            }
        )

    return {
        "schema_version": "eucons.ai4work_response_integrity_control.v0.1",
        "research_id": RESEARCH_ID,
        "stage": "PRE_SYNTHESIS_RESPONSE_INTEGRITY_DIAGNOSTIC",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "source_evidence_class": "PROD_REAL_EVIDENCE",
        "source_export_sha256": canonical_export_sha,
        "record_count": len(records),
        "unique_analytical_signature_count": len(clusters),
        "repeated_signature_cluster_count": len(repeated),
        "repeated_signature_record_count": repeated_record_count,
        "repeated_signature_record_share": repeated_record_count / len(records),
        "repeated_signature_clusters": repeated,
        "response_integrity_qa_required": bool(repeated),
        "same_person_multiple_submission_determined": False,
        "automatic_exclusion_authorized": False,
        "identity_or_device_linkage_used": False,
        "representativeness_claim_allowed": False,
        "scope_boundary": "Exact repeated analytical signatures are QA signals only. They may reflect legitimate identical categorical responses, coordinated/bot submissions, or repeated submissions; this control cannot distinguish those causes without prohibited identity/device linkage. No record is automatically excluded. Adversarial QA must disclose and test the influence of repeated-signature clusters before final ranking when any are present.",
    }
