from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .authorization_receipt_validator import compile_authorization_receipt_validator
from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_session import (
    LiveReadOnlyProbeSessionContract,
    ProbeSessionEnvelope,
    ZeroWriteRecorderReceipt,
    compile_live_read_only_probe_session,
    compile_probe_session_envelope,
    record_zero_write_dry_run,
    validate_live_read_only_probe_session_contract,
    validate_probe_session_envelope,
    validate_zero_write_recorder,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-evidence-import-v1.0.0"
BUNDLE_SCHEMA = "PPOS_CP64_REDACTED_EVIDENCE_BUNDLE_V1"
STATE = "PASS_CP64_EVIDENCE_IMPORT_GATE_REPLAY_VALIDATOR_DRY_RUN_LOCAL_ONLY_LIVE_HOLD"
CHECKPOINT = "CP64"
PARENT_SESSION_CHECKPOINT = "CP63"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP65_LIVE_READ_ONLY_PROBE_EXECUTION_ADMISSION_GATE_AND_OPERATOR_PREFLIGHT_PACKET"
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
    "HOLD_CP64_SYNTHETIC_IMPORT_REPLAY_ONLY",
)

BUNDLE_KEYS = frozenset(
    {
        "schema_version",
        "source_kind",
        "cp63_contract_id",
        "cp63_contract_hash",
        "session_envelope_id",
        "session_envelope_hash",
        "zero_write_recorder_id",
        "zero_write_recorder_hash",
        "active_platforms",
        "method_allowlist",
        "evidence_items",
        "replay_trace",
        "global_kill_switch_engaged",
        "redaction_complete",
        "immutable",
        "live_evidence",
        "network_attempt_count",
        "write_attempt_count",
        "external_write_count",
        "sensitive_material_count",
        "authority_claimed",
        "control_plane_promotion_claimed",
        "publish_authority_claimed",
    }
)

SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization",
        "password",
        "raw_token",
        "raw_secret",
    }
)


class LiveReadOnlyProbeEvidenceImportError(ValueError):
    pass


class LiveReadOnlyProbeEvidenceImportHold(LiveReadOnlyProbeEvidenceImportError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EvidenceImportReceipt:
    import_id: str
    import_hash: str
    model_version: str
    checkpoint: str
    cp63_contract_id: str
    cp63_contract_hash: str
    session_envelope_id: str
    session_envelope_hash: str
    zero_write_recorder_id: str
    zero_write_recorder_hash: str
    bundle_sha256: str
    evidence_codes: tuple[str, ...]
    evidence_item_count: int
    replay_trace_count: int
    active_platforms: tuple[str, ...]
    bundle_schema_validated: bool = True
    redaction_validated: bool = True
    hash_binding_validated: bool = True
    exact_parent_binding_validated: bool = True
    synthetic_only: bool = True
    live_evidence_imported: bool = False
    network_attempted: bool = False
    external_write_performed: bool = False
    sensitive_material_persisted: bool = False
    authority_activated: bool = False
    control_plane_promoted: bool = False
    publish_authorized: bool = False
    state: str = "PASS_SYNTHETIC_REDACTED_IMPORT_ONLY_NO_LIVE_AUTHORITY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence_codes"] = list(self.evidence_codes)
        data["active_platforms"] = list(self.active_platforms)
        return data


@dataclass(frozen=True)
class ReplayValidationReceipt:
    replay_id: str
    replay_hash: str
    model_version: str
    checkpoint: str
    import_id: str
    import_hash: str
    bundle_sha256: str
    session_envelope_id: str
    session_envelope_hash: str
    zero_write_recorder_id: str
    zero_write_recorder_hash: str
    matched_trace_count: int
    expected_trace_count: int
    structural_replay_validated: bool = True
    deterministic_order_validated: bool = True
    get_only_validated: bool = True
    synthetic_endpoints_validated: bool = True
    zero_write_validated: bool = True
    zero_network_validated: bool = True
    live_execution_performed: bool = False
    network_attempted: bool = False
    external_write_performed: bool = False
    authority_activated: bool = False
    state: str = "PASS_OFFLINE_STRUCTURAL_REPLAY_ONLY_NO_LIVE_EXECUTION"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LiveReadOnlyProbeEvidenceImportContract:
    contract_id: str
    contract_hash: str
    model_version: str
    engine_version: str
    checkpoint: str
    parent_session_checkpoint: str
    parent_control_checkpoint: str
    cp63_contract_id: str
    cp63_contract_hash: str
    session_envelope_id: str
    session_envelope_hash: str
    zero_write_recorder_id: str
    zero_write_recorder_hash: str
    evidence_import_id: str
    evidence_import_hash: str
    replay_validation_id: str
    replay_validation_hash: str
    policy_sha256: str
    cp63_policy_sha256: str
    cp56_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    evidence_import_gate_validated: bool = True
    structural_replay_validated: bool = True
    global_kill_switch_engaged: bool = True
    synthetic_fixture_only: bool = True
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


