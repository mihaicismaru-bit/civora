from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .control_plane_authorization_intake import (
    ControlPlaneAuthorizationIntakeContract,
    AuthorizationShapeReceipt,
    compile_control_plane_authorization_intake,
    validate_authorization_shape_receipt,
    validate_authorization_submission_shape,
    validate_control_plane_authorization_intake_contract,
)

MODEL_VERSION = "PPOS_AUTHORIZATION_RECEIPT_VALIDATOR_V1"
ENGINE_VERSION = "ppos-authorization-receipt-validator-v1.0.0"
STATE = "PASS_CP62_AUTHORIZATION_RECEIPT_VALIDATOR_DRY_RUN_LOCAL_ONLY_CONTROL_PROMOTION_HOLD"
CHECKPOINT = "CP62"
PARENT_INTAKE_CHECKPOINT = "CP61"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP63_LIVE_READ_ONLY_PROBE_SESSION_ENVELOPE_AND_ZERO_WRITE_RECORDER_DRY_RUN"

REQUIRED_BLOCKERS = (
    "HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED",
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
)

READ_ONLY_GATE = "LIVE_READ_ONLY_CONNECTION_PROBE"
PUBLISH_GATE = "PILOT_PUBLISH"


class AuthorizationReceiptValidatorError(ValueError):
    pass


class AuthorizationReceiptValidatorHold(AuthorizationReceiptValidatorError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ImmutableAuthorizationReceipt:
    receipt_id: str
    receipt_hash: str
    model_version: str
    checkpoint: str
    parent_intake_checkpoint: str
    parent_control_checkpoint: str
    cp61_contract_id: str
    cp61_contract_hash: str
    cp61_shape_receipt_id: str
    cp61_shape_receipt_hash: str
    cp60_packet_id: str
    cp60_packet_hash: str
    authorization_id: str
    gate_code: str
    decision: str
    allowed_platforms: tuple[str, ...]
    scope: str
    authorizer_reference_sha256: str
    authorized_at: str
    expires_at: str
    authorization_evidence_sha256: str
    nonce_sha256: str
    synthetic_fixture: bool
    immutable: bool = True
    authority_activated: bool = False
    control_promotion_allowed: bool = False
    live_probe_allowed: bool = False
    network_allowed: bool = False
    publish_allowed: bool = False
    deploy_allowed: bool = False
    state: str = "VALIDATED_IMMUTABLE_RECEIPT_NO_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["allowed_platforms"] = list(self.allowed_platforms)
        return data


@dataclass(frozen=True)
class ControlPromotionDryRunReceipt:
    dry_run_id: str
    dry_run_hash: str
    model_version: str
    checkpoint: str
    source_control_checkpoint: str
    candidate_checkpoint: str
    authorization_receipt_id: str
    authorization_receipt_hash: str
    gate_code: str
    decision: str
    allowed_platforms: tuple[str, ...]
    outcome: str
    global_kill_switch_engaged: bool = True
    registry_mutated: bool = False
    runtime_policy_mutated: bool = False
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
    authority_activated: bool = False
    promotion_committed: bool = False
    state: str = "DRY_RUN_ONLY_NO_CONTROL_PROMOTION"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["allowed_platforms"] = list(self.allowed_platforms)
        return data


@dataclass(frozen=True)
class AuthorizationReceiptValidatorContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_intake_checkpoint: str
    parent_control_checkpoint: str
    cp61_contract_id: str
    cp61_contract_hash: str
    immutable_receipt_id: str
    immutable_receipt_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp61_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    synthetic_fixture_validated: bool = True
    immutable_receipt_validated: bool = True
    control_promotion_dry_run_validated: bool = True
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


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_AUTHORIZATION_RECEIPT_VALIDATOR_POLICY_V1":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M31_AUTHORIZATION_RECEIPT_VALIDATOR":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_POLICY_IDENTITY")
    if policy.get("parent_intake_checkpoint") != PARENT_INTAKE_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_PARENT_INTAKE_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_BLOCKER_SET_DRIFT")
    if policy.get("next_after_cp62") != NEXT_UNIT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_NEXT_UNIT_DRIFT")

    receipt = policy.get("receipt_contract", {})
    required_receipt_true = (
        "offline_only",
        "exact_cp61_contract_binding_required",
        "exact_cp61_shape_receipt_binding_required",
        "exact_cp60_packet_binding_required",
        "immutable_receipt_required",
        "authorizer_reference_sha256_only",
        "authorization_evidence_sha256_only",
        "nonce_sha256_only",
        "raw_authorizer_reference_persistence_forbidden",
        "raw_authorization_evidence_persistence_forbidden",
        "raw_nonce_persistence_forbidden",
        "synthetic_fixture_required_for_repo_validation",
        "global_kill_switch_must_remain_engaged",
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
        "rollback_to_cp61_required",
    )
    if any(receipt.get(key) is not True for key in required_receipt_true):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RECEIPT_GUARD_MISSING")

    dry_run = policy.get("control_promotion_dry_run", {})
    required_dry_run_true = (
        "enabled",
        "local_only",
        "registry_mutation_forbidden",
        "runtime_policy_mutation_forbidden",
        "authority_activation_forbidden",
        "promotion_commit_forbidden",
        "global_kill_switch_must_remain_engaged",
    )
    if any(dry_run.get(key) is not True for key in required_dry_run_true):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_GUARD_MISSING")
    if dry_run.get("read_only_grant_outcome") != "PASS_CANDIDATE_ONLY_NO_AUTHORITY":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_READ_ONLY_DRY_RUN_OUTCOME_DRIFT")
    if dry_run.get("publish_grant_outcome") != "HOLD_LIVE_EVIDENCE_AND_LATER_GATE_REQUIRED":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_PUBLISH_DRY_RUN_OUTCOME_DRIFT")
    if dry_run.get("deny_outcome") != "HOLD_EXTERNAL_AUTHORIZATION_DENIED":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DENY_DRY_RUN_OUTCOME_DRIFT")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_AUTHORITY_NOT_ZERO")

    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RUNTIME_ACTIVE_PLATFORM_DRIFT")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTROL_PROMOTION_MUST_REMAIN_HOLD")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M30_CONTROL_PLANE_AUTHORIZATION_INTAKE") != "CP61_AUTHORIZATION_INTAKE_CONTRACT_LOCAL_ONLY_CONTROL_PROMOTION_HOLD":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CP61_MODULE_STATE_DRIFT")
    if states.get("M31_AUTHORIZATION_RECEIPT_VALIDATOR") != "CP62_AUTHORIZATION_RECEIPT_VALIDATOR_DRY_RUN_LOCAL_ONLY_CONTROL_PROMOTION_HOLD":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_MODULE_STATE_DRIFT")


