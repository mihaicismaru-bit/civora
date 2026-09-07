from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re
from typing import Any

from .connection_preflight import SyntheticPreflightReceipt, validate_synthetic_preflight_receipt
from .connection_profiles import ConnectionProfile, validate_connection_profile
from .control import EXPECTED_ACTIVE, canonical_json
from .meta_adapters import OfflineRequestPlan, validate_request_plan
from .meta_live_read_only_probe import MetaLiveReadOnlyProbeContract, validate_live_read_only_probe_contract
from .meta_offline_evidence import MetaOfflineEvidenceBundleReceipt, validate_offline_evidence_bundle_receipt
from .meta_read_only_gate import REQUIRED_FUTURE_EVIDENCE, MetaReadOnlyGateReceipt, validate_meta_read_only_gate_receipt
from .meta_transport_twin import TwinTransportReceipt, validate_transport_twin_receipt
from .operator_provisioning import OperatorProvisioningPacket, validate_operator_provisioning_packet

MODEL_VERSION = "PPOS_META_PILOT_READINESS_AGGREGATOR_V1"
ENGINE_VERSION = "ppos-meta-pilot-readiness-aggregator-v1.0.0"
STATE = "PASS_CP58_OFFLINE_READINESS_AGGREGATED_LIVE_CONNECTION_HOLD"
AUTHORIZATION_STATE = "HOLD_LIVE_CONNECTION_AUTHORIZATION"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

LINEAGE_CODES = (
    "CP50_META_ADAPTERS",
    "CP51_META_CONNECTIONS",
    "CP52_META_PREFLIGHT",
    "CP53_META_OPERATOR_PROVISIONING",
    "CP54_META_TRANSPORT_TWIN",
    "CP55_META_READ_ONLY_GATE",
    "CP56_META_LIVE_READ_ONLY_PROBE",
    "CP57_META_OFFLINE_EVIDENCE_VALIDATOR",
)

REQUIRED_BLOCKERS = (
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED",
    "HOLD_LIVE_PERMISSION_CAPABILITY_NOT_VERIFIED",
    "HOLD_LIVE_API_VERSION_AND_DESTINATION_UNBOUND",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_FINAL_PILOT_AUTHORIZATION_REQUIRED",
)


class MetaPilotReadinessError(ValueError):
    pass


