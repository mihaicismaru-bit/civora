from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_execution_admission import AUTHORIZATION_GATE
from .live_read_only_probe_single_session_harness import (
    CHECKPOINT as CP66_CHECKPOINT,
    STATE as CP66_STATE,
    LiveReadOnlyProbeSingleSessionHarnessContract,
    compile_live_read_only_probe_single_session_harness,
    validate_live_read_only_probe_single_session_harness_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authorized-session-request-v1.0.0"
STATE = "PASS_CP67_AUTHORIZED_SESSION_REQUEST_PACKET_HANDOFF_LOCAL_ONLY_AUTHORIZATION_NOT_GRANTED_LIVE_HOLD"
CHECKPOINT = "CP67"
PARENT_SINGLE_SESSION_HARNESS_CHECKPOINT = "CP66"
PARENT_CONTROL_CHECKPOINT = "CP58"
REQUESTED_SCOPE = "READ_ONLY_METADATA_PROBE"
REQUESTED_SESSION_COUNT = 1
ALLOWED_METHODS = ("GET",)
DECISION_VALUES = ("GRANT", "DENY")
FUTURE_RECEIPT_SCHEMA = "PPOS_CP68_LIVE_READ_ONLY_SESSION_AUTHORIZATION_RECEIPT_V1"
NEXT_UNIT = "CP68_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT_INTAKE_AND_VALIDATOR_DRY_RUN"

REQUIRED_HANDOFF_FIELDS = (
    "decision",
    "scope",
    "platform_subset",
    "valid_from_utc",
    "valid_until_utc",
    "human_reference_sha256",
    "evidence_sha256",
    "nonce",
)

REQUIRED_BLOCKERS = (
    "HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED",
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
    "HOLD_CP67_REQUEST_IS_NOT_AUTHORIZATION",
    "HOLD_CP67_OPERATOR_DECISION_NOT_PRESENT",
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
        "account_id",
        "page_id",
        "instagram_account_id",
        "threads_user_id",
    }
)


class LiveReadOnlyProbeAuthorizedSessionRequestError(ValueError):
    pass


class LiveReadOnlyProbeAuthorizedSessionRequestHold(
    LiveReadOnlyProbeAuthorizedSessionRequestError
):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AuthorizedSessionRequestPacket:
    request_id: str
    request_hash: str
    model_version: str
    checkpoint: str
    parent_control_checkpoint: str
    cp66_contract_id: str
    cp66_contract_hash: str
    cp66_harness_run_id: str
    cp66_harness_run_hash: str
    active_platforms: tuple[str, ...]
    authorization_gate: str
    requested_scope: str
    method_allowlist: tuple[str, ...]
    requested_session_count: int
    authorization_state: str
    external_human_authorization_required: bool = True
    request_is_not_authorization: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_present: bool = False
    authorization_granted: bool = False
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
    immutable: bool = True
    state: str = "REQUEST_PACKET_READY_NOT_AUTHORIZATION_NO_LIVE_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["method_allowlist"] = list(self.method_allowlist)
        return data


