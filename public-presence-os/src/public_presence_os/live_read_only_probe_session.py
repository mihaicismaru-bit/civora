from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .authorization_receipt_validator import (
    AuthorizationReceiptValidatorContract,
    compile_authorization_receipt_validator,
    validate_authorization_receipt_validator_contract,
)
from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_SESSION_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-session-v1.0.0"
STATE = "PASS_CP63_SESSION_ENVELOPE_ZERO_WRITE_RECORDER_DRY_RUN_LOCAL_ONLY_LIVE_HOLD"
CHECKPOINT = "CP63"
PARENT_AUTHORIZATION_CHECKPOINT = "CP62"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP64_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT_GATE_AND_REPLAY_VALIDATOR_DRY_RUN"
SYNTHETIC_API_VERSION_LABEL = "SYNTHETIC_META_API_VERSION_NOT_FOR_NETWORK"
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
    "HOLD_CP63_SESSION_DRY_RUN_ONLY",
)


class LiveReadOnlyProbeSessionError(ValueError):
    pass


class LiveReadOnlyProbeSessionHold(LiveReadOnlyProbeSessionError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProbeStep:
    sequence: int
    platform: str
    probe_class: str
    method: str
    endpoint_label: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProbeSessionEnvelope:
    envelope_id: str
    envelope_hash: str
    model_version: str
    checkpoint: str
    parent_authorization_checkpoint: str
    parent_control_checkpoint: str
    cp62_contract_id: str
    cp62_contract_hash: str
    cp62_immutable_receipt_id: str
    cp62_immutable_receipt_hash: str
    cp62_dry_run_id: str
    cp62_dry_run_hash: str
    session_id: str
    active_platforms: tuple[str, ...]
    allowed_methods: tuple[str, ...]
    evidence_codes: tuple[str, ...]
    api_version_label: str
    steps: tuple[ProbeStep, ...]
    synthetic_only: bool = True
    offline_dry_run_only: bool = True
    global_kill_switch_engaged: bool = True
    authority_activated: bool = False
    control_plane_promoted: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
    oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    network_attempted: bool = False
    live_probe_attempted: bool = False
    publish_attempted: bool = False
    external_write_performed: bool = False
    deploy_performed: bool = False
    paid_service_used: bool = False
    state: str = "SYNTHETIC_SESSION_ENVELOPE_ONLY_NO_LIVE_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["allowed_methods"] = list(self.allowed_methods)
        data["evidence_codes"] = list(self.evidence_codes)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data


@dataclass(frozen=True)
class ZeroWriteEvent:
    sequence: int
    platform: str
    probe_class: str
    method: str
    request_fingerprint_sha256: str
    response_fingerprint_sha256: str
    write_count_before: int = 0
    write_count_after: int = 0
    mutating_method_observed: bool = False
    network_attempted: bool = False
    external_write_performed: bool = False
    raw_secret_present: bool = False
    state: str = "SYNTHETIC_ZERO_WRITE_RECORDED"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ZeroWriteRecorderReceipt:
    recorder_id: str
    recorder_hash: str
    model_version: str
    checkpoint: str
    session_envelope_id: str
    session_envelope_hash: str
    events: tuple[ZeroWriteEvent, ...]
    total_events: int
    write_attempt_count: int = 0
    mutating_method_count: int = 0
    network_attempt_count: int = 0
    secret_material_count: int = 0
    external_write_count: int = 0
    zero_write_proof: bool = True
    synthetic_only: bool = True
    immutable: bool = True
    state: str = "PASS_SYNTHETIC_ZERO_WRITE_PROOF_NO_NETWORK"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["events"] = [event.to_dict() for event in self.events]
        return data


@dataclass(frozen=True)
class LiveReadOnlyProbeSessionContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_authorization_checkpoint: str
    parent_control_checkpoint: str
    cp62_contract_id: str
    cp62_contract_hash: str
    cp62_immutable_receipt_id: str
    cp62_immutable_receipt_hash: str
    session_envelope_id: str
    session_envelope_hash: str
    zero_write_recorder_id: str
    zero_write_recorder_hash: str
    policy_sha256: str
    cp62_policy_sha256: str
    cp56_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    session_envelope_validated: bool = True
    zero_write_recorder_validated: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_ingested: bool = False
    live_evidence_captured: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
    oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    network_attempted: bool = False
    live_probe_attempted: bool = False
    publish_attempted: bool = False
    external_write_performed: bool = False
    control_plane_promoted: bool = False
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


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_LIVE_READ_ONLY_PROBE_SESSION_POLICY_V1":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M32_LIVE_READ_ONLY_PROBE_SESSION":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_POLICY_IDENTITY")
    if policy.get("parent_authorization_checkpoint") != PARENT_AUTHORIZATION_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_PARENT_AUTHORIZATION_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_BLOCKER_SET_DRIFT")
    if policy.get("rollback_target") != PARENT_AUTHORIZATION_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ROLLBACK_TARGET_DRIFT")
    if policy.get("next_after_cp63") != NEXT_UNIT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_NEXT_UNIT_DRIFT")

    envelope = policy.get("session_envelope", {})
    required_envelope_true = (
        "offline_dry_run_only",
        "synthetic_fixture_required",
        "exact_cp62_contract_binding_required",
        "exact_cp62_immutable_receipt_binding_required",
        "exact_cp62_dry_run_binding_required",
        "exact_cp56_probe_class_binding_required",
        "exact_cp56_evidence_code_binding_required",
        "synthetic_endpoint_labels_only",
        "real_url_forbidden",
        "api_version_is_synthetic_label_only",
        "global_kill_switch_must_remain_engaged",
        "authority_activation_forbidden",
        "control_promotion_forbidden",
        "secret_resolution_forbidden",
        "environment_read_forbidden",
        "keychain_read_forbidden",
        "oauth_forbidden",
        "real_account_lookup_forbidden",
        "account_connection_forbidden",
        "network_forbidden",
        "live_probe_execution_forbidden",
        "publish_execution_forbidden",
        "external_write_forbidden",
        "deploy_forbidden",
        "paid_service_forbidden",
    )
    if any(envelope.get(key) is not True for key in required_envelope_true):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_GUARD_MISSING")
    if tuple(envelope.get("method_allowlist", ())) != ALLOWED_METHODS:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_METHOD_ALLOWLIST_DRIFT")
    if tuple(envelope.get("mutating_methods_forbidden", ())) != MUTATING_METHODS:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_MUTATING_METHOD_SET_DRIFT")

    recorder = policy.get("zero_write_recorder", {})
    required_recorder_true = (
        "enabled",
        "local_only",
        "synthetic_events_only",
        "append_order_is_deterministic",
        "request_payload_persistence_forbidden",
        "response_payload_persistence_forbidden",
        "request_fingerprint_sha256_only",
        "response_fingerprint_sha256_only",
        "raw_secret_or_token_persistence_forbidden",
        "zero_write_proof_must_be_true",
    )
    if any(recorder.get(key) is not True for key in required_recorder_true):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_GUARD_MISSING")
    for key in (
        "write_attempt_count_must_equal",
        "mutating_method_count_must_equal",
        "network_attempt_count_must_equal",
        "secret_material_count_must_equal",
        "external_write_count_must_equal",
    ):
        if recorder.get(key) != 0:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ZERO_WRITE_COUNTER_POLICY_DRIFT")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RUNTIME_ACTIVE_PLATFORM_DRIFT")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTROL_PROMOTION_MUST_REMAIN_HOLD")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M31_AUTHORIZATION_RECEIPT_VALIDATOR") != "CP62_AUTHORIZATION_RECEIPT_VALIDATOR_DRY_RUN_LOCAL_ONLY_CONTROL_PROMOTION_HOLD":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP62_MODULE_STATE_DRIFT")
    if states.get("M32_LIVE_READ_ONLY_PROBE_SESSION") != "CP63_SESSION_ENVELOPE_ZERO_WRITE_RECORDER_DRY_RUN_LOCAL_ONLY_LIVE_HOLD":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_MODULE_STATE_DRIFT")


