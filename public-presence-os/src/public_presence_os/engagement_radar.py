from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from public_presence_os.growth_capability_matrix import (
    ACTIVE_PLATFORMS,
    GrowthCapabilityMatrixContract,
    GrowthCapabilityMatrixHold,
    capability_lookup,
)

MODEL_VERSION = "PPOS_ENGAGEMENT_RADAR_V1"
ENGINE_VERSION = "ppos-engagement-radar-v1.0.0"
CHECKPOINT = "CP84"
PARENT_ACTIVATION_CHECKPOINT = "CP83"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP85_INBOUND_REPLY_ENGINE"
STATE = "CP84_ENGAGEMENT_RADAR_OFFLINE_CANDIDATE_SCORING_NO_POSTING_AUTHORITY_LIVE_HOLD"
UNKNOWN_EXTERNAL_METRIC_VALUE = "UNKNOWN"

DISCOVERY_CAPABILITIES = ("MENTION_DISCOVERY", "HASHTAG_TOPIC_DISCOVERY")
PROVENANCE_KINDS = ("PUBLIC_URL_OBSERVATION", "OFFLINE_API_FIXTURE", "SYNTHETIC_FIXTURE")
SCORE_DIMENSIONS = (
    "relevance",
    "expertise_fit",
    "conversation_momentum",
    "novelty",
    "answerability",
    "reputational_risk",
    "spam_risk",
    "expected_relationship_value",
)
POSITIVE_DIMENSIONS = (
    "relevance",
    "expertise_fit",
    "conversation_momentum",
    "novelty",
    "answerability",
    "expected_relationship_value",
)
RISK_DIMENSIONS = ("reputational_risk", "spam_risk")
MAX_BATCH = 100
MAX_CONTEXT = 4000
MAX_LABEL = 160
MAX_REF = 240
PUBLIC_ID_RE = re.compile(r"^[^\s]{1,240}$")
WS_RE = re.compile(r"\s+")


