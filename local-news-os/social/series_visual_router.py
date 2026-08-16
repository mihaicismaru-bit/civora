#!/usr/bin/env python3
"""Fail-closed visual binding for recurring native social series.

The Native Series Compositor emits ``SERIES_FORMAT_READY`` products that may
span multiple verified stories. The generic Visual Router intentionally binds
one single-story product, so this router closes the multi-story boundary
without weakening its media rules.

Only real, editor-approved media with explicit provenance, reuse rights and
SHA-256 identity may be selected. Assets must be explicitly associated with a
story selected by the series. Carousel and video-roundup products require
coverage for every selected story so unrelated footage cannot illustrate a
different beat. The router is deterministic, does not generate/download media,
does not read credentials or analytics, and performs no network dispatch.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import visual_router

SCHEMA_VERSION = "1.0"
FORMAT_READY = "SERIES_FORMAT_READY"
VISUAL_READY = "SERIES_VISUAL_READY"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FULL_COVERAGE_FORMATS = {"carousel", "reel", "short", "long_video", "live"}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _product_fingerprint_valid(product: dict[str, Any]) -> bool:
    expected = _clean(product.get("product_fingerprint_sha256")).lower()
    if not SHA256_RE.fullmatch(expected):
        return False
    payload = copy.deepcopy(product)
    payload.pop("product_fingerprint_sha256", None)
    return visual_router._digest(payload)
 == expected


def _base_blocks(
    composition_result: dict[str, Any],
    channel: dict[str, Any],
    inventory: dict[str, Any],
) -> list[str]:
    blocks: list[str] = []
    if composition_result.get("blocked") is True or not isinstance(composition_result.get("product"), dict):
        blocks.append("SERIES_FORMAT_PRODUCT_BLOCKED")
        return blocks

    product = composition_result["product"]
    if _clean(product.get("status")) != FORMAT_READY:
        blocks.append("SERIES_PRODUCT_NOT_FORMAT_READY")
    if _clean(product.get("next_gate")) != "VISUAL_ROUTER":
        blocks.append("SERIES_PRODUCT_NOT_ROUTED_TO_VISUAL_GATE")
    if not _product_fingerprint_valid(product):
        blocks.append("SERIES_PRODUCT_FINGERPRINT_MISMATCH")

    instance_ids = {
        value
        for value in (
            _clean(composition_result.get("instance_id")),
            _clean(product.get("instance_id")),
            _clean(channel.get("instance_id")),
            _clean(inventory.get("instance_id")),
        )
        if value
    }
    if not instance_ids:
        blocks.append("MISSING_INSTANCE_ID")
    elif len(instance_ids) != 1:
        blocks.append("INSTANCE_MISMATCH")

    result_channel = _clean(composition_result.get("channel_id"))
    product_channel = _clean(product.get("channel_id"))
    configured_channel = _clean(channel.get("channel_id"))
    if not result_channel or not product_channel or not configured_channel:
        blocks.append("MISSING_CHANNEL_ID")
    elif len({result_channel, product_channel, configured_channel}) != 1:
        blocks.append("CHANNEL_MISMATCH")

    result_platform = _clean(composition_result.get("platform")).lower()
    product_platform = _clean(product.get("platform")).lower()
    configured_platform = _clean(channel.get("platform")).lower()
    if not result_platform or not product_platform or not configured_platform:
        blocks.append("MISSING_PLATFORM")
    elif len({result_platform, product_platform, configured_platform}) != 1:
        blocks.append("PLATFORM_MISMATCH")

    result_series = _clean(composition_result.get("series_id"))
    product_series = _clean(product.get("series_id"))
    if not result_series or not product_series:
        blocks.append("MISSING_SERIES_ID")
    elif result_series != product_series:
        blocks.append("SERIES_ID_MISMATCH")

    if channel.get("zero_paid_dependency") is not True or product.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        blocks.append("OBSERVED_METRICS_POLICY_REQUIRED")

    policy = channel.get("media_policy") if isinstance(channel.get("media_policy"), dict) else {}
    for key, reason in (
        ("real_media_only", "REAL_MEDIA_ONLY_POLICY_REQUIRED"),
        ("provenance_required", "PROVENANCE_POLICY_REQUIRED"),
        ("reuse_rights_required", "REUSE_RIGHTS_POLICY_REQUIRED"),
    ):
        if policy.get(key) is not True:
            blocks.append(reason)

    visual = product.get("visual_requirement")
    if not isinstance(visual, dict):
        blocks.append("MISSING_VISUAL_REQUIREMENT")
    else:
        if visual.get("required") is not True:
            blocks.append("SERIES_VISUAL_MEDIA_NOT_REQUIRED")
        if _clean(visual.get("subject_match_scope")) != "series_selected_stories":
            blocks.append("INVALID_SERIES_SUBJECT_MATCH_SCOPE")
        if visual.get("real_media_only") is not True:
            blocks.append("PRODUCT_REAL_MEDIA_ONLY_REQUIRED")
        if visual.get("provenance_required") is not True:
            blocks.append("PRODUCT_PROVENANCE_REQUIRED")
        if visual.get("reuse_rights_required") is not True:
            blocks.append("PRODUCT_REUSE_RIGHTS_REQUIRED")

    items = product.get("items")
    if not isinstance(items, list) or not items:
        blocks.append("MISSING_SERIES_ITEMS")
    else:
        story_ids = [_clean(item.get("story_id")) for item in items if isinstance(item, dict)]
        if len(story_ids) != len(items) or any(not value for value in story_ids):
            blocks.append("INVALID_SERIES_ITEM_STORY_ID")
        elif len(set(story_ids)) != len(story_ids):
            blocks.append("DUPLICATE_SERIES_ITEM_STORY_ID")
        for item in items:
            if not isinstance(item, dict):
                continue
            story_id = _clean(item.get("story_id")) or "UNKNOWN"
            source_hash = _clean(item.get("source_fingerprint_sha256")).lower()
            if not SHA256_RE.fullmatch(source_hash):
                blocks.append(f"INVALID_SERIES_SOURCE_HASH:{story_id}")
            if item.get("re_atomized_from_verified_fact_kernel") is not True:
                blocks.append(f"UNVERIFIED_SERIES_ITEM:{story_id}")
            hook = item.get("hook") if isinstance(item.get("hook"), dict) else {}
            if hook.get("source_preserving") is not True or hook.get("clickbait_guard") != "PASS":
                blocks.append(f"UNSAFE_SERIES_HOOK:{story_id}")

    assets = inventory.get("assets")
    if not isinstance(assets, list):
        blocks.append("INVALID_MEDIA_INVENTORY")
    return sorted(set(blocks))


def _associated_story_ids(asset: dict[str, Any], selected_story_ids: list[str]) -> list[str]:
    raw = asset.get("story_ids")
    if not isinstance(raw, list):
        return []
    selected = set(selected_story_ids)
    return [story_id for story_id in selected_story_ids if story_id in {_clean(value) for value in raw} and story_id in selected]


def _candidate_reasons(
    asset: dict[str, Any],
    *,
    instance_id: str,
    selected_story_ids: list[str],
    required_kinds: set[str],
    policy: dict[str, Any],
) -> list[str]:
    associated = _associated_story_ids(asset, selected_story_ids)
    anchor = associated[0] if associated else selected_story_ids[0]
    reasons = visual_router._candidate_reasons(
        asset,
        instance_id=instance_id,
        story_id=anchor,
        required_kinds=required_kinds,
        policy=policy,
    )
    if not associated:
        reasons.append("SERIES_STORY_ASSOCIATION_REQUIRED")
    return sorted(set(reasons))


def _candidate_score(
    asset: dict[str, Any],
    selected_story_ids: list[str],
    required_kinds: set[str],
) -> int:
    associated = _associated_story_ids(asset, selected_story_ids)
    anchor = associated[0] if associated else selected_story_ids[0]
    return visual_router._candidate_score(asset, anchor, required_kinds) + (10 * len(associated))


def _public_association(asset: dict[str, Any], selected_story_ids: list[str]) -> dict[str, Any]:
    public = visual_router._public_asset(asset)
    public["story_ids"] = _associated_story_ids(asset, selected_story_ids)
    return public


def bind_series_visuals(
    composition_result: dict[str, Any],
    channel: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    """Bind approved real media to one multi-story native series product."""
    if not all(isinstance(value, dict) for value in (composition_result, channel, inventory)):
        raise TypeError("composition_result, channel and inventory must be mappings")

    blocks = _base_blocks(composition_result, channel, inventory)
    product = composition_result.get("product") if isinstance(composition_result.get("product"), dict) else {}
    instance_id = _clean(product.get("instance_id")) or _clean(channel.get("instance_id"))
    channel_id = _clean(product.get("channel_id")) or _clean(channel.get("channel_id"))
    platform = _clean(product.get("platform")).lower() or _clean(channel.get("platform")).lower()
    series_id = _clean(product.get("series_id"))
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id or None,
        "channel_id": channel_id or None,
        "platform": platform or None,
        "series_id": series_id or None,
        "series_execution_id": _clean(product.get("series_execution_id")) or None,
        "series_slot_key": _clean(product.get("series_slot_key")) or None,
        "product_id": _clean(product.get("product_id")) or None,
        "blocked": bool(blocks),
        "hard_blocks": blocks,
        "binding": None,
        "guards": {
            "real_media_only": True,
            "provenance_required": True,
            "reuse_rights_required": True,
            "series_story_association_required": True,
            "predictive_analytics_used": False,
            "credential_values_read": False,
            "network_dispatch_performed": False,
            "paid_dependency_used": False,
            "editorial_gates_weakened": False,
            "zero_paid_dependency": True,
        },
    }
    if blocks:
        return base

    items = product["items"]
    selected_story_ids = [_clean(item["story_id"]) for item in items]
    visual = product["visual_requirement"]
    native_format = _clean(product.get("native_format"))
    required_kinds = visual_router._required_kinds(native_format, visual)
    minimum_assets = max(1, int(visual.get("minimum_assets") or 1))
    full_coverage_required = native_format in FULL_COVERAGE_FORMATS
    if full_coverage_required:
        minimum_assets = max(minimum_assets, len(selected_story_ids))
    distinct_required = bool(visual.get("distinct_assets_required")) or full_coverage_required
    policy = channel["media_policy"]

    eligible: list[tuple[int, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    raw_assets = [raw for raw in inventory.get("assets", []) if isinstance(raw, dict)]
    id_counts: dict[str, int] = {}
    hash_counts: dict[str, int] = {}
    for raw in raw_assets:
        asset_id = _clean(raw.get("asset_id"))
        sha256 = _clean(raw.get("sha256")).lower()
        if asset_id:
            id_counts[asset_id] = id_counts.get(asset_id, 0) + 1
        if SHA256_RE.fullmatch(sha256):
            hash_counts[sha256] = hash_counts.get(sha256, 0) + 1

    for raw in inventory.get("assets", []):
        if not isinstance(raw, dict):
            rejected.append({"asset_id": None, "reasons": ["INVALID_ASSET_RECORD"]})
            continue
        reasons = _candidate_reasons(
            raw,
            instance_id=instance_id,
            selected_story_ids=selected_story_ids,
            required_kinds=required_kinds,
            policy=policy,
        )
        asset_id = _clean(raw.get("asset_id"))
        sha256 = _clean(raw.get("sha256")).lower()
        if asset_id and id_counts.get(asset_id, 0) > 1:
            reasons.append("DUPLICATE_ASSET_ID")
        if SHA256_RE.fullmatch(sha256) and hash_counts.get(sha256, 0) > 1:
            reasons.append("DUPLICATE_ASSET_CONTENT")
        if reasons:
            rejected.append({"asset_id": asset_id or None, "reasons": sorted(set(reasons))})
            continue
        eligible.append((_candidate_score(raw, selected_story_ids, required_kinds), raw))

    eligible.sort(key=lambda item: (-item[0], _clean(item[1].get("asset_id"))))
    rejected.sort(key=lambda item: (_clean(item.get("asset_id")), tuple(item.get("reasons", []))))

    selected_raw: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    used_hashes: set[str] = set()
    covered: set[str] = set()

    if full_coverage_required:
        for story_id in selected_story_ids:
            candidates = [
                raw
                for _, raw in eligible
                if story_id in _associated_story_ids(raw, selected_story_ids)
                and _clean(raw.get("asset_id")) not in used_ids
                and _clean(raw.get("sha256")).lower() not in used_hashes
            ]
            if not candidates:
                base["blocked"] = True
                base["hard_blocks"] = [f"MISSING_REAL_MEDIA_FOR_SERIES_STORY:{story_id}"]
                break
            chosen = candidates[0]
            selected_raw.append(chosen)
            used_ids.add(_clean(chosen.get("asset_id")))
            used_hashes.add(_clean(chosen.get("sha256")).lower())
            covered.update(_associated_story_ids(chosen, selected_story_ids))

    if not base["blocked"]:
        for _, raw in eligible:
            if len(selected_raw) >= minimum_assets:
                break
            asset_id = _clean(raw.get("asset_id"))
            sha256 = _clean(raw.get("sha256")).lower()
            if asset_id in used_ids or sha256 in used_hashes:
                continue
            selected_raw.append(raw)
            used_ids.add(asset_id)
            used_hashes.add(sha256)
            covered.update(_associated_story_ids(raw, selected_story_ids))

    if base["blocked"] or len(selected_raw) < minimum_assets:
        if not base["blocked"]:
            base["blocked"] = True
            base["hard_blocks"] = ["INSUFFICIENT_APPROVED_REAL_SERIES_MEDIA"]
        base["binding"] = {
            "status": "SERIES_VISUAL_BLOCKED",
            "required_assets": minimum_assets,
            "eligible_assets": len(eligible),
            "selected_assets": [],
            "selected_asset_ids": [],
            "covered_story_ids": [],
            "full_story_coverage_required": full_coverage_required,
            "rejected_candidates": rejected,
            "synthetic_media_used": False,
            "provenance_complete": False,
            "reuse_rights_complete": False,
            "next_gate": "VISUAL_ROUTER",
        }
        base["binding"]["binding_fingerprint_sha256"] = visual_router._digest(base["binding"])
        return base

    selected = [_public_association(raw, selected_story_ids) for raw in selected_raw]
    covered_story_ids = [story_id for story_id in selected_story_ids if story_id in covered]
    if full_coverage_required and covered_story_ids != selected_story_ids:
        base["blocked"] = True
        base["hard_blocks"] = ["INCOMPLETE_SERIES_STORY_VISUAL_COVERAGE"]
        base["binding"] = {
            "status": "SERIES_VISUAL_BLOCKED",
            "required_assets": minimum_assets,
            "eligible_assets": len(eligible),
            "selected_assets": [],
            "selected_asset_ids": [],
            "covered_story_ids": covered_story_ids,
            "full_story_coverage_required": True,
            "rejected_candidates": rejected,
            "synthetic_media_used": False,
            "provenance_complete": False,
            "reuse_rights_complete": False,
            "next_gate": "VISUAL_ROUTER",
        }
        base["binding"]["binding_fingerprint_sha256"] = visual_router._digest(base["binding"])
        return base

    next_gate = "LINK_BINDING" if _clean(product.get("link_requirement", {}).get("mode")) == "required" else "CADENCE_FATIGUE"
    binding = {
        "status": VISUAL_READY,
        "required_assets": minimum_assets,
        "eligible_assets": len(eligible),
        "selected_assets": selected,
        "selected_asset_ids": [item["asset_id"] for item in selected],
        "asset_story_bindings": [
            {"asset_id": item["asset_id"], "story_ids": list(item["story_ids"])}
            for item in selected
        ],
        "covered_story_ids": covered_story_ids,
        "full_story_coverage_required": full_coverage_required,
        "distinct_assets_required": distinct_required,
        "rejected_candidates": rejected,
        "synthetic_media_used": False,
        "provenance_complete": True,
        "reuse_rights_complete": True,
        "selection_policy": (
            "EXACT_SERIES_STORY_FULL_COVERAGE_DETERMINISTIC_V1"
            if full_coverage_required
            else "EXACT_SELECTED_STORY_HERO_DETERMINISTIC_V1"
        ),
        "source_product_fingerprint_sha256": _clean(product.get("product_fingerprint_sha256")).lower(),
        "next_gate": next_gate,
    }
    binding["binding_fingerprint_sha256"] = visual_router._digest(binding)
    base["binding"] = binding
    base["visual_transition"] = {
        "from_status": FORMAT_READY,
        "to_status": VISUAL_READY,
        "product_id": base["product_id"],
        "binding_fingerprint_sha256": binding["binding_fingerprint_sha256"],
        "persist_before_next_gate": True,
        "next_gate": next_gate,
    }
    return base


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("composition_result", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("media_inventory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = bind_series_visuals(_load(args.composition_result), _load(args.channel), _load(args.media_inventory))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if not result["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
