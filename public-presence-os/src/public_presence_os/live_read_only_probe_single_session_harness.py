from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from .authorization_receipt_validator import compile_authorization_receipt_validator
from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_evidence_import import (
    LiveReadOnlyProbeEvidenceImportContract,
    compile_live_read_only_probe_evidence_import,
    validate_live_read_only_probe_evidence_import_contract,
)
from .live_read_only_probe_execution_admission import (
    AUTHORIZATION_GATE,
    ExecutionAdmissionReceipt,
    LiveReadOnlyProbeExecutionAdmissionContract,
    OperatorPreflightPacket,
    build_operator_preflight_packet,
    compile_live_read_only_probe_execution_admission,
    evaluate_execution_admission,
    validate_execution_admission_receipt,
    validate_live_read_only_probe_execution_admission_contract,
    validate_operator_preflight_packet,
)
from .live_read_only_probe_session import (
    ProbeSessionEnvelope,
    ProbeStep,
    compile_probe_session_envelope,
    validate_probe_session_envelope,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_SINGLE_SESSION_HARNESS_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-single-session-harness-v1.0.0"
STATE = "PASS_CP66_SINGLE_SESSION_EXECUTION_HARNESS_DRY_RUN_MOCK_ONLY_LIVE_HOLD"
CHECKPOINT = "CP66"
PARENT_EXECUTION_ADMISSION_CHECKPOINT = "CP65"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP67_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST_PACKET_AND_OPERATOR_HANDOFF"
TRANSPORT_KIND = "MOCK_IN_MEMORY_NO_NETWORK"
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
    "HOLD_CP66_MOCK_TRANSPORT_ONLY",
    "HOLD_CP66_LIVE_EXECUTION_NOT_AUTHORIZED",
)


class LiveReadOnlyProbeSingleSessionHarnessError(ValueError):
    pass


class LiveReadOnlyProbeSingleSessionHarnessHold(
    LiveReadOnlyProbeSingleSessionHarnessError
):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class HarnessRequest:
    session_id: str
    sequence: int
    platform: str
    probe_class: str
    method: str
    endpoint_label: str
    request_fingerprint_sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HarnessResponse:
    sequence: int
    platform: str
    probe_class: str
    status_code: int
    response_fingerprint_sha256: str
    write_count_before: int = 0
    write_count_after: int = 0
    mutating_method_observed: bool = False
    network_attempted: bool = False
    external_write_performed: bool = False
    raw_secret_present: bool = False
    state: str = "MOCK_READ_ONLY_OK_NO_NETWORK"

    def to_dict(self) -> dict:
        return asdict(self)


class HarnessTransport(Protocol):
    kind: str
    network_capable: bool
    call_count: int

    def execute(self, request: HarnessRequest) -> HarnessResponse:
        ...


class DeterministicMockTransport:
    kind = TRANSPORT_KIND
    network_capable = False

    def __init__(self, *, fail_sequence: int | None = None) -> None:
        self.fail_sequence = fail_sequence
        self.call_count = 0
        self.requests: list[HarnessRequest] = []

    def execute(self, request: HarnessRequest) -> HarnessResponse:
        self.call_count += 1
        self.requests.append(request)
        if self.fail_sequence is not None and request.sequence == self.fail_sequence:
            raise RuntimeError("synthetic injected transport fault")
        response_body = {
            "sequence": request.sequence,
            "platform": request.platform,
            "probe_class": request.probe_class,
            "request_fingerprint_sha256": request.request_fingerprint_sha256,
            "status_code": 200,
            "synthetic_result": "MOCK_READ_ONLY_OK_NO_NETWORK",
            "write_count": 0,
            "network_attempted": False,
        }
        return HarnessResponse(
            sequence=request.sequence,
            platform=request.platform,
            probe_class=request.probe_class,
            status_code=200,
            response_fingerprint_sha256=_hash(response_body),
        )


