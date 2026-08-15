#!/usr/bin/env python3
"""Durable publication state, retry and dedupe engine for LOCAL NEWS OS.

This module sits after the verified/native social pipeline. It owns no network
credentials and performs no publication itself. It turns an eligible native
product into channel-local durable state, prevents duplicate sends, and records
adapter outcomes with deterministic retry policy.

Website and social channels remain sibling publications. State is isolated by
``instance_id`` + ``channel_id``; a publication in one channel never suppresses
another channel's independently formatted product.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

TRANSIENT_HTTP = {408, 409, 425, 429}
AUTH_HTTP = {401, 403}
TRANSIENT_ERRORS = {
    "network",
    "network_error",
    "timeout",
    "rate_limit",
    "rate_limited",
    "server",
    "server_error",
    "transient",
}
PREDICTIVE_FIELDS = {
    "predicted_views",
    "predicted_reach",
    "predicted_engagement",
    "predicted_ctr",
    "predicted_shares",
    "predicted_saves",
    "virality_probability",
    "expected_views",
    "expected_reach",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    text = _clean(value)
    if not text:
        raise ValueError("timestamp is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint_valid(product: dict[str, Any]) -> bool:
    supplied = _clean(product.get("product_fingerprint_sha256"))
    if len(supplied) != 64:
        return False
    payload = dict(product)
    payload.pop("product_fingerprint_sha256", None)
    return supplied == _digest(payload)


def _decision_fingerprint_valid(decision: dict[str, Any]) -> bool:
    supplied = _clean(decision.get("decision_fingerprint_sha256"))
    if len(supplied) != 64:
        return False
    payload = dict(decision)
    payload.pop("decision_fingerprint_sha256", None)
    return supplied == _digest(payload)


def empty_ledger(instance_id: str, channel_id: str, platform: str) -> dict[str, Any]:
    """Create an empty channel-local ledger."""
    instance_id = _clean(instance_id)
    channel_id = _clean(channel_id)
    platform = _clean(platform).lower()
    if not instance_id or not channel_id or not platform:
        raise ValueError("instance_id, channel_id and platform are required")
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "channel_id": channel_id,
        "platform": platform,
        "records": {},
        "guards": {
            "instance_isolation": True,
            "channel_state_independent": True,
            "zero_paid_dependency": True,
        },
    }


def _validate_ledger(ledger: dict[str, Any], channel: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(ledger.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("LEDGER_SCHEMA_VERSION")
    if _clean(ledger.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("LEDGER_INSTANCE_MISMATCH")
    if _clean(ledger.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("LEDGER_CHANNEL_MISMATCH")
    if _clean(ledger.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("LEDGER_PLATFORM_MISMATCH")
    if not isinstance(ledger.get("records"), dict):
        blocks.append("LEDGER_RECORDS_INVALID")
    return blocks


def _identity_blocks(
    format_result: dict[str, Any],
    virality: dict[str, Any],
    channel: dict[str, Any],
) -> list[str]:
    blocks: list[str] = []
    instance_id = _clean(channel.get("instance_id"))
    channel_id = _clean(channel.get("channel_id"))
    platform = _clean(channel.get("platform")).lower()

    if not instance_id:
        blocks.append("MISSING_INSTANCE_ID")
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    if not platform:
        blocks.append("MISSING_PLATFORM")

    for obj in (format_result, virality):
        obj_instance = _clean(obj.get("instance_id"))
        obj_channel = _clean(obj.get("channel_id"))
        obj_platform = _clean(obj.get("platform")).lower()
        if obj_instance and instance_id and obj_instance != instance_id:
            blocks.append("INSTANCE_MISMATCH")
        if obj_channel and channel_id and obj_channel != channel_id:
            blocks.append("CHANNEL_MISMATCH")
        if obj_platform and platform and obj_platform != platform:
            blocks.append("PLATFORM_MISMATCH")

    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    story_id = _clean(format_result.get("story_id"))
    if not story_id:
        blocks.append("MISSING_STORY_ID")
    if product:
        if _clean(product.get("story_id")) and _clean(product.get("story_id")) != story_id:
            blocks.append("PRODUCT_STORY_MISMATCH")
        if _clean(product.get("channel_id")) and _clean(product.get("channel_id")) != channel_id:
            blocks.append("PRODUCT_CHANNEL_MISMATCH")
        if _clean(product.get("instance_id")) and _clean(product.get("instance_id")) != instance_id:
            blocks.append("PRODUCT_INSTANCE_MISMATCH")
        if _clean(product.get("platform")).lower() and _clean(product.get("platform")).lower() != platform:
            blocks.append("PRODUCT_PLATFORM_MISMATCH")
    virality_story = _clean(virality.get("story_id"))
    if virality_story and story_id and virality_story != story_id:
        blocks.append("VIRALITY_STORY_MISMATCH")
    if _clean(virality.get("product_id")) and product and _clean(virality.get("product_id")) != _clean(product.get("product_id")):
        blocks.append("VIRALITY_PRODUCT_MISMATCH")
    return sorted(set(blocks))


def _safety_blocks(
    format_result: dict[str, Any],
    virality: dict[str, Any],
    channel: dict[str, Any],
) -> list[str]:
    blocks: list[str] = []
    status = _clean(channel.get("status"))
    if status not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")
    if format_result.get("blocked") is True:
        blocks.append("FORMAT_BLOCKED")
    if virality.get("blocked") is True:
        blocks.append("VIRALITY_BLOCKED")
    if virality.get("hard_blocks"):
        blocks.append("VIRALITY_HARD_BLOCKS")

    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    if not product:
        blocks.append("MISSING_NATIVE_PRODUCT")
        return sorted(set(blocks))
    if _clean(product.get("format_status")) != "FORMAT_READY":
        blocks.append("FORMAT_NOT_READY")
    if _clean(product.get("cross_post_policy")) != "NATIVE_PRODUCT_ONLY":
        blocks.append("INVALID_CROSS_POST_POLICY")
    if product.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
    if product.get("invented_claims_allowed") is not False:
        blocks.append("INVENTED_CLAIMS_POLICY")
    if product.get("analytics_used") is not False:
        blocks.append("ANALYTICS_POLICY")
    if not _clean(product.get("product_id")):
        blocks.append("MISSING_PRODUCT_ID")
    if not _fingerprint_valid(product):
        blocks.append("PRODUCT_FINGERPRINT_INVALID")
    if not _decision_fingerprint_valid(virality):
        blocks.append("VIRALITY_FINGERPRINT_INVALID")

    action = _clean(virality.get("publication_action"))
    if action not in {
        "PRIORITIZE",
        "ELIGIBLE",
        "ELIGIBLE_LOW_PRIORITY",
        "OUTBOX_ONLY",
        "HOLD_TIMING",
    }:
        blocks.append("INVALID_PUBLICATION_ACTION")
    guards = virality.get("guards") if isinstance(virality.get("guards"), dict) else {}
    if guards.get("editorial_gates_weakened") is not False:
        blocks.append("EDITORIAL_GATES_WEAKENED")
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    return sorted(set(blocks))


def _publication_identity(format_result: dict[str, Any], channel: dict[str, Any]) -> dict[str, str]:
    product = format_result["product"]
    payload = {
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "story_id": _clean(format_result.get("story_id")),
        "product_id": _clean(product.get("product_id")),
        "product_fingerprint_sha256": _clean(product.get("product_fingerprint_sha256")),
    }
    key = _digest(payload)
    return {
        **payload,
        "dedupe_key": key,
        "publication_id": "publication:" + key[:24],
    }


def _desired_status(
    channel: dict[str, Any],
    product: dict[str, Any],
    virality: dict[str, Any],
    human_approved: bool,
) -> str:
    action = _clean(virality.get("publication_action"))
    if action == "HOLD_TIMING":
        return "HOLD_TIMING"
    approval = product.get("approval") if isinstance(product.get("approval"), dict) else {}
    if approval.get("human_review_required_before_publish") is True and human_approved is not True:
        return "AWAITING_APPROVAL"
    if _clean(channel.get("status")) == "outbox_only" or action == "OUTBOX_ONLY":
        return "OUTBOX_READY"
    return "READY"


def prepare_publication(
    format_result: dict[str, Any],
    virality: dict[str, Any],
    channel: dict[str, Any],
    ledger: dict[str, Any] | None = None,
    *,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Register one native product exactly once in its channel-local ledger.

    The same product may be prepared repeatedly: the dedupe key is stable and the
    existing record is returned. A HOLD or approval-waiting record can be
    promoted when a later eligible decision/approval arrives.
    """
    if not all(isinstance(value, dict) for value in (format_result, virality, channel)):
        raise TypeError("format_result, virality and channel must be mappings")
    if ledger is None:
        ledger = empty_ledger(
            _clean(channel.get("instance_id")),
            _clean(channel.get("channel_id")),
            _clean(channel.get("platform")),
        )
    if not isinstance(ledger, dict):
        raise TypeError("ledger must be a mapping")

    candidate = copy.deepcopy(ledger)
    blocks = _validate_ledger(candidate, channel)
    blocks.extend(_identity_blocks(format_result, virality, channel))
    blocks.extend(_safety_blocks(format_result, virality, channel))
    blocks = sorted(set(blocks))
    if blocks:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": True,
            "hard_blocks": blocks,
            "decision": "BLOCKED",
            "record": None,
            "ledger": candidate,
        }

    identity = _publication_identity(format_result, channel)
    product = format_result["product"]
    desired = _desired_status(channel, product, virality, human_approved)
    records = candidate["records"]
    existing = records.get(identity["publication_id"])
    if isinstance(existing, dict):
        status = _clean(existing.get("status"))
        if _clean(existing.get("dedupe_key")) != identity["dedupe_key"]:
            return {
                "schema_version": SCHEMA_VERSION,
                "blocked": True,
                "hard_blocks": ["PUBLICATION_ID_COLLISION"],
                "decision": "BLOCKED",
                "record": None,
                "ledger": candidate,
            }
        if status == "PUBLISHED":
            decision = "DEDUPE_ALREADY_PUBLISHED"
        elif status in {"READY", "OUTBOX_READY", "PUBLISHING", "RETRY_WAIT"}:
            if status == "OUTBOX_READY" and desired == "READY":
                existing["status"] = "READY"
                existing["state_reason"] = "CHANNEL_NOW_PUBLISHABLE"
                decision = "PROMOTED_READY"
            else:
                decision = "DEDUPE_EXISTING"
        elif status in {"HOLD_TIMING", "AWAITING_APPROVAL", "BLOCKED_AUTH"} and desired in {"READY", "OUTBOX_READY"}:
            existing["status"] = desired
            existing["state_reason"] = "UPSTREAM_GATE_NOW_CLEAR"
            existing["human_approved"] = human_approved is True or existing.get("human_approved") is True
            existing["virality_decision_fingerprint_sha256"] = _clean(virality.get("decision_fingerprint_sha256"))
            decision = "PROMOTED_" + desired
        elif status == "FAILED_TERMINAL":
            decision = "TERMINAL_FAILURE_REQUIRES_NEW_PRODUCT"
        else:
            decision = "DEDUPE_EXISTING"
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": decision,
            "record": copy.deepcopy(existing),
            "ledger": candidate,
        }

    ignored_predictive = sorted(key for key in PREDICTIVE_FIELDS if key in virality)
    record = {
        "publication_id": identity["publication_id"],
        "dedupe_key": identity["dedupe_key"],
        "instance_id": identity["instance_id"],
        "channel_id": identity["channel_id"],
        "platform": identity["platform"],
        "story_id": identity["story_id"],
        "product_id": identity["product_id"],
        "product_fingerprint_sha256": identity["product_fingerprint_sha256"],
        "virality_decision_fingerprint_sha256": _clean(virality.get("decision_fingerprint_sha256")),
        "status": desired,
        "state_reason": _clean(virality.get("publication_action")),
        "attempt_count": 0,
        "attempts": [],
        "remote_publication_id": None,
        "next_attempt_at": None,
        "human_approved": human_approved is True,
        "correction": product.get("correction") is True,
        "analytics": {
            "predictive_analytics_used": False,
            "observed_metrics_used_for_state": False,
            "ignored_predictive_fields": ignored_predictive,
        },
        "guards": {
            "native_product_only": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "editorial_gates_weakened": False,
            "zero_paid_dependency": True,
        },
    }
    records[identity["publication_id"]] = record
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": "REGISTERED_" + desired,
        "record": copy.deepcopy(record),
        "ledger": candidate,
    }


