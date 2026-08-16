#!/usr/bin/env python3
"""Channel-native recurring-series compositor for LOCAL NEWS OS.

The compositor consumes one durable ``SERIES_COMPOSITION_PENDING`` handoff plus
verified STORY_OBJECTs and one CHANNEL_CONFIG. It materializes source text only
at composition time, re-atomizes every selected story from the shared fact
kernel, runs the existing non-clickbait Hook Engine independently for each
story, and emits one deterministic channel-native recurring product.

It deliberately does not bind media, weaken cadence/editorial gates, read
credential values, fetch analytics, or dispatch network requests. Website and
social channels remain sibling publications; the same staged fact set is
recomposed independently for every channel rather than cross-posted verbatim.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import content_atomizer
import hook_engine

SCHEMA_VERSION = "1.0"
PENDING_STATUS = "SERIES_COMPOSITION_PENDING"
READY_STATUS = "SERIES_FORMAT_READY"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SERIES_PROFILES: dict[str, dict[str, Any]] = {
    "facebook": {
        "format_order": ["single_photo", "text", "carousel", "reel", "story"],
        "format_family": "feed_roundup",
        "surface": "feed",
        "composition": "series_frame_then_numbered_updates",
        "item_label": "numbered_update",
        "support_atoms_per_story": 1,
    },
    "instagram": {
        "format_order": ["carousel", "single_photo", "story", "reel"],
        "format_family": "visual_roundup",
        "surface": "feed",
        "composition": "series_cover_then_story_cards",
        "item_label": "story_card",
        "support_atoms_per_story": 1,
    },
    "tiktok": {
        "format_order": ["short", "single_photo", "story"],
        "format_family": "short_roundup",
        "surface": "short_video",
        "composition": "series_frame_then_verified_beats",
        "item_label": "verified_beat",
        "support_atoms_per_story": 0,
    },
    "youtube": {
        "format_order": ["short", "long_video", "single_photo"],
        "format_family": "video_roundup",
        "surface": "short_video",
        "composition": "series_frame_then_verified_beats",
        "item_label": "verified_beat",
        "support_atoms_per_story": 0,
    },
    "threads": {
        "format_order": ["thread", "text", "single_photo"],
        "format_family": "thread_roundup",
        "surface": "thread",
        "composition": "series_opening_then_one_story_per_post",
        "item_label": "thread_post",
        "support_atoms_per_story": 0,
    },
    "linkedin": {
        "format_order": ["text", "single_photo", "carousel"],
        "format_family": "professional_roundup",
        "surface": "feed",
        "composition": "series_context_then_evidence_items",
        "item_label": "context_item",
        "support_atoms_per_story": 1,
    },
    "telegram": {
        "format_order": ["digest", "text", "single_photo", "alert"],
        "format_family": "channel_digest",
        "surface": "channel",
        "composition": "digest_header_then_compact_items",
        "item_label": "digest_item",
        "support_atoms_per_story": 0,
    },
    "whatsapp": {
        "format_order": ["text", "single_photo"],
        "format_family": "low_noise_digest",
        "surface": "message",
        "composition": "low_noise_header_then_compact_items",
        "item_label": "essential_item",
        "support_atoms_per_story": 0,
    },
}

MEDIA_FORMATS = {"single_photo", "carousel", "story", "reel", "short", "long_video", "live"}
VIDEO_FORMATS = {"reel", "short", "long_video", "live"}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _series_entry(channel: dict[str, Any], series_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    entries = [
        item
        for item in channel.get("series", [])
        if isinstance(item, dict) and _clean(item.get("series_id")) == series_id
    ]
    if not entries:
        return None, ["SERIES_NOT_DECLARED_IN_CHANNEL_CONFIG"]
    if len(entries) > 1:
        return None, ["DUPLICATE_SERIES_IN_CHANNEL_CONFIG"]
    if not _clean(entries[0].get("promise")):
        return None, ["SERIES_PROMISE_REQUIRED"]
    return entries[0], []


def select_native_format(
    channel: dict[str, Any],
    staged_candidates: list[Any],
    story_count: int,
) -> str | None:
    """Select a channel-native series format without degrading a staged product.

    The staged series policy remains an upper bound: the compositor may select
    only a format present both in the durable handoff and CHANNEL_CONFIG. A
    carousel additionally requires at least two stories; otherwise the next
    explicitly staged compatible format is used.
    """
    platform = _clean(channel.get("platform")).lower()
    profile = SERIES_PROFILES.get(platform)
    if not profile:
        return None
    channel_formats = {_clean(value) for value in channel.get("native_formats", []) if _clean(value)}
    staged = {_clean(value) for value in staged_candidates if _clean(value)}
    for candidate in profile["format_order"]:
        if candidate not in channel_formats or candidate not in staged:
            continue
        if candidate == "carousel" and story_count < 2:
            continue
        return candidate
    return None


def _base_blocks(
    channel: dict[str, Any],
    staged_item: dict[str, Any],
    source_pool: dict[str, Any],
) -> list[str]:
    blocks: list[str] = []
    platform = _clean(channel.get("platform")).lower()
    instance_id = _clean(channel.get("instance_id"))
    channel_id = _clean(channel.get("channel_id"))

    if platform not in SERIES_PROFILES:
        blocks.append("UNSUPPORTED_PLATFORM")
    if _clean(channel.get("status")) not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")
    if not instance_id:
        blocks.append("MISSING_INSTANCE_ID")
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        blocks.append("OBSERVED_METRICS_POLICY_REQUIRED")

    if _clean(staged_item.get("status")) != PENDING_STATUS:
        blocks.append("STAGED_ITEM_NOT_PENDING_COMPOSITION")
    if staged_item.get("native_composition_required") is not True:
        blocks.append("NATIVE_COMPOSITION_FLAG_REQUIRED")
    if staged_item.get("reuse_prior_copy") is not False:
        blocks.append("PRIOR_COPY_REUSE_FORBIDDEN")
    if staged_item.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE_FORBIDDEN")
    if staged_item.get("zero_paid_dependency") is not True:
        blocks.append("STAGED_ZERO_PAID_DEPENDENCY_REQUIRED")
    if _clean(staged_item.get("instance_id")) != instance_id:
        blocks.append("STAGED_INSTANCE_MISMATCH")
    if _clean(staged_item.get("channel_id")) != channel_id:
        blocks.append("STAGED_CHANNEL_MISMATCH")
    if not _clean(staged_item.get("series_execution_id")):
        blocks.append("MISSING_SERIES_EXECUTION_ID")
    if not _clean(staged_item.get("series_id")):
        blocks.append("MISSING_SERIES_ID")
    if not _clean(staged_item.get("series_slot_key")):
        blocks.append("MISSING_SERIES_SLOT_KEY")

    pool_instance = _clean(source_pool.get("instance_id"))
    if pool_instance != instance_id:
        blocks.append("SOURCE_POOL_INSTANCE_MISMATCH")
    stories = source_pool.get("stories")
    if not isinstance(stories, list) or any(not isinstance(item, dict) for item in stories):
        blocks.append("INVALID_SOURCE_STORY_POOL")

    selected_ids = staged_item.get("selected_story_ids")
    selected_hashes = staged_item.get("selected_content_hashes")
    if not isinstance(selected_ids, list) or not selected_ids:
        blocks.append("NO_SELECTED_STORIES")
    elif len({_clean(value) for value in selected_ids if _clean(value)}) != len(selected_ids):
        blocks.append("DUPLICATE_SELECTED_STORY_ID")
    if not isinstance(selected_hashes, list) or len(selected_hashes) != len(selected_ids or []):
        blocks.append("SELECTED_STORY_HASH_COUNT_MISMATCH")
    elif any(not SHA256_RE.fullmatch(_clean(value).lower()) for value in selected_hashes):
        blocks.append("INVALID_SELECTED_CONTENT_HASH")

    candidates = staged_item.get("native_format_candidates")
    if not isinstance(candidates, list) or not any(_clean(value) for value in candidates):
        blocks.append("NO_STAGED_NATIVE_FORMAT_CANDIDATES")
    return sorted(set(blocks))


def _safe_support_atoms(
    atom_bundle: dict[str, Any],
    channel: dict[str, Any],
    used_atom_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Choose extra source atoms through Hook Engine safety instead of free prose."""
    if limit <= 0:
        return []
    remaining = copy.deepcopy(atom_bundle)
    remaining["atoms"] = [
        item
        for item in atom_bundle.get("atoms", [])
        if isinstance(item, dict) and _clean(item.get("atom_id")) != used_atom_id
    ]
    selected: list[dict[str, Any]] = []
    for _ in range(limit):
        if not remaining.get("atoms"):
            break
        result = hook_engine.build_hook(remaining, channel)
        if result.get("blocked") is True or not isinstance(result.get("hook"), dict):
            break
        hook = result["hook"]
        atom_id = _clean(hook.get("source_atom_id"))
        if not atom_id:
            break
        selected.append(
            {
                "source_atom_id": atom_id,
                "source_atom_type": hook.get("source_atom_type"),
                "text": hook.get("source_text"),
                "source_preserving": True,
                "invented_claims_allowed": False,
            }
        )
        remaining["atoms"] = [
            item
            for item in remaining.get("atoms", [])
            if isinstance(item, dict) and _clean(item.get("atom_id")) != atom_id
        ]
    return selected