@dataclass(frozen=True)
class HarnessTraceEvent:
    sequence: int
    platform: str
    probe_class: str
    method: str
    endpoint_label: str
    request_fingerprint_sha256: str
    response_fingerprint_sha256: str
    status_code: int
    transport_call_index: int
    write_count_before: int = 0
    write_count_after: int = 0
    mutating_method_observed: bool = False
    network_attempted: bool = False
    external_write_performed: bool = False
    raw_secret_present: bool = False
    state: str = "PASS_MOCK_GET_ZERO_WRITE_ZERO_NETWORK"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SingleSessionHarnessReceipt:
    run_id: str
    run_hash: str
    model_version: str
    checkpoint: str
    parent_control_checkpoint: str
    cp65_contract_id: str
    cp65_contract_hash: str
    preflight_packet_id: str
    preflight_packet_hash: str
    admission_id: str
    admission_hash: str
    session_envelope_id: str
    session_envelope_hash: str
    session_id: str
    transport_kind: str
    active_platforms: tuple[str, ...]
    method_allowlist: tuple[str, ...]
    events: tuple[HarnessTraceEvent, ...]
    expected_step_count: int
    executed_step_count: int
    transport_call_count: int
    retry_count: int = 0
    write_attempt_count: int = 0
    mutating_method_count: int = 0
    network_attempt_count: int = 0
    secret_material_count: int = 0
    external_write_count: int = 0
    zero_write_proof: bool = True
    zero_network_proof: bool = True
    zero_secret_material_proof: bool = True
    zero_retry_proof: bool = True
    deterministic_order_validated: bool = True
    one_call_per_step_validated: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_present: bool = False
    admission_granted: bool = False
    control_plane_promoted: bool = False
    live_probe_execution_performed: bool = False
    account_connected: bool = False
    publish_attempted: bool = False
    deploy_performed: bool = False
    paid_service_used: bool = False
    authority_activated: bool = False
    immutable: bool = True
    state: str = "PASS_SINGLE_SESSION_MOCK_DRY_RUN_NO_LIVE_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["method_allowlist"] = list(self.method_allowlist)
        data["events"] = [event.to_dict() for event in self.events]
        return data


