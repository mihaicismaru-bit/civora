from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "engagement_scheduler_rate_quality_budget_policy.json"
)


class ActionType(str, Enum):
    INBOUND_REPLY = "INBOUND_REPLY"
    OUTBOUND_VALUE_ADD = "OUTBOUND_VALUE_ADD"
    AMPLIFICATION = "AMPLIFICATION"


class CapabilityState(str, Enum):
    VERIFIED_OFFLINE_CONTRACT = "VERIFIED_OFFLINE_CONTRACT"
    HOLD_CAPABILITY_UNVERIFIED = "HOLD_CAPABILITY_UNVERIFIED"
    MANUAL_ONLY = "MANUAL_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


class DecisionCode(str, Enum):
    ELIGIBLE_DRY_RUN = "ELIGIBLE_DRY_RUN"
    IDEMPOTENT_ALREADY_RECEIPTED = "IDEMPOTENT_ALREADY_RECEIPTED"
    MANUAL_ACTION_PACKET = "MANUAL_ACTION_PACKET"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    HOLD_CAPABILITY_UNVERIFIED = "HOLD_CAPABILITY_UNVERIFIED"
    HOLD_KILL_SWITCH_ENGAGED = "HOLD_KILL_SWITCH_ENGAGED"
    HOLD_LANE_NOT_ACTIVE = "HOLD_LANE_NOT_ACTIVE"
    HOLD_OUTSIDE_HOT_WINDOW = "HOLD_OUTSIDE_HOT_WINDOW"
    HOLD_LOW_QUALITY = "HOLD_LOW_QUALITY"
    HOLD_SIMILARITY_DUPLICATE = "HOLD_SIMILARITY_DUPLICATE"
    HOLD_RATE_BUDGET_DAILY = "HOLD_RATE_BUDGET_DAILY"
    HOLD_RATE_BUDGET_WEEKLY = "HOLD_RATE_BUDGET_WEEKLY"
    HOLD_ACCOUNT_RATE_BUDGET = "HOLD_ACCOUNT_RATE_BUDGET"
    HOLD_THREAD_SATURATION = "HOLD_THREAD_SATURATION"
    HOLD_RETRY_EXHAUSTED_FAIL_CLOSED = "HOLD_RETRY_EXHAUSTED_FAIL_CLOSED"
    HOLD_POLICY_FORBIDDEN = "HOLD_POLICY_FORBIDDEN"
    HOLD_RECEIPT_CONFLICT_FAIL_CLOSED = "HOLD_RECEIPT_CONFLICT_FAIL_CLOSED"
    HOLD_INVALID_INPUT_FAIL_CLOSED = "HOLD_INVALID_INPUT_FAIL_CLOSED"


@dataclass(frozen=True)
class SchedulerCandidate:
    action_id: str
    platform: str
    account_ref: str
    thread_ref: str
    action_type: ActionType
    text: str
    publication_time_utc: datetime
    earliest_due_utc: datetime
    timezone_name: str
    quality_score: float
    capability_state: CapabilityState = CapabilityState.VERIFIED_OFFLINE_CONTRACT
    requires_live_write: bool = False
    retry_count: int = 0
    conflict_risk: bool = False
    reputational_risk: bool = False
    ambiguous_political_persuasion: bool = False
    behavior_tags: tuple[str, ...] = ()
    provenance_ref: str = ""


@dataclass(frozen=True)
class EngagementReceipt:
    action_id: str
    payload_fingerprint: str
    occurred_at_utc: datetime
    account_ref: str
    thread_ref: str
    action_type: ActionType
    text: str
    counts_against_budget: bool = True


@dataclass(frozen=True)
class PollSlot:
    utc: datetime
    local: datetime


@dataclass(frozen=True)
class ScheduleDecision:
    action_id: str
    code: DecisionCode
    reason: str
    due_at_utc: datetime | None = None
    payload_fingerprint: str | None = None
    manual_action_packet: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchedulerBatchReport:
    decisions: tuple[ScheduleDecision, ...]
    eligible_count: int
    held_count: int
    manual_count: int
    human_review_count: int
    external_write_count: int = 0
    social_api_call_count: int = 0