def _validate_cp56_source(cp56_policy: dict) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if cp56_policy.get("schema_version") != "PPOS_META_LIVE_READ_ONLY_PROBE_POLICY_V1" or cp56_policy.get("checkpoint") != "CP56":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP56_SOURCE_IDENTITY_DRIFT")
    if tuple(cp56_policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP56_PLATFORM_DRIFT")
    contract = cp56_policy.get("contract", {})
    if tuple(contract.get("method_allowlist", ())) != ALLOWED_METHODS:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP56_METHOD_DRIFT")
    if tuple(contract.get("mutating_methods_forbidden", ())) != MUTATING_METHODS:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP56_MUTATING_METHOD_DRIFT")
    probe_classes = cp56_policy.get("platform_probe_classes", {})
    ordered = []
    for platform in EXPECTED_ACTIVE:
        classes = tuple(probe_classes.get(platform, ()))
        if not classes or any(not isinstance(item, str) or not item for item in classes):
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP56_PROBE_CLASS_DRIFT")
        ordered.append((platform, classes))
    evidence_codes = tuple(cp56_policy.get("required_evidence_codes", ()))
    if not evidence_codes or "ZERO_WRITE_CONFIRMATION" not in evidence_codes:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP56_EVIDENCE_CODE_DRIFT")
    return tuple(ordered)


def _expected_steps(cp56_policy: dict) -> tuple[ProbeStep, ...]:
    ordered = _validate_cp56_source(cp56_policy)
    steps: list[ProbeStep] = []
    sequence = 1
    for platform, classes in ordered:
        for probe_class in classes:
            steps.append(
                ProbeStep(
                    sequence=sequence,
                    platform=platform,
                    probe_class=probe_class,
                    method="GET",
                    endpoint_label=f"SYNTHETIC_ENDPOINT::{platform}::{probe_class}",
                )
            )
            sequence += 1
    return tuple(steps)


def compile_probe_session_envelope(
    cp62: AuthorizationReceiptValidatorContract,
    cp56_policy: dict,
) -> ProbeSessionEnvelope:
    validate_authorization_receipt_validator_contract(cp62)
    steps = _expected_steps(cp56_policy)
    evidence_codes = tuple(cp56_policy["required_evidence_codes"])
    session_seed = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "cp62_contract_id": cp62.contract_id,
        "cp62_contract_hash": cp62.contract_hash,
        "cp62_immutable_receipt_id": cp62.immutable_receipt_id,
        "cp62_immutable_receipt_hash": cp62.immutable_receipt_hash,
        "cp62_dry_run_id": cp62.dry_run_id,
        "cp62_dry_run_hash": cp62.dry_run_hash,
        "steps": [step.to_dict() for step in steps],
        "evidence_codes": list(evidence_codes),
    }
    session_id = f"cp63_session_{_hash(session_seed)[:24]}"
    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_authorization_checkpoint": PARENT_AUTHORIZATION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp62_contract_id": cp62.contract_id,
        "cp62_contract_hash": cp62.contract_hash,
        "cp62_immutable_receipt_id": cp62.immutable_receipt_id,
        "cp62_immutable_receipt_hash": cp62.immutable_receipt_hash,
        "cp62_dry_run_id": cp62.dry_run_id,
        "cp62_dry_run_hash": cp62.dry_run_hash,
        "session_id": session_id,
        "active_platforms": list(EXPECTED_ACTIVE),
        "allowed_methods": list(ALLOWED_METHODS),
        "evidence_codes": list(evidence_codes),
        "api_version_label": SYNTHETIC_API_VERSION_LABEL,
        "steps": [step.to_dict() for step in steps],
        "synthetic_only": True,
        "offline_dry_run_only": True,
        "global_kill_switch_engaged": True,
        "authority_activated": False,
        "control_plane_promoted": False,
        "secret_reference_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "oauth_attempted": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "network_attempted": False,
        "live_probe_attempted": False,
        "publish_attempted": False,
        "external_write_performed": False,
        "deploy_performed": False,
        "paid_service_used": False,
        "state": "SYNTHETIC_SESSION_ENVELOPE_ONLY_NO_LIVE_AUTHORITY",
    }
    envelope_hash = _hash(body)
    payload = dict(body)
    payload["active_platforms"] = tuple(payload["active_platforms"])
    payload["allowed_methods"] = tuple(payload["allowed_methods"])
    payload["evidence_codes"] = tuple(payload["evidence_codes"])
    payload["steps"] = steps
    envelope = ProbeSessionEnvelope(
        envelope_id=f"cp63_envelope_{envelope_hash[:24]}",
        envelope_hash=envelope_hash,
        **payload,
    )
    validate_probe_session_envelope(cp62, cp56_policy, envelope)
    return envelope