@dataclass(frozen=True)
class LiveReadOnlyProbeSingleSessionHarnessContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_execution_admission_checkpoint: str
    parent_control_checkpoint: str
    cp65_contract_id: str
    cp65_contract_hash: str
    cp64_contract_id: str
    cp64_contract_hash: str
    session_envelope_id: str
    session_envelope_hash: str
    harness_run_id: str
    harness_run_hash: str
    policy_sha256: str
    cp65_policy_sha256: str
    cp64_policy_sha256: str
    cp63_policy_sha256: str
    cp62_policy_sha256: str
    cp56_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    exact_cp65_binding_validated: bool = True
    exact_session_envelope_binding_validated: bool = True
    injected_mock_transport_validated: bool = True
    single_session_harness_validated: bool = True
    zero_write_validated: bool = True
    zero_network_validated: bool = True
    zero_secret_material_validated: bool = True
    zero_retry_validated: bool = True
    global_kill_switch_engaged: bool = True
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


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_LIVE_READ_ONLY_PROBE_SINGLE_SESSION_HARNESS_POLICY_V1":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M35_LIVE_READ_ONLY_PROBE_SINGLE_SESSION_HARNESS":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_POLICY_IDENTITY")
    if policy.get("parent_execution_admission_checkpoint") != PARENT_EXECUTION_ADMISSION_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_PARENT_EXECUTION_ADMISSION_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_BLOCKER_SET_DRIFT")
    if policy.get("rollback_target") != PARENT_EXECUTION_ADMISSION_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_ROLLBACK_TARGET_DRIFT")
    if policy.get("next_after_cp66") != NEXT_UNIT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_NEXT_UNIT_DRIFT")

    harness = policy.get("harness", {})
    required_true = (
        "local_dry_run_only",
        "single_session_exactly",
        "exact_cp65_contract_binding_required",
        "exact_cp65_preflight_packet_binding_required",
        "exact_cp65_admission_receipt_binding_required",
        "exact_cp63_session_envelope_binding_required",
        "cp65_admission_must_remain_hold",
        "external_authorization_must_remain_absent",
        "global_kill_switch_must_remain_engaged",
        "transport_must_be_injected",
        "default_network_transport_forbidden",
        "socket_transport_forbidden",
        "standard_library_http_clients_forbidden",
        "third_party_http_clients_forbidden",
        "mutating_methods_fail_closed",
        "synthetic_endpoint_labels_only",
        "real_urls_forbidden",
        "deterministic_step_order_required",
        "one_transport_call_per_step_required",
        "automatic_retry_forbidden_in_cp66",
        "fault_injection_must_fail_closed",
        "request_payload_persistence_forbidden",
        "response_payload_persistence_forbidden",
        "request_fingerprint_sha256_only",
        "response_fingerprint_sha256_only",
        "raw_secret_or_token_persistence_forbidden",
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
    )
    if any(harness.get(key) is not True for key in required_true):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_HARNESS_GUARD_MISSING")
    if harness.get("transport_kind_must_equal") != TRANSPORT_KIND:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_TRANSPORT_KIND_POLICY_DRIFT")
    if tuple(harness.get("method_allowlist", ())) != ALLOWED_METHODS:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_METHOD_ALLOWLIST_DRIFT")
    if tuple(harness.get("mutating_methods_forbidden", ())) != MUTATING_METHODS:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_MUTATING_METHOD_SET_DRIFT")
    if harness.get("retry_count_must_equal") != 0:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RETRY_POLICY_DRIFT")

    receipt = policy.get("receipt", {})
    if any(
        receipt.get(key) is not True
        for key in (
            "canonical_json_required",
            "sha256_binding_required",
            "immutable_required",
            "transport_call_trace_required",
            "zero_write_proof_required",
            "zero_network_proof_required",
            "zero_secret_material_proof_required",
            "zero_retry_proof_required",
            "authority_claim_forbidden",
        )
    ):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_GUARD_MISSING")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RUNTIME_ACTIVE_PLATFORM_DRIFT")
    for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled"):
        if runtime.get(key) is not False:
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RUNTIME_LIVE_BOUNDARY_MUST_REMAIN_DISABLED")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTROL_PROMOTION_MUST_REMAIN_HOLD")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M34_LIVE_READ_ONLY_PROBE_EXECUTION_ADMISSION") != "CP65_EXECUTION_ADMISSION_PREFLIGHT_PACKET_LOCAL_ONLY_AUTHORIZATION_REQUIRED_LIVE_HOLD":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CP65_MODULE_STATE_DRIFT")
    if states.get("M35_LIVE_READ_ONLY_PROBE_SINGLE_SESSION_HARNESS") != "CP66_SINGLE_SESSION_EXECUTION_HARNESS_DRY_RUN_MOCK_ONLY_LIVE_HOLD":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_MODULE_STATE_DRIFT")


