from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re

from .control import EXPECTED_ACTIVE, canonical_json, validate_policy
from .meta_read_only_gate import (
    REQUIRED_FUTURE_EVIDENCE,
    MetaReadOnlyGateReceipt,
    validate_meta_read_only_gate_receipt,
)

PROBE_RUNBOOK_MODEL_VERSION = "PPOS_META_LIVE_READ_ONLY_PROBE_RUNBOOK_V1"
PROBE_RUNBOOK_ENGINE_VERSION = "ppos-meta-live-read-only-probe-runbook-v1.0.0"
PROBE_RUNBOOK_STATE = "PASS_LIVE_READ_ONLY_PROBE_RUNBOOK_CONTRACT_LOCAL_ONLY"
RUNBOOK_MODE = "CONTRACT_AND_EVIDENCE_SCHEMA_ONLY_NO_EXECUTION"
EVIDENCE_STATE = "NOT_CAPTURED"
CAPTURE_AUTHORITY = "FUTURE_OPERATOR_LIVE_READ_ONLY_PROBE"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

EVIDENCE_REPRESENTATIONS = (
    ("LIVE_TOKEN_DEBUG_REDACTED", "REDACTED_METADATA_SHA256"),
    ("LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED", "REDACTED_IDENTITY_SHA256"),
    ("LIVE_PERMISSION_SET_EXACT", "SORTED_STRING_SET"),
    ("LIVE_CAPABILITY_SET_EXACT", "SORTED_STRING_SET"),
    ("LIVE_EXPIRY_STATE", "ENUM_AND_OPTIONAL_UTC"),
    ("LIVE_READ_ONLY_RESPONSE_HASH", "SHA256_OF_REDACTED_RESPONSE"),
    ("OPERATOR_TIMESTAMP_UTC", "UTC_TIMESTAMP"),
    ("API_VERSION_PIN", "NON_SECRET_VERSION_STRING"),
    ("ZERO_WRITE_CONFIRMATION", "BOOLEAN_ATTESTATION_PLUS_LOCAL_AUDIT_SHA256"),
)

FORBIDDEN_PERSISTED_KEYS = (
    "access_token",
    "app_secret",
    "authorization",
    "client_secret",
    "code",
    "cookie",
    "refresh_token",
    "session",
    "set-cookie",
)

RUNBOOK_STEP_CODES = (
    "VALIDATE_CP55_GATE_EXACT_BINDING",
    "CONFIRM_RUNTIME_POLICY_AND_KILL_SWITCH",
    "SELECT_ONE_ACTIVE_LANE_ONLY",
    "PIN_API_VERSION_AT_FUTURE_OPERATOR_PROBE",
    "MATERIALIZE_MINIMAL_READ_ONLY_ENDPOINT_LATER",
    "RESOLVE_SECRET_REFERENCE_EPHEMERALLY_LATER",
    "EXECUTE_GET_ONLY_LATER",
    "REDACT_BEFORE_ANY_PERSISTENCE",
    "HASH_REDACTED_RESPONSE",
    "CAPTURE_REQUIRED_EVIDENCE_ATOMICALLY",
    "VERIFY_ZERO_WRITE_LOCAL_AUDIT",
    "INVALIDATE_ON_ANY_METHOD_WRITE_OR_BINDING_DRIFT",
)

RECOVERY_ABORT_CODES = (
    "ABORT_ON_MUTATING_METHOD",
    "ABORT_ON_UNEXPECTED_WRITE_EVIDENCE",
    "ABORT_ON_KILL_SWITCH_DRIFT",
    "ABORT_ON_API_VERSION_DRIFT",
    "ABORT_ON_PERMISSION_OR_CAPABILITY_DRIFT",
    "ABORT_ON_IDENTITY_MISMATCH",
    "ABORT_ON_REDACTION_FAILURE",
    "ABORT_ON_HASH_OR_LINEAGE_MISMATCH",
)


class MetaLiveReadOnlyProbeError(ValueError):
    pass