def validate_probe_session_envelope(
    cp62: AuthorizationReceiptValidatorContract,
    cp56_policy: dict,
    envelope: ProbeSessionEnvelope,
) -> None:
    validate_authorization_receipt_validator_contract(cp62)
    expected_steps = _expected_steps(cp56_policy)
    if envelope.model_version != MODEL_VERSION or envelope.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_VERSION_DRIFT")
    if envelope.parent_authorization_checkpoint != PARENT_AUTHORIZATION_CHECKPOINT or envelope.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_PARENT_DRIFT")
    if (envelope.cp62_contract_id, envelope.cp62_contract_hash) != (cp62.contract_id, cp62.contract_hash):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP62_CONTRACT_BINDING_MISMATCH")
    if (envelope.cp62_immutable_receipt_id, envelope.cp62_immutable_receipt_hash) != (cp62.immutable_receipt_id, cp62.immutable_receipt_hash):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP62_RECEIPT_BINDING_MISMATCH")
    if (envelope.cp62_dry_run_id, envelope.cp62_dry_run_hash) != (cp62.dry_run_id, cp62.dry_run_hash):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP62_DRY_RUN_BINDING_MISMATCH")
    if envelope.active_platforms != EXPECTED_ACTIVE or envelope.allowed_methods != ALLOWED_METHODS:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_PLATFORM_OR_METHOD_DRIFT")
    if envelope.evidence_codes != tuple(cp56_policy.get("required_evidence_codes", ())):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_EVIDENCE_CODE_DRIFT")
    if envelope.api_version_label != SYNTHETIC_API_VERSION_LABEL:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_API_VERSION_LABEL_DRIFT")
    if envelope.steps != expected_steps:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_PROBE_STEP_DRIFT")
    for step in envelope.steps:
        if step.method not in ALLOWED_METHODS or step.method in MUTATING_METHODS:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_MUTATING_METHOD_DETECTED")
        if not step.endpoint_label.startswith("SYNTHETIC_ENDPOINT::") or "://" in step.endpoint_label:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_REAL_OR_UNSAFE_ENDPOINT_DETECTED")
    if not envelope.synthetic_only or not envelope.offline_dry_run_only or not envelope.global_kill_switch_engaged:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_SAFETY_GUARD_INVALID")
    forbidden_true = (
        envelope.authority_activated,
        envelope.control_plane_promoted,
        envelope.secret_reference_resolved,
        envelope.environment_read,
        envelope.keychain_read,
        envelope.oauth_attempted,
        envelope.real_account_lookup_attempted,
        envelope.account_connected,
        envelope.network_attempted,
        envelope.live_probe_attempted,
        envelope.publish_attempted,
        envelope.external_write_performed,
        envelope.deploy_performed,
        envelope.paid_service_used,
    )
    if any(forbidden_true):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_SIDE_EFFECT_DETECTED")
    body = _payload_without_identity(envelope.to_dict(), "envelope_id", "envelope_hash")
    expected_hash = _hash(body)
    if envelope.envelope_hash != expected_hash or envelope.envelope_id != f"cp63_envelope_{expected_hash[:24]}":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ENVELOPE_HASH_BINDING_INVALID")