def _validate_parent_lineage(
    cp65: LiveReadOnlyProbeExecutionAdmissionContract,
    cp64: LiveReadOnlyProbeEvidenceImportContract,
    packet: OperatorPreflightPacket,
    admission: ExecutionAdmissionReceipt,
    envelope: ProbeSessionEnvelope,
) -> None:
    validate_live_read_only_probe_execution_admission_contract(cp65)
    validate_live_read_only_probe_evidence_import_contract(cp64)
    validate_operator_preflight_packet(packet, cp64)
    validate_execution_admission_receipt(admission, packet, cp64)
    if (cp65.cp64_contract_id, cp65.cp64_contract_hash) != (cp64.contract_id, cp64.contract_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CP65_CP64_BINDING_MISMATCH")
    if (cp65.preflight_packet_id, cp65.preflight_packet_hash) != (packet.packet_id, packet.packet_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CP65_PREFLIGHT_BINDING_MISMATCH")
    if (cp65.admission_id, cp65.admission_hash) != (admission.admission_id, admission.admission_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CP65_ADMISSION_BINDING_MISMATCH")
    if (cp64.session_envelope_id, cp64.session_envelope_hash) != (envelope.envelope_id, envelope.envelope_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CP64_SESSION_ENVELOPE_BINDING_MISMATCH")
    if cp65.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CP65_CONTROL_BINDING_DRIFT")
    if cp65.active_platforms != EXPECTED_ACTIVE or cp64.active_platforms != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_PARENT_PLATFORM_DRIFT")
    if not cp65.global_kill_switch_engaged or not cp64.global_kill_switch_engaged:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_PARENT_KILL_SWITCH_DRIFT")
    if admission.external_authorization_present or admission.admission_granted or admission.live_probe_allowed or admission.network_allowed:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_PARENT_ADMISSION_MUST_REMAIN_HOLD")
    if cp65.authority_activated or cp65.network_attempted or cp65.live_probe_attempted:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CP65_UNEXPECTED_LIVE_STATE")


def _request_for_step(envelope: ProbeSessionEnvelope, step: ProbeStep) -> HarnessRequest:
    if step.method not in ALLOWED_METHODS or step.method in MUTATING_METHODS:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_MUTATING_METHOD_DETECTED")
    if not step.endpoint_label.startswith("SYNTHETIC_ENDPOINT::") or "://" in step.endpoint_label:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_REAL_OR_UNSAFE_ENDPOINT_DETECTED")
    body = {
        "session_id": envelope.session_id,
        "sequence": step.sequence,
        "platform": step.platform,
        "probe_class": step.probe_class,
        "method": step.method,
        "endpoint_label": step.endpoint_label,
    }
    return HarnessRequest(
        session_id=envelope.session_id,
        sequence=step.sequence,
        platform=step.platform,
        probe_class=step.probe_class,
        method=step.method,
        endpoint_label=step.endpoint_label,
        request_fingerprint_sha256=_hash(body),
    )


def _validate_transport(transport: HarnessTransport) -> None:
    if getattr(transport, "kind", None) != TRANSPORT_KIND:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_NON_MOCK_TRANSPORT_REJECTED")
    if getattr(transport, "network_capable", None) is not False:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_NETWORK_CAPABLE_TRANSPORT_REJECTED")
    if not callable(getattr(transport, "execute", None)):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_TRANSPORT_EXECUTE_MISSING")


def _event_from_exchange(
    request: HarnessRequest,
    response: HarnessResponse,
    transport_call_index: int,
) -> HarnessTraceEvent:
    if response.sequence != request.sequence or response.platform != request.platform or response.probe_class != request.probe_class:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RESPONSE_BINDING_MISMATCH")
    if response.status_code != 200:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_MOCK_RESPONSE_NON_200_FAIL_CLOSED")
    if not _is_hex64(response.response_fingerprint_sha256):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RESPONSE_FINGERPRINT_INVALID")
    if any(
        (
            response.write_count_before != 0,
            response.write_count_after != 0,
            response.mutating_method_observed,
            response.network_attempted,
            response.external_write_performed,
            response.raw_secret_present,
        )
    ):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_SIDE_EFFECT_OR_SECRET_DETECTED")
    return HarnessTraceEvent(
        sequence=request.sequence,
        platform=request.platform,
        probe_class=request.probe_class,
        method=request.method,
        endpoint_label=request.endpoint_label,
        request_fingerprint_sha256=request.request_fingerprint_sha256,
        response_fingerprint_sha256=response.response_fingerprint_sha256,
        status_code=response.status_code,
        transport_call_index=transport_call_index,
    )


def run_single_session_harness(
    cp65: LiveReadOnlyProbeExecutionAdmissionContract,
    cp64: LiveReadOnlyProbeEvidenceImportContract,
    packet: OperatorPreflightPacket,
    admission: ExecutionAdmissionReceipt,
    envelope: ProbeSessionEnvelope,
    transport: HarnessTransport,
) -> SingleSessionHarnessReceipt:
    _validate_parent_lineage(cp65, cp64, packet, admission, envelope)
    _validate_transport(transport)

    events: list[HarnessTraceEvent] = []
    initial_call_count = int(getattr(transport, "call_count", 0))
    for step in envelope.steps:
        request = _request_for_step(envelope, step)
        before = int(getattr(transport, "call_count", 0))
        try:
            response = transport.execute(request)
        except Exception as exc:
            after_fault = int(getattr(transport, "call_count", before))
            if after_fault - before > 1:
                raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RETRY_DETECTED_DURING_FAULT") from exc
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_TRANSPORT_FAULT_FAIL_CLOSED") from exc
        after = int(getattr(transport, "call_count", before))
        if after - before != 1:
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_TRANSPORT_CALL_CARDINALITY_DRIFT")
        events.append(_event_from_exchange(request, response, after - initial_call_count))

    transport_call_count = int(getattr(transport, "call_count", initial_call_count)) - initial_call_count
    if transport_call_count != len(envelope.steps):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_TRANSPORT_CALL_COUNT_DRIFT")

    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp65_contract_id": cp65.contract_id,
        "cp65_contract_hash": cp65.contract_hash,
        "preflight_packet_id": packet.packet_id,
        "preflight_packet_hash": packet.packet_hash,
        "admission_id": admission.admission_id,
        "admission_hash": admission.admission_hash,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "session_id": envelope.session_id,
        "transport_kind": TRANSPORT_KIND,
        "active_platforms": list(EXPECTED_ACTIVE),
        "method_allowlist": list(ALLOWED_METHODS),
        "events": [event.to_dict() for event in events],
        "expected_step_count": len(envelope.steps),
        "executed_step_count": len(events),
        "transport_call_count": transport_call_count,
        "retry_count": 0,
        "write_attempt_count": 0,
        "mutating_method_count": 0,
        "network_attempt_count": 0,
        "secret_material_count": 0,
        "external_write_count": 0,
        "zero_write_proof": True,
        "zero_network_proof": True,
        "zero_secret_material_proof": True,
        "zero_retry_proof": True,
        "deterministic_order_validated": True,
        "one_call_per_step_validated": True,
        "global_kill_switch_engaged": True,
        "external_authorization_present": False,
        "admission_granted": False,
        "control_plane_promoted": False,
        "live_probe_execution_performed": False,
        "account_connected": False,
        "publish_attempted": False,
        "deploy_performed": False,
        "paid_service_used": False,
        "authority_activated": False,
        "immutable": True,
        "state": "PASS_SINGLE_SESSION_MOCK_DRY_RUN_NO_LIVE_AUTHORITY",
    }
    run_hash = _hash(body)
    receipt = SingleSessionHarnessReceipt(
        run_id=f"cp66_run_{run_hash[:24]}",
        run_hash=run_hash,
        **{
            **body,
            "active_platforms": EXPECTED_ACTIVE,
            "method_allowlist": ALLOWED_METHODS,
            "events": tuple(events),
        },
    )
    validate_single_session_harness_receipt(receipt, cp65, packet, admission, envelope)
    return receipt


def validate_single_session_harness_receipt(
    receipt: SingleSessionHarnessReceipt,
    cp65: LiveReadOnlyProbeExecutionAdmissionContract,
    packet: OperatorPreflightPacket,
    admission: ExecutionAdmissionReceipt,
    envelope: ProbeSessionEnvelope,
) -> None:
    if receipt.model_version != MODEL_VERSION or receipt.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_VERSION_DRIFT")
    if receipt.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_CONTROL_BINDING_DRIFT")
    if (receipt.cp65_contract_id, receipt.cp65_contract_hash) != (cp65.contract_id, cp65.contract_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_CP65_BINDING_MISMATCH")
    if (receipt.preflight_packet_id, receipt.preflight_packet_hash) != (packet.packet_id, packet.packet_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_PREFLIGHT_BINDING_MISMATCH")
    if (receipt.admission_id, receipt.admission_hash) != (admission.admission_id, admission.admission_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_ADMISSION_BINDING_MISMATCH")
    if (receipt.session_envelope_id, receipt.session_envelope_hash) != (envelope.envelope_id, envelope.envelope_hash):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_SESSION_BINDING_MISMATCH")
    if receipt.session_id != envelope.session_id or receipt.transport_kind != TRANSPORT_KIND:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_SESSION_OR_TRANSPORT_DRIFT")
    if receipt.active_platforms != EXPECTED_ACTIVE or receipt.method_allowlist != ALLOWED_METHODS:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_PLATFORM_OR_METHOD_DRIFT")
    if receipt.expected_step_count != len(envelope.steps) or receipt.executed_step_count != len(envelope.steps):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_STEP_COUNT_DRIFT")
    if receipt.transport_call_count != len(envelope.steps) or len(receipt.events) != len(envelope.steps):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_CALL_COUNT_DRIFT")
    if any(
        count != 0
        for count in (
            receipt.retry_count,
            receipt.write_attempt_count,
            receipt.mutating_method_count,
            receipt.network_attempt_count,
            receipt.secret_material_count,
            receipt.external_write_count,
        )
    ):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_ZERO_COUNTER_DRIFT")
    if not all(
        (
            receipt.zero_write_proof,
            receipt.zero_network_proof,
            receipt.zero_secret_material_proof,
            receipt.zero_retry_proof,
            receipt.deterministic_order_validated,
            receipt.one_call_per_step_validated,
            receipt.global_kill_switch_engaged,
            receipt.immutable,
        )
    ):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_REQUIRED_PROOF_MISSING")
    if any(
        (
            receipt.external_authorization_present,
            receipt.admission_granted,
            receipt.control_plane_promoted,
            receipt.live_probe_execution_performed,
            receipt.account_connected,
            receipt.publish_attempted,
            receipt.deploy_performed,
            receipt.paid_service_used,
            receipt.authority_activated,
        )
    ):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_LIVE_OR_AUTHORITY_STATE_DETECTED")
    if receipt.state != "PASS_SINGLE_SESSION_MOCK_DRY_RUN_NO_LIVE_AUTHORITY":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_STATE_DRIFT")

    for expected_index, (step, event) in enumerate(zip(envelope.steps, receipt.events), start=1):
        if (event.sequence, event.platform, event.probe_class, event.method, event.endpoint_label) != (
            step.sequence,
            step.platform,
            step.probe_class,
            step.method,
            step.endpoint_label,
        ):
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_EVENT_BINDING_MISMATCH")
        if event.transport_call_index != expected_index:
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_EVENT_ORDER_DRIFT")
        if event.method != "GET" or event.mutating_method_observed:
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_MUTATING_METHOD_DETECTED")
        if not event.endpoint_label.startswith("SYNTHETIC_ENDPOINT::") or "://" in event.endpoint_label:
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_REAL_ENDPOINT_DETECTED")
        if any((event.write_count_before, event.write_count_after, event.network_attempted, event.external_write_performed, event.raw_secret_present)):
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_EVENT_SIDE_EFFECT_DETECTED")
        if not _is_hex64(event.request_fingerprint_sha256) or not _is_hex64(event.response_fingerprint_sha256):
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_EVENT_FINGERPRINT_INVALID")

    body = _payload_without_identity(receipt.to_dict(), "run_id", "run_hash")
    expected_hash = _hash(body)
    if receipt.run_hash != expected_hash or receipt.run_id != f"cp66_run_{expected_hash[:24]}":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_RECEIPT_HASH_BINDING_INVALID")


def compile_live_read_only_probe_single_session_harness(
    root: Path,
    policy: dict,
) -> LiveReadOnlyProbeSingleSessionHarnessContract:
    root = root.resolve()
    _validate_policy(policy)

    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp65_policy = load_json(root / "config" / "live_read_only_probe_execution_admission_policy.json")
    cp64_policy = load_json(root / "config" / "live_read_only_probe_evidence_import_policy.json")
    cp63_policy = load_json(root / "config" / "live_read_only_probe_session_policy.json")
    cp62_policy = load_json(root / "config" / "authorization_receipt_validator_policy.json")
    cp56_policy = load_json(root / "config" / "meta_live_read_only_probe_policy.json")

    cp65 = compile_live_read_only_probe_execution_admission(root, cp65_policy)
    cp64 = compile_live_read_only_probe_evidence_import(root, cp64_policy)
    cp62 = compile_authorization_receipt_validator(root, cp62_policy)
    envelope = compile_probe_session_envelope(cp62, cp56_policy)
    validate_probe_session_envelope(cp62, cp56_policy, envelope)
    packet = build_operator_preflight_packet(cp64)
    admission = evaluate_execution_admission(packet, cp64)
    _validate_parent_lineage(cp65, cp64, packet, admission, envelope)

    transport = DeterministicMockTransport()
    harness_receipt = run_single_session_harness(
        cp65,
        cp64,
        packet,
        admission,
        envelope,
        transport,
    )

    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_execution_admission_checkpoint": PARENT_EXECUTION_ADMISSION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp65_contract_id": cp65.contract_id,
        "cp65_contract_hash": cp65.contract_hash,
        "cp64_contract_id": cp64.contract_id,
        "cp64_contract_hash": cp64.contract_hash,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "harness_run_id": harness_receipt.run_id,
        "harness_run_hash": harness_receipt.run_hash,
        "policy_sha256": _hash(policy),
        "cp65_policy_sha256": _hash(cp65_policy),
        "cp64_policy_sha256": _hash(cp64_policy),
        "cp63_policy_sha256": _hash(cp63_policy),
        "cp62_policy_sha256": _hash(cp62_policy),
        "cp56_policy_sha256": _hash(cp56_policy),
        "runtime_policy_sha256": _hash(runtime),
        "module_registry_sha256": _hash(registry),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "exact_cp65_binding_validated": True,
        "exact_session_envelope_binding_validated": True,
        "injected_mock_transport_validated": True,
        "single_session_harness_validated": True,
        "zero_write_validated": True,
        "zero_network_validated": True,
        "zero_secret_material_validated": True,
        "zero_retry_validated": True,
        "global_kill_switch_engaged": True,
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
    contract = LiveReadOnlyProbeSingleSessionHarnessContract(
        contract_id=f"cp66_contract_{contract_hash[:24]}",
        contract_hash=contract_hash,
        **{
            **body,
            "active_platforms": EXPECTED_ACTIVE,
            "blockers": REQUIRED_BLOCKERS,
        },
    )
    validate_live_read_only_probe_single_session_harness_contract(contract)
    return contract


def validate_live_read_only_probe_single_session_harness_contract(
    contract: LiveReadOnlyProbeSingleSessionHarnessContract,
) -> None:
    if contract.model_version != MODEL_VERSION or contract.engine_version != ENGINE_VERSION:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_VERSION_DRIFT")
    if contract.checkpoint != CHECKPOINT or contract.parent_execution_admission_checkpoint != PARENT_EXECUTION_ADMISSION_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_CHECKPOINT_DRIFT")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_CONTROL_BINDING_DRIFT")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_GATING_DRIFT")
    if contract.next_unit != NEXT_UNIT or contract.state != STATE:
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_STATE_OR_NEXT_UNIT_DRIFT")
    if not all(
        (
            contract.exact_cp65_binding_validated,
            contract.exact_session_envelope_binding_validated,
            contract.injected_mock_transport_validated,
            contract.single_session_harness_validated,
            contract.zero_write_validated,
            contract.zero_network_validated,
            contract.zero_secret_material_validated,
            contract.zero_retry_validated,
            contract.global_kill_switch_engaged,
        )
    ):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_REQUIRED_PROOF_MISSING")
    if any(
        (
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
    ):
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_LIVE_OR_AUTHORITY_STATE_DETECTED")
    for digest in (
        contract.cp65_contract_hash,
        contract.cp64_contract_hash,
        contract.session_envelope_hash,
        contract.harness_run_hash,
        contract.policy_sha256,
        contract.cp65_policy_sha256,
        contract.cp64_policy_sha256,
        contract.cp63_policy_sha256,
        contract.cp62_policy_sha256,
        contract.cp56_policy_sha256,
        contract.runtime_policy_sha256,
        contract.module_registry_sha256,
    ):
        if not _is_hex64(digest):
            raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_DIGEST_INVALID")
    body = _payload_without_identity(contract.to_dict(), "contract_id", "contract_hash")
    expected_hash = _hash(body)
    if contract.contract_hash != expected_hash or contract.contract_id != f"cp66_contract_{expected_hash[:24]}":
        raise LiveReadOnlyProbeSingleSessionHarnessHold("HOLD_CP66_CONTRACT_HASH_BINDING_INVALID")
