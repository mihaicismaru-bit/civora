from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_evidence_import import (
    CHECKPOINT as CP64_CHECKPOINT,
    STATE as CP64_STATE,
    LiveReadOnlyProbeEvidenceImportContract,
    compile_live_read_only_probe_evidence_import,
    validate_live_read_only_probe_evidence_import_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_EXECUTION_ADMISSION_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-execution-admission-v1.0.0"
STATE = "PASS_CP65_EXECUTION_ADMISSION_PREFLIGHT_PACKET_LOCAL_ONLY_AUTHORIZATION_REQUIRED_LIVE_HOLD"
CHECKPOINT = "CP65"
PARENT_EVIDENCE_IMPORT_CHECKPOINT = "CP64"
PARENT_CONTROL_CHECKPOINT = "CP58"
AUTHORIZATION_GATE = "LIVE_READ_ONLY_CONNECTION_PROBE"
NEXT_UNIT = "CP66_LIVE_READ_ONLY_PROBE_SINGLE_SESSION_EXECUTION_HARNESS_DRY_RUN"
ALLOWED_METHODS = ("GET",)
MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")

REQUIRED_BLOCKERS = (
    "HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED",
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
    "HOLD_CP65_EXTERNAL_HUMAN_AUTHORIZATION_REQUIRED",
    "HOLD_CP65_NETWORK_BOUNDARY_DISABLED",
)

SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization",
        "authorization_header",
        "password",
        "raw_token",
        "raw_secret",
        "bearer",
    }
)


class LiveReadOnlyProbeExecutionAdmissionError(ValueError):
    pass


