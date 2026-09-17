from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

MODEL_VERSION = "PPOS_AMPLIFICATION_ENGINE_V1"
ENGINE_VERSION = "ppos-amplification-engine-v1.0.0"
CHECKPOINT = "CP88"
PARENT_ACTIVATION_CHECKPOINT = "CP87"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP89_GROWTH_ANALYTICS_VIRALITY_LEARNING"
STATE = "CP88_AMPLIFICATION_ENGINE_OFFLINE_MATERIAL_DELTA_DUPLICATE_GUARDED_CAPABILITY_RIGHTS_GATED_NO_EXTERNAL_WRITE_LIVE_HOLD"
UNKNOWN_EXTERNAL_METRIC_VALUE = "UNKNOWN"

ACTIVE_PLATFORMS = ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
CANDIDATE_KINDS = ("OWN_POST", "COMMENT_THREAD", "PUBLIC_CONVERSATION")
ACTION_KINDS = ("FOLLOW_UP_POST", "SECOND_POST", "EXPLAINER", "CORRECTION", "CONTENT_IDEA", "QUOTE_REPOST")
DECISION_STATES = ("SELECTED_OFFLINE", "MANUAL_ACTION_PACKET", "NO_ACTION", "HOLD")
ALLOWED_CAPABILITY_CLASSIFICATIONS = ("PASS_OFFLINE_CONTRACT", "HOLD_LIVE_PERMISSION", "UNSUPPORTED", "MANUAL_ONLY")

MAX_REF = 300
MAX_TOPIC = 240
MAX_TEXT = 800
MAX_BATCH = 100
WS_RE = re.compile(r"\s+")


