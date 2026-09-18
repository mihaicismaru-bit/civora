from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from statistics import mean, median
from typing import Iterable

from .control import EXPECTED_ACTIVE, canonical_json

GROWTH_ANALYTICS_MODEL_VERSION = "PPOS_GROWTH_ANALYTICS_VIRALITY_LEARNING_V1"
GROWTH_ANALYTICS_ENGINE_VERSION = "ppos-growth-analytics-virality-learning-v1.0.0"

CORE_METRICS = (
    "engagement_per_reached_user",
    "meaningful_comment_rate",
    "reply_rate",
    "median_first_reply_latency",
    "conversation_depth",
    "repeat_engager_rate",
    "profile_visit_rate",
    "follower_conversion_rate",
    "outbound_comment_response_rate",
    "relationship_reactivation_rate",
    "amplification_yield",
    "topic_to_growth_attribution",
)

VIRALITY_COMPONENTS = (
    "topic_selection",
    "packaging",
    "early_engagement",
    "network_propagation",
)

COUNT_FIELDS = (
    "reach",
    "impressions",
    "engaged_users",
    "comments",
    "meaningful_comments",
    "replies",
    "response_opportunities",
    "repeat_engagers",
    "profile_visits",
    "follows",
    "outbound_comments",
    "outbound_comments_with_response",
    "eligible_dormant_relationships",
    "reactivated_relationships",
    "amplification_candidates",
    "successful_amplifications",
)

SCORE_FIELDS = (
    "topic_selection_score",
    "packaging_score",
    "early_engagement_score",
    "network_propagation_score",
)


class GrowthAnalyticsError(ValueError):
    pass


class GrowthAnalyticsHold(GrowthAnalyticsError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GrowthAnalyticsContract:
    checkpoint: str
    module_id: str
    parent_activation_checkpoint: str
    parent_control_checkpoint: str
    next_unit: str
    active_platforms: tuple[str, ...]
    core_metrics: tuple[str, ...]
    virality_components: tuple[str, ...]
    virality_weights: dict[str, float]
    max_batch: int
    global_kill_switch_engaged: bool
    unknown_external_metric_value: str
    external_metric_fetch_allowed: bool
    external_write_allowed: bool
    network_allowed: bool
    live_probe_allowed: bool
    oauth_allowed: bool
    account_connection_allowed: bool
    posting_authority: bool
    strategy_mutation_authority: bool
    control_plane_promoted: bool
    deploy_allowed: bool
    paid_service_allowed: bool


@dataclass(frozen=True)
class MetricValue:
    name: str
    state: str
    value: float | int | None
    unit: str
    known_observations: int
    total_observations: int
    reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GrowthObservation:
    platform: str
    observation_ref: str
    topic: str
    observed_at_utc: str
    provenance_ref: str
    evidence_class: str = "SYNTHETIC_OFFLINE"
    source_is_public: bool = True
    aggregate_content_level_only: bool = True
    reach: int | None = None
    impressions: int | None = None
    engaged_users: int | None = None
    comments: int | None = None
    meaningful_comments: int | None = None
    replies: int | None = None
    response_opportunities: int | None = None
    first_reply_latencies_seconds: tuple[float, ...] = ()
    conversation_depth_samples: tuple[float, ...] = ()
    repeat_engagers: int | None = None
    profile_visits: int | None = None
    follows: int | None = None
    outbound_comments: int | None = None
    outbound_comments_with_response: int | None = None
    eligible_dormant_relationships: int | None = None
    reactivated_relationships: int | None = None
    amplification_candidates: int | None = None
    successful_amplifications: int | None = None
    topic_selection_score: float | None = None
    packaging_score: float | None = None
    early_engagement_score: float | None = None
    network_propagation_score: float | None = None
    person_level_identifiers_present: bool = False
    sensitive_trait_data_present: bool = False
    sensitive_trait_inference_requested: bool = False
    sensitive_relationship_profiling_requested: bool = False
    political_microtargeting_requested: bool = False
    synthetic_conversation_farming_requested: bool = False
    clickbait_optimization_requested: bool = False
    conflict_fabrication_requested: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ViralityLearningPacket:
    observation_ref: str
    topic: str
    state: str
    component_scores: dict[str, MetricValue]
    observed_signal_score: MetricValue
    attribution_mode: str
    recommendations: tuple[str, ...]
    causal_claim_allowed: bool = False
    automatic_strategy_mutation_allowed: bool = False
    external_write_allowed: bool = False
    network_attempted: bool = False
    posting_authority: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["component_scores"] = {
            key: value.to_dict() for key, value in self.component_scores.items()
        }
        data["observed_signal_score"] = self.observed_signal_score.to_dict()
        return data


@dataclass(frozen=True)
class ObservationAnalytics:
    observation_ref: str
    observation_hash: str
    platform: str
    topic: str
    evidence_class: str
    metrics: dict[str, MetricValue]
    virality_learning: ViralityLearningPacket
    external_metric_state: str = "UNKNOWN_WHERE_UNAVAILABLE"
    causal_attribution_allowed: bool = False
    strategy_mutation_authority: bool = False
    external_write_allowed: bool = False
    network_attempted: bool = False
    posting_authority: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["metrics"] = {key: value.to_dict() for key, value in self.metrics.items()}
        data["virality_learning"] = self.virality_learning.to_dict()
        return data


@dataclass(frozen=True)
class TopicGrowthAttribution:
    topic: str
    observation_count: int
    metric_profile: dict[str, MetricValue]
    attribution_mode: str = "DESCRIPTIVE_NON_CAUSAL"
    causal_claim_allowed: bool = False

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "observation_count": self.observation_count,
            "metric_profile": {
                key: value.to_dict() for key, value in self.metric_profile.items()
            },
            "attribution_mode": self.attribution_mode,
            "causal_claim_allowed": self.causal_claim_allowed,
        }