@dataclass(frozen=True)
class OperatorAuthorizationHandoff:
    handoff_id: str
    handoff_hash: str
    model_version: str
    checkpoint: str
    request_id: str
    request_hash: str
    authorization_gate: str
    requested_scope: str
    active_platforms: tuple[str, ...]
    decision_values: tuple[str, ...]
    required_fields: tuple[str, ...]
    future_receipt_schema: str
    operator_only: bool = True
    decision_required: bool = True
    external_human_authorization_required: bool = True
    request_is_not_authorization: bool = True
    no_grant_material_embedded: bool = True
    no_automatic_promotion: bool = True
    authorization_present: bool = False
    authorization_granted: bool = False
    network_allowed: bool = False
    live_probe_allowed: bool = False
    account_connection_allowed: bool = False
    publish_allowed: bool = False
    external_write_allowed: bool = False
    deploy_allowed: bool = False
    authority_activated: bool = False
    global_kill_switch_engaged: bool = True
    immutable: bool = True
    state: str = "OPERATOR_HANDOFF_READY_DECISION_ABSENT_NO_LIVE_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["decision_values"] = list(self.decision_values)
        data["required_fields"] = list(self.required_fields)
        return data


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorizedSessionRequestContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_single_session_harness_checkpoint: str
    parent_control_checkpoint: str
    cp66_contract_id: str
    cp66_contract_hash: str
    cp66_harness_run_id: str
    cp66_harness_run_hash: str
    request_id: str
    request_hash: str
    handoff_id: str
    handoff_hash: str
    policy_sha256: str
    cp66_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    authorization_gate: str
    requested_scope: str
    method_allowlist: tuple[str, ...]
    requested_session_count: int
    blockers: tuple[str, ...]
    next_unit: str
    exact_cp66_binding_validated: bool = True
    request_packet_validated: bool = True
    operator_handoff_validated: bool = True
    global_kill_switch_engaged: bool = True
    external_human_authorization_required: bool = True
    request_is_not_authorization: bool = True
    external_authorization_ingested: bool = False
    authorization_granted: bool = False
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
        data["method_allowlist"] = list(self.method_allowlist)
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
            if str(key).lower() in SENSITIVE_KEYS:
                raise LiveReadOnlyProbeAuthorizedSessionRequestHold(
                    "HOLD_CP67_SENSITIVE_OR_ACCOUNT_FIELD_FORBIDDEN"
                )
            _validate_no_sensitive_or_live_material(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_no_sensitive_or_live_material(child)
    elif isinstance(value, str):
        lowered = value.lower()
        if "://" in value or "bearer " in lowered or "authorization:" in lowered:
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold(
                "HOLD_CP67_RAW_URL_OR_CREDENTIAL_MATERIAL_FORBIDDEN"
            )


def _validate_policy(policy: dict) -> None:
    _validate_no_sensitive_or_live_material(policy)
    if policy.get("schema_version") != "PPOS_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST_POLICY_V1":
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M36_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST":
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_POLICY_IDENTITY")
    if policy.get("parent_single_session_harness_checkpoint") != PARENT_SINGLE_SESSION_HARNESS_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_PARENT_CP66_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_BLOCKER_SET_DRIFT")
    if policy.get("rollback_target") != PARENT_SINGLE_SESSION_HARNESS_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_ROLLBACK_TARGET_DRIFT")
    if policy.get("next_after_cp67") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_NEXT_UNIT_DRIFT")

    packet = policy.get("request_packet", {})
    required_true = (
        "local_contract_only",
        "exact_cp66_contract_binding_required",
        "exact_cp66_harness_run_binding_required",
        "request_is_not_authorization",
        "external_human_authorization_required",
        "authorization_must_remain_absent_in_cp67",
        "canonical_json_required",
        "sha256_binding_required",
        "immutable_packet_required",
        "raw_credentials_forbidden",
        "raw_urls_forbidden",
        "real_account_identifiers_forbidden",
        "secret_resolution_forbidden",
        "environment_read_forbidden",
        "keychain_read_forbidden",
        "oauth_forbidden",
        "real_account_lookup_forbidden",
        "account_connection_forbidden",
        "network_forbidden",
        "live_probe_execution_forbidden",
        "publish_forbidden",
        "external_write_forbidden",
        "control_plane_promotion_forbidden",
        "deploy_forbidden",
        "paid_service_forbidden",
        "global_kill_switch_must_remain_engaged",
    )
    if any(packet.get(key) is not True for key in required_true):
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_GUARD_MISSING")
    if packet.get("authorization_gate_must_equal") != AUTHORIZATION_GATE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_AUTHORIZATION_GATE_DRIFT")
    if packet.get("requested_scope_must_equal") != REQUESTED_SCOPE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUESTED_SCOPE_DRIFT")
    if packet.get("requested_session_count_must_equal") != REQUESTED_SESSION_COUNT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_SESSION_COUNT_DRIFT")
    if tuple(packet.get("method_allowlist", ())) != ALLOWED_METHODS:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_METHOD_ALLOWLIST_DRIFT")

    handoff = policy.get("operator_handoff", {})
    if any(
        handoff.get(key) is not True
        for key in (
            "operator_only",
            "decision_required",
            "explicit_scope_required",
            "platform_subset_required",
            "utc_validity_window_required",
            "human_reference_hash_required",
            "evidence_sha256_required",
            "nonce_required",
            "no_grant_material_embedded_in_cp67",
            "no_automatic_promotion",
        )
    ):
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_GUARD_MISSING")
    if tuple(handoff.get("decision_values", ())) != DECISION_VALUES:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_DECISION_VALUES_DRIFT")
    if handoff.get("future_receipt_schema") != FUTURE_RECEIPT_SCHEMA:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_FUTURE_RECEIPT_SCHEMA_DRIFT")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_RUNTIME_ACTIVE_PLATFORM_DRIFT")
    for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled"):
        if runtime.get(key) is not False:
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_RUNTIME_LIVE_BOUNDARY_MUST_REMAIN_DISABLED")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTROL_PROMOTION_MUST_REMAIN_HOLD")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M35_LIVE_READ_ONLY_PROBE_SINGLE_SESSION_HARNESS") != (
        "CP66_SINGLE_SESSION_EXECUTION_HARNESS_DRY_RUN_MOCK_ONLY_LIVE_HOLD"
    ):
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CP66_MODULE_STATE_DRIFT")
    if states.get("M36_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST") != (
        "CP67_AUTHORIZED_SESSION_REQUEST_PACKET_HANDOFF_LOCAL_ONLY_AUTHORIZATION_NOT_GRANTED_LIVE_HOLD"
    ):
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_MODULE_STATE_DRIFT")


