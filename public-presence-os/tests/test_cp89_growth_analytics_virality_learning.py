import copy
import json
from pathlib import Path

import pytest

from public_presence_os.growth_analytics import (
    CORE_METRICS,
    GrowthAnalyticsHold,
    GrowthAnalyticsState,
    GrowthObservation,
    compile_growth_analytics,
    compile_growth_report,
    evaluate_observation,
    validate_policy,
    validate_report,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "growth_analytics_virality_learning_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def contract():
    return compile_growth_analytics(load_policy())


def observation(**overrides):
    base = dict(
        platform="THREADS",
        observation_ref="obs-cp89-001",
        topic="finantare europeana pentru IMM",
        observed_at_utc="2026-09-18T08:00:00Z",
        provenance_ref="fixture:cp89:001",
        evidence_class="SYNTHETIC_OFFLINE",
        source_is_public=True,
        aggregate_content_level_only=True,
        reach=1000,
        impressions=1400,
        engaged_users=120,
        comments=20,
        meaningful_comments=12,
        replies=10,
        response_opportunities=16,
        first_reply_latencies_seconds=(60, 120, 300),
        conversation_depth_samples=(2, 4, 6),
        repeat_engagers=30,
        profile_visits=50,
        follows=8,
        outbound_comments=4,
        outbound_comments_with_response=2,
        eligible_dormant_relationships=10,
        reactivated_relationships=3,
        amplification_candidates=5,
        successful_amplifications=2,
        topic_selection_score=80,
        packaging_score=70,
        early_engagement_score=90,
        network_propagation_score=60,
    )
    base.update(overrides)
    return GrowthObservation(**base)


def test_cp89_contract_keeps_cp58_and_zero_live_authority():
    c = contract()
    assert c.checkpoint == "CP89"
    assert c.module_id == "M58_GROWTH_ANALYTICS_VIRALITY_LEARNING"
    assert c.parent_activation_checkpoint == "CP88"
    assert c.parent_control_checkpoint == "CP58"
    assert c.next_unit == "CP90_ENGAGEMENT_SCHEDULER_RATE_QUALITY_BUDGET"
    assert c.global_kill_switch_engaged is True
    assert c.unknown_external_metric_value == "UNKNOWN"
    assert c.external_metric_fetch_allowed is False
    assert c.external_write_allowed is False
    assert c.network_allowed is False
    assert c.live_probe_allowed is False
    assert c.oauth_allowed is False
    assert c.account_connection_allowed is False
    assert c.posting_authority is False
    assert c.strategy_mutation_authority is False
    assert c.control_plane_promoted is False
    assert c.deploy_allowed is False
    assert c.paid_service_allowed is False
    assert c.core_metrics == CORE_METRICS


def test_cp89_computes_canonical_growth_metrics_from_explicit_evidence_only():
    result = evaluate_observation(contract(), GrowthAnalyticsState(), observation())
    metrics = result.metrics
    assert metrics["engagement_per_reached_user"].value == 0.12
    assert metrics["meaningful_comment_rate"].value == 0.6
    assert metrics["reply_rate"].value == 0.625
    assert metrics["median_first_reply_latency"].value == 120.0
    assert metrics["conversation_depth"].value == 4.0
    assert metrics["repeat_engager_rate"].value == 0.25
    assert metrics["profile_visit_rate"].value == 0.05
    assert metrics["follower_conversion_rate"].value == 0.16
    assert metrics["outbound_comment_response_rate"].value == 0.5
    assert metrics["relationship_reactivation_rate"].value == 0.3
    assert metrics["amplification_yield"].value == 0.4
    assert all(value.state == "KNOWN" for value in metrics.values())
    assert result.external_metric_state == "UNKNOWN_WHERE_UNAVAILABLE"
    assert result.external_write_allowed is False
    assert result.network_attempted is False
    assert result.posting_authority is False


def test_cp89_missing_metrics_remain_unknown_and_are_never_coerced_to_zero():
    sparse = observation(
        reach=None,
        impressions=None,
        engaged_users=None,
        comments=None,
        meaningful_comments=None,
        replies=None,
        response_opportunities=None,
        first_reply_latencies_seconds=(),
        conversation_depth_samples=(),
        repeat_engagers=None,
        profile_visits=None,
        follows=None,
        outbound_comments=None,
        outbound_comments_with_response=None,
        eligible_dormant_relationships=None,
        reactivated_relationships=None,
        amplification_candidates=None,
        successful_amplifications=None,
        topic_selection_score=None,
        packaging_score=None,
        early_engagement_score=None,
        network_propagation_score=None,
    )
    result = evaluate_observation(contract(), GrowthAnalyticsState(), sparse)
    assert all(metric.state == "UNKNOWN" and metric.value is None for metric in result.metrics.values())
    assert result.virality_learning.state == "INSUFFICIENT_EVIDENCE"
    assert result.virality_learning.observed_signal_score.state == "UNKNOWN"
    assert result.virality_learning.observed_signal_score.value is None
    assert result.virality_learning.recommendations == (
        "INSUFFICIENT_COMPONENT_EVIDENCE_NO_STRATEGY_CHANGE",
    )


def test_cp89_zero_denominator_is_unknown_not_zero():
    zero = observation(
        reach=0,
        engaged_users=0,
        comments=0,
        meaningful_comments=0,
        replies=0,
        response_opportunities=0,
        repeat_engagers=0,
        profile_visits=0,
        follows=0,
        outbound_comments=0,
        outbound_comments_with_response=0,
        eligible_dormant_relationships=0,
        reactivated_relationships=0,
        amplification_candidates=0,
        successful_amplifications=0,
    )
    result = evaluate_observation(contract(), GrowthAnalyticsState(), zero)
    for name in (
        "engagement_per_reached_user",
        "meaningful_comment_rate",
        "reply_rate",
        "repeat_engager_rate",
        "profile_visit_rate",
        "follower_conversion_rate",
        "outbound_comment_response_rate",
        "relationship_reactivation_rate",
        "amplification_yield",
    ):
        assert result.metrics[name].state == "UNKNOWN"
        assert result.metrics[name].value is None
        assert result.metrics[name].reason == "ZERO_DENOMINATOR"


def test_cp89_virality_is_observational_noncausal_and_never_mutates_strategy():
    packet = evaluate_observation(contract(), GrowthAnalyticsState(), observation()).virality_learning
    assert packet.state == "OBSERVED_SIGNAL_AVAILABLE_NON_CAUSAL"
    assert packet.observed_signal_score.value == 75.0
    assert packet.attribution_mode == "OBSERVATIONAL_NON_CAUSAL"
    assert packet.causal_claim_allowed is False
    assert packet.automatic_strategy_mutation_allowed is False
    assert packet.external_write_allowed is False
    assert packet.network_attempted is False
    assert packet.posting_authority is False
    assert "HUMAN_REVIEW_EVIDENCE_BOUND_FOLLOW_UP_PATTERN" in packet.recommendations


def test_cp89_learning_can_flag_packaging_clarity_without_clickbait():
    packet = evaluate_observation(
        contract(),
        GrowthAnalyticsState(),
        observation(packaging_score=40, topic_selection_score=85, early_engagement_score=80, network_propagation_score=55),
    ).virality_learning
    assert "HUMAN_REVIEW_PACKAGING_CLARITY_WITHOUT_CLICKBAIT" in packet.recommendations
    assert packet.automatic_strategy_mutation_allowed is False


def test_cp89_report_builds_primary_funnel_and_descriptive_topic_attribution():
    c = contract()
    state = GrowthAnalyticsState()
    second = observation(
        observation_ref="obs-cp89-002",
        provenance_ref="fixture:cp89:002",
        platform="FACEBOOK_PAGE",
        topic="finantare europeana pentru IMM",
        observed_at_utc="2026-09-18T08:10:00Z",
        reach=500,
        impressions=700,
        engaged_users=50,
        comments=10,
        meaningful_comments=5,
        replies=4,
        response_opportunities=8,
        first_reply_latencies_seconds=(90, 150),
        conversation_depth_samples=(2, 3),
        repeat_engagers=10,
        profile_visits=None,
        follows=None,
        outbound_comments=2,
        outbound_comments_with_response=1,
        eligible_dormant_relationships=5,
        reactivated_relationships=1,
        amplification_candidates=4,
        successful_amplifications=1,
        topic_selection_score=None,
        packaging_score=None,
        early_engagement_score=None,
        network_propagation_score=None,
    )
    report = compile_growth_report(c, state, (observation(), second), report_ref="fixture-report-cp89")
    assert report.observation_count == 2
    assert report.funnel["publication"].value == 2
    assert report.funnel["reach"].value == 1500
    assert report.funnel["reach"].state == "KNOWN"
    assert report.funnel["profile_visits"].state == "PARTIAL"
    assert report.funnel["profile_visits"].value == 50
    assert report.core_metrics["engagement_per_reached_user"].value == round(170 / 1500, 6)
    assert report.core_metrics["profile_visit_rate"].state == "PARTIAL"
    assert report.core_metrics["profile_visit_rate"].known_observations == 1
    assert len(report.topic_to_growth_attribution) == 1
    topic = report.topic_to_growth_attribution[0]
    assert topic.topic == "finantare europeana pentru IMM"
    assert topic.observation_count == 2
    assert topic.attribution_mode == "DESCRIPTIVE_NON_CAUSAL"
    assert topic.causal_claim_allowed is False
    assert report.causal_attribution_allowed is False
    assert report.automatic_strategy_mutation_allowed is False
    assert report.external_metric_fetch_allowed is False
    assert report.external_write_allowed is False
    assert report.network_attempted is False
    assert report.posting_authority is False
    validate_report(report)


def test_cp89_topic_attribution_does_not_claim_causality_even_with_complete_data():
    report = compile_growth_report(
        contract(), GrowthAnalyticsState(), (observation(),), report_ref="topic-noncausal"
    )
    assert report.topic_to_growth_attribution[0].causal_claim_allowed is False
    assert report.learning_mode == "OBSERVATIONAL_NON_CAUSAL_HUMAN_REVIEW_ONLY"


def test_cp89_exact_replay_is_idempotent_and_conflicting_provenance_fails_closed():
    c = contract()
    state = GrowthAnalyticsState()
    first = evaluate_observation(c, state, observation())
    before = state.to_dict()
    replay = evaluate_observation(c, state, observation())
    assert replay.observation_hash == first.observation_hash
    assert state.to_dict() == before
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_CONFLICTING_PROVENANCE_REUSE"):
        evaluate_observation(c, state, observation(reach=1001))


@pytest.mark.parametrize(
    "flag",
    [
        "person_level_identifiers_present",
        "sensitive_trait_data_present",
        "sensitive_trait_inference_requested",
        "sensitive_relationship_profiling_requested",
        "political_microtargeting_requested",
        "synthetic_conversation_farming_requested",
        "clickbait_optimization_requested",
        "conflict_fabrication_requested",
    ],
)
def test_cp89_forbidden_growth_or_sensitive_signals_fail_closed(flag):
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_FORBIDDEN_GROWTH_SIGNAL"):
        evaluate_observation(
            contract(), GrowthAnalyticsState(), observation(provenance_ref=f"fixture:forbidden:{flag}", **{flag: True})
        )


def test_cp89_unknown_platform_fails_closed_as_capability_unverified():
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        evaluate_observation(
            contract(),
            GrowthAnalyticsState(),
            observation(platform="LINKEDIN", provenance_ref="fixture:linkedin"),
        )


def test_cp89_invalid_count_relationship_fails_closed():
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_COUNT_RELATION_INVALID"):
        evaluate_observation(
            contract(), GrowthAnalyticsState(), observation(meaningful_comments=21, comments=20)
        )


def test_cp89_policy_weakening_fails_closed():
    p = copy.deepcopy(load_policy())
    p["unknown_external_metric_value"] = 0
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_POLICY_IDENTITY_DRIFT"):
        validate_policy(p)

    p = copy.deepcopy(load_policy())
    p["truthfulness"]["null_is_not_zero"] = False
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_TRUTHFULNESS_POLICY_WEAKENED"):
        validate_policy(p)

    p = copy.deepcopy(load_policy())
    p["privacy"]["sensitive_trait_inference_forbidden"] = False
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_PRIVACY_POLICY_WEAKENED"):
        validate_policy(p)

    p = copy.deepcopy(load_policy())
    p["authority"]["external_metric_fetch_allowed"] = True
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_LIVE_AUTHORITY_DRIFT"):
        validate_policy(p)

    p = copy.deepcopy(load_policy())
    p["virality_learning"]["clickbait_optimization_allowed"] = True
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_VIRALITY_SAFETY_WEAKENED"):
        validate_policy(p)


def test_cp89_batch_limit_is_hard_ceiling_and_batch_rolls_back_atomically():
    c = contract()
    too_many = tuple(
        observation(
            observation_ref=f"obs-batch-{i}",
            provenance_ref=f"fixture:batch:{i}",
        )
        for i in range(c.max_batch + 1)
    )
    with pytest.raises(GrowthAnalyticsHold, match="HOLD_CP89_BATCH_LIMIT_EXCEEDED"):
        compile_growth_report(c, GrowthAnalyticsState(), too_many, report_ref="too-many")

    state = GrowthAnalyticsState()
    bad_batch = (
        observation(observation_ref="obs-atomic-1", provenance_ref="fixture:atomic:1"),
        observation(
            observation_ref="obs-atomic-2",
            provenance_ref="fixture:atomic:2",
            sensitive_trait_inference_requested=True,
        ),
    )
    with pytest.raises(GrowthAnalyticsHold):
        compile_growth_report(c, state, bad_batch, report_ref="atomic-failure")
    assert state.to_dict() == {"provenance_receipts": {}, "observation_receipts": {}}


def test_cp89_report_is_deterministic_for_same_evidence_and_ref():
    c = contract()
    first = compile_growth_report(c, GrowthAnalyticsState(), (observation(),), report_ref="deterministic")
    second = compile_growth_report(c, GrowthAnalyticsState(), (observation(),), report_ref="deterministic")
    assert first.report_hash == second.report_hash
    assert first.report_id == second.report_id
    assert first.to_dict() == second.to_dict()