@dataclass(frozen=True)
class GrowthAnalyticsReport:
    report_id: str
    report_hash: str
    model_version: str
    engine_version: str
    report_ref: str
    observation_count: int
    observed_at_min_utc: str
    observed_at_max_utc: str
    funnel: dict[str, MetricValue]
    core_metrics: dict[str, MetricValue]
    topic_to_growth_attribution: tuple[TopicGrowthAttribution, ...]
    virality_learning_packets: tuple[ViralityLearningPacket, ...]
    evidence_classes: tuple[str, ...]
    external_metric_state: str
    learning_mode: str
    global_kill_switch: str = "ENGAGED"
    aggregate_content_level_only: bool = True
    person_level_profiling_allowed: bool = False
    sensitive_profiling_allowed: bool = False
    causal_attribution_allowed: bool = False
    automatic_strategy_mutation_allowed: bool = False
    external_metric_fetch_allowed: bool = False
    external_write_allowed: bool = False
    network_attempted: bool = False
    live_probe_attempted: bool = False
    account_connected: bool = False
    posting_authority: bool = False
    deploy_authority: bool = False
    paid_service_used: bool = False
    state: str = "CP89_OFFLINE_GROWTH_ANALYTICS_REPORT_ONLY"

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "report_hash": self.report_hash,
            "model_version": self.model_version,
            "engine_version": self.engine_version,
            "report_ref": self.report_ref,
            "observation_count": self.observation_count,
            "observed_at_min_utc": self.observed_at_min_utc,
            "observed_at_max_utc": self.observed_at_max_utc,
            "funnel": {key: value.to_dict() for key, value in self.funnel.items()},
            "core_metrics": {key: value.to_dict() for key, value in self.core_metrics.items()},
            "topic_to_growth_attribution": [item.to_dict() for item in self.topic_to_growth_attribution],
            "virality_learning_packets": [item.to_dict() for item in self.virality_learning_packets],
            "evidence_classes": list(self.evidence_classes),
            "external_metric_state": self.external_metric_state,
            "learning_mode": self.learning_mode,
            "global_kill_switch": self.global_kill_switch,
            "aggregate_content_level_only": self.aggregate_content_level_only,
            "person_level_profiling_allowed": self.person_level_profiling_allowed,
            "sensitive_profiling_allowed": self.sensitive_profiling_allowed,
            "causal_attribution_allowed": self.causal_attribution_allowed,
            "automatic_strategy_mutation_allowed": self.automatic_strategy_mutation_allowed,
            "external_metric_fetch_allowed": self.external_metric_fetch_allowed,
            "external_write_allowed": self.external_write_allowed,
            "network_attempted": self.network_attempted,
            "live_probe_attempted": self.live_probe_attempted,
            "account_connected": self.account_connected,
            "posting_authority": self.posting_authority,
            "deploy_authority": self.deploy_authority,
            "paid_service_used": self.paid_service_used,
            "state": self.state,
        }


@dataclass
class GrowthAnalyticsState:
    provenance_receipts: dict[str, tuple[str, ObservationAnalytics]] = field(default_factory=dict)
    observation_receipts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provenance_receipts": {
                key: {"observation_hash": value[0], "result": value[1].to_dict()}
                for key, value in sorted(self.provenance_receipts.items())
            },
            "observation_receipts": dict(sorted(self.observation_receipts.items())),
        }


