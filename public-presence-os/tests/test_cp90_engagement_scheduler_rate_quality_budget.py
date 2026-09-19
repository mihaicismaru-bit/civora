from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from public_presence_os.engagement_scheduler import (
    ActionType,
    CapabilityState,
    DecisionCode,
    EngagementReceipt,
    EngagementScheduler,
    SchedulerCandidate,
    candidate_fingerprint,
    load_policy,
    text_similarity,
)


BASE = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def candidate(
    action_id: str = "a1",
    *,
    account: str = "acct-a",
    thread: str = "thread-a",
    action_type: ActionType = ActionType.INBOUND_REPLY,
    text: str = "A useful clarification with concrete context and one specific question.",
    quality: float = 0.9,
    earliest: datetime | None = None,
    publication: datetime | None = None,
    platform: str = "threads",
    capability: CapabilityState = CapabilityState.VERIFIED_OFFLINE_CONTRACT,
    requires_live_write: bool = False,
    retry_count: int = 0,
    conflict_risk: bool = False,
    reputational_risk: bool = False,
    ambiguous_political_persuasion: bool = False,
    behavior_tags: tuple[str, ...] = (),
) -> SchedulerCandidate:
    return SchedulerCandidate(
        action_id=action_id,
        platform=platform,
        account_ref=account,
        thread_ref=thread,
        action_type=action_type,
        text=text,
        publication_time_utc=publication or BASE,
        earliest_due_utc=earliest or (BASE + timedelta(minutes=15)),
        timezone_name="Europe/Bucharest",
        quality_score=quality,
        capability_state=capability,
        requires_live_write=requires_live_write,
        retry_count=retry_count,
        conflict_risk=conflict_risk,
        reputational_risk=reputational_risk,
        ambiguous_political_persuasion=ambiguous_political_persuasion,
        behavior_tags=behavior_tags,
        provenance_ref=f"prov:{action_id}",
    )


def receipt_for(
    c: SchedulerCandidate,
    *,
    occurred: datetime | None = None,
    fingerprint: str | None = None,
    text: str | None = None,
) -> EngagementReceipt:
    return EngagementReceipt(
        action_id=c.action_id,
        payload_fingerprint=fingerprint or candidate_fingerprint(c),
        occurred_at_utc=occurred or BASE,
        account_ref=c.account_ref,
        thread_ref=c.thread_ref,
        action_type=c.action_type,
        text=text if text is not None else c.text,
    )


def history_receipt(
    index: int,
    *,
    account: str | None = None,
    thread: str | None = None,
    action_type: ActionType = ActionType.INBOUND_REPLY,
    occurred: datetime | None = None,
) -> EngagementReceipt:
    return EngagementReceipt(
        action_id=f"history-{index}",
        payload_fingerprint=f"fp-{index}",
        occurred_at_utc=occurred or (BASE + timedelta(minutes=index)),
        account_ref=account or f"history-account-{index}",
        thread_ref=thread or f"history-thread-{index}",
        action_type=action_type,
        text=f"Historical evidence item number {index} with unrelated vocabulary token{index}.",
    )


def test_policy_preserves_control_plane_and_zero_write_boundary() -> None:
    policy = load_policy()
    assert policy["global_checkpoint"] == "CP58"
    assert policy["kill_switch_required_state"] == "ENGAGED"
    assert policy["live_authority"] == "NONE"
    assert policy["mode"] == "OFFLINE_ONLY"
    assert policy["write_boundary"]["external_write"] is False
    assert policy["write_boundary"]["social_api_call"] is False


def test_poll_plan_is_bounded_timezone_aware_and_deterministic() -> None:
    scheduler = EngagementScheduler()
    plan = scheduler.build_poll_plan(BASE, "Europe/Bucharest")
    assert len(plan) == 9
    assert plan[0].utc == BASE
    assert plan[-1].utc == BASE + timedelta(minutes=240)
    assert all(slot.local.tzinfo is not None for slot in plan)
    assert plan == scheduler.build_poll_plan(BASE, "Europe/Bucharest")


