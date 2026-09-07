from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import re
from pathlib import Path
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .operator_pilot_handoff import (
    STATE as CP60_STATE,
    compile_operator_pilot_handoff,
    validate_operator_pilot_handoff_packet,
)

MODEL_VERSION = "PPOS_CONTROL_PLANE_AUTHORIZATION_INTAKE_V1"
ENGINE_VERSION = "ppos-control-plane-authorization-intake-v1.0.0"
STATE = "PASS_CP61_AUTHORIZATION_INTAKE_CONTRACT_LOCAL_ONLY_CONTROL_PROMOTION_HOLD"
CHECKPOINT = "CP61"
PARENT_HANDOFF_CHECKPOINT = "CP60"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP62_AUTHORIZATION_RECEIPT_VALIDATOR_AND_CONTROL_PROMOTION_DRY_RUN"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
AUTH_ID = re.compile(r"^auth_[A-Za-z0-9._:-]{8,96}$")
NONCE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")

EXPECTED_GATE_CODES = (
    "LIVE_READ_ONLY_CONNECTION_PROBE",
    "PILOT_PUBLISH",
)

REQUIRED_BLOCKERS = (
    "HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED",
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
)

SUBMISSION_FIELDS = (
    "authorization_id",
    "gate_code",
    "decision",
    "allowed_platforms",
    "scope",
    "authorizer_reference",
    "authorized_at",
    "expires_at",
    "authorization_evidence_sha256",
    "cp60_packet_id",
    "cp60_packet_hash",
    "nonce",
)

FORBIDDEN_FIELD_NAMES = {
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "credential",
    "credentials",
    "private_key",
}


class AuthorizationIntakeError(ValueError):
    pass


