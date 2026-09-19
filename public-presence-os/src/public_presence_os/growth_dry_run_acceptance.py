from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from public_presence_os.engagement_scheduler import EngagementScheduler


_DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "growth_dry_run_acceptance_policy.json"
)

CHECKPOINT = "CP91"
MODULE_ID = "M60_GROWTH_DRY_RUN_ACCEPTANCE_SUITE"
PARENT_ACTIVATION_CHECKPOINT = "CP90"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP92_PILOT_GROWTH_OPERATIONS_MANUAL_SHADOW_PILOT_PLAN"
MODE = "OFFLINE_SYNTHETIC_ONLY"
LIVE_AUTHORITY = "NONE"
UNKNOWN_EXTERNAL_METRIC_VALUE = "UNKNOWN"
ACTIVE_PLATFORMS = ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
REQUIRED_ACCEPTANCE_CASES = (
    "PUBLICATION_MONITOR_TASKS",
    "INBOUND_RANKING_AND_DRY_RUN_REPLY",
    "OUTBOUND_SCORING_LOW_VALUE_SPAM_REJECTION",
    "RELATIONSHIP_GRAPH_IDEMPOTENT",
    "DUPLICATE_ACTIONS_IMPOSSIBLE",
    "RATE_CEILINGS_ENFORCED",
    "KILL_SWITCH_SUPPRESSES_WRITE_PATHS",
    "UNSUPPORTED_CAPABILITY_MANUAL_OR_HOLD",
    "MISSING_ANALYTICS_REMAIN_UNKNOWN",
)