def test_poll_plan_rejects_unbounded_window_or_invalid_timezone() -> None:
    scheduler = EngagementScheduler()
    with pytest.raises(ValueError):
        scheduler.build_poll_plan(BASE, "Europe/Bucharest", window_minutes=300)
    with pytest.raises(Exception):
        scheduler.build_poll_plan(BASE, "Not/A_Real_Zone")


def test_clean_candidate_is_eligible_only_as_offline_dry_run() -> None:
    report = EngagementScheduler().schedule_batch([candidate()], now_utc=BASE)
    decision = report.decisions[0]
    assert decision.code == DecisionCode.ELIGIBLE_DRY_RUN
    assert decision.due_at_utc == BASE + timedelta(minutes=15)
    assert report.external_write_count == 0
    assert report.social_api_call_count == 0


def test_live_write_is_blocked_by_engaged_kill_switch() -> None:
    c = candidate(requires_live_write=True)
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_KILL_SWITCH_ENGAGED


def test_unknown_capability_fails_closed_before_write_assumption() -> None:
    c = candidate(capability=CapabilityState.HOLD_CAPABILITY_UNVERIFIED)
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_CAPABILITY_UNVERIFIED


def test_manual_only_capability_produces_manual_action_packet() -> None:
    c = candidate(capability=CapabilityState.MANUAL_ONLY)
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.MANUAL_ACTION_PACKET
    assert decision.manual_action_packet


def test_risk_flags_escalate_to_human_review() -> None:
    c = candidate(ambiguous_political_persuasion=True)
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HUMAN_REVIEW_REQUIRED


def test_forbidden_growth_mechanic_is_rejected() -> None:
    c = candidate(behavior_tags=("mass_commenting",))
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_POLICY_FORBIDDEN


def test_retry_exhaustion_is_terminal_fail_closed_hold() -> None:
    c = candidate(retry_count=3)
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_RETRY_EXHAUSTED_FAIL_CLOSED


def test_quality_floor_is_hard_gate_not_target() -> None:
    c = candidate(quality=0.69)
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_LOW_QUALITY