def _event_for_step(envelope: ProbeSessionEnvelope, step: ProbeStep) -> ZeroWriteEvent:
    request_meta = {
        "session_id": envelope.session_id,
        "sequence": step.sequence,
        "platform": step.platform,
        "probe_class": step.probe_class,
        "method": step.method,
        "endpoint_label": step.endpoint_label,
        "api_version_label": envelope.api_version_label,
    }
    request_fingerprint = _hash(request_meta)
    response_meta = {
        "request_fingerprint_sha256": request_fingerprint,
        "synthetic_result": "READ_ONLY_OK_NO_NETWORK",
        "evidence_codes": list(envelope.evidence_codes),
        "write_count": 0,
    }
    return ZeroWriteEvent(
        sequence=step.sequence,
        platform=step.platform,
        probe_class=step.probe_class,
        method=step.method,
        request_fingerprint_sha256=request_fingerprint,
        response_fingerprint_sha256=_hash(response_meta),
    )


def record_zero_write_dry_run(envelope: ProbeSessionEnvelope) -> ZeroWriteRecorderReceipt:
    events = tuple(_event_for_step(envelope, step) for step in envelope.steps)
    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "events": [event.to_dict() for event in events],
        "total_events": len(events),
        "write_attempt_count": 0,
        "mutating_method_count": 0,
        "network_attempt_count": 0,
        "secret_material_count": 0,
        "external_write_count": 0,
        "zero_write_proof": True,
        "synthetic_only": True,
        "immutable": True,
        "state": "PASS_SYNTHETIC_ZERO_WRITE_PROOF_NO_NETWORK",
    }
    recorder_hash = _hash(body)
    payload = dict(body)
    payload["events"] = events
    receipt = ZeroWriteRecorderReceipt(
        recorder_id=f"cp63_recorder_{recorder_hash[:24]}",
        recorder_hash=recorder_hash,
        **payload,
    )
    validate_zero_write_recorder(envelope, receipt)
    return receipt