def _visual_requirement(
    native_format: str,
    channel: dict[str, Any],
    story_count: int,
) -> dict[str, Any]:
    policy = channel.get("media_policy") if isinstance(channel.get("media_policy"), dict) else {}
    required = native_format in MEDIA_FORMATS
    if native_format in VIDEO_FORMATS:
        media_kind = "real_video"
        minimum_assets = 1
        distinct_assets_required = False
    elif native_format == "carousel":
        media_kind = "real_photo_or_video"
        minimum_assets = max(2, story_count)
        distinct_assets_required = True
    elif required:
        media_kind = "real_photo_or_video"
        minimum_assets = 1
        distinct_assets_required = False
    else:
        media_kind = "none"
        minimum_assets = 0
        distinct_assets_required = False
    return {
        "required": required,
        "media_kind": media_kind,
        "minimum_assets": minimum_assets,
        "distinct_assets_required": distinct_assets_required,
        "subject_match_scope": "series_selected_stories",
        "real_media_only": bool(policy.get("real_media_only")),
        "provenance_required": bool(policy.get("provenance_required")),
        "reuse_rights_required": bool(policy.get("reuse_rights_required")),
        "synthetic_real_person_forbidden": bool(policy.get("synthetic_real_person_forbidden")),
        "binding_status": "PENDING_VISUAL_ROUTER" if required else "NOT_REQUIRED",
    }


