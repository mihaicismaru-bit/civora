#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS fail-closed Visual Router."""
from __future__ import annotations

import copy

from content_atomizer import atomize_story
from format_engine import build_native_product
from hook_engine import build_hook
from visual_router import bind_visuals


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "story-visual-1",
        "material_fact_gate": "PASS",
        "headline": "Primăria publică programul pentru weekend",
        "dek": "Programul include două evenimente cu acces liber.",
        "paragraphs": ["Primul eveniment începe sâmbătă la ora 18:00."],
        "facts": [{"fact_id": "f1", "text": "Accesul este liber."}],
        "topics": ["service_journalism", "local_events"],
        "risk_flags": [],
    }


def channel(platform: str) -> dict:
    native = {
        "facebook": ["text", "single_photo"],
        "instagram": ["single_photo", "carousel", "story", "reel"],
        "tiktok": ["single_photo", "short"],
        "threads": ["text", "thread"],
    }[platform]
    return {
        "channel_id": f"valcea-{platform}",
        "instance_id": "valcea",
        "platform": platform,
        "status": "active",
        "editorial_mix": {"priorities": ["service_journalism"], "exclusions": ["rage_bait", "fake_urgency"]},
        "native_formats": native,
        "media_policy": {
            "real_media_only": True,
            "provenance_required": True,
            "reuse_rights_required": True,
            "synthetic_real_person_forbidden": True,
        },
        "link_policy": {"mode": "required" if platform == "facebook" else "optional", "canonical_hosts": ["valceaclar.ro"]},
        "approval_gates": {
            "low_risk_auto": platform != "tiktok",
            "reputational_human": True,
            "corrections_priority": True,
        },
    }


def format_result(platform: str) -> dict:
    atoms = atomize_story(story())
    ch = channel(platform)
    return build_native_product(atoms, build_hook(atoms, ch), ch)


def photo(
    asset_id: str,
    sha256: str,
    *,
    story_ids: list[str] | None = None,
    source_type: str = "creative_commons",
    rights_basis: str = "creative_commons",
) -> dict:
    item = {
        "asset_id": asset_id,
        "instance_id": "valcea",
        "kind": "photograph",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "sha256": sha256,
        "source_type": source_type,
        "source_url": "https://example.org/source-photo",
        "direct_source_url": "https://example.org/photo.jpg",
        "credit": "Autor / sursă — licență",
        "rights_basis": rights_basis,
        "license_url": "https://example.org/license",
        "rights_note": "Utilizare editorială permisă.",
        "alt_text": "Fotografie reală relevantă pentru subiect.",
    }
    if story_ids is not None:
        item["story_ids"] = story_ids
    return item


def video(asset_id: str, sha256: str, *, story_ids: list[str] | None = None) -> dict:
    item = photo(asset_id, sha256, story_ids=story_ids, source_type="official_press", rights_basis="press_use")
    item["kind"] = "video"
    item["direct_source_url"] = "https://example.org/video.mp4"
    item["alt_text"] = "Video real relevant pentru subiect."
    return item


def inventory(*assets: dict) -> dict:
    return {"schema_version": "1.0", "instance_id": "valcea", "assets": list(assets)}


def test_facebook_binds_real_photo_with_complete_provenance() -> None:
    result = bind_visuals(
        format_result("facebook"),
        channel("facebook"),
        inventory(photo("photo-exact", HASH_A, story_ids=["story-visual-1"])),
    )
    assert result["blocked"] is False
    binding = result["binding"]
    assert binding["status"] == "VISUAL_READY"
    assert binding["selected_asset_ids"] == ["photo-exact"]
    assert binding["selected_assets"][0]["kind"] == "photograph"
    assert binding["selected_assets"][0]["synthetic"] is False
    assert binding["provenance_complete"] is True
    assert binding["reuse_rights_complete"] is True
    assert binding["next_gate"] == "LINK_BINDING"


def test_instagram_carousel_requires_and_binds_two_distinct_assets() -> None:
    result = bind_visuals(
        format_result("instagram"),
        channel("instagram"),
        inventory(
            photo("photo-a", HASH_A, story_ids=["story-visual-1"]),
            photo("photo-b", HASH_B, story_ids=["story-visual-1"]),
            photo("photo-c", HASH_C),
        ),
    )
    assert result["blocked"] is False
    assert result["binding"]["required_assets"] == 2
    assert result["binding"]["selected_asset_ids"] == ["photo-a", "photo-b"]


def test_tiktok_short_requires_real_video_and_rejects_photo_only_inventory() -> None:
    result = bind_visuals(
        format_result("tiktok"),
        channel("tiktok"),
        inventory(photo("photo-only", HASH_A, story_ids=["story-visual-1"])),
    )
    assert result["blocked"] is True
    assert result["hard_blocks"] == ["INSUFFICIENT_APPROVED_REAL_MEDIA"]
    rejected = result["binding"]["rejected_candidates"]
    assert "WRONG_MEDIA_KIND" in rejected[0]["reasons"]