class GrowthDryRunAcceptanceHold(ValueError):
    """Fail-closed CP91 acceptance-contract violation."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EngagementMonitorTask:
    task_id: str
    publication_ref: str
    platform: str
    account_ref: str
    due_at_utc: str
    due_at_local: str
    action: str = "ENGAGEMENT_MONITOR_DRY_RUN"
    external_write_allowed: bool = False
    social_api_call_allowed: bool = False
    live_probe_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceEvidence:
    publication_monitor_tasks: bool
    inbound_ranking_and_dry_run_reply: bool
    outbound_scoring_low_value_spam_rejection: bool
    relationship_graph_idempotent: bool
    duplicate_actions_impossible: bool
    rate_ceilings_enforced: bool
    kill_switch_suppresses_write_paths: bool
    unsupported_capability_manual_or_hold: bool
    missing_analytics_remain_unknown: bool
    external_write_count: int = 0
    social_api_call_count: int = 0
    live_probe_count: int = 0
    oauth_count: int = 0
    account_connection_count: int = 0
    publish_count: int = 0
    deploy_count: int = 0
    paid_service_count: int = 0

    def case_results(self) -> dict[str, bool]:
        return {
            "PUBLICATION_MONITOR_TASKS": self.publication_monitor_tasks,
            "INBOUND_RANKING_AND_DRY_RUN_REPLY": self.inbound_ranking_and_dry_run_reply,
            "OUTBOUND_SCORING_LOW_VALUE_SPAM_REJECTION": self.outbound_scoring_low_value_spam_rejection,
            "RELATIONSHIP_GRAPH_IDEMPOTENT": self.relationship_graph_idempotent,
            "DUPLICATE_ACTIONS_IMPOSSIBLE": self.duplicate_actions_impossible,
            "RATE_CEILINGS_ENFORCED": self.rate_ceilings_enforced,
            "KILL_SWITCH_SUPPRESSES_WRITE_PATHS": self.kill_switch_suppresses_write_paths,
            "UNSUPPORTED_CAPABILITY_MANUAL_OR_HOLD": self.unsupported_capability_manual_or_hold,
            "MISSING_ANALYTICS_REMAIN_UNKNOWN": self.missing_analytics_remain_unknown,
        }


@dataclass(frozen=True)
class AcceptanceCaseResult:
    case_id: str
    passed: bool
    state: str


@dataclass(frozen=True)
class GrowthDryRunAcceptanceReport:
    report_id: str
    report_hash: str
    cases: tuple[AcceptanceCaseResult, ...]
    passed_count: int
    failed_count: int
    overall_state: str
    global_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    checkpoint: str = CHECKPOINT
    parent_activation_checkpoint: str = PARENT_ACTIVATION_CHECKPOINT
    next_unit: str = NEXT_UNIT
    mode: str = MODE
    global_kill_switch_engaged: bool = True
    live_authority: str = LIVE_AUTHORITY
    external_metrics: str = UNKNOWN_EXTERNAL_METRIC_VALUE
    external_write_allowed: bool = False
    external_write_performed: bool = False
    social_api_call_allowed: bool = False
    social_api_call_performed: bool = False
    live_probe_allowed: bool = False
    live_probe_performed: bool = False
    oauth_allowed: bool = False
    account_connection_allowed: bool = False
    publish_allowed: bool = False
    deploy_allowed: bool = False
    paid_service_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["cases"] = [asdict(item) for item in self.cases]
        return value


def load_policy(path: Path | str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else _DEFAULT_POLICY_PATH
    value = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_POLICY_NOT_OBJECT")
    return value


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"),
        policy.get("checkpoint"),
        policy.get("module_id"),
        policy.get("parent_activation_checkpoint"),
        policy.get("parent_control_checkpoint"),
        policy.get("next_after_cp91"),
        policy.get("mode"),
        policy.get("global_kill_switch"),
        policy.get("live_authority"),
    )
    expected = (
        "PPOS_GROWTH_DRY_RUN_ACCEPTANCE_POLICY_V1",
        CHECKPOINT,
        MODULE_ID,
        PARENT_ACTIVATION_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        NEXT_UNIT,
        MODE,
        "ENGAGED",
        LIVE_AUTHORITY,
    )
    if identity != expected:
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_POLICY_IDENTITY_DRIFT")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_acceptance_cases", ())) != REQUIRED_ACCEPTANCE_CASES:
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_ACCEPTANCE_CASE_DRIFT")

    monitor = policy.get("monitor_task_defaults")
    if not isinstance(monitor, Mapping):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_MONITOR_POLICY_MISSING")
    window = monitor.get("window_minutes")
    interval = monitor.get("interval_minutes")
    minimum = monitor.get("minimum_task_count")
    if (
        isinstance(window, bool)
        or not isinstance(window, int)
        or not 120 <= window <= 240
        or isinstance(interval, bool)
        or not isinstance(interval, int)
        or not 15 <= interval <= 60
        or isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum < 2
    ):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_MONITOR_POLICY_INVALID")

    truthfulness = policy.get("truthfulness")
    if (
        not isinstance(truthfulness, Mapping)
        or truthfulness.get("unknown_external_metric_value") != UNKNOWN_EXTERNAL_METRIC_VALUE
        or truthfulness.get("missing_is_never_zero") is not True
        or truthfulness.get("no_fabricated_external_state") is not True
    ):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_TRUTHFULNESS_WEAKENED")

    safety = policy.get("growth_safety")
    if not isinstance(safety, Mapping) or not safety or not all(value is True for value in safety.values()):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_GROWTH_SAFETY_WEAKENED")

    boundary = policy.get("write_boundary")
    if not isinstance(boundary, Mapping):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_WRITE_BOUNDARY_MISSING")
    for key in (
        "external_write",
        "social_api_call",
        "oauth",
        "token_or_secret_resolution",
        "live_probe",
        "account_connection",
        "publish",
        "deploy",
        "paid_service",
    ):
        if boundary.get(key) is not False:
            raise GrowthDryRunAcceptanceHold("HOLD_CP91_LIVE_AUTHORITY_DRIFT")
    for key in (
        "future_writes_must_be_kill_switch_bound",
        "future_writes_must_be_receipt_bound",
        "future_writes_must_be_idempotent",
        "future_writes_must_have_bounded_retry",
        "retry_exhaustion_must_fail_closed",
    ):
        if boundary.get(key) is not True:
            raise GrowthDryRunAcceptanceHold("HOLD_CP91_FUTURE_WRITE_SAFETY_WEAKENED")


def build_engagement_monitor_tasks(
    policy: Mapping[str, Any],
    scheduler_policy: Mapping[str, Any],
    *,
    publication_ref: str,
    platform: str,
    account_ref: str,
    publication_time_utc: datetime,
    timezone_name: str,
) -> tuple[EngagementMonitorTask, ...]:
    """Turn one synthetic publication into bounded monitor tasks without any I/O."""
    validate_policy(policy)
    if platform not in ACTIVE_PLATFORMS:
        raise GrowthDryRunAcceptanceHold("HOLD_CAPABILITY_UNVERIFIED")
    if not publication_ref or not account_ref:
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_MONITOR_IDENTITY_MISSING")

    monitor = policy["monitor_task_defaults"]
    scheduler = EngagementScheduler(scheduler_policy)
    slots = scheduler.build_poll_plan(
        publication_time_utc,
        timezone_name,
        window_minutes=int(monitor["window_minutes"]),
        interval_minutes=int(monitor["interval_minutes"]),
    )
    if len(slots) < int(monitor["minimum_task_count"]):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_MONITOR_TASK_COUNT_BELOW_FLOOR")

    tasks: list[EngagementMonitorTask] = []
    for index, slot in enumerate(slots):
        payload = {
            "publication_ref": publication_ref,
            "platform": platform,
            "account_ref": account_ref,
            "slot_utc": slot.utc.isoformat(),
            "index": index,
        }
        tasks.append(
            EngagementMonitorTask(
                task_id=f"cp91-monitor-{_hash(payload)[:20]}",
                publication_ref=publication_ref,
                platform=platform,
                account_ref=account_ref,
                due_at_utc=slot.utc.isoformat(),
                due_at_local=slot.local.isoformat(),
            )
        )
    return tuple(tasks)


def evaluate_acceptance(
    policy: Mapping[str, Any],
    evidence: AcceptanceEvidence,
    *,
    report_ref: str = "cp91-growth-dry-run-acceptance",
) -> GrowthDryRunAcceptanceReport:
    validate_policy(policy)
    if not report_ref or not isinstance(report_ref, str):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_REPORT_REF_INVALID")

    io_counts = (
        evidence.external_write_count,
        evidence.social_api_call_count,
        evidence.live_probe_count,
        evidence.oauth_count,
        evidence.account_connection_count,
        evidence.publish_count,
        evidence.deploy_count,
        evidence.paid_service_count,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in io_counts):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_IO_COUNT_INVALID")
    if any(io_counts):
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_EXTERNAL_IO_OBSERVED")

    case_map = evidence.case_results()
    if tuple(case_map) != REQUIRED_ACCEPTANCE_CASES:
        raise GrowthDryRunAcceptanceHold("HOLD_CP91_ACCEPTANCE_EVIDENCE_DRIFT")
    cases = tuple(
        AcceptanceCaseResult(
            case_id=case_id,
            passed=bool(case_map[case_id]),
            state="PASS_OFFLINE_SYNTHETIC" if case_map[case_id] else "HOLD_ACCEPTANCE_FAILED",
        )
        for case_id in REQUIRED_ACCEPTANCE_CASES
    )
    passed = sum(1 for item in cases if item.passed)
    failed = len(cases) - passed
    stable = {
        "report_ref": report_ref,
        "checkpoint": CHECKPOINT,
        "parent_activation_checkpoint": PARENT_ACTIVATION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "case_results": {item.case_id: item.passed for item in cases},
        "zero_external_io": True,
        "kill_switch": "ENGAGED",
        "live_authority": LIVE_AUTHORITY,
    }
    report_hash = _hash(stable)
    return GrowthDryRunAcceptanceReport(
        report_id=f"cp91-{report_hash[:20]}",
        report_hash=report_hash,
        cases=cases,
        passed_count=passed,
        failed_count=failed,
        overall_state=(
            "PASS_CP91_OFFLINE_SYNTHETIC_ACCEPTANCE"
            if failed == 0
            else "HOLD_CP91_ACCEPTANCE_INCOMPLETE"
        ),
    )
