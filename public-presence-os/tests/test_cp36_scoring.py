from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
import public_presence_os.research as research_mod
from public_presence_os.scoring import *

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-09-06T02:00:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_packet(*, secondary=False, second_primary=False, cross_host=False, captured="2026-09-06T02:30:00Z"):
    source_url = "https://example.gov.ro/news/1" if not secondary else "https://local.example/news/1"
    source_class = RadarSourceClass.PRIMARY_PUBLIC if not secondary else RadarSourceClass.SECONDARY_DISCOVERY
    signal = materialize_signal(RadarObservation(
        external_ref="story-1",
        source_url=source_url,
        source_class=source_class,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc=OBSERVED,
        title="Local announcement",
        excerpt="Specific public detail.",
        topic="transport",
        locality="Valcea",
        synthetic=False,
    ))
    first_host = "https://example.gov.ro/detail/1" if not secondary else "https://authority.gov.ro/detail/1"
    evidence = [ResearchEvidence(
        evidence_id="ev1",
        source_url=first_host,
        authority=EvidenceAuthority.PRIMARY_SOURCE,
        kind=EvidenceKind.DETAIL_PAGE,
        captured_at_utc=captured,
        content_sha256=h("one"),
    )]
    if second_primary:
        second_url = "https://other.gov.ro/doc/2" if cross_host else first_host.replace("detail/1", "doc/2")
        evidence.append(ResearchEvidence(
            evidence_id="ev2",
            source_url=second_url,
            authority=EvidenceAuthority.PRIMARY_SOURCE,
            kind=EvidenceKind.DOCUMENT,
            captured_at_utc=captured,
            content_sha256=h("two"),
        ))
    return build_research_packet(signal, evidence)


def test_scores_only_evidence_bound_m02_packet():
    scorecard = score_research_packet(make_packet())
    assert 0 <= scorecard.evidence_readiness_score <= 100
    assert scorecard.score_type == "EVIDENCE_READINESS_ONLY"
    assert scorecard.state == "SCORING_ONLY"
    assert scorecard.scoring_authority is True
    assert scorecard.fact_authority is False
    assert scorecard.draft_authority is False
    assert scorecard.queue_authority is False
    assert scorecard.publish_authority is False
    assert scorecard.network_fetch_performed is False


def test_stronger_primary_provenance_scores_higher():
    baseline = score_research_packet(make_packet())
    stronger = score_research_packet(make_packet(second_primary=True, cross_host=True))
    assert stronger.evidence_readiness_score > baseline.evidence_readiness_score
    assert stronger.readiness_band == "EVIDENCE_READY_STRONG"


def test_secondary_discovery_uses_independent_primary_directness():
    scorecard = score_research_packet(make_packet(secondary=True))
    dimension = next(d for d in scorecard.dimensions if d.name == "source_directness")
    assert dimension.score == 12
    assert dimension.reasons == ("SECONDARY_DISCOVERY_CONFIRMED_BY_INDEPENDENT_PRIMARY_HOST",)


def test_no_fake_editorial_or_virality_scores():
    scorecard = score_research_packet(make_packet())
    assert scorecard.editorial_impact_score is None
    assert scorecard.virality_score is None
    assert scorecard.audience_fit_score is None


@pytest.mark.parametrize("field,value", [
    ("scoring_input_ready", False),
    ("evidence_bound", False),
    ("research_status", "HOLD_PRIMARY_EVIDENCE"),
    ("synthetic", True),
    ("fact_authority", True),
    ("scoring_authority", True),
    ("draft_authority", True),
    ("publish_authority", True),
    ("network_fetch_performed", True),
])
def test_rejects_noneligible_or_authority_tampering(field, value):
    with pytest.raises(ValueError):
        score_research_packet(replace(make_packet(), **{field: value}))


def test_rejects_research_hash_tampering():
    with pytest.raises(ValueError):
        score_research_packet(replace(make_packet(), research_packet_hash=h("tampered")))


def test_rejects_packet_id_tampering():
    with pytest.raises(ValueError):
        score_research_packet(replace(make_packet(), packet_id=h("tampered")))


def test_deterministic_replay():
    first = score_research_packet(make_packet(second_primary=True, cross_host=True))
    second = score_research_packet(make_packet(second_primary=True, cross_host=True))
    assert first == second
    assert first.scorecard_hash == second.scorecard_hash