def build_authorized_session_request_packet(
    cp66: LiveReadOnlyProbeSingleSessionHarnessContract,
) -> AuthorizedSessionRequestPacket:
    validate_live_read_only_probe_single_session_harness_contract(cp66)
    if cp66.checkpoint != CP66_CHECKPOINT or cp66.state != CP66_STATE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CP66_CONTRACT_STATE_DRIFT")
    if cp66.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CP66_CONTROL_BINDING_DRIFT")
    if tuple(cp66.active_platforms) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CP66_ACTIVE_PLATFORM_DRIFT")
    if not cp66.global_kill_switch_engaged or cp66.authority_activated:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CP66_AUTHORITY_BOUNDARY_DRIFT")
    for field in (
        "external_authorization_ingested",
        "secret_reference_resolved",
        "environment_read",
        "keychain_read",
        "oauth_attempted",
        "real_account_lookup_attempted",
        "account_connected",
        "network_allowed",
        "network_attempted",
        "live_probe_allowed",
        "live_probe_attempted",
        "publish_allowed",
        "publish_attempted",
        "external_write_allowed",
        "external_write_performed",
        "control_plane_promoted",
        "deploy_allowed",
        "deploy_performed",
        "paid_service_used",
    ):
        if getattr(cp66, field):
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CP66_MUST_REMAIN_ZERO_AUTHORITY")

    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp66_contract_id": cp66.contract_id,
        "cp66_contract_hash": cp66.contract_hash,
        "cp66_harness_run_id": cp66.harness_run_id,
        "cp66_harness_run_hash": cp66.harness_run_hash,
        "active_platforms": list(EXPECTED_ACTIVE),
        "authorization_gate": AUTHORIZATION_GATE,
        "requested_scope": REQUESTED_SCOPE,
        "method_allowlist": list(ALLOWED_METHODS),
        "requested_session_count": REQUESTED_SESSION_COUNT,
        "authorization_state": "REQUEST_NOT_GRANTED",
        "external_human_authorization_required": True,
        "request_is_not_authorization": True,
        "global_kill_switch_engaged": True,
        "external_authorization_present": False,
        "authorization_granted": False,
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
        "immutable": True,
        "state": "REQUEST_PACKET_READY_NOT_AUTHORIZATION_NO_LIVE_AUTHORITY",
    }
    digest = _hash(body)
    packet = AuthorizedSessionRequestPacket(
        request_id=f"cp67_request_{digest[:24]}",
        request_hash=digest,
        **{key: value for key, value in body.items() if key not in ("active_platforms", "method_allowlist")},
        active_platforms=EXPECTED_ACTIVE,
        method_allowlist=ALLOWED_METHODS,
    )
    validate_authorized_session_request_packet(packet, cp66)
    return packet


