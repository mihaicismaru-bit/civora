import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from public_presence_os.engagement_radar import (
    EngagementObservation,
    EngagementScoreEvidence,
    compile_engagement_radar,
    score_candidate,
)
from public_presence_os.engagement_scheduler import (
    ActionType,
    CapabilityState,
    DecisionCode,
    EngagementReceipt,
    EngagementScheduler,
    SchedulerCandidate,
)
from public_presence_os.growth_analytics import (
    GrowthAnalyticsState,
    GrowthObservation,
    compile_growth_analytics,
    evaluate_observation,
)
from public_presence_os.growth_capability_matrix import compile_growth_capability_matrix
from public_presence_os.growth_dry_run_acceptance import (
    AcceptanceEvidence,
    GrowthDryRunAcceptanceHold,
    REQUIRED_ACCEPTANCE_CASES,
    build_engagement_monitor_tasks,
    evaluate_acceptance,
    validate_policy,
)
from public_presence_os.inbound_reply import (
    InboundObservation,
    compile_inbound_reply_engine,
    process_batch as process_inbound_batch,
)
from public_presence_os.outbound_engagement import (
    ValueAddProposal,
    compile_outbound_engagement_engine,
    compose_outbound_candidate,
)
from public_presence_os.relationship_graph import (
    InteractionEvent,
    RelationshipGraphState,
    apply_interaction,
    compile_relationship_graph,
)


ROOT = Path(__file__).resolve().parents[1]
CP91_POLICY = ROOT / "config" / "growth_dry_run_acceptance_policy.json"
CP90_POLICY = ROOT / "config" / "engagement_scheduler_rate_quality_budget_policy.json"
CP89_POLICY = ROOT / "config" / "growth_analytics_virality_learning_policy.json"
CP87_POLICY = ROOT / "config" / "relationship_graph_policy.json"
CP86_POLICY = ROOT / "config" / "outbound_value_add_engagement_policy.json"
CP85_POLICY = ROOT / "config" / "inbound_reply_policy.json"
CP84_POLICY = ROOT / "config" / "engagement_radar_policy.json"
CP83_POLICY = ROOT / "config" / "growth_capability_matrix_policy.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def cp83_contract():
    return compile_growth_capability_matrix(read_json(CP83_POLICY))


def cp84_contract():
    return compile_engagement_radar(read_json(CP84_POLICY), cp83_contract())


def cp85_contract():
    return compile_inbound_reply_engine(read_json(CP85_POLICY), cp83_contract())


def cp86_contract():
    return compile_outbound_engagement_engine(read_json(CP86_POLICY), cp83_contract())


def inbound_observation(**overrides):
    base = dict(
        platform="INSTAGRAM_PROFESSIONAL",
        surface_kind="OWN_CONTENT_COMMENT",
        provenance_kind="SYNTHETIC_FIXTURE",
        provenance_ref="fixture:cp91:ig:comment:001",
        inbound_ref="cp91-ig-comment-001",
        conversation_ref="cp91-ig-thread-001",
        own_content_ref="cp91-ig-own-post-001",
        source_url="synthetic://instagram/comment/cp91-001",
        author_public_id="@public_account",
        text="Care este termenul exact pentru inscriere?",
        observed_at_utc="2026-09-20T08:30:00Z",
        own_content_published_at_utc="2026-09-20T08:00:00Z",
        evidence_tags=("QUESTION_SIGNAL",),
        response_evidence=("Inscrierea se incheie la 30 septembrie, ora 23:59.",),
    )
    base.update(overrides)
    return InboundObservation(**base)


def radar_candidate(*, eligible=True, platform="THREADS"):
    scores = EngagementScoreEvidence(
        relevance=90 if eligible else 10,
        expertise_fit=85,
        conversation_momentum=70,
        novelty=75,
        answerability=90,
        reputational_risk=10,
        spam_risk=5,
        expected_relationship_value=80,
    )
    observation = EngagementObservation(
        platform=platform,
        discovery_capability="MENTION_DISCOVERY",
        provenance_kind="SYNTHETIC_FIXTURE",
        provenance_ref=f"fixture:cp91:{platform}:conversation:001",
        conversation_ref=f"{platform}-conversation-001",
        source_url=f"synthetic://{platform.lower()}/conversation/001",
        author_public_id="@public_peer",
        topic="finantare europeana",
        context="Discutie publica despre un termen procedural si efectul lui practic.",
        observed_at_utc="2026-09-20T09:00:00Z",
        published_at_utc="2026-09-20T08:30:00Z",
        score_evidence=scores,
    )
    return score_candidate(cp84_contract(), observation, now_utc="2026-09-20T09:30:00Z")


