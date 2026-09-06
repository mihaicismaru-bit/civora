from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re

from .control import EXPECTED_ACTIVE, canonical_json, validate_policy
from .meta_transport_twin import TwinTransportReceipt, validate_transport_twin_receipt

READ_ONLY_GATE_MODEL_VERSION = "PPOS_META_READ_ONLY_CONNECTION_GATE_V1"
READ_ONLY_GATE_ENGINE_VERSION = "ppos-meta-read-only-gate-v1.0.0"
READ_ONLY_GATE_STATE = "PASS_READ_ONLY_GATE_CONTRACT_LOCAL_ONLY"
PROBE_MODE = "CONTRACT_ONLY_NO_NETWORK"
KILL_SWITCH_INTERLOCK = "ENGAGED_REQUIRED_PRE_PILOT"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_FUTURE_EVIDENCE = (
    "LIVE_TOKEN_DEBUG_REDACTED",
    "LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED",
    "LIVE_PERMISSION_SET_EXACT",
    "LIVE_CAPABILITY_SET_EXACT",
    "LIVE_EXPIRY_STATE",
    "LIVE_READ_ONLY_RESPONSE_HASH",
    "OPERATOR_TIMESTAMP_UTC",
    "API_VERSION_PIN",
    "ZERO_WRITE_CONFIRMATION",
)


class MetaReadOnlyGateError(ValueError):
    pass


