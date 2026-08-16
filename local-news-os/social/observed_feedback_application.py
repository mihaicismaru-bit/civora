#!/usr/bin/env python3
"""Bounded application of observed-only learning to LOCAL NEWS OS virality ranking.

The module consumes only feedback reports produced by ``observed_metrics.build_feedback``.
It never fetches analytics, predicts engagement, mutates CHANNEL_CONFIG or weakens any
editorial/publication gate. Invalid or unsafe feedback is fail-closed for *learning*:
it contributes exactly zero ranking points while the underlying editorial publication
path remains unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = "1.0"
MAX_ADJUSTMENT_POINTS = 5.0
HINT_SECTIONS = (
    "fit_topic_hints",
    "format_hints",
    "timing_hints",
    "series_hints",
)
SECRET_TOKENS = {
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "credential",
    "authorization",
    "api_key",
}
PREDICTIVE_TOKENS = {
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
ALLOWED_PREDICTIVE_PATHS = {"guards.predicted_or_estimated_analytics_used"}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _valid_hash(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


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


def _feedback_fingerprint(feedback: dict[str, Any]) -> str:
    payload = _clone(feedback)
    payload.pop("feedback_fingerprint_sha256", None)
    return _digest(payload)


def validate_feedback(channel: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    """Validate a feedback report before it can influence ranking.

    A rejected report is not a publication failure. The caller must treat rejection as
    zero learning influence, preserving the editorial decision that existed without data.
    """
    if not isinstance(channel, dict) or not isinstance(feedback, dict):
        raise TypeError("channel and feedback must be mappings")

    blocks: list[str] = []
    if _clean(feedback.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("FEEDBACK_SCHEMA_VERSION")

    for key, code in (
        ("instance_id", "INSTANCE_MISMATCH"),
        ("channel_id", "CHANNEL_MISMATCH"),
    ):
        expected = _clean(channel.get(key))
        actual = _clean(feedback.get(key))
        if not expected or not actual:
            blocks.append("MISSING_" + key.upper())
        elif expected != actual:
            blocks.append(code)

    expected_platform = _clean(channel.get("platform")).lower()
    actual_platform = _clean(feedback.get("platform")).lower()
    if not expected_platform or not actual_platform:
        blocks.append("MISSING_PLATFORM")
    elif expected_platform != actual_platform:
        blocks.append("PLATFORM_MISMATCH")

    channel_metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if channel_metrics.get("observed_only") is not True:
        blocks.append("CHANNEL_METRICS_NOT_OBSERVED_ONLY")
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")

    status = _clean(feedback.get("status")).upper()
    if status not in {"READY", "INSUFFICIENT_OBSERVED_DATA"}:
        blocks.append("INVALID_FEEDBACK_STATUS")

    rejected = feedback.get("rejected_observations")
    if not isinstance(rejected, list):
        blocks.append("INVALID_REJECTED_OBSERVATIONS")
    elif rejected:
        blocks.append("FEEDBACK_CONTAINS_REJECTED_OBSERVATIONS")
    conflicts = feedback.get("provenance_conflicts")
    if not isinstance(conflicts, list):
        blocks.append("INVALID_PROVENANCE_CONFLICTS")
    elif conflicts:
        blocks.append("FEEDBACK_PROVENANCE_CONFLICTS")

    baseline = feedback.get("baseline") if isinstance(feedback.get("baseline"), dict) else None
    if baseline is None:
        blocks.append("MISSING_FEEDBACK_BASELINE")
    else:
        if baseline.get("reaction_count_used") is not False:
            blocks.append("REACTION_COUNT_OPTIMIZATION_FORBIDDEN")
        if baseline.get("cross_channel_normalization") is not False:
            blocks.append("CROSS_CHANNEL_NORMALIZATION_FORBIDDEN")

    policy = feedback.get("application_policy") if isinstance(feedback.get("application_policy"), dict) else None
    max_points = MAX_ADJUSTMENT_POINTS
    if policy is None:
        blocks.append("MISSING_APPLICATION_POLICY")
    else:
        if _clean(policy.get("mode")).upper() != "ADVISORY_ONLY":
            blocks.append("APPLICATION_POLICY_NOT_ADVISORY")
        if policy.get("auto_mutate_channel_config") is not False:
            blocks.append("CHANNEL_CONFIG_MUTATION_FORBIDDEN")
        candidate_max = policy.get("max_future_weight_adjustment_points")
        if not _number(candidate_max) or float(candidate_max) < 0.0 or float(candidate_max) > MAX_ADJUSTMENT_POINTS:
            blocks.append("UNSAFE_MAX_ADJUSTMENT")
        else:
            max_points = float(candidate_max)
        for key, code in (
            ("may_change_editorial_exclusions", "EDITORIAL_EXCLUSION_MUTATION_FORBIDDEN"),
            ("may_weaken_approval_gates", "APPROVAL_GATE_WEAKENING_FORBIDDEN"),
            ("may_override_correction_priority", "CORRECTION_PRIORITY_OVERRIDE_FORBIDDEN"),
            ("may_compare_across_channels_or_platforms", "CROSS_CHANNEL_COMPARISON_FORBIDDEN"),
        ):
            if policy.get(key) is not False:
                blocks.append(code)

    guards = feedback.get("guards") if isinstance(feedback.get("guards"), dict) else None
    if guards is None:
        blocks.append("MISSING_FEEDBACK_GUARDS")
    else:
        expected_guards = {
            "observed_metrics_only": True,
            "predicted_or_estimated_analytics_used": False,
            "rage_bait_optimization_allowed": False,
            "raw_reactions_optimized": False,
            "instance_isolation": True,
            "channel_learning_independent": True,
            "zero_paid_dependency": True,
        }
        for key, expected in expected_guards.items():
            if guards.get(key) is not expected:
                blocks.append("UNSAFE_GUARD:" + key)

    key_paths = _walk_keys(feedback)
    secret_paths = sorted(path for path, key in key_paths if _contains_token(key, SECRET_TOKENS))
    predictive_paths = sorted(
        path
        for path, key in key_paths
        if path not in ALLOWED_PREDICTIVE_PATHS and _contains_token(key, PREDICTIVE_TOKENS)
    )
    if secret_paths:
        blocks.append("SECRET_LIKE_FIELD_PRESENT")
    if predictive_paths:
        blocks.append("PREDICTIVE_OR_ESTIMATED_ANALYTICS_PRESENT")

    hint_payload = feedback.get("feedback") if isinstance(feedback.get("feedback"), dict) else None
    if hint_payload is None:
        blocks.append("MISSING_FEEDBACK_HINTS")
    else:
        for section in HINT_SECTIONS:
            hints = hint_payload.get(section)
            if not isinstance(hints, list):
                blocks.append("INVALID_HINT_SECTION:" + section)
                continue
            seen: set[str] = set()
            for hint in hints:
                if not isinstance(hint, dict):
                    blocks.append("INVALID_HINT:" + section)
                    continue
                key = _clean(hint.get("key"))
                if not key:
                    blocks.append("MISSING_HINT_KEY:" + section)
                    continue
                if key in seen:
                    blocks.append("DUPLICATE_HINT_KEY:" + section + ":" + key)
                seen.add(key)
                samples = hint.get("samples")
                if not isinstance(samples, int) or isinstance(samples, bool) or samples < 2:
                    blocks.append("INVALID_HINT_SAMPLES:" + section + ":" + key)
                points = hint.get("bounded_adjustment_points")
                if not _number(points) or abs(float(points)) > max_points + 1e-9:
                    blocks.append("UNBOUNDED_HINT:" + section + ":" + key)
                    continue
                points_value = float(points)
                recommendation = _clean(hint.get("recommendation")).lower()
                expected_recommendation = "neutral"
                if points_value >= 1.0:
                    expected_recommendation = "consider_more"
                elif points_value <= -1.0:
                    expected_recommendation = "consider_less"
                if recommendation != expected_recommendation:
                    blocks.append("HINT_RECOMMENDATION_MISMATCH:" + section + ":" + key)

    supplied_fingerprint = _clean(feedback.get("feedback_fingerprint_sha256")).lower()
    if not _valid_hash(supplied_fingerprint):
        blocks.append("INVALID_FEEDBACK_FINGERPRINT")
    elif supplied_fingerprint != _feedback_fingerprint(feedback):
        blocks.append("FEEDBACK_FINGERPRINT_MISMATCH")

    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not blocks,
        "hard_blocks": sorted(set(blocks)),
        "feedback_fingerprint_sha256": supplied_fingerprint if _valid_hash(supplied_fingerprint) else None,
        "max_adjustment_points": round(max_points, 2),
        "status": status or None,
    }


def _hint_map(feedback: dict[str, Any], section: str) -> dict[str, float]:
    payload = feedback.get("feedback") if isinstance(feedback.get("feedback"), dict) else {}
    hints = payload.get(section) if isinstance(payload.get(section), list) else []
    return {
        _clean(item.get("key")): float(item.get("bounded_adjustment_points"))
        for item in hints
        if isinstance(item, dict) and _clean(item.get("key")) and _number(item.get("bounded_adjustment_points"))
    }


def _story_topics(story: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for key in ("topics", "topic_ids", "topic_keys"):
        raw = story.get(key)
        if isinstance(raw, list):
            values.update(_clean(item) for item in raw if _clean(item))
    return sorted(values)


def _timing_key(channel: dict[str, Any], cadence: dict[str, Any] | None) -> str | None:
    if not isinstance(cadence, dict):
        return None
    instant = _clean(cadence.get("evaluated_at"))
    timezone_name = _clean(channel.get("cadence", {}).get("timezone")) if isinstance(channel.get("cadence"), dict) else ""
    if not instant or not timezone_name:
        return None
    try:
        parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return f"hour:{parsed.astimezone(zone).hour:02d}"


def _series_id(story: dict[str, Any], series: dict[str, Any] | None) -> str | None:
    if not isinstance(series, dict) or series.get("eligible") is not True or _clean(series.get("decision")) != "SERIES_READY":
        return None
    occurrence = series.get("occurrence") if isinstance(series.get("occurrence"), dict) else {}
    selected = occurrence.get("selected_story_ids") if isinstance(occurrence.get("selected_story_ids"), list) else []
    story_id = _clean(story.get("story_id") or story.get("id"))
    if story_id and story_id not in {_clean(value) for value in selected if _clean(value)}:
        return None
    return _clean(occurrence.get("series_id")) or None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def apply_observed_feedback(
    channel: dict[str, Any],
    feedback: dict[str, Any] | None,
    story: dict[str, Any],
    format_result: dict[str, Any],
    *,
    cadence: dict[str, Any] | None = None,
    series: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded ranking adjustment derived from safe observed feedback.

    The final adjustment is the arithmetic mean of the matching topic, format, timing
    and recurring-series hints, then clamped to the report's maximum (never over 5).
    Averaging prevents several dimensions from stacking into an unbounded optimization.
    """
    if not all(isinstance(value, dict) for value in (channel, story, format_result)):
        raise TypeError("channel, story and format_result must be mappings")
    if feedback is not None and not isinstance(feedback, dict):
        raise TypeError("feedback must be a mapping when provided")
    for name, value in (("cadence", cadence), ("series", series)):
        if value is not None and not isinstance(value, dict):
            raise TypeError(f"{name} must be a mapping when provided")

    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": "NO_FEEDBACK",
        "applied": False,
        "bounded_adjustment_points": 0.0,
        "matched_dimensions": [],
        "feedback_blocks": [],
        "feedback_fingerprint_sha256": None,
        "policy": {
            "mode": "ADVISORY_ONLY",
            "max_absolute_adjustment_points": MAX_ADJUSTMENT_POINTS,
            "combine_method": "MEAN_MATCHING_DIMENSIONS",
            "invalid_feedback_publication_effect": "ZERO_LEARNING_INFLUENCE",
        },
        "guards": {
            "observed_metrics_only": True,
            "predicted_or_estimated_analytics_used": False,
            "raw_reactions_optimized": False,
            "cross_channel_comparison_used": False,
            "channel_config_mutated": False,
            "editorial_gates_weakened": False,
            "publication_blocked_by_learning": False,
            "zero_paid_dependency": True,
        },
    }
    if feedback is None:
        base["application_fingerprint_sha256"] = _digest(base)
        return base

    validation = validate_feedback(channel, feedback)
    base["feedback_fingerprint_sha256"] = validation.get("feedback_fingerprint_sha256")
    base["policy"]["max_absolute_adjustment_points"] = validation.get("max_adjustment_points", MAX_ADJUSTMENT_POINTS)
    if not validation["valid"]:
        base["status"] = "IGNORED_INVALID"
        base["feedback_blocks"] = validation["hard_blocks"]
        base["application_fingerprint_sha256"] = _digest(base)
        return base
    if validation["status"] != "READY":
        base["status"] = "INSUFFICIENT_OBSERVED_DATA"
        base["application_fingerprint_sha256"] = _digest(base)
        return base

    topic_map = _hint_map(feedback, "fit_topic_hints")
    format_map = _hint_map(feedback, "format_hints")
    timing_map = _hint_map(feedback, "timing_hints")
    series_map = _hint_map(feedback, "series_hints")
    dimensions: list[dict[str, Any]] = []

    matched_topics = [topic for topic in _story_topics(story) if topic in topic_map]
    if matched_topics:
        dimensions.append({
            "dimension": "topic",
            "keys": matched_topics,
            "adjustment_points": round(_mean([topic_map[key] for key in matched_topics]), 4),
        })

    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    native_format = _clean(product.get("native_format"))
    if native_format and native_format in format_map:
        dimensions.append({
            "dimension": "format",
            "keys": [native_format],
            "adjustment_points": round(format_map[native_format], 4),
        })

    timing_key = _timing_key(channel, cadence)
    if timing_key and timing_key in timing_map:
        dimensions.append({
            "dimension": "timing",
            "keys": [timing_key],
            "adjustment_points": round(timing_map[timing_key], 4),
        })

    series_id = _series_id(story, series)
    if series_id and series_id in series_map:
        dimensions.append({
            "dimension": "series",
            "keys": [series_id],
            "adjustment_points": round(series_map[series_id], 4),
        })

    max_points = float(validation.get("max_adjustment_points", MAX_ADJUSTMENT_POINTS))
    combined = _mean([float(item["adjustment_points"]) for item in dimensions]) if dimensions else 0.0
    combined = round(max(-max_points, min(max_points, combined)), 2)
    base["matched_dimensions"] = dimensions
    base["bounded_adjustment_points"] = combined
    base["applied"] = bool(dimensions)
    base["status"] = "APPLIED" if dimensions else "NO_MATCHING_HINTS"
    base["application_fingerprint_sha256"] = _digest(base)
    return base


