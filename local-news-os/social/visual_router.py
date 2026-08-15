#!/usr/bin/env python3
"""Fail-closed Visual Router for LOCAL NEWS OS social publications.

The router binds a native Format Engine product to real editorial media only.
It never generates media, downloads assets, infers reuse rights, or fabricates
provenance. Candidate media must already exist in an instance-owned inventory
with explicit subject/editor approval, rights basis and content identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PHOTO_KINDS = {"photo", "photograph", "real_photo", "image"}
VIDEO_KINDS = {"video", "real_video"}
ALLOWED_SOURCE_TYPES = {
    "staff",
    "reader",
    "official_press",
    "official_institution",
    "licensed_agency",
    "public_domain",
    "creative_commons",
}
ALLOWED_RIGHTS = {
    "owned",
    "written_permission",
    "press_use",
    "licensed",
    "public_domain",
    "creative_commons",
    "official_reuse_permission",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalized_kind(value: Any) -> str:
    kind = _clean(value).lower()
    if kind in PHOTO_KINDS:
        return "photograph"
    if kind in VIDEO_KINDS:
        return "video"
    return ""


def _required_kinds(native_format: str, visual_requirement: dict[str, Any]) -> set[str]:
    if native_format == "single_photo":
        return {"photograph"}
    if native_format in {"reel", "short", "long_video", "live"}:
        return {"video"}
    media_kind = _clean(visual_requirement.get("media_kind"))
    if media_kind == "real_video":
        return {"video"}
    if media_kind == "real_photo":
        return {"photograph"}
    if media_kind == "real_photo_or_video":
        return {"photograph", "video"}
    return set()


def _base_blocks(format_result: dict[str, Any], channel: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if format_result.get("blocked") is True or not isinstance(format_result.get("product"), dict):
        blocks.append("FORMAT_PRODUCT_BLOCKED")

    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    instance_ids = {
        value
        for value in (
            _clean(format_result.get("instance_id")),
            _clean(channel.get("instance_id")),
            _clean(inventory.get("instance_id")),
        )
        if value
    }
    if not instance_ids:
        blocks.append("MISSING_INSTANCE_ID")
    elif len(instance_ids) != 1:
        blocks.append("INSTANCE_MISMATCH")

    channel_id = _clean(format_result.get("channel_id"))
    configured_channel = _clean(channel.get("channel_id"))
    if not channel_id or not configured_channel:
        blocks.append("MISSING_CHANNEL_ID")
    elif channel_id != configured_channel:
        blocks.append("CHANNEL_MISMATCH")

    story_id = _clean(format_result.get("story_id"))
    if not story_id:
        blocks.append("MISSING_STORY_ID")

    visual = product.get("visual_requirement") if isinstance(product.get("visual_requirement"), dict) else None
    if visual is None:
        blocks.append("MISSING_VISUAL_REQUIREMENT")

    assets = inventory.get("assets")
    if not isinstance(assets, list):
        blocks.append("INVALID_MEDIA_INVENTORY")
    return blocks


def _candidate_reasons(
    asset: dict[str, Any],
    *,
    instance_id: str,
    story_id: str,
    required_kinds: set[str],
    policy: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    asset_id = _clean(asset.get("asset_id"))
    if not asset_id:
        reasons.append("MISSING_ASSET_ID")

    if _clean(asset.get("instance_id")) != instance_id:
        reasons.append("INSTANCE_MISMATCH")

    normalized_kind = _normalized_kind(asset.get("kind"))
    if not normalized_kind:
        reasons.append("UNSUPPORTED_MEDIA_KIND")
    elif required_kinds and normalized_kind not in required_kinds:
        reasons.append("WRONG_MEDIA_KIND")

    if policy.get("real_media_only") is True and asset.get("synthetic") is not False:
        reasons.append("SYNTHETIC_OR_UNVERIFIED_MEDIA")
    if policy.get("synthetic_real_person_forbidden") is True and asset.get("synthetic") is not False:
        reasons.append("SYNTHETIC_FORBIDDEN")

    if asset.get("subject_match") is not True:
        reasons.append("SUBJECT_NOT_CONFIRMED")
    if asset.get("editor_approved") is not True:
        reasons.append("EDITOR_NOT_APPROVED")

    story_ids = asset.get("story_ids")
    if story_ids is not None:
        if not isinstance(story_ids, list) or story_id not in {_clean(item) for item in story_ids}:
            reasons.append("STORY_MISMATCH")

    sha256 = _clean(asset.get("sha256")).lower()
    if not SHA256_RE.fullmatch(sha256):
        reasons.append("MISSING_OR_INVALID_SHA256")

    source_type = _clean(asset.get("source_type"))
    credit = _clean(asset.get("credit"))
    source_url = _clean(asset.get("source_url"))
    if policy.get("provenance_required") is True:
        if source_type not in ALLOWED_SOURCE_TYPES:
            reasons.append("INVALID_SOURCE_TYPE")
        if not credit:
            reasons.append("MISSING_CREDIT")
        if source_type not in {"staff", "public_domain"} and not source_url:
            reasons.append("MISSING_SOURCE_URL")

    rights_basis = _clean(asset.get("rights_basis"))
    if policy.get("reuse_rights_required") is True and rights_basis not in ALLOWED_RIGHTS:
        reasons.append("MISSING_OR_INVALID_RIGHTS")

    if not _clean(asset.get("alt_text")):
        reasons.append("MISSING_ALT_TEXT")
    return reasons


def _candidate_score(asset: dict[str, Any], story_id: str, required_kinds: set[str]) -> int:
    score = 0
    story_ids = asset.get("story_ids")
    if isinstance(story_ids, list) and story_id in {_clean(item) for item in story_ids}:
        score += 100
    if asset.get("subject_match") is True:
        score += 40
    if asset.get("editor_approved") is True:
        score += 20
    kind = _normalized_kind(asset.get("kind"))
    if len(required_kinds) == 1 and kind in required_kinds:
        score += 10
    if _clean(asset.get("source_type")) in {"staff", "official_press", "official_institution"}:
        score += 5
    return score


def _public_asset(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": _clean(asset.get("asset_id")),
        "kind": _normalized_kind(asset.get("kind")),
        "sha256": _clean(asset.get("sha256")).lower(),
        "source_type": _clean(asset.get("source_type")),
        "source_url": _clean(asset.get("source_url")) or None,
        "direct_source_url": _clean(asset.get("direct_source_url")) or None,
        "credit": _clean(asset.get("credit")),
        "rights_basis": _clean(asset.get("rights_basis")),
        "license_url": _clean(asset.get("license_url")) or None,
        "rights_note": _clean(asset.get("rights_note")) or None,
        "alt_text": _clean(asset.get("alt_text")),
        "subject_match": True,
        "editor_approved": True,
        "synthetic": False,
    }


def bind_visuals(
    format_result: dict[str, Any],
    channel: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    """Bind approved real media to one native social product deterministically."""
    if not all(isinstance(value, dict) for value in (format_result, channel, inventory)):
        raise TypeError("format_result, channel and inventory must be mappings")

    blocks = _base_blocks(format_result, channel, inventory)
    instance_id = _clean(format_result.get("instance_id")) or _clean(channel.get("instance_id"))
    story_id = _clean(format_result.get("story_id"))
    channel_id = _clean(format_result.get("channel_id")) or _clean(channel.get("channel_id"))
    platform = _clean(format_result.get("platform")) or _clean(channel.get("platform"))
    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}

    base: dict[str, Any] = {
        "schema_version": "1.0",
        "instance_id": instance_id or None,
        "story_id": story_id or None,
        "channel_id": channel_id or None,
        "platform": platform or None,
        "blocked": bool(blocks),
        "hard_blocks": blocks,
        "binding": None,
    }
    if blocks:
        return base

    visual = product["visual_requirement"]
    if visual.get("required") is not True:
        binding = {
            "status": "NOT_REQUIRED",
            "selected_assets": [],
            "selected_asset_ids": [],
            "synthetic_media_used": False,
            "provenance_complete": True,
            "reuse_rights_complete": True,
            "next_gate": product.get("next_gate") if product.get("next_gate") != "VISUAL_ROUTER" else "PUBLICATION_STATE",
        }
        binding["binding_fingerprint_sha256"] = _digest(binding)
        base["binding"] = binding
        return base

    native_format = _clean(product.get("native_format"))
    required_kinds = _required_kinds(native_format, visual)
    minimum_assets = max(1, int(visual.get("minimum_assets") or 1))
    policy = channel.get("media_policy") if isinstance(channel.get("media_policy"), dict) else {}

    eligible: list[tuple[int, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    seen_asset_ids: set[str] = set()
    for raw in inventory.get("assets", []):
        if not isinstance(raw, dict):
            rejected.append({"asset_id": None, "reasons": ["INVALID_ASSET_RECORD"]})
            continue
        reasons = _candidate_reasons(
            raw,
            instance_id=instance_id,
            story_id=story_id,
            required_kinds=required_kinds,
            policy=policy,
        )
        asset_id = _clean(raw.get("asset_id"))
        if asset_id and asset_id in seen_asset_ids:
            reasons.append("DUPLICATE_ASSET_ID")
        if asset_id:
            seen_asset_ids.add(asset_id)
        if reasons:
            rejected.append({"asset_id": asset_id or None, "reasons": sorted(set(reasons))})
            continue
        eligible.append((_candidate_score(raw, story_id, required_kinds), raw))

    eligible.sort(key=lambda item: (-item[0], _clean(item[1].get("asset_id"))))
    selected = [_public_asset(item[1]) for item in eligible[:minimum_assets]]
    if len(selected) < minimum_assets:
        base["blocked"] = True
        base["hard_blocks"] = ["INSUFFICIENT_APPROVED_REAL_MEDIA"]
        base["binding"] = {
            "status": "VISUAL_BLOCKED",
            "required_assets": minimum_assets,
            "eligible_assets": len(eligible),
            "selected_assets": [],
            "selected_asset_ids": [],
            "rejected_candidates": rejected,
            "synthetic_media_used": False,
            "provenance_complete": False,
            "reuse_rights_complete": False,
            "next_gate": "VISUAL_ROUTER",
        }
        base["binding"]["binding_fingerprint_sha256"] = _digest(base["binding"])
        return base

    binding = {
        "status": "VISUAL_READY",
        "required_assets": minimum_assets,
        "eligible_assets": len(eligible),
        "selected_assets": selected,
        "selected_asset_ids": [item["asset_id"] for item in selected],
        "rejected_candidates": rejected,
        "synthetic_media_used": False,
        "provenance_complete": True,
        "reuse_rights_complete": True,
        "selection_policy": "EXACT_STORY_THEN_SUBJECT_APPROVED_DETERMINISTIC_V1",
        "next_gate": "LINK_BINDING" if product.get("link_requirement", {}).get("mode") == "required" else "PUBLICATION_STATE",
    }
    binding["binding_fingerprint_sha256"] = _digest(binding)
    base["binding"] = binding
    return base


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("format_result", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("media_inventory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = bind_visuals(_load(args.format_result), _load(args.channel), _load(args.media_inventory))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if not result["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