def _is_hex64(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _walk_for_sensitive_material(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_RAW_SECRET_OR_TOKEN_FIELD_DETECTED")
            _walk_for_sensitive_material(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _walk_for_sensitive_material(child)
    elif isinstance(value, str):
        lowered = value.lower()
        if "bearer " in lowered or "authorization:" in lowered:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_RAW_SECRET_OR_TOKEN_VALUE_DETECTED")


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT_POLICY_V1":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_POLICY_SCHEMA")
    if policy.get("checkpoint") != CHECKPOINT or policy.get("module_id") != "M33_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_POLICY_IDENTITY")
    if policy.get("parent_session_checkpoint") != PARENT_SESSION_CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_PARENT_SESSION_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_PARENT_CONTROL_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_BLOCKER_SET_DRIFT")
    if policy.get("rollback_target") != PARENT_SESSION_CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_ROLLBACK_TARGET_DRIFT")
    if policy.get("next_after_cp64") != NEXT_UNIT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_NEXT_UNIT_DRIFT")

    gate = policy.get("import_gate", {})
    required_gate_true = (
        "offline_dry_run_only",
        "synthetic_fixture_required_in_cp64",
        "exact_cp63_contract_binding_required",
        "exact_cp63_session_envelope_binding_required",
        "exact_cp63_zero_write_recorder_binding_required",
        "exact_cp56_evidence_code_binding_required",
        "canonical_json_required",
        "sha256_bundle_binding_required",
        "redaction_required",
        "raw_secret_or_token_material_forbidden",
        "extra_fields_fail_closed",
        "duplicate_or_missing_evidence_fail_closed",
        "global_kill_switch_must_remain_engaged",
        "live_evidence_import_forbidden_in_cp64",
        "network_forbidden",
        "external_write_forbidden",
        "publish_forbidden",
        "deploy_forbidden",
        "paid_service_forbidden",
    )
    if any(gate.get(key) is not True for key in required_gate_true):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_IMPORT_GATE_GUARD_MISSING")
    if gate.get("bundle_schema_must_equal") != BUNDLE_SCHEMA:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_BUNDLE_SCHEMA_POLICY_DRIFT")

    replay = policy.get("replay_validator", {})
    required_replay_true = (
        "enabled",
        "local_only",
        "deterministic_order_required",
        "exact_cp63_probe_step_binding_required",
        "exact_cp63_request_fingerprint_binding_required",
        "exact_cp63_response_fingerprint_binding_required",
        "synthetic_endpoint_labels_only",
        "real_url_forbidden",
        "structural_replay_only",
        "live_execution_forbidden",
    )
    if any(replay.get(key) is not True for key in required_replay_true):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_GUARD_MISSING")
    if tuple(replay.get("method_allowlist", ())) != ALLOWED_METHODS:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_METHOD_ALLOWLIST_DRIFT")
    if tuple(replay.get("mutating_methods_forbidden", ())) != MUTATING_METHODS:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_MUTATING_METHOD_SET_DRIFT")
    for key in (
        "network_attempt_count_must_equal",
        "write_attempt_count_must_equal",
        "external_write_count_must_equal",
        "sensitive_material_count_must_equal",
    ):
        if replay.get(key) != 0:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_ZERO_SIDE_EFFECT_POLICY_DRIFT")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_RUNTIME_ACTIVE_PLATFORM_DRIFT")


def _validate_registry(registry: dict) -> None:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTROL_PROMOTION_MUST_REMAIN_HOLD")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M32_LIVE_READ_ONLY_PROBE_SESSION") != "CP63_SESSION_ENVELOPE_ZERO_WRITE_RECORDER_DRY_RUN_LOCAL_ONLY_LIVE_HOLD":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CP63_MODULE_STATE_DRIFT")
    if states.get("M33_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT") != "CP64_EVIDENCE_IMPORT_GATE_REPLAY_VALIDATOR_DRY_RUN_LOCAL_ONLY_LIVE_HOLD":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_MODULE_STATE_DRIFT")


