#!/usr/bin/env python3
"""Observed-metrics schema validation and bounded feedback learning for LOCAL NEWS OS.

This module consumes only metrics actually observed for confirmed remote publications.
It rejects predicted/estimated analytics, undeclared sources, missing provenance, secret-like
fields and cross-instance/channel records. Learning is within-channel, advisory-only and
bounded; it can never mutate CHANNEL_CONFIG, weaken editorial gates or compare platforms.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = "1.0"
ALLOWED_METRICS = {
    "impressions",
    "reach",
    "reactions",
    "comments",
    "shares",
    "saves",
    "link_clicks",
    "video_views",
    "video_watch_seconds",
    "video_completions",
    "profile_visits",
    "follows",
}
LEARNING_ACTION_METRICS = ("shares", "saves", "comments", "link_clicks")
FORBIDDEN_ANALYTIC_TOKENS = {
    "predicted",
    "prediction",
    "expected",
    "estimated",
    "estimate",
    "forecast",
    "inferred",
    "modeled",
    "modelled",
    "virality_probability",
    "probability_of_virality",
}
SECRET_TOKENS = {
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "credential",
    "authorization",
    "api_key",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


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


def _valid_hash(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _metric_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0.0


def _normalize_observation(observation: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(observation, ensure_ascii=False))
    normalized.pop("observation_id", None)
    normalized["schema_version"] = SCHEMA_VERSION
    for key in ("instance_id", "channel_id", "platform", "publication_id", "remote_publication_id", "story_id", "product_id", "source"):
        if key in normalized:
            normalized[key] = _clean(normalized.get(key))
    normalized["platform"] = _clean(normalized.get("platform")).lower()

    window = normalized.get("window") if isinstance(normalized.get("window"), dict) else {}
    if window:
        for key in ("start_at", "end_at"):
            if key in window:
                try:
                    window[key] = _iso(_parse_time(window[key]))
                except ValueError:
                    pass
        window["kind"] = _clean(window.get("kind")).lower()

    context = normalized.get("publication_context") if isinstance(normalized.get("publication_context"), dict) else {}
    if context:
        if "published_at" in context:
            try:
                context["published_at"] = _iso(_parse_time(context["published_at"]))
            except ValueError:
                pass
        context["status"] = _clean(context.get("status")).upper()
        context["native_format"] = _clean(context.get("native_format")).lower()
        topics = context.get("topic_keys")
        if isinstance(topics, list):
            context["topic_keys"] = sorted({_clean(item) for item in topics if _clean(item)})
        if "series_id" in context:
            context["series_id"] = _clean(context.get("series_id")) or None

    if "observed_at" in normalized:
        try:
            normalized["observed_at"] = _iso(_parse_time(normalized["observed_at"]))
        except ValueError:
            pass
    provenance = normalized.get("provenance") if isinstance(normalized.get("provenance"), dict) else {}
    if provenance:
        provenance["retrieval_method"] = _clean(provenance.get("retrieval_method")).lower()
        provenance["collector"] = _clean(provenance.get("collector"))
        provenance["source_payload_sha256"] = _clean(provenance.get("source_payload_sha256")).lower()
        if "collected_at" in provenance:
            try:
                provenance["collected_at"] = _iso(_parse_time(provenance["collected_at"]))
            except ValueError:
                pass

    metrics = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
    if metrics:
        normalized["metrics"] = {key: metrics[key] for key in sorted(metrics)}

    guards = normalized.get("guards") if isinstance(normalized.get("guards"), dict) else {}
    if guards:
        normalized["guards"] = {
            "observed_only": guards.get("observed_only") is True,
            "predicted_or_estimated": guards.get("predicted_or_estimated") is True,
        }
    normalized["observation_id"] = "metric-observation:" + _digest(normalized)[:24]
    return normalized


def validate_observation(channel: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one observed-metrics record against CHANNEL_CONFIG."""
    if not isinstance(channel, dict) or not isinstance(observation, dict):
        raise TypeError("channel and observation must be mappings")

    blocks: list[str] = []
    channel_metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if channel_metrics.get("observed_only") is not True:
        blocks.append("CHANNEL_METRICS_NOT_OBSERVED_ONLY")
    declared_sources = {_clean(value) for value in channel_metrics.get("sources", []) if _clean(value)} if isinstance(channel_metrics.get("sources"), list) else set()

    if _clean(observation.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("OBSERVATION_SCHEMA_VERSION")
    identity = (
        ("instance_id", "INSTANCE_MISMATCH"),
        ("channel_id", "CHANNEL_MISMATCH"),
    )
    for key, code in identity:
        if not _clean(observation.get(key)):
            blocks.append("MISSING_" + key.upper())
        elif _clean(observation.get(key)) != _clean(channel.get(key)):
            blocks.append(code)
    platform = _clean(observation.get("platform")).lower()
    if not platform:
        blocks.append("MISSING_PLATFORM")
    elif platform != _clean(channel.get("platform")).lower():
        blocks.append("PLATFORM_MISMATCH")

    for key in ("publication_id", "remote_publication_id", "story_id", "product_id"):
        if not _clean(observation.get(key)):
            blocks.append("MISSING_" + key.upper())

    source = _clean(observation.get("source"))
    if not source:
        blocks.append("MISSING_METRIC_SOURCE")
    elif source not in declared_sources:
        blocks.append("UNDECLARED_METRIC_SOURCE")

    key_paths = _walk_keys(observation)
    predictive_paths = sorted(path for path, key in key_paths if path != "guards.predicted_or_estimated" and _contains_token(key, FORBIDDEN_ANALYTIC_TOKENS))
    secret_paths = sorted(path for path, key in key_paths if _contains_token(key, SECRET_TOKENS))
    if predictive_paths:
        blocks.append("PREDICTIVE_OR_ESTIMATED_ANALYTICS_PRESENT")
    if secret_paths:
        blocks.append("SECRET_LIKE_FIELD_PRESENT")

    context = observation.get("publication_context") if isinstance(observation.get("publication_context"), dict) else None
    if context is None:
        blocks.append("MISSING_PUBLICATION_CONTEXT")
        published_at = None
    else:
        if _clean(context.get("status")).upper() != "PUBLISHED":
            blocks.append("PUBLICATION_NOT_CONFIRMED")
        if not _clean(context.get("native_format")):
            blocks.append("MISSING_NATIVE_FORMAT")
        topics = context.get("topic_keys")
        if not isinstance(topics, list) or not all(isinstance(item, str) and item.strip() for item in topics):
            blocks.append("INVALID_TOPIC_KEYS")
        try:
            published_at = _parse_time(context.get("published_at"))
        except ValueError:
            published_at = None
            blocks.append("INVALID_PUBLISHED_AT")

    try:
        observed_at = _parse_time(observation.get("observed_at"))
    except ValueError:
        observed_at = None
        blocks.append("INVALID_OBSERVED_AT")

    window = observation.get("window") if isinstance(observation.get("window"), dict) else None
    start_at = end_at = None
    if window is None:
        blocks.append("MISSING_METRIC_WINDOW")
    else:
        if _clean(window.get("kind")).lower() != "cumulative":
            blocks.append("UNSUPPORTED_WINDOW_KIND")
        try:
            start_at = _parse_time(window.get("start_at"))
        except ValueError:
            blocks.append("INVALID_WINDOW_START")
        try:
            end_at = _parse_time(window.get("end_at"))
        except ValueError:
            blocks.append("INVALID_WINDOW_END")
        if start_at and end_at and start_at > end_at:
            blocks.append("INVALID_METRIC_WINDOW_ORDER")
        if published_at and start_at and start_at < published_at:
            blocks.append("WINDOW_PRECEDES_PUBLICATION")
        if observed_at and end_at and end_at > observed_at:
            blocks.append("WINDOW_END_AFTER_OBSERVATION")

    provenance = observation.get("provenance") if isinstance(observation.get("provenance"), dict) else None
    if provenance is None:
        blocks.append("MISSING_METRIC_PROVENANCE")
    else:
        if _clean(provenance.get("retrieval_method")).lower() not in {"native_api", "native_export", "manual_export"}:
            blocks.append("INVALID_RETRIEVAL_METHOD")
        if not _clean(provenance.get("collector")):
            blocks.append("MISSING_METRIC_COLLECTOR")
        if not _valid_hash(provenance.get("source_payload_sha256")):
            blocks.append("INVALID_SOURCE_PAYLOAD_HASH")
        try:
            collected_at = _parse_time(provenance.get("collected_at"))
        except ValueError:
            collected_at = None
            blocks.append("INVALID_COLLECTED_AT")
        if observed_at and collected_at and collected_at < observed_at:
            blocks.append("COLLECTION_PRECEDES_OBSERVATION")

    metrics = observation.get("metrics") if isinstance(observation.get("metrics"), dict) else None
    if not metrics:
        blocks.append("MISSING_OBSERVED_METRICS")
    else:
        unknown = sorted(set(metrics) - ALLOWED_METRICS)
        if unknown:
            blocks.append("UNKNOWN_METRIC:" + ",".join(unknown))
        invalid = sorted(key for key, value in metrics.items() if not _metric_number(value))
        if invalid:
            blocks.append("INVALID_METRIC_VALUE:" + ",".join(invalid))

    guards = observation.get("guards") if isinstance(observation.get("guards"), dict) else {}
    if guards.get("observed_only") is not True:
        blocks.append("OBSERVED_ONLY_GUARD")
    if guards.get("predicted_or_estimated") is not False:
        blocks.append("PREDICTIVE_GUARD")

    normalized = _normalize_observation(observation) if not blocks else None
    if normalized is not None:
        supplied_id = _clean(observation.get("observation_id"))
        if supplied_id and supplied_id != normalized["observation_id"]:
            blocks.append("OBSERVATION_ID_MISMATCH")
            normalized = None

    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not blocks,
        "hard_blocks": sorted(set(blocks)),
        "observation": normalized,
    }


