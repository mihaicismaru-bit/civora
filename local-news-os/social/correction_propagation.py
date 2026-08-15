#!/usr/bin/env python3
"""Fail-closed correction propagation for LOCAL NEWS OS social publications.

The engine consumes an explicitly verified correction object plus durable
publication ledgers. It never writes social copy and never dispatches network
requests. Instead it marks stale unpublished products as superseded and emits
channel-local correction actions for publications already confirmed remote.

Website and social channels remain sibling publications fed from the same
verified fact kernel. Every correction action requires re-atomization and native
re-formatting for its destination channel; prior copy cannot be reused as the
normal path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

UNPUBLISHED_STATUSES = {
    "HOLD_TIMING",
    "AWAITING_APPROVAL",
    "OUTBOX_READY",
    "READY",
    "RETRY_WAIT",
    "RETRY_READY",
    "BLOCKED_AUTH",
    "FAILED_TERMINAL",
}
IN_FLIGHT_STATUSES = {"PUBLISHING"}
PUBLISHED_STATUSES = {"PUBLISHED"}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({_clean(item) for item in value if _clean(item)})


def _fact_fingerprint(correction: dict[str, Any]) -> str:
    for key in (
        "fact_kernel_sha256",
        "fact_kernel_fingerprint_sha256",
        "correction_fact_fingerprint_sha256",
    ):
        value = _clean(correction.get(key)).lower()
        if _is_sha256(value):
            return value
    return ""


def _corrected_story_ids(correction: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "corrects_story_ids",
        "correction_of_story_ids",
        "supersedes_story_ids",
    ):
        values.extend(_string_list(correction.get(key)))
    single = _clean(correction.get("corrects_story_id")) or _clean(correction.get("correction_of_story_id"))
    if single:
        values.append(single)
    return sorted(set(values))


def _corrected_publication_ids(correction: dict[str, Any]) -> list[str]:
    values = _string_list(correction.get("corrects_publication_ids"))
    single = _clean(correction.get("corrects_publication_id"))
    if single:
        values.append(single)
    return sorted(set(values))


def _verified_correction(correction: dict[str, Any]) -> bool:
    lifecycle = _clean(correction.get("lifecycle")).lower()
    correction_flag = correction.get("correction") is True or lifecycle == "correction"
    if not correction_flag:
        return False
    if correction.get("verified") is not True:
        return False

    gate = correction.get("editorial_gate")
    if isinstance(gate, dict):
        gate = gate.get("status")
    gate_text = _clean(gate).upper()
    return gate_text in {"PASS", "APPROVED", "GO"}


def _correction_blocks(correction: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if not isinstance(correction, dict):
        return ["CORRECTION_NOT_MAPPING"]
    if not _clean(correction.get("instance_id")):
        blocks.append("MISSING_INSTANCE_ID")
    if not _clean(correction.get("story_id")):
        blocks.append("MISSING_CORRECTION_STORY_ID")
    if not _verified_correction(correction):
        blocks.append("CORRECTION_NOT_VERIFIED")
    if not _fact_fingerprint(correction):
        blocks.append("MISSING_FACT_KERNEL_FINGERPRINT")
    if not _corrected_story_ids(correction) and not _corrected_publication_ids(correction):
        blocks.append("MISSING_EXPLICIT_CORRECTION_TARGET")
    if correction.get("zero_paid_dependency") is False:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    return sorted(set(blocks))


def _record_identity_valid(record: dict[str, Any], ledger: dict[str, Any]) -> bool:
    return (
        _clean(record.get("instance_id")) == _clean(ledger.get("instance_id"))
        and _clean(record.get("channel_id")) == _clean(ledger.get("channel_id"))
        and _clean(record.get("platform")).lower() == _clean(ledger.get("platform")).lower()
        and bool(_clean(record.get("publication_id")))
        and bool(_clean(record.get("story_id")))
    )


def _affected(record: dict[str, Any], story_ids: set[str], publication_ids: set[str]) -> bool:
    return (
        _clean(record.get("story_id")) in story_ids
        or _clean(record.get("publication_id")) in publication_ids
    )


def _action_id(correction_story_id: str, record: dict[str, Any], action: str) -> str:
    payload = {
        "correction_story_id": correction_story_id,
        "publication_id": _clean(record.get("publication_id")),
        "channel_id": _clean(record.get("channel_id")),
        "action": action,
    }
    return "correction-action:" + _digest(payload)[:24]


def _native_regeneration(correction: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": True,
        "source": "VERIFIED_FACT_KERNEL",
        "fact_kernel_sha256": _fact_fingerprint(correction),
        "correction_story_id": _clean(correction.get("story_id")),
        "pipeline": [
            "CONTENT_ATOMIZER",
            "CHANNEL_FIT",
            "HOOK_ENGINE",
            "FORMAT_ENGINE",
            "VISUAL_ROUTER_IF_REQUIRED",
        ],
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "invented_claims_allowed": False,
    }


def _base_action(correction: dict[str, Any], record: dict[str, Any], action: str) -> dict[str, Any]:
    return {
        "action_id": _action_id(_clean(correction.get("story_id")), record, action),
        "action": action,
        "instance_id": _clean(record.get("instance_id")),
        "channel_id": _clean(record.get("channel_id")),
        "platform": _clean(record.get("platform")).lower(),
        "affected_story_id": _clean(record.get("story_id")),
        "affected_publication_id": _clean(record.get("publication_id")),
        "remote_publication_id": _clean(record.get("remote_publication_id")) or None,
        "correction_story_id": _clean(correction.get("story_id")),
        "native_regeneration": _native_regeneration(correction),
        "guards": {
            "editorial_gates_weakened": False,
            "prior_copy_reused": False,
            "analytics_used": False,
            "zero_paid_dependency": True,
        },
    }


def _already_propagated(record: dict[str, Any], correction_story_id: str) -> bool:
    history = record.get("correction_history")
    if not isinstance(history, list):
        return False
    return any(
        isinstance(item, dict)
        and _clean(item.get("correction_story_id")) == correction_story_id
        and _clean(item.get("action_id"))
        for item in history
    )


def _append_history(record: dict[str, Any], action: dict[str, Any], state: str) -> None:
    history = record.setdefault("correction_history", [])
    if not isinstance(history, list):
        history = []
        record["correction_history"] = history
    if any(
        isinstance(item, dict) and _clean(item.get("action_id")) == _clean(action.get("action_id"))
        for item in history
    ):
        return
    history.append(
        {
            "action_id": _clean(action.get("action_id")),
            "correction_story_id": _clean(action.get("correction_story_id")),
            "state": state,
        }
    )


def propagate_correction(
    correction: dict[str, Any],
    ledgers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic correction plan and updated channel-local ledgers.

    Foreign-instance ledgers are ignored rather than mutated. Unpublished stale
    records become ``SUPERSEDED_CORRECTION`` and therefore cannot be dispatched by
    the publication state engine. Confirmed published records stay ``PUBLISHED``
    but gain a durable ``CORRECTION_REQUIRED`` marker plus a native regeneration
    action for their own channel.
    """
    if not isinstance(ledgers, list) or any(not isinstance(item, dict) for item in ledgers):
        raise TypeError("ledgers must be a list of mappings")

    blocks = _correction_blocks(correction)
    original_ledgers = copy.deepcopy(ledgers)
    if blocks:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": True,
            "partial": False,
            "hard_blocks": blocks,
            "instance_id": _clean(correction.get("instance_id")) if isinstance(correction, dict) else "",
            "correction_story_id": _clean(correction.get("story_id")) if isinstance(correction, dict) else "",
            "actions": [],
            "unresolved": [],
            "ignored_foreign_ledgers": [],
            "updated_ledgers": original_ledgers,
            "guards": {
                "instance_isolation": True,
                "native_regeneration_required": True,
                "verbatim_cross_platform_reuse_allowed": False,
                "analytics_used": False,
                "zero_paid_dependency": True,
            },
        }

    instance_id = _clean(correction.get("instance_id"))
    correction_story_id = _clean(correction.get("story_id"))
    story_ids = set(_corrected_story_ids(correction))
    publication_ids = set(_corrected_publication_ids(correction))
    updated = copy.deepcopy(ledgers)
    actions: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    ignored_foreign: list[dict[str, str]] = []
    affected_count = 0

    for ledger in updated:
        ledger_instance = _clean(ledger.get("instance_id"))
        if ledger_instance != instance_id:
            ignored_foreign.append(
                {
                    "instance_id": ledger_instance,
                    "channel_id": _clean(ledger.get("channel_id")),
                }
            )
            continue

        records = ledger.get("records")
        if not isinstance(records, dict):
            unresolved.append(
                {
                    "channel_id": _clean(ledger.get("channel_id")),
                    "reason": "LEDGER_RECORDS_INVALID",
                }
            )
            continue

        for key in sorted(records):
            record = records[key]
            if not isinstance(record, dict) or not _affected(record, story_ids, publication_ids):
                continue
            affected_count += 1

            if not _record_identity_valid(record, ledger):
                unresolved.append(
                    {
                        "channel_id": _clean(ledger.get("channel_id")),
                        "publication_id": _clean(record.get("publication_id")) if isinstance(record, dict) else "",
                        "reason": "RECORD_IDENTITY_MISMATCH",
                    }
                )
                continue

            if _already_propagated(record, correction_story_id):
                actions.append(
                    {
                        **_base_action(correction, record, "ALREADY_PROPAGATED"),
                        "decision": "IDEMPOTENT_NOOP",
                    }
                )
                continue

            status = _clean(record.get("status")).upper()
            if status in UNPUBLISHED_STATUSES:
                action = _base_action(correction, record, "SUPERSEDE_UNPUBLISHED")
                action["decision"] = "SUPERSEDED_BEFORE_PUBLICATION"
                record["status"] = "SUPERSEDED_CORRECTION"
                record["state_reason"] = "CORRECTION_SUPERSEDED_BEFORE_PUBLICATION"
                record["next_attempt_at"] = None
                record["superseded_by_story_id"] = correction_story_id
                record["correction_state"] = "SUPERSEDED_BEFORE_PUBLICATION"
                _append_history(record, action, "SUPERSEDED_BEFORE_PUBLICATION")
                actions.append(action)
                continue

            if status in PUBLISHED_STATUSES:
                if not _clean(record.get("remote_publication_id")):
                    unresolved.append(
                        {
                            "channel_id": _clean(record.get("channel_id")),
                            "publication_id": _clean(record.get("publication_id")),
                            "reason": "PUBLISHED_WITHOUT_REMOTE_ID",
                        }
                    )
                    continue
                action = _base_action(correction, record, "CORRECT_PUBLISHED_NATIVE")
                action["decision"] = "ADAPTER_CORRECTION_REQUIRED"
                action["adapter_instruction"] = "EDIT_WHEN_SAFE_AND_SUPPORTED_ELSE_PUBLISH_NATIVE_CORRECTION"
                record["correction_state"] = "CORRECTION_REQUIRED"
                record["correction_story_id"] = correction_story_id
                record["correction_action_id"] = action["action_id"]
                _append_history(record, action, "CORRECTION_REQUIRED")
                actions.append(action)
                continue

            if status in IN_FLIGHT_STATUSES:
                action = _base_action(correction, record, "RECONCILE_IN_FLIGHT")
                action["decision"] = "REMOTE_RECONCILIATION_REQUIRED"
                record["correction_state"] = "RECONCILIATION_REQUIRED"
                record["correction_story_id"] = correction_story_id
                _append_history(record, action, "RECONCILIATION_REQUIRED")
                actions.append(action)
                continue

            if status == "SUPERSEDED_CORRECTION":
                action = _base_action(correction, record, "ALREADY_PROPAGATED")
                action["decision"] = "IDEMPOTENT_NOOP"
                actions.append(action)
                continue

            unresolved.append(
                {
                    "channel_id": _clean(record.get("channel_id")),
                    "publication_id": _clean(record.get("publication_id")),
                    "reason": "UNKNOWN_PUBLICATION_STATUS",
                    "status": status,
                }
            )

    if affected_count == 0:
        unresolved.append({"reason": "NO_AFFECTED_PUBLICATIONS_FOUND"})

    actions.sort(key=lambda item: (_clean(item.get("channel_id")), _clean(item.get("affected_publication_id")), _clean(item.get("action"))))
    unresolved.sort(key=_canonical)
    ignored_foreign.sort(key=_canonical)
    actionable = [item for item in actions if item.get("action") != "ALREADY_PROPAGATED"]
    fully_blocked = affected_count > 0 and not actionable and bool(unresolved)

    result = {
        "schema_version": SCHEMA_VERSION,
        "blocked": fully_blocked,
        "partial": bool(unresolved) and bool(actionable),
        "hard_blocks": sorted({item.get("reason", "") for item in unresolved if item.get("reason")}) if fully_blocked else [],
        "instance_id": instance_id,
        "correction_story_id": correction_story_id,
        "corrected_story_ids": sorted(story_ids),
        "corrected_publication_ids": sorted(publication_ids),
        "fact_kernel_sha256": _fact_fingerprint(correction),
        "affected_count": affected_count,
        "actions": actions,
        "unresolved": unresolved,
        "ignored_foreign_ledgers": ignored_foreign,
        "updated_ledgers": updated,
        "guards": {
            "instance_isolation": True,
            "native_regeneration_required": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "analytics_used": False,
            "zero_paid_dependency": True,
        },
    }
    fingerprint_payload = dict(result)
    fingerprint_payload.pop("updated_ledgers", None)
    result["propagation_fingerprint_sha256"] = _digest(fingerprint_payload)
    return result


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan fail-closed social correction propagation")
    parser.add_argument("correction", help="Verified correction JSON")
    parser.add_argument("ledgers", nargs="+", help="Publication ledger JSON files")
    parser.add_argument("--output", help="Optional plan JSON output path")
    args = parser.parse_args()

    correction = _read_json(args.correction)
    ledgers = [_read_json(path) for path in args.ledgers]
    result = propagate_correction(correction, ledgers)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 2 if result.get("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