def outbound_proposal(**overrides):
    base = dict(
        composer_mode="CLARIFICATION",
        material_value_kind="CLARIFICATION",
        contribution_text=(
            "Clarificarea utila aici este ca termenul se verifica in documentul oficial "
            "al apelului, nu intr-un rezumat secundar."
        ),
        evidence=("Documentul oficial al apelului este sursa de control pentru termen.",),
        provenance_kind="SYNTHETIC_FIXTURE",
        provenance_ref="fixture:cp91:threads:proposal:001",
        target_ref="THREADS-conversation-001",
        source_url="synthetic://threads/conversation/001",
    )
    base.update(overrides)
    return ValueAddProposal(**base)


def relationship_event(**overrides):
    base = dict(
        platform="THREADS",
        source_public_id="@our_public_profile",
        peer_public_id="@public_peer",
        interaction_kind="replied_to",
        conversation_ref="cp91-threads-conversation-001",
        content_ref="cp91-threads-post-001",
        topic="finantare europeana",
        observed_at_utc="2026-09-20T09:40:00Z",
        quality_score=80,
        provenance_ref="fixture:cp91:threads:interaction:001",
    )
    base.update(overrides)
    return InteractionEvent(**base)


def sparse_growth_observation():
    return GrowthObservation(
        platform="THREADS",
        observation_ref="cp91-sparse-analytics-001",
        topic="finantare europeana",
        observed_at_utc="2026-09-20T10:00:00Z",
        provenance_ref="fixture:cp91:analytics:sparse:001",
        evidence_class="SYNTHETIC_OFFLINE",
        source_is_public=True,
        aggregate_content_level_only=True,
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


def scheduler_candidate(**overrides):
    publication = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
    base = dict(
        action_id="cp91-action-001",
        platform="threads",
        account_ref="@our_public_profile",
        thread_ref="cp91-thread-001",
        action_type=ActionType.INBOUND_REPLY,
        text="Raspuns util si specific bazat pe informatia verificata din context.",
        publication_time_utc=publication,
        earliest_due_utc=publication,
        timezone_name="Europe/Bucharest",
        quality_score=0.95,
        capability_state=CapabilityState.VERIFIED_OFFLINE_CONTRACT,
        provenance_ref="fixture:cp91:scheduler:001",
    )
    base.update(overrides)
    return SchedulerCandidate(**base)


def build_real_acceptance_evidence():
    cp91_policy = read_json(CP91_POLICY)
    cp90_policy = read_json(CP90_POLICY)

    publication = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    monitor_tasks = build_engagement_monitor_tasks(
        cp91_policy,
        cp90_policy,
        publication_ref="cp91-publication-001",
        platform="THREADS",
        account_ref="@our_public_profile",
        publication_time_utc=publication,
        timezone_name="Europe/Bucharest",
    )
    publication_monitor_tasks = (
        len(monitor_tasks) >= cp91_policy["monitor_task_defaults"]["minimum_task_count"]
        and monitor_tasks[0].due_at_utc == publication.isoformat()
        and all(not task.external_write_allowed and not task.social_api_call_allowed for task in monitor_tasks)
    )

    hot = inbound_observation()
    older = inbound_observation(
        provenance_ref="fixture:cp91:ig:comment:older",
        inbound_ref="cp91-ig-comment-older",
        conversation_ref="cp91-ig-thread-older",
        own_content_ref="cp91-ig-own-post-older",
        source_url="synthetic://instagram/comment/cp91-older",
        observed_at_utc="2026-09-20T08:40:00Z",
        own_content_published_at_utc="2026-09-20T05:30:00Z",
    )
    inbound_results = process_inbound_batch(
        cp85_contract(), [older, hot], now_utc="2026-09-20T09:00:00Z"
    )
    inbound_ranking_and_dry_run_reply = (
        inbound_results[0].inbound_ref == hot.inbound_ref
        and inbound_results[0].decision == "DRAFT_READY_HUMAN_REVIEW"
        and inbound_results[0].response_candidate is not None
        and inbound_results[0].external_write_allowed is False
        and inbound_results[0].posting_authority is False
    )

    high = radar_candidate(eligible=True)
    low = radar_candidate(eligible=False)
    good_outbound = compose_outbound_candidate(cp86_contract(), high, outbound_proposal())
    low_outbound = compose_outbound_candidate(cp86_contract(), low, outbound_proposal())
    spam_outbound = compose_outbound_candidate(
        cp86_contract(),
        high,
        outbound_proposal(
            provenance_ref="fixture:cp91:threads:proposal:spam",
            generic_compliment_only=True,
        ),
    )
    outbound_scoring_low_value_spam_rejection = (
        good_outbound.decision == "DRY_RUN_API_CANDIDATE_HUMAN_REVIEW"
        and good_outbound.external_write_allowed is False
        and low_outbound.decision == "REJECT_CP84_NOT_ELIGIBLE"
        and spam_outbound.decision == "REJECT_GROWTH_SAFETY"
    )

    relationship_contract = compile_relationship_graph(read_json(CP87_POLICY))
    relationship_state = RelationshipGraphState()
    first_relationship = apply_interaction(
        relationship_contract, relationship_state, relationship_event()
    )
    state_before_replay = relationship_state.to_dict()
    replay_relationship = apply_interaction(
        relationship_contract, relationship_state, relationship_event()
    )
    relationship_graph_idempotent = (
        replay_relationship.idempotent_replay is True
        and replay_relationship.event_id == first_relationship.event_id
        and relationship_state.to_dict() == state_before_replay
    )

    scheduler = EngagementScheduler(cp90_policy)
    now = datetime(2026, 9, 20, 9, 10, tzinfo=timezone.utc)
    duplicate_report = scheduler.schedule_batch(
        [scheduler_candidate(), scheduler_candidate()], now_utc=now
    )
    inbound_dedupe = process_inbound_batch(
        cp85_contract(), [hot, hot], now_utc="2026-09-20T09:00:00Z"
    )
    duplicate_actions_impossible = (
        len(inbound_dedupe) == 1
        and duplicate_report.eligible_count == 1
        and any(
            item.code == DecisionCode.IDEMPOTENT_ALREADY_RECEIPTED
            for item in duplicate_report.decisions
        )
        and duplicate_report.external_write_count == 0
        and duplicate_report.social_api_call_count == 0
    )

    tight_policy = copy.deepcopy(cp90_policy)
    tight_policy["hard_ceiling_budgets"]["global_daily"] = 1
    budget_scheduler = EngagementScheduler(tight_policy)
    prior_receipt = EngagementReceipt(
        action_id="cp91-prior-001",
        payload_fingerprint="prior-fixture-fingerprint",
        occurred_at_utc=datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc),
        account_ref="@different_public_account",
        thread_ref="cp91-prior-thread",
        action_type=ActionType.INBOUND_REPLY,
        text="Mesaj anterior distinct despre un subiect diferit, fara suprapunere semantica.",
    )
    budget_report = budget_scheduler.schedule_batch(
        [scheduler_candidate(action_id="cp91-rate-limited")],
        prior_receipts=[prior_receipt],
        now_utc=now,
    )
    rate_ceilings_enforced = (
        budget_report.decisions[0].code == DecisionCode.HOLD_RATE_BUDGET_DAILY
        and budget_report.external_write_count == 0
    )

    kill_report = scheduler.schedule_batch(
        [scheduler_candidate(action_id="cp91-live-write", requires_live_write=True)],
        now_utc=now,
    )
    kill_switch_suppresses_write_paths = (
        kill_report.decisions[0].code == DecisionCode.HOLD_KILL_SWITCH_ENGAGED
        and kill_report.external_write_count == 0
        and kill_report.social_api_call_count == 0
        and good_outbound.external_write_allowed is False
        and inbound_results[0].external_write_allowed is False
    )

    manual_report = scheduler.schedule_batch(
        [
            scheduler_candidate(
                action_id="cp91-manual-only",
                capability_state=CapabilityState.MANUAL_ONLY,
            ),
            scheduler_candidate(
                action_id="cp91-capability-hold",
                capability_state=CapabilityState.HOLD_CAPABILITY_UNVERIFIED,
                account_ref="@another_public_account",
                thread_ref="cp91-thread-002",
                text="Alta contributie utila, distincta si verificabila pentru un context separat.",
            ),
        ],
        now_utc=now,
    )
    codes = {item.action_id: item.code for item in manual_report.decisions}
    unsupported_capability_manual_or_hold = (
        codes["cp91-manual-only"] == DecisionCode.MANUAL_ACTION_PACKET
        and codes["cp91-capability-hold"] == DecisionCode.HOLD_CAPABILITY_UNVERIFIED
        and manual_report.external_write_count == 0
    )

    analytics_contract = compile_growth_analytics(read_json(CP89_POLICY))
    sparse_result = evaluate_observation(
        analytics_contract,
        GrowthAnalyticsState(),
        sparse_growth_observation(),
    )
    missing_analytics_remain_unknown = (
        all(metric.state == "UNKNOWN" and metric.value is None for metric in sparse_result.metrics.values())
        and sparse_result.virality_learning.state == "INSUFFICIENT_EVIDENCE"
        and sparse_result.virality_learning.observed_signal_score.state == "UNKNOWN"
        and sparse_result.virality_learning.observed_signal_score.value is None
    )

    return AcceptanceEvidence(
        publication_monitor_tasks=publication_monitor_tasks,
        inbound_ranking_and_dry_run_reply=inbound_ranking_and_dry_run_reply,
        outbound_scoring_low_value_spam_rejection=outbound_scoring_low_value_spam_rejection,
        relationship_graph_idempotent=relationship_graph_idempotent,
        duplicate_actions_impossible=duplicate_actions_impossible,
        rate_ceilings_enforced=rate_ceilings_enforced,
        kill_switch_suppresses_write_paths=kill_switch_suppresses_write_paths,
        unsupported_capability_manual_or_hold=unsupported_capability_manual_or_hold,
        missing_analytics_remain_unknown=missing_analytics_remain_unknown,
    )


