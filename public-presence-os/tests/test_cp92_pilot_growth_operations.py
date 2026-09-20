import copy

import pytest

from public_presence_os.pilot_growth_operations import (
    ACTIVE_PLATFORMS,
    PilotGrowthOperationsHold,
    ShadowObservation,
    ShadowPilotEvidence,
    build_operator_setup_packet,
    build_rollback_packet,
    evaluate_offline_shadow_rehearsal,
    load_policy,
    recommend_from_shadow_observation,
    validate_policy,
)


def test_cp92_policy_is_offline_shadow_plan_only():
    policy = load_policy()
    validate_policy(policy)
    assert policy["checkpoint"] == "CP92"
    assert policy["parent_activation_checkpoint"] == "CP91"
    assert policy["parent_control_checkpoint"] == "CP58"
    assert policy["mode"] == "OFFLINE_SHADOW_PLAN_ONLY"
    assert policy["global_kill_switch"] == "ENGAGED"
    assert policy["live_authority"] == "NONE"
    assert tuple(policy["active_platforms"]) == ACTIVE_PLATFORMS
    assert policy["authorization"]["authorization_captured"] is False


@pytest.mark.parametrize("platform", ACTIVE_PLATFORMS)
def test_cp92_operator_setup_is_manual_and_zero_io(platform):
    policy = load_policy()
    packet = build_operator_setup_packet(policy, platform=platform)
    assert packet.state == "MANUAL_ACTION_PACKET_AUTHORIZATION_REQUIRED"
    assert packet.external_write_allowed is False
    assert packet.social_api_call_allowed is False
    assert packet.live_probe_allowed is False
    assert "ZERO_WRITE_AUTHORITY_CONFIRMED" in packet.required_evidence


def test_cp92_shadow_fixture_generates_recommendation_only_and_preserves_unknown():
    policy = load_policy()
    observation = ShadowObservation(
        observation_ref="fixture-comment-001",
        platform="THREADS",
        event_type="QUESTION",
        public_context="Can you clarify the evidence behind this claim?",
        metric_value=None,
    )
    recommendation = recommend_from_shadow_observation(policy, observation)
    assert recommendation.state == "RECOMMENDATION_ONLY_HUMAN_REVIEW"
    assert recommendation.recommendation_type == "DRAFT_INBOUND_REPLY"
    assert recommendation.metric_value == "UNKNOWN"
    assert recommendation.external_write_allowed is False
    assert recommendation.social_api_call_allowed is False
    assert recommendation.live_probe_allowed is False
    assert recommendation.live_authority == "NONE"


def test_cp92_live_observation_is_not_authorized():
    policy = load_policy()
    observation = ShadowObservation(
        observation_ref="real-comment-not-authorized",
        platform="FACEBOOK_PAGE",
        event_type="QUESTION",
        public_context="A real comment would require an authorized read-only phase.",
        source_mode="LIVE",
    )
    with pytest.raises(
        PilotGrowthOperationsHold,
        match="HOLD_CP92_LIVE_SHADOW_OBSERVATION_NOT_AUTHORIZED",
    ):
        recommend_from_shadow_observation(policy, observation)


@pytest.mark.parametrize("capability_state", ["MANUAL_ONLY", "HOLD_LIVE_PERMISSION"])
def test_cp92_gated_capability_becomes_manual_packet(capability_state):
    policy = load_policy()
    observation = ShadowObservation(
        observation_ref=f"fixture-{capability_state}",
        platform="INSTAGRAM_PROFESSIONAL",
        event_type="MENTION",
        public_context="Synthetic mention fixture",
        capability_state=capability_state,
    )
    packet = recommend_from_shadow_observation(policy, observation)
    assert packet.state == "MANUAL_ACTION_PACKET"
    assert packet.external_write_allowed is False
    assert "EXPLICIT_PILOT_AUTHORIZATION" in packet.required_evidence


@pytest.mark.parametrize("capability_state", ["UNSUPPORTED", "HOLD_CAPABILITY_UNVERIFIED"])
def test_cp92_unknown_or_unsupported_capability_holds(capability_state):
    policy = load_policy()
    observation = ShadowObservation(
        observation_ref=f"fixture-{capability_state}",
        platform="FACEBOOK_PAGE",
        event_type="MENTION",
        public_context="Synthetic unsupported capability fixture",
        capability_state=capability_state,
    )
    packet = recommend_from_shadow_observation(policy, observation)
    assert packet.state == "HOLD_CAPABILITY_UNVERIFIED"
    assert packet.external_write_allowed is False


def test_cp92_complete_offline_rehearsal_does_not_claim_real_shadow_completion():
    policy = load_policy()
    evidence = ShadowPilotEvidence(
        capability_matrix_revalidated_current=True,
        read_only_permission_receipts_complete=True,
        shadow_observations_recommendations_zero_writes=True,
        no_unsupported_action_drift=True,
        missing_metrics_remain_unknown=True,
        growth_safety_filters_hold=True,
        rate_budgets_are_ceilings=True,
        audit_receipts_complete=True,
    )
    report = evaluate_offline_shadow_rehearsal(policy, evidence)
    assert report["overall_state"] == "PASS_CP92_OFFLINE_SHADOW_PLAN_REHEARSAL"
    assert report["global_checkpoint"] == "CP58"
    assert report["shadow_pilot_completed"] is False
    assert report["authorization_captured"] is False
    assert report["external_metrics"] == "UNKNOWN"
    assert report["external_write_performed"] is False
    assert report["social_api_call_performed"] is False
    assert report["live_probe_performed"] is False


def test_cp92_any_external_io_fails_closed():
    policy = load_policy()
    evidence = ShadowPilotEvidence(
        capability_matrix_revalidated_current=True,
        read_only_permission_receipts_complete=True,
        shadow_observations_recommendations_zero_writes=True,
        no_unsupported_action_drift=True,
        missing_metrics_remain_unknown=True,
        growth_safety_filters_hold=True,
        rate_budgets_are_ceilings=True,
        audit_receipts_complete=True,
        external_write_count=1,
    )
    with pytest.raises(PilotGrowthOperationsHold, match="HOLD_CP92_EXTERNAL_IO_OBSERVED"):
        evaluate_offline_shadow_rehearsal(policy, evidence)


def test_cp92_policy_cannot_capture_authorization_or_weaken_kill_switch():
    policy = load_policy()
    weakened = copy.deepcopy(policy)
    weakened["authorization"]["authorization_captured"] = True
    with pytest.raises(PilotGrowthOperationsHold, match="HOLD_CP92_AUTHORIZATION_GATE_WEAKENED"):
        validate_policy(weakened)

    weakened = copy.deepcopy(policy)
    weakened["global_kill_switch"] = "DISENGAGED"
    with pytest.raises(PilotGrowthOperationsHold, match="HOLD_CP92_POLICY_IDENTITY_DRIFT"):
        validate_policy(weakened)


def test_cp92_rollback_keeps_hold_controls():
    policy = load_policy()
    rollback = build_rollback_packet(policy, reason="CAPABILITY_DRIFT")
    assert rollback["state"] == "ROLLBACK_SHADOW_PLAN_STOP_AND_HOLD"
    assert rollback["external_write_allowed"] is False
    assert "KEEP_KILL_SWITCH_ENGAGED" in rollback["actions"]
    assert "KEEP_LIVE_AUTHORITY_NONE" in rollback["actions"]
