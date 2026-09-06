from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re

from .control import EXPECTED_ACTIVE, canonical_json
from .meta_read_only_gate import (
    REQUIRED_FUTURE_EVIDENCE,
    MetaReadOnlyGateReceipt,
    validate_meta_read_only_gate_receipt,
)

PROBE_CONTRACT_MODEL_VERSION = "PPOS_META_LIVE_READ_ONLY_PROBE_CONTRACT_V1"
PROBE_CONTRACT_ENGINE_VERSION = "ppos-meta-live-read-only-probe-contract-v1.0.0"
PROBE_CONTRACT_STATE = "PASS_LIVE_READ_ONLY_PROBE_RUNBOOK_CONTRACT_LOCAL_ONLY"
CONTRACT_MODE = "RUNBOOK_CONTRACT_ONLY_NO_NETWORK"
API_VERSION_PIN_STATE = "NOT_CAPTURED"
ZERO_WRITE_PROOF_STATE = "NOT_CAPTURED"
EVIDENCE_STATE = "NOT_CAPTURED"
HASH_ALGORITHM = "SHA256"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

PLATFORM_PROBE_CLASSES = {
    "FACEBOOK_PAGE": (
        "TOKEN_DEBUG_READ_ONLY",
        "PAGE_IDENTITY_READ_ONLY",
        "PAGE_PERMISSION_CAPABILITY_READBACK",
    ),
    "INSTAGRAM_PROFESSIONAL": (
        "TOKEN_DEBUG_READ_ONLY",
        "IG_PROFESSIONAL_IDENTITY_READ_ONLY",
        "IG_PERMISSION_CAPABILITY_READBACK",
    ),
    "THREADS": (
        "TOKEN_DEBUG_READ_ONLY",
        "THREADS_PROFILE_IDENTITY_READ_ONLY",
        "THREADS_PERMISSION_CAPABILITY_READBACK",
    ),
}

CAPTURE_KIND_BY_CODE = {
    "LIVE_TOKEN_DEBUG_REDACTED": "REDACTED_CANONICAL_JSON_HASH",
    "LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED": "REDACTED_CANONICAL_JSON_HASH",
    "LIVE_PERMISSION_SET_EXACT": "SORTED_STRING_SET_AND_HASH",
    "LIVE_CAPABILITY_SET_EXACT": "SORTED_STRING_SET_AND_HASH",
    "LIVE_EXPIRY_STATE": "NORMALIZED_STATE_AND_HASH",
    "LIVE_READ_ONLY_RESPONSE_HASH": "SHA256_ONLY",
    "OPERATOR_TIMESTAMP_UTC": "RFC3339_UTC_AND_HASH",
    "API_VERSION_PIN": "VERSION_LITERAL_SOURCE_BINDING_AND_HASH",
    "ZERO_WRITE_CONFIRMATION": "LOCAL_INVARIANT_PROOF_AND_HASH",
}


class MetaLiveReadOnlyProbeError(ValueError):
    pass