class MetaLiveReadOnlyProbeHold(MetaLiveReadOnlyProbeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EvidenceSlot:
    code: str
    representation: str
    state: str = EVIDENCE_STATE
    required: bool = True
    capture_authority: str = CAPTURE_AUTHORITY
    raw_value_persistence_allowed: bool = False
    immutable_once_captured: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RedactionContract:
    forbidden_persisted_keys: tuple[str, ...] = FORBIDDEN_PERSISTED_KEYS
    redact_before_hash: bool = True
    raw_response_persistence_allowed: bool = False
    raw_headers_persistence_allowed: bool = False
    raw_secret_persistence_allowed: bool = False
    raw_account_identifier_persistence_allowed: bool = False
    token_fragment_persistence_allowed: bool = False
    response_hash_required: bool = True

    def to_dict(self) -> dict:
        data = asdict(self)
        data["forbidden_persisted_keys"] = list(self.forbidden_persisted_keys)
        return data


@dataclass(frozen=True)
class RunbookStep:
    ordinal: int
    code: str
    phase: str = "FUTURE_OPERATOR_LIVE_READ_ONLY_PROBE"
    requires_operator: bool = True
    may_execute_in_cp56: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryContract:
    abort_codes: tuple[str, ...] = RECOVERY_ABORT_CODES
    rollback_target: str = "CP55"
    kill_switch_must_remain_engaged: bool = True
    evidence_invalidated_on_abort: bool = True
    secret_material_must_not_be_persisted: bool = True
    account_connection_must_not_be_retained: bool = True
    publish_remains_disabled: bool = True
    deploy_remains_disabled: bool = True

    def to_dict(self) -> dict:
        data = asdict(self)
        data["abort_codes"] = list(self.abort_codes)
        return data


@dataclass(frozen=True)
class MetaLiveReadOnlyProbeRunbookReceipt:
    runbook_id: str
    runbook_hash: str
    model_version: str
    engine_version: str
    gate_id: str
    gate_hash: str
    transport_twin_id: str
    transport_twin_hash: str
    platform: str
    mode: str
    runtime_policy_sha256: str
    evidence_slots: tuple[EvidenceSlot, ...]
    redaction: RedactionContract
    steps: tuple[RunbookStep, ...]
    recovery: RecoveryContract
    read_only_method_allowlist: tuple[str, ...] = ("GET",)
    mutating_methods_forbidden: tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE")
    runbook_mode: str = RUNBOOK_MODE
    endpoint_materialized: bool = False
    execution_authorized: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
    oauth_attempted: bool = False
    network_attempted: bool = False
    live_response_observed: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    publish_attempted: bool = False
    external_write_performed: bool = False
    deploy_performed: bool = False
    live_entitlement_verified: bool = False
    live_connection_verified: bool = False
    pilot_publish_ready: bool = False
    global_kill_switch_required: bool = True
    live_reverification_required: bool = True
    state: str = PROBE_RUNBOOK_STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence_slots"] = [item.to_dict() for item in self.evidence_slots]
        data["redaction"] = self.redaction.to_dict()
        data["steps"] = [item.to_dict() for item in self.steps]
        data["recovery"] = self.recovery.to_dict()
        data["read_only_method_allowlist"] = list(self.read_only_method_allowlist)
        data["mutating_methods_forbidden"] = list(self.mutating_methods_forbidden)
        return data


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_runtime_policy(runtime_policy: dict) -> None:
    result = validate_policy(runtime_policy)
    if not result.ok:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RUNTIME_POLICY_INVALID")
    if tuple(runtime_policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_ACTIVE_PLATFORM_DRIFT")
    if runtime_policy.get("global_kill_switch_engaged") is not True:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_KILL_SWITCH_NOT_ENGAGED")


def _make_evidence_slots() -> tuple[EvidenceSlot, ...]:
    if tuple(code for code, _ in EVIDENCE_REPRESENTATIONS) != REQUIRED_FUTURE_EVIDENCE:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_CP55_EVIDENCE_SCHEMA_DRIFT")
    return tuple(EvidenceSlot(code=code, representation=representation) for code, representation in EVIDENCE_REPRESENTATIONS)


def _make_steps() -> tuple[RunbookStep, ...]:
    return tuple(RunbookStep(ordinal=index + 1, code=code) for index, code in enumerate(RUNBOOK_STEP_CODES))


def compile_meta_live_read_only_probe_runbook(
    gate: MetaReadOnlyGateReceipt,
    runtime_policy: dict,
) -> MetaLiveReadOnlyProbeRunbookReceipt:
    validate_meta_read_only_gate_receipt(gate)
    _validate_runtime_policy(runtime_policy)
    if gate.platform not in EXPECTED_ACTIVE:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_PLATFORM_NOT_ACTIVE")
    if gate.read_only_method_allowlist != ("GET",):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_CP55_METHOD_DRIFT")
    if gate.kill_switch.engaged is not True or gate.kill_switch.unlock_path_materialized:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_CP55_KILL_SWITCH_DRIFT")
    if any(item.state != "NOT_CAPTURED" for item in gate.evidence_requirements):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_PRETENDED_LIVE_EVIDENCE")
    if any((gate.live_probe_authorized, gate.network_attempted, gate.account_connected, gate.live_connection_verified, gate.pilot_publish_ready)):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_CP55_EXTERNAL_AUTHORITY_FORBIDDEN")

    runtime_policy_sha256 = _hash(runtime_policy)
    if runtime_policy_sha256 != gate.runtime_policy_sha256:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RUNTIME_POLICY_BINDING_MISMATCH")

    evidence_slots = _make_evidence_slots()
    redaction = RedactionContract()
    steps = _make_steps()
    recovery = RecoveryContract()
    body = {
        "model_version": PROBE_RUNBOOK_MODEL_VERSION,
        "engine_version": PROBE_RUNBOOK_ENGINE_VERSION,
        "gate_id": gate.gate_id,
        "gate_hash": gate.gate_hash,
        "transport_twin_id": gate.transport_twin_id,
        "transport_twin_hash": gate.transport_twin_hash,
        "platform": gate.platform,
        "mode": gate.mode,
        "runtime_policy_sha256": runtime_policy_sha256,
        "evidence_slots": [item.to_dict() for item in evidence_slots],
        "redaction": redaction.to_dict(),
        "steps": [item.to_dict() for item in steps],
        "recovery": recovery.to_dict(),
        "read_only_method_allowlist": ["GET"],
        "mutating_methods_forbidden": ["POST", "PUT", "PATCH", "DELETE"],
        "runbook_mode": RUNBOOK_MODE,
        "endpoint_materialized": False,
        "execution_authorized": False,
        "secret_reference_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "oauth_attempted": False,
        "network_attempted": False,
        "live_response_observed": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "publish_attempted": False,
        "external_write_performed": False,
        "deploy_performed": False,
        "live_entitlement_verified": False,
        "live_connection_verified": False,
        "pilot_publish_ready": False,
        "global_kill_switch_required": True,
        "live_reverification_required": True,
        "state": PROBE_RUNBOOK_STATE,
    }
    runbook_hash = _hash(body)
    receipt = MetaLiveReadOnlyProbeRunbookReceipt(
        runbook_id="mlrp_" + runbook_hash[:24],
        runbook_hash=runbook_hash,
        model_version=PROBE_RUNBOOK_MODEL_VERSION,
        engine_version=PROBE_RUNBOOK_ENGINE_VERSION,
        gate_id=gate.gate_id,
        gate_hash=gate.gate_hash,
        transport_twin_id=gate.transport_twin_id,
        transport_twin_hash=gate.transport_twin_hash,
        platform=gate.platform,
        mode=gate.mode,
        runtime_policy_sha256=runtime_policy_sha256,
        evidence_slots=evidence_slots,
        redaction=redaction,
        steps=steps,
        recovery=recovery,
    )
    validate_meta_live_read_only_probe_runbook_receipt(receipt)
    return receipt


def validate_meta_live_read_only_probe_runbook_receipt(receipt: MetaLiveReadOnlyProbeRunbookReceipt) -> None:
    if not isinstance(receipt, MetaLiveReadOnlyProbeRunbookReceipt):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RECEIPT_TYPE")
    if receipt.model_version != PROBE_RUNBOOK_MODEL_VERSION or receipt.engine_version != PROBE_RUNBOOK_ENGINE_VERSION:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RECEIPT_VERSION")
    if receipt.platform not in EXPECTED_ACTIVE:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(receipt.gate_hash) or not HEX64.fullmatch(receipt.transport_twin_hash) or not HEX64.fullmatch(receipt.runtime_policy_sha256):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_BINDING_HASH_INVALID")
    if receipt.read_only_method_allowlist != ("GET",):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_METHOD_ALLOWLIST_DRIFT")
    if receipt.mutating_methods_forbidden != ("POST", "PUT", "PATCH", "DELETE"):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_MUTATING_METHOD_GUARD_DRIFT")
    if receipt.runbook_mode != RUNBOOK_MODE:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_MODE_DRIFT")

    expected_slots = _make_evidence_slots()
    if receipt.evidence_slots != expected_slots:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_EVIDENCE_SCHEMA_DRIFT")
    if any(item.state != EVIDENCE_STATE or item.raw_value_persistence_allowed for item in receipt.evidence_slots):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_PRETENDED_OR_RAW_EVIDENCE")
    if receipt.redaction != RedactionContract():
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_REDACTION_CONTRACT_DRIFT")
    if receipt.steps != _make_steps():
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_STEP_CONTRACT_DRIFT")
    if any(step.may_execute_in_cp56 for step in receipt.steps):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_CP56_EXECUTION_FORBIDDEN")
    if receipt.recovery != RecoveryContract():
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RECOVERY_CONTRACT_DRIFT")

    if any((
        receipt.endpoint_materialized,
        receipt.execution_authorized,
        receipt.secret_reference_resolved,
        receipt.environment_read,
        receipt.keychain_read,
        receipt.oauth_attempted,
        receipt.network_attempted,
        receipt.live_response_observed,
        receipt.real_account_lookup_attempted,
        receipt.account_connected,
        receipt.publish_attempted,
        receipt.external_write_performed,
        receipt.deploy_performed,
        receipt.live_entitlement_verified,
        receipt.live_connection_verified,
        receipt.pilot_publish_ready,
    )):
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not receipt.global_kill_switch_required or not receipt.live_reverification_required:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_SAFETY_FLAG_DRIFT")
    if receipt.state != PROBE_RUNBOOK_STATE:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RECEIPT_STATE")

    body = receipt.to_dict()
    body.pop("runbook_id")
    body.pop("runbook_hash")
    expected_hash = _hash(body)
    if receipt.runbook_hash != expected_hash:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RECEIPT_HASH_MISMATCH")
    if receipt.runbook_id != "mlrp_" + receipt.runbook_hash[:24]:
        raise MetaLiveReadOnlyProbeHold("HOLD_PROBE_RUNBOOK_RECEIPT_ID_MISMATCH")


def render_meta_live_read_only_probe_runbook_json(receipt: MetaLiveReadOnlyProbeRunbookReceipt) -> str:
    validate_meta_live_read_only_probe_runbook_receipt(receipt)
    return canonical_json(receipt.to_dict()) + "\n"
