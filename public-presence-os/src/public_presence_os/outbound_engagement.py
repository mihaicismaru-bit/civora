from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from public_presence_os.engagement_radar import EngagementCandidate
from public_presence_os.growth_capability_matrix import (
    ACTIVE_PLATFORMS,
    GrowthCapabilityMatrixContract,
    GrowthCapabilityMatrixHold,
    capability_lookup,
)

MODEL_VERSION = "PPOS_OUTBOUND_VALUE_ADD_ENGAGEMENT_ENGINE_V1"
ENGINE_VERSION = "ppos-outbound-value-add-engagement-v1.0.0"
CHECKPOINT = "CP86"
PARENT_ACTIVATION_CHECKPOINT = "CP85"
PARENT_RADAR_CHECKPOINT = "CP84"
PARENT_CAPABILITY_CHECKPOINT = "CP83"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP87_RELATIONSHIP_GRAPH"
STATE = "CP86_OUTBOUND_VALUE_ADD_OFFLINE_COMPOSITION_CAPABILITY_GATED_MANUAL_FALLBACK_HUMAN_REVIEW_ONLY_NO_EXTERNAL_WRITE_LIVE_HOLD"
UNKNOWN_EXTERNAL_METRIC_VALUE = "UNKNOWN"

COMPOSER_MODES = (
    "CONTEXT",
    "DATA_POINT",
    "CLARIFICATION",
    "PRACTICAL_EXAMPLE",
    "GOOD_QUESTION",
    "RESPECTFUL_COUNTERPOINT",
)
MATERIAL_VALUE_KINDS = (
    "INFORMATION",
    "CONTEXT",
    "CLARIFICATION",
    "CONCRETE_QUESTION",
    "USEFUL_PERSPECTIVE",
)
PROVENANCE_KINDS = ("PUBLIC_URL_OBSERVATION", "OFFLINE_API_FIXTURE", "SYNTHETIC_FIXTURE")
MAX_TEXT = 4000
MAX_REF = 240
MAX_BATCH = 100
WS_RE = re.compile(r"\s+")


