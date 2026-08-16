#!/usr/bin/env python3
"""Observed native-metrics collection and durable snapshot materialization for LOCAL NEWS OS.

This module closes the durable side of the publication -> observation -> learning loop without
turning analytics into an editorial gate. Provider transport stays at the network boundary; this
core accepts a payload obtained from a CHANNEL_CONFIG-declared native/free source, binds it to a
confirmed remote publication, normalizes only observed scalar metrics, stores the sealed
observation in the channel's own namespace, and advances the existing durable feedback snapshot
only when the observed-data watermark moves forward.

Safety properties:
- only confirmed remote publications may be observed;
- provider payloads containing predicted/estimated analytics or secret-like fields are rejected;
- raw provider payloads and credential values are never persisted;
- collection is restricted to sources declared by CHANNEL_CONFIG and zero-paid dependency;
- observation-store identity is instance/channel/platform isolated and sealed;
- same-window conflicting payloads fail closed instead of silently overwriting evidence;
- snapshot replacement reuses durable_feedback_snapshot monotonic/freshness policy;
- insufficient, invalid or stale learning never blocks publication and cannot replace newer data;
- persistence order is crash-safe: observations first, derived snapshot second. A crash between
  those writes leaves the previous valid snapshot in place and the next run can deterministically
  rebuild it from the durable observation store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
from typing import Any

import durable_feedback_snapshot
import observed_metrics

SCHEMA_VERSION = "1.0"
COLLECTOR_ID = "local-news-os-observed-metrics-collector"

# Only scalar, semantically direct aliases are normalized. Provider-specific composite metrics
# (for example reactions broken down by type) are intentionally not summed in this layer.
METRIC_ALIASES = {
    "impressions": "impressions",
    "post_impressions": "impressions",
    "reach": "reach",
    "post_impressions_unique": "reach",
    "reactions": "reactions",
    "comments": "comments",
    "shares": "shares",
    "saved": "saves",
    "saves": "saves",
    "link_clicks": "link_clicks",
    "clicks": "link_clicks",
    "video_views": "video_views",
    "views": "video_views",
    "plays": "video_views",
    "video_watch_seconds": "video_watch_seconds",
    "watch_time_seconds": "video_watch_seconds",
    "video_completions": "video_completions",
    "completions": "video_completions",
    "profile_visits": "profile_visits",
    "profile_views": "profile_visits",
    "follows": "follows",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_hash(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _walk_keys(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = _clean(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            found.append((path, key_text.lower()))
            found.extend(_walk_keys(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk_keys(item, f"{prefix}[{index}]"))
    return found


def _contains_token(key: str, tokens: set[str]) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(token in normalized for token in tokens)


def expected_observation_store_path(channel: dict[str, Any]) -> str:
    """Derive a channel-local observation ledger from publication_state.state_path."""
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
    return str(path.with_name(f"{stem}_observed_metrics.json"))


def _provider_payload_blocks(payload: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    for path, key in _walk_keys(payload):
        if _contains_token(key, observed_metrics.FORBIDDEN_ANALYTIC_TOKENS):
            blocks.append("PREDICTIVE_OR_ESTIMATED_PROVIDER_FIELD:" + path)
        if _contains_token(key, observed_metrics.SECRET_TOKENS):
            blocks.append("SECRET_LIKE_PROVIDER_FIELD:" + path)
    return sorted(set(blocks))


def _scalar_metric(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    if isinstance(value, int):
        return value
    return number


def normalize_provider_metrics(payload: dict[str, Any]) -> dict[str, float | int]:
    """Normalize observed scalar metrics from canonical, flat, or Graph-style payloads.

    No aggregation or inference is performed. Unknown or composite provider values are ignored;
    at least one direct scalar metric must survive normalization.
    """
    if not isinstance(payload, dict):
        raise TypeError("provider payload must be a mapping")
    blocks = _provider_payload_blocks(payload)
    if blocks:
        raise ValueError(";".join(blocks))

    candidates: list[tuple[str, Any]] = []
    embedded = payload.get("metrics")
    if isinstance(embedded, dict):
        candidates.extend((_clean(key).lower(), value) for key, value in embedded.items())

    data = payload.get("data")
    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = _clean(entry.get("name")).lower()
            if not name:
                continue
            if "value" in entry:
                candidates.append((name, entry.get("value")))
                continue
            values = entry.get("values")
            if isinstance(values, list) and values:
                last = values[-1]
                if isinstance(last, dict) and "value" in last:
                    candidates.append((name, last.get("value")))

    # A small flat-payload contract is useful for native adapters that already expose direct
    # observed counters. Metadata keys are harmless because only known aliases survive.
    candidates.extend((_clean(key).lower(), value) for key, value in payload.items())

    normalized: dict[str, float | int] = {}
    for provider_name, raw_value in candidates:
        canonical_name = METRIC_ALIASES.get(provider_name)
        if not canonical_name:
            continue
        value = _scalar_metric(raw_value)
        if value is None:
            continue
        # Duplicate aliases must agree. Disagreement is evidence ambiguity, not a chance to pick
        # the largest or most convenient number.
        if canonical_name in normalized and float(normalized[canonical_name]) != float(value):
            raise ValueError("CONFLICTING_PROVIDER_METRIC:" + canonical_name)
        normalized[canonical_name] = value

    if not normalized:
        raise ValueError("NO_SUPPORTED_OBSERVED_METRICS")
    return {key: normalized[key] for key in sorted(normalized)}


def validate_publication_descriptor(channel: dict[str, Any], publication: dict[str, Any]) -> dict[str, Any]:
    """Validate the authoritative publication identity needed by observed_metrics."""
    if not isinstance(channel, dict) or not isinstance(publication, dict):
        raise TypeError("channel and publication must be mappings")
    blocks: list[str] = []
    for key, code in (("instance_id", "INSTANCE_MISMATCH"), ("channel_id", "CHANNEL_MISMATCH")):
        if not _clean(publication.get(key)):
            blocks.append("MISSING_" + key.upper())
        elif _clean(publication.get(key)) != _clean(channel.get(key)):
            blocks.append(code)
    if _clean(publication.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("PLATFORM_MISMATCH")
    if _clean(publication.get("status")).upper() != "PUBLISHED":
        blocks.append("PUBLICATION_NOT_CONFIRMED")
    for key in ("publication_id", "remote_publication_id", "story_id", "product_id", "published_at", "native_format"):
        if not _clean(publication.get(key)):
            blocks.append("MISSING_" + key.upper())
    topics = publication.get("topic_keys")
    if not isinstance(topics, list) or not all(isinstance(item, str) and item.strip() for item in topics):
        blocks.append("INVALID_TOPIC_KEYS")
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def build_observation(
    channel: dict[str, Any],
    publication: dict[str, Any],
    provider_payload: dict[str, Any],
    *,
    source: str,
    observed_at: str,
    collected_at: str,
    window_start_at: str,
    window_end_at: str,
    collector: str = COLLECTOR_ID,
) -> dict[str, Any]:
    """Bind a native provider payload to one confirmed remote publication."""
    if not isinstance(channel, dict) or not isinstance(publication, dict) or not isinstance(provider_payload, dict):
        raise TypeError("channel, publication and provider_payload must be mappings")
    if channel.get("zero_paid_dependency") is not True:
        return {"valid": False, "hard_blocks": ["ZERO_PAID_DEPENDENCY_VIOLATION"], "observation": None}

    descriptor_validation = validate_publication_descriptor(channel, publication)
    blocks = list(descriptor_validation["hard_blocks"])
    declared_sources = {
        _clean(value)
        for value in (channel.get("metrics", {}).get("sources", []) if isinstance(channel.get("metrics"), dict) else [])
        if _clean(value)
    }
    source_name = _clean(source)
    if not source_name:
        blocks.append("MISSING_METRIC_SOURCE")
    elif source_name not in declared_sources:
        blocks.append("UNDECLARED_METRIC_SOURCE")
    blocks.extend(_provider_payload_blocks(provider_payload))
    if blocks:
        return {"valid": False, "hard_blocks": sorted(set(blocks)), "observation": None}

    try:
        metrics = normalize_provider_metrics(provider_payload)
    except (TypeError, ValueError) as exc:
        return {"valid": False, "hard_blocks": [str(exc)], "observation": None}

    observation = {
        "schema_version": observed_metrics.SCHEMA_VERSION,
        "instance_id": _clean(publication.get("instance_id")),
        "channel_id": _clean(publication.get("channel_id")),
        "platform": _clean(publication.get("platform")).lower(),
        "publication_id": _clean(publication.get("publication_id")),
        "remote_publication_id": _clean(publication.get("remote_publication_id")),
        "story_id": _clean(publication.get("story_id")),
        "product_id": _clean(publication.get("product_id")),
        "source": source_name,
        "observed_at": observed_at,
        "window": {
            "kind": "cumulative",
            "start_at": window_start_at,
            "end_at": window_end_at,
        },
        "publication_context": {
            "status": "PUBLISHED",
            "published_at": publication.get("published_at"),
            "native_format": _clean(publication.get("native_format")).lower(),
            "topic_keys": sorted({_clean(item) for item in publication.get("topic_keys", []) if _clean(item)}),
            "series_id": _clean(publication.get("series_id")) or None,
        },
        "metrics": metrics,
        "provenance": {
            "retrieval_method": "native_api",
            "collector": _clean(collector) or COLLECTOR_ID,
            "source_payload_sha256": _digest(provider_payload),
            "collected_at": collected_at,
        },
        "guards": {"observed_only": True, "predicted_or_estimated": False},
    }
    validated = observed_metrics.validate_observation(channel, observation)
    return validated


def _store_fingerprint(store: dict[str, Any]) -> str:
    payload = _clone(store)
    payload.pop("store_fingerprint_sha256", None)
    return _digest(payload)


def _empty_store(channel: dict[str, Any]) -> dict[str, Any]:
    store = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "storage_path": expected_observation_store_path(channel),
        "observations": [],
        "guards": {
            "observed_metrics_only": True,
            "raw_provider_payload_persisted": False,
            "credential_values_persisted": False,
            "predicted_or_estimated_analytics_used": False,
            "cross_channel_learning": False,
            "zero_paid_dependency": True,
        },
    }
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    return store


def validate_observation_store(channel: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(channel, dict) or not isinstance(store, dict):
        raise TypeError("channel and store must be mappings")
    blocks: list[str] = []
    if _clean(store.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("STORE_SCHEMA_VERSION")
    if _clean(store.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("INSTANCE_MISMATCH")
    if _clean(store.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("CHANNEL_MISMATCH")
    if _clean(store.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("PLATFORM_MISMATCH")
    try:
        expected_path = expected_observation_store_path(channel)
    except (TypeError, ValueError):
        expected_path = ""
        blocks.append("INVALID_CHANNEL_OBSERVATION_NAMESPACE")
    if _clean(store.get("storage_path")) != expected_path:
        blocks.append("STORE_STORAGE_NAMESPACE_MISMATCH")

    observations = store.get("observations")
    if not isinstance(observations, list) or not all(isinstance(item, dict) for item in observations):
        blocks.append("INVALID_OBSERVATION_STORE_ROWS")
        observations = []
    ids: set[str] = set()
    for item in observations:
        result = observed_metrics.validate_observation(channel, item)
        if result.get("valid") is not True:
            blocks.extend("OBSERVATION:" + str(code) for code in result.get("hard_blocks", []))
            continue
        obs_id = _clean(result["observation"].get("observation_id"))
        if obs_id in ids:
            blocks.append("DUPLICATE_OBSERVATION_ID")
        ids.add(obs_id)

    guards = store.get("guards") if isinstance(store.get("guards"), dict) else {}
    required = {
        "observed_metrics_only": True,
        "raw_provider_payload_persisted": False,
        "credential_values_persisted": False,
        "predicted_or_estimated_analytics_used": False,
        "cross_channel_learning": False,
        "zero_paid_dependency": True,
    }
    for key, expected in required.items():
        if guards.get(key) is not expected:
            blocks.append("UNSAFE_STORE_GUARD:" + key)
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")

    supplied = _clean(store.get("store_fingerprint_sha256")).lower()
    if not _valid_hash(supplied):
        blocks.append("INVALID_STORE_FINGERPRINT")
    elif supplied != _store_fingerprint(store):
        blocks.append("STORE_FINGERPRINT_MISMATCH")
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def _observation_signature(observation: dict[str, Any]) -> tuple[str, str, str, str]:
    window = observation.get("window") if isinstance(observation.get("window"), dict) else {}
    return (
        _clean(observation.get("publication_id")),
        _clean(observation.get("source")),
        _clean(window.get("start_at")),
        _clean(window.get("end_at")),
    )


def merge_observation_store(
    channel: dict[str, Any], existing: dict[str, Any] | None, observation: dict[str, Any]
) -> dict[str, Any]:
    """Idempotently append one observation, rejecting same-window evidence conflicts."""
    validated_observation = observed_metrics.validate_observation(channel, observation)
    if validated_observation.get("valid") is not True:
        return {"ok": False, "action": "REJECTED_OBSERVATION", "hard_blocks": validated_observation.get("hard_blocks", []), "store": None}
    normalized = validated_observation["observation"]

    if existing is None:
        store = _empty_store(channel)
    else:
        validation = validate_observation_store(channel, existing)
        if not validation["valid"]:
            return {"ok": False, "action": "REJECTED_EXISTING_STORE", "hard_blocks": validation["hard_blocks"], "store": None}
        store = _clone(existing)

    rows = store["observations"]
    obs_id = normalized["observation_id"]
    for current in rows:
        if _clean(current.get("observation_id")) == obs_id:
            return {"ok": True, "action": "IDEMPOTENT", "hard_blocks": [], "store": store}
        if _observation_signature(current) == _observation_signature(normalized):
            return {
                "ok": False,
                "action": "HOLD_OBSERVATION_CONFLICT",
                "hard_blocks": ["SAME_WINDOW_PROVIDER_EVIDENCE_CONFLICT"],
                "store": None,
            }

    rows.append(normalized)
    rows.sort(key=lambda item: (_clean(item.get("observed_at")), _clean(item.get("observation_id"))))
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    return {"ok": True, "action": "APPENDED", "hard_blocks": [], "store": store}


def materialize_bundle(
    channel: dict[str, Any],
    publication: dict[str, Any],
    provider_payload: dict[str, Any],
    *,
    source: str,
    observed_at: str,
    collected_at: str,
    window_start_at: str,
    window_end_at: str,
    now: str,
    existing_store: dict[str, Any] | None = None,
    existing_snapshot: dict[str, Any] | None = None,
    ttl_hours: int = durable_feedback_snapshot.DEFAULT_TTL_HOURS,
    min_samples: int = 3,
) -> dict[str, Any]:
    """Build a conflict-safe durable observation + feedback snapshot commit bundle."""
    observed = build_observation(
        channel,
        publication,
        provider_payload,
        source=source,
        observed_at=observed_at,
        collected_at=collected_at,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
    )
    if observed.get("valid") is not True:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "HOLD_OBSERVATION",
            "hard_blocks": observed.get("hard_blocks", []),
            "write_plan": [],
            "guards": {"publication_blocked": False, "zero_paid_dependency": True},
        }

    merged = merge_observation_store(channel, existing_store, observed["observation"])
    if merged.get("ok") is not True:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": merged.get("action"),
            "hard_blocks": merged.get("hard_blocks", []),
            "write_plan": [],
            "guards": {"publication_blocked": False, "zero_paid_dependency": True},
        }

    store = merged["store"]
    candidate = durable_feedback_snapshot.build_snapshot(
        channel,
        store["observations"],
        now=now,
        ttl_hours=ttl_hours,
        min_samples=min_samples,
    )
    decision = durable_feedback_snapshot.should_replace_snapshot(
        channel, existing_snapshot, candidate, now=now
    )
    replace_snapshot = decision.get("replace") is True
    write_store = merged.get("action") == "APPENDED" or existing_store is None
    write_plan: list[dict[str, Any]] = []
    if write_store:
        write_plan.append({"kind": "OBSERVATION_STORE", "path": expected_observation_store_path(channel)})
    if replace_snapshot:
        write_plan.append({"kind": "FEEDBACK_SNAPSHOT", "path": durable_feedback_snapshot.expected_snapshot_path(channel)})

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "status": "MATERIALIZED" if write_plan else "IDEMPOTENT",
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "observation_action": merged.get("action"),
        "observation_id": observed["observation"]["observation_id"],
        "observation_store": store,
        "snapshot_candidate": candidate,
        "snapshot_to_persist": candidate if replace_snapshot else None,
        "snapshot_decision": {key: value for key, value in decision.items() if key not in {"candidate", "existing"}},
        "write_plan": write_plan,
        "hard_blocks": [],
        "guards": {
            "publication_blocked": False,
            "raw_provider_payload_persisted": False,
            "credential_values_persisted": False,
            "snapshot_is_derived_from_durable_observations": True,
            "persistence_order": ["OBSERVATION_STORE", "FEEDBACK_SNAPSHOT"],
            "predicted_or_estimated_analytics_used": False,
            "cross_channel_learning": False,
            "network_calls_performed_by_core": False,
            "zero_paid_dependency": True,
        },
    }
    bundle["bundle_fingerprint_sha256"] = _digest({key: value for key, value in bundle.items() if key != "bundle_fingerprint_sha256"})
    return bundle


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def persist_bundle(repo_root: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    """Persist a previously built safe bundle in crash-recoverable dependency order."""
    if _clean(bundle.get("status")) not in {"MATERIALIZED", "IDEMPOTENT"}:
        raise ValueError("only safe materialized bundles may be persisted")
    written: list[str] = []
    plan = bundle.get("write_plan") if isinstance(bundle.get("write_plan"), list) else []
    for step in plan:
        if not isinstance(step, dict):
            raise ValueError("invalid write plan")
        kind = _clean(step.get("kind"))
        relative = PurePosixPath(_clean(step.get("path")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe write path")
        if kind == "OBSERVATION_STORE":
            payload = bundle.get("observation_store")
        elif kind == "FEEDBACK_SNAPSHOT":
            payload = bundle.get("snapshot_to_persist")
        else:
            raise ValueError("unknown write-plan kind")
        if not isinstance(payload, dict):
            raise ValueError("missing write payload")
        target = repo_root.joinpath(*relative.parts)
        _atomic_write_json(target, payload)
        written.append(str(relative))
    return {"persisted": True, "written": written, "crash_recovery": "REBUILD_SNAPSHOT_FROM_OBSERVATION_STORE"}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _load_object(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("publication", type=Path)
    parser.add_argument("provider_payload", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--collected-at", required=True)
    parser.add_argument("--window-start-at", required=True)
    parser.add_argument("--window-end-at", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--existing-store", type=Path)
    parser.add_argument("--existing-snapshot", type=Path)
    parser.add_argument("--ttl-hours", type=int, default=durable_feedback_snapshot.DEFAULT_TTL_HOURS)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--persist-root", type=Path)
    args = parser.parse_args()

    bundle = materialize_bundle(
        _load_object(args.channel),
        _load_object(args.publication),
        _load_object(args.provider_payload),
        source=args.source,
        observed_at=args.observed_at,
        collected_at=args.collected_at,
        window_start_at=args.window_start_at,
        window_end_at=args.window_end_at,
        now=args.now,
        existing_store=_load_optional(args.existing_store),
        existing_snapshot=_load_optional(args.existing_snapshot),
        ttl_hours=args.ttl_hours,
        min_samples=args.min_samples,
    )
    if args.persist_root and not bundle.get("hard_blocks"):
        bundle["persistence_result"] = persist_bundle(args.persist_root, bundle)
    print(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if bundle.get("hard_blocks") else 0


if __name__ == "__main__":
    raise SystemExit(main())