class LiveReadOnlyProbeExecutionAdmissionHold(LiveReadOnlyProbeExecutionAdmissionError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OperatorPreflightPacket:
    packet_id: str
    packet_hash: str
    model_version: str
    checkpoint: str
    parent_control_checkpoint: str
    cp64_contract_id: str
    cp64_contract_hash: str
    cp64_state: str
    cp64_evidence_import_id: str
    cp64_evidence_import_hash: str
    cp64_replay_validation_id: str
    cp64_replay_validation_hash: str
    active_platforms: tuple[str, ...]
    authorization_gate: str
    method_allowlist: tuple[str, ...]
    mutating_methods_forbidden: tuple[str, ...]
    endpoint_mode: str
    authorization_requirement: str
    credential_mode: str
    evidence_mode: str
    network_mode: str
    operator_action_mode: str
    global_kill_switch_engaged: bool = True
    cp64_exact_binding_validated: bool = True
    get_only_validated: bool = True
    zero_write_required: bool = True
    redaction_required: bool = True
    immutable: bool = True
    external_human_authorization_required: bool = True
    external_authorization_present: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
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
    state: str = "PREFLIGHT_PACKET_READY_EXTERNAL_AUTHORIZATION_REQUIRED_NO_LIVE_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["method_allowlist"] = list(self.method_allowlist)
        data["mutating_methods_forbidden"] = list(self.mutating_methods_forbidden)
        return data


@dataclass(frozen=True)
class ExecutionAdmissionReceipt:
    admission_id: str
    admission_hash: str
    model_version: str
    checkpoint: str
    parent_control_checkpoint: str
    preflight_packet_id: str
    preflight_packet_hash: str
    cp64_contract_id: str
    cp64_contract_hash: str
    active_platforms: tuple[str, ...]
    authorization_gate: str
    method_allowlist: tuple[str, ...]
    blockers: tuple[str, ...]
    structural_readiness_validated: bool = True
    cp64_exact_binding_validated: bool = True
    preflight_packet_validated: bool = True
    get_only_validated: bool = True
    zero_write_validated: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_present: bool = False
    secret_reference_resolved: bool = False
    account_connected: bool = False
    network_allowed: bool = False
    live_probe_allowed: bool = False
    admission_granted: bool = False
    authority_activated: bool = False
    state: str = "HOLD_EXTERNAL_HUMAN_AUTHORIZATION_REQUIRED_NO_EXECUTION"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["method_allowlist"] = list(self.method_allowlist)
        data["blockers"] = list(self.blockers)
        return data


@dataclass(frozen=True)
class LiveReadOnlyProbeExecutionAdmissionContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_evidence_import_checkpoint: str
    parent_control_checkpoint: str
    cp64_contract_id: str
    cp64_contract_hash: str
    preflight_packet_id: str
    preflight_packet_hash: str
    admission_id: str
    admission_hash: str
    policy_sha256: str
    cp64_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    cp64_exact_binding_validated: bool = True
    operator_preflight_packet_validated: bool = True
    execution_admission_gate_validated: bool = True
    global_kill_switch_engaged: bool = True
    external_human_authorization_required: bool = True
    external_authorization_ingested: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
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
    state: str = STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["blockers"] = list(self.blockers)
        return data


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _payload_without_identity(value: dict, *identity_fields: str) -> dict:
    payload = dict(value)
    for field in identity_fields:
        payload.pop(field, None)
    return payload


def _is_hex64(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_no_sensitive_or_live_material(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS:
                raise LiveReadOnlyProbeExecutionAdmissionHold(
                    "HOLD_CP65_SENSITIVE_FIELD_NOT_ALLOWED_IN_PREFLIGHT"
                )
            _validate_no_sensitive_or_live_material(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_no_sensitive_or_live_material(child)
    elif isinstance(value, str):
        lowered = value.lower()
        if "bearer " in lowered or "authorization:" in lowered or "://" in value:
            raise LiveReadOnlyProbeExecutionAdmissionHold(
                "HOLD_CP65_RAW_CREDENTIAL_OR_URL_MATERIAL_NOT_ALLOWED"
            )


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_LIVE_READ_ONLY_PROBE_EXECUTION_ADMISSION_POLICY_V1":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M34_LIVE_READ_ONLY_PROBE_EXECUTION_ADMISSION":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_POLICY_IDENTITY")
    if policy.get("parent_evidence_import_checkpoint") != PARENT_EVIDENCE_IMPORT_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PARENT_EVIDENCE_IMPORT_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_BLOCKER_SET_DRIFT")
    if policy.get("rollback_target") != PARENT_EVIDENCE_IMPORT_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ROLLBACK_TARGET_DRIFT")
    if policy.get("next_after_cp65") != NEXT_UNIT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_NEXT_UNIT_DRIFT")

    gate = policy.get("admission_gate", {})
    required_true = (
        "offline_contract_only",
        "exact_cp64_contract_binding_required",
        "cp64_structural_readiness_required",
        "external_human_authorization_required",
        "authorization_must_not_be_inferred_from_offline_pass",
        "repo_validation_must_assume_authorization_absent",
        "global_kill_switch_must_remain_engaged",
        "get_only_required",
        "mutating_methods_fail_closed",
        "zero_write_required",
        "secret_resolution_forbidden",
        "environment_read_forbidden",
        "keychain_read_forbidden",
        "oauth_forbidden",
        "real_account_lookup_forbidden",
        "account_connection_forbidden",
        "network_forbidden_in_cp65",
        "live_probe_execution_forbidden_in_cp65",
        "publish_forbidden",
        "external_write_forbidden",
        "control_plane_promotion_forbidden",
        "deploy_forbidden",
        "paid_service_forbidden",
    )
    if any(gate.get(key) is not True for key in required_true):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_GUARD_MISSING")
    if gate.get("authorization_gate_must_equal") != AUTHORIZATION_GATE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_AUTHORIZATION_GATE_DRIFT")
    if gate.get("cp64_state_must_equal") != CP64_STATE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CP64_STATE_POLICY_DRIFT")
    if tuple(gate.get("method_allowlist", ())) != ALLOWED_METHODS:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_METHOD_ALLOWLIST_DRIFT")
    if tuple(gate.get("mutating_methods_forbidden", ())) != MUTATING_METHODS:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_MUTATING_METHOD_SET_DRIFT")

    packet = policy.get("operator_preflight_packet", {})
    packet_true = (
        "canonical_json_required",
        "sha256_packet_binding_required",
        "exact_cp64_evidence_import_binding_required",
        "exact_cp64_replay_binding_required",
        "active_lane_manifest_required",
        "method_manifest_required",
        "authorization_requirement_manifest_required",
        "credential_reference_only_manifest_required",
        "redacted_evidence_manifest_required",
        "network_disabled_manifest_required",
        "kill_switch_manifest_required",
        "operator_actions_external_only",
        "raw_credentials_forbidden",
        "raw_urls_forbidden",
        "extra_live_material_forbidden",
        "immutable_packet_required",
    )
    if any(packet.get(key) is not True for key in packet_true):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_PACKET_GUARD_MISSING")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_AUTHORITY_NOT_ZERO")

    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_RUNTIME_ACTIVE_PLATFORM_DRIFT")
    if runtime.get("network_enabled") is not False:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_RUNTIME_NETWORK_MUST_REMAIN_DISABLED")
    if runtime.get("account_connection_enabled") is not False:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_RUNTIME_ACCOUNT_CONNECTION_MUST_REMAIN_DISABLED")
    if runtime.get("publish_enabled") is not False:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_RUNTIME_PUBLISH_MUST_REMAIN_DISABLED")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTROL_PROMOTION_MUST_REMAIN_HOLD")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M33_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT") != (
        "CP64_EVIDENCE_IMPORT_GATE_REPLAY_VALIDATOR_DRY_RUN_LOCAL_ONLY_LIVE_HOLD"
    ):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CP64_MODULE_STATE_DRIFT")
    if states.get("M34_LIVE_READ_ONLY_PROBE_EXECUTION_ADMISSION") != (
        "CP65_EXECUTION_ADMISSION_PREFLIGHT_PACKET_LOCAL_ONLY_AUTHORIZATION_REQUIRED_LIVE_HOLD"
    ):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_MODULE_STATE_DRIFT")


def build_operator_preflight_packet(
    cp64: LiveReadOnlyProbeEvidenceImportContract,
) -> OperatorPreflightPacket:
    validate_live_read_only_probe_evidence_import_contract(cp64)
    if cp64.checkpoint != CP64_CHECKPOINT or cp64.state != CP64_STATE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CP64_CONTRACT_STATE_DRIFT")
    if cp64.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CP64_CONTROL_BINDING_DRIFT")
    if cp64.active_platforms != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CP64_ACTIVE_PLATFORM_DRIFT")
    if not cp64.global_kill_switch_engaged:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CP64_KILL_SWITCH_DRIFT")
    if cp64.authority_activated or cp64.network_attempted or cp64.live_probe_attempted:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CP64_UNEXPECTED_LIVE_SIDE_EFFECT")

    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp64_contract_id": cp64.contract_id,
        "cp64_contract_hash": cp64.contract_hash,
        "cp64_state": cp64.state,
        "cp64_evidence_import_id": cp64.evidence_import_id,
        "cp64_evidence_import_hash": cp64.evidence_import_hash,
        "cp64_replay_validation_id": cp64.replay_validation_id,
        "cp64_replay_validation_hash": cp64.replay_validation_hash,
        "active_platforms": list(EXPECTED_ACTIVE),
        "authorization_gate": AUTHORIZATION_GATE,
        "method_allowlist": list(ALLOWED_METHODS),
        "mutating_methods_forbidden": list(MUTATING_METHODS),
        "endpoint_mode": "SYNTHETIC_LABELS_ONLY_UNTIL_LATER_AUTHORIZED_EXECUTION_BOUNDARY",
        "authorization_requirement": "EXTERNAL_HUMAN_GRANT_REQUIRED_NOT_PRESENT_IN_CP65",
        "credential_mode": "REFERENCE_ONLY_NOT_RESOLVED_NO_VALUES",
        "evidence_mode": "REDACTED_HASH_BOUND_ONLY",
        "network_mode": "DISABLED_CP65",
        "operator_action_mode": "EXTERNAL_HUMAN_ONLY_NOT_EXECUTED",
        "global_kill_switch_engaged": True,
        "cp64_exact_binding_validated": True,
        "get_only_validated": True,
        "zero_write_required": True,
        "redaction_required": True,
        "immutable": True,
        "external_human_authorization_required": True,
        "external_authorization_present": False,
        "secret_reference_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "oauth_attempted": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "network_allowed": False,
        "network_attempted": False,
        "live_probe_allowed": False,
        "live_probe_attempted": False,
        "publish_allowed": False,
        "publish_attempted": False,
        "external_write_allowed": False,
        "external_write_performed": False,
        "control_plane_promoted": False,
        "deploy_allowed": False,
        "deploy_performed": False,
        "paid_service_used": False,
        "authority_activated": False,
        "state": "PREFLIGHT_PACKET_READY_EXTERNAL_AUTHORIZATION_REQUIRED_NO_LIVE_AUTHORITY",
    }
    _validate_no_sensitive_or_live_material(body)
    packet_hash = _hash(body)
    packet = OperatorPreflightPacket(
        packet_id=f"cp65_preflight_{packet_hash[:24]}",
        packet_hash=packet_hash,
        **{
            **body,
            "active_platforms": EXPECTED_ACTIVE,
            "method_allowlist": ALLOWED_METHODS,
            "mutating_methods_forbidden": MUTATING_METHODS,
        },
    )
    validate_operator_preflight_packet(packet, cp64)
    return packet


