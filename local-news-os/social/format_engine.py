#!/usr/bin/env python3
"""Deterministic native Format Engine for LOCAL NEWS OS social publications.

The engine converts an approved Hook Engine result plus source-preserving content
atoms and one CHANNEL_CONFIG into a platform-native publication package. It does
not bind media, invent claims, fabricate analytics, create hashtags, or perform
publication. Media and rights are deliberately left for the Visual Router.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "facebook": {
        "format_order": ["single_photo", "text", "carousel", "reel", "story", "live"],
        "body_order": ["dek", "paragraph", "fact", "quote"],
        "max_atoms": 3,
        "structure": "feed_post",
    },
    "instagram": {
        "format_order": ["carousel", "single_photo", "story", "reel"],
        "body_order": ["fact", "dek", "paragraph", "quote"],
        "max_atoms": 4,
        "structure": "visual_feed",
    },
    "tiktok": {
        "format_order": ["short", "single_photo", "story"],
        "body_order": ["fact", "dek", "paragraph", "quote"],
        "max_atoms": 3,
        "structure": "short_form_sequence",
    },
    "youtube": {
        "format_order": ["short", "long_video", "single_photo"],
        "body_order": ["fact", "dek", "paragraph", "quote"],
        "max_atoms": 4,
        "structure": "video_package",
    },
    "threads": {
        "format_order": ["thread", "text", "single_photo"],
        "body_order": ["dek", "fact", "paragraph", "quote"],
        "max_atoms": 4,
        "structure": "thread_sequence",
    },
    "linkedin": {
        "format_order": ["text", "single_photo", "carousel"],
        "body_order": ["dek", "paragraph", "fact", "quote"],
        "max_atoms": 4,
        "structure": "professional_context_post",
    },
    "whatsapp": {
        "format_order": ["alert", "digest", "text", "single_photo"],
        "body_order": ["fact", "dek", "paragraph", "quote"],
        "max_atoms": 4,
        "structure": "message_update",
    },
    "telegram": {
        "format_order": ["text", "digest", "single_photo", "alert"],
        "body_order": ["fact", "dek", "paragraph", "quote"],
        "max_atoms": 5,
        "structure": "channel_update",
    },
}

MEDIA_FORMATS = {"single_photo", "carousel", "story", "reel", "short", "long_video", "live"}
VIDEO_FORMATS = {"reel", "short", "long_video", "live"}
MULTI_ASSET_FORMATS = {"carousel"}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hard_blocks(atom_bundle: dict[str, Any], hook_result: dict[str, Any], channel: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if atom_bundle.get("blocked") is True:
        blocks.append("ATOM_BUNDLE_BLOCKED")
    if hook_result.get("blocked") is True or not isinstance(hook_result.get("hook"), dict):
        blocks.append("HOOK_BLOCKED")

    instance_ids = {
        value
        for value in (
            _clean(atom_bundle.get("instance_id")),
            _clean(hook_result.get("instance_id")),
            _clean(channel.get("instance_id")),
        )
        if value
    }
    if not instance_ids:
        blocks.append("MISSING_INSTANCE_ID")
    elif len(instance_ids) != 1:
        blocks.append("INSTANCE_MISMATCH")

    story_ids = {
        value
        for value in (_clean(atom_bundle.get("story_id")), _clean(hook_result.get("story_id")))
        if value
    }
    if not story_ids:
        blocks.append("MISSING_STORY_ID")
    elif len(story_ids) != 1:
        blocks.append("STORY_MISMATCH")

    channel_id = _clean(channel.get("channel_id"))
    hook_channel = _clean(hook_result.get("channel_id"))
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    elif hook_channel and hook_channel != channel_id:
        blocks.append("CHANNEL_MISMATCH")

    platform = _clean(channel.get("platform")).lower()
    if platform not in PLATFORM_PROFILES:
        blocks.append("UNSUPPORTED_PLATFORM")
    if _clean(channel.get("status")) not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")
    native_formats = channel.get("native_formats")
    if not isinstance(native_formats, list) or not any(_clean(item) for item in native_formats):
        blocks.append("NO_NATIVE_FORMATS")
    return blocks


def _select_format(atom_bundle: dict[str, Any], channel: dict[str, Any]) -> str | None:
    platform = _clean(channel.get("platform")).lower()
    profile = PLATFORM_PROFILES.get(platform)
    if not profile:
        return None
    available = [_clean(value) for value in channel.get("native_formats", []) if _clean(value)]
    if atom_bundle.get("correction") is True and "alert" in available:
        return "alert"
    for candidate in profile["format_order"]:
        if candidate in available:
            return candidate
    return available[0] if available else None


def _source_atoms(atom_bundle: dict[str, Any], hook_result: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    hook = hook_result.get("hook") or {}
    used_atom_id = _clean(hook.get("source_atom_id"))
    order = {name: index for index, name in enumerate(profile["body_order"])}
    candidates: list[dict[str, Any]] = []
    for atom in atom_bundle.get("atoms", []):
        if not isinstance(atom, dict):
            continue
        atom_id = _clean(atom.get("atom_id"))
        atom_type = _clean(atom.get("atom_type"))
        text = _clean(atom.get("text"))
        if not atom_id or not text or atom_id == used_atom_id or atom_type not in order:
            continue
        candidates.append(atom)
    candidates.sort(key=lambda item: (order[_clean(item.get("atom_type"))], int(item.get("ordinal", 0))))
    return candidates[: int(profile["max_atoms"])]


def _content_block(atom: dict[str, Any], position: int) -> dict[str, Any]:
    return {
        "position": position,
        "role": "supporting_source_atom",
        "text": _clean(atom.get("text")),
        "source_atom_id": atom.get("atom_id"),
        "source_atom_type": atom.get("atom_type"),
        "mutation_policy": atom.get("mutation_policy"),
        "verbatim_required": atom.get("mutation_policy") == "verbatim_only",
        "source_ref": atom.get("source_ref"),
    }


def _native_structure(platform: str, native_format: str, hook: dict[str, Any], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    atom_ids = [block["source_atom_id"] for block in blocks]
    if platform == "facebook":
        return {
            "surface": "feed",
            "composition": "hook_then_context",
            "headline_source_atom_id": hook.get("source_atom_id"),
            "body_atom_ids": atom_ids,
            "link_slot": "after_body",
        }
    if platform == "instagram":
        return {
            "surface": "feed" if native_format in {"single_photo", "carousel"} else native_format,
            "composition": "visual_first_caption_second",
            "caption_hook_atom_id": hook.get("source_atom_id"),
            "caption_support_atom_ids": atom_ids[:2],
            "visual_text_atom_ids": atom_ids if native_format == "carousel" else [],
        }
    if platform in {"tiktok", "youtube"}:
        return {
            "surface": "short_video" if native_format in {"short", "reel"} else native_format,
            "composition": "hook_frame_then_verified_beats",
            "opening_atom_id": hook.get("source_atom_id"),
            "beat_atom_ids": atom_ids,
            "voiceover_generation_allowed": False,
        }
    if platform == "threads":
        return {
            "surface": "thread",
            "composition": "opening_then_context_posts",
            "post_atom_ids": [hook.get("source_atom_id"), *atom_ids],
        }
    if platform == "linkedin":
        return {
            "surface": "feed",
            "composition": "context_then_evidence",
            "opening_atom_id": hook.get("source_atom_id"),
            "context_atom_ids": atom_ids,
        }
    return {
        "surface": "message",
        "composition": "compact_verified_update",
        "opening_atom_id": hook.get("source_atom_id"),
        "support_atom_ids": atom_ids,
    }


def _visual_requirement(native_format: str, channel: dict[str, Any]) -> dict[str, Any]:
    requires_media = native_format in MEDIA_FORMATS
    if native_format in VIDEO_FORMATS:
        media_kind = "real_video"
        minimum_assets = 1
    elif native_format in MULTI_ASSET_FORMATS:
        media_kind = "real_photo_or_video"
        minimum_assets = 2
    elif requires_media:
        media_kind = "real_photo_or_video"
        minimum_assets = 1
    else:
        media_kind = "none"
        minimum_assets = 0
    policy = channel.get("media_policy", {}) if isinstance(channel.get("media_policy"), dict) else {}
    return {
        "required": requires_media,
        "media_kind": media_kind,
        "minimum_assets": minimum_assets,
        "real_media_only": bool(policy.get("real_media_only")),
        "provenance_required": bool(policy.get("provenance_required")),
        "reuse_rights_required": bool(policy.get("reuse_rights_required")),
        "synthetic_real_person_forbidden": bool(policy.get("synthetic_real_person_forbidden")),
        "binding_status": "PENDING_VISUAL_ROUTER" if requires_media else "NOT_REQUIRED",
    }


def build_native_product(
    atom_bundle: dict[str, Any],
    hook_result: dict[str, Any],
    channel: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic, source-preserving native publication package."""
    if not all(isinstance(value, dict) for value in (atom_bundle, hook_result, channel)):
        raise TypeError("atom_bundle, hook_result and channel must be mappings")

    blocks = _hard_blocks(atom_bundle, hook_result, channel)
    instance_id = _clean(atom_bundle.get("instance_id")) or _clean(channel.get("instance_id"))
    story_id = _clean(atom_bundle.get("story_id")) or _clean(hook_result.get("story_id"))
    channel_id = _clean(channel.get("channel_id"))
    platform = _clean(channel.get("platform")).lower()
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "instance_id": instance_id or None,
        "story_id": story_id or None,
        "channel_id": channel_id or None,
        "platform": platform or None,
        "blocked": bool(blocks),
        "hard_blocks": blocks,
        "product": None,
    }
    if blocks:
        return base

    native_format = _select_format(atom_bundle, channel)
    if not native_format:
        base["blocked"] = True
        base["hard_blocks"].append("NO_COMPATIBLE_NATIVE_FORMAT")
        return base

    profile = PLATFORM_PROFILES[platform]
    hook = dict(hook_result["hook"])
    supporting = [_content_block(atom, index + 1) for index, atom in enumerate(_source_atoms(atom_bundle, hook_result, profile))]
    visual = _visual_requirement(native_format, channel)
    link_policy = channel.get("link_policy", {}) if isinstance(channel.get("link_policy"), dict) else {}
    approval = channel.get("approval_gates", {}) if isinstance(channel.get("approval_gates"), dict) else {}
    low_risk_auto = bool(approval.get("low_risk_auto"))

    product_payload = {
        "instance_id": instance_id,
        "story_id": story_id,
        "channel_id": channel_id,
        "platform": platform,
        "native_format": native_format,
        "hook_id": hook.get("hook_id"),
        "support_atom_ids": [item["source_atom_id"] for item in supporting],
        "atom_bundle_fingerprint": atom_bundle.get("source_fingerprint_sha256"),
    }
    product_id = "social-product:" + _digest(product_payload)[:24]
    product = {
        "product_id": product_id,
        "native_format": native_format,
        "format_family": profile["structure"],
        "hook": {
            "text": hook.get("text"),
            "source_atom_id": hook.get("source_atom_id"),
            "source_atom_type": hook.get("source_atom_type"),
            "source_preserving": hook.get("source_preserving") is True,
            "generated_frame": hook.get("generated_frame", ""),
        },
        "content_blocks": supporting,
        "native_structure": _native_structure(platform, native_format, hook, supporting),
        "visual_requirement": visual,
        "link_requirement": {
            "mode": _clean(link_policy.get("mode")) or "optional",
            "canonical_hosts": list(link_policy.get("canonical_hosts", [])) if isinstance(link_policy.get("canonical_hosts"), list) else [],
            "binding_status": "PENDING_LINK_BINDING" if _clean(link_policy.get("mode")) == "required" else "OPTIONAL",
        },
        "approval": {
            "low_risk_auto_allowed": low_risk_auto,
            "human_review_required_before_publish": not low_risk_auto,
            "reputational_human_gate": bool(approval.get("reputational_human")),
            "corrections_priority": bool(approval.get("corrections_priority")),
        },
        "correction": atom_bundle.get("correction") is True,
        "cross_post_policy": "NATIVE_PRODUCT_ONLY",
        "verbatim_cross_platform_reuse_allowed": False,
        "invented_claims_allowed": False,
        "analytics_used": False,
        "format_status": "FORMAT_READY",
        "next_gate": "VISUAL_ROUTER" if visual["required"] else ("LINK_BINDING" if _clean(link_policy.get("mode")) == "required" else "PUBLICATION_STATE"),
    }
    product["product_fingerprint_sha256"] = _digest(product)
    base["product"] = product
    return base


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atom_bundle", type=Path)
    parser.add_argument("hook_result", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = build_native_product(_load(args.atom_bundle), _load(args.hook_result), _load(args.channel))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())