def build_synthetic_redacted_bundle(
    cp63: LiveReadOnlyProbeSessionContract,
    envelope: ProbeSessionEnvelope,
    recorder: ZeroWriteRecorderReceipt,
    cp56_policy: dict,
) -> dict:
    validate_live_read_only_probe_session_contract(cp63)
    evidence_codes = tuple(cp56_policy.get("required_evidence_codes", ()))
    if not evidence_codes or len(evidence_codes) != len(set(evidence_codes)):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_EVIDENCE_CODE_SOURCE_INVALID")

    evidence_items = []
    for ordinal, code in enumerate(evidence_codes, start=1):
        value_hash = _hash(
            {
                "checkpoint": CHECKPOINT,
                "cp63_contract_hash": cp63.contract_hash,
                "ordinal": ordinal,
                "code": code,
                "fixture_state": "SYNTHETIC_REDACTED_NOT_LIVE",
            }
        )
        evidence_items.append(
            {
                "ordinal": ordinal,
                "code": code,
                "redacted_value_sha256": value_hash,
                "redacted": True,
                "live_captured": False,
            }
        )

    replay_trace = []
    for step, event in zip(envelope.steps, recorder.events):
        replay_trace.append(
            {
                "sequence": step.sequence,
                "platform": step.platform,
                "probe_class": step.probe_class,
                "method": step.method,
                "endpoint_label": step.endpoint_label,
                "request_fingerprint_sha256": event.request_fingerprint_sha256,
                "response_fingerprint_sha256": event.response_fingerprint_sha256,
                "network_observed": False,
                "write_observed": False,
            }
        )

    return {
        "schema_version": BUNDLE_SCHEMA,
        "source_kind": "SYNTHETIC_REDACTED_FIXTURE",
        "cp63_contract_id": cp63.contract_id,
        "cp63_contract_hash": cp63.contract_hash,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "zero_write_recorder_id": recorder.recorder_id,
        "zero_write_recorder_hash": recorder.recorder_hash,
        "active_platforms": list(EXPECTED_ACTIVE),
        "method_allowlist": list(ALLOWED_METHODS),
        "evidence_items": evidence_items,
        "replay_trace": replay_trace,
        "global_kill_switch_engaged": True,
        "redaction_complete": True,
        "immutable": True,
        "live_evidence": False,
        "network_attempt_count": 0,
        "write_attempt_count": 0,
        "external_write_count": 0,
        "sensitive_material_count": 0,
        "authority_claimed": False,
        "control_plane_promotion_claimed": False,
        "publish_authority_claimed": False,
    }