def _quality_signal(observation: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    metrics = observation.get("metrics") if isinstance(observation.get("metrics"), dict) else {}
    reach = float(metrics.get("reach", 0.0) or 0.0)
    impressions = float(metrics.get("impressions", 0.0) or 0.0)
    denominator = reach if reach > 0 else impressions if impressions > 0 else 0.0
    if denominator <= 0:
        return None, {"denominator_metric": None, "denominator": 0.0, "action_metrics": []}
    actions = [key for key in LEARNING_ACTION_METRICS if key in metrics]
    if not actions:
        return None, {"denominator_metric": "reach" if reach > 0 else "impressions", "denominator": denominator, "action_metrics": []}
    numerator = sum(float(metrics.get(key, 0.0) or 0.0) for key in actions)
    signal = min(1.0, max(0.0, numerator / denominator))
    return round(signal, 8), {
        "denominator_metric": "reach" if reach > 0 else "impressions",
        "denominator": denominator,
        "action_metrics": actions,
    }


def _hint(entries: list[tuple[str, float]], baseline: float, min_samples: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for key, signal in entries:
        if key:
            grouped.setdefault(key, []).append(signal)
    hints: list[dict[str, Any]] = []
    for key in sorted(grouped):
        values = grouped[key]
        if len(values) < min_samples:
            continue
        group_median = float(median(values))
        if baseline <= 0.0:
            relative = 0.0
        else:
            relative = max(-1.0, min(1.0, (group_median - baseline) / baseline))
        points = round(relative * 5.0, 2)
        recommendation = "neutral"
        if points >= 1.0:
            recommendation = "consider_more"
        elif points <= -1.0:
            recommendation = "consider_less"
        hints.append({
            "key": key,
            "samples": len(values),
            "median_observed_action_rate": round(group_median, 8),
            "bounded_adjustment_points": points,
            "recommendation": recommendation,
        })
    return hints


def build_feedback(channel: dict[str, Any], observations: list[dict[str, Any]], *, min_samples: int = 3) -> dict[str, Any]:
    """Build deterministic, advisory-only within-channel learning from observed data."""
    if not isinstance(channel, dict):
        raise TypeError("channel must be a mapping")
    if not isinstance(observations, list) or not all(isinstance(item, dict) for item in observations):
        raise TypeError("observations must be a list of mappings")
    if min_samples < 2:
        raise ValueError("min_samples must be at least 2")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, item in enumerate(observations):
        validated = validate_observation(channel, item)
        if validated["valid"]:
            accepted.append(validated["observation"])
        else:
            rejected.append({"index": index, "hard_blocks": validated["hard_blocks"]})

    by_id: dict[str, dict[str, Any]] = {}
    provenance_keys: dict[tuple[str, str, str, str], str] = {}
    conflicts: list[dict[str, Any]] = []
    for item in accepted:
        obs_id = item["observation_id"]
        provenance = item["provenance"]
        signature = (
            item["publication_id"],
            item["source"],
            item["window"]["end_at"],
            provenance["source_payload_sha256"],
        )
        previous = provenance_keys.get(signature)
        if previous and previous != obs_id:
            conflicts.append({"observation_id": obs_id, "conflicts_with": previous})
            continue
        provenance_keys[signature] = obs_id
        by_id[obs_id] = item

    # One latest cumulative snapshot per remote publication prevents repeated snapshots
    # from being treated as independent successes.
    latest_by_publication: dict[str, dict[str, Any]] = {}
    for item in by_id.values():
        key = item["publication_id"]
        current = latest_by_publication.get(key)
        if current is None or (item["window"]["end_at"], item["observation_id"]) > (current["window"]["end_at"], current["observation_id"]):
            latest_by_publication[key] = item

    samples: list[tuple[dict[str, Any], float, dict[str, Any]]] = []
    excluded_no_rate: list[str] = []
    for item in sorted(latest_by_publication.values(), key=lambda value: value["observation_id"]):
        signal, basis = _quality_signal(item)
        if signal is None:
            excluded_no_rate.append(item["observation_id"])
            continue
        samples.append((item, signal, basis))

    baseline = round(float(median([signal for _, signal, _ in samples])), 8) if samples else 0.0
    timezone_name = _clean(channel.get("cadence", {}).get("timezone")) if isinstance(channel.get("cadence"), dict) else "UTC"
    try:
        local_tz = ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError:
        local_tz = timezone.utc
        timezone_name = "UTC"

    topic_entries: list[tuple[str, float]] = []
    format_entries: list[tuple[str, float]] = []
    timing_entries: list[tuple[str, float]] = []
    series_entries: list[tuple[str, float]] = []
    sample_basis: list[dict[str, Any]] = []
    for item, signal, basis in samples:
        context = item["publication_context"]
        for topic in context.get("topic_keys", []):
            topic_entries.append((_clean(topic), signal))
        format_entries.append((_clean(context.get("native_format")), signal))
        published_local = _parse_time(context["published_at"]).astimezone(local_tz)
        timing_entries.append((f"hour:{published_local.hour:02d}", signal))
        if _clean(context.get("series_id")):
            series_entries.append((_clean(context.get("series_id")), signal))
        sample_basis.append({
            "observation_id": item["observation_id"],
            "publication_id": item["publication_id"],
            "observed_action_rate": signal,
            **basis,
        })

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": "READY" if samples else "INSUFFICIENT_OBSERVED_DATA",
        "accepted_observations": len(by_id),
        "rejected_observations": rejected,
        "provenance_conflicts": conflicts,
        "latest_publication_samples": len(latest_by_publication),
        "learning_samples": len(samples),
        "excluded_without_observed_denominator_or_actions": excluded_no_rate,
        "baseline": {
            "median_observed_action_rate": baseline,
            "action_metrics": list(LEARNING_ACTION_METRICS),
            "reaction_count_used": False,
            "cross_channel_normalization": False,
        },
        "feedback": {
            "fit_topic_hints": _hint(topic_entries, baseline, min_samples),
            "format_hints": _hint(format_entries, baseline, min_samples),
            "timing_hints": _hint(timing_entries, baseline, min_samples),
            "series_hints": _hint(series_entries, baseline, min_samples),
        },
        "sample_basis": sample_basis,
        "application_policy": {
            "mode": "ADVISORY_ONLY",
            "auto_mutate_channel_config": False,
            "max_future_weight_adjustment_points": 5.0,
            "may_change_editorial_exclusions": False,
            "may_weaken_approval_gates": False,
            "may_override_correction_priority": False,
            "may_compare_across_channels_or_platforms": False,
        },
        "guards": {
            "observed_metrics_only": True,
            "predicted_or_estimated_analytics_used": False,
            "rage_bait_optimization_allowed": False,
            "raw_reactions_optimized": False,
            "instance_isolation": True,
            "channel_learning_independent": True,
            "zero_paid_dependency": True,
        },
        "learning_timezone": timezone_name,
    }
    report["feedback_fingerprint_sha256"] = _digest(report)
    return report


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("observations", type=Path, help="JSON array of observed metric records")
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    channel = _load(args.channel)
    observations = _load(args.observations)
    report = build_feedback(channel, observations, min_samples=args.min_samples)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if report["rejected_observations"] or report["provenance_conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