class MetaPilotReadinessHold(MetaPilotReadinessError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LineageBinding:
    checkpoint: str
    artifact_kind: str
    artifact_id: str
    artifact_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MetaPilotReadinessReceipt:
    readiness_id: str
    readiness_hash: str
    model_version: str
    engine_version: str
    platform: str
    mode: str
    readiness_policy_sha256: str
    lineage: tuple[LineageBinding, ...]
    checks: tuple[str, ...]
    blockers: tuple[str, ...]
    required_live_evidence_codes: tuple[str, ...]
    authorization_state: str = AUTHORIZATION_STATE
    global_kill_switch_engaged: bool = True
    exact_lineage_validated: bool = True
    offline_meta_path_validated: bool = True
    synthetic_operator_dry_run_validated: bool = True
    live_evidence_captured: bool = False
    live_entitlement_verified: bool = False
    live_permission_capability_verified: bool = False
    live_api_version_destination_bound: bool = False
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
    live_connection_authorized: bool = False
    final_pilot_authorization_present: bool = False
    pilot_publish_ready: bool = False
    state: str = STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["lineage"] = [item.to_dict() for item in self.lineage]
        data["checks"] = list(self.checks)
        data["blockers"] = list(self.blockers)
        data["required_live_evidence_codes"] = list(self.required_live_evidence_codes)
        return data


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_META_PILOT_READINESS_POLICY_V1":
        raise MetaPilotReadinessHold("HOLD_CP58_POLICY_SCHEMA")
    if policy.get("checkpoint") != "CP58" or policy.get("module_id") != "M27_META_PILOT_READINESS":
        raise MetaPilotReadinessHold("HOLD_CP58_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise MetaPilotReadinessHold("HOLD_CP58_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_lineage", ())) != LINEAGE_CODES:
        raise MetaPilotReadinessHold("HOLD_CP58_REQUIRED_LINEAGE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise MetaPilotReadinessHold("HOLD_CP58_REQUIRED_BLOCKER_DRIFT")

    contract = policy.get("readiness_contract", {})
    required_true = (
        "offline_aggregation_only",
        "exact_lineage_binding_required",
        "validate_each_input_receipt_required",
        "global_kill_switch_must_be_engaged",
        "synthetic_cp57_pass_required",
        "live_evidence_required_before_connection_authorization",
        "fresh_explicit_final_authorization_required",
        "automatic_authorization_forbidden",
        "self_authorization_forbidden",
    )
    if any(contract.get(key) is not True for key in required_true):
        raise MetaPilotReadinessHold("HOLD_CP58_POLICY_REQUIRED_GUARD_MISSING")
    if contract.get("live_connection_authorization_default") != "HOLD":
        raise MetaPilotReadinessHold("HOLD_CP58_POLICY_AUTHORIZATION_DEFAULT_DRIFT")
    if contract.get("pilot_publish_ready") is not False:
        raise MetaPilotReadinessHold("HOLD_CP58_POLICY_PILOT_READY_DRIFT")

    authority = policy.get("authority", {})
    if any(value is not False for value in authority.values()):
        raise MetaPilotReadinessHold("HOLD_CP58_POLICY_EXTERNAL_AUTHORITY_NOT_ZERO")


def _validate_inputs(
    plan: OfflineRequestPlan,
    profile: ConnectionProfile,
    preflight: SyntheticPreflightReceipt,
    packet: OperatorProvisioningPacket,
    twin: TwinTransportReceipt,
    gate: MetaReadOnlyGateReceipt,
    contract: MetaLiveReadOnlyProbeContract,
    bundle: MetaOfflineEvidenceBundleReceipt,
) -> None:
    validate_request_plan(plan)
    validate_connection_profile(profile)
    validate_synthetic_preflight_receipt(preflight)
    validate_operator_provisioning_packet(packet)
    validate_transport_twin_receipt(twin)
    validate_meta_read_only_gate_receipt(gate)
    validate_live_read_only_probe_contract(contract)
    validate_offline_evidence_bundle_receipt(bundle)

    exact = (
        (preflight.plan_id, plan.plan_id),
        (preflight.plan_hash, plan.plan_hash),
        (preflight.profile_id, profile.profile_id),
        (preflight.profile_hash, profile.profile_hash),
        (packet.preflight_receipt_id, preflight.receipt_id),
        (packet.preflight_receipt_hash, preflight.receipt_hash),
        (packet.profile_id, profile.profile_id),
        (packet.profile_hash, profile.profile_hash),
        (twin.plan_id, plan.plan_id),
        (twin.plan_hash, plan.plan_hash),
        (twin.preflight_receipt_id, preflight.receipt_id),
        (twin.preflight_receipt_hash, preflight.receipt_hash),
        (twin.provisioning_packet_id, packet.packet_id),
        (twin.provisioning_packet_hash, packet.packet_hash),
        (gate.transport_twin_id, twin.twin_id),
        (gate.transport_twin_hash, twin.twin_hash),
        (contract.read_only_gate_id, gate.gate_id),
        (contract.read_only_gate_hash, gate.gate_hash),
        (bundle.cp56_contract_id, contract.contract_id),
        (bundle.cp56_contract_hash, contract.contract_hash),
    )
    if any(left != right for left, right in exact):
        raise MetaPilotReadinessHold("HOLD_CP58_EXACT_LINEAGE_BINDING_MISMATCH")

    platforms = {
        plan.platform,
        profile.platform,
        preflight.readback.platform,
        packet.platform,
        twin.platform,
        gate.platform,
        contract.platform,
        bundle.platform,
    }
    modes = {
        plan.mode,
        profile.mode,
        preflight.readback.mode,
        packet.mode,
        twin.mode,
        gate.mode,
        contract.mode,
        bundle.mode,
    }
    if len(platforms) != 1 or len(modes) != 1:
        raise MetaPilotReadinessHold("HOLD_CP58_PLATFORM_OR_MODE_LINEAGE_DRIFT")
    if plan.platform not in EXPECTED_ACTIVE:
        raise MetaPilotReadinessHold("HOLD_CP58_PLATFORM_NOT_ACTIVE")

    if not profile.offline_contract_evidence_complete or not preflight.synthetic_contract_pass:
        raise MetaPilotReadinessHold("HOLD_CP58_OFFLINE_CONTRACT_INCOMPLETE")
    if not gate.kill_switch.engaged or not gate.kill_switch.required:
        raise MetaPilotReadinessHold("HOLD_CP58_KILL_SWITCH_INTERLOCK_DRIFT")
    if not contract.global_kill_switch_required_engaged or not bundle.global_kill_switch_engaged:
        raise MetaPilotReadinessHold("HOLD_CP58_KILL_SWITCH_LINEAGE_DRIFT")
    if not bundle.synthetic_fixture_only or not bundle.operator_dry_run_passed or not bundle.zero_write_confirmed:
        raise MetaPilotReadinessHold("HOLD_CP58_CP57_SYNTHETIC_VALIDATION_INCOMPLETE")
    if tuple(item.code for item in bundle.evidence) != REQUIRED_FUTURE_EVIDENCE:
        raise MetaPilotReadinessHold("HOLD_CP58_EVIDENCE_CODE_SET_DRIFT")

    forbidden = (
        profile.real_entitlement_asserted,
        preflight.live_entitlement_verified,
        preflight.secret_resolved,
        preflight.network_attempted,
        preflight.account_connected,
        preflight.publish_attempted,
        packet.secret_resolved,
        packet.environment_read,
        packet.keychain_read,
        packet.network_attempted,
        packet.real_account_lookup_attempted,
        packet.account_connected,
        packet.publish_attempted,
        twin.secret_reference_resolved,
        twin.environment_read,
        twin.keychain_read,
        twin.oauth_attempted,
        twin.real_account_lookup_attempted,
        twin.account_connected,
        twin.network_attempted,
        twin.publish_attempted,
        gate.secret_reference_resolved,
        gate.environment_read,
        gate.keychain_read,
        gate.oauth_attempted,
        gate.real_account_lookup_attempted,
        gate.account_connected,
        gate.network_attempted,
        gate.publish_attempted,
        contract.secret_reference_resolved,
        contract.environment_read,
        contract.keychain_read,
        contract.oauth_attempted,
        contract.real_account_lookup_attempted,
        contract.account_connected,
        contract.network_attempted,
        contract.publish_attempted,
        bundle.secret_reference_resolved,
        bundle.environment_read,
        bundle.keychain_read,
        bundle.oauth_attempted,
        bundle.real_account_lookup_attempted,
        bundle.account_connected,
        bundle.network_attempted,
        bundle.publish_attempted,
        bundle.external_write_performed,
        bundle.deploy_performed,
        bundle.live_evidence_claimed,
        bundle.live_entitlement_verified,
        bundle.live_connection_verified,
        bundle.pilot_publish_ready,
    )
    if any(forbidden):
        raise MetaPilotReadinessHold("HOLD_CP58_EXTERNAL_OR_LIVE_AUTHORITY_FORBIDDEN")


def _lineage(
    plan: OfflineRequestPlan,
    profile: ConnectionProfile,
    preflight: SyntheticPreflightReceipt,
    packet: OperatorProvisioningPacket,
    twin: TwinTransportReceipt,
    gate: MetaReadOnlyGateReceipt,
    contract: MetaLiveReadOnlyProbeContract,
    bundle: MetaOfflineEvidenceBundleReceipt,
) -> tuple[LineageBinding, ...]:
    return (
        LineageBinding("CP50_META_ADAPTERS", "OFFLINE_REQUEST_PLAN", plan.plan_id, plan.plan_hash),
        LineageBinding("CP51_META_CONNECTIONS", "CONNECTION_PROFILE", profile.profile_id, profile.profile_hash),
        LineageBinding("CP52_META_PREFLIGHT", "SYNTHETIC_PREFLIGHT_RECEIPT", preflight.receipt_id, preflight.receipt_hash),
        LineageBinding("CP53_META_OPERATOR_PROVISIONING", "OPERATOR_PROVISIONING_PACKET", packet.packet_id, packet.packet_hash),
        LineageBinding("CP54_META_TRANSPORT_TWIN", "SYNTHETIC_TRANSPORT_TWIN", twin.twin_id, twin.twin_hash),
        LineageBinding("CP55_META_READ_ONLY_GATE", "READ_ONLY_CONNECTION_GATE", gate.gate_id, gate.gate_hash),
        LineageBinding("CP56_META_LIVE_READ_ONLY_PROBE", "READ_ONLY_PROBE_CONTRACT", contract.contract_id, contract.contract_hash),
        LineageBinding("CP57_META_OFFLINE_EVIDENCE_VALIDATOR", "SYNTHETIC_EVIDENCE_BUNDLE", bundle.bundle_id, bundle.bundle_hash),
    )


def compile_meta_pilot_readiness(
    plan: OfflineRequestPlan,
    profile: ConnectionProfile,
    preflight: SyntheticPreflightReceipt,
    packet: OperatorProvisioningPacket,
    twin: TwinTransportReceipt,
    gate: MetaReadOnlyGateReceipt,
    contract: MetaLiveReadOnlyProbeContract,
    bundle: MetaOfflineEvidenceBundleReceipt,
    policy: dict,
) -> MetaPilotReadinessReceipt:
    _validate_policy(policy)
    _validate_inputs(plan, profile, preflight, packet, twin, gate, contract, bundle)

    lineage = _lineage(plan, profile, preflight, packet, twin, gate, contract, bundle)
    checks = (
        "cp50_request_plan_valid",
        "cp51_connection_profile_valid",
        "cp52_preflight_valid",
        "cp53_operator_packet_valid",
        "cp54_transport_twin_valid",
        "cp55_read_only_gate_valid",
        "cp56_probe_contract_valid",
        "cp57_synthetic_evidence_bundle_valid",
        "cp50_cp57_exact_lineage_bound",
        "active_platform_exact",
        "platform_mode_exact_across_lineage",
        "global_kill_switch_engaged",
        "zero_write_confirmed",
        "offline_meta_path_validated",
        "live_connection_authorization_held",
        "pilot_publish_authority_zero",
    )
    policy_hash = _hash(policy)
    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "platform": plan.platform,
        "mode": plan.mode,
        "readiness_policy_sha256": policy_hash,
        "lineage": [item.to_dict() for item in lineage],
        "checks": list(checks),
        "blockers": list(REQUIRED_BLOCKERS),
        "required_live_evidence_codes": list(REQUIRED_FUTURE_EVIDENCE),
        "authorization_state": AUTHORIZATION_STATE,
        "global_kill_switch_engaged": True,
        "exact_lineage_validated": True,
        "offline_meta_path_validated": True,
        "synthetic_operator_dry_run_validated": True,
        "live_evidence_captured": False,
        "live_entitlement_verified": False,
        "live_permission_capability_verified": False,
        "live_api_version_destination_bound": False,
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
        "live_connection_authorized": False,
        "final_pilot_authorization_present": False,
        "pilot_publish_ready": False,
        "state": STATE,
    }
    readiness_hash = _hash(body)
    receipt = MetaPilotReadinessReceipt(
        readiness_id="mpr_" + readiness_hash[:24],
        readiness_hash=readiness_hash,
        model_version=MODEL_VERSION,
        engine_version=ENGINE_VERSION,
        platform=plan.platform,
        mode=plan.mode,
        readiness_policy_sha256=policy_hash,
        lineage=lineage,
        checks=checks,
        blockers=REQUIRED_BLOCKERS,
        required_live_evidence_codes=REQUIRED_FUTURE_EVIDENCE,
    )
    validate_meta_pilot_readiness_receipt(receipt)
    return receipt


def validate_meta_pilot_readiness_receipt(receipt: MetaPilotReadinessReceipt) -> None:
    if not isinstance(receipt, MetaPilotReadinessReceipt):
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_TYPE")
    if receipt.model_version != MODEL_VERSION or receipt.engine_version != ENGINE_VERSION:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_VERSION")
    if receipt.platform not in EXPECTED_ACTIVE:
        raise MetaPilotReadinessHold("HOLD_CP58_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(receipt.readiness_policy_sha256):
        raise MetaPilotReadinessHold("HOLD_CP58_POLICY_HASH_INVALID")
    if tuple(item.checkpoint for item in receipt.lineage) != LINEAGE_CODES:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_LINEAGE_ORDER_DRIFT")
    if any(not item.artifact_id or not HEX64.fullmatch(item.artifact_hash) for item in receipt.lineage):
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_LINEAGE_BINDING_INVALID")
    if receipt.blockers != REQUIRED_BLOCKERS:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_BLOCKER_DRIFT")
    if receipt.required_live_evidence_codes != REQUIRED_FUTURE_EVIDENCE:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_EVIDENCE_CODE_DRIFT")
    if receipt.authorization_state != AUTHORIZATION_STATE:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_AUTHORIZATION_STATE_DRIFT")
    if not all((
        receipt.global_kill_switch_engaged,
        receipt.exact_lineage_validated,
        receipt.offline_meta_path_validated,
        receipt.synthetic_operator_dry_run_validated,
    )):
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_REQUIRED_PASS_GUARD_DRIFT")
    if any((
        receipt.live_evidence_captured,
        receipt.live_entitlement_verified,
        receipt.live_permission_capability_verified,
        receipt.live_api_version_destination_bound,
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
        receipt.live_connection_authorized,
        receipt.final_pilot_authorization_present,
        receipt.pilot_publish_ready,
    )):
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_EXTERNAL_OR_LIVE_AUTHORITY_FORBIDDEN")
    if receipt.state != STATE:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_STATE")

    body = receipt.to_dict()
    body.pop("readiness_id")
    body.pop("readiness_hash")
    expected_hash = _hash(body)
    if receipt.readiness_hash != expected_hash:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_HASH_MISMATCH")
    if receipt.readiness_id != "mpr_" + receipt.readiness_hash[:24]:
        raise MetaPilotReadinessHold("HOLD_CP58_RECEIPT_ID_MISMATCH")


def render_meta_pilot_readiness_json(receipt: MetaPilotReadinessReceipt) -> str:
    validate_meta_pilot_readiness_receipt(receipt)
    return canonical_json(receipt.to_dict()) + "\n"
