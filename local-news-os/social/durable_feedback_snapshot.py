#!/usr/bin/env python3
"""Durable observed-feedback snapshots for LOCAL NEWS OS social runtime.

This module closes the gap between observed-metrics learning and production ranking without
turning learning into an editorial gate. It builds one channel-local snapshot from validated
observations, seals it with deterministic fingerprints and a freshness TTL, then resolves the
snapshot into ``production_runtime`` only while it is structurally valid and fresh.

Safety properties:
- observations are validated through ``observed_metrics`` and feedback through
  ``observed_feedback_application``;
- freshness is anchored to the newest *observed_at* timestamp, never to the time a snapshot is
  rebuilt, so stale analytics cannot be made fresh by rewriting the file;
- invalid, stale, insufficient or cross-channel snapshots have exactly zero learning influence
  and never block an otherwise valid publication;
- snapshot replacement is monotonic by observed-data watermark and idempotent;
- no credential values, predicted analytics, network calls or paid dependencies are accepted;
- storage is derived from the channel's own publication-state namespace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import observed_feedback_application
import observed_metrics
import production_runtime

SCHEMA_VERSION = "1.0"
DEFAULT_TTL_HOURS = 168
MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 720


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _parse_time(value: Any) -> datetime:
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


def _valid_hash(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    payload = _clone(snapshot)
    payload.pop("snapshot_fingerprint_sha256", None)
    return _digest(payload)


def expected_snapshot_path(channel: dict[str, Any]) -> str:
    """Derive a channel-local feedback path from the existing publication state path."""
    if not isinstance(channel, dict):
        raise TypeError("channel must be a mapping")
    publication_state = channel.get("publication_state") if isinstance(channel.get("publication_state"), dict) else {}
    raw = _clean(publication_state.get("state_path"))
    if not raw:
        raise ValueError("channel publication_state.state_path is required")
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        raise ValueError("unsafe channel publication state path")
    name = path.name
    stem = name[:-5] if name.endswith(".json") else name
    return str(path.with_name(f"{stem}_feedback_snapshot.json"))


def _validated_observations(channel: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for item in observations:
        result = observed_metrics.validate_observation(channel, item)
        if result.get("valid") is True and isinstance(result.get("observation"), dict):
            accepted.append(result["observation"])
    return accepted


def build_snapshot(
    channel: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    now: str,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    min_samples: int = 3,
) -> dict[str, Any]:
    """Build a deterministic durable feedback snapshot from observed metrics.

    The expiry clock begins at the newest accepted observation, not at ``now``. Rebuilding an
    old observation set later therefore never extends its learning lifetime.
    """
    if not isinstance(channel, dict):
        raise TypeError("channel must be a mapping")
    if not isinstance(observations, list) or not all(isinstance(item, dict) for item in observations):
        raise TypeError("observations must be a list of mappings")
    if not isinstance(ttl_hours, int) or isinstance(ttl_hours, bool) or not MIN_TTL_HOURS <= ttl_hours <= MAX_TTL_HOURS:
        raise ValueError(f"ttl_hours must be between {MIN_TTL_HOURS} and {MAX_TTL_HOURS}")
    now_dt = _parse_time(now)

    report = observed_metrics.build_feedback(channel, observations, min_samples=min_samples)
    feedback_validation = observed_feedback_application.validate_feedback(channel, report)
    accepted = _validated_observations(channel, observations)
    latest_observed = max((_parse_time(item["observed_at"]) for item in accepted), default=None)

    hard_blocks = list(feedback_validation.get("hard_blocks", []))
    if latest_observed and latest_observed > now_dt:
        hard_blocks.append("OBSERVATION_FROM_FUTURE")

    structurally_safe = feedback_validation.get("valid") is True and not hard_blocks
    feedback_ready = _clean(report.get("status")).upper() == "READY"
    usable = structurally_safe and feedback_ready and latest_observed is not None
    expires_at = latest_observed + timedelta(hours=ttl_hours) if latest_observed else None

    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "storage_path": expected_snapshot_path(channel),
        "status": "READY" if usable else ("INSUFFICIENT_OBSERVED_DATA" if structurally_safe else "REJECTED_UNSAFE_FEEDBACK"),
        "usable": usable,
        "created_at": _iso(now_dt),
        "source_latest_observed_at": _iso(latest_observed) if latest_observed else None,
        "expires_at": _iso(expires_at) if expires_at else None,
        "ttl_hours": ttl_hours,
        "source_observation_count": len(accepted),
        "source_observation_ids": sorted(_clean(item.get("observation_id")) for item in accepted if _clean(item.get("observation_id"))),
        "feedback_fingerprint_sha256": report.get("feedback_fingerprint_sha256"),
        "feedback": report,
        "hard_blocks": sorted(set(str(value) for value in hard_blocks if _clean(value))),
        "replacement_policy": {
            "mode": "MONOTONIC_OBSERVED_WATERMARK",
            "same_fingerprint_is_idempotent": True,
            "older_observed_data_may_replace_newer": False,
            "insufficient_data_may_replace_ready": False,
        },
        "guards": {
            "observed_metrics_only": True,
            "freshness_anchored_to_observed_at": True,
            "predicted_or_estimated_analytics_used": False,
            "raw_reactions_optimized": False,
            "cross_channel_comparison_used": False,
            "channel_config_mutated": False,
            "editorial_gates_weakened": False,
            "invalid_or_stale_feedback_blocks_publication": False,
            "credential_values_read": False,
            "network_calls_performed": False,
            "zero_paid_dependency": True,
        },
    }
    snapshot["snapshot_fingerprint_sha256"] = _snapshot_fingerprint(snapshot)
    return snapshot


def validate_snapshot(channel: dict[str, Any], snapshot: dict[str, Any], *, now: str) -> dict[str, Any]:
    """Validate snapshot identity, seal, feedback contract and freshness."""
    if not isinstance(channel, dict) or not isinstance(snapshot, dict):
        raise TypeError("channel and snapshot must be mappings")
    now_dt = _parse_time(now)
    blocks: list[str] = []

    if _clean(snapshot.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("SNAPSHOT_SCHEMA_VERSION")
    for key, code in (
        ("instance_id", "INSTANCE_MISMATCH"),
        ("channel_id", "CHANNEL_MISMATCH"),
    ):
        if not _clean(snapshot.get(key)):
            blocks.append("MISSING_" + key.upper())
        elif _clean(snapshot.get(key)) != _clean(channel.get(key)):
            blocks.append(code)
    if _clean(snapshot.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("PLATFORM_MISMATCH")

    try:
        expected_path = expected_snapshot_path(channel)
    except (TypeError, ValueError):
        expected_path = ""
        blocks.append("INVALID_CHANNEL_SNAPSHOT_NAMESPACE")
    if _clean(snapshot.get("storage_path")) != expected_path:
        blocks.append("SNAPSHOT_STORAGE_NAMESPACE_MISMATCH")

    ttl = snapshot.get("ttl_hours")
    if not isinstance(ttl, int) or isinstance(ttl, bool) or not MIN_TTL_HOURS <= ttl <= MAX_TTL_HOURS:
        blocks.append("INVALID_SNAPSHOT_TTL")

    try:
        created_at = _parse_time(snapshot.get("created_at"))
    except ValueError:
        created_at = None
        blocks.append("INVALID_SNAPSHOT_CREATED_AT")
    latest_text = _clean(snapshot.get("source_latest_observed_at"))
    try:
        latest_observed = _parse_time(latest_text) if latest_text else None
    except ValueError:
        latest_observed = None
        blocks.append("INVALID_SOURCE_LATEST_OBSERVED_AT")
    expires_text = _clean(snapshot.get("expires_at"))
    try:
        expires_at = _parse_time(expires_text) if expires_text else None
    except ValueError:
        expires_at = None
        blocks.append("INVALID_SNAPSHOT_EXPIRES_AT")

    if latest_observed and latest_observed > now_dt:
        blocks.append("OBSERVATION_FROM_FUTURE")
    if created_at and latest_observed and created_at < latest_observed:
        blocks.append("SNAPSHOT_PRECEDES_OBSERVATION")
    if latest_observed and expires_at and isinstance(ttl, int) and MIN_TTL_HOURS <= ttl <= MAX_TTL_HOURS:
        expected_expiry = latest_observed + timedelta(hours=ttl)
        if abs((expires_at - expected_expiry).total_seconds()) > 0.5:
            blocks.append("SNAPSHOT_EXPIRY_NOT_OBSERVED_ANCHORED")

    feedback = snapshot.get("feedback") if isinstance(snapshot.get("feedback"), dict) else None
    feedback_validation: dict[str, Any] | None = None
    if feedback is None:
        blocks.append("MISSING_FEEDBACK_REPORT")
    else:
        feedback_validation = observed_feedback_application.validate_feedback(channel, feedback)
        if feedback_validation.get("valid") is not True:
            blocks.extend("FEEDBACK:" + str(value) for value in feedback_validation.get("hard_blocks", []))
        supplied_feedback_fp = _clean(snapshot.get("feedback_fingerprint_sha256")).lower()
        if supplied_feedback_fp != _clean(feedback.get("feedback_fingerprint_sha256")).lower():
            blocks.append("SNAPSHOT_FEEDBACK_FINGERPRINT_MISMATCH")

    guards = snapshot.get("guards") if isinstance(snapshot.get("guards"), dict) else {}
    required_guards = {
        "observed_metrics_only": True,
        "freshness_anchored_to_observed_at": True,
        "predicted_or_estimated_analytics_used": False,
        "raw_reactions_optimized": False,
        "cross_channel_comparison_used": False,
        "channel_config_mutated": False,
        "editorial_gates_weakened": False,
        "invalid_or_stale_feedback_blocks_publication": False,
        "credential_values_read": False,
        "network_calls_performed": False,
        "zero_paid_dependency": True,
    }
    for key, expected in required_guards.items():
        if guards.get(key) is not expected:
            blocks.append("UNSAFE_SNAPSHOT_GUARD:" + key)
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")

    supplied_snapshot_fp = _clean(snapshot.get("snapshot_fingerprint_sha256")).lower()
    if not _valid_hash(supplied_snapshot_fp):
        blocks.append("INVALID_SNAPSHOT_FINGERPRINT")
    elif supplied_snapshot_fp != _snapshot_fingerprint(snapshot):
        blocks.append("SNAPSHOT_FINGERPRINT_MISMATCH")

    status = _clean(snapshot.get("status")).upper()
    usable_flag = snapshot.get("usable") is True
    if usable_flag:
        if status != "READY":
            blocks.append("USABLE_SNAPSHOT_NOT_READY")
        if latest_observed is None or expires_at is None:
            blocks.append("USABLE_SNAPSHOT_MISSING_FRESHNESS_WINDOW")
        if feedback is not None and _clean(feedback.get("status")).upper() != "READY":
            blocks.append("USABLE_SNAPSHOT_FEEDBACK_NOT_READY")

    fresh = bool(expires_at and now_dt <= expires_at)
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not blocks,
        "fresh": fresh,
        "usable": usable_flag and not blocks and fresh,
        "status": status or None,
        "hard_blocks": sorted(set(blocks)),
        "source_latest_observed_at": _iso(latest_observed) if latest_observed else None,
        "expires_at": _iso(expires_at) if expires_at else None,
        "snapshot_fingerprint_sha256": supplied_snapshot_fp if _valid_hash(supplied_snapshot_fp) else None,
        "feedback_fingerprint_sha256": _clean(snapshot.get("feedback_fingerprint_sha256")).lower() or None,
    }


def resolve_snapshot(channel: dict[str, Any], snapshot: dict[str, Any] | None, *, now: str) -> dict[str, Any]:
    """Resolve a durable snapshot to zero or one feedback report for production ranking."""
    if snapshot is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "NO_SNAPSHOT",
            "bound": False,
            "feedback": None,
            "hard_blocks": [],
            "snapshot_fingerprint_sha256": None,
            "guards": {"publication_blocked": False, "zero_paid_dependency": True},
        }
    validation = validate_snapshot(channel, snapshot, now=now)
    if not validation["valid"]:
        status = "IGNORED_INVALID"
        feedback = None
    elif not validation["fresh"]:
        status = "IGNORED_STALE"
        feedback = None
    elif snapshot.get("usable") is not True or _clean(snapshot.get("status")).upper() != "READY":
        status = "NO_USABLE_FEEDBACK"
        feedback = None
    else:
        status = "BOUND"
        feedback = _clone(snapshot["feedback"])
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "bound": feedback is not None,
        "feedback": feedback,
        "hard_blocks": validation.get("hard_blocks", []),
        "fresh": validation.get("fresh"),
        "source_latest_observed_at": validation.get("source_latest_observed_at"),
        "expires_at": validation.get("expires_at"),
        "snapshot_fingerprint_sha256": validation.get("snapshot_fingerprint_sha256"),
        "feedback_fingerprint_sha256": validation.get("feedback_fingerprint_sha256"),
        "guards": {
            "publication_blocked": False,
            "invalid_feedback_learning_effect": "ZERO",
            "stale_feedback_learning_effect": "ZERO",
            "credential_values_read": False,
            "network_calls_performed": False,
            "zero_paid_dependency": True,
        },
    }


def should_replace_snapshot(
    channel: dict[str, Any],
    existing: dict[str, Any] | None,
    candidate: dict[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    """Return monotonic persistence advice for a channel-local snapshot file."""
    candidate_validation = validate_snapshot(channel, candidate, now=now)
    if not candidate_validation["valid"]:
        return {"replace": False, "reason": "CANDIDATE_INVALID", "candidate": candidate_validation}
    if candidate.get("usable") is not True:
        return {"replace": False, "reason": "CANDIDATE_NOT_READY", "candidate": candidate_validation}
    if existing is None:
        return {"replace": True, "reason": "NO_EXISTING_SNAPSHOT", "candidate": candidate_validation}

    existing_validation = validate_snapshot(channel, existing, now=now)
    if not existing_validation["valid"]:
        return {"replace": True, "reason": "REPLACE_INVALID_EXISTING", "candidate": candidate_validation, "existing": existing_validation}
    if _clean(existing.get("snapshot_fingerprint_sha256")) == _clean(candidate.get("snapshot_fingerprint_sha256")):
        return {"replace": False, "reason": "IDEMPOTENT_SAME_SNAPSHOT", "candidate": candidate_validation, "existing": existing_validation}

    candidate_watermark = candidate_validation.get("source_latest_observed_at")
    existing_watermark = existing_validation.get("source_latest_observed_at")
    if not candidate_watermark:
        return {"replace": False, "reason": "CANDIDATE_MISSING_WATERMARK", "candidate": candidate_validation, "existing": existing_validation}
    if not existing_watermark or _parse_time(candidate_watermark) > _parse_time(existing_watermark):
        return {"replace": True, "reason": "NEWER_OBSERVED_WATERMARK", "candidate": candidate_validation, "existing": existing_validation}
    return {"replace": False, "reason": "NOT_NEWER_OBSERVED_WATERMARK", "candidate": candidate_validation, "existing": existing_validation}


def orchestrate_with_snapshot(
    story: dict[str, Any],
    channel: dict[str, Any],
    media_inventory: dict[str, Any],
    cadence_history: dict[str, Any],
    *,
    now: str,
    feedback_snapshot: dict[str, Any] | None,
    ledger: dict[str, Any] | None = None,
    human_approved: bool = False,
    canonical_url: str | None = None,
    series_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run production runtime with the latest safe durable feedback snapshot automatically bound."""
    binding = resolve_snapshot(channel, feedback_snapshot, now=now)
    result = production_runtime.orchestrate_channel(
        story,
        channel,
        media_inventory,
        cadence_history,
        now=now,
        ledger=ledger,
        human_approved=human_approved,
        canonical_url=canonical_url,
        series_decision=series_decision,
        observed_feedback=binding.get("feedback") if binding.get("bound") is True else None,
    )
    result["feedback_snapshot_binding"] = {
        key: value for key, value in binding.items() if key != "feedback"
    }
    return result


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a sealed snapshot from observed metrics")
    build.add_argument("channel", type=Path)
    build.add_argument("observations", type=Path)
    build.add_argument("--now", required=True)
    build.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    build.add_argument("--min-samples", type=int, default=3)
    build.add_argument("--output", type=Path)

    resolve = subparsers.add_parser("resolve", help="validate freshness and resolve snapshot binding")
    resolve.add_argument("channel", type=Path)
    resolve.add_argument("snapshot", type=Path)
    resolve.add_argument("--now", required=True)
    resolve.add_argument("--output", type=Path)

    args = parser.parse_args()
    if args.command == "build":
        payload_value = build_snapshot(
            _load_object(args.channel),
            _load_array(args.observations),
            now=args.now,
            ttl_hours=args.ttl_hours,
            min_samples=args.min_samples,
        )
    else:
        resolved = resolve_snapshot(_load_object(args.channel), _load_object(args.snapshot), now=args.now)
        payload_value = {key: value for key, value in resolved.items() if key != "feedback"}

    payload = json.dumps(payload_value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