class AmplificationHold(ValueError):
    """Fail-closed CP88 contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _norm_text(value: str, *, name: str, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AmplificationHold(f"HOLD_CP88_{name.upper()}_TYPE")
    value = WS_RE.sub(" ", value).strip()
    if not value and not allow_empty:
        raise AmplificationHold(f"HOLD_CP88_{name.upper()}_MISSING")
    if len(value) > max_len:
        raise AmplificationHold(f"HOLD_CP88_{name.upper()}_TOO_LONG")
    return value


def _norm_utc(value: str) -> str:
    value = _norm_text(value, name="observed_at_utc", max_len=40)
    if not value.endswith("Z"):
        raise AmplificationHold("HOLD_CP88_OBSERVED_AT_NOT_UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AmplificationHold("HOLD_CP88_OBSERVED_AT_INVALID") from exc
    if parsed.tzinfo != timezone.utc:
        raise AmplificationHold("HOLD_CP88_OBSERVED_AT_NOT_UTC")
    return parsed.isoformat().replace("+00:00", "Z")


def _score(value: int, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise AmplificationHold(f"HOLD_CP88_{name.upper()}_INVALID")
    return value


@dataclass(frozen=True)
class AmplificationContract:
    contract_id: str
    contract_hash: str
    policy_sha256: str
    minimum_amplification_score: int
    minimum_novelty_score: int
    minimum_material_delta_score: int
    strong_thread_quality_score: int
    strong_thread_depth: int
    correction_need_score: int
    score_weights: Mapping[str, float]
    quote_repost_capability_baseline: Mapping[str, Mapping[str, str]]
    max_batch: int
    checkpoint: str = CHECKPOINT
    parent_activation_checkpoint: str = PARENT_ACTIVATION_CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    next_unit: str = NEXT_UNIT
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    global_kill_switch_engaged: bool = True
    material_new_information_required: bool = True
    duplicate_posting_forbidden: bool = True
    repetitive_self_amplification_forbidden: bool = True
    quote_repost_rights_context_required: bool = True
    posting_authority: bool = False
    external_write_allowed: bool = False
    network_allowed: bool = False
    live_probe_allowed: bool = False
    oauth_allowed: bool = False
    account_connection_allowed: bool = False
    automated_targeting_allowed: bool = False
    control_plane_promoted: bool = False
    deploy_allowed: bool = False
    paid_service_allowed: bool = False
    external_metrics: str = UNKNOWN_EXTERNAL_METRIC_VALUE
    state: str = STATE

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["score_weights"] = dict(self.score_weights)
        value["quote_repost_capability_baseline"] = {
            k: dict(v) for k, v in self.quote_repost_capability_baseline.items()
        }
        return value


@dataclass(frozen=True)
class AmplificationCandidate:
    platform: str
    candidate_kind: str
    source_ref: str
    conversation_ref: str
    topic: str
    observed_at_utc: str
    provenance_ref: str
    relevance_score: int
    substance_score: int
    novelty_score: int
    followup_value_score: int
    explanation_value_score: int
    material_delta_score: int
    thread_quality_score: int = 0
    conversation_depth: int = 0
    correction_need_score: int = 0
    thread_takeaway: str = ""
    material_new_information: bool = True
    source_is_public: bool = True
    rights_context_passed: bool = False
    context_integrity_passed: bool = False
    quote_repost_requested: bool = False
    sensitive_trait_data_present: bool = False
    sensitive_trait_inference_requested: bool = False
    sensitive_relationship_profiling_requested: bool = False
    political_microtargeting_requested: bool = False
    synthetic_conversation_farming_requested: bool = False
    conflict_fabrication_requested: bool = False


@dataclass(frozen=True)
class ManualActionPacket:
    packet_id: str
    platform: str
    requested_action: str
    source_ref: str
    conversation_ref: str
    topic: str
    capability_classification: str
    automation_mode: str
    live_gate: str
    required_human_checks: tuple[str, ...]
    execution_status: str = "MANUAL_ONLY_NOT_AUTHORITY"
    external_write_attempted: bool = False
    network_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_human_checks"] = list(self.required_human_checks)
        return value


@dataclass(frozen=True)
class ContentIdea:
    idea_id: str
    topic: str
    source_ref: str
    seed: str
    origin: str = "STRONG_PUBLIC_CONVERSATION"
    status: str = "FUTURE_CONTENT_IDEA_OFFLINE_ONLY"


@dataclass(frozen=True)
class AmplificationDecision:
    event_id: str
    decision_state: str
    recommended_action: str | None
    amplification_score: float
    reason: str
    source_ref: str
    platform: str
    content_idea: ContentIdea | None = None
    manual_action_packet: ManualActionPacket | None = None
    idempotent_replay: bool = False
    external_write_allowed: bool = False
    external_write_attempted: bool = False
    network_fetch_performed: bool = False
    posting_authority: bool = False
    automated_targeting_allowed: bool = False
    external_metrics: str = UNKNOWN_EXTERNAL_METRIC_VALUE

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.content_idea is not None:
            value["content_idea"] = asdict(self.content_idea)
        if self.manual_action_packet is not None:
            value["manual_action_packet"] = self.manual_action_packet.to_dict()
        return value


@dataclass
class AmplificationState:
    receipts: dict[str, tuple[str, AmplificationDecision]] = field(default_factory=dict)
    source_action_fingerprints: set[str] = field(default_factory=set)
    idea_fingerprints: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipts": {
                k: {"payload_hash": v[0], "decision": v[1].to_dict()}
                for k, v in sorted(self.receipts.items())
            },
            "source_action_fingerprints": sorted(self.source_action_fingerprints),
            "idea_fingerprints": sorted(self.idea_fingerprints),
        }


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"),
        policy.get("checkpoint"),
        policy.get("module_id"),
        policy.get("parent_activation_checkpoint"),
        policy.get("parent_control_checkpoint"),
        policy.get("next_after_cp88"),
    )
    expected = (
        "PPOS_AMPLIFICATION_ENGINE_POLICY_V1",
        CHECKPOINT,
        "M57_AMPLIFICATION_ENGINE",
        PARENT_ACTIVATION_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        NEXT_UNIT,
    )
    if identity != expected:
        raise AmplificationHold("HOLD_CP88_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise AmplificationHold("HOLD_CP88_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("candidate_kinds", ())) != CANDIDATE_KINDS:
        raise AmplificationHold("HOLD_CP88_CANDIDATE_KIND_DRIFT")
    if tuple(policy.get("action_kinds", ())) != ACTION_KINDS:
        raise AmplificationHold("HOLD_CP88_ACTION_KIND_DRIFT")
    if tuple(policy.get("decision_states", ())) != DECISION_STATES:
        raise AmplificationHold("HOLD_CP88_DECISION_STATE_DRIFT")
    if policy.get("global_kill_switch") != "ENGAGED":
        raise AmplificationHold("HOLD_CP88_KILL_SWITCH_NOT_ENGAGED")
    if policy.get("unknown_external_metric_value") != UNKNOWN_EXTERNAL_METRIC_VALUE:
        raise AmplificationHold("HOLD_CP88_UNKNOWN_METRIC_DRIFT")

    authority = policy.get("authority")
    if not isinstance(authority, Mapping) or not authority:
        raise AmplificationHold("HOLD_CP88_AUTHORITY_MISSING")
    if any(value is not False for value in authority.values()):
        raise AmplificationHold("HOLD_CP88_LIVE_AUTHORITY_DRIFT")

    safety = policy.get("safety")
    if not isinstance(safety, Mapping):
        raise AmplificationHold("HOLD_CP88_SAFETY_POLICY_MISSING")
    required_true = (
        "material_new_information_required",
        "duplicate_posting_forbidden",
        "repetitive_self_amplification_forbidden",
        "quote_repost_rights_context_required",
        "quote_repost_context_integrity_required",
        "capability_unknown_fail_closed",
        "manual_packet_when_api_write_not_supported",
        "political_microtargeting_forbidden",
        "sensitive_trait_inference_forbidden",
        "sensitive_relationship_profiling_forbidden",
        "synthetic_conversation_farming_forbidden",
        "clickbait_conflict_fabrication_forbidden",
    )
    if any(safety.get(key) is not True for key in required_true):
        raise AmplificationHold("HOLD_CP88_SAFETY_POLICY_WEAKENED")

    thresholds = policy.get("quality_thresholds")
    if not isinstance(thresholds, Mapping):
        raise AmplificationHold("HOLD_CP88_THRESHOLDS_MISSING")
    for key in (
        "minimum_amplification_score",
        "minimum_novelty_score",
        "minimum_material_delta_score",
        "strong_thread_quality_score",
        "correction_need_score",
    ):
        value = thresholds.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise AmplificationHold("HOLD_CP88_THRESHOLD_INVALID")
    depth = thresholds.get("strong_thread_depth")
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 50:
        raise AmplificationHold("HOLD_CP88_THRESHOLD_INVALID")

    weights = policy.get("score_weights")
    if not isinstance(weights, Mapping):
        raise AmplificationHold("HOLD_CP88_SCORE_WEIGHTS_MISSING")
    expected_keys = {"relevance", "substance", "novelty", "followup_value", "explanation_value"}
    if set(weights) != expected_keys:
        raise AmplificationHold("HOLD_CP88_SCORE_WEIGHT_KEYS")
    try:
        total = sum(float(weights[k]) for k in expected_keys)
    except (TypeError, ValueError) as exc:
        raise AmplificationHold("HOLD_CP88_SCORE_WEIGHT_INVALID") from exc
    if any(isinstance(weights[k], bool) or not 0 <= float(weights[k]) <= 1 for k in expected_keys):
        raise AmplificationHold("HOLD_CP88_SCORE_WEIGHT_INVALID")
    if abs(total - 1.0) > 1e-9:
        raise AmplificationHold("HOLD_CP88_SCORE_WEIGHT_SUM")

    baseline = policy.get("quote_repost_capability_baseline")
    if not isinstance(baseline, Mapping) or set(baseline) != set(ACTIVE_PLATFORMS):
        raise AmplificationHold("HOLD_CP88_QUOTE_REPOST_BASELINE_DRIFT")
    expected_baseline = {
        "FACEBOOK_PAGE": ("MANUAL_ONLY", "MANUAL_ACTION_PACKET", "HOLD_LIVE_PERMISSION"),
        "INSTAGRAM_PROFESSIONAL": ("UNSUPPORTED", "MANUAL_ACTION_PACKET", "HOLD_CAPABILITY_UNVERIFIED"),
        "THREADS": ("MANUAL_ONLY", "MANUAL_ACTION_PACKET", "HOLD_LIVE_PERMISSION"),
    }
    for platform, expected_values in expected_baseline.items():
        row = baseline.get(platform)
        if not isinstance(row, Mapping):
            raise AmplificationHold("HOLD_CP88_QUOTE_REPOST_BASELINE_DRIFT")
        actual = (row.get("classification"), row.get("automation_mode"), row.get("live_gate"))
        if actual != expected_values:
            raise AmplificationHold("HOLD_CP88_QUOTE_REPOST_BASELINE_DRIFT")
        if actual[0] not in ALLOWED_CAPABILITY_CLASSIFICATIONS:
            raise AmplificationHold("HOLD_CP88_QUOTE_REPOST_BASELINE_DRIFT")

    max_batch = policy.get("max_batch")
    if isinstance(max_batch, bool) or not isinstance(max_batch, int) or not 1 <= max_batch <= MAX_BATCH:
        raise AmplificationHold("HOLD_CP88_MAX_BATCH_INVALID")


def compile_amplification_engine(policy: Mapping[str, Any]) -> AmplificationContract:
    validate_policy(policy)
    thresholds = policy["quality_thresholds"]
    payload = {
        "checkpoint": CHECKPOINT,
        "parent_activation_checkpoint": PARENT_ACTIVATION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "next_unit": NEXT_UNIT,
        "active_platforms": list(ACTIVE_PLATFORMS),
        "candidate_kinds": list(CANDIDATE_KINDS),
        "action_kinds": list(ACTION_KINDS),
        "quality_thresholds": thresholds,
        "score_weights": policy["score_weights"],
        "quote_repost_capability_baseline": policy["quote_repost_capability_baseline"],
        "safety": policy["safety"],
        "authority": policy["authority"],
        "global_kill_switch": policy["global_kill_switch"],
    }
    digest = _hash(payload)
    return AmplificationContract(
        contract_id=f"ppos-cp88-{digest[:16]}",
        contract_hash=digest,
        policy_sha256=_hash(policy),
        minimum_amplification_score=thresholds["minimum_amplification_score"],
        minimum_novelty_score=thresholds["minimum_novelty_score"],
        minimum_material_delta_score=thresholds["minimum_material_delta_score"],
        strong_thread_quality_score=thresholds["strong_thread_quality_score"],
        strong_thread_depth=thresholds["strong_thread_depth"],
        correction_need_score=thresholds["correction_need_score"],
        score_weights={k: float(v) for k, v in policy["score_weights"].items()},
        quote_repost_capability_baseline={
            k: dict(v) for k, v in policy["quote_repost_capability_baseline"].items()
        },
        max_batch=policy["max_batch"],
    )


def _normalized_candidate(candidate: AmplificationCandidate) -> dict[str, Any]:
    if candidate.platform not in ACTIVE_PLATFORMS:
        raise AmplificationHold("HOLD_CAPABILITY_UNVERIFIED")
    if candidate.candidate_kind not in CANDIDATE_KINDS:
        raise AmplificationHold("HOLD_CP88_CANDIDATE_KIND_INVALID")
    if candidate.source_is_public is not True:
        raise AmplificationHold("HOLD_CP88_PUBLIC_SOURCE_REQUIRED")
    if candidate.sensitive_trait_data_present or candidate.sensitive_trait_inference_requested:
        raise AmplificationHold("HOLD_CP88_SENSITIVE_TRAIT_SIGNAL_FORBIDDEN")
    if candidate.sensitive_relationship_profiling_requested:
        raise AmplificationHold("HOLD_CP88_SENSITIVE_RELATIONSHIP_PROFILING_FORBIDDEN")
    if candidate.political_microtargeting_requested:
        raise AmplificationHold("HOLD_CP88_POLITICAL_MICROTARGETING_FORBIDDEN")
    if candidate.synthetic_conversation_farming_requested:
        raise AmplificationHold("HOLD_CP88_SYNTHETIC_CONVERSATION_FARMING_FORBIDDEN")
    if candidate.conflict_fabrication_requested:
        raise AmplificationHold("HOLD_CP88_CONFLICT_FABRICATION_FORBIDDEN")
    if not isinstance(candidate.material_new_information, bool):
        raise AmplificationHold("HOLD_CP88_MATERIAL_NEW_INFORMATION_TYPE")
    if not isinstance(candidate.rights_context_passed, bool) or not isinstance(candidate.context_integrity_passed, bool):
        raise AmplificationHold("HOLD_CP88_RIGHTS_CONTEXT_TYPE")
    if not isinstance(candidate.quote_repost_requested, bool):
        raise AmplificationHold("HOLD_CP88_QUOTE_REPOST_REQUEST_TYPE")
    if isinstance(candidate.conversation_depth, bool) or not isinstance(candidate.conversation_depth, int):
        raise AmplificationHold("HOLD_CP88_CONVERSATION_DEPTH_INVALID")
    if not 0 <= candidate.conversation_depth <= 1000:
        raise AmplificationHold("HOLD_CP88_CONVERSATION_DEPTH_INVALID")

    takeaway = _norm_text(candidate.thread_takeaway, name="thread_takeaway", max_len=MAX_TEXT, allow_empty=True)
    return {
        "platform": candidate.platform,
        "candidate_kind": candidate.candidate_kind,
        "source_ref": _norm_text(candidate.source_ref, name="source_ref", max_len=MAX_REF),
        "conversation_ref": _norm_text(candidate.conversation_ref, name="conversation_ref", max_len=MAX_REF),
        "topic": _norm_text(candidate.topic, name="topic", max_len=MAX_TOPIC),
        "observed_at_utc": _norm_utc(candidate.observed_at_utc),
        "provenance_ref": _norm_text(candidate.provenance_ref, name="provenance_ref", max_len=MAX_REF),
        "relevance_score": _score(candidate.relevance_score, name="relevance_score"),
        "substance_score": _score(candidate.substance_score, name="substance_score"),
        "novelty_score": _score(candidate.novelty_score, name="novelty_score"),
        "followup_value_score": _score(candidate.followup_value_score, name="followup_value_score"),
        "explanation_value_score": _score(candidate.explanation_value_score, name="explanation_value_score"),
        "material_delta_score": _score(candidate.material_delta_score, name="material_delta_score"),
        "thread_quality_score": _score(candidate.thread_quality_score, name="thread_quality_score"),
        "conversation_depth": candidate.conversation_depth,
        "correction_need_score": _score(candidate.correction_need_score, name="correction_need_score"),
        "thread_takeaway": takeaway,
        "material_new_information": candidate.material_new_information,
        "rights_context_passed": candidate.rights_context_passed,
        "context_integrity_passed": candidate.context_integrity_passed,
        "quote_repost_requested": candidate.quote_repost_requested,
    }


def _amplification_score(contract: AmplificationContract, value: Mapping[str, Any]) -> float:
    weights = contract.score_weights
    score = (
        value["relevance_score"] * weights["relevance"]
        + value["substance_score"] * weights["substance"]
        + value["novelty_score"] * weights["novelty"]
        + value["followup_value_score"] * weights["followup_value"]
        + value["explanation_value_score"] * weights["explanation_value"]
    )
    return round(score, 2)


def _event_id(value: Mapping[str, Any]) -> str:
    return "amp_evt_" + _hash(value)[:24]


def _receipt_key(value: Mapping[str, Any]) -> str:
    return "receipt_" + _hash([value["platform"], value["provenance_ref"]])[:24]


def _source_action_fingerprint(value: Mapping[str, Any], action: str) -> str:
    return _hash([value["platform"], value["source_ref"], action, value["topic"]])


def _idea_fingerprint(value: Mapping[str, Any]) -> str:
    return _hash([value["topic"].lower(), value["thread_takeaway"].lower()])


def _manual_quote_repost_packet(
    contract: AmplificationContract,
    value: Mapping[str, Any],
) -> ManualActionPacket:
    if not value["rights_context_passed"] or not value["context_integrity_passed"]:
        raise AmplificationHold("HOLD_CP88_QUOTE_REPOST_RIGHTS_CONTEXT_REQUIRED")
    row = contract.quote_repost_capability_baseline.get(value["platform"])
    if not isinstance(row, Mapping):
        raise AmplificationHold("HOLD_CAPABILITY_UNVERIFIED")
    classification = row.get("classification")
    automation_mode = row.get("automation_mode")
    live_gate = row.get("live_gate")
    if classification not in ALLOWED_CAPABILITY_CLASSIFICATIONS:
        raise AmplificationHold("HOLD_CAPABILITY_UNVERIFIED")
    if automation_mode != "MANUAL_ACTION_PACKET":
        raise AmplificationHold("HOLD_CP88_QUOTE_REPOST_AUTOMATION_MODE_DRIFT")
    packet_payload = [
        value["platform"],
        value["source_ref"],
        value["conversation_ref"],
        value["topic"],
        classification,
        live_gate,
    ]
    return ManualActionPacket(
        packet_id="manual_amp_" + _hash(packet_payload)[:24],
        platform=value["platform"],
        requested_action="QUOTE_REPOST",
        source_ref=value["source_ref"],
        conversation_ref=value["conversation_ref"],
        topic=value["topic"],
        capability_classification=str(classification),
        automation_mode=str(automation_mode),
        live_gate=str(live_gate),
        required_human_checks=(
            "RECONFIRM_OFFICIAL_CAPABILITY_AT_ACTION_TIME",
            "RECONFIRM_RIGHTS_AND_ATTRIBUTION",
            "RECONFIRM_CONTEXT_INTEGRITY",
            "RECONFIRM_OWNER_AUTHORIZATION",
            "NO_AUTOMATED_WRITE_FROM_CP88",
        ),
    )


def _select_action(
    contract: AmplificationContract,
    value: Mapping[str, Any],
    score: float,
) -> tuple[str, str | None, str]:
    if value["quote_repost_requested"]:
        return ("MANUAL_ACTION_PACKET", "QUOTE_REPOST", "QUOTE_REPOST_CAPABILITY_GATED_MANUAL_ONLY")

    if value["correction_need_score"] >= contract.correction_need_score:
        if not value["material_new_information"] or value["material_delta_score"] < contract.minimum_material_delta_score:
            return ("NO_ACTION", None, "CORRECTION_LACKS_MATERIAL_DELTA")
        return ("SELECTED_OFFLINE", "CORRECTION", "MATERIAL_CORRECTION_MERITS_FOLLOW_UP")

    strong_thread = (
        value["candidate_kind"] == "COMMENT_THREAD"
        and value["thread_quality_score"] >= contract.strong_thread_quality_score
        and value["conversation_depth"] >= contract.strong_thread_depth
        and bool(value["thread_takeaway"])
    )
    if strong_thread:
        if value["explanation_value_score"] >= 80 and value["material_delta_score"] >= contract.minimum_material_delta_score:
            return ("SELECTED_OFFLINE", "EXPLAINER", "STRONG_THREAD_MERITS_EXPLAINER")
        return ("SELECTED_OFFLINE", "CONTENT_IDEA", "STRONG_THREAD_CONVERTED_TO_FUTURE_CONTENT_IDEA")

    if not value["material_new_information"]:
        return ("NO_ACTION", None, "NO_MATERIAL_NEW_INFORMATION")
    if value["material_delta_score"] < contract.minimum_material_delta_score:
        return ("NO_ACTION", None, "MATERIAL_DELTA_BELOW_THRESHOLD")
    if value["novelty_score"] < contract.minimum_novelty_score:
        return ("NO_ACTION", None, "NOVELTY_BELOW_THRESHOLD")
    if score < contract.minimum_amplification_score:
        return ("NO_ACTION", None, "AMPLIFICATION_SCORE_BELOW_THRESHOLD")

    if value["candidate_kind"] == "OWN_POST":
        if value["explanation_value_score"] >= 80:
            return ("SELECTED_OFFLINE", "EXPLAINER", "OWN_POST_MERITS_DEEPER_EXPLANATION")
        if value["followup_value_score"] >= 80 and value["novelty_score"] >= 70:
            return ("SELECTED_OFFLINE", "SECOND_POST", "OWN_POST_MERITS_DISTINCT_SECOND_POST")
        return ("SELECTED_OFFLINE", "FOLLOW_UP_POST", "OWN_POST_MERITS_MATERIAL_FOLLOW_UP")

    if value["candidate_kind"] == "PUBLIC_CONVERSATION":
        if value["explanation_value_score"] >= 80:
            return ("SELECTED_OFFLINE", "EXPLAINER", "PUBLIC_CONVERSATION_MERITS_EXPLAINER")
        return ("SELECTED_OFFLINE", "CONTENT_IDEA", "PUBLIC_CONVERSATION_MERITS_FUTURE_CONTENT_IDEA")

    return ("NO_ACTION", None, "NO_ELIGIBLE_AMPLIFICATION_MODE")


def evaluate_candidate(
    contract: AmplificationContract,
    state: AmplificationState,
    candidate: AmplificationCandidate,
) -> AmplificationDecision:
    value = _normalized_candidate(candidate)
    payload_hash = _hash(value)
    receipt_key = _receipt_key(value)
    prior = state.receipts.get(receipt_key)
    if prior is not None:
        prior_hash, prior_decision = prior
        if prior_hash != payload_hash:
            raise AmplificationHold("HOLD_CP88_CONFLICTING_DUPLICATE_PROVENANCE")
        replay = AmplificationDecision(
            **{
                **prior_decision.__dict__,
                "idempotent_replay": True,
            }
        )
        return replay

    score = _amplification_score(contract, value)
    decision_state, action, reason = _select_action(contract, value, score)
    manual_packet: ManualActionPacket | None = None
    content_idea: ContentIdea | None = None

    if decision_state == "MANUAL_ACTION_PACKET":
        manual_packet = _manual_quote_repost_packet(contract, value)

    if action in {"CONTENT_IDEA", "EXPLAINER"} and value["candidate_kind"] in {"COMMENT_THREAD", "PUBLIC_CONVERSATION"}:
        seed = value["thread_takeaway"] or f"Develop a future explainer on {value['topic']} from {value['source_ref']}."
        idea_fp = _idea_fingerprint(value)
        if idea_fp in state.idea_fingerprints:
            raise AmplificationHold("HOLD_CP88_DUPLICATE_CONTENT_IDEA")
        content_idea = ContentIdea(
            idea_id="idea_" + idea_fp[:24],
            topic=value["topic"],
            source_ref=value["source_ref"],
            seed=seed,
        )

    if action is not None and decision_state in {"SELECTED_OFFLINE", "MANUAL_ACTION_PACKET"}:
        fingerprint = _source_action_fingerprint(value, action)
        if fingerprint in state.source_action_fingerprints:
            raise AmplificationHold("HOLD_CP88_DUPLICATE_OR_REPETITIVE_AMPLIFICATION")
    else:
        fingerprint = None

    event_id = _event_id(value)
    decision = AmplificationDecision(
        event_id=event_id,
        decision_state=decision_state,
        recommended_action=action,
        amplification_score=score,
        reason=reason,
        source_ref=value["source_ref"],
        platform=value["platform"],
        content_idea=content_idea,
        manual_action_packet=manual_packet,
    )

    # Mutate state only after all fail-closed checks have passed.
    if fingerprint is not None:
        state.source_action_fingerprints.add(fingerprint)
    if content_idea is not None:
        state.idea_fingerprints.add(_idea_fingerprint(value))
    state.receipts[receipt_key] = (payload_hash, decision)
    return decision


def process_batch(
    contract: AmplificationContract,
    state: AmplificationState,
    candidates: Sequence[AmplificationCandidate],
) -> tuple[AmplificationDecision, ...]:
    if len(candidates) > contract.max_batch:
        raise AmplificationHold("HOLD_CP88_BATCH_LIMIT_EXCEEDED")
    if not candidates:
        return ()
    snapshot = AmplificationState(
        receipts=dict(state.receipts),
        source_action_fingerprints=set(state.source_action_fingerprints),
        idea_fingerprints=set(state.idea_fingerprints),
    )
    results: list[AmplificationDecision] = []
    try:
        for candidate in candidates:
            results.append(evaluate_candidate(contract, state, candidate))
    except Exception:
        state.receipts = snapshot.receipts
        state.source_action_fingerprints = snapshot.source_action_fingerprints
        state.idea_fingerprints = snapshot.idea_fingerprints
        raise
    return tuple(results)