def validate_zero_write_recorder(
    envelope: ProbeSessionEnvelope,
    receipt: ZeroWriteRecorderReceipt,
) -> None:
    if receipt.model_version != MODEL_VERSION or receipt.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_VERSION_DRIFT")
    if (receipt.session_envelope_id, receipt.session_envelope_hash) != (envelope.envelope_id, envelope.envelope_hash):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_ENVELOPE_BINDING_MISMATCH")
    if receipt.total_events != len(envelope.steps) or len(receipt.events) != len(envelope.steps):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_EVENT_COUNT_DRIFT")
    if not receipt.zero_write_proof or not receipt.synthetic_only or not receipt.immutable:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ZERO_WRITE_PROOF_INVALID")
    if any(
        count != 0
        for count in (
            receipt.write_attempt_count,
            receipt.mutating_method_count,
            receipt.network_attempt_count,
            receipt.secret_material_count,
            receipt.external_write_count,
        )
    ):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_ZERO_WRITE_COUNTER_NONZERO")
    for step, event in zip(envelope.steps, receipt.events):
        expected = _event_for_step(envelope, step)
        if event != expected:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_EVENT_BINDING_MISMATCH")
        if event.method != "GET" or event.mutating_method_observed:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_MUTATING_METHOD_DETECTED")
        if event.write_count_before != 0 or event.write_count_after != 0:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_WRITE_COUNT_NONZERO")
        if event.network_attempted or event.external_write_performed or event.raw_secret_present:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_SIDE_EFFECT_OR_SECRET_DETECTED")
        if len(event.request_fingerprint_sha256) != 64 or len(event.response_fingerprint_sha256) != 64:
            raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_FINGERPRINT_INVALID")
    body = _payload_without_identity(receipt.to_dict(), "recorder_id", "recorder_hash")
    expected_hash = _hash(body)
    if receipt.recorder_hash != expected_hash or receipt.recorder_id != f"cp63_recorder_{expected_hash[:24]}":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_RECORDER_HASH_BINDING_INVALID")


