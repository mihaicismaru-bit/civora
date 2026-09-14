from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

MODEL_VERSION = "PPOS_GROWTH_CAPABILITY_MATRIX_ENGAGEMENT_API_GATE_V1"
ENGINE_VERSION = "ppos-growth-capability-matrix-engagement-api-gate-v1.0.0"
CHECKPOINT = "CP83"
PARENT_ACTIVATION_CHECKPOINT = "CP82"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP84_ENGAGEMENT_RADAR"
STATE = "PASS_CP83_GROWTH_CAPABILITY_MATRIX_ENGAGEMENT_API_GATE_OFFLINE_CONTRACT_LIVE_PERMISSION_HOLD_MANUAL_FALLBACK_NO_EXTERNAL_CONNECTION_LIVE_HOLD"

ACTIVE_PLATFORMS = ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
CAPABILITY_KINDS = (
    "INBOUND_REPLY",
    "OUTBOUND_COMMENT",
    "MENTION_DISCOVERY",
    "HASHTAG_TOPIC_DISCOVERY",
    "QUOTE_REPOST",
    "INSIGHTS",
    "FOLLOW",
)
ALLOWED_CLASSIFICATIONS = (
    "PASS_OFFLINE_CONTRACT",
    "HOLD_LIVE_PERMISSION",
    "UNSUPPORTED",
    "MANUAL_ONLY",
)
UNKNOWN_CAPABILITY_STATE = "HOLD_CAPABILITY_UNVERIFIED"
UNKNOWN_EXTERNAL_METRIC_VALUE = "UNKNOWN"
EXPECTED_ROWS = len(ACTIVE_PLATFORMS) * len(CAPABILITY_KINDS)