def test_batch_deduplicates_and_orders_by_evidence_readiness():
    weak = make_packet()
    strong = make_packet(second_primary=True, cross_host=True)
    output = score_packets([weak, strong, strong])
    assert len(output) == 2
    assert output[0].evidence_readiness_score >= output[1].evidence_readiness_score


@pytest.mark.parametrize("captured,expected", [
    ("2026-09-06T02:30:00Z", 20),
    ("2026-09-06T12:00:00Z", 15),
    ("2026-09-08T02:00:00Z", 10),
    ("2026-09-10T02:00:00Z", 5),
    ("2026-09-20T02:00:00Z", 0),
])
def test_timeliness_buckets(captured, expected):
    scorecard = score_research_packet(make_packet(captured=captured))
    dimension = next(d for d in scorecard.dimensions if d.name == "research_timeliness")
    assert dimension.score == expected


def test_scorecard_hash_changes_with_evidence():
    baseline = score_research_packet(make_packet())
    changed = score_research_packet(make_packet(second_primary=True))
    assert baseline.scorecard_hash != changed.scorecard_hash


def test_json_replay_is_stable():
    first = scorecards_json(score_packets([make_packet(), make_packet(second_primary=True, cross_host=True)]))
    second = scorecards_json(score_packets([make_packet(), make_packet(second_primary=True, cross_host=True)]))
    assert first == second


def test_policy_mirrors_code_and_has_no_execution_authority():
    policy = json.loads((ROOT / "config" / "scoring_policy.json").read_text())
    assert policy["checkpoint"] == "CP36"
    assert policy["model_version"] == SCORE_MODEL_VERSION
    assert policy["score_type"] == SCORE_TYPE
    assert sum(d["maximum"] for d in policy["dimensions"]) == MAX_SCORE
    assert "virality" in policy["explicitly_unscored"]
    assert "predicted_engagement" in policy["explicitly_unscored"]
    authority = policy["authority"]
    assert authority["internal_scoring_only"] is True
    assert authority["fact_authority"] is False
    assert authority["draft_authority"] is False
    assert authority["queue_authority"] is False
    assert authority["publish_authority"] is False
    assert authority["network_fetch_allowed"] is False


def _rehash_forged(packet):
    body = {
        "schema_version": "PPOS_RESEARCH_PACKET_V1",
        "signal_id": packet.signal_id,
        "radar_observation_hash": packet.radar_observation_hash,
        "source_url": packet.source_url,
        "source_class": packet.source_class,
        "kind": packet.kind,
        "observed_at_utc": packet.observed_at_utc,
        "title": packet.title,
        "excerpt": packet.excerpt,
        "topic": packet.topic,
        "locality": packet.locality,
        "evidence_refs": [asdict(e) for e in packet.evidence_refs],
        "evidence_requirements": packet.evidence_requirements,
        "unresolved_questions": packet.unresolved_questions,
        "research_status": packet.research_status,
        "evidence_bound": packet.evidence_bound,
        "scoring_input_ready": packet.scoring_input_ready,
        "synthetic": packet.synthetic,
        "state": packet.state,
        "fact_authority": packet.fact_authority,
        "scoring_authority": packet.scoring_authority,
        "draft_authority": packet.draft_authority,
        "publish_authority": packet.publish_authority,
        "network_fetch_performed": packet.network_fetch_performed,
    }
    return replace(packet, research_packet_hash=research_mod._hash(body))


@pytest.mark.parametrize("mutation", [
    lambda p: replace(p, source_class="MANUAL_SYNTHETIC"),
    lambda p: replace(p, kind="BAD_KIND"),
    lambda p: replace(p, evidence_refs=(replace(p.evidence_refs[0], synthetic=True),)),
    lambda p: replace(p, evidence_refs=(replace(p.evidence_refs[0], authority="UNKNOWN"),)),
    lambda p: replace(p, evidence_refs=(replace(p.evidence_refs[0], kind="UNKNOWN"),)),
    lambda p: replace(p, evidence_refs=(replace(p.evidence_refs[0], content_sha256="bad"),)),
    lambda p: replace(p, evidence_refs=(replace(p.evidence_refs[0], source_url="http://example.gov.ro/x"),)),
    lambda p: replace(p, evidence_refs=(replace(p.evidence_refs[0], captured_at_utc="2026-09-05T23:00:00Z"),)),
])
def test_rejects_semantically_forged_packet_even_if_self_hash_recomputed(mutation):
    forged = _rehash_forged(mutation(make_packet()))
    with pytest.raises(ValueError):
        score_research_packet(forged)