def _payload_without_identity(value: dict, *identity_fields: str) -> dict:
    payload = dict(value)
    for field in identity_fields:
        payload.pop(field, None)
    return payload


def compile_immutable_authorization_receipt(
    cp61_contract: ControlPlaneAuthorizationIntakeContract,
    shape_receipt: AuthorizationShapeReceipt,
    *,
    synthetic_fixture: bool,
) -> ImmutableAuthorizationReceipt:
    validate_control_plane_authorization_intake_contract(cp61_contract)
    validate_authorization_shape_receipt(shape_receipt)
    if shape_receipt.cp60_packet_id != cp61_contract.cp60_packet_id or shape_receipt.cp60_packet_hash != cp61_contract.cp60_packet_hash:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CP60_BINDING_MISMATCH")
    if tuple(shape_receipt.allowed_platforms) != tuple(p for p in EXPECTED_ACTIVE if p in shape_receipt.allowed_platforms):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_PLATFORM_ORDER_OR_SCOPE_DRIFT")
    if not synthetic_fixture:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_REPO_VALIDATION_REQUIRES_SYNTHETIC_FIXTURE")

    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_intake_checkpoint": PARENT_INTAKE_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp61_contract_id": cp61_contract.contract_id,
        "cp61_contract_hash": cp61_contract.contract_hash,
        "cp61_shape_receipt_id": shape_receipt.receipt_id,
        "cp61_shape_receipt_hash": shape_receipt.receipt_hash,
        "cp60_packet_id": shape_receipt.cp60_packet_id,
        "cp60_packet_hash": shape_receipt.cp60_packet_hash,
        "authorization_id": shape_receipt.authorization_id,
        "gate_code": shape_receipt.gate_code,
        "decision": shape_receipt.decision,
        "allowed_platforms": list(shape_receipt.allowed_platforms),
        "scope": shape_receipt.scope,
        "authorizer_reference_sha256": sha256(shape_receipt.authorizer_reference.encode("utf-8")).hexdigest(),
        "authorized_at": shape_receipt.authorized_at,
        "expires_at": shape_receipt.expires_at,
        "authorization_evidence_sha256": shape_receipt.authorization_evidence_sha256,
        "nonce_sha256": shape_receipt.nonce_sha256,
        "synthetic_fixture": True,
        "immutable": True,
        "authority_activated": False,
        "control_promotion_allowed": False,
        "live_probe_allowed": False,
        "network_allowed": False,
        "publish_allowed": False,
        "deploy_allowed": False,
        "state": "VALIDATED_IMMUTABLE_RECEIPT_NO_AUTHORITY",
    }
    receipt_hash = _hash(body)
    receipt_payload = dict(body)
    receipt_payload["allowed_platforms"] = tuple(receipt_payload["allowed_platforms"])
    receipt = ImmutableAuthorizationReceipt(
        receipt_id=f"cp62_receipt_{receipt_hash[:24]}",
        receipt_hash=receipt_hash,
        **receipt_payload,
    )
    validate_immutable_authorization_receipt(cp61_contract, shape_receipt, receipt)
    return receipt