def validate_operator_preflight_packet(
    packet: OperatorPreflightPacket,
    cp64: LiveReadOnlyProbeEvidenceImportContract,
) -> None:
    validate_live_read_only_probe_evidence_import_contract(cp64)
    if packet.model_version != MODEL_VERSION or packet.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_VERSION_DRIFT")
    if packet.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_CONTROL_BINDING_DRIFT")
    if (packet.cp64_contract_id, packet.cp64_contract_hash) != (cp64.contract_id, cp64.contract_hash):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_CP64_BINDING_MISMATCH")
    if (packet.cp64_evidence_import_id, packet.cp64_evidence_import_hash) != (
        cp64.evidence_import_id,
        cp64.evidence_import_hash,
    ):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_IMPORT_BINDING_MISMATCH")
    if (packet.cp64_replay_validation_id, packet.cp64_replay_validation_hash) != (
        cp64.replay_validation_id,
        cp64.replay_validation_hash,
    ):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_REPLAY_BINDING_MISMATCH")
    if packet.cp64_state != CP64_STATE or packet.active_platforms != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_STATE_OR_PLATFORM_DRIFT")
    if packet.authorization_gate != AUTHORIZATION_GATE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_AUTHORIZATION_GATE_DRIFT")
    if packet.method_allowlist != ALLOWED_METHODS or packet.mutating_methods_forbidden != MUTATING_METHODS:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_METHOD_DRIFT")
    if packet.endpoint_mode != "SYNTHETIC_LABELS_ONLY_UNTIL_LATER_AUTHORIZED_EXECUTION_BOUNDARY":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_ENDPOINT_MODE_DRIFT")
    if packet.authorization_requirement != "EXTERNAL_HUMAN_GRANT_REQUIRED_NOT_PRESENT_IN_CP65":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_AUTHORIZATION_REQUIREMENT_DRIFT")
    if packet.credential_mode != "REFERENCE_ONLY_NOT_RESOLVED_NO_VALUES":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_CREDENTIAL_MODE_DRIFT")
    if packet.evidence_mode != "REDACTED_HASH_BOUND_ONLY" or packet.network_mode != "DISABLED_CP65":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_EVIDENCE_OR_NETWORK_MODE_DRIFT")
    if packet.operator_action_mode != "EXTERNAL_HUMAN_ONLY_NOT_EXECUTED":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_OPERATOR_MODE_DRIFT")

    required_true = (
        packet.global_kill_switch_engaged,
        packet.cp64_exact_binding_validated,
        packet.get_only_validated,
        packet.zero_write_required,
        packet.redaction_required,
        packet.immutable,
        packet.external_human_authorization_required,
    )
    if not all(required_true):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_REQUIRED_PROOF_MISSING")

    forbidden_true = (
        packet.external_authorization_present,
        packet.secret_reference_resolved,
        packet.environment_read,
        packet.keychain_read,
        packet.oauth_attempted,
        packet.real_account_lookup_attempted,
        packet.account_connected,
        packet.network_allowed,
        packet.network_attempted,
        packet.live_probe_allowed,
        packet.live_probe_attempted,
        packet.publish_allowed,
        packet.publish_attempted,
        packet.external_write_allowed,
        packet.external_write_performed,
        packet.control_plane_promoted,
        packet.deploy_allowed,
        packet.deploy_performed,
        packet.paid_service_used,
        packet.authority_activated,
    )
    if any(forbidden_true):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_LIVE_OR_AUTHORITY_STATE_DETECTED")

    _validate_no_sensitive_or_live_material(
        _payload_without_identity(packet.to_dict(), "packet_id", "packet_hash")
    )
    body = _payload_without_identity(packet.to_dict(), "packet_id", "packet_hash")
    expected_hash = _hash(body)
    if packet.packet_hash != expected_hash or packet.packet_id != f"cp65_preflight_{expected_hash[:24]}":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_HASH_BINDING_INVALID")
    for digest in (
        packet.cp64_contract_hash,
        packet.cp64_evidence_import_hash,
        packet.cp64_replay_validation_hash,
        packet.packet_hash,
    ):
        if not _is_hex64(digest):
            raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_PREFLIGHT_DIGEST_INVALID")