class AuthorizationIntakeHold(AuthorizationIntakeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AuthorizationIntakeTemplate:
    gate_code: str
    state: str
    decision_source: str
    allowed_platforms: tuple[str, ...]
    scope: str
    grant_effect: str
    live_evidence_prerequisite: str
    may_publish: bool
    may_deploy: bool

    def to_dict(self) -> dict:
        data = asdict(self)
        data["allowed_platforms"] = list(self.allowed_platforms)
        return data


@dataclass(frozen=True)
class AuthorizationShapeReceipt:
    receipt_id: str
    receipt_hash: str
    model_version: str
    authorization_id: str
    gate_code: str
    decision: str
    allowed_platforms: tuple[str, ...]
    scope: str
    authorizer_reference: str
    authorized_at: str
    expires_at: str
    authorization_evidence_sha256: str
    cp60_packet_id: str
    cp60_packet_hash: str
    nonce_sha256: str
    structurally_valid: bool = True
    authority_activated: bool = False
    control_promotion_allowed: bool = False
    live_probe_allowed: bool = False
    network_allowed: bool = False
    publish_allowed: bool = False
    deploy_allowed: bool = False
    state: str = "VALIDATED_SHAPE_ONLY_NO_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["allowed_platforms"] = list(self.allowed_platforms)
        return data


@dataclass(frozen=True)
class ControlPlaneAuthorizationIntakeContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_handoff_checkpoint: str
    parent_control_checkpoint: str
    cp60_packet_id: str
    cp60_packet_hash: str
    cp60_policy_sha256: str
    policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    intake_templates: tuple[AuthorizationIntakeTemplate, ...]
    blockers: tuple[str, ...]
    next_unit: str
    cp60_handoff_validated: bool = True
    intake_schema_ready: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_ingested: bool = False
    authorization_activated: bool = False
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
    self_authorization_performed: bool = False
    state: str = STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["intake_templates"] = [item.to_dict() for item in self.intake_templates]
        data["blockers"] = list(self.blockers)
        return data


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_CONTROL_PLANE_AUTHORIZATION_INTAKE_POLICY_V1":
        raise AuthorizationIntakeHold("HOLD_CP61_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M30_CONTROL_PLANE_AUTHORIZATION_INTAKE":
        raise AuthorizationIntakeHold("HOLD_CP61_POLICY_IDENTITY")
    if policy.get("parent_handoff_checkpoint") != PARENT_HANDOFF_CHECKPOINT:
        raise AuthorizationIntakeHold("HOLD_CP61_PARENT_HANDOFF_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationIntakeHold("HOLD_CP61_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise AuthorizationIntakeHold("HOLD_CP61_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise AuthorizationIntakeHold("HOLD_CP61_BLOCKER_SET_DRIFT")
    if policy.get("next_after_cp61") != NEXT_UNIT:
        raise AuthorizationIntakeHold("HOLD_CP61_NEXT_UNIT_DRIFT")

    contract = policy.get("intake_contract", {})
    required_true = (
        "offline_only",
        "exact_cp60_packet_binding_required",
        "global_control_checkpoint_must_remain_parent",
        "authorization_intake_schema_only",
        "authorization_decision_activation_forbidden",
        "authorization_must_be_explicit_external_human",
        "authorization_may_not_be_inferred",
        "authorization_must_be_scope_bound",
        "authorization_must_be_platform_bound",
        "authorization_must_be_evidence_hash_bound",
        "authorization_must_be_time_bound",
        "authorization_must_be_nonce_bound",
        "read_only_and_publish_gates_must_remain_separate",
        "publish_grant_requires_later_live_evidence_validation",
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
        "control_plane_promotion_execution_forbidden",
        "rollback_to_cp60_required",
    )
    if any(contract.get(key) is not True for key in required_true):
        raise AuthorizationIntakeHold("HOLD_CP61_INTAKE_GUARD_MISSING")

    schema = policy.get("submission_schema", {})
    if tuple(schema.get("required_fields", ())) != SUBMISSION_FIELDS:
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_FIELD_SET_DRIFT")
    if tuple(schema.get("allowed_decisions", ())) != ("GRANT", "DENY"):
        raise AuthorizationIntakeHold("HOLD_CP61_DECISION_SET_DRIFT")
    if schema.get("authorizer_reference_prefix") != "HUMAN:" or schema.get("authorization_id_prefix") != "auth_":
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_IDENTITY_RULE_DRIFT")
    if schema.get("minimum_nonce_length") != 16:
        raise AuthorizationIntakeHold("HOLD_CP61_NONCE_RULE_DRIFT")
    if any(schema.get(key) is not True for key in (
        "unknown_fields_forbidden",
        "raw_secret_fields_forbidden",
        "structural_validation_does_not_activate_authority",
    )):
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_GUARD_MISSING")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise AuthorizationIntakeHold("HOLD_CP61_AUTHORITY_NOT_ZERO")

    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise AuthorizationIntakeHold("HOLD_CP61_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise AuthorizationIntakeHold("HOLD_CP61_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise AuthorizationIntakeHold("HOLD_CP61_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise AuthorizationIntakeHold("HOLD_CP61_RUNTIME_ACTIVE_PLATFORM_DRIFT")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise AuthorizationIntakeHold("HOLD_CP61_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTROL_PROMOTION_MUST_REMAIN_HOLD")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M29_OPERATOR_PILOT_HANDOFF") != "CP60_OPERATOR_HANDOFF_READY_AUTHORIZATION_HOLD":
        raise AuthorizationIntakeHold("HOLD_CP61_CP60_MODULE_STATE_DRIFT")
    if states.get("M30_CONTROL_PLANE_AUTHORIZATION_INTAKE") != "CP61_AUTHORIZATION_INTAKE_CONTRACT_LOCAL_ONLY_CONTROL_PROMOTION_HOLD":
        raise AuthorizationIntakeHold("HOLD_CP61_MODULE_STATE_DRIFT")


def _compile_templates(policy: dict) -> tuple[AuthorizationIntakeTemplate, ...]:
    rows = policy.get("authorization_gates", [])
    if tuple(row.get("gate_code") for row in rows) != EXPECTED_GATE_CODES:
        raise AuthorizationIntakeHold("HOLD_CP61_GATE_SET_DRIFT")
    templates: list[AuthorizationIntakeTemplate] = []
    for row in rows:
        if row.get("default_state") != "AWAITING_EXTERNAL_HUMAN_DECISION":
            raise AuthorizationIntakeHold("HOLD_CP61_GATE_DEFAULT_STATE_DRIFT")
        if row.get("decision_source") != "EXTERNAL_HUMAN_ONLY":
            raise AuthorizationIntakeHold("HOLD_CP61_GATE_DECISION_SOURCE_DRIFT")
        if tuple(row.get("allowed_platforms", ())) != EXPECTED_ACTIVE:
            raise AuthorizationIntakeHold("HOLD_CP61_GATE_PLATFORM_DRIFT")
        if row.get("may_publish") is not False or row.get("may_deploy") is not False:
            raise AuthorizationIntakeHold("HOLD_CP61_GATE_AUTHORITY_TOO_BROAD")
        scope = str(row.get("scope", ""))
        grant_effect = str(row.get("grant_effect", ""))
        prerequisite = str(row.get("live_evidence_prerequisite", ""))
        if not scope or not grant_effect or not prerequisite:
            raise AuthorizationIntakeHold("HOLD_CP61_GATE_CONTRACT_INCOMPLETE")
        templates.append(
            AuthorizationIntakeTemplate(
                gate_code=str(row["gate_code"]),
                state="AWAITING_EXTERNAL_HUMAN_DECISION",
                decision_source="EXTERNAL_HUMAN_ONLY",
                allowed_platforms=EXPECTED_ACTIVE,
                scope=scope,
                grant_effect=grant_effect,
                live_evidence_prerequisite=prerequisite,
                may_publish=False,
                may_deploy=False,
            )
        )
    return tuple(templates)


def _contract_body(
    *,
    cp60_packet_id: str,
    cp60_packet_hash: str,
    cp60_policy_sha256: str,
    policy_sha256: str,
    runtime_policy_sha256: str,
    module_registry_sha256: str,
    intake_templates: tuple[AuthorizationIntakeTemplate, ...],
) -> dict:
    return {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_handoff_checkpoint": PARENT_HANDOFF_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp60_packet_id": cp60_packet_id,
        "cp60_packet_hash": cp60_packet_hash,
        "cp60_policy_sha256": cp60_policy_sha256,
        "policy_sha256": policy_sha256,
        "runtime_policy_sha256": runtime_policy_sha256,
        "module_registry_sha256": module_registry_sha256,
        "active_platforms": list(EXPECTED_ACTIVE),
        "intake_templates": [item.to_dict() for item in intake_templates],
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "cp60_handoff_validated": True,
        "intake_schema_ready": True,
        "global_kill_switch_engaged": True,
        "external_authorization_ingested": False,
        "authorization_activated": False,
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
        "self_authorization_performed": False,
        "state": STATE,
    }


def compile_control_plane_authorization_intake(
    root: Path,
    policy: dict,
) -> ControlPlaneAuthorizationIntakeContract:
    root = root.resolve()
    _validate_policy(policy)
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp60_policy = load_json(root / "config" / "operator_pilot_handoff_policy.json")
    cp60 = compile_operator_pilot_handoff(root, cp60_policy)
    validate_operator_pilot_handoff_packet(cp60)
    if cp60.state != CP60_STATE or cp60.checkpoint != PARENT_HANDOFF_CHECKPOINT:
        raise AuthorizationIntakeHold("HOLD_CP61_CP60_HANDOFF_INVALID")
    if cp60.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationIntakeHold("HOLD_CP61_CP60_CONTROL_BINDING_DRIFT")

    templates = _compile_templates(policy)
    cp60_policy_sha256 = _hash(cp60_policy)
    policy_sha256 = _hash(policy)
    runtime_policy_sha256 = _hash(runtime)
    module_registry_sha256 = _hash(registry)
    body = _contract_body(
        cp60_packet_id=cp60.packet_id,
        cp60_packet_hash=cp60.packet_hash,
        cp60_policy_sha256=cp60_policy_sha256,
        policy_sha256=policy_sha256,
        runtime_policy_sha256=runtime_policy_sha256,
        module_registry_sha256=module_registry_sha256,
        intake_templates=templates,
    )
    contract_hash = _hash(body)
    contract = ControlPlaneAuthorizationIntakeContract(
        contract_id="cai_" + contract_hash[:24],
        contract_hash=contract_hash,
        model_version=MODEL_VERSION,
        engine_version=ENGINE_VERSION,
        checkpoint=CHECKPOINT,
        parent_handoff_checkpoint=PARENT_HANDOFF_CHECKPOINT,
        parent_control_checkpoint=PARENT_CONTROL_CHECKPOINT,
        cp60_packet_id=cp60.packet_id,
        cp60_packet_hash=cp60.packet_hash,
        cp60_policy_sha256=cp60_policy_sha256,
        policy_sha256=policy_sha256,
        runtime_policy_sha256=runtime_policy_sha256,
        module_registry_sha256=module_registry_sha256,
        active_platforms=EXPECTED_ACTIVE,
        intake_templates=templates,
        blockers=REQUIRED_BLOCKERS,
        next_unit=NEXT_UNIT,
    )
    validate_control_plane_authorization_intake_contract(contract)
    return contract


def validate_control_plane_authorization_intake_contract(
    contract: ControlPlaneAuthorizationIntakeContract,
) -> None:
    if contract.model_version != MODEL_VERSION or contract.engine_version != ENGINE_VERSION:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_VERSION_DRIFT")
    if contract.checkpoint != CHECKPOINT or contract.parent_handoff_checkpoint != PARENT_HANDOFF_CHECKPOINT:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_CHECKPOINT_DRIFT")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_PARENT_CONTROL_DRIFT")
    if tuple(contract.active_platforms) != EXPECTED_ACTIVE:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_ACTIVE_PLATFORM_DRIFT")
    if tuple(item.gate_code for item in contract.intake_templates) != EXPECTED_GATE_CODES:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_GATE_DRIFT")
    if any(
        item.state != "AWAITING_EXTERNAL_HUMAN_DECISION"
        or item.decision_source != "EXTERNAL_HUMAN_ONLY"
        or item.may_publish
        or item.may_deploy
        for item in contract.intake_templates
    ):
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_TEMPLATE_AUTHORITY_DRIFT")
    if contract.blockers != REQUIRED_BLOCKERS or contract.next_unit != NEXT_UNIT:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_CONTROL_DRIFT")
    if not contract.cp60_handoff_validated or not contract.intake_schema_ready or not contract.global_kill_switch_engaged:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_PREREQUISITE_DRIFT")

    forbidden = (
        contract.external_authorization_ingested,
        contract.authorization_activated,
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
        contract.self_authorization_performed,
    )
    if any(forbidden):
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_EXTERNAL_OR_AUTHORITY_FORBIDDEN")

    hashes = (
        contract.contract_hash,
        contract.cp60_packet_hash,
        contract.cp60_policy_sha256,
        contract.policy_sha256,
        contract.runtime_policy_sha256,
        contract.module_registry_sha256,
    )
    if any(not HEX64.fullmatch(value) for value in hashes):
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_HASH_FORMAT")
    body = contract.to_dict()
    body.pop("contract_id")
    body.pop("contract_hash")
    if _hash(body) != contract.contract_hash:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_HASH_MISMATCH")
    if contract.contract_id != "cai_" + contract.contract_hash[:24]:
        raise AuthorizationIntakeHold("HOLD_CP61_CONTRACT_ID_MISMATCH")


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AuthorizationIntakeHold(f"HOLD_CP61_{field}_MUST_BE_UTC_Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AuthorizationIntakeHold(f"HOLD_CP61_{field}_INVALID") from exc
    return parsed


def validate_authorization_submission_shape(
    contract: ControlPlaneAuthorizationIntakeContract,
    submission: dict,
) -> AuthorizationShapeReceipt:
    validate_control_plane_authorization_intake_contract(contract)
    if not isinstance(submission, dict):
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_NOT_OBJECT")
    keys = tuple(submission.keys())
    if set(keys) != set(SUBMISSION_FIELDS):
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_FIELD_SET_INVALID")
    if any(str(key).lower() in FORBIDDEN_FIELD_NAMES for key in keys):
        raise AuthorizationIntakeHold("HOLD_CP61_RAW_SECRET_FIELD_FORBIDDEN")

    authorization_id = submission.get("authorization_id")
    if not isinstance(authorization_id, str) or not AUTH_ID.fullmatch(authorization_id):
        raise AuthorizationIntakeHold("HOLD_CP61_AUTHORIZATION_ID_INVALID")
    decision = submission.get("decision")
    if decision not in ("GRANT", "DENY"):
        raise AuthorizationIntakeHold("HOLD_CP61_DECISION_INVALID")
    gate_code = submission.get("gate_code")
    template = next((item for item in contract.intake_templates if item.gate_code == gate_code), None)
    if template is None:
        raise AuthorizationIntakeHold("HOLD_CP61_GATE_CODE_INVALID")
    platforms = submission.get("allowed_platforms")
    if not isinstance(platforms, list) or not platforms or len(platforms) != len(set(platforms)):
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_PLATFORM_SET_INVALID")
    if any(platform not in EXPECTED_ACTIVE for platform in platforms):
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_PLATFORM_OUTSIDE_ACTIVE_LANES")
    if submission.get("scope") != template.scope:
        raise AuthorizationIntakeHold("HOLD_CP61_SUBMISSION_SCOPE_MISMATCH")
    authorizer_reference = submission.get("authorizer_reference")
    if not isinstance(authorizer_reference, str) or not authorizer_reference.startswith("HUMAN:") or len(authorizer_reference) <= 6:
        raise AuthorizationIntakeHold("HOLD_CP61_AUTHORIZER_REFERENCE_INVALID")
    evidence_sha = submission.get("authorization_evidence_sha256")
    if not isinstance(evidence_sha, str) or not HEX64.fullmatch(evidence_sha):
        raise AuthorizationIntakeHold("HOLD_CP61_AUTHORIZATION_EVIDENCE_HASH_INVALID")
    if submission.get("cp60_packet_id") != contract.cp60_packet_id or submission.get("cp60_packet_hash") != contract.cp60_packet_hash:
        raise AuthorizationIntakeHold("HOLD_CP61_CP60_BINDING_MISMATCH")
    nonce = submission.get("nonce")
    if not isinstance(nonce, str) or not NONCE.fullmatch(nonce):
        raise AuthorizationIntakeHold("HOLD_CP61_NONCE_INVALID")

    authorized_at = submission.get("authorized_at")
    expires_at = submission.get("expires_at")
    authorized_dt = _parse_utc(authorized_at, "AUTHORIZED_AT")
    expires_dt = _parse_utc(expires_at, "EXPIRES_AT")
    if expires_dt <= authorized_dt:
        raise AuthorizationIntakeHold("HOLD_CP61_AUTHORIZATION_WINDOW_INVALID")

    body = {
        "model_version": MODEL_VERSION,
        "authorization_id": authorization_id,
        "gate_code": gate_code,
        "decision": decision,
        "allowed_platforms": list(platforms),
        "scope": template.scope,
        "authorizer_reference": authorizer_reference,
        "authorized_at": authorized_at,
        "expires_at": expires_at,
        "authorization_evidence_sha256": evidence_sha,
        "cp60_packet_id": contract.cp60_packet_id,
        "cp60_packet_hash": contract.cp60_packet_hash,
        "nonce_sha256": sha256(nonce.encode("utf-8")).hexdigest(),
        "structurally_valid": True,
        "authority_activated": False,
        "control_promotion_allowed": False,
        "live_probe_allowed": False,
        "network_allowed": False,
        "publish_allowed": False,
        "deploy_allowed": False,
        "state": "VALIDATED_SHAPE_ONLY_NO_AUTHORITY",
    }
    receipt_hash = _hash(body)
    receipt = AuthorizationShapeReceipt(
        receipt_id="asr_" + receipt_hash[:24],
        receipt_hash=receipt_hash,
        model_version=MODEL_VERSION,
        authorization_id=authorization_id,
        gate_code=gate_code,
        decision=decision,
        allowed_platforms=tuple(platforms),
        scope=template.scope,
        authorizer_reference=authorizer_reference,
        authorized_at=authorized_at,
        expires_at=expires_at,
        authorization_evidence_sha256=evidence_sha,
        cp60_packet_id=contract.cp60_packet_id,
        cp60_packet_hash=contract.cp60_packet_hash,
        nonce_sha256=body["nonce_sha256"],
    )
    validate_authorization_shape_receipt(receipt)
    return receipt


def validate_authorization_shape_receipt(receipt: AuthorizationShapeReceipt) -> None:
    if receipt.model_version != MODEL_VERSION:
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_VERSION_DRIFT")
    if receipt.gate_code not in EXPECTED_GATE_CODES or receipt.decision not in ("GRANT", "DENY"):
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_DECISION_DRIFT")
    if not receipt.structurally_valid:
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_NOT_VALID")
    if any((
        receipt.authority_activated,
        receipt.control_promotion_allowed,
        receipt.live_probe_allowed,
        receipt.network_allowed,
        receipt.publish_allowed,
        receipt.deploy_allowed,
    )):
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_AUTHORITY_FORBIDDEN")
    if receipt.state != "VALIDATED_SHAPE_ONLY_NO_AUTHORITY":
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_STATE_DRIFT")
    if any(not HEX64.fullmatch(value) for value in (
        receipt.receipt_hash,
        receipt.authorization_evidence_sha256,
        receipt.cp60_packet_hash,
        receipt.nonce_sha256,
    )):
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_HASH_FORMAT")
    body = receipt.to_dict()
    body.pop("receipt_id")
    body.pop("receipt_hash")
    if _hash(body) != receipt.receipt_hash:
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_HASH_MISMATCH")
    if receipt.receipt_id != "asr_" + receipt.receipt_hash[:24]:
        raise AuthorizationIntakeHold("HOLD_CP61_SHAPE_RECEIPT_ID_MISMATCH")


def render_control_plane_authorization_intake_json(
    contract: ControlPlaneAuthorizationIntakeContract,
) -> str:
    validate_control_plane_authorization_intake_contract(contract)
    return canonical_json(contract.to_dict())
