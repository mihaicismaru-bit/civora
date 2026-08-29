from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import nf06_preingest as NF06
import primary_evidence_readiness as READY
from channel_provenance import ChannelProvenanceError, validate_recruitment_channel_id
from research_storage import RESEARCH_ID, canonical_json_bytes


class RealBatchSynthesisGateError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RealBatchSynthesisGateError(f"{field} must be a non-empty ISO timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RealBatchSynthesisGateError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RealBatchSynthesisGateError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _plain_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _recompute_manifest_aggregates(records: list[dict[str, Any]]) -> dict[str, Any]:
    form_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    form_region_counts: dict[str, Counter[str]] = {
        form_id: Counter() for form_id in READY.FORM_AUDIENCE
    }
    channel_counts: Counter[str] = Counter()
    region_channel_counts: dict[str, Counter[str]] = {
        region: Counter() for region in READY.TARGET_REGIONS
    }
    form_region_channel_counts: dict[str, dict[str, Counter[str]]] = {
        form_id: {region: Counter() for region in READY.TARGET_REGIONS}
        for form_id in READY.FORM_AUDIENCE
    }
    region_channel_ids: dict[str, set[str]] = {
        region: set() for region in READY.TARGET_REGIONS
    }
    form_region_channel_ids: dict[str, dict[str, set[str]]] = {
        form_id: {region: set() for region in READY.TARGET_REGIONS}
        for form_id in READY.FORM_AUDIENCE
    }
    response_ids: set[str] = set()

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise RealBatchSynthesisGateError(f"record[{index}] must be an object")
        if record.get("research_id") != RESEARCH_ID:
            raise RealBatchSynthesisGateError(f"record[{index}] research_id mismatch")
        if record.get("synthetic") is not False:
            raise RealBatchSynthesisGateError("real synthesis gate accepts only synthetic=false PROD records")
        response_id = record.get("response_id")
        if not isinstance(response_id, str) or not NF06.SHA256_RE.fullmatch(response_id):
            raise RealBatchSynthesisGateError(f"record[{index}] response_id must be a lowercase 64-hex opaque receipt")
        if response_id in response_ids:
            raise RealBatchSynthesisGateError("duplicate response_id in bound real batch")
        response_ids.add(response_id)

        form_id = record.get("form_id")
        if form_id not in READY.FORM_AUDIENCE:
            raise RealBatchSynthesisGateError(f"record[{index}] unsupported form_id")
        profile = record.get("profile")
        if not isinstance(profile, dict):
            raise RealBatchSynthesisGateError(f"record[{index}] profile must be an object")
        region = profile.get("region")
        if region not in READY.TARGET_REGIONS:
            raise RealBatchSynthesisGateError(f"record[{index}] region outside target regions")
        try:
            channel_id = validate_recruitment_channel_id(record.get("recruitment_channel_id"))
        except ChannelProvenanceError as exc:
            raise RealBatchSynthesisGateError(str(exc)) from exc

        form_counts[form_id] += 1
        region_counts[region] += 1
        form_region_counts[form_id][region] += 1
        channel_counts[channel_id] += 1
        region_channel_counts[region][channel_id] += 1
        form_region_channel_counts[form_id][region][channel_id] += 1
        region_channel_ids[region].add(channel_id)
        form_region_channel_ids[form_id][region].add(channel_id)

    return {
        "record_count": len(records),
        "form_counts": {form_id: form_counts.get(form_id, 0) for form_id in READY.FORM_AUDIENCE},
        "region_counts": {region: region_counts.get(region, 0) for region in READY.TARGET_REGIONS},
        "form_region_counts": {
            form_id: {
                region: form_region_counts[form_id].get(region, 0)
                for region in READY.TARGET_REGIONS
            }
            for form_id in READY.FORM_AUDIENCE
        },
        "channel_counts": _plain_counter(channel_counts),
        "region_channel_counts": {
            region: _plain_counter(region_channel_counts[region])
            for region in READY.TARGET_REGIONS
        },
        "form_region_channel_counts": {
            form_id: {
                region: _plain_counter(form_region_channel_counts[form_id][region])
                for region in READY.TARGET_REGIONS
            }
            for form_id in READY.FORM_AUDIENCE
        },
        "region_channel_ids": {
            region: sorted(region_channel_ids[region])
            for region in READY.TARGET_REGIONS
        },
        "form_region_channel_ids": {
            form_id: {
                region: sorted(form_region_channel_ids[form_id][region])
                for region in READY.TARGET_REGIONS
            }
            for form_id in READY.FORM_AUDIENCE
        },
    }


def _assert_manifest_bound_to_records(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if not records:
        raise RealBatchSynthesisGateError("real synthesis gate requires a non-empty record batch")
    if not isinstance(manifest, dict):
        raise RealBatchSynthesisGateError("NF06 manifest must be an object")

    source_sha = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    if manifest.get("source_export_sha256") != source_sha:
        raise RealBatchSynthesisGateError("record bytes do not match manifest source_export_sha256")

    recomputed = _recompute_manifest_aggregates(records)
    for field, value in recomputed.items():
        if manifest.get(field) != value:
            raise RealBatchSynthesisGateError(f"manifest {field} does not reconcile with the bound record batch")
    return recomputed


def _assert_collection_frame_bound(
    records: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    collection_frame: dict[str, Any],
) -> dict[str, Any]:
    """Bind the exact real batch and NF06 manifest to the frozen PROD collection frame."""
    try:
        frame_start, frame_end, allowed_channels = NF06.validate_collection_frame(collection_frame, prod=True)
    except NF06.NF06PreingestError as exc:
        raise RealBatchSynthesisGateError(str(exc)) from exc

    frame_sha = hashlib.sha256(canonical_json_bytes(collection_frame)).hexdigest()
    if manifest.get("collection_frame_sha256") != frame_sha:
        raise RealBatchSynthesisGateError("NF06 manifest is not bound to the supplied collection frame")

    source_sha = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    if collection_frame.get("source_export_sha256") != source_sha:
        raise RealBatchSynthesisGateError("collection frame source_export_sha256 does not bind the real batch")
    if manifest.get("source_export_sha256") != source_sha:
        raise RealBatchSynthesisGateError("manifest source_export_sha256 does not bind the real batch")

    for field in (
        "collection_channel_register_sha256",
        "form_contract_sha256",
        "forms_definition_sha256",
    ):
        if manifest.get(field) != collection_frame.get(field):
            raise RealBatchSynthesisGateError(f"manifest {field} is not bound to the collection frame")

    used_channels: set[str] = set()
    for index, record in enumerate(records):
        try:
            channel_id = validate_recruitment_channel_id(record.get("recruitment_channel_id"))
        except ChannelProvenanceError as exc:
            raise RealBatchSynthesisGateError(str(exc)) from exc
        used_channels.add(channel_id)
        received = _parse_ts(record.get("received_at"), field=f"record[{index}].received_at")
        if not frame_start <= received <= frame_end:
            raise RealBatchSynthesisGateError(
                f"record[{index}] received_at is outside the frozen PROD collection frame"
            )

    undeclared = used_channels - set(allowed_channels)
    if undeclared:
        raise RealBatchSynthesisGateError(
            f"bound real batch uses channel(s) outside collection frame: {sorted(undeclared)}"
        )

    return {
        "collection_frame_sha256": frame_sha,
        "collection_frame_window_validated": True,
        "collection_frame_channel_membership_validated": True,
    }


def _assert_channel_register_snapshot_bound(
    *,
    manifest: dict[str, Any],
    collection_frame: dict[str, Any],
    channel_register: dict[str, Any],
) -> str:
    """Bind the exact supplied channel-register snapshot to the frozen frame and NF06 manifest."""
    register_sha = hashlib.sha256(canonical_json_bytes(channel_register)).hexdigest()
    frame_sha = collection_frame.get("collection_channel_register_sha256")
    manifest_sha = manifest.get("collection_channel_register_sha256")
    if register_sha != frame_sha:
        raise RealBatchSynthesisGateError(
            "supplied channel register does not match collection_frame collection_channel_register_sha256"
        )
    if register_sha != manifest_sha:
        raise RealBatchSynthesisGateError(
            "supplied channel register does not match manifest collection_channel_register_sha256"
        )
    return register_sha


def validate_channel_temporal_provenance(
    records: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    collection_frame: dict[str, Any],
    channel_register: dict[str, Any],
) -> dict[str, Any]:
    """Bind each real response to the frozen PROD frame and its attributed channel window.

    This is a control/provenance check only. It is not need evidence and does not
    make a non-probability sample representative.
    """
    _assert_manifest_bound_to_records(records, manifest)
    frame_binding = _assert_collection_frame_bound(
        records,
        manifest=manifest,
        collection_frame=collection_frame,
    )
    try:
        register_by_id = READY._validate_channel_register(channel_register)
    except READY.PrimaryEvidenceReadinessError as exc:
        raise RealBatchSynthesisGateError(str(exc)) from exc
    register_sha = _assert_channel_register_snapshot_bound(
        manifest=manifest,
        collection_frame=collection_frame,
        channel_register=channel_register,
    )

    bounds: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        channel_id = validate_recruitment_channel_id(record.get("recruitment_channel_id"))
        entry = register_by_id.get(channel_id)
        if entry is None:
            raise RealBatchSynthesisGateError(f"record[{index}] channel absent from frozen register")
        region = record["profile"]["region"]
        audience = READY.FORM_AUDIENCE[record["form_id"]]
        if region not in entry["region_scope"]:
            raise RealBatchSynthesisGateError(f"record[{index}] channel is not authorised for its region")
        if audience not in entry["audience_scope"]:
            raise RealBatchSynthesisGateError(f"record[{index}] channel is not authorised for its audience")

        received = _parse_ts(record.get("received_at"), field=f"record[{index}].received_at")
        opened = _parse_ts(entry.get("opened_at"), field=f"channel[{channel_id}].opened_at")
        closed = _parse_ts(entry.get("closed_at"), field=f"channel[{channel_id}].closed_at")
        if not opened <= received <= closed:
            raise RealBatchSynthesisGateError(
                f"record[{index}] received_at is outside the attributed channel collection window"
            )

        current = bounds.setdefault(
            channel_id,
            {"count": 0, "first_received_at": received, "last_received_at": received},
        )
        current["count"] += 1
        if received < current["first_received_at"]:
            current["first_received_at"] = received
        if received > current["last_received_at"]:
            current["last_received_at"] = received

    rendered_bounds = {
        channel_id: {
            "count": data["count"],
            "first_received_at": data["first_received_at"].isoformat(),
            "last_received_at": data["last_received_at"].isoformat(),
        }
        for channel_id, data in sorted(bounds.items())
    }
    if {channel_id: data["count"] for channel_id, data in rendered_bounds.items()} != manifest.get("channel_counts"):
        raise RealBatchSynthesisGateError("temporal channel counts do not reconcile with manifest channel_counts")

    return {
        "schema_version": "eucons.ai4work_channel_temporal_provenance.v0.2",
        "research_id": RESEARCH_ID,
        "stage": "PRE_SYNTHESIS_CHANNEL_TEMPORAL_PROVENANCE",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "source_evidence_class": READY.PROD_EVIDENCE_CLASS,
        "collection_frame_bound": True,
        "collection_frame_sha256": frame_binding["collection_frame_sha256"],
        "collection_frame_window_validated": frame_binding["collection_frame_window_validated"],
        "collection_frame_channel_membership_validated": frame_binding[
            "collection_frame_channel_membership_validated"
        ],
        "channel_register_bound": True,
        "channel_register_sha256": register_sha,
        "channel_temporal_windows_validated": True,
        "channel_received_at_bounds": rendered_bounds,
        "representativeness_claim_allowed": False,
        "scope_boundary": "PASS proves only that the bound real-response batch reconciles to the NF06 manifest, the frozen PROD collection frame, the exact frozen channel-register snapshot and the authorised channel windows. It is not population or need evidence.",
    }


def assert_real_batch_ready_for_synthesis(
    records: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    collection_frame: dict[str, Any],
    method_frame: dict[str, Any],
    channel_register: dict[str, Any],
    dominant_channel_sensitivity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical fail-closed gate for a real NF06 batch entering needs synthesis."""
    temporal = validate_channel_temporal_provenance(
        records,
        manifest=manifest,
        collection_frame=collection_frame,
        channel_register=channel_register,
    )
    try:
        readiness = READY.assert_primary_evidence_ready_for_synthesis(
            manifest,
            method_frame=method_frame,
            channel_register=channel_register,
            dominant_channel_sensitivity=dominant_channel_sensitivity,
        )
    except READY.PrimaryEvidenceReadinessError as exc:
        raise RealBatchSynthesisGateError(str(exc)) from exc

    return {
        "schema_version": "eucons.ai4work_real_batch_synthesis_gate.v0.2",
        "research_id": RESEARCH_ID,
        "stage": "REAL_BATCH_PRE_SYNTHESIS_GATE",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "source_evidence_class": READY.PROD_EVIDENCE_CLASS,
        "ready_for_primary_synthesis": True,
        "collection_frame_bound": temporal["collection_frame_bound"],
        "collection_frame_sha256": temporal["collection_frame_sha256"],
        "collection_frame_window_validated": temporal["collection_frame_window_validated"],
        "collection_frame_channel_membership_validated": temporal[
            "collection_frame_channel_membership_validated"
        ],
        "channel_register_bound": temporal["channel_register_bound"],
        "channel_register_sha256": temporal["channel_register_sha256"],
        "channel_temporal_windows_validated": temporal["channel_temporal_windows_validated"],
        "channel_received_at_bounds": temporal["channel_received_at_bounds"],
        "method_readiness_schema_version": readiness["schema_version"],
        "representativeness_claim_allowed": False,
        "weighting_allowed": False,
        "scope_boundary": "Only this combined gate authorises entry of the exact real PROD batch bound to its NF06 manifest, frozen PROD collection frame and exact frozen channel-register snapshot into needs synthesis/adversarial QA. PASS does not establish prevalence, causality, representativeness or any need conclusion.",
    }