def validate_and_import_evidence_bundle(
    payload: dict,
    cp63: LiveReadOnlyProbeSessionContract,
    envelope: ProbeSessionEnvelope,
    recorder: ZeroWriteRecorderReceipt,
    cp56_policy: dict,
) -> EvidenceImportReceipt:
    validate_live_read_only_probe_session_contract(cp63)
    _walk_for_sensitive_material(payload)
    if set(payload) != BUNDLE_KEYS:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_BUNDLE_FIELD_SET_DRIFT")
    if payload.get("schema_version") != BUNDLE_SCHEMA or payload.get("source_kind") != "SYNTHETIC_REDACTED_FIXTURE":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_BUNDLE_IDENTITY_DRIFT")
    if (payload.get("cp63_contract_id"), payload.get("cp63_contract_hash")) != (cp63.contract_id, cp63.contract_hash):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CP63_CONTRACT_BINDING_MISMATCH")
    if (payload.get("session_envelope_id"), payload.get("session_envelope_hash")) != (envelope.envelope_id, envelope.envelope_hash):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_SESSION_ENVELOPE_BINDING_MISMATCH")
    if (payload.get("zero_write_recorder_id"), payload.get("zero_write_recorder_hash")) != (recorder.recorder_id, recorder.recorder_hash):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_ZERO_WRITE_RECORDER_BINDING_MISMATCH")
    if tuple(payload.get("active_platforms", ())) != EXPECTED_ACTIVE or tuple(payload.get("method_allowlist", ())) != ALLOWED_METHODS:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_PLATFORM_OR_METHOD_DRIFT")

    expected_codes = tuple(cp56_policy.get("required_evidence_codes", ()))
    items = payload.get("evidence_items")
    if not isinstance(items, list) or len(items) != len(expected_codes):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_EVIDENCE_ITEM_COUNT_DRIFT")
    observed_codes = tuple(item.get("code") for item in items if isinstance(item, dict))
    if observed_codes != expected_codes or len(observed_codes) != len(set(observed_codes)):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_EVIDENCE_CODE_SET_OR_ORDER_DRIFT")
    expected_bundle = build_synthetic_redacted_bundle(cp63, envelope, recorder, cp56_policy)
    for expected, observed in zip(expected_bundle["evidence_items"], items):
        if observed != expected or observed.get("redacted") is not True or observed.get("live_captured") is not False:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REDACTION_OR_EVIDENCE_HASH_INVALID")
        if not _is_hex64(observed.get("redacted_value_sha256")):
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_EVIDENCE_DIGEST_INVALID")

    trace = payload.get("replay_trace")
    if not isinstance(trace, list) or len(trace) != len(envelope.steps) or len(trace) != len(recorder.events):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_TRACE_COUNT_DRIFT")
    for expected, observed in zip(expected_bundle["replay_trace"], trace):
        if observed != expected:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_TRACE_BINDING_MISMATCH")
        if observed.get("method") != "GET" or observed.get("method") in MUTATING_METHODS:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_MUTATING_METHOD_DETECTED")
        endpoint = observed.get("endpoint_label")
        if not isinstance(endpoint, str) or not endpoint.startswith("SYNTHETIC_ENDPOINT::") or "://" in endpoint:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REAL_OR_UNSAFE_ENDPOINT_DETECTED")
        if observed.get("network_observed") is not False or observed.get("write_observed") is not False:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_SIDE_EFFECT_DETECTED")
        if not _is_hex64(observed.get("request_fingerprint_sha256")) or not _is_hex64(observed.get("response_fingerprint_sha256")):
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_FINGERPRINT_INVALID")

    if payload.get("global_kill_switch_engaged") is not True or payload.get("redaction_complete") is not True or payload.get("immutable") is not True:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_BUNDLE_SAFETY_GUARD_INVALID")
    if payload.get("live_evidence") is not False:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_LIVE_EVIDENCE_NOT_ALLOWED")
    if any(payload.get(key) != 0 for key in ("network_attempt_count", "write_attempt_count", "external_write_count", "sensitive_material_count")):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_BUNDLE_SIDE_EFFECT_COUNTER_NONZERO")
    if any(payload.get(key) is not False for key in ("authority_claimed", "control_plane_promotion_claimed", "publish_authority_claimed")):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_AUTHORITY_CLAIM_DETECTED")

    bundle_sha256 = _hash(payload)
    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "cp63_contract_id": cp63.contract_id,
        "cp63_contract_hash": cp63.contract_hash,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "zero_write_recorder_id": recorder.recorder_id,
        "zero_write_recorder_hash": recorder.recorder_hash,
        "bundle_sha256": bundle_sha256,
        "evidence_codes": list(expected_codes),
        "evidence_item_count": len(items),
        "replay_trace_count": len(trace),
        "active_platforms": list(EXPECTED_ACTIVE),
        "bundle_schema_validated": True,
        "redaction_validated": True,
        "hash_binding_validated": True,
        "exact_parent_binding_validated": True,
        "synthetic_only": True,
        "live_evidence_imported": False,
        "network_attempted": False,
        "external_write_performed": False,
        "sensitive_material_persisted": False,
        "authority_activated": False,
        "control_plane_promoted": False,
        "publish_authorized": False,
        "state": "PASS_SYNTHETIC_REDACTED_IMPORT_ONLY_NO_LIVE_AUTHORITY",
    }
    import_hash = _hash(body)
    receipt = EvidenceImportReceipt(
        import_id=f"cp64_import_{import_hash[:24]}",
        import_hash=import_hash,
        **{**body, "evidence_codes": expected_codes, "active_platforms": EXPECTED_ACTIVE},
    )
    validate_evidence_import_receipt(receipt)
    return receipt


