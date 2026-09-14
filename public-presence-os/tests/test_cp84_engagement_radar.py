import copy
import json
from pathlib import Path

import pytest

from public_presence_os.engagement_radar import (
    ACTIVE_PLATFORMS,
    DISCOVERY_CAPABILITIES,
    EngagementObservation,
    EngagementRadarHold,
    EngagementScoreEvidence,
    compile_engagement_radar,
    score_batch,
    score_candidate,
    validate_policy,
)
from public_presence_os.growth_capability_matrix import compile_growth_capability_matrix

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "engagement_radar_policy.json"
CP83_POLICY_PATH = ROOT / "config" / "growth_capability_matrix_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def load_cp83():
    return compile_growth_capability_matrix(
        json.loads(CP83_POLICY_PATH.read_text(encoding="utf-8"))
    )


def contract():
    return compile_engagement_radar(load_policy(), load_cp83())


def evidence(**overrides):
    base = dict(
        relevance=90,
        expertise_fit=80,
        conversation_momentum=70,
        novelty=65,
        answerability=90,
        reputational_risk=10,
        spam_risk=5,
        expected_relationship_value=80,
    )
    base.update(overrides)
    return EngagementScoreEvidence(**base)


def observation(**overrides):
    base = dict(
        platform="INSTAGRAM_PROFESSIONAL",
        discovery_capability="MENTION_DISCOVERY",
        provenance_kind="SYNTHETIC_FIXTURE",
        provenance_ref="fixture:ig:mention:001",
        conversation_ref="ig-conversation-001",
        source_url="synthetic://instagram/mention/001",
        author_public_id="@public_account",
        topic="local public-interest update",
        context="A substantive public conversation with enough context for a useful response assessment.",
        observed_at_utc="2026-09-14T11:00:00Z",
        published_at_utc="2026-09-14T10:00:00Z",
        score_evidence=evidence(),
    )
    base.update(overrides)
    return EngagementObservation(**base)


def test_cp84_exact_route_matrix_parent_binding_and_control_hold():
    c = contract()
    assert c.checkpoint == "CP84"
    assert c.parent_activation_checkpoint == "CP83"
    assert c.parent_control_checkpoint == "CP58"
    assert c.next_unit == "CP85_INBOUND_REPLY_ENGINE"
    assert {(r.platform, r.capability) for r in c.routes} == {
        (p, capability) for p in ACTIVE_PLATFORMS for capability in DISCOVERY_CAPABILITIES
    }
    assert len(c.routes) == 6
    assert c.global_kill_switch_engaged is True
    assert c.posting_authority is False
    assert c.external_write_allowed is False
    assert c.external_write_performed is False
    assert c.network_allowed is False
    assert c.network_attempted is False
    assert c.live_probe_allowed is False
    assert c.oauth_attempted is False
    assert c.account_connected is False
    assert c.control_plane_promoted is False
    assert c.deploy_allowed is False
    assert c.external_metrics == "UNKNOWN"


def test_cp84_routes_match_cp83_capability_classifications_exactly():
    c = contract()
    classifications = {(r.platform, r.capability): r.expected_cp83_classification for r in c.routes}
    assert classifications[("FACEBOOK_PAGE", "MENTION_DISCOVERY")] == "MANUAL_ONLY"
    assert classifications[("FACEBOOK_PAGE", "HASHTAG_TOPIC_DISCOVERY")] == "MANUAL_ONLY"
    assert classifications[("INSTAGRAM_PROFESSIONAL", "MENTION_DISCOVERY")] == "PASS_OFFLINE_CONTRACT"
    assert classifications[("INSTAGRAM_PROFESSIONAL", "HASHTAG_TOPIC_DISCOVERY")] == "PASS_OFFLINE_CONTRACT"
    assert classifications[("THREADS", "MENTION_DISCOVERY")] == "PASS_OFFLINE_CONTRACT"
    assert classifications[("THREADS", "HASHTAG_TOPIC_DISCOVERY")] == "HOLD_LIVE_PERMISSION"


