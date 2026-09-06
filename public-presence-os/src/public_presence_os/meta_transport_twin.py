from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import hmac
import re

from .connection_preflight import SyntheticPreflightReceipt, validate_synthetic_preflight_receipt
from .control import EXPECTED_ACTIVE, canonical_json
from .meta_adapters import (
    API_VERSION_REF,
    CONTAINER_ID_REF,
    DESTINATION_REF,
    STAGING_URL_REF,
    OfflineRequestPlan,
    RequestStep,
    validate_request_plan,
)
from .operator_provisioning import (
    OperatorProvisioningPacket,
    validate_operator_provisioning_packet,
)

TRANSPORT_TWIN_MODEL_VERSION = "PPOS_META_TRANSPORT_TEST_TWIN_V1"
TRANSPORT_TWIN_ENGINE_VERSION = "ppos-meta-transport-test-twin-v1.0.0"
TWIN_STATE = "PASS_SYNTHETIC_TRANSPORT_TWIN_ONLY"
SIGNATURE_SCOPE = "TWIN_INTERNAL_HMAC_SHA256_ONLY"
AUTH_SCOPE = "SYNTHETIC_BEARER_BOUNDARY_ONLY"
IDEMPOTENCY_SCOPE = "LOCAL_DETERMINISTIC_KEY_ONLY"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TEST_DESTINATION = re.compile(r"^TEST_DESTINATION_[A-Z0-9_]{4,96}$")
TEST_API_VERSION = re.compile(r"^TEST_API_VERSION_[A-Z0-9_]{2,64}$")
TEST_TOKEN = re.compile(r"^TEST_ONLY_TOKEN_[A-Za-z0-9._:-]{12,200}$")
TEST_SIGNING_SECRET = re.compile(r"^TEST_ONLY_SIGNING_SECRET_[A-Za-z0-9._:-]{12,200}$")
INVALID_STAGING_PREFIX = "https://example.invalid/"

RETRY_SUCCESS = "SUCCESS_SYNTHETIC"
RETRY_TRANSIENT = "RETRY_TRANSIENT_SYNTHETIC"
RETRY_RATE_LIMIT = "RETRY_RATE_LIMIT_SYNTHETIC"
NO_RETRY_AUTH = "NO_RETRY_AUTH_SYNTHETIC"
NO_RETRY_CLIENT = "NO_RETRY_CLIENT_SYNTHETIC"
HOLD_UNKNOWN = "HOLD_UNKNOWN_SYNTHETIC_STATUS"


class MetaTransportTwinError(ValueError):
    pass