def validate_authorized_session_request_packet(
    packet: AuthorizedSessionRequestPacket,
    cp66: LiveReadOnlyProbeSingleSessionHarnessContract,
) -> None:
    validate_live_read_only_probe_single_session_harness_contract(cp66)
    if packet.model_version != MODEL_VERSION or packet.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_VERSION_OR_CHECKPOINT_DRIFT")
    if packet.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_CONTROL_BINDING_DRIFT")
    if packet.cp66_contract_id != cp66.contract_id or packet.cp66_contract_hash != cp66.contract_hash:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_CP66_BINDING_DRIFT")
    if packet.cp66_harness_run_id != cp66.harness_run_id or packet.cp66_harness_run_hash != cp66.harness_run_hash:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_HARNESS_RUN_BINDING_DRIFT")
    if packet.active_platforms != EXPECTED_ACTIVE or packet.method_allowlist != ALLOWED_METHODS:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_SCOPE_OR_METHOD_DRIFT")
    if packet.authorization_gate != AUTHORIZATION_GATE or packet.requested_scope != REQUESTED_SCOPE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_GATE_OR_SCOPE_DRIFT")
    if packet.requested_session_count != REQUESTED_SESSION_COUNT or packet.authorization_state != "REQUEST_NOT_GRANTED":
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_CARDINALITY_OR_STATE_DRIFT")
    required_true = (
        "external_human_authorization_required",
        "request_is_not_authorization",
        "global_kill_switch_engaged",
        "immutable",
    )
    if any(getattr(packet, field) is not True for field in required_true):
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_REQUIRED_GUARD_FALSE")
    required_false = (
        "external_authorization_present",
        "authorization_granted",
        "secret_reference_resolved",
        "environment_read",
        "keychain_read",
        "oauth_attempted",
        "real_account_lookup_attempted",
        "account_connected",
        "network_allowed",
        "network_attempted",
        "live_probe_allowed",
        "live_probe_attempted",
        "publish_allowed",
        "publish_attempted",
        "external_write_allowed",
        "external_write_performed",
        "control_plane_promoted",
        "deploy_allowed",
        "deploy_performed",
        "paid_service_used",
        "authority_activated",
    )
    if any(getattr(packet, field) is not False for field in required_false):
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_LIVE_AUTHORITY_MUST_REMAIN_ZERO")
    body = _payload_without_identity(packet.to_dict(), "request_id", "request_hash")
    expected_hash = _hash(body)
    if packet.request_hash != expected_hash or packet.request_id != f"cp67_request_{expected_hash[:24]}":
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_REQUEST_HASH_BINDING_INVALID")


def build_operator_authorization_handoff(
    packet: AuthorizedSessionRequestPacket,
    cp66: LiveReadOnlyProbeSingleSessionHarnessContract,
) -> OperatorAuthorizationHandoff:
    validate_authorized_session_request_packet(packet, cp66)
    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "request_id": packet.request_id,
        "request_hash": packet.request_hash,
        "authorization_gate": AUTHORIZATION_GATE,
        "requested_scope": REQUESTED_SCOPE,
        "active_platforms": list(EXPECTED_ACTIVE),
        "decision_values": list(DECISION_VALUES),
        "required_fields": list(REQUIRED_HANDOFF_FIELDS),
        "future_receipt_schema": FUTURE_RECEIPT_SCHEMA,
        "operator_only": True,
        "decision_required": True,
        "external_human_authorization_required": True,
        "request_is_not_authorization": True,
        "no_grant_material_embedded": True,
        "no_automatic_promotion": True,
        "authorization_present": False,
        "authorization_granted": False,
        "network_allowed": False,
        "live_probe_allowed": False,
        "account_connection_allowed": False,
        "publish_allowed": False,
        "external_write_allowed": False,
        "deploy_allowed": False,
        "authority_activated": False,
        "global_kill_switch_engaged": True,
        "immutable": True,
        "state": "OPERATOR_HANDOFF_READY_DECISION_ABSENT_NO_LIVE_AUTHORITY",
    }
    digest = _hash(body)
    handoff = OperatorAuthorizationHandoff(
        handoff_id=f"cp67_handoff_{digest[:24]}",
        handoff_hash=digest,
        **{key: value for key, value in body.items() if key not in ("active_platforms", "decision_values", "required_fields")},
        active_platforms=EXPECTED_ACTIVE,
        decision_values=DECISION_VALUES,
        required_fields=REQUIRED_HANDOFF_FIELDS,
    )
    validate_operator_authorization_handoff(handoff, packet, cp66)
    return handoff


