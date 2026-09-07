from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re
from pathlib import Path
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .pilot_package_acceptance import (
    STATE as CP59_STATE,
    compile_pilot_package_acceptance,
    validate_pilot_package_acceptance_receipt,
)

MODEL_VERSION = "PPOS_OPERATOR_PILOT_HANDOFF_V1"
ENGINE_VERSION = "ppos-operator-pilot-handoff-v1.0.0"
STATE = "PASS_CP60_OPERATOR_HANDOFF_READY_AUTHORIZATION_HOLD"
CHECKPOINT = "CP60"
PARENT_ACCEPTANCE_CHECKPOINT = "CP59"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP61_CONTROL_PLANE_PROMOTION_AND_AUTHORIZATION_INTAKE_CONTRACT"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_BLOCKERS = (
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_LIVE_READ_ONLY_AUTHORIZATION_NOT_GRANTED",
    "HOLD_PILOT_PUBLISH_AUTHORIZATION_NOT_GRANTED",
    "HOLD_GLOBAL_CONTROL_CHECKPOINT_PROMOTION",
)

EXPECTED_GATE_CODES = (
    "LIVE_READ_ONLY_CONNECTION_PROBE",
    "PILOT_PUBLISH",
)


class OperatorPilotHandoffError(ValueError):
    pass