def test_cp84_normalizes_scores_and_provenance_without_write_authority():
    candidate = score_candidate(contract(), observation(), now_utc="2026-09-14T12:00:00Z")
    assert candidate.platform == "INSTAGRAM_PROFESSIONAL"
    assert candidate.freshness_hours == 2.0
    assert candidate.final_score > 55
    assert candidate.decision == "ELIGIBLE_HUMAN_REVIEW"
    assert candidate.automation_discovery_eligible is True
    assert candidate.posting_authority is False
    assert candidate.external_write_allowed is False
    assert candidate.external_write_attempted is False
    assert candidate.network_fetch_performed is False
    assert candidate.external_metrics == "UNKNOWN"
    assert len(candidate.candidate_id) == 64
    assert len(candidate.provenance_hash) == 64
    assert len(candidate.observation_hash) == 64


def test_cp84_manual_facebook_discovery_is_scored_but_never_claimed_automatable():
    candidate = score_candidate(
        contract(),
        observation(
            platform="FACEBOOK_PAGE",
            discovery_capability="MENTION_DISCOVERY",
            provenance_ref="fixture:fb:manual:001",
            conversation_ref="fb-public-conversation-001",
            source_url="synthetic://facebook/manual/001",
        ),
        now_utc="2026-09-14T12:00:00Z",
    )
    assert candidate.cp83_classification == "MANUAL_ONLY"
    assert candidate.automation_discovery_eligible is False
    assert "HOLD_CAPABILITY_UNVERIFIED" in candidate.blockers
    assert "AUTOMATION_DISCOVERY_NOT_AUTHORIZED" in candidate.decision_reasons
    assert candidate.posting_authority is False


def test_cp84_threads_topic_discovery_remains_capability_hold():
    candidate = score_candidate(
        contract(),
        observation(
            platform="THREADS",
            discovery_capability="HASHTAG_TOPIC_DISCOVERY",
            provenance_ref="fixture:threads:topic:001",
            conversation_ref="threads-topic-001",
            source_url="synthetic://threads/topic/001",
        ),
        now_utc="2026-09-14T12:00:00Z",
    )
    assert candidate.cp83_classification == "HOLD_LIVE_PERMISSION"
    assert candidate.automation_discovery_eligible is False
    assert "HOLD_CAPABILITY_UNVERIFIED" in candidate.blockers
    assert "CAPABILITY_NOT_PASS_OFFLINE_CONTRACT" in candidate.decision_reasons


@pytest.mark.parametrize(
    "score_overrides,expected",
    [
        ({"spam_risk": 70}, "REJECT_SPAM_RISK"),
        ({"reputational_risk": 80}, "REJECT_REPUTATIONAL_RISK"),
        ({"relevance": 34}, "REJECT_LOW_RELEVANCE"),
        ({"answerability": 29}, "REJECT_UNANSWERABLE"),
    ],
)
def test_cp84_hard_quality_and_risk_rejections(score_overrides, expected):
    candidate = score_candidate(
        contract(),
        observation(score_evidence=evidence(**score_overrides)),
        now_utc="2026-09-14T12:00:00Z",
    )
    assert candidate.decision == expected


def test_cp84_stale_candidate_holds_even_with_strong_scores():
    candidate = score_candidate(
        contract(),
        observation(
            observed_at_utc="2026-09-14T11:00:00Z",
            published_at_utc="2026-09-01T10:00:00Z",
        ),
        now_utc="2026-09-14T12:00:00Z",
    )
    assert candidate.decision == "HOLD_STALE"


@pytest.mark.parametrize(
    "flag",
    [
        "sensitive_trait_inference_used",
        "sensitive_relationship_profiling_used",
        "political_microtargeting_used",
        "synthetic_conversation_farming_used",
    ],
)
def test_cp84_prohibited_growth_safety_signals_reject(flag):
    candidate = score_candidate(
        contract(),
        observation(**{flag: True}),
        now_utc="2026-09-14T12:00:00Z",
    )
    assert candidate.decision == "REJECT_SAFETY"
    assert candidate.posting_authority is False