def classify_failure(http_status: int | None = None, error_class: str | None = None) -> str:
    """Classify adapter failure without inspecting secrets or provider payloads."""
    error = _clean(error_class).lower()
    if http_status in AUTH_HTTP or error in {"auth", "authentication", "authorization", "credential"}:
        return "AUTH"
    if http_status in TRANSIENT_HTTP or (isinstance(http_status, int) and 500 <= http_status <= 599):
        return "TRANSIENT"
    if error in TRANSIENT_ERRORS:
        return "TRANSIENT"
    return "PERMANENT"


def apply_attempt(
    ledger: dict[str, Any],
    publication_id: str,
    attempted_at: str,
    *,
    success: bool,
    remote_publication_id: str | None = None,
    http_status: int | None = None,
    error_class: str | None = None,
    error_code: str | None = None,
    retry_after_seconds: int | None = None,
    max_attempts: int = 5,
    base_delay_seconds: int = 60,
    max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """Record one adapter attempt and transition durable state.

    Retry timing is deterministic exponential backoff. Server-provided
    ``retry_after_seconds`` may extend the delay but is bounded to 24 hours.
    """
    if not isinstance(ledger, dict):
        raise TypeError("ledger must be a mapping")
    if max_attempts < 1 or base_delay_seconds < 1 or max_delay_seconds < base_delay_seconds:
        raise ValueError("invalid retry policy")
    when = _parse_time(attempted_at)
    candidate = copy.deepcopy(ledger)
    records = candidate.get("records")
    if not isinstance(records, dict) or publication_id not in records or not isinstance(records[publication_id], dict):
        return {
            "blocked": True,
            "hard_blocks": ["UNKNOWN_PUBLICATION_ID"],
            "decision": "BLOCKED",
            "record": None,
            "ledger": candidate,
        }
    record = records[publication_id]
    if _clean(record.get("status")) not in {"READY", "RETRY_READY"}:
        return {
            "blocked": True,
            "hard_blocks": ["PUBLICATION_NOT_DISPATCHABLE"],
            "decision": "BLOCKED",
            "record": copy.deepcopy(record),
            "ledger": candidate,
        }

    attempt_no = int(record.get("attempt_count", 0) or 0) + 1
    attempt = {
        "attempt": attempt_no,
        "attempted_at": _iso(when),
        "success": success is True,
        "http_status": http_status,
        "error_class": _clean(error_class) or None,
        "error_code": _clean(error_code) or None,
    }
    record["attempt_count"] = attempt_no
    record.setdefault("attempts", []).append(attempt)

    if success is True:
        remote_id = _clean(remote_publication_id)
        if not remote_id:
            record["attempts"].pop()
            record["attempt_count"] = attempt_no - 1
            return {
                "blocked": True,
                "hard_blocks": ["MISSING_REMOTE_PUBLICATION_ID"],
                "decision": "BLOCKED",
                "record": copy.deepcopy(record),
                "ledger": candidate,
            }
        record["status"] = "PUBLISHED"
        record["state_reason"] = "ADAPTER_CONFIRMED"
        record["remote_publication_id"] = remote_id
        record["published_at"] = _iso(when)
        record["next_attempt_at"] = None
        decision = "PUBLISHED"
    else:
        failure = classify_failure(http_status=http_status, error_class=error_class)
        attempt["failure_class"] = failure
        if failure == "AUTH":
            record["status"] = "BLOCKED_AUTH"
            record["state_reason"] = "CREDENTIAL_REPAIR_REQUIRED"
            record["next_attempt_at"] = None
            decision = "BLOCKED_AUTH"
        elif failure == "TRANSIENT" and attempt_no < max_attempts:
            delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt_no - 1)))
            if retry_after_seconds is not None:
                delay = max(delay, max(0, min(86400, int(retry_after_seconds))))
            record["status"] = "RETRY_WAIT"
            record["state_reason"] = "TRANSIENT_FAILURE"
            record["next_attempt_at"] = _iso(when + timedelta(seconds=delay))
            decision = "RETRY_SCHEDULED"
        else:
            record["status"] = "FAILED_TERMINAL"
            record["state_reason"] = "RETRY_EXHAUSTED" if failure == "TRANSIENT" else "PERMANENT_FAILURE"
            record["next_attempt_at"] = None
            decision = "FAILED_TERMINAL"

    return {
        "blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "record": copy.deepcopy(record),
        "ledger": candidate,
    }