class MetaLiveReadOnlyProbeHold(MetaLiveReadOnlyProbeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProbeStep:
    order: int
    step_id: str
    request_class: str
    method: str = "GET"
    endpoint_selector: str = "OPERATOR_VERIFIED_META_DOCUMENTED_ENDPOINT"
    endpoint_materialized: bool = False
    secret_reference_resolved: bool = False
    network_allowed: bool = False
    external_write_allowed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceCaptureContract:
    code: str
    capture_kind: str
    state: str = EVIDENCE_STATE
    hash_algorithm: str = HASH_ALGORITHM
    canonicalization_required: bool = True
    redaction_required: bool = True
    raw_secret_bytes_allowed: bool = False
    raw_token_persistence_allowed: bool = False
    external_upload_allowed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryContract:
    keep_global_kill_switch_engaged: bool = True
    abort_on_non_get_method: bool = True
    abort_on_endpoint_drift: bool = True
    abort_on_api_version_drift: bool = True
    abort_on_permission_or_identity_mismatch: bool = True
    discard_unredacted_working_material: bool = True
    preserve_only_redacted_hash_bound_evidence: bool = True
    auto_retry_live_probe_allowed: bool = False
    rollback_mutation_required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MetaLiveReadOnlyProbeContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    read_only_gate_id: str
    read_only_gate_hash: str
    platform: str
    mode: str
    runbook_policy_sha256: str
    steps: tuple[ProbeStep, ...]
    evidence_contract: tuple[EvidenceCaptureContract, ...]
    recovery: RecoveryContract
    method_allowlist: tuple[str, ...] = ("GET",)
    mutating_methods_forbidden: tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE")
    api_version_pin_state: str = API_VERSION_PIN_STATE
    zero_write_proof_state: str = ZERO_WRITE_PROOF_STATE
    contract_mode: str = CONTRACT_MODE
    global_kill_switch_required_engaged: bool = True
    live_endpoint_materialized: bool = False
    live_probe_authorized: bool = False
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
    live_entitlement_verified: bool = False
    live_connection_verified: bool = False
    pilot_publish_ready: bool = False
    live_reverification_required: bool = True
    state: str = PROBE_CONTRACT_STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["steps"] = [item.to_dict() for item in self.steps]
        data["evidence_contract"] = [item.to_dict() for item in self.evidence_contract]
        data["recovery"] = self.recovery.to_dict()
        data["method_allowlist"] = list(self.method_allowlist)
        data["mutating_methods_forbidden"] = list(self.mutating_methods_forbidden)
        return data


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_META_LIVE_READ_ONLY_PROBE_POLICY_V1":
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_POLICY_SCHEMA")
    if policy.get("checkpoint") != "CP56" or policy.get("module_id") != "M25_META_LIVE_READ_ONLY_PROBE":
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_ACTIVE_PLATFORM_DRIFT")
    contract = policy.get("contract", {})
    required_true = (
        "runbook_contract_only",
        "exact_cp55_gate_binding_required",
        "global_kill_switch_must_be_engaged",
        "api_version_pin_required_later",
        "redaction_before_persistence_required_later",
        "sha256_evidence_binding_required_later",
        "zero_write_proof_required_later",
        "operator_timestamp_required_later",
        "live_reverification_required",
    )
    if any(contract.get(key) is not True for key in required_true):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_POLICY_REQUIRED_GUARD_MISSING")
    if contract.get("method_allowlist") != ["GET"]:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_POLICY_METHOD_DRIFT")
    if contract.get("mutating_methods_forbidden") != ["POST", "PUT", "PATCH", "DELETE"]:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_POLICY_MUTATING_GUARD_DRIFT")
    if policy.get("required_evidence_codes") != list(REQUIRED_FUTURE_EVIDENCE):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_POLICY_EVIDENCE_DRIFT")
    authority = policy.get("authority", {})
    required_false = (
        "real_secret_reference_resolution_allowed",
        "environment_read_allowed",
        "keychain_read_allowed",
        "oauth_allowed",
        "real_account_lookup_allowed",
        "account_connection_allowed",
        "network_allowed",
        "publish_execution_allowed",
        "external_write_allowed",
        "deploy_allowed",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_POLICY_EXTERNAL_AUTHORITY_NOT_ZERO")


def _steps(platform: str) -> tuple[ProbeStep, ...]:
    request_classes = PLATFORM_PROBE_CLASSES.get(platform)
    if request_classes is None:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PLATFORM_NOT_ACTIVE")
    return tuple(
        ProbeStep(order=index + 1, step_id=f"S{index + 1:02d}", request_class=request_class)
        for index, request_class in enumerate(request_classes)
    )


def _evidence_contract() -> tuple[EvidenceCaptureContract, ...]:
    return tuple(
        EvidenceCaptureContract(code=code, capture_kind=CAPTURE_KIND_BY_CODE[code])
        for code in REQUIRED_FUTURE_EVIDENCE
    )


def compile_live_read_only_probe_contract(
    gate: MetaReadOnlyGateReceipt,
    policy: dict,
) -> MetaLiveReadOnlyProbeContract:
    validate_meta_read_only_gate_receipt(gate)
    _validate_policy(policy)
    if gate.platform not in EXPECTED_ACTIVE:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PLATFORM_NOT_ACTIVE")
    if not gate.kill_switch.engaged or not gate.kill_switch.required:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_KILL_SWITCH_INTERLOCK_DRIFT")
    if gate.live_probe_authorized or gate.network_attempted or gate.account_connected:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_CP55_EXTERNAL_AUTHORITY_DRIFT")
    if tuple(item.code for item in gate.evidence_requirements) != REQUIRED_FUTURE_EVIDENCE:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_CP55_EVIDENCE_DRIFT")
    if any(item.state != "NOT_CAPTURED" for item in gate.evidence_requirements):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PRETENDED_LIVE_EVIDENCE")

    policy_hash = _hash(policy)
    steps = _steps(gate.platform)
    evidence = _evidence_contract()
    recovery = RecoveryContract()
    body = {
        "model_version": PROBE_CONTRACT_MODEL_VERSION,
        "engine_version": PROBE_CONTRACT_ENGINE_VERSION,
        "read_only_gate_id": gate.gate_id,
        "read_only_gate_hash": gate.gate_hash,
        "platform": gate.platform,
        "mode": gate.mode,
        "runbook_policy_sha256": policy_hash,
        "steps": [item.to_dict() for item in steps],
        "evidence_contract": [item.to_dict() for item in evidence],
        "recovery": recovery.to_dict(),
        "method_allowlist": ["GET"],
        "mutating_methods_forbidden": ["POST", "PUT", "PATCH", "DELETE"],
        "api_version_pin_state": API_VERSION_PIN_STATE,
        "zero_write_proof_state": ZERO_WRITE_PROOF_STATE,
        "contract_mode": CONTRACT_MODE,
        "global_kill_switch_required_engaged": True,
        "live_endpoint_materialized": False,
        "live_probe_authorized": False,
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
        "live_entitlement_verified": False,
        "live_connection_verified": False,
        "pilot_publish_ready": False,
        "live_reverification_required": True,
        "state": PROBE_CONTRACT_STATE,
    }
    contract_hash = _hash(body)
    receipt = MetaLiveReadOnlyProbeContract(
        contract_id="mlrop_" + contract_hash[:24],
        contract_hash=contract_hash,
        model_version=PROBE_CONTRACT_MODEL_VERSION,
        engine_version=PROBE_CONTRACT_ENGINE_VERSION,
        read_only_gate_id=gate.gate_id,
        read_only_gate_hash=gate.gate_hash,
        platform=gate.platform,
        mode=gate.mode,
        runbook_policy_sha256=policy_hash,
        steps=steps,
        evidence_contract=evidence,
        recovery=recovery,
    )
    validate_live_read_only_probe_contract(receipt)
    return receipt


def validate_live_read_only_probe_contract(receipt: MetaLiveReadOnlyProbeContract) -> None:
    if not isinstance(receipt, MetaLiveReadOnlyProbeContract):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_RECEIPT_TYPE")
    if receipt.model_version != PROBE_CONTRACT_MODEL_VERSION or receipt.engine_version != PROBE_CONTRACT_ENGINE_VERSION:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_RECEIPT_VERSION")
    if receipt.platform not in EXPECTED_ACTIVE:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(receipt.read_only_gate_hash) or not HEX64.fullmatch(receipt.runbook_policy_sha256):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_BINDING_HASH_INVALID")
    if receipt.method_allowlist != ("GET",) or receipt.mutating_methods_forbidden != ("POST", "PUT", "PATCH", "DELETE"):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_METHOD_GUARD_DRIFT")
    expected_classes = PLATFORM_PROBE_CLASSES[receipt.platform]
    if tuple(item.request_class for item in receipt.steps) != expected_classes:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PROBE_STEP_DRIFT")
    if tuple(item.order for item in receipt.steps) != tuple(range(1, len(receipt.steps) + 1)):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PROBE_ORDER_DRIFT")
    for item in receipt.steps:
        if item.method != "GET" or item.endpoint_materialized or item.secret_reference_resolved or item.network_allowed or item.external_write_allowed:
            raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PROBE_STEP_EXTERNAL_AUTHORITY")
        if item.endpoint_selector != "OPERATOR_VERIFIED_META_DOCUMENTED_ENDPOINT":
            raise MetaLiveReadOnlyProbeHold("HOLD_CP56_ENDPOINT_SELECTOR_DRIFT")
    if tuple(item.code for item in receipt.evidence_contract) != REQUIRED_FUTURE_EVIDENCE:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_EVIDENCE_SET_DRIFT")
    for item in receipt.evidence_contract:
        if item.capture_kind != CAPTURE_KIND_BY_CODE[item.code]:
            raise MetaLiveReadOnlyProbeHold("HOLD_CP56_EVIDENCE_CAPTURE_KIND_DRIFT")
        if item.state != EVIDENCE_STATE or item.hash_algorithm != HASH_ALGORITHM:
            raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PRETENDED_LIVE_EVIDENCE")
        if not item.canonicalization_required or not item.redaction_required:
            raise MetaLiveReadOnlyProbeHold("HOLD_CP56_EVIDENCE_REDACTION_GUARD_DRIFT")
        if item.raw_secret_bytes_allowed or item.raw_token_persistence_allowed or item.external_upload_allowed:
            raise MetaLiveReadOnlyProbeHold("HOLD_CP56_EVIDENCE_RAW_OR_EXTERNAL_PERSISTENCE_FORBIDDEN")
    if receipt.recovery != RecoveryContract():
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_RECOVERY_CONTRACT_DRIFT")
    if receipt.api_version_pin_state != API_VERSION_PIN_STATE or receipt.zero_write_proof_state != ZERO_WRITE_PROOF_STATE:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_PRETENDED_RUNTIME_PROOF")
    if receipt.contract_mode != CONTRACT_MODE or not receipt.global_kill_switch_required_engaged:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_CONTRACT_MODE_DRIFT")
    if any((
        receipt.live_endpoint_materialized,
        receipt.live_probe_authorized,
        receipt.secret_reference_resolved,
        receipt.environment_read,
        receipt.keychain_read,
        receipt.oauth_attempted,
        receipt.real_account_lookup_attempted,
        receipt.account_connected,
        receipt.network_attempted,
        receipt.publish_attempted,
        receipt.external_write_performed,
        receipt.deploy_performed,
        receipt.live_entitlement_verified,
        receipt.live_connection_verified,
        receipt.pilot_publish_ready,
    )):
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not receipt.live_reverification_required or receipt.state != PROBE_CONTRACT_STATE:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_RECEIPT_STATE")
    body = receipt.to_dict()
    body.pop("contract_id")
    body.pop("contract_hash")
    expected_hash = _hash(body)
    if receipt.contract_hash != expected_hash:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_RECEIPT_HASH_MISMATCH")
    if receipt.contract_id != "mlrop_" + receipt.contract_hash[:24]:
        raise MetaLiveReadOnlyProbeHold("HOLD_CP56_RECEIPT_ID_MISMATCH")


def render_live_read_only_probe_contract_json(receipt: MetaLiveReadOnlyProbeContract) -> str:
    validate_live_read_only_probe_contract(receipt)
    return canonical_json(receipt.to_dict()) + "\n"