class GrowthCapabilityMatrixHold(ValueError):
    """Fail-closed CP83 contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CapabilityRow:
    platform: str
    capability: str
    classification: str
    scope: str
    source_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    live_gate: str
    automation_mode: str
    read_surface: bool
    write_surface: bool
    broad_outbound_allowed: bool
    manual_action_packet: bool
    external_metrics: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_ids"] = list(self.source_ids)
        d["blockers"] = list(self.blockers)
        return d


@dataclass(frozen=True)
class GrowthCapabilityMatrixContract:
    contract_id: str
    contract_hash: str
    policy_sha256: str
    rows: tuple[CapabilityRow, ...]
    official_source_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    excluded_platforms: Mapping[str, str]
    checkpoint: str = CHECKPOINT
    parent_activation_checkpoint: str = PARENT_ACTIVATION_CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    next_unit: str = NEXT_UNIT
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    expected_rows: int = EXPECTED_ROWS
    all_twenty_one_rows_present: bool = True
    exact_platform_capability_cartesian_product: bool = True
    unknown_capability_fails_closed: bool = True
    manual_packet_fallback_required: bool = True
    automated_follow_unfollow_forbidden: bool = True
    broad_outbound_commenting_not_assumed: bool = True
    unavailable_external_metrics_remain_unknown: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_ingested: bool = False
    authorization_granted: bool = False
    runtime_authorization_effective: bool = False
    secret_reference_resolved: bool = False
    oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    network_allowed: bool = False
    network_attempted: bool = False
    live_probe_allowed: bool = False
    live_probe_attempted: bool = False
    publish_allowed: bool = False
    publish_attempted: bool = False
    external_write_allowed: bool = False
    external_write_performed: bool = False
    control_plane_promoted: bool = False
    deploy_allowed: bool = False
    deploy_performed: bool = False
    paid_service_used: bool = False
    authority_activated: bool = False
    runtime_mutated: bool = False
    state: str = STATE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rows"] = [row.to_dict() for row in self.rows]
        d["official_source_ids"] = list(self.official_source_ids)
        d["blockers"] = list(self.blockers)
        d["excluded_platforms"] = dict(self.excluded_platforms)
        return d


def _required_cartesian() -> set[tuple[str, str]]:
    return {(p, c) for p in ACTIVE_PLATFORMS for c in CAPABILITY_KINDS}


def validate_policy(policy: Mapping[str, Any]) -> None:
    identity = (
        policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id"),
        policy.get("parent_activation_checkpoint"), policy.get("parent_control_checkpoint"),
        policy.get("next_after_cp83"),
    )
    expected_identity = (
        "PPOS_GROWTH_CAPABILITY_MATRIX_ENGAGEMENT_API_GATE_POLICY_V1", CHECKPOINT,
        "M52_GROWTH_CAPABILITY_MATRIX_ENGAGEMENT_API_GATE", PARENT_ACTIVATION_CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT, NEXT_UNIT,
    )
    if identity != expected_identity:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != ACTIVE_PLATFORMS:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("capability_kinds", ())) != CAPABILITY_KINDS:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_CAPABILITY_KIND_DRIFT")
    if tuple(policy.get("allowed_classifications", ())) != ALLOWED_CLASSIFICATIONS:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_CLASSIFICATION_DRIFT")
    if policy.get("unknown_capability_state") != UNKNOWN_CAPABILITY_STATE:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_UNKNOWN_CAPABILITY_NOT_FAIL_CLOSED")
    if policy.get("unknown_external_metric_value") != UNKNOWN_EXTERNAL_METRIC_VALUE:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_UNKNOWN_METRIC_DRIFT")
    if policy.get("global_kill_switch") != "ENGAGED":
        raise GrowthCapabilityMatrixHold("HOLD_CP83_KILL_SWITCH_NOT_ENGAGED")

    authority = policy.get("authority")
    if not isinstance(authority, Mapping):
        raise GrowthCapabilityMatrixHold("HOLD_CP83_AUTHORITY_MISSING")
    forbidden_true = (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
        "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed",
        "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated",
    )
    if any(authority.get(key) is not False for key in forbidden_true):
        raise GrowthCapabilityMatrixHold("HOLD_CP83_LIVE_AUTHORITY_DRIFT")

    safety = policy.get("growth_safety")
    if not isinstance(safety, Mapping) or not all(bool(v) for v in safety.values()):
        raise GrowthCapabilityMatrixHold("HOLD_CP83_GROWTH_SAFETY_WEAKENED")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_USEFUL_API_IS_PAID",
        "BLUESKY": "HOLD_ROI",
    }:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_EXCLUDED_PLATFORM_DRIFT")

    sources = policy.get("official_sources")
    if not isinstance(sources, list) or not sources:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_OFFICIAL_SOURCES_MISSING")
    source_ids = {s.get("source_id") for s in sources if isinstance(s, Mapping)}
    if None in source_ids or len(source_ids) != len(sources):
        raise GrowthCapabilityMatrixHold("HOLD_CP83_SOURCE_ID_INVALID")

    matrix = policy.get("capability_matrix")
    if not isinstance(matrix, list) or len(matrix) != EXPECTED_ROWS:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_MATRIX_CARDINALITY")
    pairs = {(r.get("platform"), r.get("capability")) for r in matrix if isinstance(r, Mapping)}
    if pairs != _required_cartesian():
        raise GrowthCapabilityMatrixHold("HOLD_CP83_MATRIX_NOT_EXACT_CARTESIAN")

    for r in matrix:
        if not isinstance(r, Mapping):
            raise GrowthCapabilityMatrixHold("HOLD_CP83_ROW_INVALID")
        if r.get("classification") not in ALLOWED_CLASSIFICATIONS:
            raise GrowthCapabilityMatrixHold("HOLD_CP83_ROW_CLASSIFICATION_INVALID")
        if not set(r.get("source_ids", ())).issubset(source_ids):
            raise GrowthCapabilityMatrixHold("HOLD_CP83_ROW_SOURCE_UNKNOWN")
        if r.get("broad_outbound_allowed") is not False:
            raise GrowthCapabilityMatrixHold("HOLD_CP83_BROAD_OUTBOUND_FORBIDDEN")
        if r.get("capability") == "FOLLOW":
            if r.get("classification") != "MANUAL_ONLY":
                raise GrowthCapabilityMatrixHold("HOLD_CP83_FOLLOW_MUST_BE_MANUAL_ONLY")
            if r.get("automation_mode") != "MANUAL_ACTION_PACKET" or r.get("manual_action_packet") is not True:
                raise GrowthCapabilityMatrixHold("HOLD_CP83_FOLLOW_MANUAL_PACKET_REQUIRED")
        if r.get("classification") in {"MANUAL_ONLY", "UNSUPPORTED"}:
            if r.get("automation_mode") != "MANUAL_ACTION_PACKET" or r.get("manual_action_packet") is not True:
                raise GrowthCapabilityMatrixHold("HOLD_CP83_MANUAL_PACKET_REQUIRED")
        if r.get("write_surface") is True and r.get("classification") == "PASS_OFFLINE_CONTRACT":
            if "HOLD_LIVE_PERMISSION" not in set(r.get("blockers", ())):
                raise GrowthCapabilityMatrixHold("HOLD_CP83_WRITE_WITHOUT_LIVE_PERMISSION_GATE")
        if r.get("external_metrics") != UNKNOWN_EXTERNAL_METRIC_VALUE:
            raise GrowthCapabilityMatrixHold("HOLD_CP83_EXTERNAL_METRIC_FABRICATED")

    by_key = {(r["platform"], r["capability"]): r for r in matrix}
    for key in (
        ("FACEBOOK_PAGE", "OUTBOUND_COMMENT"), ("INSTAGRAM_PROFESSIONAL", "OUTBOUND_COMMENT"),
        ("FACEBOOK_PAGE", "FOLLOW"), ("INSTAGRAM_PROFESSIONAL", "FOLLOW"), ("THREADS", "FOLLOW"),
    ):
        if by_key[key]["classification"] != "MANUAL_ONLY":
            raise GrowthCapabilityMatrixHold("HOLD_CP83_POLICY_MANDATED_MANUAL_SURFACE_DRIFT")
    threads_outbound = by_key[("THREADS", "OUTBOUND_COMMENT")]
    if threads_outbound["classification"] == "PASS_OFFLINE_CONTRACT" and "specific readable post/reply" not in threads_outbound["scope"]:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_THREADS_OUTBOUND_SCOPE_TOO_BROAD")


def compile_growth_capability_matrix(policy: Mapping[str, Any]) -> GrowthCapabilityMatrixContract:
    validate_policy(policy)
    rows = tuple(CapabilityRow(
        platform=r["platform"], capability=r["capability"], classification=r["classification"], scope=r["scope"],
        source_ids=tuple(r["source_ids"]), blockers=tuple(r["blockers"]), live_gate=r["live_gate"],
        automation_mode=r["automation_mode"], read_surface=bool(r["read_surface"]), write_surface=bool(r["write_surface"]),
        broad_outbound_allowed=bool(r["broad_outbound_allowed"]), manual_action_packet=bool(r["manual_action_packet"]),
        external_metrics=r["external_metrics"],
    ) for r in policy["capability_matrix"])
    payload = {
        "checkpoint": CHECKPOINT, "parent_activation_checkpoint": PARENT_ACTIVATION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT, "next_unit": NEXT_UNIT,
        "rows": [r.to_dict() for r in rows], "official_source_ids": [s["source_id"] for s in policy["official_sources"]],
        "excluded_platforms": policy["excluded_platforms"], "required_blockers": policy["required_blockers"],
        "global_kill_switch": policy["global_kill_switch"],
    }
    contract_hash = _hash(payload)
    return GrowthCapabilityMatrixContract(
        contract_id=f"cp83-growth-capability-matrix-{contract_hash[:16]}", contract_hash=contract_hash,
        policy_sha256=_hash(policy), rows=rows, official_source_ids=tuple(s["source_id"] for s in policy["official_sources"]),
        blockers=tuple(policy["required_blockers"]), excluded_platforms=dict(policy["excluded_platforms"]),
    )


def capability_lookup(contract: GrowthCapabilityMatrixContract, platform: str, capability: str) -> CapabilityRow:
    if platform not in ACTIVE_PLATFORMS or capability not in CAPABILITY_KINDS:
        raise GrowthCapabilityMatrixHold(UNKNOWN_CAPABILITY_STATE)
    for row in contract.rows:
        if row.platform == platform and row.capability == capability:
            return row
    raise GrowthCapabilityMatrixHold(UNKNOWN_CAPABILITY_STATE)


def build_manual_action_packet(contract: GrowthCapabilityMatrixContract, platform: str, capability: str, context_id: str) -> dict[str, Any]:
    row = capability_lookup(contract, platform, capability)
    if row.classification not in {"MANUAL_ONLY", "UNSUPPORTED"}:
        raise GrowthCapabilityMatrixHold("HOLD_CP83_MANUAL_PACKET_NOT_REQUIRED")
    if not isinstance(context_id, str) or not context_id.strip():
        raise GrowthCapabilityMatrixHold("HOLD_CP83_MANUAL_PACKET_CONTEXT_REQUIRED")
    packet = {
        "schema_version": "PPOS_MANUAL_ACTION_PACKET_V1", "checkpoint": CHECKPOINT,
        "platform": platform, "capability": capability, "context_id": context_id.strip(),
        "classification": row.classification, "scope": row.scope, "blockers": list(row.blockers),
        "automation_attempted": False, "external_write_attempted": False,
        "requires_human_review": True, "kill_switch": "ENGAGED",
    }
    packet["packet_sha256"] = _hash(packet)
    return packet
