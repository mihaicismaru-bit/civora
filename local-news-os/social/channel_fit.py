#!/usr/bin/env python3
"""Deterministic, dependency-free channel fit scorer for LOCAL NEWS OS.

The scorer consumes a normalized STORY_OBJECT-like mapping plus a CHANNEL_CONFIG
and returns an auditable 0..100 fit score with hard-block reasons separated from
ranking. It never invents engagement metrics and never weakens editorial gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


RECOMMENDATION_THRESHOLDS = (
    (70.0, "primary"),
    (55.0, "eligible"),
    (40.0, "low_fit"),
    (0.0, "skip"),
)


def _as_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _bounded_number(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _topic_score(topics: set[str], priorities: list[str]) -> tuple[float, list[str]]:
    if not topics or not priorities:
        return 0.0, []
    matched: list[str] = []
    best = 0.0
    total = max(1, len(priorities))
    for index, topic in enumerate(priorities):
        if topic not in topics:
            continue
        matched.append(topic)
        # Earlier CHANNEL_CONFIG priorities carry more weight, but even the last
        # listed priority remains useful. Range: 21..35 for the best match.
        rank_fraction = 1.0 - (index / max(1, total - 1)) if total > 1 else 1.0
        best = max(best, 21.0 + 14.0 * rank_fraction)
    # A second matched priority adds bounded breadth without swamping quality.
    if len(matched) > 1:
        best = min(35.0, best + min(4.0, float(len(matched) - 1) * 2.0))
    return round(best, 2), matched


def _format_score(story_formats: set[str], native_formats: set[str]) -> tuple[float, list[str]]:
    matches = sorted(story_formats & native_formats)
    if not matches:
        return 0.0, []
    # One native-ready format is sufficient for full fit; additional matches are
    # recorded for downstream format selection, not rewarded as engagement bait.
    return 15.0, matches


def _recommend(score: float, blocked: bool) -> str:
    if blocked:
        return "blocked"
    for threshold, label in RECOMMENDATION_THRESHOLDS:
        if score >= threshold:
            return label
    return "skip"


def score_story(story: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    """Score one normalized story against one CHANNEL_CONFIG.

    Expected optional story fields:
      instance_id, story_id/id, topics[], risk_flags[], available_formats[],
      confidence (0..100), locality (0..1), utility (0..1), share_value (0..1),
      urgency (0..1), material_fact_gate, human_approved, correction.

    Missing soft-signal fields default conservatively. Hard editorial/isolation
    constraints always fail closed.
    """
    reasons: list[str] = []
    hard_blocks: list[str] = []

    channel_instance = str(channel.get("instance_id", "")).strip()
    story_instance = str(story.get("instance_id", "")).strip()
    if story_instance and channel_instance and story_instance != channel_instance:
        hard_blocks.append("INSTANCE_MISMATCH")

    status = str(channel.get("status", "")).strip()
    if status not in {"active", "outbox_only"}:
        hard_blocks.append("CHANNEL_NOT_ACTIVE")

    exclusions = _as_set(channel.get("editorial_mix", {}).get("exclusions"))
    risk_flags = _as_set(story.get("risk_flags"))
    excluded_hits = sorted(exclusions & risk_flags)
    if excluded_hits:
        hard_blocks.append("CHANNEL_EXCLUSION:" + ",".join(excluded_hits))

    gate = str(story.get("material_fact_gate", "PASS")).upper().strip()
    if gate.startswith("FAIL") or gate.startswith("HOLD") or gate in {"BLOCK", "BLOCKED"}:
        hard_blocks.append("MATERIAL_FACT_GATE")

    approval = channel.get("approval_gates", {})
    reputational = bool({"reputational", "accusation", "personal_harm"} & risk_flags)
    if reputational and bool(approval.get("reputational_human", True)) and story.get("human_approved") is not True:
        hard_blocks.append("HUMAN_APPROVAL_REQUIRED")

    if story.get("correction") is True and bool(approval.get("corrections_priority", True)):
        reasons.append("CORRECTION_PRIORITY")

    topics = _as_set(story.get("topics"))
    priorities = [str(x) for x in channel.get("editorial_mix", {}).get("priorities", []) if str(x)]
    topic_points, matched_topics = _topic_score(topics, priorities)
    if matched_topics:
        reasons.append("TOPIC_MATCH:" + ",".join(matched_topics))
    else:
        reasons.append("NO_PRIORITY_TOPIC_MATCH")

    story_formats = _as_set(story.get("available_formats")) or {"text"}
    native_formats = _as_set(channel.get("native_formats"))
    format_points, matched_formats = _format_score(story_formats, native_formats)
    if matched_formats:
        reasons.append("NATIVE_FORMAT:" + ",".join(matched_formats))
    else:
        reasons.append("NO_NATIVE_FORMAT_READY")

    confidence = _bounded_number(story.get("confidence"), 0.0, 100.0, 70.0)
    confidence_points = 15.0 * confidence / 100.0
    if confidence < 80.0:
        reasons.append("CONFIDENCE_BELOW_80")

    locality = _bounded_number(story.get("locality"), 0.0, 1.0, 0.5)
    utility = _bounded_number(story.get("utility"), 0.0, 1.0, 0.5)
    share_value = _bounded_number(story.get("share_value"), 0.0, 1.0, 0.35)
    urgency = _bounded_number(story.get("urgency"), 0.0, 1.0, 0.25)

    components = {
        "topic_alignment": round(topic_points, 2),
        "native_format_ready": round(format_points, 2),
        "confidence": round(confidence_points, 2),
        "locality": round(locality * 10.0, 2),
        "utility": round(utility * 10.0, 2),
        "share_value": round(share_value * 10.0, 2),
        "urgency": round(urgency * 5.0, 2),
    }
    score = round(min(100.0, sum(components.values())), 2)

    # Corrections are promoted operationally, never by fabricating a higher fit
    # score. Downstream schedulers can prioritize on the explicit reason code.
    blocked = bool(hard_blocks)
    return {
        "schema_version": "1.0",
        "story_id": str(story.get("story_id") or story.get("id") or "unknown"),
        "channel_id": str(channel.get("channel_id") or channel.get("platform") or "unknown"),
        "instance_id": channel_instance or story_instance or None,
        "score": score,
        "recommendation": _recommend(score, blocked),
        "blocked": blocked,
        "hard_blocks": hard_blocks,
        "matched_topics": matched_topics,
        "matched_formats": matched_formats,
        "components": components,
        "reasons": reasons,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story", type=Path, help="normalized STORY_OBJECT JSON")
    parser.add_argument("channel", type=Path, help="CHANNEL_CONFIG JSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = score_story(_load(args.story), _load(args.channel))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if not result["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