def test_similarity_guard_blocks_repetitive_outgoing_message() -> None:
    c = candidate(action_id="new")
    old = history_receipt(1)
    old = EngagementReceipt(
        action_id=old.action_id,
        payload_fingerprint=old.payload_fingerprint,
        occurred_at_utc=old.occurred_at_utc,
        account_ref=old.account_ref,
        thread_ref=old.thread_ref,
        action_type=old.action_type,
        text="A useful clarification with concrete context and one specific question!",
    )
    decision = EngagementScheduler().schedule_batch([c], [old], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_SIMILARITY_DUPLICATE
    assert text_similarity(c.text, old.text) == 1.0


def test_global_daily_ceiling_is_never_exceeded() -> None:
    receipts = [history_receipt(i) for i in range(12)]
    decision = EngagementScheduler().schedule_batch(
        [candidate(action_id="daily-cap")], receipts, now_utc=BASE
    ).decisions[0]
    assert decision.code == DecisionCode.HOLD_RATE_BUDGET_DAILY


def test_global_weekly_ceiling_is_never_exceeded() -> None:
    receipts = []
    for i in range(48):
        occurred = BASE - timedelta(days=i % 6, minutes=i)
        receipts.append(history_receipt(i, occurred=occurred))
    c = candidate(action_id="weekly-cap", publication=BASE - timedelta(days=1), earliest=BASE)
    decision = EngagementScheduler().schedule_batch([c], receipts, now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_RATE_BUDGET_WEEKLY


def test_per_account_daily_ceiling_is_enforced() -> None:
    receipts = [history_receipt(i, account="acct-a") for i in range(3)]
    decision = EngagementScheduler().schedule_batch(
        [candidate(action_id="account-cap")], receipts, now_utc=BASE
    ).decisions[0]
    assert decision.code == DecisionCode.HOLD_ACCOUNT_RATE_BUDGET


def test_thread_saturation_ceiling_is_enforced() -> None:
    receipts = [history_receipt(i, thread="thread-a") for i in range(2)]
    decision = EngagementScheduler().schedule_batch(
        [candidate(action_id="thread-cap")], receipts, now_utc=BASE
    ).decisions[0]
    assert decision.code == DecisionCode.HOLD_THREAD_SATURATION


def test_account_cooldown_reschedules_inside_hot_window() -> None:
    last = history_receipt(1, account="acct-a", occurred=BASE + timedelta(minutes=20))
    c = candidate(action_id="cooldown", earliest=BASE + timedelta(minutes=25))
    decision = EngagementScheduler().schedule_batch([c], [last], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.ELIGIBLE_DRY_RUN
    assert decision.due_at_utc == BASE + timedelta(minutes=65)


def test_candidate_fails_closed_when_hot_window_has_elapsed() -> None:
    c = candidate(action_id="late", earliest=BASE + timedelta(minutes=250))
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_OUTSIDE_HOT_WINDOW


def test_receipt_replay_is_idempotent_and_has_no_duplicate_effect() -> None:
    c = candidate(action_id="receipt-id")
    prior = receipt_for(c)
    report = EngagementScheduler().schedule_batch([c], [prior], now_utc=BASE)
    assert report.decisions[0].code == DecisionCode.IDEMPOTENT_ALREADY_RECEIPTED
    assert report.eligible_count == 0


def test_receipt_payload_collision_fails_closed() -> None:
    c = candidate(action_id="collision")
    prior = receipt_for(c, fingerprint="different-payload-fingerprint")
    decision = EngagementScheduler().schedule_batch([c], [prior], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_RECEIPT_CONFLICT_FAIL_CLOSED


def test_fair_queue_order_prevents_one_account_from_dominating_first_round() -> None:
    a1 = candidate("a1", account="acct-a", thread="t1", quality=0.99)
    a2 = candidate("a2", account="acct-a", thread="t2", quality=0.98)
    b1 = candidate("b1", account="acct-b", thread="t3", quality=0.97)
    report = EngagementScheduler().schedule_batch([a2, b1, a1], now_utc=BASE)
    assert [d.action_id for d in report.decisions] == ["a1", "b1", "a2"]


def test_inactive_lane_is_held() -> None:
    c = candidate(platform="linkedin")
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_LANE_NOT_ACTIVE


def test_naive_datetime_fails_closed() -> None:
    c = candidate(publication=datetime(2026, 9, 19, 0, 0))
    decision = EngagementScheduler().schedule_batch([c], now_utc=BASE).decisions[0]
    assert decision.code == DecisionCode.HOLD_INVALID_INPUT_FAIL_CLOSED


def test_candidate_fingerprint_is_deterministic() -> None:
    c = candidate()
    assert candidate_fingerprint(c) == candidate_fingerprint(c)
    assert candidate_fingerprint(c) != candidate_fingerprint(candidate(action_id="a2"))


def test_outbound_and_amplification_type_specific_daily_caps() -> None:
    outbound_history = [
        history_receipt(i, action_type=ActionType.OUTBOUND_VALUE_ADD) for i in range(3)
    ]
    outbound = candidate(
        "outbound-cap",
        action_type=ActionType.OUTBOUND_VALUE_ADD,
        account="new-account",
        thread="new-thread",
    )
    assert (
        EngagementScheduler()
        .schedule_batch([outbound], outbound_history, now_utc=BASE)
        .decisions[0]
        .code
        == DecisionCode.HOLD_RATE_BUDGET_DAILY
    )

    amplification_history = [
        history_receipt(20 + i, action_type=ActionType.AMPLIFICATION) for i in range(2)
    ]
    amplification = candidate(
        "amp-cap",
        action_type=ActionType.AMPLIFICATION,
        account="amp-account",
        thread="amp-thread",
    )
    assert (
        EngagementScheduler()
        .schedule_batch([amplification], amplification_history, now_utc=BASE)
        .decisions[0]
        .code
        == DecisionCode.HOLD_RATE_BUDGET_DAILY
    )


def test_no_action_path_can_report_external_write_or_social_api_call() -> None:
    cases = [
        candidate("dry"),
        candidate("live", requires_live_write=True),
        candidate("manual", capability=CapabilityState.MANUAL_ONLY),
        candidate("unknown", capability=CapabilityState.HOLD_CAPABILITY_UNVERIFIED),
    ]
    report = EngagementScheduler().schedule_batch(cases, now_utc=BASE)
    assert report.external_write_count == 0
    assert report.social_api_call_count == 0