def validate_evidence_import_receipt(receipt: EvidenceImportReceipt) -> None:
    if receipt.model_version != MODEL_VERSION or receipt.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_IMPORT_RECEIPT_VERSION_DRIFT")
    if receipt.active_platforms != EXPECTED_ACTIVE or receipt.evidence_item_count != len(receipt.evidence_codes):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_IMPORT_RECEIPT_CARDINALITY_DRIFT")
    if not all((receipt.bundle_schema_validated, receipt.redaction_validated, receipt.hash_binding_validated, receipt.exact_parent_binding_validated, receipt.synthetic_only)):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_IMPORT_RECEIPT_REQUIRED_PROOF_MISSING")
    if any((receipt.live_evidence_imported, receipt.network_attempted, receipt.external_write_performed, receipt.sensitive_material_persisted, receipt.authority_activated, receipt.control_plane_promoted, receipt.publish_authorized)):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_IMPORT_RECEIPT_SIDE_EFFECT_OR_AUTHORITY_DETECTED")
    for digest in (receipt.cp63_contract_hash, receipt.session_envelope_hash, receipt.zero_write_recorder_hash, receipt.bundle_sha256):
        if not _is_hex64(digest):
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_IMPORT_RECEIPT_DIGEST_INVALID")
    body = _payload_without_identity(receipt.to_dict(), "import_id", "import_hash")
    expected_hash = _hash(body)
    if receipt.import_hash != expected_hash or receipt.import_id != f"cp64_import_{expected_hash[:24]}":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_IMPORT_RECEIPT_HASH_BINDING_INVALID")


def replay_imported_bundle(
    payload: dict,
    receipt: EvidenceImportReceipt,
    envelope: ProbeSessionEnvelope,
    recorder: ZeroWriteRecorderReceipt,
) -> ReplayValidationReceipt:
    validate_evidence_import_receipt(receipt)
    if _hash(payload) != receipt.bundle_sha256:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_BUNDLE_HASH_MISMATCH")
    trace = payload.get("replay_trace", [])
    if len(trace) != len(envelope.steps) or len(trace) != len(recorder.events):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_CARDINALITY_DRIFT")
    for step, event, observed in zip(envelope.steps, recorder.events, trace):
        expected = {
            "sequence": step.sequence,
            "platform": step.platform,
            "probe_class": step.probe_class,
            "method": step.method,
            "endpoint_label": step.endpoint_label,
            "request_fingerprint_sha256": event.request_fingerprint_sha256,
            "response_fingerprint_sha256": event.response_fingerprint_sha256,
            "network_observed": False,
            "write_observed": False,
        }
        if observed != expected:
            raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_STRUCTURAL_REPLAY_MISMATCH")

    body = {
        "model_version": MODEL_VERSION,
        "checkpoint": CHECKPOINT,
        "import_id": receipt.import_id,
        "import_hash": receipt.import_hash,
        "bundle_sha256": receipt.bundle_sha256,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "zero_write_recorder_id": recorder.recorder_id,
        "zero_write_recorder_hash": recorder.recorder_hash,
        "matched_trace_count": len(trace),
        "expected_trace_count": len(envelope.steps),
        "structural_replay_validated": True,
        "deterministic_order_validated": True,
        "get_only_validated": True,
        "synthetic_endpoints_validated": True,
        "zero_write_validated": True,
        "zero_network_validated": True,
        "live_execution_performed": False,
        "network_attempted": False,
        "external_write_performed": False,
        "authority_activated": False,
        "state": "PASS_OFFLINE_STRUCTURAL_REPLAY_ONLY_NO_LIVE_EXECUTION",
    }
    replay_hash = _hash(body)
    replay = ReplayValidationReceipt(
        replay_id=f"cp64_replay_{replay_hash[:24]}",
        replay_hash=replay_hash,
        **body,
    )
    validate_replay_validation_receipt(replay)
    return replay


def validate_replay_validation_receipt(receipt: ReplayValidationReceipt) -> None:
    if receipt.model_version != MODEL_VERSION or receipt.checkpoint != CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_RECEIPT_VERSION_DRIFT")
    if receipt.matched_trace_count != receipt.expected_trace_count or receipt.expected_trace_count <= 0:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_RECEIPT_CARDINALITY_DRIFT")
    if not all((receipt.structural_replay_validated, receipt.deterministic_order_validated, receipt.get_only_validated, receipt.synthetic_endpoints_validated, receipt.zero_write_validated, receipt.zero_network_validated)):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_RECEIPT_REQUIRED_PROOF_MISSING")
    if any((receipt.live_execution_performed, receipt.network_attempted, receipt.external_write_performed, receipt.authority_activated)):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_RECEIPT_SIDE_EFFECT_DETECTED")
    body = _payload_without_identity(receipt.to_dict(), "replay_id", "replay_hash")
    expected_hash = _hash(body)
    if receipt.replay_hash != expected_hash or receipt.replay_id != f"cp64_replay_{expected_hash[:24]}":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_REPLAY_RECEIPT_HASH_BINDING_INVALID")