class EngagementScheduler:
    """Deterministic CP90 scheduler. It never performs an external write or API call."""

    def __init__(self, policy: Mapping[str, object] | None = None) -> None:
        self.policy = dict(policy or load_policy())
        self._validate_policy()

    def _validate_policy(self) -> None:
        if self.policy.get("mode") != "OFFLINE_ONLY":
            raise ValueError("CP90 policy must remain OFFLINE_ONLY")
        if self.policy.get("global_checkpoint") != "CP58":
            raise ValueError("global checkpoint must remain CP58")
        if self.policy.get("kill_switch_required_state") != "ENGAGED":
            raise ValueError("kill switch must remain ENGAGED")
        if self.policy.get("live_authority") != "NONE":
            raise ValueError("live authority must remain NONE")
        boundary = self.policy.get("write_boundary")
        if not isinstance(boundary, Mapping):
            raise ValueError("write_boundary missing")
        for key in (
            "external_write",
            "social_api_call",
            "oauth",
            "token_or_secret_resolution",
            "deploy",
            "paid_service",
        ):
            if boundary.get(key) is not False:
                raise ValueError(f"{key} must remain false")

    def build_poll_plan(
        self,
        publication_time_utc: datetime,
        timezone_name: str,
        *,
        window_minutes: int | None = None,
        interval_minutes: int | None = None,
    ) -> tuple[PollSlot, ...]:
        publication = _as_utc(publication_time_utc)
        zone = _zone(timezone_name)
        hot = _mapping(self.policy, "hot_window")
        window = int(window_minutes or hot["default_minutes"])
        interval = int(interval_minutes or hot["default_poll_interval_minutes"])
        if not int(hot["minimum_minutes"]) <= window <= int(hot["maximum_minutes"]):
            raise ValueError("hot window outside policy bounds")
        if not int(hot["minimum_poll_interval_minutes"]) <= interval <= int(
            hot["maximum_poll_interval_minutes"]
        ):
            raise ValueError("poll interval outside policy bounds")
        end = publication + timedelta(minutes=window)
        cursor = publication
        slots: list[PollSlot] = []
        while cursor <= end:
            slots.append(PollSlot(utc=cursor, local=cursor.astimezone(zone)))
            cursor += timedelta(minutes=interval)
        return tuple(slots)

    def schedule_batch(
        self,
        candidates: Sequence[SchedulerCandidate],
        prior_receipts: Sequence[EngagementReceipt] = (),
        *,
        now_utc: datetime,
    ) -> SchedulerBatchReport:
        now = _as_utc(now_utc)
        ordered = self._fair_order(candidates)
        working_receipts = list(prior_receipts)
        decisions: list[ScheduleDecision] = []
        seen_candidates: dict[str, str] = {}

        for candidate in ordered:
            try:
                fingerprint = candidate_fingerprint(candidate)
            except (TypeError, ValueError):
                decisions.append(
                    ScheduleDecision(
                        candidate.action_id,
                        DecisionCode.HOLD_INVALID_INPUT_FAIL_CLOSED,
                        "candidate could not be normalized deterministically",
                    )
                )
                continue

            prior_candidate_fingerprint = seen_candidates.get(candidate.action_id)
            if prior_candidate_fingerprint is not None:
                code = (
                    DecisionCode.IDEMPOTENT_ALREADY_RECEIPTED
                    if prior_candidate_fingerprint == fingerprint
                    else DecisionCode.HOLD_RECEIPT_CONFLICT_FAIL_CLOSED
                )
                decisions.append(
                    ScheduleDecision(
                        candidate.action_id,
                        code,
                        "duplicate action_id in candidate batch",
                        payload_fingerprint=fingerprint,
                    )
                )
                continue
            seen_candidates[candidate.action_id] = fingerprint

            existing = [r for r in working_receipts if r.action_id == candidate.action_id]
            if existing:
                if all(r.payload_fingerprint == fingerprint for r in existing):
                    decisions.append(
                        ScheduleDecision(
                            candidate.action_id,
                            DecisionCode.IDEMPOTENT_ALREADY_RECEIPTED,
                            "matching receipt already exists; no duplicate effect",
                            payload_fingerprint=fingerprint,
                        )
                    )
                else:
                    decisions.append(
                        ScheduleDecision(
                            candidate.action_id,
                            DecisionCode.HOLD_RECEIPT_CONFLICT_FAIL_CLOSED,
                            "action_id collides with a different receipt payload",
                            payload_fingerprint=fingerprint,
                        )
                    )
                continue

            decision = self._evaluate(candidate, working_receipts, now, fingerprint)
            decisions.append(decision)
            if decision.code == DecisionCode.ELIGIBLE_DRY_RUN and decision.due_at_utc:
                working_receipts.append(
                    EngagementReceipt(
                        action_id=candidate.action_id,
                        payload_fingerprint=fingerprint,
                        occurred_at_utc=decision.due_at_utc,
                        account_ref=candidate.account_ref,
                        thread_ref=candidate.thread_ref,
                        action_type=candidate.action_type,
                        text=candidate.text,
                        counts_against_budget=True,
                    )
                )

        counts = Counter(d.code for d in decisions)
        eligible = counts[DecisionCode.ELIGIBLE_DRY_RUN]
        manual = counts[DecisionCode.MANUAL_ACTION_PACKET]
        human = counts[DecisionCode.HUMAN_REVIEW_REQUIRED]
        held = len(decisions) - eligible - manual - human
        return SchedulerBatchReport(
            decisions=tuple(decisions),
            eligible_count=eligible,
            held_count=held,
            manual_count=manual,
            human_review_count=human,
        )

    def _evaluate(
        self,
        candidate: SchedulerCandidate,
        receipts: Sequence[EngagementReceipt],
        now: datetime,
        fingerprint: str,
    ) -> ScheduleDecision:
        invalid = _candidate_validation_error(candidate)
        if invalid:
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_INVALID_INPUT_FAIL_CLOSED,
                invalid,
                payload_fingerprint=fingerprint,
            )

        active_lanes = set(self.policy.get("active_lanes", ()))
        if candidate.platform not in active_lanes:
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_LANE_NOT_ACTIVE,
                "platform is not an active CP90 lane",
                payload_fingerprint=fingerprint,
            )

        forbidden = set(self.policy.get("forbidden_growth_mechanics", ()))
        if forbidden.intersection(candidate.behavior_tags):
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_POLICY_FORBIDDEN,
                "candidate contains a forbidden growth mechanic",
                payload_fingerprint=fingerprint,
            )

        if (
            candidate.conflict_risk
            or candidate.reputational_risk
            or candidate.ambiguous_political_persuasion
        ):
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HUMAN_REVIEW_REQUIRED,
                "conflict, reputational, or ambiguous political-persuasion risk",
                payload_fingerprint=fingerprint,
            )

        quality = _mapping(self.policy, "quality")
        if candidate.quality_score < float(quality["minimum_score"]):
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_LOW_QUALITY,
                "quality score is below the hard eligibility floor",
                payload_fingerprint=fingerprint,
            )

        retry = _mapping(self.policy, "retry")
        if candidate.retry_count >= int(retry["maximum_attempts"]):
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_RETRY_EXHAUSTED_FAIL_CLOSED,
                "bounded retry budget is exhausted",
                payload_fingerprint=fingerprint,
            )

        if candidate.capability_state == CapabilityState.HOLD_CAPABILITY_UNVERIFIED:
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_CAPABILITY_UNVERIFIED,
                "exact write capability is unknown or lacks readback evidence",
                payload_fingerprint=fingerprint,
            )
        if candidate.capability_state in {
            CapabilityState.MANUAL_ONLY,
            CapabilityState.UNSUPPORTED,
        }:
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.MANUAL_ACTION_PACKET,
                "automation is not legitimately available for this action",
                payload_fingerprint=fingerprint,
                manual_action_packet=(
                    "Review the prepared value-add action.",
                    "Perform it manually only if platform capability and policy permit.",
                    "Capture a real receipt/readback before recording completion.",
                ),
            )

        if candidate.requires_live_write:
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_KILL_SWITCH_ENGAGED,
                "kill switch is ENGAGED and live authority is NONE",
                payload_fingerprint=fingerprint,
            )

        publication = _as_utc(candidate.publication_time_utc)
        earliest = _as_utc(candidate.earliest_due_utc)
        hot = _mapping(self.policy, "hot_window")
        hot_end = publication + timedelta(minutes=int(hot["default_minutes"]))
        due = max(now, earliest, publication)
        if due > hot_end:
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_OUTSIDE_HOT_WINDOW,
                "candidate cannot be scheduled inside the bounded hot window",
                payload_fingerprint=fingerprint,
            )

        similar = self._find_similar(candidate.text, receipts)
        if similar is not None:
            return ScheduleDecision(
                candidate.action_id,
                DecisionCode.HOLD_SIMILARITY_DUPLICATE,
                f"same or semantically similar outgoing text already receipted: {similar.action_id}",
                payload_fingerprint=fingerprint,
            )

        cooldown = timedelta(minutes=int(quality["account_cooldown_minutes"]))
        account_times = [
            _as_utc(r.occurred_at_utc)
            for r in receipts
            if r.counts_against_budget and r.account_ref == candidate.account_ref
        ]
        if account_times:
            due = max(due, max(account_times) + cooldown)
            if due > hot_end:
                return ScheduleDecision(
                    candidate.action_id,
                    DecisionCode.HOLD_OUTSIDE_HOT_WINDOW,
                    "account cooldown pushes action beyond the bounded hot window",
                    payload_fingerprint=fingerprint,
                )

        budget_hold = self._budget_hold(candidate, receipts, due)
        if budget_hold is not None:
            return ScheduleDecision(
                candidate.action_id,
                budget_hold[0],
                budget_hold[1],
                payload_fingerprint=fingerprint,
            )

        return ScheduleDecision(
            candidate.action_id,
            DecisionCode.ELIGIBLE_DRY_RUN,
            "offline scheduling candidate satisfies CP90 gates; no write performed",
            due_at_utc=due,
            payload_fingerprint=fingerprint,
        )

    def _find_similar(
        self, text: str, receipts: Sequence[EngagementReceipt]
    ) -> EngagementReceipt | None:
        threshold = float(_mapping(self.policy, "quality")["semantic_similarity_threshold"])
        for receipt in receipts:
            if not receipt.counts_against_budget:
                continue
            if text_similarity(text, receipt.text) >= threshold:
                return receipt
        return None

    def _budget_hold(
        self,
        candidate: SchedulerCandidate,
        receipts: Sequence[EngagementReceipt],
        due: datetime,
    ) -> tuple[DecisionCode, str] | None:
        budgets = _mapping(self.policy, "hard_ceiling_budgets")
        quality = _mapping(self.policy, "quality")
        zone = _zone(candidate.timezone_name)
        due_local = due.astimezone(zone)
        day = due_local.date()
        week = due_local.isocalendar()[:2]
        counted = [r for r in receipts if r.counts_against_budget]

        daily = [r for r in counted if _as_utc(r.occurred_at_utc).astimezone(zone).date() == day]
        weekly = [
            r
            for r in counted
            if _as_utc(r.occurred_at_utc).astimezone(zone).isocalendar()[:2] == week
        ]
        if len(daily) >= int(budgets["global_daily"]):
            return DecisionCode.HOLD_RATE_BUDGET_DAILY, "global daily hard ceiling reached"
        if len(weekly) >= int(budgets["global_weekly"]):
            return DecisionCode.HOLD_RATE_BUDGET_WEEKLY, "global weekly hard ceiling reached"

        account_daily = [r for r in daily if r.account_ref == candidate.account_ref]
        if len(account_daily) >= int(budgets["per_account_daily"]):
            return DecisionCode.HOLD_ACCOUNT_RATE_BUDGET, "per-account daily hard ceiling reached"

        thread_window = timedelta(minutes=int(quality["thread_saturation_window_minutes"]))
        thread_recent = [
            r
            for r in counted
            if r.thread_ref == candidate.thread_ref
            and timedelta(0) <= due - _as_utc(r.occurred_at_utc) <= thread_window
        ]
        if len(thread_recent) >= int(budgets["per_thread_window"]):
            return DecisionCode.HOLD_THREAD_SATURATION, "thread saturation hard ceiling reached"

        if candidate.action_type == ActionType.OUTBOUND_VALUE_ADD:
            same_type = [r for r in daily if r.action_type == ActionType.OUTBOUND_VALUE_ADD]
            if len(same_type) >= int(budgets["outbound_value_add_daily"]):
                return DecisionCode.HOLD_RATE_BUDGET_DAILY, "outbound value-add daily hard ceiling reached"
        if candidate.action_type == ActionType.AMPLIFICATION:
            same_type = [r for r in daily if r.action_type == ActionType.AMPLIFICATION]
            if len(same_type) >= int(budgets["amplification_daily"]):
                return DecisionCode.HOLD_RATE_BUDGET_DAILY, "amplification daily hard ceiling reached"
        return None

    def _fair_order(self, candidates: Sequence[SchedulerCandidate]) -> tuple[SchedulerCandidate, ...]:
        priority = {
            ActionType.INBOUND_REPLY: 0,
            ActionType.OUTBOUND_VALUE_ADD: 1,
            ActionType.AMPLIFICATION: 2,
        }
        base = sorted(
            candidates,
            key=lambda c: (
                priority.get(c.action_type, 99),
                -float(c.quality_score),
                _safe_datetime_key(c.earliest_due_utc),
                c.action_id,
            ),
        )
        account_seen: defaultdict[str, int] = defaultdict(int)
        thread_seen: defaultdict[str, int] = defaultdict(int)
        decorated: list[tuple[int, tuple[object, ...], SchedulerCandidate]] = []
        for candidate in base:
            fairness_round = max(
                account_seen[candidate.account_ref],
                thread_seen[candidate.thread_ref],
            )
            account_seen[candidate.account_ref] += 1
            thread_seen[candidate.thread_ref] += 1
            base_key: tuple[object, ...] = (
                priority.get(candidate.action_type, 99),
                -float(candidate.quality_score),
                _safe_datetime_key(candidate.earliest_due_utc),
                candidate.action_id,
            )
            decorated.append((fairness_round, base_key, candidate))
        decorated.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in decorated)