def evaluate_execution_admission(
    packet: OperatorPreflightPacket,
    cp64: LiveReadOnlyProbeEvidenceImportContract,
) -> ExecutionAdmissionReceipt:
    validate_operator_preflight_packet(packet, cp64)

    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "preflight_packet_id": packet.packet_id,
        "preflight_packet_hash": packet.packet_hash,
        "cp64_contract_id": cp64.contract_id,
        "cp64_contract_hash": cp64.contract_hash,
        "active_platforms": list(EXPECTED_ACTIVE),
        "authorization_gate": AUTHORIZATION_GATE,
        "method_allowlist": list(ALLOWED_METHODS),
        "blockers": list(REQUIRED_BLOCKERS),
        "structural_readiness_validated": True,
        "cp64_exact_binding_validated": True,
        "preflight_packet_validated": True,
        "get_only_validated": True,
        "zero_write_validated": True,
        "global_kill_switch_engaged": True,
        "external_authorization_present": False,
        "secret_reference_resolved": False,
        "account_connected": False,
        "network_allowed": False,
        "live_probe_allowed": False,
        "admission_granted": False,
        "authority_activated": False,
        "state": "HOLD_EXTERNAL_HUMAN_AUTHORIZATION_REQUIRED_NO_EXECUTION",
    }
    admission_hash = _hash(body)
    receipt = ExecutionAdmissionReceipt(
        admission_id=f"cp65_admission_{admission_hash[:24]}",
        admission_hash=admission_hash,
        **{
            **body,
            "active_platforms": EXPECTED_ACTIVE,
            "method_allowlist": ALLOWED_METHODS,
            "blockers": REQUIRED_BLOCKERS,
        },
    )
    validate_execution_admission_receipt(receipt, packet, cp64)
    return receipt


