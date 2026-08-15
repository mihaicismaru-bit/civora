#!/usr/bin/env python3
"""Deterministic, non-clickbait Virality Engine for LOCAL NEWS OS.

The engine ranks already-verified, channel-native publication products using only
explicit editorial signals and upstream decisions. It never predicts views,
engagement, virality probability, CTR, reach, followers or any other analytics.
Editorial, identity, provenance and anti-clickbait gates remain fail-closed and
are kept separate from ranking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


FORBIDDEN_TACTICS = {
    "rage_bait",
    "fake_urgency",
    "fake_exclusivity",
    "misleading_thumbnail",
    "engagement_fabricated",
    "invented_analytics",
    "synthetic_real_person_imagery",
    "verbatim_cross_posting",
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

LIFECYCLE_STAGES = {
    "baseline",
    "breaking",
    "developing",
    "follow_up",
    "event_live",
    "evergreen",
    "correction",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _bounded(value: Any, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, number)) * maximum, 2)


def _id(value: dict[str, Any], key: str) -> str:
    return _clean(value.get(key))


def _identity_blocks(
    story: dict[str, Any],
    channel: dict[str, Any],
    fit: dict[str, Any],
    hook: dict[str, Any],
    format_result: dict[str, Any],
    visual: dict[str, Any] | None,
    cadence: dict[str, Any] | None,
    series: dict[str, Any] | None,
) -> list[str]:
    blocks: list[str] = []
    instance_id = _id(channel, "instance_id")
    channel_id = _id(channel, "channel_id")
    story_id = _id(story, "story_id") or _id(story, "id")
    if not instance_id:
        blocks.append("MISSING_INSTANCE_ID")
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    if not story_id:
        blocks.append("MISSING_STORY_ID")

    objects = [story, fit, hook, format_result]
    if visual is not None:
        objects.append(visual)
    if cadence is not None:
        objects.append(cadence)
    if series is not None:
        objects.append(series)

    for obj in objects:
        obj_instance = _id(obj, "instance_id")
        if obj_instance and instance_id and obj_instance != instance_id:
            blocks.append("INSTANCE_MISMATCH")
        obj_story = _id(obj, "story_id")
        if obj_story and story_id and obj_story != story_id:
            blocks.append("STORY_MISMATCH")
        obj_channel = _id(obj, "channel_id")
        if obj_channel and channel_id and obj_channel != channel_id:
            blocks.append("CHANNEL_MISMATCH")
    return sorted(set(blocks))


def _safety_blocks(
    story: dict[str, Any],
    channel: dict[str, Any],
    fit: dict[str, Any],
    hook: dict[str, Any],
    format_result: dict[str, Any],
    visual: dict[str, Any] | None,
    cadence: dict[str, Any] | None,
    series: dict[str, Any] | None,
) -> list[str]:
    blocks: list[str] = []
    if _clean(channel.get("status")) not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")

    gate = _clean(story.get("material_fact_gate")).upper()
    if not gate.startswith("PASS"):
        blocks.append("MATERIAL_FACT_GATE")

    risk_flags = {
        _clean(value)
        for value in story.get("risk_flags", [])
        if _clean(value)
    } if isinstance(story.get("risk_flags"), list) else set()
    channel_exclusions = {
        _clean(value)
        for value in channel.get("editorial_mix", {}).get("exclusions", [])
        if _clean(value)
    }
    forbidden_hits = sorted(risk_flags & (FORBIDDEN_TACTICS | channel_exclusions))
    if forbidden_hits:
        blocks.append("FORBIDDEN_TACTIC:" + ",".join(forbidden_hits))

    if fit.get("blocked") is True or _clean(fit.get("recommendation")) == "blocked":
        blocks.append("CHANNEL_FIT_BLOCKED")
    if _clean(fit.get("recommendation")) == "skip":
        blocks.append("CHANNEL_FIT_SKIP")

    if hook.get("blocked") is True:
        blocks.append("HOOK_BLOCKED")
    hook_payload = hook.get("hook") if isinstance(hook.get("hook"), dict) else {}
    if not hook_payload:
        blocks.append("MISSING_SAFE_HOOK")
    else:
        if hook_payload.get("source_preserving") is not True:
            blocks.append("HOOK_NOT_SOURCE_PRESERVING")
        if _clean(hook_payload.get("clickbait_guard")) != "PASS":
            blocks.append("HOOK_CLICKBAIT_GUARD")
        if hook_payload.get("invented_claims_allowed") is not False:
            blocks.append("HOOK_INVENTED_CLAIMS_POLICY")

    if format_result.get("blocked") is True:
        blocks.append("FORMAT_BLOCKED")
    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    if not product:
        blocks.append("MISSING_NATIVE_PRODUCT")
    else:
        if _clean(product.get("cross_post_policy")) != "NATIVE_PRODUCT_ONLY":
            blocks.append("INVALID_CROSS_POST_POLICY")
        if product.get("verbatim_cross_platform_reuse_allowed") is not False:
            blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
        if product.get("invented_claims_allowed") is not False:
            blocks.append("FORMAT_INVENTED_CLAIMS_POLICY")
        visual_req = product.get("visual_requirement") if isinstance(product.get("visual_requirement"), dict) else {}
        if visual_req.get("required") is True:
            if visual is None:
                blocks.append("VISUAL_BINDING_REQUIRED")
            else:
                if visual.get("blocked") is True:
                    blocks.append("VISUAL_BLOCKED")
                binding = visual.get("binding") if isinstance(visual.get("binding"), dict) else {}
                if _clean(binding.get("status")) != "VISUAL_READY":
                    blocks.append("VISUAL_NOT_READY")
                if binding.get("synthetic_media_used") is not False:
                    blocks.append("SYNTHETIC_MEDIA_USED")
                if binding.get("provenance_complete") is not True:
                    blocks.append("VISUAL_PROVENANCE_INCOMPLETE")
                if binding.get("reuse_rights_complete") is not True:
                    blocks.append("VISUAL_RIGHTS_INCOMPLETE")

    if cadence is not None and cadence.get("hard_blocks"):
        blocks.append("CADENCE_HARD_BLOCK")
    if series is not None and series.get("hard_blocks"):
        blocks.append("SERIES_HARD_BLOCK")

    stage = _clean(story.get("lifecycle_stage") or "baseline").lower()
    if stage not in LIFECYCLE_STAGES:
        blocks.append("INVALID_LIFECYCLE_STAGE")
    if stage == "breaking" and story.get("verified_breaking") is not True:
        blocks.append("UNVERIFIED_BREAKING_STAGE")
    if stage == "event_live" and story.get("verified_event") is not True:
        blocks.append("UNVERIFIED_EVENT_LIFECYCLE")

    return sorted(set(blocks))


def _hook_points(hook: dict[str, Any]) -> float:
    payload = hook.get("hook") if isinstance(hook.get("hook"), dict) else {}
    if payload.get("source_preserving") is not True or _clean(payload.get("clickbait_guard")) != "PASS":
        return 0.0
    atom_type = _clean(payload.get("source_atom_type"))
    return {
        "headline": 7.0,
        "fact": 7.0,
        "dek": 6.0,
        "paragraph": 4.0,
        "quote": 3.0,
    }.get(atom_type, 2.0)


def _native_points(format_result: dict[str, Any]) -> float:
    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    if (
        _clean(product.get("format_status")) == "FORMAT_READY"
        and _clean(product.get("native_format"))
        and _clean(product.get("cross_post_policy")) == "NATIVE_PRODUCT_ONLY"
        and product.get("verbatim_cross_platform_reuse_allowed") is False
    ):
        return 5.0
    return 0.0


def _timing_points(cadence: dict[str, Any] | None) -> float:
    if cadence is None:
        return 0.0
    if cadence.get("eligible") is True and _clean(cadence.get("decision")) in {"PUBLISH_NOW", "PUBLISH_CORRECTION_PRIORITY"}:
        return 5.0
    return 0.0


def _series_points(story_id: str, series: dict[str, Any] | None) -> float:
    if series is None or series.get("eligible") is not True or _clean(series.get("decision")) != "SERIES_READY":
        return 0.0
    occurrence = series.get("occurrence") if isinstance(series.get("occurrence"), dict) else {}
    selected = occurrence.get("selected_story_ids") if isinstance(occurrence.get("selected_story_ids"), list) else []
    return 3.0 if story_id in {_clean(value) for value in selected} else 0.0


def _lifecycle_points(story: dict[str, Any]) -> tuple[float, list[str], str]:
    stage = _clean(story.get("lifecycle_stage") or "baseline").lower()
    reasons: list[str] = []
    action = "standalone"
    if story.get("correction") is True or stage == "correction":
        return 4.0, ["CORRECTION_PROPAGATION_PRIORITY"], "correction_propagation"
    if stage == "breaking" and story.get("verified_breaking") is True:
        return 4.0, ["VERIFIED_BREAKING_LIFECYCLE"], "publish_or_update"
    if stage == "developing":
        if story.get("material_update") is True:
            return 3.0, ["MATERIAL_DEVELOPING_UPDATE"], "follow_up"
        reasons.append("DEVELOPING_WITHOUT_MATERIAL_UPDATE")
        return 1.0, reasons, action
    if stage == "follow_up":
        if story.get("material_update") is True:
            return 4.0, ["MATERIAL_FOLLOW_UP"], "follow_up"
        reasons.append("FOLLOW_UP_NOT_MATERIAL")
        return 0.0, reasons, action
    if stage == "event_live" and story.get("verified_event") is True:
        return 3.0, ["VERIFIED_EVENT_LIFECYCLE"], "publish_or_update"
    if stage == "evergreen":
        if story.get("evergreen") is True:
            return 2.0, ["EVERGREEN_RESURFACE_ELIGIBLE"], "resurface"
        reasons.append("EVERGREEN_NOT_DECLARED")
        return 0.0, reasons, action
    return 1.0, ["BASELINE_STANDALONE"], action


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


def score_virality(
    story: dict[str, Any],
    channel: dict[str, Any],
    fit: dict[str, Any],
    hook: dict[str, Any],
    format_result: dict[str, Any],
    *,
    visual: dict[str, Any] | None = None,
    cadence: dict[str, Any] | None = None,
    series: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rank one channel-native product without predicting engagement.

    Soft story signals are explicit editorial assessments in the 0..1 range:
    proximity/locality, utility, share_value, save_value, conversation_value.
    Missing soft signals contribute zero instead of being guessed.
    """
    required = (story, channel, fit, hook, format_result)
    if not all(isinstance(value, dict) for value in required):
        raise TypeError("story, channel, fit, hook and format_result must be mappings")
    for name, value in (("visual", visual), ("cadence", cadence), ("series", series)):
        if value is not None and not isinstance(value, dict):
            raise TypeError(f"{name} must be a mapping when provided")

    story_id = _id(story, "story_id") or _id(story, "id")
    instance_id = _id(channel, "instance_id") or _id(story, "instance_id")
    channel_id = _id(channel, "channel_id")
    blocks = _identity_blocks(story, channel, fit, hook, format_result, visual, cadence, series)
    blocks.extend(_safety_blocks(story, channel, fit, hook, format_result, visual, cadence, series))
    blocks = sorted(set(blocks))

    ignored_predictive = sorted(key for key in PREDICTIVE_FIELDS if key in story)
    reasons: list[str] = []
    if ignored_predictive:
        reasons.append("PREDICTIVE_ANALYTICS_IGNORED:" + ",".join(ignored_predictive))

    fit_score = max(0.0, min(100.0, float(fit.get("score", 0.0) or 0.0)))
    lifecycle_points, lifecycle_reasons, lifecycle_action = _lifecycle_points(story)
    reasons.extend(lifecycle_reasons)
    components = {
        "channel_fit": round(fit_score * 0.24, 2),
        "proximity": _bounded(story.get("proximity", story.get("locality")), 12.0),
        "utility": _bounded(story.get("utility"), 12.0),
        "share_value": _bounded(story.get("share_value"), 12.0),
        "save_value": _bounded(story.get("save_value"), 8.0),
        "conversation_value": _bounded(story.get("conversation_value"), 8.0),
        "first_frame": _hook_points(hook),
        "native_format": _native_points(format_result),
        "timing": _timing_points(cadence),
        "recurring_series": _series_points(story_id, series),
        "lifecycle": lifecycle_points,
    }
    score = round(min(100.0, sum(components.values())), 2)

    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    lifecycle_stage = _clean(story.get("lifecycle_stage") or ("correction" if story.get("correction") is True else "baseline")).lower()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "instance_id": instance_id or None,
        "story_id": story_id or None,
        "channel_id": channel_id or None,
        "platform": _clean(channel.get("platform")) or None,
        "product_id": _clean(product.get("product_id")) or None,
        "blocked": bool(blocks),
        "hard_blocks": blocks,
        "score": score,
        "band": _band(score),
        "components": components,
        "reasons": reasons,
        "publication_action": _publication_action(score, channel, cadence, bool(blocks)),
        "lifecycle": {
            "stage": lifecycle_stage,
            "action": lifecycle_action,
            "material_update": story.get("material_update") is True,
            "verified_breaking": story.get("verified_breaking") is True,
            "verified_event": story.get("verified_event") is True,
            "evergreen": story.get("evergreen") is True,
        },
        "cross_channel_handoff": {
            "policy": "RE_ATOMIZE_FROM_SHARED_FACT_KERNEL",
            "verbatim_reuse_allowed": False,
            "reuse_current_social_copy": False,
            "candidate_channel_ids": sorted({_clean(x) for x in story.get("handoff_channel_ids", []) if _clean(x)}) if isinstance(story.get("handoff_channel_ids"), list) else [],
            "requires_independent_channel_fit": True,
            "requires_independent_hook_and_format": True,
        },
        "analytics": {
            "predictive_analytics_used": False,
            "observed_metrics_used": False,
            "ignored_predictive_fields": ignored_predictive,
        },
        "guards": {
            "editorial_gates_weakened": False,
            "rage_bait_allowed": False,
            "fake_urgency_allowed": False,
            "fake_exclusivity_allowed": False,
            "misleading_thumbnail_allowed": False,
            "fabricated_engagement_allowed": False,
            "zero_paid_dependency": True,
        },
    }
    result["decision_fingerprint_sha256"] = _digest(result)
    return result


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("fit", type=Path)
    parser.add_argument("hook", type=Path)
    parser.add_argument("format_result", type=Path)
    parser.add_argument("--visual", type=Path)
    parser.add_argument("--cadence", type=Path)
    parser.add_argument("--series", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = score_virality(
        _load(args.story),
        _load(args.channel),
        _load(args.fit),
        _load(args.hook),
        _load(args.format_result),
        visual=_load(args.visual) if args.visual else None,
        cadence=_load(args.cadence) if args.cadence else None,
        series=_load(args.series) if args.series else None,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