def release_retry(ledger: dict[str, Any], publication_id: str, now: str) -> dict[str, Any]:
    """Move a due retry from RETRY_WAIT to RETRY_READY; never dispatch early."""
    if not isinstance(ledger, dict):
        raise TypeError("ledger must be a mapping")
    current = _parse_time(now)
    candidate = copy.deepcopy(ledger)
    records = candidate.get("records")
    if not isinstance(records, dict) or publication_id not in records or not isinstance(records[publication_id], dict):
        return {"blocked": True, "hard_blocks": ["UNKNOWN_PUBLICATION_ID"], "decision": "BLOCKED", "record": None, "ledger": candidate}
    record = records[publication_id]
    if _clean(record.get("status")) != "RETRY_WAIT":
        return {"blocked": True, "hard_blocks": ["PUBLICATION_NOT_WAITING_RETRY"], "decision": "BLOCKED", "record": copy.deepcopy(record), "ledger": candidate}
    due = _parse_time(_clean(record.get("next_attempt_at")))
    if current < due:
        return {"blocked": False, "hard_blocks": [], "decision": "RETRY_NOT_DUE", "record": copy.deepcopy(record), "ledger": candidate}
    record["status"] = "RETRY_READY"
    record["state_reason"] = "RETRY_DUE"
    return {"blocked": False, "hard_blocks": [], "decision": "RETRY_READY", "record": copy.deepcopy(record), "ledger": candidate}


