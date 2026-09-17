from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

MODEL_VERSION = "PPOS_RELATIONSHIP_GRAPH_V1"
ENGINE_VERSION = "ppos-relationship-graph-v1.0.0"
CHECKPOINT = "CP87"
PARENT_ACTIVATION_CHECKPOINT = "CP86"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP88_AMPLIFICATION_ENGINE"
STATE = "CP87_RELATIONSHIP_GRAPH_OFFLINE_PUBLIC_NON_SENSITIVE_IDEMPOTENT_CONTINUITY_ONLY_NO_EXTERNAL_WRITE_LIVE_HOLD"
UNKNOWN_EXTERNAL_METRIC_VALUE = "UNKNOWN"

ACTIVE_PLATFORMS = ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
INPUT_EDGE_TYPES = ("replied_to", "mentioned", "quoted")
DERIVED_EDGE_TYPES = ("recurring_interaction", "shared_topic", "prior_useful_exchange")
EDGE_TYPES = INPUT_EDGE_TYPES + DERIVED_EDGE_TYPES
NODE_TYPES = ("public_account", "content", "conversation")
MAX_REF = 300
MAX_TOPIC = 240
MAX_BATCH = 100
WS_RE = re.compile(r"\s+")


class RelationshipGraphHold(ValueError):
    """Fail-closed CP87 contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _norm_text(value: str, *, name: str, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise RelationshipGraphHold(f"HOLD_CP87_{name.upper()}_TYPE")
    value = WS_RE.sub(" ", value).strip()
    if not value and not allow_empty:
        raise RelationshipGraphHold(f"HOLD_CP87_{name.upper()}_MISSING")
    if len(value) > max_len:
        raise RelationshipGraphHold(f"HOLD_CP87_{name.upper()}_TOO_LONG")
    return value


def _norm_utc(value: str) -> str:
    value = _norm_text(value, name="observed_at_utc", max_len=40)
    if not value.endswith("Z"):
        raise RelationshipGraphHold("HOLD_CP87_OBSERVED_AT_NOT_UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RelationshipGraphHold("HOLD_CP87_OBSERVED_AT_INVALID") from exc
    if parsed.tzinfo != timezone.utc:
        raise RelationshipGraphHold("HOLD_CP87_OBSERVED_AT_NOT_UTC")
    return parsed.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RelationshipGraphContract:
    contract_id: str
    contract_hash: str
    policy_sha256: str
    repeat_interaction_min_count: int
    useful_exchange_min_quality: int
    repeat_bonus_points: int
    repeat_bonus_cap: int
    mean_quality_weight: float
    max_batch: int
    checkpoint: str = CHECKPOINT
    parent_activation_checkpoint: str = PARENT_ACTIVATION_CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    next_unit: str = NEXT_UNIT
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    global_kill_switch_engaged: bool = True
    continuity_context_only: bool = True
    sensitive_trait_inference_allowed: bool = False
    sensitive_relationship_profiling_allowed: bool = False
    political_microtargeting_allowed: bool = False
    automated_targeting_allowed: bool = False
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
        return asdict(self)


@dataclass(frozen=True)
class InteractionEvent:
    platform: str
    source_public_id: str
    peer_public_id: str
    interaction_kind: str
    conversation_ref: str
    content_ref: str
    topic: str
    observed_at_utc: str
    quality_score: int
    provenance_ref: str
    public_visibility_confirmed: bool = True
    evidence_is_public: bool = True
    sensitive_trait_data_present: bool = False
    sensitive_relationship_profiling_requested: bool = False
    political_microtargeting_requested: bool = False
    extra_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    platform: str
    public_ref: str


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    edge_type: str
    platform: str
    source_node_id: str
    target_node_id: str
    first_seen_utc: str
    last_seen_utc: str
    interaction_count: int
    quality_sum: int
    quality_mean: float
    topic: str | None = None
    conversation_ref: str | None = None
    content_ref: str | None = None


@dataclass(frozen=True)
class RelationshipSummary:
    pair_id: str
    platform: str
    source_public_id: str
    peer_public_id: str
    interaction_count: int
    useful_exchange_count: int
    quality_sum: int
    quality_mean: float
    relationship_score: float
    score_basis: str = "REPEATED_PUBLIC_INTERACTION_QUALITY_ONLY"
    permitted_use: str = "CONTINUITY_CONTEXT_ONLY_NOT_ACTION_AUTHORITY"


@dataclass
class RelationshipGraphState:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: dict[str, GraphEdge] = field(default_factory=dict)
    relationships: dict[str, RelationshipSummary] = field(default_factory=dict)
    receipts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {k: asdict(v) for k, v in sorted(self.nodes.items())},
            "edges": {k: asdict(v) for k, v in sorted(self.edges.items())},
            "relationships": {k: asdict(v) for k, v in sorted(self.relationships.items())},
            "receipts": dict(sorted(self.receipts.items())),
        }


@dataclass(frozen=True)
class RelationshipGraphResult:
    event_id: str
    pair_id: str
    relationship_score: float
    interaction_count: int
    edge_types_present: tuple[str, ...]
    idempotent_replay: bool
    state_hash: str
    external_write_allowed: bool = False
    external_write_attempted: bool = False
    network_fetch_performed: bool = False
    posting_authority: bool = False
    automated_targeting_allowed: bool = False
    permitted_use: str = "CONTINUITY_CONTEXT_ONLY_NOT_ACTION_AUTHORITY"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["edge_types_present"] = list(self.edge_types_present)
        return value


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"),
        policy.get("checkpoint"),
        policy.get("module_id"),
        policy.get("parent_activation_checkpoint"),
        policy.get("parent_control_checkpoint"),
        policy.get("next_after_cp87"),
    )
    expected = (
        "PPOS_RELATIONSHIP_GRAPH_POLICY_V1",
        CHECKPOINT,
        "M56_RELATIONSHIP_GRAPH",
        PARENT_ACTIVATION_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        NEXT_UNIT,
    )
    if identity != expected:
        raise RelationshipGraphHold("HOLD_CP87_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise RelationshipGraphHold("HOLD_CP87_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("input_edge_types", ())) != INPUT_EDGE_TYPES:
        raise RelationshipGraphHold("HOLD_CP87_INPUT_EDGE_DRIFT")
    if tuple(policy.get("derived_edge_types", ())) != DERIVED_EDGE_TYPES:
        raise RelationshipGraphHold("HOLD_CP87_DERIVED_EDGE_DRIFT")
    if tuple(policy.get("node_types", ())) != NODE_TYPES:
        raise RelationshipGraphHold("HOLD_CP87_NODE_TYPE_DRIFT")
    if policy.get("global_kill_switch") != "ENGAGED":
        raise RelationshipGraphHold("HOLD_CP87_KILL_SWITCH_NOT_ENGAGED")
    if policy.get("unknown_external_metric_value") != UNKNOWN_EXTERNAL_METRIC_VALUE:
        raise RelationshipGraphHold("HOLD_CP87_UNKNOWN_METRIC_DRIFT")

    authority = policy.get("authority")
    if not isinstance(authority, Mapping) or not authority:
        raise RelationshipGraphHold("HOLD_CP87_AUTHORITY_MISSING")
    if any(value is not False for value in authority.values()):
        raise RelationshipGraphHold("HOLD_CP87_LIVE_AUTHORITY_DRIFT")

    privacy = policy.get("privacy")
    if not isinstance(privacy, Mapping):
        raise RelationshipGraphHold("HOLD_CP87_PRIVACY_POLICY_MISSING")
    required_true = (
        "public_identifiers_only",
        "public_interaction_metadata_only",
        "extra_metadata_forbidden",
        "sensitive_trait_inference_forbidden",
        "sensitive_relationship_profiling_forbidden",
        "political_microtargeting_forbidden",
        "demographic_scoring_forbidden",
    )
    if any(privacy.get(key) is not True for key in required_true):
        raise RelationshipGraphHold("HOLD_CP87_PRIVACY_POLICY_WEAKENED")
    if privacy.get("relationship_score_basis") != "REPEATED_PUBLIC_INTERACTION_QUALITY_ONLY":
        raise RelationshipGraphHold("HOLD_CP87_SCORE_BASIS_DRIFT")
    if privacy.get("permitted_use") != "CONTINUITY_CONTEXT_ONLY_NOT_ACTION_AUTHORITY":
        raise RelationshipGraphHold("HOLD_CP87_PERMITTED_USE_DRIFT")

    score = policy.get("relationship_score")
    if not isinstance(score, Mapping):
        raise RelationshipGraphHold("HOLD_CP87_SCORE_POLICY_MISSING")
    params = (
        score.get("repeat_interaction_min_count"),
        score.get("useful_exchange_min_quality"),
        score.get("repeat_bonus_points"),
        score.get("repeat_bonus_cap"),
        score.get("mean_quality_weight"),
    )
    if any(isinstance(v, bool) for v in params):
        raise RelationshipGraphHold("HOLD_CP87_SCORE_POLICY_INVALID")
    repeat_min, useful_min, bonus_points, bonus_cap, weight = params
    if not isinstance(repeat_min, int) or not 2 <= repeat_min <= 10:
        raise RelationshipGraphHold("HOLD_CP87_SCORE_POLICY_INVALID")
    if not isinstance(useful_min, int) or not 1 <= useful_min <= 100:
        raise RelationshipGraphHold("HOLD_CP87_SCORE_POLICY_INVALID")
    if not isinstance(bonus_points, int) or not 0 <= bonus_points <= 20:
        raise RelationshipGraphHold("HOLD_CP87_SCORE_POLICY_INVALID")
    if not isinstance(bonus_cap, int) or not 0 <= bonus_cap <= 10:
        raise RelationshipGraphHold("HOLD_CP87_SCORE_POLICY_INVALID")
    if not isinstance(weight, (int, float)) or not 0 < float(weight) <= 1:
        raise RelationshipGraphHold("HOLD_CP87_SCORE_POLICY_INVALID")
    if score.get("formula") != "MEAN_QUALITY_WEIGHTED_PLUS_BOUNDED_REPEAT_BONUS_CAPPED_100":
        raise RelationshipGraphHold("HOLD_CP87_SCORE_FORMULA_DRIFT")
    max_batch = policy.get("max_batch")
    if isinstance(max_batch, bool) or not isinstance(max_batch, int) or not 1 <= max_batch <= MAX_BATCH:
        raise RelationshipGraphHold("HOLD_CP87_MAX_BATCH_INVALID")


def compile_relationship_graph(policy: Mapping[str, Any]) -> RelationshipGraphContract:
    validate_policy(policy)
    score = policy["relationship_score"]
    payload = {
        "checkpoint": CHECKPOINT,
        "parent_activation_checkpoint": PARENT_ACTIVATION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "next_unit": NEXT_UNIT,
        "active_platforms": list(ACTIVE_PLATFORMS),
        "node_types": list(NODE_TYPES),
        "input_edge_types": list(INPUT_EDGE_TYPES),
        "derived_edge_types": list(DERIVED_EDGE_TYPES),
        "privacy": policy["privacy"],
        "relationship_score": score,
        "authority": policy["authority"],
        "global_kill_switch": policy["global_kill_switch"],
    }
    digest = _hash(payload)
    return RelationshipGraphContract(
        contract_id=f"ppos-cp87-{digest[:16]}",
        contract_hash=digest,
        policy_sha256=_hash(policy),
        repeat_interaction_min_count=score["repeat_interaction_min_count"],
        useful_exchange_min_quality=score["useful_exchange_min_quality"],
        repeat_bonus_points=score["repeat_bonus_points"],
        repeat_bonus_cap=score["repeat_bonus_cap"],
        mean_quality_weight=float(score["mean_quality_weight"]),
        max_batch=policy["max_batch"],
    )


def _normalized_event(event: InteractionEvent) -> dict[str, Any]:
    if event.platform not in ACTIVE_PLATFORMS:
        raise RelationshipGraphHold("HOLD_CAPABILITY_UNVERIFIED")
    if event.interaction_kind not in INPUT_EDGE_TYPES:
        raise RelationshipGraphHold("HOLD_CP87_INTERACTION_KIND_INVALID")
    if event.public_visibility_confirmed is not True or event.evidence_is_public is not True:
        raise RelationshipGraphHold("HOLD_CP87_PUBLIC_EVIDENCE_REQUIRED")
    if event.sensitive_trait_data_present:
        raise RelationshipGraphHold("HOLD_CP87_SENSITIVE_TRAIT_DATA_FORBIDDEN")
    if event.sensitive_relationship_profiling_requested:
        raise RelationshipGraphHold("HOLD_CP87_SENSITIVE_RELATIONSHIP_PROFILING_FORBIDDEN")
    if event.political_microtargeting_requested:
        raise RelationshipGraphHold("HOLD_CP87_POLITICAL_MICROTARGETING_FORBIDDEN")
    if not isinstance(event.extra_metadata, Mapping):
        raise RelationshipGraphHold("HOLD_CP87_EXTRA_METADATA_TYPE")
    if event.extra_metadata:
        raise RelationshipGraphHold("HOLD_CP87_EXTRA_METADATA_FORBIDDEN")
    if isinstance(event.quality_score, bool) or not isinstance(event.quality_score, int) or not 0 <= event.quality_score <= 100:
        raise RelationshipGraphHold("HOLD_CP87_QUALITY_SCORE_INVALID")

    source = _norm_text(event.source_public_id, name="source_public_id", max_len=MAX_REF)
    peer = _norm_text(event.peer_public_id, name="peer_public_id", max_len=MAX_REF)
    if source == peer:
        raise RelationshipGraphHold("HOLD_CP87_SELF_RELATIONSHIP_FORBIDDEN")
    return {
        "platform": event.platform,
        "source_public_id": source,
        "peer_public_id": peer,
        "interaction_kind": event.interaction_kind,
        "conversation_ref": _norm_text(event.conversation_ref, name="conversation_ref", max_len=MAX_REF),
        "content_ref": _norm_text(event.content_ref, name="content_ref", max_len=MAX_REF),
        "topic": _norm_text(event.topic, name="topic", max_len=MAX_TOPIC),
        "observed_at_utc": _norm_utc(event.observed_at_utc),
        "quality_score": event.quality_score,
        "provenance_ref": _norm_text(event.provenance_ref, name="provenance_ref", max_len=MAX_REF),
    }


def _node_id(platform: str, node_type: str, public_ref: str) -> str:
    return "node_" + _hash([platform, node_type, public_ref])[:24]


def _pair_id(platform: str, source_public_id: str, peer_public_id: str) -> str:
    return "pair_" + _hash([platform, source_public_id, peer_public_id])[:24]


def _edge_id(
    platform: str,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    *,
    topic: str | None = None,
) -> str:
    return "edge_" + _hash([platform, source_node_id, target_node_id, edge_type, topic or ""])[:24]


def _upsert_edge(
    state: RelationshipGraphState,
    *,
    edge_type: str,
    platform: str,
    source_node_id: str,
    target_node_id: str,
    observed_at_utc: str,
    quality_score: int,
    topic: str | None = None,
    conversation_ref: str | None = None,
    content_ref: str | None = None,
) -> None:
    edge_id = _edge_id(platform, source_node_id, target_node_id, edge_type, topic=topic)
    existing = state.edges.get(edge_id)
    if existing is None:
        state.edges[edge_id] = GraphEdge(
            edge_id=edge_id,
            edge_type=edge_type,
            platform=platform,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            first_seen_utc=observed_at_utc,
            last_seen_utc=observed_at_utc,
            interaction_count=1,
            quality_sum=quality_score,
            quality_mean=float(quality_score),
            topic=topic,
            conversation_ref=conversation_ref,
            content_ref=content_ref,
        )
        return
    count = existing.interaction_count + 1
    quality_sum = existing.quality_sum + quality_score
    state.edges[edge_id] = GraphEdge(
        edge_id=edge_id,
        edge_type=edge_type,
        platform=platform,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        first_seen_utc=min(existing.first_seen_utc, observed_at_utc),
        last_seen_utc=max(existing.last_seen_utc, observed_at_utc),
        interaction_count=count,
        quality_sum=quality_sum,
        quality_mean=round(quality_sum / count, 2),
        topic=topic,
        conversation_ref=conversation_ref or existing.conversation_ref,
        content_ref=content_ref or existing.content_ref,
    )


def _relationship_score(contract: RelationshipGraphContract, *, count: int, quality_sum: int) -> tuple[float, float]:
    mean = round(quality_sum / count, 2)
    repeat_units = min(max(count - 1, 0), contract.repeat_bonus_cap)
    score = min(
        100.0,
        mean * contract.mean_quality_weight + repeat_units * contract.repeat_bonus_points,
    )
    return mean, round(score, 2)


def apply_interaction(
    contract: RelationshipGraphContract,
    state: RelationshipGraphState,
    event: InteractionEvent,
) -> RelationshipGraphResult:
    if contract.checkpoint != CHECKPOINT or contract.parent_activation_checkpoint != PARENT_ACTIVATION_CHECKPOINT:
        raise RelationshipGraphHold("HOLD_CP87_CONTRACT_IDENTITY")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise RelationshipGraphHold("HOLD_CP87_PARENT_CONTROL_DRIFT")
    if not contract.global_kill_switch_engaged:
        raise RelationshipGraphHold("HOLD_CP87_KILL_SWITCH_NOT_ENGAGED")
    if contract.external_write_allowed or contract.posting_authority or contract.network_allowed:
        raise RelationshipGraphHold("HOLD_CP87_AUTHORITY_DRIFT")

    normalized = _normalized_event(event)
    event_hash = _hash(normalized)
    receipt_key = f"{normalized['platform']}:{normalized['provenance_ref']}"
    pair_id = _pair_id(
        normalized["platform"],
        normalized["source_public_id"],
        normalized["peer_public_id"],
    )

    existing_receipt = state.receipts.get(receipt_key)
    if existing_receipt is not None:
        if existing_receipt != event_hash:
            raise RelationshipGraphHold("HOLD_CP87_CONFLICTING_DUPLICATE_PROVENANCE")
        summary = state.relationships[pair_id]
        edge_types = tuple(sorted({
            edge.edge_type
            for edge in state.edges.values()
            if edge.platform == normalized["platform"]
            and edge.source_node_id == _node_id(normalized["platform"], "public_account", normalized["source_public_id"])
            and edge.target_node_id == _node_id(normalized["platform"], "public_account", normalized["peer_public_id"])
        }))
        return RelationshipGraphResult(
            event_id="event_" + event_hash[:24],
            pair_id=pair_id,
            relationship_score=summary.relationship_score,
            interaction_count=summary.interaction_count,
            edge_types_present=edge_types,
            idempotent_replay=True,
            state_hash=_hash(state.to_dict()),
        )

    source_node = GraphNode(
        node_id=_node_id(normalized["platform"], "public_account", normalized["source_public_id"]),
        node_type="public_account",
        platform=normalized["platform"],
        public_ref=normalized["source_public_id"],
    )
    peer_node = GraphNode(
        node_id=_node_id(normalized["platform"], "public_account", normalized["peer_public_id"]),
        node_type="public_account",
        platform=normalized["platform"],
        public_ref=normalized["peer_public_id"],
    )
    conversation_node = GraphNode(
        node_id=_node_id(normalized["platform"], "conversation", normalized["conversation_ref"]),
        node_type="conversation",
        platform=normalized["platform"],
        public_ref=normalized["conversation_ref"],
    )
    content_node = GraphNode(
        node_id=_node_id(normalized["platform"], "content", normalized["content_ref"]),
        node_type="content",
        platform=normalized["platform"],
        public_ref=normalized["content_ref"],
    )
    for node in (source_node, peer_node, conversation_node, content_node):
        state.nodes.setdefault(node.node_id, node)

    previous = state.relationships.get(pair_id)
    count = (previous.interaction_count if previous else 0) + 1
    useful_count = (previous.useful_exchange_count if previous else 0) + (
        1 if normalized["quality_score"] >= contract.useful_exchange_min_quality else 0
    )
    quality_sum = (previous.quality_sum if previous else 0) + normalized["quality_score"]
    quality_mean, score = _relationship_score(contract, count=count, quality_sum=quality_sum)
    state.relationships[pair_id] = RelationshipSummary(
        pair_id=pair_id,
        platform=normalized["platform"],
        source_public_id=normalized["source_public_id"],
        peer_public_id=normalized["peer_public_id"],
        interaction_count=count,
        useful_exchange_count=useful_count,
        quality_sum=quality_sum,
        quality_mean=quality_mean,
        relationship_score=score,
    )

    _upsert_edge(
        state,
        edge_type=normalized["interaction_kind"],
        platform=normalized["platform"],
        source_node_id=source_node.node_id,
        target_node_id=peer_node.node_id,
        observed_at_utc=normalized["observed_at_utc"],
        quality_score=normalized["quality_score"],
        conversation_ref=normalized["conversation_ref"],
        content_ref=normalized["content_ref"],
    )
    _upsert_edge(
        state,
        edge_type="shared_topic",
        platform=normalized["platform"],
        source_node_id=source_node.node_id,
        target_node_id=peer_node.node_id,
        observed_at_utc=normalized["observed_at_utc"],
        quality_score=normalized["quality_score"],
        topic=normalized["topic"],
        conversation_ref=normalized["conversation_ref"],
        content_ref=normalized["content_ref"],
    )
    if normalized["quality_score"] >= contract.useful_exchange_min_quality:
        _upsert_edge(
            state,
            edge_type="prior_useful_exchange",
            platform=normalized["platform"],
            source_node_id=source_node.node_id,
            target_node_id=peer_node.node_id,
            observed_at_utc=normalized["observed_at_utc"],
            quality_score=normalized["quality_score"],
            conversation_ref=normalized["conversation_ref"],
            content_ref=normalized["content_ref"],
        )
    if count >= contract.repeat_interaction_min_count:
        _upsert_edge(
            state,
            edge_type="recurring_interaction",
            platform=normalized["platform"],
            source_node_id=source_node.node_id,
            target_node_id=peer_node.node_id,
            observed_at_utc=normalized["observed_at_utc"],
            quality_score=normalized["quality_score"],
            conversation_ref=normalized["conversation_ref"],
            content_ref=normalized["content_ref"],
        )

    state.receipts[receipt_key] = event_hash
    edge_types = tuple(sorted({
        edge.edge_type
        for edge in state.edges.values()
        if edge.platform == normalized["platform"]
        and edge.source_node_id == source_node.node_id
        and edge.target_node_id == peer_node.node_id
    }))
    return RelationshipGraphResult(
        event_id="event_" + event_hash[:24],
        pair_id=pair_id,
        relationship_score=score,
        interaction_count=count,
        edge_types_present=edge_types,
        idempotent_replay=False,
        state_hash=_hash(state.to_dict()),
    )


def process_batch(
    contract: RelationshipGraphContract,
    state: RelationshipGraphState,
    events: Sequence[InteractionEvent],
) -> tuple[RelationshipGraphResult, ...]:
    if len(events) > contract.max_batch:
        raise RelationshipGraphHold("HOLD_CP87_BATCH_LIMIT_EXCEEDED")
    return tuple(apply_interaction(contract, state, event) for event in events)