def load_policy(path: Path | str | None = None) -> dict[str, object]:
    policy_path = Path(path) if path is not None else _DEFAULT_POLICY_PATH
    with policy_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("CP90 policy root must be an object")
    return data


def candidate_fingerprint(candidate: SchedulerCandidate) -> str:
    payload = {
        "action_id": candidate.action_id,
        "platform": candidate.platform,
        "account_ref": candidate.account_ref,
        "thread_ref": candidate.thread_ref,
        "action_type": candidate.action_type.value,
        "text": normalize_text(candidate.text),
        "publication_time_utc": _as_utc(candidate.publication_time_utc).isoformat(),
        "earliest_due_utc": _as_utc(candidate.earliest_due_utc).isoformat(),
        "timezone_name": candidate.timezone_name,
        "quality_score": round(float(candidate.quality_score), 8),
        "capability_state": candidate.capability_state.value,
        "requires_live_write": bool(candidate.requires_live_write),
        "retry_count": int(candidate.retry_count),
        "conflict_risk": bool(candidate.conflict_risk),
        "reputational_risk": bool(candidate.reputational_risk),
        "ambiguous_political_persuasion": bool(candidate.ambiguous_political_persuasion),
        "behavior_tags": sorted(candidate.behavior_tags),
        "provenance_ref": candidate.provenance_ref,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def text_similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if left_norm == right_norm:
        return 1.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _candidate_validation_error(candidate: SchedulerCandidate) -> str | None:
    if not candidate.action_id.strip():
        return "action_id is required"
    if not candidate.account_ref.strip() or not candidate.thread_ref.strip():
        return "account_ref and thread_ref are required"
    if not normalize_text(candidate.text):
        return "non-empty value-add text is required"
    if not 0.0 <= float(candidate.quality_score) <= 1.0:
        return "quality_score must be in [0,1]"
    if candidate.retry_count < 0:
        return "retry_count cannot be negative"
    try:
        _as_utc(candidate.publication_time_utc)
        _as_utc(candidate.earliest_due_utc)
        _zone(candidate.timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return "timestamps must be timezone-aware and timezone must be valid IANA"
    return None


def _mapping(root: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = root.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"policy.{key} must be an object")
    return value


def _zone(name: str) -> ZoneInfo:
    if not name:
        raise ValueError("timezone name is required")
    return ZoneInfo(name)


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _safe_datetime_key(value: datetime) -> datetime:
    try:
        return _as_utc(value)
    except (TypeError, ValueError):
        return datetime.max.replace(tzinfo=timezone.utc)