def compile_live_read_only_probe_session(
    root: Path,
    policy: dict,
) -> LiveReadOnlyProbeSessionContract:
    root = root.resolve()
    _validate_policy(policy)
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp62_policy = load_json(root / "config" / "authorization_receipt_validator_policy.json")
    cp62 = compile_authorization_receipt_validator(root, cp62_policy)
    validate_authorization_receipt_validator_contract(cp62)
    if cp62.checkpoint != PARENT_AUTHORIZATION_CHECKPOINT or cp62.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CP62_PARENT_BINDING_DRIFT")

    cp56_policy = load_json(root / "config" / "meta_live_read_only_probe_policy.json")
    _validate_cp56_source(cp56_policy)
    envelope = compile_probe_session_envelope(cp62, cp56_policy)
    recorder = record_zero_write_dry_run(envelope)

    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_authorization_checkpoint": PARENT_AUTHORIZATION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp62_contract_id": cp62.contract_id,
        "cp62_contract_hash": cp62.contract_hash,
        "cp62_immutable_receipt_id": cp62.immutable_receipt_id,
        "cp62_immutable_receipt_hash": cp62.immutable_receipt_hash,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "zero_write_recorder_id": recorder.recorder_id,
        "zero_write_recorder_hash": recorder.recorder_hash,
        "policy_sha256": _hash(policy),
        "cp62_policy_sha256": _hash(cp62_policy),
        "cp56_policy_sha256": _hash(cp56_policy),
        "runtime_policy_sha256": _hash(runtime),
        "module_registry_sha256": _hash(registry),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "session_envelope_validated": True,
        "zero_write_recorder_validated": True,
        "global_kill_switch_engaged": True,
        "external_authorization_ingested": False,
        "live_evidence_captured": False,
        "secret_reference_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "oauth_attempted": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "network_attempted": False,
        "live_probe_attempted": False,
        "publish_attempted": False,
        "external_write_performed": False,
        "control_plane_promoted": False,
        "deploy_performed": False,
        "paid_service_used": False,
        "authority_activated": False,
        "state": STATE,
    }
    contract_hash = _hash(body)
    payload = dict(body)
    payload["active_platforms"] = tuple(payload["active_platforms"])
    payload["blockers"] = tuple(payload["blockers"])
    contract = LiveReadOnlyProbeSessionContract(
        contract_id=f"cp63_contract_{contract_hash[:24]}",
        contract_hash=contract_hash,
        **payload,
    )
    validate_live_read_only_probe_session_contract(contract)
    return contract


def validate_live_read_only_probe_session_contract(
    contract: LiveReadOnlyProbeSessionContract,
) -> None:
    if contract.model_version != MODEL_VERSION or contract.engine_version != ENGINE_VERSION:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_VERSION_DRIFT")
    if contract.checkpoint != CHECKPOINT or contract.parent_authorization_checkpoint != PARENT_AUTHORIZATION_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_CHECKPOINT_DRIFT")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_CONTROL_BINDING_DRIFT")
    if contract.active_platforms != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_PLATFORM_DRIFT")
    if contract.blockers != REQUIRED_BLOCKERS or contract.next_unit != NEXT_UNIT:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_GATING_DRIFT")
    if not contract.session_envelope_validated or not contract.zero_write_recorder_validated or not contract.global_kill_switch_engaged:
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_REQUIRED_PROOF_MISSING")
    forbidden_true = (
        contract.external_authorization_ingested,
        contract.live_evidence_captured,
        contract.secret_reference_resolved,
        contract.environment_read,
        contract.keychain_read,
        contract.oauth_attempted,
        contract.real_account_lookup_attempted,
        contract.account_connected,
        contract.network_attempted,
        contract.live_probe_attempted,
        contract.publish_attempted,
        contract.external_write_performed,
        contract.control_plane_promoted,
        contract.deploy_performed,
        contract.paid_service_used,
        contract.authority_activated,
    )
    if any(forbidden_true):
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_SIDE_EFFECT_DETECTED")
    body = _payload_without_identity(contract.to_dict(), "contract_id", "contract_hash")
    expected_hash = _hash(body)
    if contract.contract_hash != expected_hash or contract.contract_id != f"cp63_contract_{expected_hash[:24]}":
        raise LiveReadOnlyProbeSessionHold("HOLD_CP63_CONTRACT_HASH_BINDING_INVALID")