class EngagementRadarHold(ValueError):
    """Fail-closed CP84 contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _norm_text(value: str, *, name: str, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise EngagementRadarHold(f"HOLD_CP84_{name.upper()}_TYPE")
    value = WS_RE.sub(" ", value).strip()
    if not value and not allow_empty:
        raise EngagementRadarHold(f"HOLD_CP84_{name.upper()}_MISSING")
    if len(value) > max_len:
        raise EngagementRadarHold(f"HOLD_CP84_{name.upper()}_TOO_LONG")
    return value


def _norm_utc(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EngagementRadarHold(f"HOLD_CP84_{name.upper()}_UTC_REQUIRED")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EngagementRadarHold(f"HOLD_CP84_{name.upper()}_INVALID") from exc
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise EngagementRadarHold(f"HOLD_CP84_{name.upper()}_UTC_REQUIRED")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


def _norm_source_url(url: str, provenance_kind: str) -> str:
    if not isinstance(url, str):
        raise EngagementRadarHold("HOLD_CP84_SOURCE_URL_TYPE")
    p = urlsplit(url.strip())
    if provenance_kind == "SYNTHETIC_FIXTURE":
        if p.scheme != "synthetic" or not p.netloc:
            raise EngagementRadarHold("HOLD_CP84_SYNTHETIC_FIXTURE_URL_REQUIRED")
        return urlunsplit(("synthetic", p.netloc.lower(), p.path or "/", p.query, ""))
    if p.scheme != "https" or not p.netloc:
        raise EngagementRadarHold("HOLD_CP84_PUBLIC_SOURCE_HTTPS_REQUIRED")
    if "@" in p.netloc:
        raise EngagementRadarHold("HOLD_CP84_SOURCE_URL_USERINFO_FORBIDDEN")
    return urlunsplit(("https", p.netloc.lower(), p.path or "/", p.query, ""))


def _score_value(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise EngagementRadarHold(f"HOLD_CP84_{name.upper()}_SCORE_INVALID")
    return value


@dataclass(frozen=True)
class EngagementScoreEvidence:
    relevance: int
    expertise_fit: int
    conversation_momentum: int
    novelty: int
    answerability: int
    reputational_risk: int
    spam_risk: int
    expected_relationship_value: int

    def validated(self) -> "EngagementScoreEvidence":
        values = {name: _score_value(getattr(self, name), name) for name in SCORE_DIMENSIONS}
        return EngagementScoreEvidence(**values)

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class EngagementObservation:
    platform: str
    discovery_capability: str
    provenance_kind: str
    provenance_ref: str
    conversation_ref: str
    source_url: str
    author_public_id: str
    topic: str
    context: str
    observed_at_utc: str
    published_at_utc: str
    score_evidence: EngagementScoreEvidence
    sensitive_trait_inference_used: bool = False
    sensitive_relationship_profiling_used: bool = False
    political_microtargeting_used: bool = False
    synthetic_conversation_farming_used: bool = False


@dataclass(frozen=True)
class DiscoveryRoute:
    platform: str
    capability: str
    expected_cp83_classification: str
    automation_discovery_eligible: bool
    allowed_provenance: tuple[str, ...]
    required_blockers: tuple[str, ...]


@dataclass(frozen=True)
class EngagementRadarContract:
    contract_id: str
    contract_hash: str
    policy_sha256: str
    routes: tuple[DiscoveryRoute, ...]
    benefit_weights: Mapping[str, int]
    risk_penalty_weights: Mapping[str, float]
    thresholds: Mapping[str, int]
    blockers: tuple[str, ...]
    checkpoint: str = CHECKPOINT
    parent_activation_checkpoint: str = PARENT_ACTIVATION_CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    next_unit: str = NEXT_UNIT
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    global_kill_switch_engaged: bool = True
    posting_authority: bool = False
    external_write_allowed: bool = False
    external_write_performed: bool = False
    network_allowed: bool = False
    network_attempted: bool = False
    live_probe_allowed: bool = False
    live_probe_attempted: bool = False
    oauth_attempted: bool = False
    account_connected: bool = False
    control_plane_promoted: bool = False
    deploy_allowed: bool = False
    deploy_performed: bool = False
    external_metrics: str = UNKNOWN_EXTERNAL_METRIC_VALUE
    state: str = STATE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["routes"] = [asdict(route) | {
            "allowed_provenance": list(route.allowed_provenance),
            "required_blockers": list(route.required_blockers),
        } for route in self.routes]
        d["benefit_weights"] = dict(self.benefit_weights)
        d["risk_penalty_weights"] = dict(self.risk_penalty_weights)
        d["thresholds"] = dict(self.thresholds)
        d["blockers"] = list(self.blockers)
        return d


@dataclass(frozen=True)
class EngagementCandidate:
    candidate_id: str
    observation_hash: str
    provenance_hash: str
    platform: str
    discovery_capability: str
    cp83_classification: str
    automation_discovery_eligible: bool
    provenance_kind: str
    provenance_ref: str
    conversation_ref: str
    source_url: str
    author_public_id: str
    topic: str
    context: str
    observed_at_utc: str
    published_at_utc: str
    freshness_hours: float
    score_evidence: EngagementScoreEvidence
    benefit_score: float
    risk_penalty: float
    final_score: float
    decision: str
    decision_reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    posting_authority: bool = False
    external_write_allowed: bool = False
    external_write_attempted: bool = False
    network_fetch_performed: bool = False
    external_metrics: str = UNKNOWN_EXTERNAL_METRIC_VALUE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["score_evidence"] = self.score_evidence.to_dict()
        d["decision_reasons"] = list(self.decision_reasons)
        d["blockers"] = list(self.blockers)
        return d


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"),
        policy.get("checkpoint"),
        policy.get("module_id"),
        policy.get("parent_activation_checkpoint"),
        policy.get("parent_control_checkpoint"),
        policy.get("next_after_cp84"),
    )
    expected = (
        "PPOS_ENGAGEMENT_RADAR_POLICY_V1",
        CHECKPOINT,
        "M53_ENGAGEMENT_RADAR",
        PARENT_ACTIVATION_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        NEXT_UNIT,
    )
    if identity != expected:
        raise EngagementRadarHold("HOLD_CP84_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise EngagementRadarHold("HOLD_CP84_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("discovery_capabilities", ())) != DISCOVERY_CAPABILITIES:
        raise EngagementRadarHold("HOLD_CP84_DISCOVERY_CAPABILITY_DRIFT")
    if tuple(policy.get("provenance_kinds", ())) != PROVENANCE_KINDS:
        raise EngagementRadarHold("HOLD_CP84_PROVENANCE_KIND_DRIFT")
    if tuple(policy.get("score_dimensions", ())) != SCORE_DIMENSIONS:
        raise EngagementRadarHold("HOLD_CP84_SCORE_DIMENSION_DRIFT")
    if policy.get("global_kill_switch") != "ENGAGED":
        raise EngagementRadarHold("HOLD_CP84_KILL_SWITCH_NOT_ENGAGED")
    if policy.get("unknown_external_metric_value") != UNKNOWN_EXTERNAL_METRIC_VALUE:
        raise EngagementRadarHold("HOLD_CP84_UNKNOWN_METRIC_DRIFT")

    authority = policy.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise EngagementRadarHold("HOLD_CP84_LIVE_AUTHORITY_DRIFT")
    safety = policy.get("growth_safety")
    if not isinstance(safety, Mapping) or not safety or not all(value is True for value in safety.values()):
        raise EngagementRadarHold("HOLD_CP84_GROWTH_SAFETY_WEAKENED")

    benefit = policy.get("benefit_weights")
    if not isinstance(benefit, Mapping) or set(benefit) != set(POSITIVE_DIMENSIONS):
        raise EngagementRadarHold("HOLD_CP84_BENEFIT_WEIGHT_DIMENSION_DRIFT")
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in benefit.values()):
        raise EngagementRadarHold("HOLD_CP84_BENEFIT_WEIGHT_INVALID")
    if sum(benefit.values()) != 100:
        raise EngagementRadarHold("HOLD_CP84_BENEFIT_WEIGHT_SUM")

    penalties = policy.get("risk_penalty_weights")
    if not isinstance(penalties, Mapping) or set(penalties) != set(RISK_DIMENSIONS):
        raise EngagementRadarHold("HOLD_CP84_RISK_WEIGHT_DIMENSION_DRIFT")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= float(v) <= 1 for v in penalties.values()):
        raise EngagementRadarHold("HOLD_CP84_RISK_WEIGHT_INVALID")

    thresholds = policy.get("thresholds")
    required_thresholds = {
        "eligible_score_min",
        "spam_reject_at",
        "reputational_reject_at",
        "relevance_reject_below",
        "answerability_reject_below",
        "max_candidate_age_hours",
    }
    if not isinstance(thresholds, Mapping) or set(thresholds) != required_thresholds:
        raise EngagementRadarHold("HOLD_CP84_THRESHOLD_DRIFT")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in thresholds.values()):
        raise EngagementRadarHold("HOLD_CP84_THRESHOLD_INVALID")
    for key in required_thresholds - {"max_candidate_age_hours"}:
        if thresholds[key] > 100:
            raise EngagementRadarHold("HOLD_CP84_THRESHOLD_INVALID")
    if thresholds["max_candidate_age_hours"] <= 0:
        raise EngagementRadarHold("HOLD_CP84_THRESHOLD_INVALID")

    routes = policy.get("discovery_routes")
    if not isinstance(routes, list) or len(routes) != len(ACTIVE_PLATFORMS) * len(DISCOVERY_CAPABILITIES):
        raise EngagementRadarHold("HOLD_CP84_ROUTE_CARDINALITY")
    expected_pairs = {(p, c) for p in ACTIVE_PLATFORMS for c in DISCOVERY_CAPABILITIES}
    pairs = {(route.get("platform"), route.get("capability")) for route in routes if isinstance(route, Mapping)}
    if pairs != expected_pairs:
        raise EngagementRadarHold("HOLD_CP84_ROUTE_NOT_EXACT_CARTESIAN")
    for route in routes:
        if not isinstance(route, Mapping):
            raise EngagementRadarHold("HOLD_CP84_ROUTE_INVALID")
        allowed = tuple(route.get("allowed_provenance", ()))
        if not allowed or not set(allowed).issubset(PROVENANCE_KINDS):
            raise EngagementRadarHold("HOLD_CP84_ROUTE_PROVENANCE_INVALID")
        classification = route.get("expected_cp83_classification")
        if classification not in {"PASS_OFFLINE_CONTRACT", "HOLD_LIVE_PERMISSION", "MANUAL_ONLY", "UNSUPPORTED"}:
            raise EngagementRadarHold("HOLD_CP84_ROUTE_CLASSIFICATION_INVALID")
        automation = route.get("automation_discovery_eligible")
        if not isinstance(automation, bool):
            raise EngagementRadarHold("HOLD_CP84_ROUTE_AUTOMATION_FLAG_INVALID")
        if classification != "PASS_OFFLINE_CONTRACT" and automation:
            raise EngagementRadarHold("HOLD_CP84_UNVERIFIED_ROUTE_CANNOT_AUTOMATE")
        blockers = route.get("required_blockers")
        if not isinstance(blockers, list) or not blockers:
            raise EngagementRadarHold("HOLD_CP84_ROUTE_BLOCKERS_REQUIRED")
        if classification != "PASS_OFFLINE_CONTRACT" and "HOLD_CAPABILITY_UNVERIFIED" not in blockers:
            raise EngagementRadarHold("HOLD_CP84_UNVERIFIED_ROUTE_BLOCKER_MISSING")


def compile_engagement_radar(
    policy: Mapping[str, Any],
    capability_contract: GrowthCapabilityMatrixContract,
) -> EngagementRadarContract:
    validate_policy(policy)
    if capability_contract.checkpoint != PARENT_ACTIVATION_CHECKPOINT:
        raise EngagementRadarHold("HOLD_CP84_PARENT_CAPABILITY_CONTRACT_INVALID")
    if capability_contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise EngagementRadarHold("HOLD_CP84_PARENT_CONTROL_DRIFT")
    if not capability_contract.global_kill_switch_engaged:
        raise EngagementRadarHold("HOLD_CP84_PARENT_KILL_SWITCH_NOT_ENGAGED")

    routes: list[DiscoveryRoute] = []
    for item in policy["discovery_routes"]:
        try:
            parent_row = capability_lookup(capability_contract, item["platform"], item["capability"])
        except GrowthCapabilityMatrixHold as exc:
            raise EngagementRadarHold("HOLD_CAPABILITY_UNVERIFIED") from exc
        if parent_row.classification != item["expected_cp83_classification"]:
            raise EngagementRadarHold("HOLD_CP84_PARENT_CLASSIFICATION_DRIFT")
        if not set(item["required_blockers"]).issubset(set(parent_row.blockers) | {"HOLD_CAPABILITY_UNVERIFIED"}):
            raise EngagementRadarHold("HOLD_CP84_PARENT_BLOCKER_DRIFT")
        routes.append(DiscoveryRoute(
            platform=item["platform"],
            capability=item["capability"],
            expected_cp83_classification=item["expected_cp83_classification"],
            automation_discovery_eligible=item["automation_discovery_eligible"],
            allowed_provenance=tuple(item["allowed_provenance"]),
            required_blockers=tuple(item["required_blockers"]),
        ))

    payload = {
        "checkpoint": CHECKPOINT,
        "parent_activation_checkpoint": PARENT_ACTIVATION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "next_unit": NEXT_UNIT,
        "routes": [asdict(route) for route in routes],
        "benefit_weights": policy["benefit_weights"],
        "risk_penalty_weights": policy["risk_penalty_weights"],
        "thresholds": policy["thresholds"],
        "global_kill_switch": policy["global_kill_switch"],
    }
    contract_hash = _hash(payload)
    return EngagementRadarContract(
        contract_id=f"cp84-engagement-radar-{contract_hash[:16]}",
        contract_hash=contract_hash,
        policy_sha256=_hash(policy),
        routes=tuple(routes),
        benefit_weights=dict(policy["benefit_weights"]),
        risk_penalty_weights={k: float(v) for k, v in policy["risk_penalty_weights"].items()},
        thresholds=dict(policy["thresholds"]),
        blockers=tuple(policy["required_blockers"]),
    )


def _route_for(contract: EngagementRadarContract, platform: str, capability: str) -> DiscoveryRoute:
    if platform not in ACTIVE_PLATFORMS or capability not in DISCOVERY_CAPABILITIES:
        raise EngagementRadarHold("HOLD_CAPABILITY_UNVERIFIED")
    for route in contract.routes:
        if route.platform == platform and route.capability == capability:
            return route
    raise EngagementRadarHold("HOLD_CAPABILITY_UNVERIFIED")


def _normalize_observation(
    contract: EngagementRadarContract,
    observation: EngagementObservation,
    now_utc: str,
) -> dict[str, Any]:
    if not isinstance(observation, EngagementObservation):
        raise EngagementRadarHold("HOLD_CP84_OBSERVATION_TYPE")
    route = _route_for(contract, observation.platform, observation.discovery_capability)
    if observation.provenance_kind not in route.allowed_provenance:
        raise EngagementRadarHold("HOLD_CP84_PROVENANCE_NOT_ALLOWED_FOR_ROUTE")
    source_url = _norm_source_url(observation.source_url, observation.provenance_kind)
    provenance_ref = _norm_text(observation.provenance_ref, name="provenance_ref", max_len=MAX_REF)
    conversation_ref = _norm_text(observation.conversation_ref, name="conversation_ref", max_len=MAX_REF)
    author_public_id = _norm_text(observation.author_public_id, name="author_public_id", max_len=MAX_REF)
    if not PUBLIC_ID_RE.fullmatch(author_public_id):
        raise EngagementRadarHold("HOLD_CP84_AUTHOR_PUBLIC_ID_INVALID")
    topic = _norm_text(observation.topic, name="topic", max_len=MAX_LABEL)
    context = _norm_text(observation.context, name="context", max_len=MAX_CONTEXT)
    observed_at = _norm_utc(observation.observed_at_utc, name="observed_at")
    published_at = _norm_utc(observation.published_at_utc, name="published_at")
    now = _norm_utc(now_utc, name="now")
    observed_dt, published_dt, now_dt = _parse_utc(observed_at), _parse_utc(published_at), _parse_utc(now)
    if published_dt > observed_dt or observed_dt > now_dt:
        raise EngagementRadarHold("HOLD_CP84_TEMPORAL_ORDER_INVALID")
    freshness_hours = round((now_dt - published_dt).total_seconds() / 3600.0, 3)
    evidence = observation.score_evidence.validated()
    safety_flags = {
        "sensitive_trait_inference_used": observation.sensitive_trait_inference_used,
        "sensitive_relationship_profiling_used": observation.sensitive_relationship_profiling_used,
        "political_microtargeting_used": observation.political_microtargeting_used,
        "synthetic_conversation_farming_used": observation.synthetic_conversation_farming_used,
    }
    if any(not isinstance(v, bool) for v in safety_flags.values()):
        raise EngagementRadarHold("HOLD_CP84_SAFETY_FLAG_INVALID")
    return {
        "platform": observation.platform,
        "discovery_capability": observation.discovery_capability,
        "provenance_kind": observation.provenance_kind,
        "provenance_ref": provenance_ref,
        "conversation_ref": conversation_ref,
        "source_url": source_url,
        "author_public_id": author_public_id,
        "topic": topic,
        "context": context,
        "observed_at_utc": observed_at,
        "published_at_utc": published_at,
        "freshness_hours": freshness_hours,
        "score_evidence": evidence,
        "safety_flags": safety_flags,
        "route": route,
    }


def score_candidate(
    contract: EngagementRadarContract,
    observation: EngagementObservation,
    *,
    now_utc: str,
) -> EngagementCandidate:
    normalized = _normalize_observation(contract, observation, now_utc)
    route: DiscoveryRoute = normalized["route"]
    evidence: EngagementScoreEvidence = normalized["score_evidence"]

    benefit = sum(
        getattr(evidence, name) * contract.benefit_weights[name] / 100.0
        for name in POSITIVE_DIMENSIONS
    )
    penalty = sum(
        getattr(evidence, name) * contract.risk_penalty_weights[name]
        for name in RISK_DIMENSIONS
    )
    final_score = round(max(0.0, min(100.0, benefit - penalty)), 2)

    reasons: list[str] = []
    decision = "HOLD_LOW_EXPECTED_VALUE"
    t = contract.thresholds
    if any(normalized["safety_flags"].values()):
        decision = "REJECT_SAFETY"
        reasons.append("PROHIBITED_GROWTH_SAFETY_SIGNAL")
    elif evidence.spam_risk >= t["spam_reject_at"]:
        decision = "REJECT_SPAM_RISK"
        reasons.append("SPAM_RISK_THRESHOLD")
    elif evidence.reputational_risk >= t["reputational_reject_at"]:
        decision = "REJECT_REPUTATIONAL_RISK"
        reasons.append("REPUTATIONAL_RISK_THRESHOLD")
    elif evidence.relevance < t["relevance_reject_below"]:
        decision = "REJECT_LOW_RELEVANCE"
        reasons.append("RELEVANCE_BELOW_MINIMUM")
    elif evidence.answerability < t["answerability_reject_below"]:
        decision = "REJECT_UNANSWERABLE"
        reasons.append("ANSWERABILITY_BELOW_MINIMUM")
    elif normalized["freshness_hours"] > t["max_candidate_age_hours"]:
        decision = "HOLD_STALE"
        reasons.append("CANDIDATE_TOO_OLD")
    elif final_score >= t["eligible_score_min"]:
        decision = "ELIGIBLE_HUMAN_REVIEW"
        reasons.append("SCORE_GATE_MET")
    else:
        reasons.append("SCORE_GATE_NOT_MET")

    if not route.automation_discovery_eligible:
        reasons.append("AUTOMATION_DISCOVERY_NOT_AUTHORIZED")
    if route.expected_cp83_classification != "PASS_OFFLINE_CONTRACT":
        reasons.append("CAPABILITY_NOT_PASS_OFFLINE_CONTRACT")

    candidate_identity = {
        "platform": normalized["platform"],
        "conversation_ref": normalized["conversation_ref"],
        "source_url": normalized["source_url"],
    }
    provenance_payload = {
        "provenance_kind": normalized["provenance_kind"],
        "provenance_ref": normalized["provenance_ref"],
        "source_url": normalized["source_url"],
        "observed_at_utc": normalized["observed_at_utc"],
    }
    observation_payload = {
        **candidate_identity,
        "discovery_capability": normalized["discovery_capability"],
        "author_public_id": normalized["author_public_id"],
        "topic": normalized["topic"],
        "context": normalized["context"],
        "published_at_utc": normalized["published_at_utc"],
        "score_evidence": evidence.to_dict(),
        "safety_flags": normalized["safety_flags"],
        "provenance_hash": _hash(provenance_payload),
    }
    return EngagementCandidate(
        candidate_id=_hash(candidate_identity),
        observation_hash=_hash(observation_payload),
        provenance_hash=_hash(provenance_payload),
        platform=normalized["platform"],
        discovery_capability=normalized["discovery_capability"],
        cp83_classification=route.expected_cp83_classification,
        automation_discovery_eligible=route.automation_discovery_eligible,
        provenance_kind=normalized["provenance_kind"],
        provenance_ref=normalized["provenance_ref"],
        conversation_ref=normalized["conversation_ref"],
        source_url=normalized["source_url"],
        author_public_id=normalized["author_public_id"],
        topic=normalized["topic"],
        context=normalized["context"],
        observed_at_utc=normalized["observed_at_utc"],
        published_at_utc=normalized["published_at_utc"],
        freshness_hours=normalized["freshness_hours"],
        score_evidence=evidence,
        benefit_score=round(benefit, 2),
        risk_penalty=round(penalty, 2),
        final_score=final_score,
        decision=decision,
        decision_reasons=tuple(reasons),
        blockers=route.required_blockers,
    )


def score_batch(
    contract: EngagementRadarContract,
    observations,
    *,
    now_utc: str,
) -> tuple[EngagementCandidate, ...]:
    observations = tuple(observations)
    if len(observations) > MAX_BATCH:
        raise EngagementRadarHold(f"HOLD_CP84_BATCH_EXCEEDS_{MAX_BATCH}")
    by_candidate: dict[str, EngagementCandidate] = {}
    for observation in observations:
        candidate = score_candidate(contract, observation, now_utc=now_utc)
        existing = by_candidate.get(candidate.candidate_id)
        if existing and existing.observation_hash != candidate.observation_hash:
            raise EngagementRadarHold("HOLD_CP84_CONFLICTING_DUPLICATE")
        by_candidate.setdefault(candidate.candidate_id, candidate)
    return tuple(sorted(
        by_candidate.values(),
        key=lambda item: (-item.final_score, item.freshness_hours, item.candidate_id),
    ))


def candidates_json(candidates: tuple[EngagementCandidate, ...]) -> str:
    return json.dumps([candidate.to_dict() for candidate in candidates], indent=2, ensure_ascii=False, sort_keys=True)