def test_cp84_unknown_platform_or_capability_fails_closed():
    c = contract()
    with pytest.raises(EngagementRadarHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        score_candidate(c, observation(platform="LINKEDIN"), now_utc="2026-09-14T12:00:00Z")
    with pytest.raises(EngagementRadarHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        score_candidate(c, observation(discovery_capability="OUTBOUND_COMMENT"), now_utc="2026-09-14T12:00:00Z")


def test_cp84_route_provenance_gate_prevents_false_api_support():
    c = contract()
    with pytest.raises(EngagementRadarHold, match="HOLD_CP84_PROVENANCE_NOT_ALLOWED_FOR_ROUTE"):
        score_candidate(
            c,
            observation(
                platform="FACEBOOK_PAGE",
                discovery_capability="MENTION_DISCOVERY",
                provenance_kind="OFFLINE_API_FIXTURE",
                provenance_ref="fixture:fb:api:forbidden",
                source_url="https://example.org/fb/forbidden",
            ),
            now_utc="2026-09-14T12:00:00Z",
        )


def test_cp84_public_observation_requires_https_and_synthetic_requires_synthetic_url():
    c = contract()
    with pytest.raises(EngagementRadarHold, match="HOLD_CP84_PUBLIC_SOURCE_HTTPS_REQUIRED"):
        score_candidate(
            c,
            observation(
                provenance_kind="PUBLIC_URL_OBSERVATION",
                source_url="http://example.org/not-https",
            ),
            now_utc="2026-09-14T12:00:00Z",
        )
    with pytest.raises(EngagementRadarHold, match="HOLD_CP84_SYNTHETIC_FIXTURE_URL_REQUIRED"):
        score_candidate(
            c,
            observation(
                provenance_kind="SYNTHETIC_FIXTURE",
                source_url="https://example.org/not-synthetic",
            ),
            now_utc="2026-09-14T12:00:00Z",
        )


def test_cp84_conflicting_duplicate_candidate_fails_closed_and_identical_dedupes():
    c = contract()
    a = observation()
    assert len(score_batch(c, [a, a], now_utc="2026-09-14T12:00:00Z")) == 1
    b = observation(context="Conflicting observation for the same public conversation identity.")
    with pytest.raises(EngagementRadarHold, match="HOLD_CP84_CONFLICTING_DUPLICATE"):
        score_batch(c, [a, b], now_utc="2026-09-14T12:00:00Z")


def test_cp84_batch_orders_high_value_then_fresher_and_never_creates_authority():
    c = contract()
    high = observation(
        conversation_ref="high",
        source_url="synthetic://instagram/high",
        score_evidence=evidence(relevance=100, expertise_fit=95),
    )
    lower = observation(
        conversation_ref="lower",
        source_url="synthetic://instagram/lower",
        score_evidence=evidence(relevance=60, expertise_fit=50),
    )
    ranked = score_batch(c, [lower, high], now_utc="2026-09-14T12:00:00Z")
    assert ranked[0].conversation_ref == "high"
    assert all(x.posting_authority is False and x.external_write_allowed is False for x in ranked)


@pytest.mark.parametrize(
    "mutator,reason",
    [
        (lambda p: p.__setitem__("global_kill_switch", "DISENGAGED"), "HOLD_CP84_KILL_SWITCH_NOT_ENGAGED"),
        (lambda p: p["authority"].__setitem__("network_allowed", True), "HOLD_CP84_LIVE_AUTHORITY_DRIFT"),
        (lambda p: p["growth_safety"].__setitem__("mass_commenting_forbidden", False), "HOLD_CP84_GROWTH_SAFETY_WEAKENED"),
        (lambda p: p["benefit_weights"].__setitem__("relevance", 24), "HOLD_CP84_BENEFIT_WEIGHT_SUM"),
        (lambda p: p["score_dimensions"].append("follower_count"), "HOLD_CP84_SCORE_DIMENSION_DRIFT"),
        (lambda p: p["discovery_routes"][0].__setitem__("automation_discovery_eligible", True), "HOLD_CP84_UNVERIFIED_ROUTE_CANNOT_AUTOMATE"),
    ],
)
def test_cp84_policy_weakening_fails_closed(mutator, reason):
    p = copy.deepcopy(load_policy())
    mutator(p)
    with pytest.raises(EngagementRadarHold, match=reason):
        validate_policy(p)