def validate_execution_admission_receipt(
    receipt: ExecutionAdmissionReceipt,
    packet: OperatorPreflightPacket,
    cp64: LiveReadOnlyProbeEvidenceImportContract,
) -> None:
    validate_operator_preflight_packet(packet, cp64)
    if receipt.model_version != MODEL_VERSION or receipt.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_RECEIPT_VERSION_DRIFT")
    if receipt.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_RECEIPT_CONTROL_DRIFT")
    if (receipt.preflight_packet_id, receipt.preflight_packet_hash) != (packet.packet_id, packet.packet_hash):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_PREFLIGHT_BINDING_MISMATCH")
    if (receipt.cp64_contract_id, receipt.cp64_contract_hash) != (cp64.contract_id, cp64.contract_hash):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_CP64_BINDING_MISMATCH")
    if receipt.active_platforms != EXPECTED_ACTIVE or receipt.method_allowlist != ALLOWED_METHODS:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_PLATFORM_OR_METHOD_DRIFT")
    if receipt.authorization_gate != AUTHORIZATION_GATE or receipt.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_GATING_DRIFT")

    required_true = (
        receipt.structural_readiness_validated,
        receipt.cp64_exact_binding_validated,
        receipt.preflight_packet_validated,
        receipt.get_only_validated,
        receipt.zero_write_validated,
        receipt.global_kill_switch_engaged,
    )
    if not all(required_true):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_REQUIRED_PROOF_MISSING")
    if any(
        (
            receipt.external_authorization_present,
            receipt.secret_reference_resolved,
            receipt.account_connected,
            receipt.network_allowed,
            receipt.live_probe_allowed,
            receipt.admission_granted,
            receipt.authority_activated,
        )
    ):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_MUST_REMAIN_HOLD")
    if receipt.state != "HOLD_EXTERNAL_HUMAN_AUTHORIZATION_REQUIRED_NO_EXECUTION":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_STATE_DRIFT")

    body = _payload_without_identity(receipt.to_dict(), "admission_id", "admission_hash")
    expected_hash = _hash(body)
    if receipt.admission_hash != expected_hash or receipt.admission_id != f"cp65_admission_{expected_hash[:24]}":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_ADMISSION_HASH_BINDING_INVALID")