def validate_operator_authorization_handoff(
    handoff: OperatorAuthorizationHandoff,
    packet: AuthorizedSessionRequestPacket,
    cp66: LiveReadOnlyProbeSingleSessionHarnessContract,
) -> None:
    validate_authorized_session_request_packet(packet, cp66)
    if handoff.model_version != MODEL_VERSION or handoff.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_VERSION_OR_CHECKPOINT_DRIFT")
    if handoff.request_id != packet.request_id or handoff.request_hash != packet.request_hash:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_REQUEST_BINDING_DRIFT")
    if handoff.authorization_gate != AUTHORIZATION_GATE or handoff.requested_scope != REQUESTED_SCOPE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_GATE_OR_SCOPE_DRIFT")
    if handoff.active_platforms != EXPECTED_ACTIVE or handoff.decision_values != DECISION_VALUES:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_PLATFORM_OR_DECISION_DRIFT")
    if handoff.required_fields != REQUIRED_HANDOFF_FIELDS or handoff.future_receipt_schema != FUTURE_RECEIPT_SCHEMA:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_SCHEMA_DRIFT")
    for field in (
        "operator_only",
        "decision_required",
        "external_human_authorization_required",
        "request_is_not_authorization",
        "no_grant_material_embedded",
        "no_automatic_promotion",
        "global_kill_switch_engaged",
        "immutable",
    ):
        if getattr(handoff, field) is not True:
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_REQUIRED_GUARD_FALSE")
    for field in (
        "authorization_present",
        "authorization_granted",
        "network_allowed",
        "live_probe_allowed",
        "account_connection_allowed",
        "publish_allowed",
        "external_write_allowed",
        "deploy_allowed",
        "authority_activated",
    ):
        if getattr(handoff, field) is not False:
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_LIVE_AUTHORITY_MUST_REMAIN_ZERO")
    body = _payload_without_identity(handoff.to_dict(), "handoff_id", "handoff_hash")
    expected_hash = _hash(body)
    if handoff.handoff_hash != expected_hash or handoff.handoff_id != f"cp67_handoff_{expected_hash[:24]}":
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_HANDOFF_HASH_BINDING_INVALID")


def compile_live_read_only_probe_authorized_session_request(
    root: Path,
    policy: dict,
) -> LiveReadOnlyProbeAuthorizedSessionRequestContract:
    root = root.resolve()
    _validate_policy(policy)
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp66_policy_path = root / "config" / "live_read_only_probe_single_session_harness_policy.json"
    cp66_policy = load_json(cp66_policy_path)
    cp66 = compile_live_read_only_probe_single_session_harness(root, cp66_policy)
    validate_live_read_only_probe_single_session_harness_contract(cp66)

    packet = build_authorized_session_request_packet(cp66)
    handoff = build_operator_authorization_handoff(packet, cp66)

    policy_path = root / "config" / "live_read_only_probe_authorized_session_request_policy.json"
    runtime_path = root / "config" / "runtime_policy.json"
    registry_path = root / "config" / "module_registry.json"
    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_single_session_harness_checkpoint": PARENT_SINGLE_SESSION_HARNESS_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp66_contract_id": cp66.contract_id,
        "cp66_contract_hash": cp66.contract_hash,
        "cp66_harness_run_id": cp66.harness_run_id,
        "cp66_harness_run_hash": cp66.harness_run_hash,
        "request_id": packet.request_id,
        "request_hash": packet.request_hash,
        "handoff_id": handoff.handoff_id,
        "handoff_hash": handoff.handoff_hash,
        "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        "cp66_policy_sha256": sha256(cp66_policy_path.read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256(runtime_path.read_bytes()).hexdigest(),
        "module_registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "authorization_gate": AUTHORIZATION_GATE,
        "requested_scope": REQUESTED_SCOPE,
        "method_allowlist": list(ALLOWED_METHODS),
        "requested_session_count": REQUESTED_SESSION_COUNT,
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "exact_cp66_binding_validated": True,
        "request_packet_validated": True,
        "operator_handoff_validated": True,
        "global_kill_switch_engaged": True,
        "external_human_authorization_required": True,
        "request_is_not_authorization": True,
        "external_authorization_ingested": False,
        "authorization_granted": False,
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
    digest = _hash(body)
    contract = LiveReadOnlyProbeAuthorizedSessionRequestContract(
        contract_id=f"cp67_contract_{digest[:24]}",
        contract_hash=digest,
        **{key: value for key, value in body.items() if key not in ("active_platforms", "method_allowlist", "blockers")},
        active_platforms=EXPECTED_ACTIVE,
        method_allowlist=ALLOWED_METHODS,
        blockers=REQUIRED_BLOCKERS,
    )
    validate_live_read_only_probe_authorized_session_request_contract(contract)
    return contract