class OperatorPilotHandoffHold(OperatorPilotHandoffError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class HandoffChecklistItem:
    code: str
    description: str
    required: bool
    status: str = "READY_FOR_OPERATOR_REVIEW"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AuthorizationGateTemplate:
    gate_code: str
    state: str
    decision_source: str
    allowed_platforms: tuple[str, ...]
    scope: str
    may_publish: bool
    may_deploy: bool
    authorizer_reference: str | None = None
    authorized_at: str | None = None
    authorization_evidence_sha256: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["allowed_platforms"] = list(self.allowed_platforms)
        return data


@dataclass(frozen=True)
class OperatorPilotHandoffPacket:
    packet_id: str
    packet_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_acceptance_checkpoint: str
    parent_control_checkpoint: str
    cp59_acceptance_id: str
    cp59_acceptance_hash: str
    cp59_source_manifest_sha256: str
    policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    checklist: tuple[HandoffChecklistItem, ...]
    authorization_gates: tuple[AuthorizationGateTemplate, ...]
    blockers: tuple[str, ...]
    next_unit: str
    cp59_final_offline_acceptance_validated: bool = True
    operator_handoff_ready: bool = True
    global_kill_switch_engaged: bool = True
    live_evidence_captured: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
    oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    network_attempted: bool = False
    publish_attempted: bool = False
    external_write_performed: bool = False
    deploy_performed: bool = False
    paid_service_used: bool = False
    live_read_only_authorization_granted: bool = False
    pilot_publish_authorization_granted: bool = False
    self_authorization_performed: bool = False
    state: str = STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["checklist"] = [item.to_dict() for item in self.checklist]
        data["authorization_gates"] = [item.to_dict() for item in self.authorization_gates]
        data["blockers"] = list(self.blockers)
        return data


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_OPERATOR_PILOT_HANDOFF_POLICY_V1":
        raise OperatorPilotHandoffHold("HOLD_CP60_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M29_OPERATOR_PILOT_HANDOFF":
        raise OperatorPilotHandoffHold("HOLD_CP60_POLICY_IDENTITY")
    if policy.get("parent_acceptance_checkpoint") != PARENT_ACCEPTANCE_CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_PARENT_ACCEPTANCE_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise OperatorPilotHandoffHold("HOLD_CP60_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise OperatorPilotHandoffHold("HOLD_CP60_BLOCKER_SET_DRIFT")
    if policy.get("next_after_cp60") != NEXT_UNIT:
        raise OperatorPilotHandoffHold("HOLD_CP60_NEXT_UNIT_DRIFT")

    contract = policy.get("handoff_contract", {})
    required_true = (
        "offline_only",
        "cp59_final_offline_acceptance_required",
        "exact_cp59_receipt_binding_required",
        "operator_checklist_required",
        "authorization_packet_defaults_to_hold",
        "authorization_must_be_explicit_external_human",
        "authorization_may_not_be_inferred",
        "authorization_must_be_scope_bound",
        "authorization_must_be_platform_bound",
        "read_only_connection_probe_authorization_separate_from_publish_authorization",
        "global_kill_switch_must_remain_engaged",
        "secret_resolution_forbidden",
        "environment_read_forbidden",
        "keychain_read_forbidden",
        "oauth_forbidden",
        "real_account_lookup_forbidden",
        "account_connection_forbidden",
        "network_forbidden",
        "publish_execution_forbidden",
        "external_write_forbidden",
        "deploy_forbidden",
        "paid_service_forbidden",
        "rollback_to_cp59_required",
    )
    if any(contract.get(key) is not True for key in required_true):
        raise OperatorPilotHandoffHold("HOLD_CP60_HANDOFF_GUARD_MISSING")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise OperatorPilotHandoffHold("HOLD_CP60_EXTERNAL_AUTHORITY_NOT_ZERO")

    excluded = policy.get("excluded_platforms", {})
    if excluded != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise OperatorPilotHandoffHold("HOLD_CP60_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise OperatorPilotHandoffHold("HOLD_CP60_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise OperatorPilotHandoffHold("HOLD_CP60_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise OperatorPilotHandoffHold("HOLD_CP60_RUNTIME_ACTIVE_PLATFORM_DRIFT")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise OperatorPilotHandoffHold("HOLD_CP60_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_GLOBAL_CONTROL_PROMOTION_FORBIDDEN")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M28_PILOT_PACKAGE_ACCEPTANCE") != "CP59_FINAL_OFFLINE_ACCEPTANCE_PASS_LIVE_GATES_HOLD":
        raise OperatorPilotHandoffHold("HOLD_CP60_CP59_MODULE_STATE_DRIFT")
    if states.get("M29_OPERATOR_PILOT_HANDOFF") != "CP60_OPERATOR_HANDOFF_READY_AUTHORIZATION_HOLD":
        raise OperatorPilotHandoffHold("HOLD_CP60_MODULE_STATE_DRIFT")


def _compile_checklist(policy: dict) -> tuple[HandoffChecklistItem, ...]:
    rows = policy.get("operator_checklist", [])
    if not rows:
        raise OperatorPilotHandoffHold("HOLD_CP60_CHECKLIST_MISSING")
    items = tuple(
        HandoffChecklistItem(
            code=str(row.get("code", "")),
            description=str(row.get("description", "")),
            required=row.get("required") is True,
        )
        for row in rows
    )
    if any(not item.code or not item.description or not item.required for item in items):
        raise OperatorPilotHandoffHold("HOLD_CP60_CHECKLIST_INVALID")
    if len({item.code for item in items}) != len(items):
        raise OperatorPilotHandoffHold("HOLD_CP60_CHECKLIST_DUPLICATE_CODE")
    return items


def _compile_authorization_gates(policy: dict) -> tuple[AuthorizationGateTemplate, ...]:
    rows = policy.get("authorization_gates", [])
    if tuple(row.get("gate_code") for row in rows) != EXPECTED_GATE_CODES:
        raise OperatorPilotHandoffHold("HOLD_CP60_AUTHORIZATION_GATE_SET_DRIFT")
    gates: list[AuthorizationGateTemplate] = []
    for row in rows:
        if row.get("default_state") != "NOT_GRANTED":
            raise OperatorPilotHandoffHold("HOLD_CP60_AUTHORIZATION_DEFAULT_NOT_HOLD")
        if row.get("decision_source") != "EXTERNAL_HUMAN_ONLY":
            raise OperatorPilotHandoffHold("HOLD_CP60_AUTHORIZATION_SOURCE_DRIFT")
        if tuple(row.get("allowed_platforms", ())) != EXPECTED_ACTIVE:
            raise OperatorPilotHandoffHold("HOLD_CP60_AUTHORIZATION_PLATFORM_DRIFT")
        if row.get("may_publish") is not False or row.get("may_deploy") is not False:
            raise OperatorPilotHandoffHold("HOLD_CP60_AUTHORIZATION_SCOPE_TOO_BROAD")
        scope = str(row.get("scope", ""))
        if not scope:
            raise OperatorPilotHandoffHold("HOLD_CP60_AUTHORIZATION_SCOPE_MISSING")
        gates.append(
            AuthorizationGateTemplate(
                gate_code=row["gate_code"],
                state="NOT_GRANTED",
                decision_source="EXTERNAL_HUMAN_ONLY",
                allowed_platforms=EXPECTED_ACTIVE,
                scope=scope,
                may_publish=False,
                may_deploy=False,
            )
        )
    return tuple(gates)


def _packet_body(
    *,
    cp59_acceptance_id: str,
    cp59_acceptance_hash: str,
    cp59_source_manifest_sha256: str,
    policy_sha256: str,
    runtime_policy_sha256: str,
    module_registry_sha256: str,
    checklist: tuple[HandoffChecklistItem, ...],
    authorization_gates: tuple[AuthorizationGateTemplate, ...],
) -> dict:
    return {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_acceptance_checkpoint": PARENT_ACCEPTANCE_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp59_acceptance_id": cp59_acceptance_id,
        "cp59_acceptance_hash": cp59_acceptance_hash,
        "cp59_source_manifest_sha256": cp59_source_manifest_sha256,
        "policy_sha256": policy_sha256,
        "runtime_policy_sha256": runtime_policy_sha256,
        "module_registry_sha256": module_registry_sha256,
        "active_platforms": list(EXPECTED_ACTIVE),
        "checklist": [item.to_dict() for item in checklist],
        "authorization_gates": [item.to_dict() for item in authorization_gates],
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "cp59_final_offline_acceptance_validated": True,
        "operator_handoff_ready": True,
        "global_kill_switch_engaged": True,
        "live_evidence_captured": False,
        "secret_reference_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "oauth_attempted": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "network_attempted": False,
        "publish_attempted": False,
        "external_write_performed": False,
        "deploy_performed": False,
        "paid_service_used": False,
        "live_read_only_authorization_granted": False,
        "pilot_publish_authorization_granted": False,
        "self_authorization_performed": False,
        "state": STATE,
    }


def compile_operator_pilot_handoff(root: Path, policy: dict) -> OperatorPilotHandoffPacket:
    root = root.resolve()
    _validate_policy(policy)

    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp59_policy = load_json(root / "config" / "pilot_package_acceptance_policy.json")
    cp59 = compile_pilot_package_acceptance(root, cp59_policy)
    validate_pilot_package_acceptance_receipt(cp59)
    if cp59.state != CP59_STATE or cp59.acceptance_checkpoint != PARENT_ACCEPTANCE_CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_CP59_ACCEPTANCE_INVALID")
    if cp59.global_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_CP59_CONTROL_BINDING_DRIFT")

    checklist = _compile_checklist(policy)
    authorization_gates = _compile_authorization_gates(policy)
    policy_sha256 = _hash(policy)
    runtime_policy_sha256 = _hash(runtime)
    module_registry_sha256 = _hash(registry)

    body = _packet_body(
        cp59_acceptance_id=cp59.acceptance_id,
        cp59_acceptance_hash=cp59.acceptance_hash,
        cp59_source_manifest_sha256=cp59.source_manifest_sha256,
        policy_sha256=policy_sha256,
        runtime_policy_sha256=runtime_policy_sha256,
        module_registry_sha256=module_registry_sha256,
        checklist=checklist,
        authorization_gates=authorization_gates,
    )
    packet_hash = _hash(body)
    packet = OperatorPilotHandoffPacket(
        packet_id="oph_" + packet_hash[:24],
        packet_hash=packet_hash,
        model_version=MODEL_VERSION,
        engine_version=ENGINE_VERSION,
        checkpoint=CHECKPOINT,
        parent_acceptance_checkpoint=PARENT_ACCEPTANCE_CHECKPOINT,
        parent_control_checkpoint=PARENT_CONTROL_CHECKPOINT,
        cp59_acceptance_id=cp59.acceptance_id,
        cp59_acceptance_hash=cp59.acceptance_hash,
        cp59_source_manifest_sha256=cp59.source_manifest_sha256,
        policy_sha256=policy_sha256,
        runtime_policy_sha256=runtime_policy_sha256,
        module_registry_sha256=module_registry_sha256,
        active_platforms=EXPECTED_ACTIVE,
        checklist=checklist,
        authorization_gates=authorization_gates,
        blockers=REQUIRED_BLOCKERS,
        next_unit=NEXT_UNIT,
    )
    validate_operator_pilot_handoff_packet(packet)
    return packet


def validate_operator_pilot_handoff_packet(packet: OperatorPilotHandoffPacket) -> None:
    if packet.model_version != MODEL_VERSION or packet.engine_version != ENGINE_VERSION:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_VERSION_DRIFT")
    if packet.checkpoint != CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_CHECKPOINT_DRIFT")
    if packet.parent_acceptance_checkpoint != PARENT_ACCEPTANCE_CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_PARENT_ACCEPTANCE_DRIFT")
    if packet.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_PARENT_CONTROL_DRIFT")
    if tuple(packet.active_platforms) != EXPECTED_ACTIVE:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_ACTIVE_PLATFORM_DRIFT")
    if tuple(gate.gate_code for gate in packet.authorization_gates) != EXPECTED_GATE_CODES:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_AUTHORIZATION_GATE_DRIFT")
    if any(
        gate.state != "NOT_GRANTED"
        or gate.decision_source != "EXTERNAL_HUMAN_ONLY"
        or gate.authorizer_reference is not None
        or gate.authorized_at is not None
        or gate.authorization_evidence_sha256 is not None
        or gate.may_publish
        or gate.may_deploy
        for gate in packet.authorization_gates
    ):
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_AUTHORIZATION_MUST_REMAIN_UNGRANTED")
    if packet.blockers != REQUIRED_BLOCKERS or packet.next_unit != NEXT_UNIT:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_CONTROL_DRIFT")
    if not packet.cp59_final_offline_acceptance_validated or not packet.operator_handoff_ready:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_HANDOFF_NOT_READY")
    if not packet.global_kill_switch_engaged:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_KILL_SWITCH_DRIFT")

    forbidden = (
        packet.live_evidence_captured,
        packet.secret_reference_resolved,
        packet.environment_read,
        packet.keychain_read,
        packet.oauth_attempted,
        packet.real_account_lookup_attempted,
        packet.account_connected,
        packet.network_attempted,
        packet.publish_attempted,
        packet.external_write_performed,
        packet.deploy_performed,
        packet.paid_service_used,
        packet.live_read_only_authorization_granted,
        packet.pilot_publish_authorization_granted,
        packet.self_authorization_performed,
    )
    if any(forbidden):
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_EXTERNAL_OR_AUTHORITY_FORBIDDEN")

    hashes = (
        packet.packet_hash,
        packet.cp59_acceptance_hash,
        packet.cp59_source_manifest_sha256,
        packet.policy_sha256,
        packet.runtime_policy_sha256,
        packet.module_registry_sha256,
    )
    if any(not HEX64.fullmatch(value) for value in hashes):
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_HASH_FORMAT")

    body = packet.to_dict()
    body.pop("packet_id")
    body.pop("packet_hash")
    if _hash(body) != packet.packet_hash:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_HASH_MISMATCH")
    if packet.packet_id != "oph_" + packet.packet_hash[:24]:
        raise OperatorPilotHandoffHold("HOLD_CP60_PACKET_ID_MISMATCH")


def render_operator_pilot_handoff_json(packet: OperatorPilotHandoffPacket) -> str:
    validate_operator_pilot_handoff_packet(packet)
    return canonical_json(packet.to_dict())