def _parse_iso(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise GrowthAnalyticsHold("HOLD_CP89_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None:
        raise GrowthAnalyticsHold("HOLD_CP89_TIMESTAMP_INVALID")
    return dt.astimezone(timezone.utc)


def _iso(value: str) -> str:
    return _parse_iso(value).isoformat().replace("+00:00", "Z")


def _hash(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_GROWTH_ANALYTICS_VIRALITY_LEARNING_POLICY_V1":
        raise GrowthAnalyticsHold("HOLD_CP89_POLICY_VERSION")
    expected_identity = {
        "checkpoint": "CP89",
        "module_id": "M58_GROWTH_ANALYTICS_VIRALITY_LEARNING",
        "parent_activation_checkpoint": "CP88",
        "parent_control_checkpoint": "CP58",
        "next_after_cp89": "CP90_ENGAGEMENT_SCHEDULER_RATE_QUALITY_BUDGET",
        "global_kill_switch": "ENGAGED",
        "unknown_external_metric_value": "UNKNOWN",
    }
    for key, expected in expected_identity.items():
        if policy.get(key) != expected:
            raise GrowthAnalyticsHold(f"HOLD_CP89_POLICY_IDENTITY_DRIFT:{key}")
    if set(policy.get("active_platforms", ())) != set(EXPECTED_ACTIVE):
        raise GrowthAnalyticsHold("HOLD_CP89_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("core_metrics", ())) != CORE_METRICS:
        raise GrowthAnalyticsHold("HOLD_CP89_CORE_METRIC_DRIFT")

    virality = policy.get("virality_learning", {})
    if tuple(virality.get("components", ())) != VIRALITY_COMPONENTS:
        raise GrowthAnalyticsHold("HOLD_CP89_VIRALITY_COMPONENT_DRIFT")
    weights = virality.get("weights", {})
    if set(weights) != set(VIRALITY_COMPONENTS):
        raise GrowthAnalyticsHold("HOLD_CP89_VIRALITY_WEIGHT_DRIFT")
    try:
        total_weight = sum(float(weights[name]) for name in VIRALITY_COMPONENTS)
    except (TypeError, ValueError) as exc:
        raise GrowthAnalyticsHold("HOLD_CP89_VIRALITY_WEIGHT_DRIFT") from exc
    if abs(total_weight - 1.0) > 1e-9 or any(float(weights[name]) <= 0 for name in VIRALITY_COMPONENTS):
        raise GrowthAnalyticsHold("HOLD_CP89_VIRALITY_WEIGHT_DRIFT")
    if virality.get("mode") != "OBSERVATIONAL_NON_CAUSAL":
        raise GrowthAnalyticsHold("HOLD_CP89_CAUSALITY_POLICY_WEAKENED")
    if virality.get("all_components_required_for_observed_signal_score") is not True:
        raise GrowthAnalyticsHold("HOLD_CP89_TRUTHFULNESS_POLICY_WEAKENED")
    if any((
        virality.get("automatic_strategy_mutation_allowed") is not False,
        virality.get("clickbait_optimization_allowed") is not False,
        virality.get("conflict_fabrication_allowed") is not False,
    )):
        raise GrowthAnalyticsHold("HOLD_CP89_VIRALITY_SAFETY_WEAKENED")

    truthfulness = policy.get("truthfulness", {})
    required_truth = {
        "missing_value_state": "UNKNOWN",
        "zero_denominator_state": "UNKNOWN",
        "null_is_not_zero": True,
        "partial_coverage_must_be_labeled": True,
        "causal_attribution_claims_forbidden": True,
        "fabricated_external_metrics_forbidden": True,
    }
    if any(truthfulness.get(key) != expected for key, expected in required_truth.items()):
        raise GrowthAnalyticsHold("HOLD_CP89_TRUTHFULNESS_POLICY_WEAKENED")

    privacy = policy.get("privacy", {})
    required_privacy = (
        "aggregate_content_level_only",
        "person_level_identifiers_forbidden",
        "sensitive_trait_inference_forbidden",
        "sensitive_relationship_profiling_forbidden",
        "political_microtargeting_forbidden",
    )
    if any(privacy.get(key) is not True for key in required_privacy):
        raise GrowthAnalyticsHold("HOLD_CP89_PRIVACY_POLICY_WEAKENED")

    safety = policy.get("safety", {})
    required_safety = (
        "automated_follow_unfollow_forbidden",
        "mass_commenting_forbidden",
        "engagement_pods_forbidden",
        "repetitive_praise_forbidden",
        "copy_paste_replies_forbidden",
        "synthetic_conversation_farming_forbidden",
        "clickbait_conflict_fabrication_forbidden",
        "unknown_capability_fail_closed",
        "rate_budgets_are_ceilings",
    )
    if any(safety.get(key) is not True for key in required_safety):
        raise GrowthAnalyticsHold("HOLD_CP89_GROWTH_SAFETY_POLICY_WEAKENED")

    authority = policy.get("authority", {})
    required_false = (
        "external_metric_fetch_allowed",
        "external_write_allowed",
        "network_allowed",
        "live_probe_allowed",
        "oauth_allowed",
        "account_connection_allowed",
        "posting_authority",
        "strategy_mutation_authority",
        "control_plane_promotion_allowed",
        "deploy_allowed",
        "paid_service_allowed",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise GrowthAnalyticsHold("HOLD_CP89_LIVE_AUTHORITY_DRIFT")
    if type(policy.get("max_batch")) is not int or not 1 <= policy["max_batch"] <= 1000:
        raise GrowthAnalyticsHold("HOLD_CP89_BATCH_LIMIT_INVALID")


def compile_growth_analytics(policy: dict) -> GrowthAnalyticsContract:
    validate_policy(policy)
    authority = policy["authority"]
    virality = policy["virality_learning"]
    return GrowthAnalyticsContract(
        checkpoint=policy["checkpoint"],
        module_id=policy["module_id"],
        parent_activation_checkpoint=policy["parent_activation_checkpoint"],
        parent_control_checkpoint=policy["parent_control_checkpoint"],
        next_unit=policy["next_after_cp89"],
        active_platforms=tuple(policy["active_platforms"]),
        core_metrics=tuple(policy["core_metrics"]),
        virality_components=tuple(virality["components"]),
        virality_weights={key: float(value) for key, value in virality["weights"].items()},
        max_batch=policy["max_batch"],
        global_kill_switch_engaged=policy["global_kill_switch"] == "ENGAGED",
        unknown_external_metric_value=policy["unknown_external_metric_value"],
        external_metric_fetch_allowed=authority["external_metric_fetch_allowed"],
        external_write_allowed=authority["external_write_allowed"],
        network_allowed=authority["network_allowed"],
        live_probe_allowed=authority["live_probe_allowed"],
        oauth_allowed=authority["oauth_allowed"],
        account_connection_allowed=authority["account_connection_allowed"],
        posting_authority=authority["posting_authority"],
        strategy_mutation_authority=authority["strategy_mutation_authority"],
        control_plane_promoted=authority["control_plane_promotion_allowed"],
        deploy_allowed=authority["deploy_allowed"],
        paid_service_allowed=authority["paid_service_allowed"],
    )


def _validate_optional_count(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if type(value) is not int or value < 0:
        raise GrowthAnalyticsHold(f"HOLD_CP89_COUNT_INVALID:{field_name}")


def _validate_score(value: float | None, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
        raise GrowthAnalyticsHold(f"HOLD_CP89_SCORE_INVALID:{field_name}")


def validate_observation(contract: GrowthAnalyticsContract, observation: GrowthObservation) -> None:
    if not isinstance(observation, GrowthObservation):
        raise GrowthAnalyticsHold("HOLD_CP89_OBSERVATION_TYPE")
    if observation.platform not in contract.active_platforms:
        raise GrowthAnalyticsHold("HOLD_CAPABILITY_UNVERIFIED")
    if not observation.observation_ref.strip() or not observation.provenance_ref.strip() or not observation.topic.strip():
        raise GrowthAnalyticsHold("HOLD_CP89_REQUIRED_REFERENCE_MISSING")
    if len(observation.topic) > 240:
        raise GrowthAnalyticsHold("HOLD_CP89_TOPIC_TOO_LONG")
    _parse_iso(observation.observed_at_utc)
    if observation.evidence_class not in {"SYNTHETIC_OFFLINE", "VERIFIED_READBACK_IMPORT"}:
        raise GrowthAnalyticsHold("HOLD_CP89_EVIDENCE_CLASS_INVALID")
    if not observation.source_is_public or not observation.aggregate_content_level_only:
        raise GrowthAnalyticsHold("HOLD_CP89_PUBLIC_AGGREGATE_SCOPE_REQUIRED")

    forbidden_flags = {
        "person_level_identifiers_present": observation.person_level_identifiers_present,
        "sensitive_trait_data_present": observation.sensitive_trait_data_present,
        "sensitive_trait_inference_requested": observation.sensitive_trait_inference_requested,
        "sensitive_relationship_profiling_requested": observation.sensitive_relationship_profiling_requested,
        "political_microtargeting_requested": observation.political_microtargeting_requested,
        "synthetic_conversation_farming_requested": observation.synthetic_conversation_farming_requested,
        "clickbait_optimization_requested": observation.clickbait_optimization_requested,
        "conflict_fabrication_requested": observation.conflict_fabrication_requested,
    }
    active_forbidden = [key for key, value in forbidden_flags.items() if value]
    if active_forbidden:
        raise GrowthAnalyticsHold(f"HOLD_CP89_FORBIDDEN_GROWTH_SIGNAL:{active_forbidden[0]}")

    for field_name in COUNT_FIELDS:
        _validate_optional_count(getattr(observation, field_name), field_name)
    for field_name in SCORE_FIELDS:
        _validate_score(getattr(observation, field_name), field_name)
    for name, values in (
        ("first_reply_latencies_seconds", observation.first_reply_latencies_seconds),
        ("conversation_depth_samples", observation.conversation_depth_samples),
    ):
        if not isinstance(values, tuple):
            raise GrowthAnalyticsHold(f"HOLD_CP89_SAMPLE_TYPE_INVALID:{name}")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 for value in values):
            raise GrowthAnalyticsHold(f"HOLD_CP89_SAMPLE_VALUE_INVALID:{name}")

    subset_rules = (
        ("meaningful_comments", "comments"),
        ("replies", "response_opportunities"),
        ("repeat_engagers", "engaged_users"),
        ("follows", "profile_visits"),
        ("outbound_comments_with_response", "outbound_comments"),
        ("reactivated_relationships", "eligible_dormant_relationships"),
        ("successful_amplifications", "amplification_candidates"),
    )
    for subset_name, total_name in subset_rules:
        subset = getattr(observation, subset_name)
        total = getattr(observation, total_name)
        if subset is not None and total is not None and subset > total:
            raise GrowthAnalyticsHold(f"HOLD_CP89_COUNT_RELATION_INVALID:{subset_name}>{total_name}")


def _metric_unknown(name: str, unit: str, total: int, reason: str) -> MetricValue:
    return MetricValue(
        name=name,
        state="UNKNOWN",
        value=None,
        unit=unit,
        known_observations=0,
        total_observations=total,
        reason=reason,
    )


def _metric_known(name: str, value: float | int, unit: str, known: int, total: int) -> MetricValue:
    state = "KNOWN" if known == total else "PARTIAL"
    return MetricValue(
        name=name,
        state=state,
        value=value,
        unit=unit,
        known_observations=known,
        total_observations=total,
        reason=None if state == "KNOWN" else "PARTIAL_COVERAGE_EXPLICIT",
    )


def _single_rate(name: str, numerator: int | None, denominator: int | None) -> MetricValue:
    if numerator is None or denominator is None:
        return _metric_unknown(name, "ratio", 1, "INPUT_UNAVAILABLE")
    if denominator == 0:
        return _metric_unknown(name, "ratio", 1, "ZERO_DENOMINATOR")
    return _metric_known(name, round(numerator / denominator, 6), "ratio", 1, 1)


def _single_samples(name: str, values: tuple[float, ...], *, method: str, unit: str) -> MetricValue:
    if not values:
        return _metric_unknown(name, unit, 1, "INPUT_UNAVAILABLE")
    if method == "median":
        value = median(values)
    elif method == "mean":
        value = mean(values)
    else:
        raise GrowthAnalyticsHold("HOLD_CP89_INTERNAL_AGGREGATION_MODE")
    return _metric_known(name, round(float(value), 6), unit, 1, 1)


def _observation_metrics(observation: GrowthObservation) -> dict[str, MetricValue]:
    return {
        "engagement_per_reached_user": _single_rate(
            "engagement_per_reached_user", observation.engaged_users, observation.reach
        ),
        "meaningful_comment_rate": _single_rate(
            "meaningful_comment_rate", observation.meaningful_comments, observation.comments
        ),
        "reply_rate": _single_rate("reply_rate", observation.replies, observation.response_opportunities),
        "median_first_reply_latency": _single_samples(
            "median_first_reply_latency",
            observation.first_reply_latencies_seconds,
            method="median",
            unit="seconds",
        ),
        "conversation_depth": _single_samples(
            "conversation_depth",
            observation.conversation_depth_samples,
            method="mean",
            unit="turns",
        ),
        "repeat_engager_rate": _single_rate(
            "repeat_engager_rate", observation.repeat_engagers, observation.engaged_users
        ),
        "profile_visit_rate": _single_rate(
            "profile_visit_rate", observation.profile_visits, observation.reach
        ),
        "follower_conversion_rate": _single_rate(
            "follower_conversion_rate", observation.follows, observation.profile_visits
        ),
        "outbound_comment_response_rate": _single_rate(
            "outbound_comment_response_rate",
            observation.outbound_comments_with_response,
            observation.outbound_comments,
        ),
        "relationship_reactivation_rate": _single_rate(
            "relationship_reactivation_rate",
            observation.reactivated_relationships,
            observation.eligible_dormant_relationships,
        ),
        "amplification_yield": _single_rate(
            "amplification_yield",
            observation.successful_amplifications,
            observation.amplification_candidates,
        ),
    }


def _virality_packet(contract: GrowthAnalyticsContract, observation: GrowthObservation) -> ViralityLearningPacket:
    source_scores = {
        "topic_selection": observation.topic_selection_score,
        "packaging": observation.packaging_score,
        "early_engagement": observation.early_engagement_score,
        "network_propagation": observation.network_propagation_score,
    }
    component_scores: dict[str, MetricValue] = {}
    for component in contract.virality_components:
        value = source_scores[component]
        if value is None:
            component_scores[component] = _metric_unknown(component, "score_0_100", 1, "INPUT_UNAVAILABLE")
        else:
            component_scores[component] = _metric_known(
                component, round(float(value), 6), "score_0_100", 1, 1
            )

    if all(component_scores[name].state == "KNOWN" for name in contract.virality_components):
        score = round(
            sum(
                float(component_scores[name].value) * contract.virality_weights[name]
                for name in contract.virality_components
            ),
            6,
        )
        observed_signal = _metric_known("observed_virality_signal_score", score, "score_0_100", 1, 1)
        state = "OBSERVED_SIGNAL_AVAILABLE_NON_CAUSAL"
        recommendations: list[str] = []
        topic_score = float(component_scores["topic_selection"].value)
        packaging_score = float(component_scores["packaging"].value)
        early_score = float(component_scores["early_engagement"].value)
        network_score = float(component_scores["network_propagation"].value)
        if score >= 75:
            recommendations.append("HUMAN_REVIEW_EVIDENCE_BOUND_FOLLOW_UP_PATTERN")
        if topic_score >= 70 and packaging_score < 50:
            recommendations.append("HUMAN_REVIEW_PACKAGING_CLARITY_WITHOUT_CLICKBAIT")
        if early_score >= 70 and network_score < 50:
            recommendations.append("HUMAN_REVIEW_DISTRIBUTION_CONTEXT_NO_SYNTHETIC_AMPLIFICATION")
        if not recommendations:
            recommendations.append("NO_AUTOMATIC_STRATEGY_CHANGE")
    else:
        observed_signal = _metric_unknown(
            "observed_virality_signal_score", "score_0_100", 1, "INCOMPLETE_COMPONENT_EVIDENCE"
        )
        state = "INSUFFICIENT_EVIDENCE"
        recommendations = ["INSUFFICIENT_COMPONENT_EVIDENCE_NO_STRATEGY_CHANGE"]

    return ViralityLearningPacket(
        observation_ref=observation.observation_ref,
        topic=observation.topic,
        state=state,
        component_scores=component_scores,
        observed_signal_score=observed_signal,
        attribution_mode="OBSERVATIONAL_NON_CAUSAL",
        recommendations=tuple(recommendations),
    )


def evaluate_observation(
    contract: GrowthAnalyticsContract,
    state: GrowthAnalyticsState,
    observation: GrowthObservation,
) -> ObservationAnalytics:
    validate_observation(contract, observation)
    body = observation.to_dict()
    body["observed_at_utc"] = _iso(observation.observed_at_utc)
    observation_hash = _hash(body)

    prior_provenance = state.provenance_receipts.get(observation.provenance_ref)
    if prior_provenance is not None:
        prior_hash, prior_result = prior_provenance
        if prior_hash != observation_hash:
            raise GrowthAnalyticsHold("HOLD_CP89_CONFLICTING_PROVENANCE_REUSE")
        return prior_result

    prior_observation_hash = state.observation_receipts.get(observation.observation_ref)
    if prior_observation_hash is not None and prior_observation_hash != observation_hash:
        raise GrowthAnalyticsHold("HOLD_CP89_CONFLICTING_OBSERVATION_REUSE")

    metrics = _observation_metrics(observation)
    virality_learning = _virality_packet(contract, observation)
    result = ObservationAnalytics(
        observation_ref=observation.observation_ref,
        observation_hash=observation_hash,
        platform=observation.platform,
        topic=observation.topic,
        evidence_class=observation.evidence_class,
        metrics=metrics,
        virality_learning=virality_learning,
    )
    state.provenance_receipts[observation.provenance_ref] = (observation_hash, result)
    state.observation_receipts[observation.observation_ref] = observation_hash
    return result


def _aggregate_rate(
    observations: tuple[GrowthObservation, ...],
    name: str,
    numerator_field: str,
    denominator_field: str,
) -> MetricValue:
    valid: list[tuple[int, int]] = []
    for observation in observations:
        numerator = getattr(observation, numerator_field)
        denominator = getattr(observation, denominator_field)
        if numerator is not None and denominator is not None and denominator > 0:
            valid.append((numerator, denominator))
    if not valid:
        return _metric_unknown(name, "ratio", len(observations), "NO_VALID_DENOMINATOR_EVIDENCE")
    numerator_total = sum(item[0] for item in valid)
    denominator_total = sum(item[1] for item in valid)
    return _metric_known(
        name,
        round(numerator_total / denominator_total, 6),
        "ratio",
        len(valid),
        len(observations),
    )


def _aggregate_samples(
    observations: tuple[GrowthObservation, ...],
    name: str,
    field_name: str,
    *,
    method: str,
    unit: str,
) -> MetricValue:
    samples: list[float] = []
    known = 0
    for observation in observations:
        values = getattr(observation, field_name)
        if values:
            known += 1
            samples.extend(float(value) for value in values)
    if not samples:
        return _metric_unknown(name, unit, len(observations), "INPUT_UNAVAILABLE")
    value = median(samples) if method == "median" else mean(samples)
    return _metric_known(name, round(float(value), 6), unit, known, len(observations))


def _aggregate_count(
    observations: tuple[GrowthObservation, ...],
    name: str,
    field_name: str,
) -> MetricValue:
    values = [getattr(observation, field_name) for observation in observations]
    known_values = [value for value in values if value is not None]
    if not known_values:
        return _metric_unknown(name, "count", len(observations), "INPUT_UNAVAILABLE")
    return _metric_known(name, sum(known_values), "count", len(known_values), len(observations))


def _aggregate_core_metrics(observations: tuple[GrowthObservation, ...]) -> dict[str, MetricValue]:
    return {
        "engagement_per_reached_user": _aggregate_rate(
            observations, "engagement_per_reached_user", "engaged_users", "reach"
        ),
        "meaningful_comment_rate": _aggregate_rate(
            observations, "meaningful_comment_rate", "meaningful_comments", "comments"
        ),
        "reply_rate": _aggregate_rate(
            observations, "reply_rate", "replies", "response_opportunities"
        ),
        "median_first_reply_latency": _aggregate_samples(
            observations,
            "median_first_reply_latency",
            "first_reply_latencies_seconds",
            method="median",
            unit="seconds",
        ),
        "conversation_depth": _aggregate_samples(
            observations,
            "conversation_depth",
            "conversation_depth_samples",
            method="mean",
            unit="turns",
        ),
        "repeat_engager_rate": _aggregate_rate(
            observations, "repeat_engager_rate", "repeat_engagers", "engaged_users"
        ),
        "profile_visit_rate": _aggregate_rate(
            observations, "profile_visit_rate", "profile_visits", "reach"
        ),
        "follower_conversion_rate": _aggregate_rate(
            observations, "follower_conversion_rate", "follows", "profile_visits"
        ),
        "outbound_comment_response_rate": _aggregate_rate(
            observations,
            "outbound_comment_response_rate",
            "outbound_comments_with_response",
            "outbound_comments",
        ),
        "relationship_reactivation_rate": _aggregate_rate(
            observations,
            "relationship_reactivation_rate",
            "reactivated_relationships",
            "eligible_dormant_relationships",
        ),
        "amplification_yield": _aggregate_rate(
            observations,
            "amplification_yield",
            "successful_amplifications",
            "amplification_candidates",
        ),
    }


def _funnel(observations: tuple[GrowthObservation, ...]) -> dict[str, MetricValue]:
    return {
        "publication": _metric_known("publication", len(observations), "count", len(observations), len(observations)),
        "reach": _aggregate_count(observations, "reach", "reach"),
        "impressions": _aggregate_count(observations, "impressions", "impressions"),
        "engaged_users": _aggregate_count(observations, "engaged_users", "engaged_users"),
        "comments": _aggregate_count(observations, "comments", "comments"),
        "replies": _aggregate_count(observations, "replies", "replies"),
        "profile_visits": _aggregate_count(observations, "profile_visits", "profile_visits"),
        "follows": _aggregate_count(observations, "follows", "follows"),
        "repeat_engagers": _aggregate_count(observations, "repeat_engagers", "repeat_engagers"),
        "conversation_depth": _aggregate_samples(
            observations,
            "conversation_depth",
            "conversation_depth_samples",
            method="mean",
            unit="turns",
        ),
    }


def _topic_attribution(observations: tuple[GrowthObservation, ...]) -> tuple[TopicGrowthAttribution, ...]:
    grouped: dict[str, list[GrowthObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.topic, []).append(observation)
    profiles: list[TopicGrowthAttribution] = []
    for topic in sorted(grouped):
        group = tuple(grouped[topic])
        profiles.append(
            TopicGrowthAttribution(
                topic=topic,
                observation_count=len(group),
                metric_profile=_aggregate_core_metrics(group),
            )
        )
    return tuple(profiles)


def _report_body(
    report_ref: str,
    observations: tuple[GrowthObservation, ...],
    funnel: dict[str, MetricValue],
    core_metrics: dict[str, MetricValue],
    topic_profiles: tuple[TopicGrowthAttribution, ...],
    packets: tuple[ViralityLearningPacket, ...],
) -> dict:
    times = sorted(_parse_iso(observation.observed_at_utc) for observation in observations)
    return {
        "model_version": GROWTH_ANALYTICS_MODEL_VERSION,
        "engine_version": GROWTH_ANALYTICS_ENGINE_VERSION,
        "report_ref": report_ref,
        "observation_count": len(observations),
        "observed_at_min_utc": times[0].isoformat().replace("+00:00", "Z"),
        "observed_at_max_utc": times[-1].isoformat().replace("+00:00", "Z"),
        "funnel": {key: value.to_dict() for key, value in funnel.items()},
        "core_metrics": {key: value.to_dict() for key, value in core_metrics.items()},
        "topic_to_growth_attribution": [item.to_dict() for item in topic_profiles],
        "virality_learning_packets": [item.to_dict() for item in packets],
        "evidence_classes": sorted({observation.evidence_class for observation in observations}),
        "external_metric_state": "UNKNOWN_WHERE_UNAVAILABLE",
        "learning_mode": "OBSERVATIONAL_NON_CAUSAL_HUMAN_REVIEW_ONLY",
        "global_kill_switch": "ENGAGED",
        "aggregate_content_level_only": True,
        "person_level_profiling_allowed": False,
        "sensitive_profiling_allowed": False,
        "causal_attribution_allowed": False,
        "automatic_strategy_mutation_allowed": False,
        "external_metric_fetch_allowed": False,
        "external_write_allowed": False,
        "network_attempted": False,
        "live_probe_attempted": False,
        "account_connected": False,
        "posting_authority": False,
        "deploy_authority": False,
        "paid_service_used": False,
        "state": "CP89_OFFLINE_GROWTH_ANALYTICS_REPORT_ONLY",
    }


def validate_report(report: GrowthAnalyticsReport) -> None:
    if not isinstance(report, GrowthAnalyticsReport):
        raise GrowthAnalyticsHold("HOLD_CP89_REPORT_TYPE")
    if report.model_version != GROWTH_ANALYTICS_MODEL_VERSION or report.engine_version != GROWTH_ANALYTICS_ENGINE_VERSION:
        raise GrowthAnalyticsHold("HOLD_CP89_REPORT_VERSION")
    if report.observation_count < 1:
        raise GrowthAnalyticsHold("HOLD_CP89_EMPTY_REPORT")
    if report.external_metric_state != "UNKNOWN_WHERE_UNAVAILABLE":
        raise GrowthAnalyticsHold("HOLD_CP89_FALSE_EXTERNAL_METRIC_STATE")
    if report.learning_mode != "OBSERVATIONAL_NON_CAUSAL_HUMAN_REVIEW_ONLY":
        raise GrowthAnalyticsHold("HOLD_CP89_CAUSALITY_DRIFT")
    if report.global_kill_switch != "ENGAGED":
        raise GrowthAnalyticsHold("HOLD_CP89_KILL_SWITCH_NOT_ENGAGED")
    if not report.aggregate_content_level_only:
        raise GrowthAnalyticsHold("HOLD_CP89_AGGREGATE_SCOPE_DRIFT")
    if any((
        report.person_level_profiling_allowed,
        report.sensitive_profiling_allowed,
        report.causal_attribution_allowed,
        report.automatic_strategy_mutation_allowed,
        report.external_metric_fetch_allowed,
        report.external_write_allowed,
        report.network_attempted,
        report.live_probe_attempted,
        report.account_connected,
        report.posting_authority,
        report.deploy_authority,
        report.paid_service_used,
    )):
        raise GrowthAnalyticsHold("HOLD_CP89_EXTERNAL_AUTHORITY_OR_PROFILING_DRIFT")
    if set(report.core_metrics) != set(CORE_METRICS[:-1]):
        raise GrowthAnalyticsHold("HOLD_CP89_REPORT_METRIC_SET_INVALID")
    if any(profile.attribution_mode != "DESCRIPTIVE_NON_CAUSAL" or profile.causal_claim_allowed for profile in report.topic_to_growth_attribution):
        raise GrowthAnalyticsHold("HOLD_CP89_TOPIC_ATTRIBUTION_CAUSALITY_DRIFT")
    body = report.to_dict()
    body.pop("report_id")
    body.pop("report_hash")
    expected_hash = _hash(body)
    if report.report_hash != expected_hash or report.report_id != "gar_" + expected_hash[:24]:
        raise GrowthAnalyticsHold("HOLD_CP89_REPORT_HASH_MISMATCH")


def compile_growth_report(
    contract: GrowthAnalyticsContract,
    state: GrowthAnalyticsState,
    observations: Iterable[GrowthObservation],
    *,
    report_ref: str,
) -> GrowthAnalyticsReport:
    batch = tuple(observations)
    if not report_ref.strip():
        raise GrowthAnalyticsHold("HOLD_CP89_REPORT_REF_MISSING")
    if not batch:
        raise GrowthAnalyticsHold("HOLD_CP89_EMPTY_BATCH")
    if len(batch) > contract.max_batch:
        raise GrowthAnalyticsHold("HOLD_CP89_BATCH_LIMIT_EXCEEDED")

    shadow = deepcopy(state)
    results = tuple(evaluate_observation(contract, shadow, observation) for observation in batch)
    funnel = _funnel(batch)
    core_metrics = _aggregate_core_metrics(batch)
    topic_profiles = _topic_attribution(batch)
    packets = tuple(result.virality_learning for result in results)
    body = _report_body(report_ref, batch, funnel, core_metrics, topic_profiles, packets)
    report_hash = _hash(body)
    report = GrowthAnalyticsReport(
        report_id="gar_" + report_hash[:24],
        report_hash=report_hash,
        model_version=body["model_version"],
        engine_version=body["engine_version"],
        report_ref=body["report_ref"],
        observation_count=body["observation_count"],
        observed_at_min_utc=body["observed_at_min_utc"],
        observed_at_max_utc=body["observed_at_max_utc"],
        funnel=funnel,
        core_metrics=core_metrics,
        topic_to_growth_attribution=topic_profiles,
        virality_learning_packets=packets,
        evidence_classes=tuple(body["evidence_classes"]),
        external_metric_state=body["external_metric_state"],
        learning_mode=body["learning_mode"],
    )
    validate_report(report)
    state.provenance_receipts = shadow.provenance_receipts
    state.observation_receipts = shadow.observation_receipts
    return report
