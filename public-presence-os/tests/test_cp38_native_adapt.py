from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
from public_presence_os.scoring import score_research_packet
from public_presence_os.master_draft import build_master_draft_brief
from public_presence_os.native_adapt import *

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-09-06T04:30:00Z"
CAPTURED = "2026-09-06T04:40:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_brief(*, exact_primary=True, excerpt="Specific public detail."):
    source_url = "https://example.gov.ro/news/38"
    signal = materialize_signal(RadarObservation(
        external_ref="story-38",
        source_url=source_url,
        source_class=RadarSourceClass.PRIMARY_PUBLIC,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc=OBSERVED,
        title="Local announcement",
        excerpt=excerpt,
        topic="transport",
        locality="Valcea",
        synthetic=False,
    ))
    evidence_url = source_url if exact_primary else "https://example.gov.ro/detail/38"
    packet = build_research_packet(signal, [
        ResearchEvidence(
            evidence_id="ev38",
            source_url=evidence_url,
            authority=EvidenceAuthority.PRIMARY_SOURCE,
            kind=EvidenceKind.DETAIL_PAGE,
            captured_at_utc=CAPTURED,
            content_sha256=h("evidence-38"),
        )
    ])
    scorecard = score_research_packet(packet)
    return build_master_draft_brief(packet, scorecard)


def by_platform(bundle):
    return {item.platform: item for item in bundle.adaptations}


def test_short_bound_brief_produces_all_three_active_native_lanes():
    brief = make_brief()
    bundle = build_native_adaptation_bundle(brief)
    assert bundle.status == NativeBundleStatus.READY_ALL_ACTIVE_LANES.value
    assert bundle.rights_input_ready is True
    assert bundle.active_platforms == (
        "FACEBOOK_PAGE",
        "INSTAGRAM_PROFESSIONAL",
        "THREADS",
    )
    assert tuple(item.platform for item in bundle.adaptations) == bundle.active_platforms
    assert all(item.status == NativeAdaptationStatus.READY.value for item in bundle.adaptations)


def test_support_text_is_preserved_verbatim_in_every_ready_lane():
    brief = make_brief(excerpt="Exact source context with 42 units.")
    bundle = build_native_adaptation_bundle(brief)
    title = brief.support_items[0].text
    excerpt = brief.support_items[1].text
    for item in bundle.adaptations:
        assert title in item.text
        assert excerpt in item.text
        assert brief.source_url in item.text
        assert item.evidence_ids == ("ev38",)
        assert item.support_kinds == ("SOURCE_TITLE", "SOURCE_EXCERPT")


def test_lane_rendering_is_native_but_adds_only_attribution_scaffolding():
    bundle = build_native_adaptation_bundle(make_brief())
    lanes = by_platform(bundle)
    assert "Din sursa primară:" in lanes["FACEBOOK_PAGE"].text
    assert "Sursă primară:" in lanes["INSTAGRAM_PROFESSIONAL"].text
    assert " — " in lanes["THREADS"].text
    assert "Sursa:" in lanes["THREADS"].text
    for item in bundle.adaptations:
        assert "#" not in item.text
        assert "click" not in item.text.lower()
        assert "urmărește" not in item.text.lower()


def test_upstream_hold_remains_hold_for_all_lanes():
    brief = make_brief(exact_primary=False)
    assert brief.native_adaptation_input_ready is False
    bundle = build_native_adaptation_bundle(brief)
    assert bundle.status == NativeBundleStatus.HOLD_INPUT_NOT_READY.value
    assert bundle.rights_input_ready is False
    for item in bundle.adaptations:
        assert item.status == NativeAdaptationStatus.HOLD_INPUT_NOT_READY.value
        assert item.text == ""
        assert item.char_count == 0
        assert item.adaptation_ready is False


def test_threads_length_budget_fails_closed_without_truncation():
    excerpt = "A" * 600
    brief = make_brief(excerpt=excerpt)
    bundle = build_native_adaptation_bundle(brief)
    lanes = by_platform(bundle)
    assert lanes["FACEBOOK_PAGE"].adaptation_ready is True
    assert lanes["INSTAGRAM_PROFESSIONAL"].adaptation_ready is True
    assert lanes["THREADS"].status == NativeAdaptationStatus.HOLD_LENGTH_BUDGET.value
    assert lanes["THREADS"].text == ""
    assert lanes["THREADS"].char_count == 0
    assert bundle.status == NativeBundleStatus.HOLD_ONE_OR_MORE_LANES.value
    assert bundle.rights_input_ready is False