def validate_immutable_authorization_receipt(
    cp61_contract: ControlPlaneAuthorizationIntakeContract,
    shape_receipt: AuthorizationShapeReceipt,
    receipt: ImmutableAuthorizationReceipt,
) -> None:
    validate_control_plane_authorization_intake_contract(cp61_contract)
    validate_authorization_shape_receipt(shape_receipt)
    if receipt.model_version != MODEL_VERSION or receipt.checkpoint != CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RECEIPT_VERSION_DRIFT")
    if receipt.parent_intake_checkpoint != PARENT_INTAKE_CHECKPOINT or receipt.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RECEIPT_PARENT_DRIFT")
    if (receipt.cp61_contract_id, receipt.cp61_contract_hash) != (cp61_contract.contract_id, cp61_contract.contract_hash):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CP61_CONTRACT_BINDING_MISMATCH")
    if (receipt.cp61_shape_receipt_id, receipt.cp61_shape_receipt_hash) != (shape_receipt.receipt_id, shape_receipt.receipt_hash):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CP61_SHAPE_BINDING_MISMATCH")
    if (receipt.cp60_packet_id, receipt.cp60_packet_hash) != (shape_receipt.cp60_packet_id, shape_receipt.cp60_packet_hash):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CP60_BINDING_MISMATCH")
    if (
        receipt.authorization_id != shape_receipt.authorization_id
        or receipt.gate_code != shape_receipt.gate_code
        or receipt.decision != shape_receipt.decision
        or receipt.scope != shape_receipt.scope
        or receipt.allowed_platforms != shape_receipt.allowed_platforms
    ):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_AUTHORIZATION_SHAPE_BINDING_MISMATCH")
    if receipt.authorizer_reference_sha256 != sha256(shape_receipt.authorizer_reference.encode("utf-8")).hexdigest():
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_AUTHORIZER_REFERENCE_HASH_MISMATCH")
    if receipt.authorization_evidence_sha256 != shape_receipt.authorization_evidence_sha256:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_EVIDENCE_HASH_MISMATCH")
    if receipt.nonce_sha256 != shape_receipt.nonce_sha256:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_NONCE_HASH_MISMATCH")
    if receipt.authorized_at != shape_receipt.authorized_at or receipt.expires_at != shape_receipt.expires_at:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_AUTHORIZATION_WINDOW_BINDING_MISMATCH")
    if not receipt.synthetic_fixture or not receipt.immutable:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RECEIPT_MUST_BE_SYNTHETIC_IMMUTABLE")
    forbidden_true = (
        receipt.authority_activated,
        receipt.control_promotion_allowed,
        receipt.live_probe_allowed,
        receipt.network_allowed,
        receipt.publish_allowed,
        receipt.deploy_allowed,
    )
    if any(forbidden_true):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RECEIPT_AUTHORITY_NOT_ZERO")
    payload = _payload_without_identity(receipt.to_dict(), "receipt_id", "receipt_hash")
    expected_hash = _hash(payload)
    if receipt.receipt_hash != expected_hash or receipt.receipt_id != f"cp62_receipt_{expected_hash[:24]}":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_RECEIPT_HASH_BINDING_INVALID")