def test_tiktok_binds_verified_real_video() -> None:
    result = bind_visuals(
        format_result("tiktok"),
        channel("tiktok"),
        inventory(video("video-exact", HASH_C, story_ids=["story-visual-1"])),
    )
    assert result["blocked"] is False
    assert result["binding"]["selected_assets"][0]["kind"] == "video"
    assert result["binding"]["next_gate"] == "PUBLICATION_STATE"


def test_synthetic_media_is_fail_closed() -> None:
    bad = photo("synthetic", HASH_A, story_ids=["story-visual-1"])
    bad["synthetic"] = True
    result = bind_visuals(format_result("facebook"), channel("facebook"), inventory(bad))
    assert result["blocked"] is True
    reasons = result["binding"]["rejected_candidates"][0]["reasons"]
    assert "SYNTHETIC_OR_UNVERIFIED_MEDIA" in reasons
    assert "SYNTHETIC_FORBIDDEN" in reasons


def test_missing_provenance_or_rights_is_rejected() -> None:
    bad = photo("bad-rights", HASH_A, story_ids=["story-visual-1"])
    bad["credit"] = ""
    bad["rights_basis"] = "unknown"
    bad["source_url"] = ""
    result = bind_visuals(format_result("facebook"), channel("facebook"), inventory(bad))
    assert result["blocked"] is True
    reasons = result["binding"]["rejected_candidates"][0]["reasons"]
    assert "MISSING_CREDIT" in reasons
    assert "MISSING_SOURCE_URL" in reasons
    assert "MISSING_OR_INVALID_RIGHTS" in reasons


def test_story_mismatch_is_rejected_instead_of_cross_story_reuse() -> None:
    foreign = photo("other-story", HASH_A, story_ids=["different-story"])
    result = bind_visuals(format_result("facebook"), channel("facebook"), inventory(foreign))
    assert result["blocked"] is True
    assert "STORY_MISMATCH" in result["binding"]["rejected_candidates"][0]["reasons"]


def test_instance_mismatch_inventory_fails_before_selection() -> None:
    media = inventory(photo("photo-a", HASH_A, story_ids=["story-visual-1"]))
    media["instance_id"] = "cluj"
    result = bind_visuals(format_result("facebook"), channel("facebook"), media)
    assert result["blocked"] is True
    assert "INSTANCE_MISMATCH" in result["hard_blocks"]
    assert result["binding"] is None


def test_exact_story_match_outranks_contextual_approved_media() -> None:
    result = bind_visuals(
        format_result("facebook"),
        channel("facebook"),
        inventory(
            photo("contextual", HASH_A),
            photo("exact", HASH_B, story_ids=["story-visual-1"]),
        ),
    )
    assert result["blocked"] is False
    assert result["binding"]["selected_asset_ids"] == ["exact"]


def test_invalid_content_identity_is_rejected() -> None:
    bad = photo("bad-hash", "not-a-hash", story_ids=["story-visual-1"])
    result = bind_visuals(format_result("facebook"), channel("facebook"), inventory(bad))
    assert result["blocked"] is True
    assert "MISSING_OR_INVALID_SHA256" in result["binding"]["rejected_candidates"][0]["reasons"]


def test_text_native_product_passes_without_media() -> None:
    result = bind_visuals(format_result("threads"), channel("threads"), inventory())
    assert result["blocked"] is False
    assert result["binding"]["status"] == "NOT_REQUIRED"
    assert result["binding"]["selected_assets"] == []


def test_output_is_deterministic_and_does_not_leak_poison_fields() -> None:
    media = inventory(
        photo("b-photo", HASH_B, story_ids=["story-visual-1"]),
        photo("a-photo", HASH_A, story_ids=["story-visual-1"]),
    )
    media["assets"][0]["secret_token"] = "DO-NOT-LEAK"
    media["assets"][0]["analytics"] = {"viral": True, "views": 999999}
    first = bind_visuals(format_result("facebook"), channel("facebook"), media)
    second = bind_visuals(format_result("facebook"), channel("facebook"), copy.deepcopy(media))
    assert first == second
    assert first["binding"]["selected_asset_ids"] == ["a-photo"]
    serialized = str(first)
    assert "DO-NOT-LEAK" not in serialized
    assert "999999" not in serialized
    assert len(first["binding"]["binding_fingerprint_sha256"]) == 64


def main() -> int:
    tests = [
        test_facebook_binds_real_photo_with_complete_provenance,
        test_instagram_carousel_requires_and_binds_two_distinct_assets,
        test_tiktok_short_requires_real_video_and_rejects_photo_only_inventory,
        test_tiktok_binds_verified_real_video,
        test_synthetic_media_is_fail_closed,
        test_missing_provenance_or_rights_is_rejected,
        test_story_mismatch_is_rejected_instead_of_cross_story_reuse,
        test_instance_mismatch_inventory_fails_before_selection,
        test_exact_story_match_outranks_contextual_approved_media,
        test_invalid_content_identity_is_rejected,
        test_text_native_product_passes_without_media,
        test_output_is_deterministic_and_does_not_leak_poison_fields,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Visual Router acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