def test_cp91_policy_keeps_cp58_kill_switch_and_zero_live_authority():
    policy = read_json(CP91_POLICY)
    validate_policy(policy)
    assert policy["checkpoint"] == "CP91"
    assert policy["parent_activation_checkpoint"] == "CP90"
    assert policy["parent_control_checkpoint"] == "CP58"
    assert policy["global_kill_switch"] == "ENGAGED"
    assert policy["live_authority"] == "NONE"
    assert policy["next_after_cp91"] == "CP92_PILOT_GROWTH_OPERATIONS_MANUAL_SHADOW_PILOT_PLAN"
    assert tuple(policy["required_acceptance_cases"]) == REQUIRED_ACCEPTANCE_CASES
    assert all(value is False for key, value in policy["write_boundary"].items() if key in {
        "external_write", "social_api_call", "oauth", "token_or_secret_resolution",
        "live_probe", "account_connection", "publish", "deploy", "paid_service"
    })


def test_cp91_one_publication_produces_bounded_monitor_tasks_without_io():
    policy = read_json(CP91_POLICY)
    publication = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
    tasks = build_engagement_monitor_tasks(
        policy,
        read_json(CP90_POLICY),
        publication_ref="cp91-publication-monitor-test",
        platform="THREADS",
        account_ref="@our_public_profile",
        publication_time_utc=publication,
        timezone_name="Europe/Bucharest",
    )
    assert len(tasks) == 9
    assert tasks[0].due_at_utc == publication.isoformat()
    assert tasks[-1].due_at_utc == (publication + timedelta(hours=4)).isoformat()
    assert len({task.task_id for task in tasks}) == len(tasks)
    assert all(task.action == "ENGAGEMENT_MONITOR_DRY_RUN" for task in tasks)
    assert all(task.external_write_allowed is False for task in tasks)
    assert all(task.social_api_call_allowed is False for task in tasks)
    assert all(task.live_probe_allowed is False for task in tasks)