def _dry_run_outcome(receipt: ImmutableAuthorizationReceipt) -> str:
    if receipt.decision == "DENY":
        return "HOLD_EXTERNAL_AUTHORIZATION_DENIED_NO_AUTHORITY"
    if receipt.gate_code == PUBLISH_GATE:
        return "HOLD_PILOT_PUBLISH_REQUIRES_LIVE_EVIDENCE_AND_LATER_GATE"
    if receipt.gate_code == READ_ONLY_GATE:
        return "PASS_CP62_DRY_RUN_VALIDATED_RECEIPT_CANDIDATE_ONLY_NO_AUTHORITY"
    raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_GATE_INVALID")


def simulate_control_promotion_dry_run(
    receipt: ImmutableAuthorizationReceipt,
) -> ControlPromotionDryRunReceipt:
    if receipt.checkpoint != CHECKPOINT or receipt.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_RECEIPT_PARENT_INVALID")
    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "source_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "candidate_checkpoint": CHECKPOINT,
        "authorization_receipt_id": receipt.receipt_id,
        "authorization_receipt_hash": receipt.receipt_hash,
        "gate_code": receipt.gate_code,
        "decision": receipt.decision,
        "allowed_platforms": list(receipt.allowed_platforms),
        "outcome": _dry_run_outcome(receipt),
        "global_kill_switch_engaged": True,
        "registry_mutated": False,
        "runtime_policy_mutated": False,
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
        "authority_activated": False,
        "promotion_committed": False,
        "state": "DRY_RUN_ONLY_NO_CONTROL_PROMOTION",
    }
    dry_run_hash = _hash(body)
    dry_run_payload = dict(body)
    dry_run_payload["allowed_platforms"] = tuple(dry_run_payload["allowed_platforms"])
    dry_run = ControlPromotionDryRunReceipt(
        dry_run_id=f"cp62_dryrun_{dry_run_hash[:24]}",
        dry_run_hash=dry_run_hash,
        **dry_run_payload,
    )
    validate_control_promotion_dry_run_receipt(receipt, dry_run)
    return dry_run


def validate_control_promotion_dry_run_receipt(
    receipt: ImmutableAuthorizationReceipt,
    dry_run: ControlPromotionDryRunReceipt,
) -> None:
    if dry_run.model_version != MODEL_VERSION or dry_run.checkpoint != CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_VERSION_DRIFT")
    if dry_run.source_control_checkpoint != PARENT_CONTROL_CHECKPOINT or dry_run.candidate_checkpoint != CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_CONTROL_BINDING_DRIFT")
    if (dry_run.authorization_receipt_id, dry_run.authorization_receipt_hash) != (receipt.receipt_id, receipt.receipt_hash):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_RECEIPT_BINDING_MISMATCH")
    if dry_run.gate_code != receipt.gate_code or dry_run.decision != receipt.decision or dry_run.allowed_platforms != receipt.allowed_platforms:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_SCOPE_BINDING_MISMATCH")
    if dry_run.outcome != _dry_run_outcome(receipt):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_OUTCOME_INVALID")
    if not dry_run.global_kill_switch_engaged:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_KILL_SWITCH_NOT_ENGAGED")
    forbidden_true = (
        dry_run.registry_mutated,
        dry_run.runtime_policy_mutated,
        dry_run.secret_reference_resolved,
        dry_run.environment_read,
        dry_run.keychain_read,
        dry_run.oauth_attempted,
        dry_run.real_account_lookup_attempted,
        dry_run.account_connected,
        dry_run.network_attempted,
        dry_run.live_probe_attempted,
        dry_run.publish_attempted,
        dry_run.external_write_performed,
        dry_run.deploy_performed,
        dry_run.paid_service_used,
        dry_run.authority_activated,
        dry_run.promotion_committed,
    )
    if any(forbidden_true):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_SIDE_EFFECT_DETECTED")
    payload = _payload_without_identity(dry_run.to_dict(), "dry_run_id", "dry_run_hash")
    expected_hash = _hash(payload)
    if dry_run.dry_run_hash != expected_hash or dry_run.dry_run_id != f"cp62_dryrun_{expected_hash[:24]}":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_DRY_RUN_HASH_BINDING_INVALID")