class MetaReadOnlyGateHold(MetaReadOnlyGateError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EvidenceRequirement:
    code: str
    state: str = "NOT_CAPTURED"
    required: bool = True
    must_be_live: bool = True
    operator_supplied: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class KillSwitchInterlock:
    required: bool = True
    engaged: bool = True
    state: str = KILL_SWITCH_INTERLOCK
    automatic_disengage_allowed: bool = False
    operator_override_allowed: bool = False
    unlock_path_materialized: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MetaReadOnlyGateReceipt:
    gate_id: str
    gate_hash: str
    model_version: str
    engine_version: str
    transport_twin_id: str
    transport_twin_hash: str
    platform: str
    mode: str
    runtime_policy_sha256: str
    evidence_requirements: tuple[EvidenceRequirement, ...]
    kill_switch: KillSwitchInterlock
    read_only_method_allowlist: tuple[str, ...] = ("GET",)
    mutating_methods_forbidden: tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE")
    probe_mode: str = PROBE_MODE
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
    state: str = READ_ONLY_GATE_STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence_requirements"] = [item.to_dict() for item in self.evidence_requirements]
        data["kill_switch"] = self.kill_switch.to_dict()
        data["read_only_method_allowlist"] = list(self.read_only_method_allowlist)
        data["mutating_methods_forbidden"] = list(self.mutating_methods_forbidden)
        return data


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_runtime_policy(runtime_policy: dict) -> None:
    result = validate_policy(runtime_policy)
    if not result.ok:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_RUNTIME_POLICY_INVALID")
    if tuple(runtime_policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_ACTIVE_PLATFORM_DRIFT")
    if runtime_policy.get("global_kill_switch_engaged") is not True:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_KILL_SWITCH_NOT_ENGAGED")
    forbidden_true = (
        "network_enabled",
        "real_accounts_connected",
        "publish_enabled",
        "deploy_enabled",
        "account_connection_enabled",
        "scheduler_write_enabled",
        "queue_mutation_enabled",
        "publisher_write_enabled",
    )
    if any(runtime_policy.get(key) is not False for key in forbidden_true):
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_RUNTIME_AUTHORITY_NOT_ZERO")


def compile_meta_read_only_gate(
    twin: TwinTransportReceipt,
    runtime_policy: dict,
) -> MetaReadOnlyGateReceipt:
    validate_transport_twin_receipt(twin)
    _validate_runtime_policy(runtime_policy)
    if twin.platform not in EXPECTED_ACTIVE:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_PLATFORM_NOT_ACTIVE")
    if not twin.global_kill_switch_required or not twin.live_reverification_required:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_CP54_SAFETY_DRIFT")
    if twin.live_transport_ready or twin.pilot_publish_ready:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_CP54_EXTERNAL_AUTHORITY_FORBIDDEN")

    runtime_policy_sha256 = _hash(runtime_policy)
    requirements = tuple(EvidenceRequirement(code=code) for code in REQUIRED_FUTURE_EVIDENCE)
    interlock = KillSwitchInterlock()
    body = {
        "model_version": READ_ONLY_GATE_MODEL_VERSION,
        "engine_version": READ_ONLY_GATE_ENGINE_VERSION,
        "transport_twin_id": twin.twin_id,
        "transport_twin_hash": twin.twin_hash,
        "platform": twin.platform,
        "mode": twin.mode,
        "runtime_policy_sha256": runtime_policy_sha256,
        "evidence_requirements": [item.to_dict() for item in requirements],
        "kill_switch": interlock.to_dict(),
        "read_only_method_allowlist": ["GET"],
        "mutating_methods_forbidden": ["POST", "PUT", "PATCH", "DELETE"],
        "probe_mode": PROBE_MODE,
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
        "state": READ_ONLY_GATE_STATE,
    }
    gate_hash = _hash(body)
    receipt = MetaReadOnlyGateReceipt(
        gate_id="mrog_" + gate_hash[:24],
        gate_hash=gate_hash,
        model_version=READ_ONLY_GATE_MODEL_VERSION,
        engine_version=READ_ONLY_GATE_ENGINE_VERSION,
        transport_twin_id=twin.twin_id,
        transport_twin_hash=twin.twin_hash,
        platform=twin.platform,
        mode=twin.mode,
        runtime_policy_sha256=runtime_policy_sha256,
        evidence_requirements=requirements,
        kill_switch=interlock,
    )
    validate_meta_read_only_gate_receipt(receipt)
    return receipt


def validate_meta_read_only_gate_receipt(receipt: MetaReadOnlyGateReceipt) -> None:
    if not isinstance(receipt, MetaReadOnlyGateReceipt):
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_RECEIPT_TYPE")
    if receipt.model_version != READ_ONLY_GATE_MODEL_VERSION or receipt.engine_version != READ_ONLY_GATE_ENGINE_VERSION:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_RECEIPT_VERSION")
    if receipt.platform not in EXPECTED_ACTIVE:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(receipt.transport_twin_hash) or not HEX64.fullmatch(receipt.runtime_policy_sha256):
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_BINDING_HASH_INVALID")
    if receipt.read_only_method_allowlist != ("GET",):
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_METHOD_ALLOWLIST_DRIFT")
    if receipt.mutating_methods_forbidden != ("POST", "PUT", "PATCH", "DELETE"):
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_MUTATING_METHOD_GUARD_DRIFT")
    if receipt.probe_mode != PROBE_MODE:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_PROBE_MODE_DRIFT")
    if tuple(item.code for item in receipt.evidence_requirements) != REQUIRED_FUTURE_EVIDENCE:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_EVIDENCE_SET_DRIFT")
    for item in receipt.evidence_requirements:
        if item.state != "NOT_CAPTURED" or not item.required or not item.must_be_live or not item.operator_supplied:
            raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_PRETENDED_LIVE_EVIDENCE")
    if receipt.kill_switch != KillSwitchInterlock():
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_KILL_SWITCH_INTERLOCK_DRIFT")
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
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not receipt.live_reverification_required:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_LIVE_REVERIFICATION_DRIFT")
    if receipt.state != READ_ONLY_GATE_STATE:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_RECEIPT_STATE")
    body = receipt.to_dict()
    body.pop("gate_id")
    body.pop("gate_hash")
    expected_hash = _hash(body)
    if receipt.gate_hash != expected_hash:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_RECEIPT_HASH_MISMATCH")
    if receipt.gate_id != "mrog_" + receipt.gate_hash[:24]:
        raise MetaReadOnlyGateHold("HOLD_READ_ONLY_GATE_RECEIPT_ID_MISMATCH")


def render_meta_read_only_gate_json(receipt: MetaReadOnlyGateReceipt) -> str:
    validate_meta_read_only_gate_receipt(receipt)
    return canonical_json(receipt.to_dict()) + "\n"