def test_cp91_canonical_end_to_end_evidence_passes_all_nine_cases():
    evidence = build_real_acceptance_evidence()
    assert all(evidence.case_results().values())
    report = evaluate_acceptance(read_json(CP91_POLICY), evidence)
    assert report.overall_state == "PASS_CP91_OFFLINE_SYNTHETIC_ACCEPTANCE"
    assert report.passed_count == 9
    assert report.failed_count == 0
    assert tuple(item.case_id for item in report.cases) == REQUIRED_ACCEPTANCE_CASES
    assert all(item.passed and item.state == "PASS_OFFLINE_SYNTHETIC" for item in report.cases)
    assert report.global_checkpoint == "CP58"
    assert report.global_kill_switch_engaged is True
    assert report.live_authority == "NONE"
    assert report.external_metrics == "UNKNOWN"
    assert report.external_write_allowed is False
    assert report.social_api_call_allowed is False
    assert report.live_probe_allowed is False
    assert report.oauth_allowed is False
    assert report.account_connection_allowed is False
    assert report.publish_allowed is False
    assert report.deploy_allowed is False
    assert report.paid_service_allowed is False


def test_cp91_one_failed_gate_never_becomes_false_pass():
    evidence = replace(
        build_real_acceptance_evidence(),
        unsupported_capability_manual_or_hold=False,
    )
    report = evaluate_acceptance(read_json(CP91_POLICY), evidence)
    assert report.overall_state == "HOLD_CP91_ACCEPTANCE_INCOMPLETE"
    assert report.passed_count == 8
    assert report.failed_count == 1
    failed = [item for item in report.cases if not item.passed]
    assert [item.case_id for item in failed] == ["UNSUPPORTED_CAPABILITY_MANUAL_OR_HOLD"]


