from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from public_presence_os.growth_capability_matrix import (
    ACTIVE_PLATFORMS,
    GrowthCapabilityMatrixContract,
    GrowthCapabilityMatrixHold,
    capability_lookup,
)

MODEL_VERSION = "PPOS_INBOUND_REPLY_ENGINE_V1"
ENGINE_VERSION = "ppos-inbound-reply-engine-v1.0.0"
CHECKPOINT = "CP85"
PARENT_ACTIVATION_CHECKPOINT = "CP84"
PARENT_CAPABILITY_CHECKPOINT = "CP83"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP86_OUTBOUND_VALUE_ADD_ENGAGEMENT_ENGINE"
STATE = "CP85_INBOUND_REPLY_ENGINE_OFFLINE_DRAFT_HUMAN_REVIEW_ONLY_NO_EXTERNAL_WRITE_LIVE_HOLD"
UNKNOWN_EXTERNAL_METRIC_VALUE = "UNKNOWN"

SURFACE_KINDS = ("OWN_CONTENT_COMMENT", "OWN_CONTENT_REPLY", "ACCOUNT_MENTION")
PROVENANCE_KINDS = ("PUBLIC_URL_OBSERVATION", "OFFLINE_API_FIXTURE", "SYNTHETIC_FIXTURE")
CLASSIFICATIONS = (
    "QUESTION",
    "AGREEMENT_WITH_SUBSTANCE",
    "CORRECTION",
    "COUNTERPOINT",
    "EXPERT_LEAD",
    "COMMUNITY_SIGNAL",
    "LOW_VALUE",
    "ABUSE_SPAM",
)
EVIDENCE_TAGS = (
    "QUESTION_SIGNAL",
    "SUBSTANTIVE_AGREEMENT_SIGNAL",
    "CORRECTION_SIGNAL",
    "COUNTERPOINT_SIGNAL",
    "PUBLIC_EXPERTISE_SIGNAL",
    "COMMUNITY_RELEVANCE_SIGNAL",
    "LOW_VALUE_SIGNAL",
    "ABUSE_SIGNAL",
    "SPAM_SIGNAL",
)
CLASSIFICATION_PRECEDENCE = (
    "ABUSE_SPAM",
    "CORRECTION",
    "QUESTION",
    "COUNTERPOINT",
    "EXPERT_LEAD",
    "AGREEMENT_WITH_SUBSTANCE",
    "COMMUNITY_SIGNAL",
    "LOW_VALUE",
)
TERMINAL_NO_REPLY_STATES = (
    "NO_REPLY_ABUSE_SPAM",
    "NO_REPLY_LOW_VALUE",
    "NO_REPLY_CAPABILITY_HOLD",
    "NO_REPLY_TERMINAL_ALREADY_CLOSED",
)
CONVERSATION_STATES = (
    "NEW",
    "CLASSIFIED",
    "DRAFT_READY_HUMAN_REVIEW",
    "HOLD_EDITORIAL_CONTEXT_REQUIRED",
    *TERMINAL_NO_REPLY_STATES,
)
MAX_BATCH = 100
MAX_TEXT = 4000
MAX_REF = 240
MAX_EVIDENCE_ITEM = 500
WS_RE = re.compile(r"\s+")