def validate_live_read_only_probe_authorized_session_request_contract(
    contract: LiveReadOnlyProbeAuthorizedSessionRequestContract,
) -> None:
    if contract.model_version != MODEL_VERSION or contract.engine_version != ENGINE_VERSION:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_VERSION_DRIFT")
    if contract.checkpoint != CHECKPOINT or contract.parent_single_session_harness_checkpoint != PARENT_SINGLE_SESSION_HARNESS_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_CHECKPOINT_DRIFT")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_CONTROL_BINDING_DRIFT")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.method_allowlist != ALLOWED_METHODS:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_SCOPE_OR_METHOD_DRIFT")
    if contract.authorization_gate != AUTHORIZATION_GATE or contract.requested_scope != REQUESTED_SCOPE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_GATE_OR_SCOPE_DRIFT")
    if contract.requested_session_count != REQUESTED_SESSION_COUNT:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_SESSION_COUNT_DRIFT")
    if contract.blockers != REQUIRED_BLOCKERS or contract.next_unit != NEXT_UNIT or contract.state != STATE:
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_STATE_OR_BLOCKER_DRIFT")
    for field in (
        "exact_cp66_binding_validated",
        "request_packet_validated",
        "operator_handoff_validated",
        "global_kill_switch_engaged",
        "external_human_authorization_required",
        "request_is_not_authorization",
    ):
        if getattr(contract, field) is not True:
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_REQUIRED_GUARD_FALSE")
    for field in (
        "external_authorization_ingested",
        "authorization_granted",
        "secret_reference_resolved",
        "environment_read",
        "keychain_read",
        "oauth_attempted",
        "real_account_lookup_attempted",
        "account_connected",
        "network_allowed",
        "network_attempted",
        "live_probe_allowed",
        "live_probe_attempted",
        "publish_allowed",
        "publish_attempted",
        "external_write_allowed",
        "external_write_performed",
        "control_plane_promoted",
        "deploy_allowed",
        "deploy_performed",
        "paid_service_used",
        "authority_activated",
    ):
        if getattr(contract, field) is not False:
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_LIVE_AUTHORITY_MUST_REMAIN_ZERO")
    for digest in (
        contract.contract_hash,
        contract.cp66_contract_hash,
        contract.cp66_harness_run_hash,
        contract.request_hash,
        contract.handoff_hash,
        contract.policy_sha256,
        contract.cp66_policy_sha256,
        contract.runtime_policy_sha256,
        contract.module_registry_sha256,
    ):
        if not _is_hex64(digest):
            raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_DIGEST_INVALID")
    body = _payload_without_identity(contract.to_dict(), "contract_id", "contract_hash")
    expected_hash = _hash(body)
    if contract.contract_hash != expected_hash or contract.contract_id != f"cp67_contract_{expected_hash[:24]}":
        raise LiveReadOnlyProbeAuthorizedSessionRequestHold("HOLD_CP67_CONTRACT_HASH_BINDING_INVALID")