def test_cp91_any_external_io_observation_fails_closed():
    evidence = replace(build_real_acceptance_evidence(), external_write_count=1)
    with pytest.raises(GrowthDryRunAcceptanceHold, match="HOLD_CP91_EXTERNAL_IO_OBSERVED"):
        evaluate_acceptance(read_json(CP91_POLICY), evidence)


def test_cp91_policy_weakening_fails_closed():
    policy = read_json(CP91_POLICY)
    weakened = copy.deepcopy(policy)
    weakened["global_kill_switch"] = "DISENGAGED"
    with pytest.raises(GrowthDryRunAcceptanceHold, match="HOLD_CP91_POLICY_IDENTITY_DRIFT"):
        validate_policy(weakened)

    weakened = copy.deepcopy(policy)
    weakened["write_boundary"]["external_write"] = True
    with pytest.raises(GrowthDryRunAcceptanceHold, match="HOLD_CP91_LIVE_AUTHORITY_DRIFT"):
        validate_policy(weakened)

    weakened = copy.deepcopy(policy)
    weakened["truthfulness"]["missing_is_never_zero"] = False
    with pytest.raises(GrowthDryRunAcceptanceHold, match="HOLD_CP91_TRUTHFULNESS_WEAKENED"):
        validate_policy(weakened)

    weakened = copy.deepcopy(policy)
    weakened["growth_safety"]["mass_commenting_forbidden"] = False
    with pytest.raises(GrowthDryRunAcceptanceHold, match="HOLD_CP91_GROWTH_SAFETY_WEAKENED"):
        validate_policy(weakened)


def test_cp91_acceptance_report_is_deterministic_for_same_evidence():
    evidence = build_real_acceptance_evidence()
    first = evaluate_acceptance(read_json(CP91_POLICY), evidence, report_ref="deterministic-cp91")
    second = evaluate_acceptance(read_json(CP91_POLICY), evidence, report_ref="deterministic-cp91")
    assert first.report_id == second.report_id
    assert first.report_hash == second.report_hash
    assert first.to_dict() == second.to_dict()