class OutboundEngagementHold(ValueError):
    """Fail-closed CP86 contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _norm_text(value: str, *, name: str, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise OutboundEngagementHold(f"HOLD_CP86_{name.upper()}_TYPE")
    value = WS_RE.sub(" ", value).strip()
    if not value and not allow_empty:
        raise OutboundEngagementHold(f"HOLD_CP86_{name.upper()}_MISSING")
    if len(value) > max_len:
        raise OutboundEngagementHold(f"HOLD_CP86_{name.upper()}_TOO_LONG")
    return value


def _norm_source_url(url: str, provenance_kind: str) -> str:
    if not isinstance(url, str):
        raise OutboundEngagementHold("HOLD_CP86_SOURCE_URL_TYPE")
    p = urlsplit(url.strip())
    if provenance_kind == "SYNTHETIC_FIXTURE":
        if p.scheme != "synthetic" or not p.netloc:
            raise OutboundEngagementHold("HOLD_CP86_SYNTHETIC_FIXTURE_URL_REQUIRED")
        return urlunsplit(("synthetic", p.netloc.lower(), p.path or "/", p.query, ""))
    if p.scheme != "https" or not p.netloc or "@" in p.netloc:
        raise OutboundEngagementHold("HOLD_CP86_PUBLIC_SOURCE_HTTPS_REQUIRED")
    return urlunsplit(("https", p.netloc.lower(), p.path or "/", p.query, ""))


@dataclass(frozen=True)
class OutboundRoute:
    platform: str
    capability: str
    expected_cp83_classification: str
    automation_mode: str
    specific_target_required: bool
    allowed_provenance: tuple[str, ...]
    required_blockers: tuple[str, ...]


@dataclass(frozen=True)
class OutboundEngagementContract:
    contract_id: str
    contract_hash: str
    policy_sha256: str
    routes: tuple[OutboundRoute, ...]
    blockers: tuple[str, ...]
    max_comment_chars: int
    max_evidence_items: int
    checkpoint: str = CHECKPOINT
    parent_activation_checkpoint: str = PARENT_ACTIVATION_CHECKPOINT
    parent_radar_checkpoint: str = PARENT_RADAR_CHECKPOINT
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
class ValueAddProposal:
    composer_mode: str
    material_value_kind: str
    contribution_text: str
    evidence: tuple[str, ...]
    provenance_kind: str
    provenance_ref: str
    target_ref: str
    source_url: str
    generic_compliment_only: bool = False
    engagement_bait_used: bool = False
    repetitive_praise_used: bool = False
    copy_paste_reply_used: bool = False
    mass_commenting_context: bool = False
    engagement_pod_context: bool = False
    sensitive_trait_inference_used: bool = False
    sensitive_relationship_profiling_used: bool = False
    political_microtargeting_used: bool = False
    synthetic_conversation_farming_used: bool = False


@dataclass(frozen=True)
class ManualActionPacket:
    packet_id: str
    platform: str
    target_ref: str
    source_url: str
    suggested_text: str
    composer_mode: str
    material_value_kind: str
    evidence: tuple[str, ...]
    blockers: tuple[str, ...]
    operator_action_required: bool = True
    automated_dispatch_supported: bool = False
    external_write_attempted: bool = False
    receipt: str = "NOT_APPLICABLE_NO_EXTERNAL_WRITE"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = list(self.evidence)
        value["blockers"] = list(self.blockers)
        return value


@dataclass(frozen=True)
class OutboundEngagementCandidate:
    candidate_id: str
    proposal_hash: str
    radar_candidate_id: str
    radar_observation_hash: str
    platform: str
    target_ref: str
    source_url: str
    composer_mode: str
    material_value_kind: str
    contribution_text: str | None
    evidence: tuple[str, ...]
    cp83_classification: str
    automation_mode: str
    decision: str
    decision_reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    manual_action_packet: ManualActionPacket | None
    human_review_required: bool = True
    posting_authority: bool = False
    external_write_allowed: bool = False
    external_write_attempted: bool = False
    network_fetch_performed: bool = False
    external_metrics: str = UNKNOWN_EXTERNAL_METRIC_VALUE

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = list(self.evidence)
        value["decision_reasons"] = list(self.decision_reasons)
        value["blockers"] = list(self.blockers)
        value["manual_action_packet"] = (
            self.manual_action_packet.to_dict() if self.manual_action_packet else None
        )
        return value


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"),
        policy.get("checkpoint"),
        policy.get("module_id"),
        policy.get("parent_activation_checkpoint"),
        policy.get("parent_radar_checkpoint"),
        policy.get("parent_capability_checkpoint"),
        policy.get("parent_control_checkpoint"),
        policy.get("next_after_cp86"),
    )
    expected = (
        "PPOS_OUTBOUND_VALUE_ADD_ENGAGEMENT_ENGINE_POLICY_V1",
        CHECKPOINT,
        "M55_OUTBOUND_VALUE_ADD_ENGAGEMENT_ENGINE",
        PARENT_ACTIVATION_CHECKPOINT,
        PARENT_RADAR_CHECKPOINT,
        PARENT_CAPABILITY_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        NEXT_UNIT,
    )
    if identity != expected:
        raise OutboundEngagementHold("HOLD_CP86_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise OutboundEngagementHold("HOLD_CP86_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("composer_modes", ())) != COMPOSER_MODES:
        raise OutboundEngagementHold("HOLD_CP86_COMPOSER_MODE_DRIFT")
    if tuple(policy.get("material_value_kinds", ())) != MATERIAL_VALUE_KINDS:
        raise OutboundEngagementHold("HOLD_CP86_MATERIAL_VALUE_KIND_DRIFT")
    if tuple(policy.get("provenance_kinds", ())) != PROVENANCE_KINDS:
        raise OutboundEngagementHold("HOLD_CP86_PROVENANCE_KIND_DRIFT")
    if policy.get("global_kill_switch") != "ENGAGED":
        raise OutboundEngagementHold("HOLD_CP86_KILL_SWITCH_NOT_ENGAGED")
    if policy.get("unknown_external_metric_value") != UNKNOWN_EXTERNAL_METRIC_VALUE:
        raise OutboundEngagementHold("HOLD_CP86_UNKNOWN_METRIC_DRIFT")

    authority = policy.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise OutboundEngagementHold("HOLD_CP86_LIVE_AUTHORITY_DRIFT")
    safety = policy.get("growth_safety")
    if not isinstance(safety, Mapping) or not safety or not all(value is True for value in safety.values()):
        raise OutboundEngagementHold("HOLD_CP86_GROWTH_SAFETY_WEAKENED")

    candidate_input = policy.get("candidate_input")
    if not isinstance(candidate_input, Mapping):
        raise OutboundEngagementHold("HOLD_CP86_CANDIDATE_INPUT_MISSING")
    if candidate_input.get("cp84_decision_required") != "ELIGIBLE_HUMAN_REVIEW":
        raise OutboundEngagementHold("HOLD_CP86_CP84_GATE_WEAKENED")
    for key in ("fact_bound_evidence_required", "exact_target_required", "human_review_required"):
        if candidate_input.get(key) is not True:
            raise OutboundEngagementHold("HOLD_CP86_CANDIDATE_SAFETY_WEAKENED")
    max_chars = candidate_input.get("max_comment_chars")
    max_evidence = candidate_input.get("max_evidence_items")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 1000:
        raise OutboundEngagementHold("HOLD_CP86_COMMENT_LIMIT_INVALID")
    if isinstance(max_evidence, bool) or not isinstance(max_evidence, int) or not 1 <= max_evidence <= 10:
        raise OutboundEngagementHold("HOLD_CP86_EVIDENCE_LIMIT_INVALID")

    routes = policy.get("outbound_routes")
    if not isinstance(routes, list) or len(routes) != len(ACTIVE_PLATFORMS):
        raise OutboundEngagementHold("HOLD_CP86_ROUTE_CARDINALITY")
    if {r.get("platform") for r in routes if isinstance(r, Mapping)} != set(ACTIVE_PLATFORMS):
        raise OutboundEngagementHold("HOLD_CP86_ROUTE_NOT_EXACT_ACTIVE_PLATFORMS")
    for route in routes:
        if not isinstance(route, Mapping) or route.get("capability") != "OUTBOUND_COMMENT":
            raise OutboundEngagementHold("HOLD_CP86_ROUTE_INVALID")
        classification = route.get("expected_cp83_classification")
        if classification not in {"PASS_OFFLINE_CONTRACT", "HOLD_LIVE_PERMISSION", "UNSUPPORTED", "MANUAL_ONLY"}:
            raise OutboundEngagementHold("HOLD_CP86_ROUTE_CLASSIFICATION_INVALID")
        if route.get("specific_target_required") is not True:
            raise OutboundEngagementHold("HOLD_CP86_BROAD_OUTBOUND_FORBIDDEN")
        allowed = tuple(route.get("allowed_provenance", ()))
        if not allowed or not set(allowed).issubset(PROVENANCE_KINDS):
            raise OutboundEngagementHold("HOLD_CP86_ROUTE_PROVENANCE_INVALID")
        blockers = route.get("required_blockers")
        if not isinstance(blockers, list) or not blockers:
            raise OutboundEngagementHold("HOLD_CP86_ROUTE_BLOCKERS_REQUIRED")
        mode = route.get("automation_mode")
        if classification in {"MANUAL_ONLY", "UNSUPPORTED", "HOLD_LIVE_PERMISSION"}:
            if mode != "MANUAL_ACTION_PACKET":
                raise OutboundEngagementHold("HOLD_CP86_MANUAL_PACKET_REQUIRED")
        elif mode != "DRY_RUN_API_CANDIDATE":
            raise OutboundEngagementHold("HOLD_CP86_PASS_ROUTE_MUST_REMAIN_DRY_RUN")


def compile_outbound_engagement_engine(
    policy: Mapping[str, Any],
    capability_contract: GrowthCapabilityMatrixContract,
) -> OutboundEngagementContract:
    validate_policy(policy)
    if capability_contract.checkpoint != PARENT_CAPABILITY_CHECKPOINT:
        raise OutboundEngagementHold("HOLD_CP86_PARENT_CAPABILITY_CONTRACT_INVALID")
    if capability_contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise OutboundEngagementHold("HOLD_CP86_PARENT_CONTROL_DRIFT")
    if not capability_contract.global_kill_switch_engaged:
        raise OutboundEngagementHold("HOLD_CP86_PARENT_KILL_SWITCH_NOT_ENGAGED")

    routes: list[OutboundRoute] = []
    for item in policy["outbound_routes"]:
        try:
            parent = capability_lookup(capability_contract, item["platform"], "OUTBOUND_COMMENT")
        except GrowthCapabilityMatrixHold as exc:
            raise OutboundEngagementHold("HOLD_CAPABILITY_UNVERIFIED") from exc
        if parent.classification != item["expected_cp83_classification"]:
            raise OutboundEngagementHold("HOLD_CP86_PARENT_CLASSIFICATION_DRIFT")
        if parent.broad_outbound_allowed:
            raise OutboundEngagementHold("HOLD_CP86_PARENT_BROAD_OUTBOUND_DRIFT")
        expected_mode = "MANUAL_ACTION_PACKET" if parent.classification != "PASS_OFFLINE_CONTRACT" else "DRY_RUN_API_CANDIDATE"
        if item["automation_mode"] != expected_mode:
            raise OutboundEngagementHold("HOLD_CP86_PARENT_AUTOMATION_MODE_DRIFT")
        if not set(item["required_blockers"]).issubset(set(parent.blockers) | {"HOLD_CAPABILITY_UNVERIFIED"}):
            raise OutboundEngagementHold("HOLD_CP86_PARENT_BLOCKER_DRIFT")
        routes.append(OutboundRoute(
            platform=item["platform"],
            capability="OUTBOUND_COMMENT",
            expected_cp83_classification=item["expected_cp83_classification"],
            automation_mode=item["automation_mode"],
            specific_target_required=True,
            allowed_provenance=tuple(item["allowed_provenance"]),
            required_blockers=tuple(item["required_blockers"]),
        ))

    payload = {
        "checkpoint": CHECKPOINT,
        "parent_activation_checkpoint": PARENT_ACTIVATION_CHECKPOINT,
        "parent_radar_checkpoint": PARENT_RADAR_CHECKPOINT,
        "parent_capability_checkpoint": PARENT_CAPABILITY_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "next_unit": NEXT_UNIT,
        "routes": [asdict(route) for route in routes],
        "candidate_input": policy["candidate_input"],
        "global_kill_switch": policy["global_kill_switch"],
    }
    contract_hash = _hash(payload)
    return OutboundEngagementContract(
        contract_id=f"cp86-outbound-value-add-{contract_hash[:16]}",
        contract_hash=contract_hash,
        policy_sha256=_hash(policy),
        routes=tuple(routes),
        blockers=tuple(policy["required_blockers"]),
        max_comment_chars=int(policy["candidate_input"]["max_comment_chars"]),
        max_evidence_items=int(policy["candidate_input"]["max_evidence_items"]),
    )


def _route_for(contract: OutboundEngagementContract, platform: str) -> OutboundRoute:
    if platform not in ACTIVE_PLATFORMS:
        raise OutboundEngagementHold("HOLD_CAPABILITY_UNVERIFIED")
    for route in contract.routes:
        if route.platform == platform:
            return route
    raise OutboundEngagementHold("HOLD_CAPABILITY_UNVERIFIED")


def _normalize_proposal(
    contract: OutboundEngagementContract,
    radar_candidate: EngagementCandidate,
    proposal: ValueAddProposal,
) -> dict[str, Any]:
    if not isinstance(radar_candidate, EngagementCandidate):
        raise OutboundEngagementHold("HOLD_CP86_RADAR_CANDIDATE_TYPE")
    if not isinstance(proposal, ValueAddProposal):
        raise OutboundEngagementHold("HOLD_CP86_PROPOSAL_TYPE")
    if radar_candidate.decision != "ELIGIBLE_HUMAN_REVIEW":
        return {"reject": "REJECT_CP84_NOT_ELIGIBLE"}
    route = _route_for(contract, radar_candidate.platform)
    if proposal.composer_mode not in COMPOSER_MODES:
        raise OutboundEngagementHold("HOLD_CP86_COMPOSER_MODE_INVALID")
    if proposal.material_value_kind not in MATERIAL_VALUE_KINDS:
        raise OutboundEngagementHold("HOLD_CP86_MATERIAL_VALUE_KIND_INVALID")
    if proposal.provenance_kind not in route.allowed_provenance:
        raise OutboundEngagementHold("HOLD_CP86_PROVENANCE_NOT_ALLOWED_FOR_ROUTE")

    target_ref = _norm_text(proposal.target_ref, name="target_ref", max_len=MAX_REF)
    if target_ref != radar_candidate.conversation_ref:
        raise OutboundEngagementHold("HOLD_CP86_EXACT_TARGET_MISMATCH")
    source_url = _norm_source_url(proposal.source_url, proposal.provenance_kind)
    if source_url != radar_candidate.source_url:
        raise OutboundEngagementHold("HOLD_CP86_SOURCE_BINDING_MISMATCH")
    provenance_ref = _norm_text(proposal.provenance_ref, name="provenance_ref", max_len=MAX_REF)

    contribution = _norm_text(proposal.contribution_text, name="contribution_text", max_len=contract.max_comment_chars)
    if proposal.composer_mode == "GOOD_QUESTION" and not contribution.endswith("?"):
        raise OutboundEngagementHold("HOLD_CP86_GOOD_QUESTION_MUST_BE_CONCRETE_QUESTION")

    if not isinstance(proposal.evidence, tuple) or not proposal.evidence:
        return {"reject": "REJECT_NO_FACT_BOUND_EVIDENCE"}
    if len(proposal.evidence) > contract.max_evidence_items:
        raise OutboundEngagementHold("HOLD_CP86_EVIDENCE_LIMIT_EXCEEDED")
    evidence = tuple(_norm_text(item, name="evidence_item", max_len=MAX_TEXT) for item in proposal.evidence)

    flags = {
        "generic_compliment_only": proposal.generic_compliment_only,
        "engagement_bait_used": proposal.engagement_bait_used,
        "repetitive_praise_used": proposal.repetitive_praise_used,
        "copy_paste_reply_used": proposal.copy_paste_reply_used,
        "mass_commenting_context": proposal.mass_commenting_context,
        "engagement_pod_context": proposal.engagement_pod_context,
        "sensitive_trait_inference_used": proposal.sensitive_trait_inference_used,
        "sensitive_relationship_profiling_used": proposal.sensitive_relationship_profiling_used,
        "political_microtargeting_used": proposal.political_microtargeting_used,
        "synthetic_conversation_farming_used": proposal.synthetic_conversation_farming_used,
    }
    if any(not isinstance(value, bool) for value in flags.values()):
        raise OutboundEngagementHold("HOLD_CP86_SAFETY_FLAG_INVALID")
    return {"route":route,"target_ref":target_ref,"source_url":source_url,"provenance_ref":provenance_ref,"contribution":contribution,"evidence":evidence,"flags":flags}


def compose_outbound_candidate(
    contract: OutboundEngagementContract,
    radar_candidate: EngagementCandidate,
    proposal: ValueAddProposal,
) -> OutboundEngagementCandidate:
    normalized = _normalize_proposal(contract, radar_candidate, proposal)
    route = _route_for(contract, radar_candidate.platform)
    reject = normalized.get("reject")
    if reject:
        payload = {"radar_candidate_id":radar_candidate.candidate_id,"platform":radar_candidate.platform,"target_ref":proposal.target_ref,"composer_mode":proposal.composer_mode,"material_value_kind":proposal.material_value_kind,"reject":reject}
        return OutboundEngagementCandidate(
            candidate_id=_hash({"platform":radar_candidate.platform,"target_ref":proposal.target_ref}),
            proposal_hash=_hash(payload),
            radar_candidate_id=radar_candidate.candidate_id,
            radar_observation_hash=radar_candidate.observation_hash,
            platform=radar_candidate.platform,
            target_ref=proposal.target_ref,
            source_url=proposal.source_url,
            composer_mode=proposal.composer_mode,
            material_value_kind=proposal.material_value_kind,
            contribution_text=None,
            evidence=(),
            cp83_classification=route.expected_cp83_classification,
            automation_mode=route.automation_mode,
            decision=reject,
            decision_reasons=(reject,),
            blockers=tuple(sorted(set(contract.blockers) | set(route.required_blockers))),
            manual_action_packet=None,
        )

    flags = normalized["flags"]
    if any(flags.values()):
        decision = "REJECT_GROWTH_SAFETY"
        reasons = tuple(key.upper() for key, value in flags.items() if value)
        contribution_text = None
        packet = None
    elif route.expected_cp83_classification != "PASS_OFFLINE_CONTRACT":
        decision = "MANUAL_ACTION_REQUIRED"
        reasons = ("OFFICIAL_API_AUTOMATION_NOT_EXACTLY_VERIFIED",)
        packet_payload = {"platform":radar_candidate.platform,"target_ref":normalized["target_ref"],"source_url":normalized["source_url"],"suggested_text":normalized["contribution"],"composer_mode":proposal.composer_mode,"material_value_kind":proposal.material_value_kind,"evidence":normalized["evidence"],"blockers":route.required_blockers}
        packet = ManualActionPacket(
            packet_id=f"manual-cp86-{_hash(packet_payload)[:20]}",
            platform=radar_candidate.platform,
            target_ref=normalized["target_ref"],
            source_url=normalized["source_url"],
            suggested_text=normalized["contribution"],
            composer_mode=proposal.composer_mode,
            material_value_kind=proposal.material_value_kind,
            evidence=normalized["evidence"],
            blockers=route.required_blockers,
        )
        contribution_text = normalized["contribution"]
    else:
        decision = "DRY_RUN_API_CANDIDATE_HUMAN_REVIEW"
        reasons = ("MATERIAL_VALUE_PRESENT","EXACT_TARGET_BOUND","LIVE_PERMISSION_AND_PILOT_AUTHORIZATION_STILL_REQUIRED")
        contribution_text = normalized["contribution"]
        packet = None

    proposal_payload = {"radar_candidate_id":radar_candidate.candidate_id,"radar_observation_hash":radar_candidate.observation_hash,"platform":radar_candidate.platform,"target_ref":normalized["target_ref"],"source_url":normalized["source_url"],"provenance_kind":proposal.provenance_kind,"provenance_ref":normalized["provenance_ref"],"composer_mode":proposal.composer_mode,"material_value_kind":proposal.material_value_kind,"contribution":normalized["contribution"],"evidence":normalized["evidence"],"safety_flags":flags,"cp83_classification":route.expected_cp83_classification}
    blockers = tuple(sorted(set(contract.blockers) | set(route.required_blockers)))
    return OutboundEngagementCandidate(
        candidate_id=_hash({"platform":radar_candidate.platform,"target_ref":normalized["target_ref"]}),
        proposal_hash=_hash(proposal_payload),
        radar_candidate_id=radar_candidate.candidate_id,
        radar_observation_hash=radar_candidate.observation_hash,
        platform=radar_candidate.platform,
        target_ref=normalized["target_ref"],
        source_url=normalized["source_url"],
        composer_mode=proposal.composer_mode,
        material_value_kind=proposal.material_value_kind,
        contribution_text=contribution_text,
        evidence=normalized["evidence"],
        cp83_classification=route.expected_cp83_classification,
        automation_mode=route.automation_mode,
        decision=decision,
        decision_reasons=reasons,
        blockers=blockers,
        manual_action_packet=packet,
    )


def process_batch(
    contract: OutboundEngagementContract,
    items: Sequence[tuple[EngagementCandidate, ValueAddProposal]],
) -> tuple[OutboundEngagementCandidate, ...]:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise OutboundEngagementHold("HOLD_CP86_BATCH_TYPE")
    if len(items) > MAX_BATCH:
        raise OutboundEngagementHold("HOLD_CP86_BATCH_TOO_LARGE")
    by_identity: dict[str, OutboundEngagementCandidate] = {}
    for pair in items:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise OutboundEngagementHold("HOLD_CP86_BATCH_ITEM_INVALID")
        candidate = compose_outbound_candidate(contract, pair[0], pair[1])
        previous = by_identity.get(candidate.candidate_id)
        if previous is None:
            by_identity[candidate.candidate_id] = candidate
        elif previous.proposal_hash != candidate.proposal_hash:
            raise OutboundEngagementHold("HOLD_CP86_CONFLICTING_DUPLICATE_TARGET")
    return tuple(sorted(by_identity.values(), key=lambda item: (item.platform, item.target_ref)))
