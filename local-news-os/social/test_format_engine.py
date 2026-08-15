#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS native social Format Engine."""
from __future__ import annotations

import copy

from content_atomizer import atomize_story
from format_engine import build_native_product
from hook_engine import build_hook


def story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "story-format-1",
        "material_fact_gate": "PASS",
        "headline": "Primăria publică programul pentru weekend",
        "dek": "Programul include două evenimente cu acces liber.",
        "paragraphs": [
            "Primul eveniment începe sâmbătă la ora 18:00.",
            "Al doilea eveniment este programat duminică în parc.",
        ],
        "facts": [{"fact_id": "f1", "text": "Accesul este liber."}],
        "quotes": [{"quote_id": "q1", "text": "Programul rămâne neschimbat."}],
        "topics": ["service_journalism", "local_events"],
        "risk_flags": [],
    }


def channel(platform: str) -> dict:
    native = {
        "facebook": ["text", "single_photo"],
        "instagram": ["single_photo", "carousel", "story", "reel"],
        "tiktok": ["single_photo", "short"],
        "threads": ["text", "thread"],
        "linkedin": ["text", "single_photo"],
        "whatsapp": ["alert", "digest"],
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


def bundle(source: dict | None = None) -> dict:
    return atomize_story(source or story())


def hook(platform: str, source: dict | None = None) -> dict:
    atoms = bundle(source)
    return build_hook(atoms, channel(platform))


def product(platform: str, source: dict | None = None) -> dict:
    atoms = bundle(source)
    return build_native_product(atoms, build_hook(atoms, channel(platform)), channel(platform))


def test_facebook_selects_native_photo_feed_and_defers_visual_binding() -> None:
    result = product("facebook")
    assert result["blocked"] is False
    item = result["product"]
    assert item["native_format"] == "single_photo"
    assert item["format_family"] == "feed_post"
    assert item["visual_requirement"]["required"] is True
    assert item["visual_requirement"]["binding_status"] == "PENDING_VISUAL_ROUTER"
    assert item["next_gate"] == "VISUAL_ROUTER"


def test_instagram_prefers_carousel_and_builds_visual_first_structure() -> None:
    result = product("instagram")
    item = result["product"]
    assert item["native_format"] == "carousel"
    assert item["native_structure"]["composition"] == "visual_first_caption_second"
    assert item["visual_requirement"]["minimum_assets"] == 2
    assert item["native_structure"]["visual_text_atom_ids"]


def test_tiktok_prefers_short_and_never_generates_voiceover() -> None:
    result = product("tiktok")
    item = result["product"]
    assert item["native_format"] == "short"
    assert item["native_structure"]["surface"] == "short_video"
    assert item["native_structure"]["voiceover_generation_allowed"] is False
    assert item["approval"]["human_review_required_before_publish"] is True


def test_cross_platform_products_are_native_not_verbatim_reuse() -> None:
    facebook = product("facebook")["product"]
    instagram = product("instagram")["product"]
    tiktok = product("tiktok")["product"]
    assert facebook["hook"]["text"] != instagram["hook"]["text"]
    assert instagram["hook"]["text"] != tiktok["hook"]["text"]
    assert len({facebook["native_format"], instagram["native_format"], tiktok["native_format"]}) == 3
    for item in (facebook, instagram, tiktok):
        assert item["cross_post_policy"] == "NATIVE_PRODUCT_ONLY"
        assert item["verbatim_cross_platform_reuse_allowed"] is False


def test_supporting_blocks_preserve_source_text_and_quotes() -> None:
    result = product("facebook")["product"]
    source_texts = {atom["text"] for atom in bundle()["atoms"] if atom.get("text")}
    for block in result["content_blocks"]:
        assert block["text"] in source_texts
        if block["source_atom_type"] == "quote":
            assert block["verbatim_required"] is True


def test_hook_source_atom_is_not_duplicated_in_body() -> None:
    item = product("facebook")["product"]
    hook_atom_id = item["hook"]["source_atom_id"]
    assert hook_atom_id not in {block["source_atom_id"] for block in item["content_blocks"]}


def test_required_link_is_declared_but_not_invented() -> None:
    item = product("facebook")["product"]
    requirement = item["link_requirement"]
    assert requirement["mode"] == "required"
    assert requirement["binding_status"] == "PENDING_LINK_BINDING"
    assert requirement["canonical_hosts"] == ["valceaclar.ro"]
    assert "url" not in requirement


def test_instance_mismatch_fails_closed() -> None:
    atoms = bundle()
    hk = build_hook(atoms, channel("facebook"))
    foreign = channel("facebook")
    foreign["instance_id"] = "cluj"
    result = build_native_product(atoms, hk, foreign)
    assert result["blocked"] is True
    assert "INSTANCE_MISMATCH" in result["hard_blocks"]
    assert result["product"] is None


def test_blocked_hook_fails_closed() -> None:
    atoms = bundle()
    blocked_hook = hook("facebook")
    blocked_hook["blocked"] = True
    blocked_hook["hook"] = None
    result = build_native_product(atoms, blocked_hook, channel("facebook"))
    assert result["blocked"] is True
    assert "HOOK_BLOCKED" in result["hard_blocks"]


def test_correction_uses_alert_when_channel_supports_it() -> None:
    source = story()
    source["correction"] = True
    atoms = bundle(source)
    hk = build_hook(atoms, channel("whatsapp"))
    result = build_native_product(atoms, hk, channel("whatsapp"))
    assert result["blocked"] is False
    assert result["product"]["native_format"] == "alert"
    assert result["product"]["correction"] is True
    assert result["product"]["hook"]["text"].startswith("Corecție — ")


def test_deterministic_output_and_id() -> None:
    first = product("instagram")
    second = product("instagram")
    assert first == second
    assert first["product"]["product_id"] == second["product"]["product_id"]
    assert first["product"]["product_fingerprint_sha256"] == second["product"]["product_fingerprint_sha256"]


def test_poison_fields_and_fake_analytics_cannot_enter_product() -> None:
    atoms = bundle()
    atoms["raw_story"] = "URGENT invented claim 999999"
    atoms["analytics"] = {"views": 999999999, "viral": True}
    hk = build_hook(atoms, channel("facebook"))
    result = build_native_product(atoms, hk, channel("facebook"))
    serialized = str(result["product"])
    assert "999999" not in serialized
    assert result["product"]["analytics_used"] is False
    assert result["product"]["invented_claims_allowed"] is False


def main() -> int:
    tests = [
        test_facebook_selects_native_photo_feed_and_defers_visual_binding,
        test_instagram_prefers_carousel_and_builds_visual_first_structure,
        test_tiktok_prefers_short_and_never_generates_voiceover,
        test_cross_platform_products_are_native_not_verbatim_reuse,
        test_supporting_blocks_preserve_source_text_and_quotes,
        test_hook_source_atom_is_not_duplicated_in_body,
        test_required_link_is_declared_but_not_invented,
        test_instance_mismatch_fails_closed,
        test_blocked_hook_fails_closed,
        test_correction_uses_alert_when_channel_supports_it,
        test_deterministic_output_and_id,
        test_poison_fields_and_fake_analytics_cannot_enter_product,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Format Engine acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