class MetaTransportTwinHold(MetaTransportTwinError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SyntheticCredentialEnvelope:
    auth_reference_kind: str
    bearer_token: str
    signing_secret: str
    marker: str = "PPOS_TEST_ONLY"


@dataclass(frozen=True)
class SyntheticTransportBinding:
    destination_id: str
    api_version: str
    staging_url: str | None = None


@dataclass(frozen=True)
class TwinWireRequest:
    ordinal: int
    operation: str
    method: str
    logical_host: str
    resolved_path: str
    body: tuple[tuple[str, str], ...]
    output_id_ref: str | None
    authorization_scheme: str
    authorization_value_sha256: str
    internal_signature_sha256: str
    request_hash: str
    idempotency_key: str
    auth_scope: str = AUTH_SCOPE
    signature_scope: str = SIGNATURE_SCOPE
    idempotency_scope: str = IDEMPOTENCY_SCOPE
    credential_material_serialized: bool = False
    wire_signature_header_included: bool = False
    wire_idempotency_header_included: bool = False
    network_target_materialized: bool = False
    network_attempted: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["body"] = [{"key": key, "value": value} for key, value in self.body]
        return data


@dataclass(frozen=True)
class TwinTransportReceipt:
    twin_id: str
    twin_hash: str
    model_version: str
    engine_version: str
    plan_id: str
    plan_hash: str
    preflight_receipt_id: str
    preflight_receipt_hash: str
    provisioning_packet_id: str
    provisioning_packet_hash: str
    platform: str
    mode: str
    destination_binding_sha256: str
    api_version_binding_sha256: str
    staging_binding_sha256: str | None
    auth_reference_kind: str
    request_hashes: tuple[str, ...]
    requests: tuple[TwinWireRequest, ...]
    retry_classifier_version: str = "PPOS_SYNTHETIC_RETRY_CLASSIFIER_V1"
    transport_mode: str = "SYNTHETIC_TEST_TWIN_ONLY"
    synthetic_credentials_only: bool = True
    production_signing_semantics_asserted: bool = False
    production_idempotency_semantics_asserted: bool = False
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
    live_transport_ready: bool = False
    pilot_publish_ready: bool = False
    global_kill_switch_required: bool = True
    live_reverification_required: bool = True
    state: str = TWIN_STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["requests"] = [request.to_dict() for request in self.requests]
        return data


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _validate_credentials(credentials: SyntheticCredentialEnvelope, plan: OfflineRequestPlan) -> None:
    if not isinstance(credentials, SyntheticCredentialEnvelope):
        raise MetaTransportTwinHold("HOLD_TWIN_CREDENTIAL_TYPE")
    if credentials.marker != "PPOS_TEST_ONLY":
        raise MetaTransportTwinHold("HOLD_TWIN_CREDENTIAL_MARKER")
    if credentials.auth_reference_kind != plan.auth_reference_kind:
        raise MetaTransportTwinHold("HOLD_TWIN_AUTH_REFERENCE_KIND_MISMATCH")
    if not TEST_TOKEN.fullmatch(credentials.bearer_token):
        raise MetaTransportTwinHold("HOLD_TWIN_REAL_OR_UNMARKED_TOKEN_FORBIDDEN")
    if not TEST_SIGNING_SECRET.fullmatch(credentials.signing_secret):
        raise MetaTransportTwinHold("HOLD_TWIN_REAL_OR_UNMARKED_SIGNING_SECRET_FORBIDDEN")


def _validate_binding(binding: SyntheticTransportBinding, plan: OfflineRequestPlan) -> None:
    if not isinstance(binding, SyntheticTransportBinding):
        raise MetaTransportTwinHold("HOLD_TWIN_BINDING_TYPE")
    if not TEST_DESTINATION.fullmatch(binding.destination_id):
        raise MetaTransportTwinHold("HOLD_TWIN_REAL_DESTINATION_FORBIDDEN")
    if not TEST_API_VERSION.fullmatch(binding.api_version):
        raise MetaTransportTwinHold("HOLD_TWIN_REAL_API_VERSION_FORBIDDEN")
    if plan.mode == "SINGLE_IMAGE":
        if not isinstance(binding.staging_url, str) or not binding.staging_url.startswith(INVALID_STAGING_PREFIX):
            raise MetaTransportTwinHold("HOLD_TWIN_NONROUTABLE_STAGING_URL_REQUIRED")
    elif binding.staging_url is not None:
        raise MetaTransportTwinHold("HOLD_TWIN_STAGING_URL_FOR_TEXT_FORBIDDEN")


def _exact_lineage(
    plan: OfflineRequestPlan,
    preflight: SyntheticPreflightReceipt,
    packet: OperatorProvisioningPacket,
) -> None:
    validate_request_plan(plan)
    validate_synthetic_preflight_receipt(preflight)
    validate_operator_provisioning_packet(packet)
    if preflight.plan_id != plan.plan_id or preflight.plan_hash != plan.plan_hash:
        raise MetaTransportTwinHold("HOLD_TWIN_PREFLIGHT_PLAN_BINDING_MISMATCH")
    if packet.preflight_receipt_id != preflight.receipt_id or packet.preflight_receipt_hash != preflight.receipt_hash:
        raise MetaTransportTwinHold("HOLD_TWIN_PACKET_PREFLIGHT_BINDING_MISMATCH")
    if packet.platform != plan.platform or packet.mode != plan.mode:
        raise MetaTransportTwinHold("HOLD_TWIN_PLATFORM_OR_MODE_MISMATCH")
    if packet.auth_reference_kind != plan.auth_reference_kind:
        raise MetaTransportTwinHold("HOLD_TWIN_AUTH_REFERENCE_KIND_MISMATCH")
    if packet.required_permissions != plan.required_permissions:
        raise MetaTransportTwinHold("HOLD_TWIN_PERMISSION_BINDING_MISMATCH")
    if packet.required_capabilities != plan.required_capabilities:
        raise MetaTransportTwinHold("HOLD_TWIN_CAPABILITY_BINDING_MISMATCH")
    if plan.platform not in EXPECTED_ACTIVE:
        raise MetaTransportTwinHold("HOLD_TWIN_PLATFORM_NOT_ACTIVE")
    if not packet.global_kill_switch_required or not packet.live_reverification_required:
        raise MetaTransportTwinHold("HOLD_TWIN_SAFETY_GATE_DRIFT")
    if packet.live_connection_ready or packet.pilot_publish_ready:
        raise MetaTransportTwinHold("HOLD_TWIN_PACKET_EXTERNAL_AUTHORITY_FORBIDDEN")


def _resolve_value(value: str, binding: SyntheticTransportBinding) -> str:
    if value == STAGING_URL_REF:
        if binding.staging_url is None:
            raise MetaTransportTwinHold("HOLD_TWIN_STAGING_URL_MISSING")
        return binding.staging_url
    if value == DESTINATION_REF:
        return binding.destination_id
    if value == API_VERSION_REF:
        return binding.api_version
    return value


def _resolve_step(
    step: RequestStep,
    *,
    plan: OfflineRequestPlan,
    binding: SyntheticTransportBinding,
    credentials: SyntheticCredentialEnvelope,
) -> TwinWireRequest:
    resolved_path = step.path_template.replace("{API_VERSION}", binding.api_version).replace(
        "{DESTINATION_ID}", binding.destination_id
    )
    if "{API_VERSION}" in resolved_path or "{DESTINATION_ID}" in resolved_path:
        raise MetaTransportTwinHold("HOLD_TWIN_UNRESOLVED_PATH_PLACEHOLDER")

    body = tuple((key, _resolve_value(value, binding)) for key, value in step.body)
    auth_value_hash = _text_hash("Bearer " + credentials.bearer_token)
    unsigned = {
        "ordinal": step.ordinal,
        "operation": step.operation,
        "method": step.method,
        "logical_host": step.host,
        "resolved_path": resolved_path,
        "body": [{"key": key, "value": value} for key, value in body],
        "output_id_ref": step.output_id_ref,
        "authorization_scheme": "Bearer",
        "authorization_value_sha256": auth_value_hash,
        "auth_scope": AUTH_SCOPE,
        "signature_scope": SIGNATURE_SCOPE,
        "idempotency_scope": IDEMPOTENCY_SCOPE,
    }
    unsigned_bytes = canonical_json(unsigned).encode("utf-8")
    internal_signature = hmac.new(
        credentials.signing_secret.encode("utf-8"),
        unsigned_bytes,
        digestmod=sha256,
    ).hexdigest()
    idempotency_key = "twinidem_" + _hash({
        "plan_hash": plan.plan_hash,
        "ordinal": step.ordinal,
        "operation": step.operation,
        "destination_binding_sha256": _text_hash(binding.destination_id),
    })[:32]
    request_body = {
        **unsigned,
        "internal_signature_sha256": internal_signature,
        "idempotency_key": idempotency_key,
        "credential_material_serialized": False,
        "wire_signature_header_included": False,
        "wire_idempotency_header_included": False,
        "network_target_materialized": False,
        "network_attempted": False,
    }
    request_hash = _hash(request_body)
    return TwinWireRequest(
        ordinal=step.ordinal,
        operation=step.operation,
        method=step.method,
        logical_host=step.host,
        resolved_path=resolved_path,
        body=body,
        output_id_ref=step.output_id_ref,
        authorization_scheme="Bearer",
        authorization_value_sha256=auth_value_hash,
        internal_signature_sha256=internal_signature,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
    )


def compile_transport_test_twin(
    plan: OfflineRequestPlan,
    preflight: SyntheticPreflightReceipt,
    packet: OperatorProvisioningPacket,
    *,
    binding: SyntheticTransportBinding,
    credentials: SyntheticCredentialEnvelope,
) -> TwinTransportReceipt:
    _exact_lineage(plan, preflight, packet)
    _validate_binding(binding, plan)
    _validate_credentials(credentials, plan)

    requests = tuple(
        _resolve_step(step, plan=plan, binding=binding, credentials=credentials)
        for step in plan.steps
    )
    body = {
        "model_version": TRANSPORT_TWIN_MODEL_VERSION,
        "engine_version": TRANSPORT_TWIN_ENGINE_VERSION,
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "preflight_receipt_id": preflight.receipt_id,
        "preflight_receipt_hash": preflight.receipt_hash,
        "provisioning_packet_id": packet.packet_id,
        "provisioning_packet_hash": packet.packet_hash,
        "platform": plan.platform,
        "mode": plan.mode,
        "destination_binding_sha256": _text_hash(binding.destination_id),
        "api_version_binding_sha256": _text_hash(binding.api_version),
        "staging_binding_sha256": _text_hash(binding.staging_url) if binding.staging_url is not None else None,
        "auth_reference_kind": plan.auth_reference_kind,
        "request_hashes": [request.request_hash for request in requests],
        "requests": [request.to_dict() for request in requests],
        "retry_classifier_version": "PPOS_SYNTHETIC_RETRY_CLASSIFIER_V1",
        "transport_mode": "SYNTHETIC_TEST_TWIN_ONLY",
        "synthetic_credentials_only": True,
        "production_signing_semantics_asserted": False,
        "production_idempotency_semantics_asserted": False,
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
        "live_transport_ready": False,
        "pilot_publish_ready": False,
        "global_kill_switch_required": True,
        "live_reverification_required": True,
        "state": TWIN_STATE,
    }
    twin_hash = _hash(body)
    receipt = TwinTransportReceipt(
        twin_id="mtt_" + twin_hash[:24],
        twin_hash=twin_hash,
        model_version=TRANSPORT_TWIN_MODEL_VERSION,
        engine_version=TRANSPORT_TWIN_ENGINE_VERSION,
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        preflight_receipt_id=preflight.receipt_id,
        preflight_receipt_hash=preflight.receipt_hash,
        provisioning_packet_id=packet.packet_id,
        provisioning_packet_hash=packet.packet_hash,
        platform=plan.platform,
        mode=plan.mode,
        destination_binding_sha256=_text_hash(binding.destination_id),
        api_version_binding_sha256=_text_hash(binding.api_version),
        staging_binding_sha256=_text_hash(binding.staging_url) if binding.staging_url is not None else None,
        auth_reference_kind=plan.auth_reference_kind,
        request_hashes=tuple(request.request_hash for request in requests),
        requests=requests,
    )
    validate_transport_twin_receipt(receipt)
    return receipt


def validate_transport_twin_receipt(receipt: TwinTransportReceipt) -> None:
    if not isinstance(receipt, TwinTransportReceipt):
        raise MetaTransportTwinHold("HOLD_TWIN_RECEIPT_TYPE")
    if receipt.model_version != TRANSPORT_TWIN_MODEL_VERSION or receipt.engine_version != TRANSPORT_TWIN_ENGINE_VERSION:
        raise MetaTransportTwinHold("HOLD_TWIN_RECEIPT_VERSION")
    if receipt.platform not in EXPECTED_ACTIVE:
        raise MetaTransportTwinHold("HOLD_TWIN_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(receipt.plan_hash) or not HEX64.fullmatch(receipt.preflight_receipt_hash):
        raise MetaTransportTwinHold("HOLD_TWIN_LINEAGE_HASH_INVALID")
    if not HEX64.fullmatch(receipt.provisioning_packet_hash):
        raise MetaTransportTwinHold("HOLD_TWIN_PACKET_HASH_INVALID")
    if not receipt.requests or receipt.request_hashes != tuple(request.request_hash for request in receipt.requests):
        raise MetaTransportTwinHold("HOLD_TWIN_REQUEST_HASH_SET_MISMATCH")
    for expected_ordinal, request in enumerate(receipt.requests, start=1):
        if request.ordinal != expected_ordinal or request.method != "POST":
            raise MetaTransportTwinHold("HOLD_TWIN_REQUEST_SEQUENCE_INVALID")
        if not HEX64.fullmatch(request.authorization_value_sha256):
            raise MetaTransportTwinHold("HOLD_TWIN_AUTH_HASH_INVALID")
        if not HEX64.fullmatch(request.internal_signature_sha256) or not HEX64.fullmatch(request.request_hash):
            raise MetaTransportTwinHold("HOLD_TWIN_REQUEST_SIGNATURE_OR_HASH_INVALID")
        if request.signature_scope != SIGNATURE_SCOPE or request.auth_scope != AUTH_SCOPE:
            raise MetaTransportTwinHold("HOLD_TWIN_BOUNDARY_SCOPE_DRIFT")
        if request.idempotency_scope != IDEMPOTENCY_SCOPE or not request.idempotency_key.startswith("twinidem_"):
            raise MetaTransportTwinHold("HOLD_TWIN_IDEMPOTENCY_SCOPE_DRIFT")
        if any((
            request.credential_material_serialized,
            request.wire_signature_header_included,
            request.wire_idempotency_header_included,
            request.network_target_materialized,
            request.network_attempted,
        )):
            raise MetaTransportTwinHold("HOLD_TWIN_WIRE_AUTHORITY_FORBIDDEN")
        request_body = request.to_dict()
        request_body.pop("request_hash")
        expected_request_hash = _hash(request_body)
        if request.request_hash != expected_request_hash:
            raise MetaTransportTwinHold("HOLD_TWIN_REQUEST_HASH_MISMATCH")
    if not receipt.synthetic_credentials_only:
        raise MetaTransportTwinHold("HOLD_TWIN_SYNTHETIC_CREDENTIAL_GATE_DRIFT")
    if receipt.production_signing_semantics_asserted or receipt.production_idempotency_semantics_asserted:
        raise MetaTransportTwinHold("HOLD_TWIN_PRODUCTION_SEMANTICS_ASSERTION_FORBIDDEN")
    if any((
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
        receipt.live_transport_ready,
        receipt.pilot_publish_ready,
    )):
        raise MetaTransportTwinHold("HOLD_TWIN_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not receipt.global_kill_switch_required or not receipt.live_reverification_required:
        raise MetaTransportTwinHold("HOLD_TWIN_SAFETY_GATE_DRIFT")
    if receipt.state != TWIN_STATE:
        raise MetaTransportTwinHold("HOLD_TWIN_RECEIPT_STATE")
    body = receipt.to_dict()
    body.pop("twin_id")
    body.pop("twin_hash")
    expected_hash = _hash(body)
    if receipt.twin_hash != expected_hash:
        raise MetaTransportTwinHold("HOLD_TWIN_RECEIPT_HASH_MISMATCH")
    if receipt.twin_id != "mtt_" + receipt.twin_hash[:24]:
        raise MetaTransportTwinHold("HOLD_TWIN_RECEIPT_ID_MISMATCH")


def classify_synthetic_response(status_code: int) -> str:
    if not isinstance(status_code, int) or isinstance(status_code, bool) or status_code < 100 or status_code > 599:
        raise MetaTransportTwinHold("HOLD_TWIN_SYNTHETIC_STATUS_INVALID")
    if 200 <= status_code <= 299:
        return RETRY_SUCCESS
    if status_code == 429:
        return RETRY_RATE_LIMIT
    if status_code in (408, 500, 502, 503, 504):
        return RETRY_TRANSIENT
    if status_code in (401, 403):
        return NO_RETRY_AUTH
    if 400 <= status_code <= 499:
        return NO_RETRY_CLIENT
    return HOLD_UNKNOWN


def render_transport_twin_json(receipt: TwinTransportReceipt) -> str:
    validate_transport_twin_receipt(receipt)
    return canonical_json(receipt.to_dict()) + "\n"