class InboundReplyHold(ValueError):
    """Fail-closed CP85 contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _norm_text(value: str, *, name: str, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise InboundReplyHold(f"HOLD_CP85_{name.upper()}_TYPE")
    value = WS_RE.sub(" ", value).strip()
    if not value and not allow_empty:
        raise InboundReplyHold(f"HOLD_CP85_{name.upper()}_MISSING")
    if len(value) > max_len:
        raise InboundReplyHold(f"HOLD_CP85_{name.upper()}_TOO_LONG")
    return value


def _norm_utc(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise InboundReplyHold(f"HOLD_CP85_{name.upper()}_UTC_REQUIRED")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InboundReplyHold(f"HOLD_CP85_{name.upper()}_INVALID") from exc
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise InboundReplyHold(f"HOLD_CP85_{name.upper()}_UTC_REQUIRED")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


def _norm_source_url(url: str, provenance_kind: str) -> str:
    if not isinstance(url, str):
        raise InboundReplyHold("HOLD_CP85_SOURCE_URL_TYPE")
    p = urlsplit(url.strip())
    if provenance_kind == "SYNTHETIC_FIXTURE":
        if p.scheme != "synthetic" or not p.netloc:
            raise InboundReplyHold("HOLD_CP85_SYNTHETIC_FIXTURE_URL_REQUIRED")
        return urlunsplit(("synthetic", p.netloc.lower(), p.path or "/", p.query, ""))
    if p.scheme != "https" or not p.netloc or "@" in p.netloc:
        raise InboundReplyHold("HOLD_CP85_PUBLIC_SOURCE_HTTPS_REQUIRED")
    return urlunsplit(("https", p.netloc.lower(), p.path or "/", p.query, ""))


@dataclass(frozen=True)
class InboundObservation:
    platform: str
    surface_kind: str
    provenance_kind: str
    provenance_ref: str
    inbound_ref: str
    conversation_ref: str
    own_content_ref: str
    source_url: str
    author_public_id: str
    text: str
    observed_at_utc: str
    own_content_published_at_utc: str
    evidence_tags: tuple[str, ...]
    response_evidence: tuple[str, ...] = ()
    prior_state: str = "NEW"
    sensitive_trait_inference_used: bool = False
    sensitive_relationship_profiling_used: bool = False
    political_microtargeting_used: bool = False
    synthetic_conversation_farming_used: bool = False


@dataclass(frozen=True)
class IngressRoute:
    platform: str
    surface_kind: str
    capability: str
    expected_cp83_classification: str
    automation_ingest_eligible: bool
    allowed_provenance: tuple[str, ...]
    required_blockers: tuple[str, ...]


@dataclass(frozen=True)
class InboundReplyContract:
    contract_id: str
    contract_hash: str
    policy_sha256: str
    routes: tuple[IngressRoute, ...]
    blockers: tuple[str, ...]
    hot_window_hours: int
    priority_window_hours: int
    max_response_chars: int
    max_evidence_items: int
    checkpoint: str = CHECKPOINT
    parent_activation_checkpoint: str = PARENT_ACTIVATION_CHECKPOINT
    parent_capability_checkpoint: str = PARENT_CAPABILITY_CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    next_unit: str = NEXT_UNIT
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    global_kill_switch_engaged: bool = True
    human_review_required: bool = True
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
        value = asdict(self)
        value["routes"] = [
            asdict(route)
            | {
                "allowed_provenance": list(route.allowed_provenance),
                "required_blockers": list(route.required_blockers),
            }
            for route in self.routes
        ]
        value["blockers"] = list(self.blockers)
        return value


@dataclass(frozen=True)
class InboundReplyCandidate:
    candidate_id: str
    observation_hash: str
    platform: str
    surface_kind: str
    capability: str
    cp83_classification: str
    automation_ingest_eligible: bool
    inbound_ref: str
    conversation_ref: str
    own_content_ref: str
    author_public_id: str
    text: str
    classification: str
    sla_label: str
    age_since_publication_hours: float
    prior_state: str
    next_state: str
    response_candidate: str | None
    decision: str
    decision_reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    provenance_kind: str
    provenance_ref: str
    source_url: str
    observed_at_utc: str
    own_content_published_at_utc: str
    posting_authority: bool = False
    external_write_allowed: bool = False
    external_write_attempted: bool = False
    network_fetch_performed: bool = False
    human_review_required: bool = True
    external_metrics: str = UNKNOWN_EXTERNAL_METRIC_VALUE

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["decision_reasons"] = list(self.decision_reasons)
        value["blockers"] = list(self.blockers)
        return value


def _route_key(platform: str, surface_kind: str) -> tuple[str, str]:
    return platform, surface_kind


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"),
        policy.get("checkpoint"),
        policy.get("module_id"),
        policy.get("parent_activation_checkpoint"),
        policy.get("parent_capability_checkpoint"),
        policy.get("parent_control_checkpoint"),
        policy.get("next_after_cp85"),
    )
    expected = (
        "PPOS_INBOUND_REPLY_ENGINE_POLICY_V1",
        CHECKPOINT,
        "M54_INBOUND_REPLY_ENGINE",
        PARENT_ACTIVATION_CHECKPOINT,
        PARENT_CAPABILITY_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        NEXT_UNIT,
    )
    if identity != expected:
        raise InboundReplyHold("HOLD_CP85_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise InboundReplyHold("HOLD_CP85_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("surface_kinds", ())) != SURFACE_KINDS:
        raise InboundReplyHold("HOLD_CP85_SURFACE_KIND_DRIFT")
    if tuple(policy.get("provenance_kinds", ())) != PROVENANCE_KINDS:
        raise InboundReplyHold("HOLD_CP85_PROVENANCE_KIND_DRIFT")
    if tuple(policy.get("classifications", ())) != CLASSIFICATIONS:
        raise InboundReplyHold("HOLD_CP85_CLASSIFICATION_DRIFT")
    if tuple(policy.get("evidence_tags", ())) != EVIDENCE_TAGS:
        raise InboundReplyHold("HOLD_CP85_EVIDENCE_TAG_DRIFT")
    if tuple(policy.get("classification_precedence", ())) != CLASSIFICATION_PRECEDENCE:
        raise InboundReplyHold("HOLD_CP85_CLASSIFICATION_PRECEDENCE_DRIFT")
    if tuple(policy.get("terminal_no_reply_states", ())) != TERMINAL_NO_REPLY_STATES:
        raise InboundReplyHold("HOLD_CP85_TERMINAL_STATE_DRIFT")
    if tuple(policy.get("conversation_states", ())) != CONVERSATION_STATES:
        raise InboundReplyHold("HOLD_CP85_CONVERSATION_STATE_DRIFT")
    if policy.get("global_kill_switch") != "ENGAGED":
        raise InboundReplyHold("HOLD_CP85_KILL_SWITCH_NOT_ENGAGED")
    if policy.get("unknown_external_metric_value") != UNKNOWN_EXTERNAL_METRIC_VALUE:
        raise InboundReplyHold("HOLD_CP85_UNKNOWN_METRIC_DRIFT")

    authority = policy.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise InboundReplyHold("HOLD_CP85_LIVE_AUTHORITY_DRIFT")
    safety = policy.get("growth_safety")
    if not isinstance(safety, Mapping) or not safety or not all(value is True for value in safety.values()):
        raise InboundReplyHold("HOLD_CP85_GROWTH_SAFETY_WEAKENED")

    sla = policy.get("sla")
    if (
        not isinstance(sla, Mapping)
        or sla.get("hot_window_hours") != 2
        or sla.get("priority_window_hours") != 4
        or tuple(sla.get("labels", ())) != ("HOT_0_2H", "PRIORITY_2_4H", "STANDARD_AFTER_4H")
    ):
        raise InboundReplyHold("HOLD_CP85_SLA_DRIFT")

    response = policy.get("response")
    if not isinstance(response, Mapping):
        raise InboundReplyHold("HOLD_CP85_RESPONSE_POLICY_MISSING")
    if response.get("human_review_required") is not True or response.get("fact_bound_only") is not True:
        raise InboundReplyHold("HOLD_CP85_RESPONSE_SAFETY_WEAKENED")
    if response.get("generic_praise_forbidden") is not True or response.get("copy_paste_replies_forbidden") is not True:
        raise InboundReplyHold("HOLD_CP85_RESPONSE_SAFETY_WEAKENED")
    max_chars = response.get("max_chars")
    max_evidence = response.get("max_evidence_items")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 1000:
        raise InboundReplyHold("HOLD_CP85_RESPONSE_LIMIT_INVALID")
    if isinstance(max_evidence, bool) or not isinstance(max_evidence, int) or not 1 <= max_evidence <= 10:
        raise InboundReplyHold("HOLD_CP85_RESPONSE_LIMIT_INVALID")

    routes = policy.get("ingress_routes")
    expected_pairs = {(p, s) for p in ACTIVE_PLATFORMS for s in SURFACE_KINDS}
    if not isinstance(routes, list) or len(routes) != len(expected_pairs):
        raise InboundReplyHold("HOLD_CP85_ROUTE_CARDINALITY")
    pairs = {
        (route.get("platform"), route.get("surface_kind"))
        for route in routes
        if isinstance(route, Mapping)
    }
    if pairs != expected_pairs:
        raise InboundReplyHold("HOLD_CP85_ROUTE_NOT_EXACT_CARTESIAN")
    for route in routes:
        if not isinstance(route, Mapping):
            raise InboundReplyHold("HOLD_CP85_ROUTE_INVALID")
        if route.get("capability") not in {"INBOUND_REPLY", "MENTION_DISCOVERY"}:
            raise InboundReplyHold("HOLD_CP85_ROUTE_CAPABILITY_INVALID")
        classification = route.get("expected_cp83_classification")
        if classification not in {"PASS_OFFLINE_CONTRACT", "HOLD_LIVE_PERMISSION", "MANUAL_ONLY", "UNSUPPORTED"}:
            raise InboundReplyHold("HOLD_CP85_ROUTE_CLASSIFICATION_INVALID")
        automation = route.get("automation_ingest_eligible")
        if not isinstance(automation, bool):
            raise InboundReplyHold("HOLD_CP85_ROUTE_AUTOMATION_FLAG_INVALID")
        if classification != "PASS_OFFLINE_CONTRACT" and automation:
            raise InboundReplyHold("HOLD_CP85_UNVERIFIED_ROUTE_CANNOT_AUTOMATE")
        allowed = tuple(route.get("allowed_provenance", ()))
        if not allowed or not set(allowed).issubset(PROVENANCE_KINDS):
            raise InboundReplyHold("HOLD_CP85_ROUTE_PROVENANCE_INVALID")
        blockers = route.get("required_blockers")
        if not isinstance(blockers, list) or not blockers:
            raise InboundReplyHold("HOLD_CP85_ROUTE_BLOCKERS_REQUIRED")
        if classification != "PASS_OFFLINE_CONTRACT" and "HOLD_CAPABILITY_UNVERIFIED" not in blockers:
            raise InboundReplyHold("HOLD_CP85_UNVERIFIED_ROUTE_BLOCKER_MISSING")


def compile_inbound_reply_engine(
    policy: Mapping[str, Any],
    capability_contract: GrowthCapabilityMatrixContract,
) -> InboundReplyContract:
    validate_policy(policy)
    if capability_contract.checkpoint != PARENT_CAPABILITY_CHECKPOINT:
        raise InboundReplyHold("HOLD_CP85_PARENT_CAPABILITY_CONTRACT_INVALID")
    if capability_contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise InboundReplyHold("HOLD_CP85_PARENT_CONTROL_DRIFT")
    if not capability_contract.global_kill_switch_engaged:
        raise InboundReplyHold("HOLD_CP85_PARENT_KILL_SWITCH_NOT_ENGAGED")

    routes: list[IngressRoute] = []
    for item in policy["ingress_routes"]:
        try:
            parent_row = capability_lookup(capability_contract, item["platform"], item["capability"])
        except GrowthCapabilityMatrixHold as exc:
            raise InboundReplyHold("HOLD_CAPABILITY_UNVERIFIED") from exc
        if parent_row.classification != item["expected_cp83_classification"]:
            raise InboundReplyHold("HOLD_CP85_CP83_CLASSIFICATION_DRIFT")
        if parent_row.classification != "PASS_OFFLINE_CONTRACT" and item["automation_ingest_eligible"]:
            raise InboundReplyHold("HOLD_CP85_UNVERIFIED_ROUTE_CANNOT_AUTOMATE")
        routes.append(
            IngressRoute(
                platform=item["platform"],
                surface_kind=item["surface_kind"],
                capability=item["capability"],
                expected_cp83_classification=item["expected_cp83_classification"],
                automation_ingest_eligible=item["automation_ingest_eligible"],
                allowed_provenance=tuple(item["allowed_provenance"]),
                required_blockers=tuple(item["required_blockers"]),
            )
        )

    stable = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_activation_checkpoint": PARENT_ACTIVATION_CHECKPOINT,
        "parent_capability_checkpoint": PARENT_CAPABILITY_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "routes": [asdict(r) for r in routes],
        "blockers": policy["required_blockers"],
        "sla": policy["sla"],
        "response": policy["response"],
    }
    contract_hash = _hash(stable)
    return InboundReplyContract(
        contract_id=f"cp85-{contract_hash[:16]}",
        contract_hash=contract_hash,
        policy_sha256=_hash(policy),
        routes=tuple(routes),
        blockers=tuple(policy["required_blockers"]),
        hot_window_hours=policy["sla"]["hot_window_hours"],
        priority_window_hours=policy["sla"]["priority_window_hours"],
        max_response_chars=policy["response"]["max_chars"],
        max_evidence_items=policy["response"]["max_evidence_items"],
    )


def _route_for(contract: InboundReplyContract, platform: str, surface_kind: str) -> IngressRoute:
    if platform not in ACTIVE_PLATFORMS or surface_kind not in SURFACE_KINDS:
        raise InboundReplyHold("HOLD_CAPABILITY_UNVERIFIED")
    matches = [r for r in contract.routes if _route_key(r.platform, r.surface_kind) == (platform, surface_kind)]
    if len(matches) != 1:
        raise InboundReplyHold("HOLD_CAPABILITY_UNVERIFIED")
    return matches[0]


def _classification(tags: tuple[str, ...]) -> str:
    tagset = set(tags)
    if not tagset.issubset(EVIDENCE_TAGS):
        raise InboundReplyHold("HOLD_CP85_UNKNOWN_CLASSIFICATION_EVIDENCE")
    if {"ABUSE_SIGNAL", "SPAM_SIGNAL"} & tagset:
        return "ABUSE_SPAM"
    if "CORRECTION_SIGNAL" in tagset:
        return "CORRECTION"
    if "QUESTION_SIGNAL" in tagset:
        return "QUESTION"
    if "COUNTERPOINT_SIGNAL" in tagset:
        return "COUNTERPOINT"
    if "PUBLIC_EXPERTISE_SIGNAL" in tagset:
        return "EXPERT_LEAD"
    if "SUBSTANTIVE_AGREEMENT_SIGNAL" in tagset:
        return "AGREEMENT_WITH_SUBSTANCE"
    if "COMMUNITY_RELEVANCE_SIGNAL" in tagset:
        return "COMMUNITY_SIGNAL"
    return "LOW_VALUE"


def _sla_label(contract: InboundReplyContract, published: str, now: str) -> tuple[str, float]:
    published_dt = _parse_utc(published)
    now_dt = _parse_utc(now)
    if published_dt > now_dt:
        raise InboundReplyHold("HOLD_CP85_PUBLICATION_TIME_IN_FUTURE")
    age = round((now_dt - published_dt).total_seconds() / 3600.0, 3)
    if age <= contract.hot_window_hours:
        return "HOT_0_2H", age
    if age <= contract.priority_window_hours:
        return "PRIORITY_2_4H", age
    return "STANDARD_AFTER_4H", age


def _response_candidate(
    classification: str,
    evidence: Sequence[str],
    *,
    max_chars: int,
    max_evidence_items: int,
) -> str | None:
    if classification in {"LOW_VALUE", "ABUSE_SPAM"}:
        return None
    clean: list[str] = []
    for item in evidence[:max_evidence_items]:
        clean_item = _norm_text(item, name="response_evidence", max_len=MAX_EVIDENCE_ITEM)
        if clean_item not in clean:
            clean.append(clean_item)
    if not clean:
        return None
    fact = clean[0]
    prefixes = {
        "QUESTION": "Pe scurt: ",
        "AGREEMENT_WITH_SUBSTANCE": "Da — ",
        "CORRECTION": "Corecția relevantă este aceasta: ",
        "COUNTERPOINT": "Punctul-cheie de clarificat este acesta: ",
        "EXPERT_LEAD": "Contextul util aici este acesta: ",
        "COMMUNITY_SIGNAL": "Contextul concret este acesta: ",
    }
    draft = prefixes[classification] + fact
    return _norm_text(draft, name="response_candidate", max_len=max_chars)


def classify_inbound(
    contract: InboundReplyContract,
    observation: InboundObservation,
    *,
    now_utc: str,
) -> InboundReplyCandidate:
    now = _norm_utc(now_utc, name="now")
    if observation.prior_state not in CONVERSATION_STATES:
        raise InboundReplyHold("HOLD_CP85_UNKNOWN_CONVERSATION_STATE")
    if observation.prior_state in TERMINAL_NO_REPLY_STATES:
        return _terminal_existing(contract, observation, now)

    route = _route_for(contract, observation.platform, observation.surface_kind)
    if observation.provenance_kind not in PROVENANCE_KINDS:
        raise InboundReplyHold("HOLD_CP85_PROVENANCE_KIND_INVALID")
    if observation.provenance_kind not in route.allowed_provenance:
        raise InboundReplyHold("HOLD_CP85_PROVENANCE_NOT_ALLOWED_FOR_ROUTE")

    provenance_ref = _norm_text(observation.provenance_ref, name="provenance_ref", max_len=MAX_REF)
    inbound_ref = _norm_text(observation.inbound_ref, name="inbound_ref", max_len=MAX_REF)
    conversation_ref = _norm_text(observation.conversation_ref, name="conversation_ref", max_len=MAX_REF)
    own_content_ref = _norm_text(observation.own_content_ref, name="own_content_ref", max_len=MAX_REF)
    author_public_id = _norm_text(observation.author_public_id, name="author_public_id", max_len=MAX_REF)
    text = _norm_text(observation.text, name="text", max_len=MAX_TEXT)
    observed_at = _norm_utc(observation.observed_at_utc, name="observed_at")
    own_published = _norm_utc(observation.own_content_published_at_utc, name="own_content_published_at")
    source_url = _norm_source_url(observation.source_url, observation.provenance_kind)
    if _parse_utc(observed_at) > _parse_utc(now):
        raise InboundReplyHold("HOLD_CP85_OBSERVATION_TIME_IN_FUTURE")

    tags = tuple(dict.fromkeys(observation.evidence_tags))
    classification = _classification(tags)
    sla_label, age_hours = _sla_label(contract, own_published, now)

    safety_violation = any(
        (
            observation.sensitive_trait_inference_used,
            observation.sensitive_relationship_profiling_used,
            observation.political_microtargeting_used,
            observation.synthetic_conversation_farming_used,
        )
    )
    reasons: list[str] = []
    blockers = list(dict.fromkeys((*contract.blockers, *route.required_blockers)))
    response_candidate: str | None = None

    if safety_violation:
        classification = "ABUSE_SPAM"
        next_state = "NO_REPLY_ABUSE_SPAM"
        decision = "NO_REPLY_SAFETY"
        reasons.append("PROHIBITED_GROWTH_SAFETY_SIGNAL")
    elif route.expected_cp83_classification != "PASS_OFFLINE_CONTRACT":
        next_state = "NO_REPLY_CAPABILITY_HOLD"
        decision = "NO_REPLY_CAPABILITY_HOLD"
        reasons.extend(("CAPABILITY_NOT_PASS_OFFLINE_CONTRACT", "HOLD_CAPABILITY_UNVERIFIED"))
        if "HOLD_CAPABILITY_UNVERIFIED" not in blockers:
            blockers.append("HOLD_CAPABILITY_UNVERIFIED")
    elif classification == "ABUSE_SPAM":
        next_state = "NO_REPLY_ABUSE_SPAM"
        decision = "NO_REPLY_ABUSE_SPAM"
        reasons.append("ABUSE_OR_SPAM_CLASSIFICATION")
    elif classification == "LOW_VALUE":
        next_state = "NO_REPLY_LOW_VALUE"
        decision = "NO_REPLY_LOW_VALUE"
        reasons.append("LOW_VALUE_NO_USEFUL_RESPONSE")
    else:
        response_candidate = _response_candidate(
            classification,
            observation.response_evidence,
            max_chars=contract.max_response_chars,
            max_evidence_items=contract.max_evidence_items,
        )
        if response_candidate is None:
            next_state = "HOLD_EDITORIAL_CONTEXT_REQUIRED"
            decision = "HOLD_EDITORIAL_CONTEXT_REQUIRED"
            reasons.append("NO_FACT_BOUND_RESPONSE_EVIDENCE")
        else:
            next_state = "DRAFT_READY_HUMAN_REVIEW"
            decision = "DRAFT_READY_HUMAN_REVIEW"
            reasons.extend(("FACT_BOUND_RESPONSE_CANDIDATE", "HUMAN_REVIEW_REQUIRED"))

    normalized = {
        "platform": observation.platform,
        "surface_kind": observation.surface_kind,
        "capability": route.capability,
        "provenance_kind": observation.provenance_kind,
        "provenance_ref": provenance_ref,
        "inbound_ref": inbound_ref,
        "conversation_ref": conversation_ref,
        "own_content_ref": own_content_ref,
        "source_url": source_url,
        "author_public_id": author_public_id,
        "text": text,
        "observed_at_utc": observed_at,
        "own_content_published_at_utc": own_published,
        "evidence_tags": tags,
        "response_evidence": tuple(observation.response_evidence),
        "prior_state": observation.prior_state,
    }
    observation_hash = _hash(normalized)
    candidate_id = _hash(
        {
            "platform": observation.platform,
            "surface_kind": observation.surface_kind,
            "inbound_ref": inbound_ref,
            "conversation_ref": conversation_ref,
            "own_content_ref": own_content_ref,
        }
    )

    return InboundReplyCandidate(
        candidate_id=candidate_id,
        observation_hash=observation_hash,
        platform=observation.platform,
        surface_kind=observation.surface_kind,
        capability=route.capability,
        cp83_classification=route.expected_cp83_classification,
        automation_ingest_eligible=route.automation_ingest_eligible,
        inbound_ref=inbound_ref,
        conversation_ref=conversation_ref,
        own_content_ref=own_content_ref,
        author_public_id=author_public_id,
        text=text,
        classification=classification,
        sla_label=sla_label,
        age_since_publication_hours=age_hours,
        prior_state=observation.prior_state,
        next_state=next_state,
        response_candidate=response_candidate,
        decision=decision,
        decision_reasons=tuple(reasons),
        blockers=tuple(blockers),
        provenance_kind=observation.provenance_kind,
        provenance_ref=provenance_ref,
        source_url=source_url,
        observed_at_utc=observed_at,
        own_content_published_at_utc=own_published,
    )


def _terminal_existing(
    contract: InboundReplyContract,
    observation: InboundObservation,
    now_utc: str,
) -> InboundReplyCandidate:
    route = _route_for(contract, observation.platform, observation.surface_kind)
    if observation.provenance_kind not in route.allowed_provenance:
        raise InboundReplyHold("HOLD_CP85_PROVENANCE_NOT_ALLOWED_FOR_ROUTE")
    observed_at = _norm_utc(observation.observed_at_utc, name="observed_at")
    published_at = _norm_utc(observation.own_content_published_at_utc, name="own_content_published_at")
    sla_label, age_hours = _sla_label(contract, published_at, now_utc)
    source_url = _norm_source_url(observation.source_url, observation.provenance_kind)
    normalized = {
        "platform": observation.platform,
        "surface_kind": observation.surface_kind,
        "inbound_ref": observation.inbound_ref,
        "conversation_ref": observation.conversation_ref,
        "own_content_ref": observation.own_content_ref,
        "prior_state": observation.prior_state,
    }
    return InboundReplyCandidate(
        candidate_id=_hash(normalized),
        observation_hash=_hash(asdict(observation)),
        platform=observation.platform,
        surface_kind=observation.surface_kind,
        capability=route.capability,
        cp83_classification=route.expected_cp83_classification,
        automation_ingest_eligible=False,
        inbound_ref=_norm_text(observation.inbound_ref, name="inbound_ref", max_len=MAX_REF),
        conversation_ref=_norm_text(observation.conversation_ref, name="conversation_ref", max_len=MAX_REF),
        own_content_ref=_norm_text(observation.own_content_ref, name="own_content_ref", max_len=MAX_REF),
        author_public_id=_norm_text(observation.author_public_id, name="author_public_id", max_len=MAX_REF),
        text=_norm_text(observation.text, name="text", max_len=MAX_TEXT),
        classification="LOW_VALUE",
        sla_label=sla_label,
        age_since_publication_hours=age_hours,
        prior_state=observation.prior_state,
        next_state="NO_REPLY_TERMINAL_ALREADY_CLOSED",
        response_candidate=None,
        decision="NO_REPLY_TERMINAL_ALREADY_CLOSED",
        decision_reasons=("TERMINAL_STATE_NO_RESURRECTION",),
        blockers=tuple(dict.fromkeys((*contract.blockers, *route.required_blockers))),
        provenance_kind=observation.provenance_kind,
        provenance_ref=_norm_text(observation.provenance_ref, name="provenance_ref", max_len=MAX_REF),
        source_url=source_url,
        observed_at_utc=observed_at,
        own_content_published_at_utc=published_at,
    )


def process_batch(
    contract: InboundReplyContract,
    observations: Sequence[InboundObservation],
    *,
    now_utc: str,
) -> list[InboundReplyCandidate]:
    if len(observations) > MAX_BATCH:
        raise InboundReplyHold("HOLD_CP85_BATCH_TOO_LARGE")
    results: list[InboundReplyCandidate] = []
    seen: dict[str, str] = {}
    for observation in observations:
        candidate = classify_inbound(contract, observation, now_utc=now_utc)
        prior_hash = seen.get(candidate.candidate_id)
        if prior_hash is None:
            seen[candidate.candidate_id] = candidate.observation_hash
            results.append(candidate)
        elif prior_hash != candidate.observation_hash:
            raise InboundReplyHold("HOLD_CP85_CONFLICTING_DUPLICATE")
    priority = {"HOT_0_2H": 0, "PRIORITY_2_4H": 1, "STANDARD_AFTER_4H": 2}
    return sorted(
        results,
        key=lambda item: (
            priority[item.sla_label],
            0 if item.decision == "DRAFT_READY_HUMAN_REVIEW" else 1,
            item.observed_at_utc,
            item.candidate_id,
        ),
    )