def requeue_after_auth_repair(ledger: dict[str, Any], publication_id: str) -> dict[str, Any]:
    """Explicitly requeue an auth-blocked record after credentials are repaired."""
    if not isinstance(ledger, dict):
        raise TypeError("ledger must be a mapping")
    candidate = copy.deepcopy(ledger)
    records = candidate.get("records")
    if not isinstance(records, dict) or publication_id not in records or not isinstance(records[publication_id], dict):
        return {"blocked": True, "hard_blocks": ["UNKNOWN_PUBLICATION_ID"], "decision": "BLOCKED", "record": None, "ledger": candidate}
    record = records[publication_id]
    if _clean(record.get("status")) != "BLOCKED_AUTH":
        return {"blocked": True, "hard_blocks": ["PUBLICATION_NOT_AUTH_BLOCKED"], "decision": "BLOCKED", "record": copy.deepcopy(record), "ledger": candidate}
    record["status"] = "READY"
    record["state_reason"] = "AUTH_REPAIR_CONFIRMED_EXTERNALLY"
    return {"blocked": False, "hard_blocks": [], "decision": "READY", "record": copy.deepcopy(record), "ledger": candidate}


def import_legacy_facebook_state(
    legacy_state: dict[str, Any],
    *,
    instance_id: str,
    channel_id: str,
    platform: str = "facebook",
) -> dict[str, Any]:
    """Read-only normalization of the existing Facebook state shape.

    This does not mutate or replace the legacy runtime file. It preserves
    already-published remote ids as generic PUBLISHED records so the first
    adapter can be generalized incrementally instead of duplicated.
    """
    if not isinstance(legacy_state, dict):
        raise TypeError("legacy_state must be a mapping")
    ledger = empty_ledger(instance_id, channel_id, platform)
    published = legacy_state.get("published")
    if not isinstance(published, dict):
        return ledger
    for legacy_key in sorted(published):
        value = published[legacy_key]
        if not isinstance(value, dict):
            continue
        remote_id = _clean(value.get("facebook_post_id"))
        if not remote_id:
            continue
        identity = {
            "instance_id": _clean(instance_id),
            "channel_id": _clean(channel_id),
            "platform": _clean(platform).lower(),
            "legacy_key": _clean(legacy_key),
            "remote_publication_id": remote_id,
        }
        key = _digest(identity)
        publication_id = "legacy-publication:" + key[:24]
        ledger["records"][publication_id] = {
            "publication_id": publication_id,
            "dedupe_key": key,
            "instance_id": _clean(instance_id),
            "channel_id": _clean(channel_id),
            "platform": _clean(platform).lower(),
            "story_id": _clean(legacy_key),
            "product_id": None,
            "product_fingerprint_sha256": None,
            "status": "PUBLISHED",
            "state_reason": "IMPORTED_LEGACY_FACEBOOK_STATE",
            "attempt_count": 0,
            "attempts": [],
            "remote_publication_id": remote_id,
            "published_at": _clean(value.get("published_at")) or None,
            "legacy_source_key": _clean(legacy_key),
            "guards": {
                "legacy_file_mutated": False,
                "zero_paid_dependency": True,
            },
        }
    return ledger


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("format_result", type=Path)
    parser.add_argument("virality", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--human-approved", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = prepare_publication(
        _load(args.format_result),
        _load(args.virality),
        _load(args.channel),
        _load(args.ledger) if args.ledger else None,
        human_approved=args.human_approved,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
