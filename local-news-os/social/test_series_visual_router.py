#!/usr/bin/env python3
"""Acceptance tests for recurring-series real-media visual binding."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import content_atomizer
import native_series_compositor
import series_visual_router

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64

NATIVE_FORMATS = {
    "facebook": ["single_photo", "text"],
    "instagram": ["carousel", "single_photo"],
    "tiktok": ["short", "single_photo"],
    "youtube": ["short", "long_video"],
}


def channel(platform: str) -> dict:
    return {
        "schema_version": "1.0",
        "channel_id": f"valcea-{platform}",
        "instance_id": "valcea",
        "platform": platform,
        "status": "active" if platform in {"facebook", "instagram", "tiktok"} else "outbox_only",
        "native_formats": list(NATIVE_FORMATS[platform]),
        "media_policy": {
            "real_media_only": True,
            "provenance_required": True,
            "reuse_rights_required": True,
            "synthetic_real_person_forbidden": True,
        },
        "link_policy": {"mode": "optional", "canonical_hosts": ["valceaclar.ro"]},
        "series": [{"series_id": "daily-brief", "promise": f"Daily brief for {platform}."}],
        "approval_gates": {
            "low_risk_auto": platform not in {"tiktok", "youtube"},
            "reputational_human": True,
            "corrections_priority": True,
        },
        "metrics": {"observed_only": True},
        "zero_paid_dependency": True,
    }


def stories() -> list[dict]:
    return [
        {
            "instance_id": "valcea",
            "story_id": "story-a",
            "material_fact_gate": "PASS",
            "headline": "Podul din centru se redeschide luni",
            "dek": "Traficul va fi reluat după finalizarea lucrărilor programate.",
            "paragraphs": ["Primăria a anunțat redeschiderea pentru luni dimineață."],
            "facts": [{"fact_id": "a1", "text": "Restricțiile sunt ridicate luni la ora 06:00."}],
            "topics": ["infrastructure"],
        },
        {
            "instance_id": "valcea",
            "story_id": "story-b",
            "material_fact_gate": "PASS",
            "headline": "Festivalul din Zăvoi începe vineri",
            "dek": "Accesul la concertele din prima seară este liber.",
            "paragraphs": ["Programul publicat include concerte vineri și sâmbătă."],
            "facts": [{"fact_id": "b1", "text": "Prima seară începe la ora 19:00."}],
            "topics": ["local_events"],
        },
    ]


def fingerprint(story: dict) -> str:
    return content_atomizer.atomize_story(story)["source_fingerprint_sha256"]


def staged(platform: str, source_stories: list[dict] | None = None) -> dict:
    source_stories = copy.deepcopy(source_stories or stories())
    return {
        "series_execution_id": f"series-execution:{platform}-daily",
        "occurrence_id": f"occurrence:{platform}-daily",
        "instance_id": "valcea",
        "channel_id": f"valcea-{platform}",
        "series_id": "daily-brief",
        "series_slot_key": "daily-brief:2026-08-16:0:17:00",
        "status": "SERIES_COMPOSITION_PENDING",
        "publication_mode": "channel_native_series_composition_pending",
        "selected_story_ids": [story["story_id"] for story in source_stories],
        "selected_content_hashes": [fingerprint(story) for story in source_stories],
        "native_format_candidates": list(NATIVE_FORMATS[platform]),
        "composition_fingerprint_sha256": "f" * 64,
        "native_composition_required": True,
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "source_story_text_materialized": False,
        "predictive_analytics_used": False,
        "credential_values_read": False,
        "network_dispatch_performed": False,
        "editorial_gates_weakened": False,
        "zero_paid_dependency": True,
    }


def composition(platform: str, source_stories: list[dict] | None = None) -> dict:
    source_stories = copy.deepcopy(source_stories or stories())
    result = native_series_compositor.compose_staged_series(
        channel(platform),
        staged(platform, source_stories),
        {"instance_id": "valcea", "stories": source_stories},
    )
    assert result["blocked"] is False
    assert result["product"]["next_gate"] == "VISUAL_ROUTER"
    return result


def photo(asset_id: str, sha256: str, story_ids: list[str]) -> dict:
    return {
        "asset_id": asset_id,
        "instance_id": "valcea",
        "kind": "photograph",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "sha256": sha256,
        "source_type": "creative_commons",
        "source_url": "https://example.org/source-photo",
        "direct_source_url": f"https://example.org/{asset_id}.jpg",
        "credit": "Autor / sursă — licență",
        "rights_basis": "creative_commons",
        "license_url": "https://example.org/license",
        "rights_note": "Utilizare editorială permisă.",
        "alt_text": "Fotografie reală relevantă pentru subiect.",
        "story_ids": list(story_ids),
    }


def video(asset_id: str, sha256: str, story_ids: list[str]) -> dict:
    item = photo(asset_id, sha256, story_ids)
    item["kind"] = "video"
    item["source_type"] = "official_press"
    item["rights_basis"] = "press_use"
    item["direct_source_url"] = f"https://example.org/{asset_id}.mp4"
    item["alt_text"] = "Video real relevant pentru subiect."
    return item


def inventory(*assets: dict) -> dict:
    return {"schema_version": "1.0", "instance_id": "valcea", "assets": list(assets)}


def test_instagram_carousel_binds_one_real_asset_per_story() -> None:
    result = series_visual_router.bind_series_visuals(
        composition("instagram"), channel("instagram"),
        inventory(photo("photo-b", HASH_B, ["story-b"]), photo("photo-a", HASH_A, ["story-a"]), photo("photo-extra", HASH_C, ["story-a"])),
    )
    assert result["blocked"] is False
    binding = result["binding"]
    assert binding["status"] == "SERIES_VISUAL_READY"
    assert binding["selected_asset_ids"] == ["photo-a", "photo-b"]
    assert binding["covered_story_ids"] == ["story-a", "story-b"]
    assert binding["full_story_coverage_required"] is True
    assert binding["next_gate"] == "CADENCE_FATIGUE"
    assert result["visual_transition"]["persist_before_next_gate"] is True


def test_instagram_blocks_when_one_story_has_no_exact_visual() -> None:
    result = series_visual_router.bind_series_visuals(
        composition("instagram"), channel("instagram"),
        inventory(photo("photo-a", HASH_A, ["story-a"]), photo("photo-a2", HASH_B, ["story-a"])),
    )
    assert result["blocked"] is True
    assert result["hard_blocks"] == ["MISSING_REAL_MEDIA_FOR_SERIES_STORY:story-b"]
    assert result["binding"]["status"] == "SERIES_VISUAL_BLOCKED"


def test_tiktok_requires_real_video_for_every_verified_beat() -> None:
    result = series_visual_router.bind_series_visuals(
        composition("tiktok"), channel("tiktok"),
        inventory(video("video-a", HASH_A, ["story-a"]), photo("photo-b", HASH_B, ["story-b"])),
    )
    assert result["blocked"] is True
    assert result["hard_blocks"] == ["MISSING_REAL_MEDIA_FOR_SERIES_STORY:story-b"]
    rejected = {item["asset_id"]: item["reasons"] for item in result["binding"]["rejected_candidates"]}
    assert "WRONG_MEDIA_KIND" in rejected["photo-b"]


def test_youtube_short_binds_real_video_coverage_without_direct_publish_claim() -> None:
    result = series_visual_router.bind_series_visuals(
        composition("youtube"), channel("youtube"),
        inventory(video("video-a", HASH_A, ["story-a"]), video("video-b", HASH_B, ["story-b"])),
    )
    assert result["blocked"] is False
    assert result["binding"]["selected_asset_ids"] == ["video-a", "video-b"]
    assert result["binding"]["full_story_coverage_required"] is True
    assert result["guards"]["network_dispatch_performed"] is False
    assert result["guards"]["credential_values_read"] is False


def test_facebook_roundup_uses_exact_story_hero_without_claiming_full_coverage() -> None:
    result = series_visual_router.bind_series_visuals(
        composition("facebook"), channel("facebook"),
        inventory(photo("photo-b", HASH_B, ["story-b"]), photo("photo-a", HASH_A, ["story-a"])),
    )
    assert result["blocked"] is False
    assert result["binding"]["selected_asset_ids"] == ["photo-a"]
    assert result["binding"]["covered_story_ids"] == ["story-a"]
    assert result["binding"]["full_story_coverage_required"] is False


def test_contextual_media_without_explicit_series_story_association_is_rejected() -> None:
    contextual = photo("contextual", HASH_A, ["story-a"])
    contextual.pop("story_ids")
    result = series_visual_router.bind_series_visuals(composition("facebook"), channel("facebook"), inventory(contextual))
    assert result["blocked"] is True
    assert "SERIES_STORY_ASSOCIATION_REQUIRED" in result["binding"]["rejected_candidates"][0]["reasons"]


def test_synthetic_media_is_fail_closed() -> None:
    bad = photo("synthetic", HASH_A, ["story-a"])
    bad["synthetic"] = True
    result = series_visual_router.bind_series_visuals(composition("facebook"), channel("facebook"), inventory(bad))
    assert result["blocked"] is True
    reasons = result["binding"]["rejected_candidates"][0]["reasons"]
    assert "SYNTHETIC_OR_UNVERIFIED_MEDIA" in reasons and "SYNTHETIC_FORBIDDEN" in reasons


def test_missing_provenance_and_rights_are_fail_closed() -> None:
    bad = photo("bad-rights", HASH_A, ["story-a"])
    bad["credit"] = ""
    bad["source_url"] = ""
    bad["rights_basis"] = "unknown"
    result = series_visual_router.bind_series_visuals(composition("facebook"), channel("facebook"), inventory(bad))
    assert result["blocked"] is True
    reasons = result["binding"]["rejected_candidates"][0]["reasons"]
    assert "MISSING_CREDIT" in reasons
    assert "MISSING_SOURCE_URL" in reasons
    assert "MISSING_OR_INVALID_RIGHTS" in reasons


def test_cross_instance_inventory_is_blocked_before_selection() -> None:
    media = inventory(photo("photo-a", HASH_A, ["story-a"]))
    media["instance_id"] = "cluj"
    result = series_visual_router.bind_series_visuals(composition("facebook"), channel("facebook"), media)
    assert result["blocked"] is True
    assert "INSTANCE_MISMATCH" in result["hard_blocks"]
    assert result["binding"] is None


def test_foreign_story_asset_cannot_illustrate_series() -> None:
    result = series_visual_router.bind_series_visuals(
        composition("facebook"), channel("facebook"), inventory(photo("foreign", HASH_A, ["story-foreign"]))
    )
    assert result["blocked"] is True
    reasons = result["binding"]["rejected_candidates"][0]["reasons"]
    assert "SERIES_STORY_ASSOCIATION_REQUIRED" in reasons
    assert "STORY_MISMATCH" in reasons


def test_source_product_fingerprint_tamper_is_fail_closed() -> None:
    composed = composition("facebook")
    composed["product"]["series_frame"]["text"] = "Tampered copy"
    result = series_visual_router.bind_series_visuals(
        composed, channel("facebook"), inventory(photo("photo-a", HASH_A, ["story-a"]))
    )
    assert result["blocked"] is True
    assert "SERIES_PRODUCT_FINGERPRINT_MISMATCH" in result["hard_blocks"]
    assert result["binding"] is None


def test_wrong_runtime_gate_is_rejected() -> None:
    composed = composition("facebook")
    composed["product"]["next_gate"] = "CADENCE_FATIGUE"
    product = composed["product"]
    payload = {key: value for key, value in product.items() if key != "product_fingerprint_sha256"}
    product["product_fingerprint_sha256"] = series_visual_router.visual_router._digest(payload)
    result = series_visual_router.bind_series_visuals(
        composed, channel("facebook"), inventory(photo("photo-a", HASH_A, ["story-a"]))
    )
    assert result["blocked"] is True
    assert "SERIES_PRODUCT_NOT_ROUTED_TO_VISUAL_GATE" in result["hard_blocks"]


def test_duplicate_asset_content_cannot_satisfy_distinct_carousel() -> None:
    result = series_visual_router.bind_series_visuals(
        composition("instagram"), channel("instagram"),
        inventory(photo("photo-a", HASH_A, ["story-a"]), photo("photo-b", HASH_A, ["story-b"])),
    )
    assert result["blocked"] is True
    rejected = {item["asset_id"]: item["reasons"] for item in result["binding"]["rejected_candidates"]}
    assert "DUPLICATE_ASSET_CONTENT" in rejected["photo-a"]
    assert "DUPLICATE_ASSET_CONTENT" in rejected["photo-b"]


def test_zero_paid_and_real_media_policies_cannot_be_weakened() -> None:
    ch = channel("facebook")
    ch["zero_paid_dependency"] = False
    ch["media_policy"]["provenance_required"] = False
    result = series_visual_router.bind_series_visuals(
        composition("facebook"), ch, inventory(photo("photo-a", HASH_A, ["story-a"]))
    )
    assert result["blocked"] is True
    assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"]
    assert "PROVENANCE_POLICY_REQUIRED" in result["hard_blocks"]


def test_predictive_analytics_and_secret_fields_never_affect_or_leak_binding() -> None:
    media = inventory(photo("photo-b", HASH_B, ["story-b"]), photo("photo-a", HASH_A, ["story-a"]), photo("extra", HASH_C, ["story-a"]))
    baseline = series_visual_router.bind_series_visuals(composition("instagram"), channel("instagram"), media)
    poisoned = copy.deepcopy(media)
    poisoned["predicted_views"] = 99999999
    poisoned["assets"][0]["secret_token"] = "DO-NOT-LEAK"
    poisoned["assets"][0]["analytics"] = {"virality_probability": 0.999}
    poisoned["assets"].reverse()
    second = series_visual_router.bind_series_visuals(composition("instagram"), channel("instagram"), poisoned)
    assert baseline["binding"]["binding_fingerprint_sha256"] == second["binding"]["binding_fingerprint_sha256"]
    assert baseline["binding"]["selected_asset_ids"] == second["binding"]["selected_asset_ids"]
    serialized = str(second)
    assert "DO-NOT-LEAK" not in serialized
    assert "99999999" not in serialized
    assert "0.999" not in serialized


def test_output_is_deterministic() -> None:
    media = inventory(video("video-b", HASH_B, ["story-b"]), video("video-a", HASH_A, ["story-a"]), video("video-extra", HASH_C, ["story-a", "story-b"]))
    first = series_visual_router.bind_series_visuals(composition("tiktok"), channel("tiktok"), media)
    second = series_visual_router.bind_series_visuals(composition("tiktok"), channel("tiktok"), copy.deepcopy(media))
    assert first == second
    assert len(first["binding"]["binding_fingerprint_sha256"]) == 64


def main() -> int:
    tests = [
        test_instagram_carousel_binds_one_real_asset_per_story,
        test_instagram_blocks_when_one_story_has_no_exact_visual,
        test_tiktok_requires_real_video_for_every_verified_beat,
        test_youtube_short_binds_real_video_coverage_without_direct_publish_claim,
        test_facebook_roundup_uses_exact_story_hero_without_claiming_full_coverage,
        test_contextual_media_without_explicit_series_story_association_is_rejected,
        test_synthetic_media_is_fail_closed,
        test_missing_provenance_and_rights_are_fail_closed,
        test_cross_instance_inventory_is_blocked_before_selection,
        test_foreign_story_asset_cannot_illustrate_series,
        test_source_product_fingerprint_tamper_is_fail_closed,
        test_wrong_runtime_gate_is_rejected,
        test_duplicate_asset_content_cannot_satisfy_distinct_carousel,
        test_zero_paid_and_real_media_policies_cannot_be_weakened,
        test_predictive_analytics_and_secret_fields_never_affect_or_leak_binding,
        test_output_is_deterministic,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Series Visual Router acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