def _band(score: float) -> str:
    if score >= 75.0:
        return "strong"
    if score >= 60.0:
        return "useful"
    if score >= 45.0:
        return "modest"
    return "low"


def _publication_action(score: float, channel: dict[str, Any], cadence: dict[str, Any] | None, blocked: bool) -> str:
    if blocked:
        return "BLOCKED"
    if _clean(channel.get("status")) == "outbox_only":
        return "OUTBOX_ONLY"
    if cadence is not None and cadence.get("eligible") is not True:
        return "HOLD_TIMING"
    if score >= 75.0:
        return "PRIORITIZE"
    if score >= 55.0:
        return "ELIGIBLE"
    return "ELIGIBLE_LOW_PRIORITY"


def apply_to_virality(
    channel: dict[str, Any],
    feedback: dict[str, Any] | None,
    story: dict[str, Any],
    format_result: dict[str, Any],
    base_virality: dict[str, Any],
    *,
    cadence: dict[str, Any] | None = None,
    series: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a valid observed-feedback adjustment without changing hard gates.

    The returned bundle keeps the feedback audit separate from the virality decision.
    When feedback is absent, invalid, insufficient, unmatched, or the base decision is
    already blocked, ``virality`` is byte-for-byte-equivalent as a JSON object to the
    supplied base decision. This avoids dedupe/state churn from unusable analytics.
    """
    if not isinstance(base_virality, dict):
        raise TypeError("base_virality must be a mapping")
    application = apply_observed_feedback(
        channel,
        feedback,
        story,
        format_result,
        cadence=cadence,
        series=series,
    )
    base = _clone(base_virality)
    effective = application.get("applied") is True and base.get("blocked") is not True
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "effective_applied": effective,
        "feedback_application": application,
        "virality": base,
    }
    if not effective:
        bundle["bundle_fingerprint_sha256"] = _digest(bundle)
        return bundle

    adjustment = float(application.get("bounded_adjustment_points", 0.0) or 0.0)
    original_score = float(base.get("score", 0.0) or 0.0)
    adjusted_score = round(max(0.0, min(100.0, original_score + adjustment)), 2)

    components = base.get("components") if isinstance(base.get("components"), dict) else {}
    components = _clone(components)
    components["observed_feedback"] = round(adjustment, 2)
    base["components"] = components
    base["score"] = adjusted_score
    base["band"] = _band(adjusted_score)
    base["publication_action"] = _publication_action(
        adjusted_score,
        channel,
        cadence,
        bool(base.get("blocked")),
    )

    reasons = base.get("reasons") if isinstance(base.get("reasons"), list) else []
    reasons = [str(value) for value in reasons]
    reasons.append(f"OBSERVED_FEEDBACK_APPLIED:{adjustment:+.2f}")
    base["reasons"] = reasons

    analytics = base.get("analytics") if isinstance(base.get("analytics"), dict) else {}
    analytics = _clone(analytics)
    analytics["observed_metrics_used"] = True
    analytics["observed_feedback_adjustment_points"] = round(adjustment, 2)
    analytics["observed_feedback_fingerprint_sha256"] = application.get("feedback_fingerprint_sha256")
    analytics["predicted_analytics_used_for_feedback"] = False
    base["analytics"] = analytics

    guards = base.get("guards") if isinstance(base.get("guards"), dict) else {}
    guards = _clone(guards)
    guards["editorial_gates_weakened"] = False
    guards["observed_feedback_bounded"] = True
    guards["raw_reactions_optimized"] = False
    guards["cross_channel_learning_used"] = False
    guards["zero_paid_dependency"] = True
    base["guards"] = guards

    previous_fingerprint = _clean(base.get("decision_fingerprint_sha256")) or None
    base["base_virality_decision_fingerprint_sha256"] = previous_fingerprint
    base.pop("decision_fingerprint_sha256", None)
    base["decision_fingerprint_sha256"] = _digest(base)
    bundle["virality"] = base
    bundle["bundle_fingerprint_sha256"] = _digest(bundle)
    return bundle


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("feedback", type=Path)
    parser.add_argument("story", type=Path)
    parser.add_argument("format_result", type=Path)
    parser.add_argument("--cadence", type=Path)
    parser.add_argument("--series", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = apply_observed_feedback(
        _load(args.channel),
        _load(args.feedback),
        _load(args.story),
        _load(args.format_result),
        cadence=_load(args.cadence) if args.cadence else None,
        series=_load(args.series) if args.series else None,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] != "IGNORED_INVALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