def compile_live_read_only_probe_execution_admission(
    root: Path,
    policy: dict,
) -> LiveReadOnlyProbeExecutionAdmissionContract:
    root = root.resolve()
    _validate_policy(policy)

    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp64_policy = load_json(root / "config" / "live_read_only_probe_evidence_import_policy.json")
    cp64 = compile_live_read_only_probe_evidence_import(root, cp64_policy)
    validate_live_read_only_probe_evidence_import_contract(cp64)

    packet = build_operator_preflight_packet(cp64)
    admission = evaluate_execution_admission(packet, cp64)

    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_evidence_import_checkpoint": PARENT_EVIDENCE_IMPORT_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp64_contract_id": cp64.contract_id,
        "cp64_contract_hash": cp64.contract_hash,
        "preflight_packet_id": packet.packet_id,
        "preflight_packet_hash": packet.packet_hash,
        "admission_id": admission.admission_id,
        "admission_hash": admission.admission_hash,
        "policy_sha256": _hash(policy),
        "cp64_policy_sha256": _hash(cp64_policy),
        "runtime_policy_sha256": _hash(runtime),
        "module_registry_sha256": _hash(registry),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "cp64_exact_binding_validated": True,
        "operator_preflight_packet_validated": True,
        "execution_admission_gate_validated": True,
        "global_kill_switch_engaged": True,
        "external_human_authorization_required": True,
        "external_authorization_ingested": False,
        "secret_reference_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "oauth_attempted": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "network_allowed": False,
        "network_attempted": False,
        "live_probe_allowed": False,
        "live_probe_attempted": False,
        "publish_allowed": False,
        "publish_attempted": False,
        "external_write_allowed": False,
        "external_write_performed": False,
        "control_plane_promoted": False,
        "deploy_allowed": False,
        "deploy_performed": False,
        "paid_service_used": False,
        "authority_activated": False,
        "state": STATE,
    }
    contract_hash = _hash(body)
    contract = LiveReadOnlyProbeExecutionAdmissionContract(
        contract_id=f"cp65_contract_{contract_hash[:24]}",
        contract_hash=contract_hash,
        **{
            **body,
            "active_platforms": EXPECTED_ACTIVE,
            "blockers": REQUIRED_BLOCKERS,
        },
    )
    validate_live_read_only_probe_execution_admission_contract(contract)
    return contract


def validate_live_read_only_probe_execution_admission_contract(
    contract: LiveReadOnlyProbeExecutionAdmissionContract,
) -> None:
    if contract.model_version != MODEL_VERSION or contract.engine_version != ENGINE_VERSION:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_VERSION_DRIFT")
    if contract.checkpoint != CHECKPOINT or contract.parent_evidence_import_checkpoint != PARENT_EVIDENCE_IMPORT_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_CHECKPOINT_DRIFT")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_CONTROL_BINDING_DRIFT")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_GATING_DRIFT")
    if contract.next_unit != NEXT_UNIT or contract.state != STATE:
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_STATE_OR_NEXT_UNIT_DRIFT")

    required_true = (
        contract.cp64_exact_binding_validated,
        contract.operator_preflight_packet_validated,
        contract.execution_admission_gate_validated,
        contract.global_kill_switch_engaged,
        contract.external_human_authorization_required,
    )
    if not all(required_true):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_REQUIRED_PROOF_MISSING")
    forbidden_true = (
        contract.external_authorization_ingested,
        contract.secret_reference_resolved,
        contract.environment_read,
        contract.keychain_read,
        contract.oauth_attempted,
        contract.real_account_lookup_attempted,
        contract.account_connected,
        contract.network_allowed,
        contract.network_attempted,
        contract.live_probe_allowed,
        contract.live_probe_attempted,
        contract.publish_allowed,
        contract.publish_attempted,
        contract.external_write_allowed,
        contract.external_write_performed,
        contract.control_plane_promoted,
        contract.deploy_allowed,
        contract.deploy_performed,
        contract.paid_service_used,
        contract.authority_activated,
    )
    if any(forbidden_true):
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_LIVE_OR_AUTHORITY_STATE_DETECTED")

    for digest in (
        contract.cp64_contract_hash,
        contract.preflight_packet_hash,
        contract.admission_hash,
        contract.policy_sha256,
        contract.cp64_policy_sha256,
        contract.runtime_policy_sha256,
        contract.module_registry_sha256,
    ):
        if not _is_hex64(digest):
            raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_DIGEST_INVALID")

    body = _payload_without_identity(contract.to_dict(), "contract_id", "contract_hash")
    expected_hash = _hash(body)
    if contract.contract_hash != expected_hash or contract.contract_id != f"cp65_contract_{expected_hash[:24]}":
        raise LiveReadOnlyProbeExecutionAdmissionHold("HOLD_CP65_CONTRACT_HASH_BINDING_INVALID")