def _native_structure(
    platform: str,
    native_format: str,
    story_ids: list[str],
) -> dict[str, Any]:
    profile = SERIES_PROFILES[platform]
    structure: dict[str, Any] = {
        "surface": profile["surface"],
        "composition": profile["composition"],
        "series_frame_first": True,
        "ordered_story_ids": list(story_ids),
        "item_role": profile["item_label"],
    }
    if platform == "instagram":
        structure.update(
            {
                "cover": "series_frame",
                "story_card_story_ids": list(story_ids),
                "caption_generated_from_story_atoms_only": True,
            }
        )
    elif platform in {"tiktok", "youtube"}:
        structure.update(
            {
                "opening": "series_frame",
                "beat_story_ids": list(story_ids),
                "voiceover_generation_allowed": False,
            }
        )
    elif platform == "threads":
        structure["post_story_ids"] = list(story_ids)
    elif platform == "linkedin":
        structure["evidence_item_story_ids"] = list(story_ids)
    elif platform in {"telegram", "whatsapp"}:
        structure["compact_item_story_ids"] = list(story_ids)
    elif platform == "facebook":
        structure["numbered_update_story_ids"] = list(story_ids)
    structure["native_format"] = native_format
    return structure


def _compose_story_item(
    story: dict[str, Any],
    expected_hash: str,
    channel: dict[str, Any],
    position: int,
    support_limit: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    story_id = _clean(story.get("story_id") or story.get("id"))
    atom_bundle = content_atomizer.atomize_story(story)
    blocks: list[str] = []
    if atom_bundle.get("blocked") is True:
        blocks.extend(f"STORY_ATOMIZER_BLOCKED:{story_id}:{reason}" for reason in atom_bundle.get("hard_blocks", []))
        return None, blocks
    actual_hash = _clean(atom_bundle.get("source_fingerprint_sha256")).lower()
    if actual_hash != expected_hash.lower():
        return None, [f"STORY_CONTENT_HASH_MISMATCH:{story_id}"]

    hook_result = hook_engine.build_hook(atom_bundle, channel)
    if hook_result.get("blocked") is True or not isinstance(hook_result.get("hook"), dict):
        reasons = hook_result.get("hard_blocks") or ["NO_SAFE_HOOK"]
        blocks.extend(f"STORY_HOOK_BLOCKED:{story_id}:{reason}" for reason in reasons)
        return None, blocks
    hook = hook_result["hook"]
    used_atom_id = _clean(hook.get("source_atom_id"))
    support = _safe_support_atoms(atom_bundle, channel, used_atom_id, support_limit)
    return {
        "position": position,
        "story_id": story_id,
        "source_fingerprint_sha256": actual_hash,
        "hook": {
            "text": hook.get("text"),
            "source_text": hook.get("source_text"),
            "generated_frame": hook.get("generated_frame", ""),
            "source_atom_id": hook.get("source_atom_id"),
            "source_atom_type": hook.get("source_atom_type"),
            "source_preserving": hook.get("source_preserving") is True,
            "clickbait_guard": hook.get("clickbait_guard"),
            "invented_claims_allowed": False,
        },
        "support_blocks": support,
        "re_atomized_from_verified_fact_kernel": True,
        "reuse_prior_copy": False,
    }, []


def compose_staged_series(
    channel: dict[str, Any],
    staged_item: dict[str, Any],
    source_pool: dict[str, Any],
) -> dict[str, Any]:
    """Compose one staged recurring-series handoff into a native channel product."""
    if not all(isinstance(value, dict) for value in (channel, staged_item, source_pool)):
        raise TypeError("channel, staged_item and source_pool must be mappings")

    blocks = _base_blocks(channel, staged_item, source_pool)
    instance_id = _clean(channel.get("instance_id")) or None
    channel_id = _clean(channel.get("channel_id")) or None
    platform = _clean(channel.get("platform")).lower() or None
    series_id = _clean(staged_item.get("series_id")) or None
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "channel_id": channel_id,
        "platform": platform,
        "series_id": series_id,
        "series_execution_id": _clean(staged_item.get("series_execution_id")) or None,
        "series_slot_key": _clean(staged_item.get("series_slot_key")) or None,
        "blocked": bool(blocks),
        "hard_blocks": blocks,
        "product": None,
        "guards": {
            "fact_kernel_re_atomized_per_story": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "prior_copy_reuse_allowed": False,
            "predictive_analytics_used": False,
            "credential_values_read": False,
            "network_dispatch_performed": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "editorial_gates_weakened": False,
            "zero_paid_dependency": True,
        },
    }
    if blocks:
        return base

    assert platform is not None and series_id is not None
    series, series_blocks = _series_entry(channel, series_id)
    if series_blocks or series is None:
        base["blocked"] = True
        base["hard_blocks"] = sorted(set([*base["hard_blocks"], *series_blocks]))
        return base

    selected_ids = [_clean(value) for value in staged_item["selected_story_ids"]]
    selected_hashes = [_clean(value).lower() for value in staged_item["selected_content_hashes"]]
    stories = source_pool["stories"]
    index: dict[str, list[dict[str, Any]]] = {}
    for story in stories:
        story_id = _clean(story.get("story_id") or story.get("id"))
        if story_id:
            index.setdefault(story_id, []).append(story)

    source_blocks: list[str] = []
    selected_stories: list[dict[str, Any]] = []
    for story_id in selected_ids:
        matches = index.get(story_id, [])
        if not matches:
            source_blocks.append(f"SELECTED_STORY_MISSING:{story_id}")
            continue
        if len(matches) > 1:
            source_blocks.append(f"DUPLICATE_SOURCE_STORY:{story_id}")
            continue
        story = matches[0]
        if _clean(story.get("instance_id")) != _clean(channel.get("instance_id")):
            source_blocks.append(f"SOURCE_STORY_INSTANCE_MISMATCH:{story_id}")
            continue
        selected_stories.append(story)
    if source_blocks:
        base["blocked"] = True
        base["hard_blocks"] = sorted(set([*base["hard_blocks"], *source_blocks]))
        return base

    native_format = select_native_format(channel, list(staged_item["native_format_candidates"]), len(selected_stories))
    if not native_format:
        base["blocked"] = True
        base["hard_blocks"].append("NO_COMPATIBLE_STAGED_NATIVE_FORMAT")
        return base

    profile = SERIES_PROFILES[platform]
    composed_items: list[dict[str, Any]] = []
    item_blocks: list[str] = []
    for position, (story, expected_hash) in enumerate(zip(selected_stories, selected_hashes), start=1):
        item, story_blocks = _compose_story_item(
            story,
            expected_hash,
            channel,
            position,
            int(profile["support_atoms_per_story"]),
        )
        if story_blocks:
            item_blocks.extend(story_blocks)
        elif item is not None:
            composed_items.append(item)
    if item_blocks or len(composed_items) != len(selected_ids):
        base["blocked"] = True
        base["hard_blocks"] = sorted(set([*base["hard_blocks"], *item_blocks]))
        if len(composed_items) != len(selected_ids) and not item_blocks:
            base["hard_blocks"].append("INCOMPLETE_SERIES_COMPOSITION")
        return base

    visual = _visual_requirement(native_format, channel, len(composed_items))
    link_policy = channel.get("link_policy") if isinstance(channel.get("link_policy"), dict) else {}
    approval = channel.get("approval_gates") if isinstance(channel.get("approval_gates"), dict) else {}
    series_frame = {
        "text": _clean(series.get("promise")),
        "source": "channel_config.series.promise",
        "source_preserving": True,
        "invented_claims_allowed": False,
    }
    identity_payload = {
        "instance_id": instance_id,
        "channel_id": channel_id,
        "platform": platform,
        "series_id": series_id,
        "series_execution_id": base["series_execution_id"],
        "series_slot_key": base["series_slot_key"],
        "composition_fingerprint_sha256": _clean(staged_item.get("composition_fingerprint_sha256")),
        "native_format": native_format,
        "story_hashes": [item["source_fingerprint_sha256"] for item in composed_items],
        "story_hook_atom_ids": [item["hook"]["source_atom_id"] for item in composed_items],
    }
    product_id = "series-product:" + _digest(identity_payload)[:24]
    product: dict[str, Any] = {
        "product_id": product_id,
        "instance_id": instance_id,
        "channel_id": channel_id,
        "platform": platform,
        "series_id": series_id,
        "series_execution_id": base["series_execution_id"],
        "series_slot_key": base["series_slot_key"],
        "staged_composition_fingerprint_sha256": _clean(staged_item.get("composition_fingerprint_sha256")),
        "native_format": native_format,
        "format_family": profile["format_family"],
        "series_frame": series_frame,
        "items": composed_items,
        "native_structure": _native_structure(platform, native_format, selected_ids),
        "visual_requirement": visual,
        "link_requirement": {
            "mode": _clean(link_policy.get("mode")) or "optional",
            "canonical_hosts": list(link_policy.get("canonical_hosts", [])) if isinstance(link_policy.get("canonical_hosts"), list) else [],
            "binding_status": "PENDING_LINK_BINDING" if _clean(link_policy.get("mode")) == "required" else "OPTIONAL",
        },
        "approval": {
            "low_risk_auto_allowed": bool(approval.get("low_risk_auto")),
            "human_review_required_before_publish": not bool(approval.get("low_risk_auto")),
            "reputational_human_gate": bool(approval.get("reputational_human")),
            "corrections_priority": bool(approval.get("corrections_priority")),
        },
        "composition_policy": "RE_ATOMIZE_PER_CHANNEL_FROM_VERIFIED_FACT_KERNEL",
        "cross_post_policy": "CHANNEL_NATIVE_SERIES_ONLY",
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "invented_claims_allowed": False,
        "analytics_used": False,
        "credential_values_read": False,
        "network_dispatch_performed": False,
        "zero_paid_dependency": True,
        "status": READY_STATUS,
        "next_gate": "VISUAL_ROUTER" if visual["required"] else ("LINK_BINDING" if _clean(link_policy.get("mode")) == "required" else "CADENCE_FATIGUE"),
    }
    product["product_fingerprint_sha256"] = _digest(product)
    base["product"] = product
    base["composition_transition"] = {
        "from_status": PENDING_STATUS,
        "to_status": READY_STATUS,
        "series_execution_id": base["series_execution_id"],
        "product_id": product_id,
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "persist_before_next_gate": True,
    }
    return base


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("staged_item", type=Path)
    parser.add_argument("source_pool", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = compose_staged_series(_load(args.channel), _load(args.staged_item), _load(args.source_pool))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
