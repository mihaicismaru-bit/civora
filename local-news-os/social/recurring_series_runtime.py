#!/usr/bin/env python3
"""Durable recurring-series runtime staging for LOCAL NEWS OS social publications.

This bridge turns a Recurring Series Engine decision into one channel-local,
deterministic composition handoff. It does not write social copy, fetch
analytics, read credentials, or dispatch network requests. The selected story
IDs/content hashes remain the only payload until a channel-native compositor
builds the actual recurring product.

Website and social channels remain sibling publications. Each channel owns its
series outbox/state, and a slot already staged cannot be silently replaced with
different source content.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import recurring_series

SCHEMA_VERSION = "1.0"
PENDING_STATUS = "SERIES_COMPOSITION_PENDING"


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _default_outbox(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "items": [],
        "publication_model": "recurring_series_native_composition",
        "zero_paid_dependency": True,
    }


def _default_state(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "occurrences": {},
        "publication_model": "recurring_series_native_composition",
        "zero_paid_dependency": True,
    }


def _container_blocks(
    channel: dict[str, Any],
    outbox: dict[str, Any],
    state: dict[str, Any],
) -> list[str]:
    blocks: list[str] = []
    instance_id = _clean(channel.get("instance_id"))
    channel_id = _clean(channel.get("channel_id"))

    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        blocks.append("OBSERVED_METRICS_POLICY_REQUIRED")

    for name, doc in (("OUTBOX", outbox), ("STATE", state)):
        if _clean(doc.get("instance_id")) != instance_id or not instance_id:
            blocks.append(f"{name}_INSTANCE_MISMATCH")
        if _clean(doc.get("channel_id")) != channel_id or not channel_id:
            blocks.append(f"{name}_CHANNEL_MISMATCH")
        if doc.get("zero_paid_dependency") is not True:
            blocks.append(f"{name}_ZERO_PAID_DEPENDENCY_REQUIRED")

    items = outbox.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        blocks.append("INVALID_SERIES_OUTBOX")
    occurrences = state.get("occurrences")
    if not isinstance(occurrences, dict) or any(not isinstance(value, dict) for value in occurrences.values()):
        blocks.append("INVALID_SERIES_STATE")
    return sorted(set(blocks))


def _stable_occurrence_contract(occurrence: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": _clean(occurrence.get("instance_id")),
        "channel_id": _clean(occurrence.get("channel_id")),
        "series_id": _clean(occurrence.get("series_id")),
        "series_slot_key": _clean(occurrence.get("series_slot_key")),
        "selected_candidate_ids": list(occurrence.get("selected_candidate_ids") or []),
        "selected_story_ids": list(occurrence.get("selected_story_ids") or []),
        "selected_content_hashes": [str(value).lower() for value in occurrence.get("selected_content_hashes") or []],
        "topic_ids": list(occurrence.get("topic_ids") or []),
        "preferred_formats": list(occurrence.get("preferred_formats") or []),
        "replay_policy": _clean(occurrence.get("replay_policy")),
    }


def _stage_item(occurrence: dict[str, Any], series_decision: dict[str, Any]) -> dict[str, Any]:
    contract = _stable_occurrence_contract(occurrence)
    composition_fingerprint = _digest(contract)
    execution_id = "series-execution:" + _digest({
        "slot": contract["series_slot_key"],
        "composition_fingerprint_sha256": composition_fingerprint,
    })[:24]
    return {
        "series_execution_id": execution_id,
        "occurrence_id": occurrence.get("occurrence_id"),
        "instance_id": contract["instance_id"],
        "channel_id": contract["channel_id"],
        "series_id": contract["series_id"],
        "series_slot_key": contract["series_slot_key"],
        "status": PENDING_STATUS,
        "publication_mode": "channel_native_series_composition_pending",
        "selected_candidate_ids": contract["selected_candidate_ids"],
        "selected_story_ids": contract["selected_story_ids"],
        "selected_content_hashes": contract["selected_content_hashes"],
        "topic_ids": contract["topic_ids"],
        "native_format_candidates": contract["preferred_formats"],
        "replay_policy": contract["replay_policy"],
        "composition_fingerprint_sha256": composition_fingerprint,
        "series_decision_fingerprint_sha256": series_decision.get("decision_fingerprint_sha256"),
        "native_composition_required": True,
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "source_story_text_materialized": False,
        "predictive_analytics_used": False,
        "credential_values_read": False,
        "network_dispatch_performed": False,
        "editorial_gates_weakened": False,
        "zero_paid_dependency": True,
    }


def _result(
    *,
    channel: dict[str, Any],
    series_decision: dict[str, Any] | None,
    outbox: dict[str, Any],
    state: dict[str, Any],
    blocked: bool,
    disposition: str,
    staged: bool = False,
    idempotent: bool = False,
    hard_blocks: list[str] | None = None,
    series_blocks: list[str] | None = None,
    staged_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "blocked": blocked,
        "disposition": disposition,
        "staged": staged,
        "idempotent": idempotent,
        "hard_blocks": sorted(set(hard_blocks or [])),
        "series_blocks": sorted(set(series_blocks or [])),
        "series_decision": series_decision,
        "staged_item": staged_item,
        "outbox": outbox,
        "state": state,
        "handoff": {
            "native_series_composition_required": staged or idempotent,
            "adapter_dispatch_eligible": False,
            "network_dispatch_performed": False,
        },
        "guards": {
            "source_story_ids_only_until_composition": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "predictive_analytics_used": False,
            "credential_values_read": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }
    payload["runtime_fingerprint_sha256"] = _digest({
        "instance_id": payload["instance_id"],
        "channel_id": payload["channel_id"],
        "disposition": disposition,
        "series_decision_fingerprint_sha256": (series_decision or {}).get("decision_fingerprint_sha256"),
        "staged_item_fingerprint_sha256": (staged_item or {}).get("composition_fingerprint_sha256"),
        "hard_blocks": payload["hard_blocks"],
        "series_blocks": payload["series_blocks"],
    })
    return payload


def stage_due_occurrence(
    channel: dict[str, Any],
    registry: dict[str, Any],
    candidate_pool: dict[str, Any],
    history: dict[str, Any],
    *,
    now: str,
    outbox: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate and durably stage one due recurring-series occurrence.

    The function is side-effect free. Callers persist the returned ``outbox`` and
    ``state`` using their existing conflict-safe persistence layer. A staged slot
    is idempotent for identical source content and fail-closed if the slot is
    later presented with a different composition fingerprint.
    """
    required = (channel, registry, candidate_pool, history)
    if not all(isinstance(value, dict) for value in required):
        raise TypeError("channel, registry, candidate_pool and history must be mappings")
    if outbox is not None and not isinstance(outbox, dict):
        raise TypeError("outbox must be a mapping when provided")
    if state is not None and not isinstance(state, dict):
        raise TypeError("state must be a mapping when provided")
    if not _clean(now):
        raise ValueError("now is required")

    outbox_doc = copy.deepcopy(outbox) if outbox is not None else _default_outbox(channel)
    state_doc = copy.deepcopy(state) if state is not None else _default_state(channel)
    container_blocks = _container_blocks(channel, outbox_doc, state_doc)
    if container_blocks:
        return _result(
            channel=channel,
            series_decision=None,
            outbox=outbox_doc,
            state=state_doc,
            blocked=True,
            disposition="BLOCKED_RUNTIME_STATE",
            hard_blocks=container_blocks,
        )

    decision = recurring_series.evaluate_series(channel, registry, candidate_pool, history, now=now)
    if decision.get("hard_blocks"):
        return _result(
            channel=channel,
            series_decision=decision,
            outbox=outbox_doc,
            state=state_doc,
            blocked=True,
            disposition="BLOCKED_SERIES_ENGINE",
            hard_blocks=[str(value) for value in decision.get("hard_blocks", [])],
            series_blocks=[str(value) for value in decision.get("series_blocks", [])],
        )
    if decision.get("decision") != "SERIES_READY" or not isinstance(decision.get("occurrence"), dict):
        return _result(
            channel=channel,
            series_decision=decision,
            outbox=outbox_doc,
            state=state_doc,
            blocked=False,
            disposition=str(decision.get("decision") or "HOLD_SERIES"),
            series_blocks=[str(value) for value in decision.get("series_blocks", [])],
        )

    occurrence = decision["occurrence"]
    item = _stage_item(occurrence, decision)
    slot_key = _clean(item.get("series_slot_key"))
    if not slot_key:
        return _result(
            channel=channel,
            series_decision=decision,
            outbox=outbox_doc,
            state=state_doc,
            blocked=True,
            disposition="BLOCKED_SERIES_OCCURRENCE",
            hard_blocks=["MISSING_SERIES_SLOT_KEY"],
        )

    items = outbox_doc["items"]
    occurrences = state_doc["occurrences"]
    matching_items = [row for row in items if _clean(row.get("series_slot_key")) == slot_key]
    state_record = occurrences.get(slot_key)

    if len(matching_items) > 1:
        return _result(
            channel=channel,
            series_decision=decision,
            outbox=outbox_doc,
            state=state_doc,
            blocked=True,
            disposition="BLOCKED_SERIES_STATE_DIVERGENCE",
            hard_blocks=["DUPLICATE_STAGED_SERIES_SLOT"],
        )
    if bool(matching_items) != isinstance(state_record, dict):
        return _result(
            channel=channel,
            series_decision=decision,
            outbox=outbox_doc,
            state=state_doc,
            blocked=True,
            disposition="BLOCKED_SERIES_STATE_DIVERGENCE",
            hard_blocks=["SERIES_STATE_OUTBOX_DIVERGENCE"],
        )

    if matching_items:
        existing = matching_items[0]
        existing_fp = _clean(existing.get("composition_fingerprint_sha256"))
        state_fp = _clean(state_record.get("composition_fingerprint_sha256")) if isinstance(state_record, dict) else ""
        new_fp = _clean(item.get("composition_fingerprint_sha256"))
        if not existing_fp or existing_fp != state_fp:
            return _result(
                channel=channel,
                series_decision=decision,
                outbox=outbox_doc,
                state=state_doc,
                blocked=True,
                disposition="BLOCKED_SERIES_STATE_DIVERGENCE",
                hard_blocks=["SERIES_COMPOSITION_FINGERPRINT_DIVERGENCE"],
            )
        if existing_fp == new_fp:
            return _result(
                channel=channel,
                series_decision=decision,
                outbox=outbox_doc,
                state=state_doc,
                blocked=False,
                disposition="IDEMPOTENT_ALREADY_STAGED",
                staged=False,
                idempotent=True,
                staged_item=existing,
            )
        return _result(
            channel=channel,
            series_decision=decision,
            outbox=outbox_doc,
            state=state_doc,
            blocked=False,
            disposition="HOLD_STAGED_SLOT_CONFLICT",
            series_blocks=["SERIES_SLOT_STAGED_WITH_DIFFERENT_CONTENT"],
            staged_item=existing,
        )

    items.append(item)
    occurrences[slot_key] = {
        "series_execution_id": item["series_execution_id"],
        "occurrence_id": item.get("occurrence_id"),
        "series_id": item["series_id"],
        "series_slot_key": slot_key,
        "status": PENDING_STATUS,
        "composition_fingerprint_sha256": item["composition_fingerprint_sha256"],
        "selected_story_ids": list(item["selected_story_ids"]),
        "selected_content_hashes": list(item["selected_content_hashes"]),
        "network_dispatch_performed": False,
        "zero_paid_dependency": True,
    }
    return _result(
        channel=channel,
        series_decision=decision,
        outbox=outbox_doc,
        state=state_doc,
        blocked=False,
        disposition=PENDING_STATUS,
        staged=True,
        staged_item=item,
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("series_registry", type=Path)
    parser.add_argument("candidate_pool", type=Path)
    parser.add_argument("history", type=Path)
    parser.add_argument("--now", required=True, help="timezone-aware ISO-8601 instant")
    parser.add_argument("--outbox", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = stage_due_occurrence(
        _load(args.channel),
        _load(args.series_registry),
        _load(args.candidate_pool),
        _load(args.history),
        now=args.now,
        outbox=_load(args.outbox) if args.outbox else None,
        state=_load(args.state) if args.state else None,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
