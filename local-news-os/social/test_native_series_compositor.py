#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import content_atomizer

MODULE = MODULE_DIR / "native_series_compositor.py"
spec = importlib.util.spec_from_file_location("native_series_compositor", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

NATIVE_FORMATS = {
    "facebook": ["text", "single_photo", "carousel"],
    "instagram": ["single_photo", "carousel", "story", "reel"],
    "tiktok": ["short", "single_photo", "story"],
    "youtube": ["short", "long_video", "single_photo"],
    "threads": ["thread", "text", "single_photo"],
    "linkedin": ["text", "single_photo", "carousel"],
    "telegram": ["text", "digest", "single_photo", "alert"],
    "whatsapp": ["text", "single_photo"],
}

STAGED_FORMATS = {
    "facebook": ["single_photo", "text"],
    "instagram": ["carousel", "single_photo", "story"],
    "tiktok": ["short", "single_photo"],
    "youtube": ["short", "long_video"],
    "threads": ["thread", "text"],
    "linkedin": ["text", "single_photo"],
    "telegram": ["digest", "text"],
    "whatsapp": ["text", "single_photo"],
}

PROMISES = {
    "facebook": "Ediția locală verificată, pe scurt.",
    "instagram": "Vâlcea pe scurt, explicată vizual.",
    "tiktok": "Vâlcea azi, în cadre scurte și verificate.",
    "youtube": "Cele mai importante lucruri locale, într-un recap video verificat.",
    "threads": "Vâlcea în idei scurte, cu context verificat.",
    "linkedin": "Context local pentru profesioniști și decidenți.",
    "telegram": "Un digest rapid al lucrurilor locale de știut.",
    "whatsapp": "Doar actualizările locale esențiale, fără zgomot.",
}


def channel(platform="facebook"):
    return {
        "schema_version": "1.0",
        "channel_id": f"valcea-{platform}",
        "instance_id": "valcea",
        "platform": platform,
        "status": "active" if platform not in {"threads", "linkedin", "telegram", "whatsapp", "youtube"} else "outbox_only",
        "native_formats": list(NATIVE_FORMATS[platform]),
        "media_policy": {
            "real_media_only": True,
            "provenance_required": True,
            "reuse_rights_required": True,
            "synthetic_real_person_forbidden": True,
        },
        "link_policy": {"mode": "optional", "canonical_hosts": ["valceaclar.ro"]},
        "series": [{"series_id": "daily-brief", "promise": PROMISES[platform]}],
        "approval_gates": {
            "low_risk_auto": platform not in {"tiktok", "youtube"},
            "reputational_human": True,
            "corrections_priority": True,
        },
        "metrics": {"observed_only": True},
        "zero_paid_dependency": True,
    }


def stories():
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


def fingerprint(story):
    return content_atomizer.atomize_story(story)["source_fingerprint_sha256"]


def staged(platform="facebook", source_stories=None, formats=None):
    source_stories = list(source_stories or stories())
    return {
        "series_execution_id": f"series-execution:{platform}-daily",
        "occurrence_id": f"occurrence:{platform}-daily",
        "instance_id": "valcea",
        "channel_id": f"valcea-{platform}",
        "series_id": "daily-brief",
        "series_slot_key": "daily-brief:2026-08-16:0:07:00",
        "status": "SERIES_COMPOSITION_PENDING",
        "publication_mode": "channel_native_series_composition_pending",
        "selected_story_ids": [story["story_id"] for story in source_stories],
        "selected_content_hashes": [fingerprint(story) for story in source_stories],
        "native_format_candidates": list(formats or STAGED_FORMATS[platform]),
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


def pool(source_stories=None):
    return {
        "instance_id": "valcea",
        "stories": copy.deepcopy(list(source_stories or stories())),
        "predicted_views": 999999,
        "virality_probability": 0.999,
    }


def compose(platform="facebook", source_stories=None, formats=None):
    source_stories = list(source_stories or stories())
    return mod.compose_staged_series(
        channel(platform),
        staged(platform, source_stories, formats=formats),
        pool(source_stories),
    )


def run(name, fn):
    fn()
    print(f"PASS {name}")


def facebook_roundup_is_native_and_visual_routed_next():
    result = compose("facebook")
    assert result["blocked"] is False
    product = result["product"]
    assert product["native_format"] == "single_photo"
    assert product["format_family"] == "feed_roundup"
    assert product["native_structure"]["composition"] == "series_frame_then_numbered_updates"
    assert len(product["items"]) == 2
    assert product["visual_requirement"]["required"] is True
    assert product["visual_requirement"]["provenance_required"] is True
    assert product["next_gate"] == "VISUAL_ROUTER"
    assert result["composition_transition"]["to_status"] == "SERIES_FORMAT_READY"
    assert all(item["hook"]["source_preserving"] for item in product["items"])


def instagram_prefers_real_carousel():
    result = compose("instagram")
    assert result["blocked"] is False
    product = result["product"]
    assert product["native_format"] == "carousel"
    assert product["format_family"] == "visual_roundup"
    assert product["native_structure"]["composition"] == "series_cover_then_story_cards"
    assert product["visual_requirement"]["minimum_assets"] == 2
    assert product["visual_requirement"]["distinct_assets_required"] is True
    assert product["visual_requirement"]["subject_match_scope"] == "series_selected_stories"


def single_story_carousel_falls_back_without_degrading_outside_staged_formats():
    one = stories()[:1]
    result = compose("instagram", one, formats=["carousel", "single_photo"])
    assert result["blocked"] is False
    assert result["product"]["native_format"] == "single_photo"
    assert result["product"]["visual_requirement"]["minimum_assets"] == 1


def tiktok_short_requires_real_video_and_no_generated_voiceover():
    result = compose("tiktok")
    product = result["product"]
    assert result["blocked"] is False
    assert product["native_format"] == "short"
    assert product["visual_requirement"]["media_kind"] == "real_video"
    assert product["native_structure"]["voiceover_generation_allowed"] is False


def telegram_and_whatsapp_are_distinct_sibling_products():
    telegram = compose("telegram")["product"]
    whatsapp = compose("whatsapp")["product"]
    assert telegram["native_format"] == "digest"
    assert telegram["format_family"] == "channel_digest"
    assert whatsapp["native_format"] == "text"
    assert whatsapp["format_family"] == "low_noise_digest"
    assert telegram["native_structure"]["composition"] != whatsapp["native_structure"]["composition"]
    assert telegram["series_frame"]["text"] != whatsapp["series_frame"]["text"]
    assert telegram["product_fingerprint_sha256"] != whatsapp["product_fingerprint_sha256"]


def threads_and_linkedin_keep_native_structures():
    threads = compose("threads")["product"]
    linkedin = compose("linkedin")["product"]
    assert threads["native_format"] == "thread"
    assert threads["native_structure"]["composition"] == "series_opening_then_one_story_per_post"
    assert linkedin["native_format"] == "text"
    assert linkedin["native_structure"]["composition"] == "series_context_then_evidence_items"
    assert threads["product_id"] != linkedin["product_id"]


def content_hash_tamper_blocks_fail_closed():
    source = stories()
    item = staged("facebook", source)
    item["selected_content_hashes"][0] = "0" * 64
    result = mod.compose_staged_series(channel("facebook"), item, pool(source))
    assert result["blocked"] is True
    assert "STORY_CONTENT_HASH_MISMATCH:story-a" in result["hard_blocks"]
    assert result["product"] is None


def missing_selected_story_blocks():
    source = stories()
    item = staged("facebook", source)
    source_pool = pool(source[1:])
    result = mod.compose_staged_series(channel("facebook"), item, source_pool)
    assert result["blocked"] is True
    assert "SELECTED_STORY_MISSING:story-a" in result["hard_blocks"]


def duplicate_source_story_blocks():
    source = stories()
    source_pool = pool(source)
    source_pool["stories"].append(copy.deepcopy(source[0]))
    result = mod.compose_staged_series(channel("facebook"), staged("facebook", source), source_pool)
    assert result["blocked"] is True
    assert "DUPLICATE_SOURCE_STORY:story-a" in result["hard_blocks"]


def instance_and_channel_isolation_are_fail_closed():
    source = stories()
    bad_pool = pool(source)
    bad_pool["instance_id"] = "other"
    instance_result = mod.compose_staged_series(channel("facebook"), staged("facebook", source), bad_pool)
    assert instance_result["blocked"] is True
    assert "SOURCE_POOL_INSTANCE_MISMATCH" in instance_result["hard_blocks"]

    bad_stage = staged("facebook", source)
    bad_stage["channel_id"] = "valcea-instagram"
    channel_result = mod.compose_staged_series(channel("facebook"), bad_stage, pool(source))
    assert channel_result["blocked"] is True
    assert "STAGED_CHANNEL_MISMATCH" in channel_result["hard_blocks"]


def material_fact_hold_blocks_story_composition():
    source = stories()
    source[0]["material_fact_gate"] = "HOLD_REVIEW"
    result = compose("facebook", source)
    assert result["blocked"] is True
    assert any(value.startswith("STORY_ATOMIZER_BLOCKED:story-a:MATERIAL_FACT_GATE") for value in result["hard_blocks"])


def clickbait_headline_falls_back_to_safe_source_atom():
    source = stories()
    source[0]["headline"] = "Șocant: nu o să crezi ce s-a întâmplat"
    source[0]["dek"] = "Podul din centru se redeschide luni după lucrările programate."
    result = compose("facebook", source)
    assert result["blocked"] is False
    first = result["product"]["items"][0]
    assert first["hook"]["source_atom_type"] == "dek"
    assert "Șocant" not in first["hook"]["text"]
    assert first["hook"]["clickbait_guard"] == "PASS"


def all_unsafe_hook_material_blocks_story():
    source = stories()
    source[0] = {
        "instance_id": "valcea",
        "story_id": "story-a",
        "material_fact_gate": "PASS",
        "headline": "Șocant: nu o să crezi ce s-a întâmplat",
        "dek": "Exclusiv: doar la noi afli ce nu vor să știi",
        "topics": ["infrastructure"],
    }
    result = compose("facebook", source)
    assert result["blocked"] is True
    assert any(value.startswith("STORY_HOOK_BLOCKED:story-a:NO_SAFE_HOOK_ATOM") for value in result["hard_blocks"])


def predictive_fields_cannot_change_product_identity():
    source = stories()
    base = compose("facebook", source)
    noisy_stories = copy.deepcopy(source)
    noisy_stories[0]["predicted_views"] = 5000000
    noisy_stories[0]["predicted_engagement"] = 0.99
    ch = channel("facebook")
    ch["virality_probability"] = 1.0
    noisy_pool = pool(noisy_stories)
    noisy_pool["predicted_saves"] = 777777
    noisy = mod.compose_staged_series(ch, staged("facebook", noisy_stories), noisy_pool)
    assert base["blocked"] is False and noisy["blocked"] is False
    assert base["product"]["product_fingerprint_sha256"] == noisy["product"]["product_fingerprint_sha256"]
    assert noisy["guards"]["predictive_analytics_used"] is False


def incompatible_staged_format_blocks_without_silent_degrade():
    result = compose("facebook", formats=["short"])
    assert result["blocked"] is True
    assert "NO_COMPATIBLE_STAGED_NATIVE_FORMAT" in result["hard_blocks"]
    assert result["product"] is None


def zero_paid_dependency_is_required_everywhere():
    source = stories()
    ch = channel("facebook")
    ch["zero_paid_dependency"] = False
    result = mod.compose_staged_series(ch, staged("facebook", source), pool(source))
    assert result["blocked"] is True
    assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"]

    item = staged("facebook", source)
    item["zero_paid_dependency"] = False
    result2 = mod.compose_staged_series(channel("facebook"), item, pool(source))
    assert result2["blocked"] is True
    assert "STAGED_ZERO_PAID_DEPENDENCY_REQUIRED" in result2["hard_blocks"]


def staged_item_must_still_be_pending():
    source = stories()
    item = staged("facebook", source)
    item["status"] = "SERIES_FORMAT_READY"
    result = mod.compose_staged_series(channel("facebook"), item, pool(source))
    assert result["blocked"] is True
    assert "STAGED_ITEM_NOT_PENDING_COMPOSITION" in result["hard_blocks"]


def prior_copy_and_verbatim_reuse_are_forbidden():
    source = stories()
    item = staged("facebook", source)
    item["reuse_prior_copy"] = True
    item["verbatim_cross_platform_reuse_allowed"] = True
    result = mod.compose_staged_series(channel("facebook"), item, pool(source))
    assert result["blocked"] is True
    assert "PRIOR_COPY_REUSE_FORBIDDEN" in result["hard_blocks"]
    assert "VERBATIM_CROSS_PLATFORM_REUSE_FORBIDDEN" in result["hard_blocks"]


def output_is_deterministic():
    source = stories()
    args = (channel("instagram"), staged("instagram", source), pool(source))
    first = mod.compose_staged_series(*copy.deepcopy(args))
    second = mod.compose_staged_series(*copy.deepcopy(args))
    assert first == second
    assert first["product"]["product_id"].startswith("series-product:")
    assert first["product"]["network_dispatch_performed"] is False
    assert first["product"]["credential_values_read"] is False


if __name__ == "__main__":
    tests = [
        facebook_roundup_is_native_and_visual_routed_next,
        instagram_prefers_real_carousel,
        single_story_carousel_falls_back_without_degrading_outside_staged_formats,
        tiktok_short_requires_real_video_and_no_generated_voiceover,
        telegram_and_whatsapp_are_distinct_sibling_products,
        threads_and_linkedin_keep_native_structures,
        content_hash_tamper_blocks_fail_closed,
        missing_selected_story_blocks,
        duplicate_source_story_blocks,
        instance_and_channel_isolation_are_fail_closed,
        material_fact_hold_blocks_story_composition,
        clickbait_headline_falls_back_to_safe_source_atom,
        all_unsafe_hook_material_blocks_story,
        predictive_fields_cannot_change_product_identity,
        incompatible_staged_format_blocks_without_silent_degrade,
        zero_paid_dependency_is_required_everywhere,
        staged_item_must_still_be_pending,
        prior_copy_and_verbatim_reuse_are_forbidden,
        output_is_deterministic,
    ]
    for fn in tests:
        run(fn.__name__.replace("_", "-"), fn)
    print(f"Native Series Compositor acceptance tests: PASS ({len(tests)})")