def compile_live_read_only_probe_evidence_import(
    root: Path,
    policy: dict,
) -> LiveReadOnlyProbeEvidenceImportContract:
    root = root.resolve()
    _validate_policy(policy)
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    _validate_runtime(runtime)
    _validate_registry(registry)

    cp63_policy = load_json(root / "config" / "live_read_only_probe_session_policy.json")
    cp63 = compile_live_read_only_probe_session(root, cp63_policy)
    validate_live_read_only_probe_session_contract(cp63)
    if cp63.checkpoint != PARENT_SESSION_CHECKPOINT or cp63.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CP63_PARENT_BINDING_DRIFT")

    cp62_policy = load_json(root / "config" / "authorization_receipt_validator_policy.json")
    cp62 = compile_authorization_receipt_validator(root, cp62_policy)
    cp56_policy = load_json(root / "config" / "meta_live_read_only_probe_policy.json")
    envelope = compile_probe_session_envelope(cp62, cp56_policy)
    recorder = record_zero_write_dry_run(envelope)
    validate_probe_session_envelope(cp62, cp56_policy, envelope)
    validate_zero_write_recorder(envelope, recorder)
    if (cp63.session_envelope_id, cp63.session_envelope_hash) != (envelope.envelope_id, envelope.envelope_hash):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_RECOMPILED_ENVELOPE_BINDING_MISMATCH")
    if (cp63.zero_write_recorder_id, cp63.zero_write_recorder_hash) != (recorder.recorder_id, recorder.recorder_hash):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_RECOMPILED_RECORDER_BINDING_MISMATCH")

    bundle = build_synthetic_redacted_bundle(cp63, envelope, recorder, cp56_policy)
    imported = validate_and_import_evidence_bundle(bundle, cp63, envelope, recorder, cp56_policy)
    replayed = replay_imported_bundle(bundle, imported, envelope, recorder)

    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_session_checkpoint": PARENT_SESSION_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "cp63_contract_id": cp63.contract_id,
        "cp63_contract_hash": cp63.contract_hash,
        "session_envelope_id": envelope.envelope_id,
        "session_envelope_hash": envelope.envelope_hash,
        "zero_write_recorder_id": recorder.recorder_id,
        "zero_write_recorder_hash": recorder.recorder_hash,
        "evidence_import_id": imported.import_id,
        "evidence_import_hash": imported.import_hash,
        "replay_validation_id": replayed.replay_id,
        "replay_validation_hash": replayed.replay_hash,
        "policy_sha256": _hash(policy),
        "cp63_policy_sha256": _hash(cp63_policy),
        "cp56_policy_sha256": _hash(cp56_policy),
        "runtime_policy_sha256": _hash(runtime),
        "module_registry_sha256": _hash(registry),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "evidence_import_gate_validated": True,
        "structural_replay_validated": True,
        "global_kill_switch_engaged": True,
        "synthetic_fixture_only": True,
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
    contract = LiveReadOnlyProbeEvidenceImportContract(
        contract_id=f"cp64_contract_{contract_hash[:24]}",
        contract_hash=contract_hash,
        **{**body, "active_platforms": EXPECTED_ACTIVE, "blockers": REQUIRED_BLOCKERS},
    )
    validate_live_read_only_probe_evidence_import_contract(contract)
    return contract


def validate_live_read_only_probe_evidence_import_contract(
    contract: LiveReadOnlyProbeEvidenceImportContract,
) -> None:
    if contract.model_version != MODEL_VERSION or contract.engine_version != ENGINE_VERSION:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTRACT_VERSION_DRIFT")
    if contract.checkpoint != CHECKPOINT or contract.parent_session_checkpoint != PARENT_SESSION_CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTRACT_CHECKPOINT_DRIFT")
    if contract.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTRACT_CONTROL_BINDING_DRIFT")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS or contract.next_unit != NEXT_UNIT:
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTRACT_GATING_DRIFT")
    if not all((contract.evidence_import_gate_validated, contract.structural_replay_validated, contract.global_kill_switch_engaged, contract.synthetic_fixture_only)):
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTRACT_REQUIRED_PROOF_MISSING")
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
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTRACT_SIDE_EFFECT_DETECTED")
    body = _payload_without_identity(contract.to_dict(), "contract_id", "contract_hash")
    expected_hash = _hash(body)
    if contract.contract_hash != expected_hash or contract.contract_id != f"cp64_contract_{expected_hash[:24]}":
        raise LiveReadOnlyProbeEvidenceImportHold("HOLD_CP64_CONTRACT_HASH_BINDING_INVALID")
