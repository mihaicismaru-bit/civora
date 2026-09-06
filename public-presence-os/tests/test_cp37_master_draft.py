from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
from public_presence_os.scoring import score_research_packet
from public_presence_os.master_draft import *

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-09-06T03:30:00Z"
CAPTURED = "2026-09-06T03:40:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_bound_pair(*, secondary=False, exact_primary=True, excerpt="Specific public detail."):
    source_url = "https://example.gov.ro/news/1" if not secondary else "https://local.example/news/1"
    source_class = RadarSourceClass.PRIMARY_PUBLIC if not secondary else RadarSourceClass.SECONDARY_DISCOVERY
    signal = materialize_signal(RadarObservation(
        external_ref="story-37",
        source_url=source_url,
        source_class=source_class,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc=OBSERVED,
        title="Local announcement",
        excerpt=excerpt,
        topic="transport",
        locality="Valcea",
        synthetic=False,
    ))
    if secondary:
        evidence_url = "https://authority.gov.ro/detail/1"
    elif exact_primary:
        evidence_url = source_url
    else:
        evidence_url = "https://example.gov.ro/detail/1"
    packet = build_research_packet(signal, [
        ResearchEvidence(
            evidence_id="ev1",
            source_url=evidence_url,
            authority=EvidenceAuthority.PRIMARY_SOURCE,
            kind=EvidenceKind.DETAIL_PAGE,
            captured_at_utc=CAPTURED,
            content_sha256=h("evidence"),
        )
    ])
    return packet, score_research_packet(packet)


def test_direct_primary_exact_url_becomes_adaptation_ready():
    packet, scorecard = make_bound_pair()
    brief = build_master_draft_brief(packet, scorecard)
    assert brief.draft_status == DraftBriefStatus.DIRECT_PRIMARY_CONTEXT_BOUND.value
    assert brief.native_adaptation_input_ready is True
    assert brief.working_headline == packet.title
    assert [item.kind for item in brief.support_items] == ["SOURCE_TITLE", "SOURCE_EXCERPT"]
    assert all(item.attribution_required for item in brief.support_items)
    assert all(item.evidence_ids == ("ev1",) for item in brief.support_items)


def test_same_host_but_different_primary_url_holds():
    packet, scorecard = make_bound_pair(exact_primary=False)
    assert packet.research_status == "EVIDENCE_BOUND"
    brief = build_master_draft_brief(packet, scorecard)
    assert brief.draft_status == DraftBriefStatus.HOLD_DIRECT_PRIMARY_CONTEXT.value
    assert brief.native_adaptation_input_ready is False
    assert brief.support_items == ()
    assert brief.attribution_requirements == ()


def test_secondary_discovery_holds_even_when_research_is_evidence_bound():
    packet, scorecard = make_bound_pair(secondary=True)
    assert packet.research_status == "EVIDENCE_BOUND"
    brief = build_master_draft_brief(packet, scorecard)
    assert brief.draft_status == DraftBriefStatus.HOLD_DIRECT_PRIMARY_CONTEXT.value
    assert brief.native_adaptation_input_ready is False
    assert brief.support_items == ()


def test_empty_source_excerpt_holds():
    packet, scorecard = make_bound_pair(excerpt="")
    brief = build_master_draft_brief(packet, scorecard)
    assert brief.native_adaptation_input_ready is False
    assert brief.support_items == ()


def test_exact_scorecard_packet_binding_required():
    packet, scorecard = make_bound_pair()
    with pytest.raises(ValueError):
        build_master_draft_brief(packet, replace(scorecard, scorecard_hash=h("tampered")))


def test_research_packet_tampering_is_rejected_via_m03_revalidation():
    packet, scorecard = make_bound_pair()
    with pytest.raises(ValueError):
        build_master_draft_brief(replace(packet, title="Forged title"), scorecard)


def test_no_fact_queue_or_publish_authority():
    packet, scorecard = make_bound_pair()
    brief = build_master_draft_brief(packet, scorecard)
    assert brief.state == "MASTER_DRAFT_BRIEF_ONLY"
    assert brief.internal_draft_brief_authority is True
    assert brief.fact_authority is False
    assert brief.queue_authority is False
    assert brief.publish_authority is False
    assert brief.network_fetch_performed is False
    assert brief.synthetic is False


def test_unknowns_and_constraints_preserved():
    packet, scorecard = make_bound_pair()
    brief = build_master_draft_brief(packet, scorecard)
    for q in packet.unresolved_questions:
        assert q in brief.unknowns
    assert "NO_SEMANTIC_CLAIM_EXTRACTION_BEYOND_DIRECT_BOUND_SOURCE_CONTEXT" in brief.unknowns
    assert "DO_NOT_PROMOTE_SOURCE_CONTEXT_TO_UNATTRIBUTED_FACT" in brief.drafting_constraints
    assert "DO_NOT_INFER_MISSING_NAMES_DATES_NUMBERS_CAUSES_OR_OUTCOMES" in brief.drafting_constraints


def test_deterministic_replay():
    a = build_master_draft_brief(*make_bound_pair())
    b = build_master_draft_brief(*make_bound_pair())
    assert a == b
    assert a.brief_hash == b.brief_hash


def test_json_batch_deduplicates_and_prioritizes_ready():
    ready = make_bound_pair()
    hold = make_bound_pair(exact_primary=False)
    payload = json.loads(master_draft_briefs_json([hold, ready, ready]))
    assert len(payload) == 2
    assert payload[0]["native_adaptation_input_ready"] is True
    assert payload[1]["native_adaptation_input_ready"] is False


def test_policy_is_fail_closed_and_matches_model():
    policy = json.loads((ROOT / "config" / "master_draft_policy.json").read_text())
    assert policy["checkpoint"] == "CP37"
    assert policy["model_version"] == MASTER_DRAFT_MODEL_VERSION
    assert policy["direct_context_rule"]["source_class"] == "PRIMARY_PUBLIC"
    assert policy["direct_context_rule"]["exact_primary_url_match_required"] is True
    assert policy["secondary_discovery"]["native_adaptation_input_ready"] is False
    authority = policy["authority"]
    assert authority["internal_draft_brief_authority"] is True
    assert authority["fact_authority"] is False
    assert authority["queue_authority"] is False
    assert authority["publish_authority"] is False
    assert authority["network_fetch_allowed"] is False


def test_support_items_are_verbatim_not_generated_claims():
    packet, scorecard = make_bound_pair()
    brief = build_master_draft_brief(packet, scorecard)
    assert brief.support_items[0].text == packet.title
    assert brief.support_items[1].text == packet.excerpt
