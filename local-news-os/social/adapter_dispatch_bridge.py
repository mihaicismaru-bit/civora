#!/usr/bin/env python3
"""Adapter-gated dispatch bridge for LOCAL NEWS OS social publications.

The production orchestrator stops at durable publication state. This bridge is the
next trust boundary: it consumes an orchestrator report, the instance channel
registry and only the *names* of credential references known to be present at
runtime. It never reads credential values and never performs network dispatch.

For a dispatchable publication it emits one deterministic atomic handoff bundle
containing the channel-local ledger plus a durable logical outbox item. The item
is explicitly classified as DIRECT_READY, OUTBOX_ONLY or
BLOCKED_MISSING_CREDENTIALS. Existing platform adapters remain the network
boundary and may consume DIRECT_READY items only.

Website and every social channel remain sibling publications. The bridge accepts
only the already-built native product for the current channel and never copies
content from another platform.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import publishing_adapters

SCHEMA_VERSION = "1.0"
DISPATCHABLE_PUBLICATION_STATES = {"READY", "OUTBOX_READY"}
UPSTREAM_HOLD_STATES = {
    "HOLD_TIMING",
    "AWAITING_APPROVAL",
    "RETRY_WAIT",
    "BLOCKED_AUTH",
    "PUBLISHED",
    "FAILED_TERMINAL",
    "SUPERSEDED_CORRECTION",
    "CORRECTION_REQUIRED",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _platform_key(value: Any) -> str:
    return _clean(value).lower().replace("-", "_")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def empty_handoff_outbox(instance_id: str, channel_id: str, platform: str) -> dict[str, Any]:
    """Return an empty logical channel outbox owned by the bridge."""
    instance_id = _clean(instance_id)
    channel_id = _clean(channel_id)
    platform = _platform_key(platform)
    if not instance_id or not channel_id or not platform:
        raise ValueError("instance_id, channel_id and platform are required")
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "channel_id": channel_id,
        "platform": platform,
        "items": {},
        "guards": {
            "channel_outbox_logically_independent": True,
            "credential_values_allowed": False,
            "network_dispatch_performed": False,
            "zero_paid_dependency": True,
        },
    }


def _normalize_present_refs(values: Iterable[str] | None) -> tuple[set[str], list[str]]:
    if values is None:
        return set(), []
    if isinstance(values, (str, bytes)):
        values = [str(values)]
    refs: set[str] = set()
    errors: list[str] = []
    try:
        iterator = iter(values)
    except TypeError:
        return set(), ["INVALID_PRESENT_REFERENCE_COLLECTION"]
    for raw in iterator:
        text = _clean(raw)
        lowered = text.lower()
        if (
            not publishing_adapters.REFERENCE_RE.fullmatch(text)
            or lowered.startswith(publishing_adapters.SECRET_VALUE_PREFIXES)
        ):
            errors.append("PRESENT_REFERENCE_NOT_NAME")
            continue
        refs.add(text)
    return refs, sorted(set(errors))


def _find_registry_entry(registry: dict[str, Any], platform: str) -> dict[str, Any] | None:
    channels = registry.get("channels")
    if not isinstance(channels, list):
        return None
    wanted = _platform_key(platform)
    matches = [raw for raw in channels if isinstance(raw, dict) and _platform_key(raw.get("channel_id")) == wanted]
    return matches[0] if len(matches) == 1 else None


def _runtime_parts(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
    publication = artifacts.get("publication") if isinstance(artifacts.get("publication"), dict) else {}
    record = publication.get("record") if isinstance(publication.get("record"), dict) else {}
    ledger = publication.get("ledger") if isinstance(publication.get("ledger"), dict) else {}
    formatted = artifacts.get("format") if isinstance(artifacts.get("format"), dict) else {}
    product = formatted.get("product") if isinstance(formatted.get("product"), dict) else {}
    return artifacts, publication, record, ledger, product


def _runtime_blocks(report: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if report.get("blocked") is True:
        blocks.append("UPSTREAM_RUNTIME_BLOCKED")

    instance_id = _clean(report.get("instance_id"))
    channel_id = _clean(report.get("channel_id"))
    platform = _platform_key(report.get("platform"))
    if not instance_id:
        blocks.append("MISSING_INSTANCE_ID")
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    if not platform:
        blocks.append("MISSING_PLATFORM")
    registry_instance = _clean(registry.get("instance_id"))
    if registry_instance and instance_id and registry_instance != instance_id:
        blocks.append("REGISTRY_INSTANCE_MISMATCH")

    policy = registry.get("policy") if isinstance(registry.get("policy"), dict) else {}
    if policy.get("fail_closed_on_missing_credentials") is not True:
        blocks.append("REGISTRY_MUST_FAIL_CLOSED_ON_MISSING_CREDENTIALS")
    if policy.get("paid_social_scheduler_required") is not False:
        blocks.append("PAID_SCHEDULER_POLICY_VIOLATION")
    if policy.get("paid_llm_api_required") is not False:
        blocks.append("PAID_LLM_POLICY_VIOLATION")

    guards = report.get("guards") if isinstance(report.get("guards"), dict) else {}
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    if guards.get("network_calls_performed") is not False:
        blocks.append("UPSTREAM_NETWORK_CALLS_FORBIDDEN")
    if guards.get("credential_values_read") is not False:
        blocks.append("UPSTREAM_CREDENTIAL_VALUES_READ")
    if guards.get("credential_values_exposed") is not False:
        blocks.append("UPSTREAM_CREDENTIAL_VALUES_EXPOSED")
    if guards.get("paid_scheduler_used") is not False:
        blocks.append("PAID_SCHEDULER_USED")
    if guards.get("paid_llm_api_used") is not False:
        blocks.append("PAID_LLM_API_USED")
    if guards.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")

    pipeline_fp = _clean(report.get("pipeline_fingerprint_sha256"))
    if not _is_sha256(pipeline_fp):
        blocks.append("INVALID_PIPELINE_FINGERPRINT")

    _, publication, record, ledger, product = _runtime_parts(report)
    if not publication:
        blocks.append("MISSING_PUBLICATION_STATE")
    if not record:
        blocks.append("MISSING_PUBLICATION_RECORD")
    if not ledger:
        blocks.append("MISSING_PUBLICATION_LEDGER")
    if not product:
        blocks.append("MISSING_NATIVE_PRODUCT")

    if record:
        if _clean(record.get("instance_id")) != instance_id:
            blocks.append("RECORD_INSTANCE_MISMATCH")
        if _clean(record.get("channel_id")) != channel_id:
            blocks.append("RECORD_CHANNEL_MISMATCH")
        if _platform_key(record.get("platform")) != platform:
            blocks.append("RECORD_PLATFORM_MISMATCH")
        if not _clean(record.get("publication_id")):
            blocks.append("MISSING_PUBLICATION_ID")
        if not _clean(record.get("dedupe_key")):
            blocks.append("MISSING_DEDUPE_KEY")

    if ledger:
        if _clean(ledger.get("instance_id")) != instance_id:
            blocks.append("LEDGER_INSTANCE_MISMATCH")
        if _clean(ledger.get("channel_id")) != channel_id:
            blocks.append("LEDGER_CHANNEL_MISMATCH")
        if _platform_key(ledger.get("platform")) != platform:
            blocks.append("LEDGER_PLATFORM_MISMATCH")
        records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
        publication_id = _clean(record.get("publication_id"))
        stored = records.get(publication_id) if publication_id else None
        if not isinstance(stored, dict):
            blocks.append("LEDGER_PUBLICATION_MISSING")
        elif _clean(stored.get("dedupe_key")) != _clean(record.get("dedupe_key")):
            blocks.append("LEDGER_RECORD_DEDUPE_MISMATCH")

    if product:
        product_instance = _clean(product.get("instance_id"))
        product_channel = _clean(product.get("channel_id"))
        product_platform = _platform_key(product.get("platform"))
        if product_instance and product_instance != instance_id:
            blocks.append("PRODUCT_INSTANCE_MISMATCH")
        if product_channel and product_channel != channel_id:
            blocks.append("PRODUCT_CHANNEL_MISMATCH")
        if product_platform and product_platform != platform:
            blocks.append("PRODUCT_PLATFORM_MISMATCH")
        if _clean(product.get("product_id")) != _clean(record.get("product_id")):
            blocks.append("PRODUCT_RECORD_ID_MISMATCH")
        if _clean(product.get("product_fingerprint_sha256")) != _clean(record.get("product_fingerprint_sha256")):
            blocks.append("PRODUCT_RECORD_FINGERPRINT_MISMATCH")
        if _clean(product.get("cross_post_policy")) != "NATIVE_PRODUCT_ONLY":
            blocks.append("INVALID_CROSS_POST_POLICY")
        if product.get("verbatim_cross_platform_reuse_allowed") is not False:
            blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
        if product.get("analytics_used") is not False:
            blocks.append("ANALYTICS_POLICY_VIOLATION")

    return sorted(set(blocks))


def _validate_outbox(outbox: dict[str, Any], report: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(outbox.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("OUTBOX_SCHEMA_VERSION")
    if _clean(outbox.get("instance_id")) != _clean(report.get("instance_id")):
        blocks.append("OUTBOX_INSTANCE_MISMATCH")
    if _clean(outbox.get("channel_id")) != _clean(report.get("channel_id")):
        blocks.append("OUTBOX_CHANNEL_MISMATCH")
    if _platform_key(outbox.get("platform")) != _platform_key(report.get("platform")):
        blocks.append("OUTBOX_PLATFORM_MISMATCH")
    if not isinstance(outbox.get("items"), dict):
        blocks.append("OUTBOX_ITEMS_INVALID")
    guards = outbox.get("guards") if isinstance(outbox.get("guards"), dict) else {}
    if guards.get("credential_values_allowed") is not False:
        blocks.append("OUTBOX_CREDENTIAL_VALUE_POLICY")
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("OUTBOX_ZERO_PAID_DEPENDENCY")
    return sorted(set(blocks))


def _adapter_payload(report: dict[str, Any]) -> dict[str, Any]:
    artifacts, _, record, _, product = _runtime_parts(report)
    visual = artifacts.get("visual") if isinstance(artifacts.get("visual"), dict) else {}
    visual_binding = visual.get("binding") if isinstance(visual.get("binding"), dict) else {}
    link_binding = artifacts.get("link_binding") if isinstance(artifacts.get("link_binding"), dict) else {}
    return {
        "instance_id": _clean(report.get("instance_id")),
        "channel_id": _clean(report.get("channel_id")),
        "platform": _platform_key(report.get("platform")),
        "story_id": _clean(report.get("story_id")),
        "publication_id": _clean(record.get("publication_id")),
        "dedupe_key": _clean(record.get("dedupe_key")),
        "product_id": _clean(product.get("product_id")),
        "product_fingerprint_sha256": _clean(product.get("product_fingerprint_sha256")),
        "pipeline_fingerprint_sha256": _clean(report.get("pipeline_fingerprint_sha256")),
        "native_product": copy.deepcopy(product),
        "visual_binding": copy.deepcopy(visual_binding),
        "link_binding": copy.deepcopy(link_binding),
    }


def _blocked(report: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(report.get("instance_id")) or None,
        "channel_id": _clean(report.get("channel_id")) or None,
        "platform": _platform_key(report.get("platform")) or None,
        "blocked": True,
        "hard_blocks": sorted(set(reasons)),
        "decision": "BLOCKED",
        "dispatch_disposition": "BLOCKED",
        "runtime_gate": None,
        "adapter_handoff": None,
        "commit_bundle": None,
        "guards": {
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }


def bridge_runtime_handoff(
    runtime_report: dict[str, Any],
    registry: dict[str, Any],
    present_refs: Iterable[str] | None,
    outbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, credential-value-free dispatch handoff bundle."""
    if not isinstance(runtime_report, dict) or not isinstance(registry, dict):
        raise TypeError("runtime_report and registry must be mappings")
    if outbox is not None and not isinstance(outbox, dict):
        raise TypeError("outbox must be a mapping when provided")

    blocks = _runtime_blocks(runtime_report, registry)
    refs, ref_errors = _normalize_present_refs(present_refs)
    blocks.extend(ref_errors)
    if blocks:
        return _blocked(runtime_report, blocks)

    artifacts, _, record, ledger, _ = _runtime_parts(runtime_report)
    publication_status = _clean(record.get("status"))
    if publication_status not in DISPATCHABLE_PUBLICATION_STATES:
        if publication_status not in UPSTREAM_HOLD_STATES:
            return _blocked(runtime_report, ["UNKNOWN_PUBLICATION_STATE"])
        return {
            "schema_version": SCHEMA_VERSION,
            "instance_id": _clean(runtime_report.get("instance_id")),
            "channel_id": _clean(runtime_report.get("channel_id")),
            "platform": _platform_key(runtime_report.get("platform")),
            "blocked": False,
            "hard_blocks": [],
            "decision": "NO_HANDOFF_UPSTREAM_STATE",
            "dispatch_disposition": "HOLD_UPSTREAM",
            "publication_status": publication_status,
            "runtime_gate": None,
            "adapter_handoff": None,
            "commit_bundle": None,
            "guards": {
                "credential_values_read": False,
                "credential_values_exposed": False,
                "network_dispatch_performed": False,
                "paid_scheduler_used": False,
                "paid_llm_api_used": False,
                "zero_paid_dependency": True,
            },
        }

    platform = _platform_key(runtime_report.get("platform"))
    entry = _find_registry_entry(registry, platform)
    if entry is None:
        return _blocked(runtime_report, ["CHANNEL_REGISTRY_ENTRY_MISSING_OR_AMBIGUOUS"])

    gate = publishing_adapters.runtime_gate(entry, refs)
    gate_decision = _clean(gate.get("decision"))
    if gate_decision == "BLOCKED_INVALID_CREDENTIAL_CONTRACT":
        return _blocked(runtime_report, [str(value) for value in gate.get("errors", [])] or [gate_decision])

    adapter = _clean(entry.get("adapter"))
    outbox_path = _clean(entry.get("outbox"))
    state_path = _clean(entry.get("state"))
    if not outbox_path:
        return _blocked(runtime_report, ["MISSING_DURABLE_OUTBOX_PATH"])
    if not state_path:
        return _blocked(runtime_report, ["MISSING_DURABLE_STATE_PATH"])

    if gate_decision == "DIRECT_READY" and publication_status == "READY":
        if not adapter:
            return _blocked(runtime_report, ["DIRECT_READY_WITHOUT_ADAPTER"])
        if _clean(entry.get("publication_mode")).lower() not in publishing_adapters.DIRECT_MODES:
            return _blocked(runtime_report, ["DIRECT_READY_WITH_UNAPPROVED_MODE"])
        disposition = "DIRECT_READY"
    elif gate_decision == "BLOCKED_MISSING_CREDENTIALS":
        disposition = "BLOCKED_MISSING_CREDENTIALS"
    elif gate_decision == "OUTBOX_ONLY" or publication_status == "OUTBOX_READY":
        disposition = "OUTBOX_ONLY"
    else:
        return _blocked(runtime_report, ["UNRECOGNIZED_RUNTIME_GATE_DECISION"])

    logical_outbox = copy.deepcopy(outbox) if outbox is not None else empty_handoff_outbox(
        _clean(runtime_report.get("instance_id")),
        _clean(runtime_report.get("channel_id")),
        platform,
    )
    outbox_blocks = _validate_outbox(logical_outbox, runtime_report)
    if outbox_blocks:
        return _blocked(runtime_report, outbox_blocks)

    payload = _adapter_payload(runtime_report)
    payload_fp = _digest(payload)
    publication_id = _clean(record.get("publication_id"))
    handoff_id = "handoff:" + _digest(
        {
            "instance_id": _clean(runtime_report.get("instance_id")),
            "channel_id": _clean(runtime_report.get("channel_id")),
            "platform": platform,
            "publication_id": publication_id,
            "dedupe_key": _clean(record.get("dedupe_key")),
            "product_fingerprint_sha256": _clean(record.get("product_fingerprint_sha256")),
        }
    )[:24]

    refs_declared, credential_errors = publishing_adapters.credential_reference_names(entry)
    if credential_errors:
        return _blocked(runtime_report, credential_errors)
    missing_refs = sorted(str(value) for value in gate.get("missing_references", []))
    item = {
        "handoff_id": handoff_id,
        "instance_id": _clean(runtime_report.get("instance_id")),
        "channel_id": _clean(runtime_report.get("channel_id")),
        "platform": platform,
        "publication_id": publication_id,
        "story_id": _clean(runtime_report.get("story_id")),
        "product_id": _clean(record.get("product_id")),
        "dispatch_disposition": disposition,
        "adapter": adapter or None,
        "physical_outbox_path": outbox_path,
        "physical_state_path": state_path,
        "credential_reference_names": refs_declared,
        "missing_reference_names": missing_refs,
        "credential_values_included": False,
        "network_dispatch_performed": False,
        "adapter_payload": payload,
        "adapter_payload_fingerprint_sha256": payload_fp,
    }
    item["handoff_fingerprint_sha256"] = _digest(item)

    items = logical_outbox["items"]
    existing = items.get(handoff_id)
    if isinstance(existing, dict):
        if _clean(existing.get("adapter_payload_fingerprint_sha256")) != payload_fp:
            return _blocked(runtime_report, ["HANDOFF_ID_COLLISION"])
        previous_disposition = _clean(existing.get("dispatch_disposition"))
        decision = "DEDUPE_EXISTING_HANDOFF" if previous_disposition == disposition else "UPDATED_HANDOFF_GATE"
    else:
        decision = "REGISTERED_HANDOFF"
    items[handoff_id] = item

    candidate_ledger = copy.deepcopy(ledger)
    ledger_records = candidate_ledger["records"]
    candidate_record = ledger_records[publication_id]
    if disposition == "OUTBOX_ONLY":
        candidate_record["status"] = "OUTBOX_READY"
        candidate_record["state_reason"] = "DISPATCH_BRIDGE_OUTBOX_ONLY"
    elif disposition == "BLOCKED_MISSING_CREDENTIALS":
        candidate_record["status"] = "BLOCKED_AUTH"
        candidate_record["state_reason"] = "MISSING_CREDENTIAL_REFERENCES"
        candidate_record["next_attempt_at"] = None
    else:
        candidate_record["status"] = "READY"
        candidate_record["state_reason"] = "ADAPTER_RUNTIME_GATE_CLEAR"
    candidate_record["dispatch_bridge"] = {
        "handoff_id": handoff_id,
        "dispatch_disposition": disposition,
        "credential_reference_names": refs_declared,
        "missing_reference_names": missing_refs,
        "credential_values_exposed": False,
    }

    commit_bundle = {
        "instance_id": _clean(runtime_report.get("instance_id")),
        "channel_id": _clean(runtime_report.get("channel_id")),
        "platform": platform,
        "handoff_id": handoff_id,
        "ledger": candidate_ledger,
        "outbox": logical_outbox,
        "atomic_persist_required": True,
        "network_dispatch_performed": False,
    }
    bundle_fp = _digest(commit_bundle)

    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(runtime_report.get("instance_id")),
        "channel_id": _clean(runtime_report.get("channel_id")),
        "platform": platform,
        "blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "dispatch_disposition": disposition,
        "publication_status_before_bridge": publication_status,
        "publication_status_after_bridge": candidate_record["status"],
        "runtime_gate": copy.deepcopy(gate),
        "adapter_handoff": {
            "handoff_id": handoff_id,
            "adapter": adapter or None,
            "dispatch_allowed": disposition == "DIRECT_READY",
            "durable_outbox_only": disposition == "OUTBOX_ONLY",
            "blocked_missing_credentials": disposition == "BLOCKED_MISSING_CREDENTIALS",
            "credential_reference_names": refs_declared,
            "missing_reference_names": missing_refs,
            "credential_values_exposed": False,
        },
        "commit_bundle": commit_bundle,
        "bundle_fingerprint_sha256": bundle_fp,
        "guards": {
            "verified_native_product_required": True,
            "channel_state_independent": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_report", type=Path)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--present-ref", action="append", default=[])
    parser.add_argument("--outbox", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = bridge_runtime_handoff(
        _load(args.runtime_report),
        _load(args.registry),
        args.present_ref,
        _load(args.outbox) if args.outbox else None,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
