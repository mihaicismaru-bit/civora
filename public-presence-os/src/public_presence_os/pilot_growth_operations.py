from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

_DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "pilot_growth_operations_shadow_plan_policy.json"
)

CHECKPOINT = "CP92"
MODULE_ID = "M61_PILOT_GROWTH_OPERATIONS_MANUAL_SHADOW_PILOT_PLAN"
PARENT_ACTIVATION_CHECKPOINT = "CP91"
PARENT_CONTROL_CHECKPOINT = "CP58"
MODE = "OFFLINE_SHADOW_PLAN_ONLY"
LIVE_AUTHORITY = "NONE"
UNKNOWN = "UNKNOWN"
ACTIVE_PLATFORMS = ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
REQUIRED_SUCCESS_CRITERIA = (
    "CAPABILITY_MATRIX_REVALIDATED_CURRENT",
    "READ_ONLY_PERMISSION_RECEIPTS_COMPLETE",
    "SHADOW_OBSERVATIONS_PRODUCE_RECOMMENDATIONS_WITH_ZERO_WRITES",
    "NO_UNSUPPORTED_ACTION_DRIFT",
    "MISSING_METRICS_REMAIN_UNKNOWN",
    "GROWTH_SAFETY_FILTERS_HOLD",
    "RATE_BUDGETS_TREATED_AS_CEILINGS",
    "AUDIT_RECEIPTS_COMPLETE",
)
FORBIDDEN_NOW = (
    "ACCOUNT_CONNECTION",
    "OAUTH",
    "TOKEN_OR_SECRET_RESOLUTION",
    "SOCIAL_API_TRAFFIC",
    "LIVE_PROBE",
    "EXTERNAL_WRITE",
    "PUBLISH",
    "DEPLOY",
    "PAID_SERVICE",
)