def test_house_length_budgets_are_not_claimed_as_platform_api_limits():
    bundle = build_native_adaptation_bundle(make_brief())
    for item in bundle.adaptations:
        assert item.house_max_chars == HOUSE_MAX_CHARS[item.platform]
        assert "HOUSE_LENGTH_BUDGET_NOT_PLATFORM_API_LIMIT" in item.constraints


def test_instagram_caption_requires_visual_downstream_while_m05_has_no_visual_authority():
    bundle = build_native_adaptation_bundle(make_brief())
    lanes = by_platform(bundle)
    assert lanes["INSTAGRAM_PROFESSIONAL"].content_surface == "MEDIA_CAPTION"
    assert lanes["INSTAGRAM_PROFESSIONAL"].visual_requirement == "REQUIRED_DOWNSTREAM_M06"
    assert bundle.visual_authority is False


def test_no_lane_has_queue_publish_network_or_account_write_authority():
    bundle = build_native_adaptation_bundle(make_brief())
    assert bundle.state == "NATIVE_ADAPTATION_ONLY"
    assert bundle.native_adaptation_authority is True
    assert bundle.fact_authority is False
    assert bundle.queue_authority is False
    assert bundle.publish_authority is False
    assert bundle.network_fetch_performed is False
    assert bundle.real_account_connection_performed is False
    for item in bundle.adaptations:
        assert item.api_write_allowed is False
        assert item.queue_authority is False
        assert item.publish_authority is False
        assert item.network_fetch_performed is False
        assert item.real_account_connection_performed is False


def test_unknowns_are_preserved_exactly():
    brief = make_brief()
    bundle = build_native_adaptation_bundle(brief)
    assert bundle.unknowns == brief.unknowns
    assert all(item.unknowns == brief.unknowns for item in bundle.adaptations)


def test_master_brief_tampering_is_rejected():
    brief = make_brief()
    with pytest.raises(ValueError):
        build_native_adaptation_bundle(replace(brief, working_headline="Forged headline"))


def test_deterministic_replay():
    a = build_native_adaptation_bundle(make_brief())
    b = build_native_adaptation_bundle(make_brief())
    assert a == b
    assert a.bundle_hash == b.bundle_hash
    assert [x.adaptation_hash for x in a.adaptations] == [x.adaptation_hash for x in b.adaptations]


def test_json_batch_deduplicates_and_prioritizes_rights_ready():
    ready = make_brief()
    hold = make_brief(exact_primary=False)
    payload = json.loads(native_adaptation_bundles_json([hold, ready, ready]))
    assert len(payload) == 2
    assert payload[0]["rights_input_ready"] is True
    assert payload[1]["rights_input_ready"] is False


def test_policy_matches_active_lane_canon_and_excludes_deferred_platforms():
    policy = json.loads((ROOT / "config" / "native_adaptation_policy.json").read_text())
    assert policy["checkpoint"] == "CP38"
    assert policy["model_version"] == NATIVE_ADAPT_MODEL_VERSION
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["deferred_platforms"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["deferred_platforms"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["deferred_platforms"]["BLUESKY"] == "HOLD_ROI"
    assert not ({"LINKEDIN", "X", "BLUESKY"} & set(policy["active_platforms"]))


def test_policy_is_fail_closed():
    policy = json.loads((ROOT / "config" / "native_adaptation_policy.json").read_text())
    assert policy["adaptation_rules"]["truncation_allowed"] is False
    assert policy["adaptation_rules"]["paraphrase_allowed"] is False
    assert policy["adaptation_rules"]["rights_input_requires_all_active_lanes_ready"] is True
    authority = policy["authority"]
    assert authority["native_adaptation_authority"] is True
    assert authority["fact_authority"] is False
    assert authority["visual_authority"] is False
    assert authority["queue_authority"] is False
    assert authority["publish_authority"] is False
    assert authority["network_fetch_allowed"] is False
    assert authority["real_account_connection_allowed"] is False
    assert authority["api_write_allowed"] is False