def _synthetic_submission(cp61_contract: ControlPlaneAuthorizationIntakeContract) -> dict:
    template = next(item for item in cp61_contract.intake_templates if item.gate_code == READ_ONLY_GATE)
    return {
        "authorization_id": "auth_cp62_synthetic_001",
        "gate_code": READ_ONLY_GATE,
        "decision": "GRANT",
        "allowed_platforms": list(EXPECTED_ACTIVE),
        "scope": template.scope,
        "authorizer_reference": "HUMAN:CP62_SYNTHETIC_FIXTURE",
        "authorized_at": "2026-09-07T00:00:00Z",
        "expires_at": "2026-09-07T01:00:00Z",
        "authorization_evidence_sha256": sha256(b"PPOS_CP62_SYNTHETIC_AUTHORIZATION_EVIDENCE_V1").hexdigest(),
        "cp60_packet_id": cp61_contract.cp60_packet_id,
        "cp60_packet_hash": cp61_contract.cp60_packet_hash,
        "nonce": "cp62_synthetic_nonce_0001",
    }


def compile_authorization_receipt_validator(
    root: Path,
    policy: dict,
) -> AuthorizationReceiptValidatorContract:
    root = root.resolve()
    _validate_policy(policy)
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp61_policy = load_json(root / "config" / "control_plane_authorization_intake_policy.json")
    cp61 = compile_control_plane_authorization_intake(root, cp61_policy)
    validate_control_plane_authorization_intake_contract(cp61)
    if cp61.checkpoint != PARENT_INTAKE_CHECKPOINT or cp61.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CP61_PARENT_BINDING_DRIFT")

    submission = _synthetic_submission(cp61)
    shape = validate_authorization_submission_shape(cp61, submission)
    validate_authorization_shape_receipt(shape)
    receipt = compile_immutable_authorization_receipt(cp61, shape, synthetic_fixture=True)
    dry_run = simulate_control_promotion_dry_run(receipt)

    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_intake_checkpoint": PARENT_INTAKE_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp61_contract_id": cp61.contract_id,
        "cp61_contract_hash": cp61.contract_hash,
        "immutable_receipt_id": receipt.receipt_id,
        "immutable_receipt_hash": receipt.receipt_hash,
        "dry_run_id": dry_run.dry_run_id,
        "dry_run_hash": dry_run.dry_run_hash,
        "policy_sha256": _hash(policy),
        "cp61_policy_sha256": _hash(cp61_policy),
        "runtime_policy_sha256": _hash(runtime),
        "module_registry_sha256": _hash(registry),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "synthetic_fixture_validated": True,
        "immutable_receipt_validated": True,
        "control_promotion_dry_run_validated": True,
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
    contract_payload = dict(body)
    contract_payload["active_platforms"] = tuple(contract_payload["active_platforms"])
    contract_payload["blockers"] = tuple(contract_payload["blockers"])
    contract = AuthorizationReceiptValidatorContract(
        contract_id=f"cp62_contract_{contract_hash[:24]}",
        contract_hash=contract_hash,
        **contract_payload,
    )
    validate_authorization_receipt_validator_contract(contract)
    return contract


def validate_authorization_receipt_validator_contract(
    contract: AuthorizationReceiptValidatorContract,
) -> None:
    if contract.model_version != MODEL_VERSION or contract.engine_version != ENGINE_VERSION:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_VERSION_DRIFT")
    if contract.checkpoint != CHECKPOINT or contract.parent_intake_checkpoint != PARENT_INTAKE_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_CHECKPOINT_DRIFT")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_CONTROL_BINDING_DRIFT")
    if contract.active_platforms != EXPECTED_ACTIVE:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_PLATFORM_DRIFT")
    if contract.blockers != REQUIRED_BLOCKERS or contract.next_unit != NEXT_UNIT:
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_GATING_DRIFT")
    if not (
        contract.synthetic_fixture_validated
        and contract.immutable_receipt_validated
        and contract.control_promotion_dry_run_validated
        and contract.global_kill_switch_engaged
    ):
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_REQUIRED_PROOF_MISSING")
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
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_SIDE_EFFECT_DETECTED")
    payload = _payload_without_identity(contract.to_dict(), "contract_id", "contract_hash")
    expected_hash = _hash(payload)
    if contract.contract_hash != expected_hash or contract.contract_id != f"cp62_contract_{expected_hash[:24]}":
        raise AuthorizationReceiptValidatorHold("HOLD_CP62_CONTRACT_HASH_BINDING_INVALID")