class PilotGrowthOperationsHold(ValueError):
    """Fail-closed CP92 plan-contract violation."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ManualActionPacket:
    packet_id: str
    platform: str
    purpose: str
    state: str
    required_evidence: tuple[str, ...]
    external_write_allowed: bool = False
    social_api_call_allowed: bool = False
    live_probe_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_evidence"] = list(self.required_evidence)
        return value


@dataclass(frozen=True)
class ShadowObservation:
    observation_ref: str
    platform: str
    event_type: str
    public_context: str
    capability_state: str = "PASS_OFFLINE_CONTRACT"
    source_mode: str = "SYNTHETIC_FIXTURE"
    metric_value: int | float | str | None = None


@dataclass(frozen=True)
class ShadowRecommendation:
    recommendation_id: str
    observation_ref: str
    platform: str
    recommendation_type: str
    state: str
    rationale: str
    metric_value: int | float | str
    human_review_required: bool = True
    external_write_allowed: bool = False
    social_api_call_allowed: bool = False
    live_probe_allowed: bool = False
    live_authority: str = LIVE_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowPilotEvidence:
    capability_matrix_revalidated_current: bool
    read_only_permission_receipts_complete: bool
    shadow_observations_recommendations_zero_writes: bool
    no_unsupported_action_drift: bool
    missing_metrics_remain_unknown: bool
    growth_safety_filters_hold: bool
    rate_budgets_are_ceilings: bool
    audit_receipts_complete: bool
    external_write_count: int = 0
    social_api_call_count: int = 0
    live_probe_count: int = 0
    oauth_count: int = 0
    account_connection_count: int = 0
    publish_count: int = 0
    deploy_count: int = 0
    paid_service_count: int = 0

    def criteria(self) -> dict[str, bool]:
        return {
            "CAPABILITY_MATRIX_REVALIDATED_CURRENT": self.capability_matrix_revalidated_current,
            "READ_ONLY_PERMISSION_RECEIPTS_COMPLETE": self.read_only_permission_receipts_complete,
            "SHADOW_OBSERVATIONS_PRODUCE_RECOMMENDATIONS_WITH_ZERO_WRITES":
                self.shadow_observations_recommendations_zero_writes,
            "NO_UNSUPPORTED_ACTION_DRIFT": self.no_unsupported_action_drift,
            "MISSING_METRICS_REMAIN_UNKNOWN": self.missing_metrics_remain_unknown,
            "GROWTH_SAFETY_FILTERS_HOLD": self.growth_safety_filters_hold,
            "RATE_BUDGETS_TREATED_AS_CEILINGS": self.rate_budgets_are_ceilings,
            "AUDIT_RECEIPTS_COMPLETE": self.audit_receipts_complete,
        }


def load_policy(path: Path | str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else _DEFAULT_POLICY_PATH
    value = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PilotGrowthOperationsHold("HOLD_CP92_POLICY_NOT_OBJECT")
    return value


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"),
        policy.get("checkpoint"),
        policy.get("module_id"),
        policy.get("parent_activation_checkpoint"),
        policy.get("parent_control_checkpoint"),
        policy.get("mode"),
        policy.get("global_kill_switch"),
        policy.get("live_authority"),
    )
    expected = (
        "PPOS_PILOT_GROWTH_OPERATIONS_SHADOW_PLAN_V1",
        CHECKPOINT,
        MODULE_ID,
        PARENT_ACTIVATION_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        MODE,
        "ENGAGED",
        LIVE_AUTHORITY,
    )
    if identity != expected:
        raise PilotGrowthOperationsHold("HOLD_CP92_POLICY_IDENTITY_DRIFT")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise PilotGrowthOperationsHold("HOLD_CP92_ACTIVE_PLATFORM_DRIFT")

    lane_states = policy.get("lane_states")
    if not isinstance(lane_states, Mapping):
        raise PilotGrowthOperationsHold("HOLD_CP92_LANE_STATES_MISSING")
    if lane_states.get("LINKEDIN") != "HOLD_PRODUCTION_API_ACCESS":
        raise PilotGrowthOperationsHold("HOLD_CP92_LINKEDIN_GATE_WEAKENED")
    if lane_states.get("X") != "EXCLUDED_PAID_API":
        raise PilotGrowthOperationsHold("HOLD_CP92_X_GATE_WEAKENED")
    if lane_states.get("BLUESKY") != "HOLD_ROI":
        raise PilotGrowthOperationsHold("HOLD_CP92_BLUESKY_GATE_WEAKENED")

    setup = policy.get("operator_setup")
    if not isinstance(setup, Mapping):
        raise PilotGrowthOperationsHold("HOLD_CP92_OPERATOR_SETUP_MISSING")
    if setup.get("permission_validation_mode") != (
        "MANUAL_ACTION_PACKET_UNTIL_EXPLICIT_PILOT_AUTHORIZATION"
    ):
        raise PilotGrowthOperationsHold("HOLD_CP92_PERMISSION_VALIDATION_MODE_DRIFT")
    if tuple(setup.get("forbidden_now", ())) != FORBIDDEN_NOW:
        raise PilotGrowthOperationsHold("HOLD_CP92_FORBIDDEN_BOUNDARY_DRIFT")

    shadow = policy.get("shadow_pilot")
    if (
        not isinstance(shadow, Mapping)
        or shadow.get("execution_state") != "HOLD_SHADOW_PILOT_NOT_AUTHORIZED"
        or shadow.get("recommendation_only") is not True
        or shadow.get("human_review_required") is not True
        or shadow.get("external_write_allowed") is not False
        or shadow.get("public_publish_allowed") is not False
        or shadow.get("unsupported_action_state") != "HOLD_CAPABILITY_UNVERIFIED"
        or shadow.get("unsupported_action_fallback") != "MANUAL_ACTION_PACKET"
        or shadow.get("unknown_metric_value") != UNKNOWN
    ):
        raise PilotGrowthOperationsHold("HOLD_CP92_SHADOW_BOUNDARY_WEAKENED")

    if tuple(policy.get("success_criteria", ())) != REQUIRED_SUCCESS_CRITERIA:
        raise PilotGrowthOperationsHold("HOLD_CP92_SUCCESS_CRITERIA_DRIFT")

    authorization = policy.get("authorization")
    if (
        not isinstance(authorization, Mapping)
        or authorization.get(
            "explicit_owner_authorization_required_before_first_real_reply_comment_publish"
        ) is not True
        or authorization.get("authorization_captured") is not False
    ):
        raise PilotGrowthOperationsHold("HOLD_CP92_AUTHORIZATION_GATE_WEAKENED")

    future = policy.get("future_write_contract")
    if not isinstance(future, Mapping) or not future or not all(
        future.get(key) is True
        for key in (
            "kill_switch_bound",
            "receipt_bound",
            "idempotent",
            "bounded_retry",
            "retry_exhaustion_fail_closed",
        )
    ):
        raise PilotGrowthOperationsHold("HOLD_CP92_FUTURE_WRITE_CONTRACT_WEAKENED")


def build_operator_setup_packet(
    policy: Mapping[str, Any],
    *,
    platform: str,
) -> ManualActionPacket:
    """Prepare future read-only validation work without performing any connection or API call."""
    validate_policy(policy)
    if platform not in ACTIVE_PLATFORMS:
        raise PilotGrowthOperationsHold("HOLD_CAPABILITY_UNVERIFIED")
    stable = {
        "checkpoint": CHECKPOINT,
        "platform": platform,
        "purpose": "READ_ONLY_ENGAGEMENT_PERMISSION_VALIDATION",
        "kill_switch": "ENGAGED",
        "live_authority": LIVE_AUTHORITY,
    }
    return ManualActionPacket(
        packet_id=f"cp92-manual-{_hash(stable)[:20]}",
        platform=platform,
        purpose="READ_ONLY_ENGAGEMENT_PERMISSION_VALIDATION",
        state="MANUAL_ACTION_PACKET_AUTHORIZATION_REQUIRED",
        required_evidence=(
            "OFFICIAL_CAPABILITY_SURFACE_REVALIDATED",
            "READ_ONLY_PERMISSION_SCOPE_CAPTURED",
            "OBJECT_LEVEL_READBACK_CAPTURED_WHERE_APPLICABLE",
            "ZERO_WRITE_AUTHORITY_CONFIRMED",
            "KILL_SWITCH_ENGAGED_CONFIRMED",
        ),
    )


def recommend_from_shadow_observation(
    policy: Mapping[str, Any],
    observation: ShadowObservation,
) -> ShadowRecommendation | ManualActionPacket:
    """Generate a recommendation from a synthetic shadow fixture; never dispatch."""
    validate_policy(policy)
    if observation.platform not in ACTIVE_PLATFORMS:
        raise PilotGrowthOperationsHold("HOLD_CAPABILITY_UNVERIFIED")
    if not observation.observation_ref or not observation.public_context.strip():
        raise PilotGrowthOperationsHold("HOLD_CP92_OBSERVATION_IDENTITY_MISSING")
    if observation.source_mode != "SYNTHETIC_FIXTURE":
        raise PilotGrowthOperationsHold("HOLD_CP92_LIVE_SHADOW_OBSERVATION_NOT_AUTHORIZED")

    if observation.capability_state not in {
        "PASS_OFFLINE_CONTRACT",
        "HOLD_LIVE_PERMISSION",
        "MANUAL_ONLY",
        "UNSUPPORTED",
        "HOLD_CAPABILITY_UNVERIFIED",
    }:
        raise PilotGrowthOperationsHold("HOLD_CP92_CAPABILITY_STATE_INVALID")
    if observation.capability_state != "PASS_OFFLINE_CONTRACT":
        stable = {
            "checkpoint": CHECKPOINT,
            "platform": observation.platform,
            "observation_ref": observation.observation_ref,
            "capability_state": observation.capability_state,
        }
        return ManualActionPacket(
            packet_id=f"cp92-manual-{_hash(stable)[:20]}",
            platform=observation.platform,
            purpose=f"SHADOW_RECOMMENDATION_{observation.event_type}",
            state=(
                "HOLD_CAPABILITY_UNVERIFIED"
                if observation.capability_state in {"UNSUPPORTED", "HOLD_CAPABILITY_UNVERIFIED"}
                else "MANUAL_ACTION_PACKET"
            ),
            required_evidence=(
                "EXACT_OFFICIAL_CAPABILITY_VERIFIED",
                "READBACKABLE_PERMISSION_RECEIPT",
                "EXPLICIT_PILOT_AUTHORIZATION",
            ),
        )

    event_map = {
        "QUESTION": ("DRAFT_INBOUND_REPLY", "Answer the concrete question with fact-bound context."),
        "CORRECTION": ("DRAFT_CORRECTION_RESPONSE", "Verify the correction and propose a concise evidence-bound response."),
        "COUNTERPOINT": ("DRAFT_RESPECTFUL_COUNTERPOINT", "Add material context without manufacturing conflict."),
        "EXPERT_LEAD": ("ESCALATE_EXPERT_LEAD", "Preserve the useful lead for human review and relationship continuity."),
        "MENTION": ("REVIEW_MENTION", "Assess whether a useful contextual response is warranted."),
        "LOW_VALUE": ("NO_ENGAGEMENT", "No material information, clarity, trust, continuity, discoverability, or depth gain."),
        "ABUSE_SPAM": ("NO_ENGAGEMENT", "Terminal no-engagement state for abuse/spam."),
    }
    recommendation_type, rationale = event_map.get(
        observation.event_type,
        ("HUMAN_REVIEW", "Unrecognized event type requires human review; no automated write."),
    )
    metric = UNKNOWN if observation.metric_value is None else observation.metric_value
    stable = {
        "checkpoint": CHECKPOINT,
        "observation_ref": observation.observation_ref,
        "platform": observation.platform,
        "event_type": observation.event_type,
        "recommendation_type": recommendation_type,
        "metric": metric,
    }
    return ShadowRecommendation(
        recommendation_id=f"cp92-rec-{_hash(stable)[:20]}",
        observation_ref=observation.observation_ref,
        platform=observation.platform,
        recommendation_type=recommendation_type,
        state="RECOMMENDATION_ONLY_HUMAN_REVIEW",
        rationale=rationale,
        metric_value=metric,
    )


def evaluate_offline_shadow_rehearsal(
    policy: Mapping[str, Any],
    evidence: ShadowPilotEvidence,
) -> dict[str, Any]:
    """Evaluate only offline plan rehearsal evidence; this never marks a real shadow pilot complete."""
    validate_policy(policy)
    counts = (
        evidence.external_write_count,
        evidence.social_api_call_count,
        evidence.live_probe_count,
        evidence.oauth_count,
        evidence.account_connection_count,
        evidence.publish_count,
        evidence.deploy_count,
        evidence.paid_service_count,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        raise PilotGrowthOperationsHold("HOLD_CP92_IO_COUNT_INVALID")
    if any(counts):
        raise PilotGrowthOperationsHold("HOLD_CP92_EXTERNAL_IO_OBSERVED")

    criteria = evidence.criteria()
    if tuple(criteria) != REQUIRED_SUCCESS_CRITERIA:
        raise PilotGrowthOperationsHold("HOLD_CP92_EVIDENCE_CRITERIA_DRIFT")
    passed = sum(1 for value in criteria.values() if value)
    failed = len(criteria) - passed
    report_core = {
        "checkpoint": CHECKPOINT,
        "global_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "criteria": criteria,
        "zero_external_io": True,
        "kill_switch": "ENGAGED",
        "live_authority": LIVE_AUTHORITY,
        "shadow_pilot_completed": False,
        "authorization_captured": False,
    }
    digest = _hash(report_core)
    return {
        "report_id": f"cp92-rehearsal-{digest[:20]}",
        "report_hash": digest,
        "overall_state": (
            "PASS_CP92_OFFLINE_SHADOW_PLAN_REHEARSAL"
            if failed == 0
            else "HOLD_CP92_OFFLINE_SHADOW_PLAN_REHEARSAL_INCOMPLETE"
        ),
        "passed_count": passed,
        "failed_count": failed,
        "criteria": criteria,
        "global_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "checkpoint": CHECKPOINT,
        "mode": MODE,
        "global_kill_switch_engaged": True,
        "live_authority": LIVE_AUTHORITY,
        "shadow_pilot_completed": False,
        "authorization_captured": False,
        "external_metrics": UNKNOWN,
        "external_write_performed": False,
        "social_api_call_performed": False,
        "live_probe_performed": False,
    }


def build_rollback_packet(policy: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    validate_policy(policy)
    if not reason or not reason.strip():
        raise PilotGrowthOperationsHold("HOLD_CP92_ROLLBACK_REASON_REQUIRED")
    stable = {"checkpoint": CHECKPOINT, "reason": reason.strip(), "kill_switch": "ENGAGED"}
    digest = _hash(stable)
    return {
        "rollback_id": f"cp92-rollback-{digest[:20]}",
        "state": "ROLLBACK_SHADOW_PLAN_STOP_AND_HOLD",
        "reason": reason.strip(),
        "actions": [
            "STOP_SHADOW_OBSERVATION_PLAN",
            "PRESERVE_AUDIT_EVIDENCE",
            "INVALIDATE_UNVERIFIED_CAPABILITY_ASSUMPTIONS",
            "KEEP_KILL_SWITCH_ENGAGED",
            "KEEP_LIVE_AUTHORITY_NONE",
            "REQUIRE_FRESH_OWNER_AUTHORIZATION_BEFORE_ANY_FUTURE_LIVE_STEP",
        ],
        "external_write_allowed": False,
    }
