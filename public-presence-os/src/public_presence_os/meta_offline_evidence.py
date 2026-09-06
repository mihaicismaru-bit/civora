from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .control import EXPECTED_ACTIVE, canonical_json
from .meta_live_read_only_probe import (
    PLATFORM_PROBE_CLASSES,
    MetaLiveReadOnlyProbeContract,
    validate_live_read_only_probe_contract,
)
from .meta_read_only_gate import REQUIRED_FUTURE_EVIDENCE

MODEL_VERSION = "PPOS_META_OFFLINE_EVIDENCE_BUNDLE_V1"
ENGINE_VERSION = "ppos-meta-offline-evidence-validator-v1.0.0"
STATE = "PASS_SYNTHETIC_EVIDENCE_BUNDLE_AND_OPERATOR_DRY_RUN_LOCAL_ONLY"
FIXTURE_SCOPE = "SYNTHETIC_OFFLINE_ONLY"
SYNTHETIC_API_VERSION = "TEST_API_VERSION_V1"
SYNTHETIC_ENDPOINT_SELECTOR = "SYNTHETIC_OFFLINE_ENDPOINT_ONLY"
HASH_ALGORITHM = "SHA256"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SENSITIVE_KEY = re.compile(
    r"^(?:authorization|cookie|client[_-]?secret|refresh[_-]?token|access[_-]?token|bearer[_-]?token|signing[_-]?secret)$",
    re.I,
)
BEARER_VALUE = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I)


class MetaOfflineEvidenceError(ValueError):
    pass


class MetaOfflineEvidenceHold(MetaOfflineEvidenceError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SyntheticEvidenceRecord:
    code: str
    canonical_payload: str
    payload_sha256: str
    fixture_scope: str = FIXTURE_SCOPE
    state: str = "SYNTHETIC_VALIDATED"
    redacted: bool = True
    canonicalized: bool = True
    hash_algorithm: str = HASH_ALGORITHM
    live_evidence: bool = False
    raw_secret_material_present: bool = False
    external_upload_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OperatorDryRunStep:
    order: int
    step_id: str
    request_class: str
    method: str = "GET"
    endpoint_selector: str = SYNTHETIC_ENDPOINT_SELECTOR
    result: str = "PASS_SYNTHETIC_SERIALIZATION_ONLY"
    endpoint_materialized: bool = False
    secret_reference_resolved: bool = False
    network_attempted: bool = False
    external_write_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MetaOfflineEvidenceBundleReceipt:
    bundle_id: str
    bundle_hash: str
    model_version: str
    engine_version: str
    cp56_contract_id: str
    cp56_contract_hash: str
    platform: str
    mode: str
    validator_policy_sha256: str
    operator_timestamp_utc: str
    api_version_literal: str
    evidence: tuple[SyntheticEvidenceRecord, ...]
    dry_run_steps: tuple[OperatorDryRunStep, ...]
    global_kill_switch_engaged: bool = True
    synthetic_fixture_only: bool = True
    evidence_code_set_exact: bool = True
    zero_write_confirmed: bool = True
    operator_dry_run_passed: bool = True
    live_evidence_claimed: bool = False
    live_entitlement_verified: bool = False
    live_connection_verified: bool = False
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
    pilot_publish_ready: bool = False
    state: str = STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        data["dry_run_steps"] = [item.to_dict() for item in self.dry_run_steps]
        return data


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_sensitive_material(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if SENSITIVE_KEY.fullmatch(key_text):
                raise MetaOfflineEvidenceHold("HOLD_CP57_RAW_SECRET_FIELD_FORBIDDEN")
            _reject_sensitive_material(child, f"{path}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive_material(child, f"{path}[{index}]")
        return
    if isinstance(value, str) and BEARER_VALUE.search(value):
        raise MetaOfflineEvidenceHold("HOLD_CP57_RAW_SECRET_VALUE_FORBIDDEN")


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_META_OFFLINE_EVIDENCE_VALIDATOR_POLICY_V1":
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_SCHEMA")
    if policy.get("checkpoint") != "CP57" or policy.get("module_id") != "M26_META_OFFLINE_EVIDENCE_VALIDATOR":
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_IDENTITY")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise MetaOfflineEvidenceHold("HOLD_CP57_ACTIVE_PLATFORM_DRIFT")
    if policy.get("required_evidence_codes") != list(REQUIRED_FUTURE_EVIDENCE):
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_EVIDENCE_DRIFT")

    contract = policy.get("validator_contract", {})
    required_true = (
        "offline_only",
        "exact_cp56_contract_binding_required",
        "synthetic_fixture_only",
        "evidence_code_set_must_be_exact",
        "canonical_json_required",
        "sha256_binding_required",
        "redaction_guard_required",
        "operator_dry_run_required",
        "global_kill_switch_must_be_engaged",
        "synthetic_api_version_only",
    )
    if any(contract.get(key) is not True for key in required_true):
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_REQUIRED_GUARD_MISSING")
    if contract.get("method_allowlist") != ["GET"]:
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_METHOD_DRIFT")
    if contract.get("mutating_methods_forbidden") != ["POST", "PUT", "PATCH", "DELETE"]:
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_MUTATING_GUARD_DRIFT")
    if contract.get("live_evidence_claim_allowed") is not False or contract.get("pilot_publish_ready") is not False:
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_LIVE_AUTHORITY_DRIFT")

    fixture = policy.get("synthetic_fixture", {})
    if fixture.get("scope") != FIXTURE_SCOPE:
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_FIXTURE_SCOPE_DRIFT")
    if fixture.get("api_version_literal") != SYNTHETIC_API_VERSION:
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_API_VERSION_DRIFT")
    if fixture.get("endpoint_selector") != SYNTHETIC_ENDPOINT_SELECTOR:
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_ENDPOINT_SELECTOR_DRIFT")

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
        raise MetaOfflineEvidenceHold("HOLD_CP57_POLICY_EXTERNAL_AUTHORITY_NOT_ZERO")


def _synthetic_payloads(
    contract: MetaLiveReadOnlyProbeContract,
    operator_timestamp_utc: str,
) -> dict[str, dict]:
    response_seed = {
        "fixture_scope": FIXTURE_SCOPE,
        "platform": contract.platform,
        "mode": contract.mode,
        "request_classes": [step.request_class for step in contract.steps],
        "methods": ["GET" for _ in contract.steps],
        "network_attempted": False,
        "external_write_performed": False,
    }
    response_hash = _hash(response_seed)
    return {
        "LIVE_TOKEN_DEBUG_REDACTED": {
            "fixture_scope": FIXTURE_SCOPE,
            "platform": contract.platform,
            "credential_state": "SYNTHETIC_REDACTED",
            "redacted": True,
        },
        "LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED": {
            "fixture_scope": FIXTURE_SCOPE,
            "platform": contract.platform,
            "identity_reference": "SYNTHETIC_ACCOUNT_REFERENCE",
            "identity_match": True,
            "redacted": True,
        },
        "LIVE_PERMISSION_SET_EXACT": {
            "fixture_scope": FIXTURE_SCOPE,
            "permissions": ["SYNTHETIC_PERMISSION_SET_NOT_LIVE"],
        },
        "LIVE_CAPABILITY_SET_EXACT": {
            "fixture_scope": FIXTURE_SCOPE,
            "capabilities": ["SYNTHETIC_CAPABILITY_SET_NOT_LIVE"],
        },
        "LIVE_EXPIRY_STATE": {
            "fixture_scope": FIXTURE_SCOPE,
            "expiry_state": "SYNTHETIC_KNOWN",
            "expires_at_utc": "2099-12-31T23:59:59Z",
        },
        "LIVE_READ_ONLY_RESPONSE_HASH": {
            "fixture_scope": FIXTURE_SCOPE,
            "sha256": response_hash,
            "live_response": False,
        },
        "OPERATOR_TIMESTAMP_UTC": {
            "fixture_scope": FIXTURE_SCOPE,
            "timestamp_utc": operator_timestamp_utc,
        },
        "API_VERSION_PIN": {
            "fixture_scope": FIXTURE_SCOPE,
            "api_version": SYNTHETIC_API_VERSION,
            "source_binding": "SYNTHETIC_OFFLINE_FIXTURE",
            "live_version_claimed": False,
        },
        "ZERO_WRITE_CONFIRMATION": {
            "fixture_scope": FIXTURE_SCOPE,
            "global_kill_switch_engaged": True,
            "method_allowlist": ["GET"],
            "network_attempted": False,
            "publisher_write_performed": False,
            "queue_mutation_performed": False,
            "external_write_performed": False,
        },
    }


def build_synthetic_evidence_fixture(
    contract: MetaLiveReadOnlyProbeContract,
    operator_timestamp_utc: str,
) -> dict[str, dict]:
    validate_live_read_only_probe_contract(contract)
    if not UTC_RFC3339.fullmatch(operator_timestamp_utc):
        raise MetaOfflineEvidenceHold("HOLD_CP57_OPERATOR_TIMESTAMP_INVALID")
    return _synthetic_payloads(contract, operator_timestamp_utc)


def _validate_fixture(
    fixture: Mapping[str, Any],
    contract: MetaLiveReadOnlyProbeContract,
    operator_timestamp_utc: str,
) -> tuple[SyntheticEvidenceRecord, ...]:
    if tuple(fixture.keys()) != REQUIRED_FUTURE_EVIDENCE:
        raise MetaOfflineEvidenceHold("HOLD_CP57_EVIDENCE_CODE_SET_DRIFT")

    records: list[SyntheticEvidenceRecord] = []
    for code in REQUIRED_FUTURE_EVIDENCE:
        payload = fixture[code]
        if not isinstance(payload, Mapping):
            raise MetaOfflineEvidenceHold("HOLD_CP57_EVIDENCE_PAYLOAD_TYPE")
        _reject_sensitive_material(payload)
        if payload.get("fixture_scope") != FIXTURE_SCOPE:
            raise MetaOfflineEvidenceHold("HOLD_CP57_NON_SYNTHETIC_EVIDENCE_FORBIDDEN")
        canonical = canonical_json(payload)
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        records.append(SyntheticEvidenceRecord(code=code, canonical_payload=canonical, payload_sha256=digest))

    decoded = {item.code: json.loads(item.canonical_payload) for item in records}
    if decoded["OPERATOR_TIMESTAMP_UTC"].get("timestamp_utc") != operator_timestamp_utc:
        raise MetaOfflineEvidenceHold("HOLD_CP57_OPERATOR_TIMESTAMP_BINDING_DRIFT")
    version = decoded["API_VERSION_PIN"]
    if version.get("api_version") != SYNTHETIC_API_VERSION or version.get("live_version_claimed") is not False:
        raise MetaOfflineEvidenceHold("HOLD_CP57_API_VERSION_FIXTURE_DRIFT")
    zero_write = decoded["ZERO_WRITE_CONFIRMATION"]
    expected_zero = {
        "global_kill_switch_engaged": True,
        "network_attempted": False,
        "publisher_write_performed": False,
        "queue_mutation_performed": False,
        "external_write_performed": False,
    }
    if any(zero_write.get(key) is not value for key, value in expected_zero.items()):
        raise MetaOfflineEvidenceHold("HOLD_CP57_ZERO_WRITE_FIXTURE_DRIFT")
    if zero_write.get("method_allowlist") != ["GET"]:
        raise MetaOfflineEvidenceHold("HOLD_CP57_ZERO_WRITE_METHOD_DRIFT")

    identity = decoded["LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED"]
    if identity.get("platform") != contract.platform or identity.get("identity_reference") != "SYNTHETIC_ACCOUNT_REFERENCE":
        raise MetaOfflineEvidenceHold("HOLD_CP57_SYNTHETIC_IDENTITY_DRIFT")
    return tuple(records)


def _dry_run_steps(contract: MetaLiveReadOnlyProbeContract) -> tuple[OperatorDryRunStep, ...]:
    expected_classes = PLATFORM_PROBE_CLASSES[contract.platform]
    if tuple(step.request_class for step in contract.steps) != expected_classes:
        raise MetaOfflineEvidenceHold("HOLD_CP57_CP56_PROBE_CLASS_DRIFT")
    return tuple(
        OperatorDryRunStep(
            order=index + 1,
            step_id=f"DRY{index + 1:02d}",
            request_class=request_class,
        )
        for index, request_class in enumerate(expected_classes)
    )


def compile_offline_evidence_bundle(
    contract: MetaLiveReadOnlyProbeContract,
    policy: dict,
    *,
    operator_timestamp_utc: str,
    fixture: Mapping[str, Any] | None = None,
) -> MetaOfflineEvidenceBundleReceipt:
    validate_live_read_only_probe_contract(contract)
    _validate_policy(policy)
    if contract.platform not in EXPECTED_ACTIVE:
        raise MetaOfflineEvidenceHold("HOLD_CP57_PLATFORM_NOT_ACTIVE")
    if not contract.global_kill_switch_required_engaged:
        raise MetaOfflineEvidenceHold("HOLD_CP57_CP56_KILL_SWITCH_DRIFT")
    if contract.live_probe_authorized or contract.network_attempted or contract.account_connected:
        raise MetaOfflineEvidenceHold("HOLD_CP57_CP56_EXTERNAL_AUTHORITY_DRIFT")
    if any(item.state != "NOT_CAPTURED" for item in contract.evidence_contract):
        raise MetaOfflineEvidenceHold("HOLD_CP57_CP56_PRETENDED_LIVE_EVIDENCE")
    if not UTC_RFC3339.fullmatch(operator_timestamp_utc):
        raise MetaOfflineEvidenceHold("HOLD_CP57_OPERATOR_TIMESTAMP_INVALID")

    policy_hash = _hash(policy)
    fixture_value = fixture if fixture is not None else build_synthetic_evidence_fixture(contract, operator_timestamp_utc)
    evidence = _validate_fixture(fixture_value, contract, operator_timestamp_utc)
    steps = _dry_run_steps(contract)
    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "cp56_contract_id": contract.contract_id,
        "cp56_contract_hash": contract.contract_hash,
        "platform": contract.platform,
        "mode": contract.mode,
        "validator_policy_sha256": policy_hash,
        "operator_timestamp_utc": operator_timestamp_utc,
        "api_version_literal": SYNTHETIC_API_VERSION,
        "evidence": [item.to_dict() for item in evidence],
        "dry_run_steps": [item.to_dict() for item in steps],
        "global_kill_switch_engaged": True,
        "synthetic_fixture_only": True,
        "evidence_code_set_exact": True,
        "zero_write_confirmed": True,
        "operator_dry_run_passed": True,
        "live_evidence_claimed": False,
        "live_entitlement_verified": False,
        "live_connection_verified": False,
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
        "pilot_publish_ready": False,
        "state": STATE,
    }
    bundle_hash = _hash(body)
    receipt = MetaOfflineEvidenceBundleReceipt(
        bundle_id="moeb_" + bundle_hash[:24],
        bundle_hash=bundle_hash,
        model_version=MODEL_VERSION,
        engine_version=ENGINE_VERSION,
        cp56_contract_id=contract.contract_id,
        cp56_contract_hash=contract.contract_hash,
        platform=contract.platform,
        mode=contract.mode,
        validator_policy_sha256=policy_hash,
        operator_timestamp_utc=operator_timestamp_utc,
        api_version_literal=SYNTHETIC_API_VERSION,
        evidence=evidence,
        dry_run_steps=steps,
    )
    validate_offline_evidence_bundle_receipt(receipt)
    return receipt


def validate_offline_evidence_bundle_receipt(receipt: MetaOfflineEvidenceBundleReceipt) -> None:
    if not isinstance(receipt, MetaOfflineEvidenceBundleReceipt):
        raise MetaOfflineEvidenceHold("HOLD_CP57_RECEIPT_TYPE")
    if receipt.model_version != MODEL_VERSION or receipt.engine_version != ENGINE_VERSION:
        raise MetaOfflineEvidenceHold("HOLD_CP57_RECEIPT_VERSION")
    if receipt.platform not in EXPECTED_ACTIVE:
        raise MetaOfflineEvidenceHold("HOLD_CP57_PLATFORM_NOT_ACTIVE")
    for digest in (receipt.bundle_hash, receipt.cp56_contract_hash, receipt.validator_policy_sha256):
        if not HEX64.fullmatch(digest):
            raise MetaOfflineEvidenceHold("HOLD_CP57_BINDING_HASH_INVALID")
    if not UTC_RFC3339.fullmatch(receipt.operator_timestamp_utc):
        raise MetaOfflineEvidenceHold("HOLD_CP57_OPERATOR_TIMESTAMP_INVALID")
    if receipt.api_version_literal != SYNTHETIC_API_VERSION:
        raise MetaOfflineEvidenceHold("HOLD_CP57_API_VERSION_FIXTURE_DRIFT")
    if tuple(item.code for item in receipt.evidence) != REQUIRED_FUTURE_EVIDENCE:
        raise MetaOfflineEvidenceHold("HOLD_CP57_EVIDENCE_CODE_SET_DRIFT")
    for item in receipt.evidence:
        if item.fixture_scope != FIXTURE_SCOPE or item.state != "SYNTHETIC_VALIDATED":
            raise MetaOfflineEvidenceHold("HOLD_CP57_EVIDENCE_STATE_DRIFT")
        if not item.redacted or not item.canonicalized or item.hash_algorithm != HASH_ALGORITHM:
            raise MetaOfflineEvidenceHold("HOLD_CP57_EVIDENCE_GUARD_DRIFT")
        if item.live_evidence or item.raw_secret_material_present or item.external_upload_performed:
            raise MetaOfflineEvidenceHold("HOLD_CP57_EVIDENCE_EXTERNAL_AUTHORITY_FORBIDDEN")
        parsed = json.loads(item.canonical_payload)
        _reject_sensitive_material(parsed)
        if parsed.get("fixture_scope") != FIXTURE_SCOPE:
            raise MetaOfflineEvidenceHold("HOLD_CP57_NON_SYNTHETIC_EVIDENCE_FORBIDDEN")
        if item.payload_sha256 != sha256(item.canonical_payload.encode("utf-8")).hexdigest():
            raise MetaOfflineEvidenceHold("HOLD_CP57_EVIDENCE_HASH_MISMATCH")
    expected_classes = PLATFORM_PROBE_CLASSES[receipt.platform]
    if tuple(step.request_class for step in receipt.dry_run_steps) != expected_classes:
        raise MetaOfflineEvidenceHold("HOLD_CP57_DRY_RUN_CLASS_DRIFT")
    if tuple(step.order for step in receipt.dry_run_steps) != tuple(range(1, len(receipt.dry_run_steps) + 1)):
        raise MetaOfflineEvidenceHold("HOLD_CP57_DRY_RUN_ORDER_DRIFT")
    for step in receipt.dry_run_steps:
        if step.method != "GET" or step.endpoint_selector != SYNTHETIC_ENDPOINT_SELECTOR:
            raise MetaOfflineEvidenceHold("HOLD_CP57_DRY_RUN_METHOD_OR_ENDPOINT_DRIFT")
        if step.endpoint_materialized or step.secret_reference_resolved or step.network_attempted or step.external_write_performed:
            raise MetaOfflineEvidenceHold("HOLD_CP57_DRY_RUN_EXTERNAL_AUTHORITY_FORBIDDEN")
        if step.result != "PASS_SYNTHETIC_SERIALIZATION_ONLY":
            raise MetaOfflineEvidenceHold("HOLD_CP57_DRY_RUN_RESULT_DRIFT")
    if not all((
        receipt.global_kill_switch_engaged,
        receipt.synthetic_fixture_only,
        receipt.evidence_code_set_exact,
        receipt.zero_write_confirmed,
        receipt.operator_dry_run_passed,
    )):
        raise MetaOfflineEvidenceHold("HOLD_CP57_FAIL_CLOSED_GUARD_DRIFT")
    if any((
        receipt.live_evidence_claimed,
        receipt.live_entitlement_verified,
        receipt.live_connection_verified,
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
        receipt.pilot_publish_ready,
    )):
        raise MetaOfflineEvidenceHold("HOLD_CP57_EXTERNAL_AUTHORITY_FORBIDDEN")
    if receipt.state != STATE:
        raise MetaOfflineEvidenceHold("HOLD_CP57_RECEIPT_STATE")
    body = receipt.to_dict()
    body.pop("bundle_id")
    body.pop("bundle_hash")
    expected_hash = _hash(body)
    if receipt.bundle_hash != expected_hash:
        raise MetaOfflineEvidenceHold("HOLD_CP57_RECEIPT_HASH_MISMATCH")
    if receipt.bundle_id != "moeb_" + receipt.bundle_hash[:24]:
        raise MetaOfflineEvidenceHold("HOLD_CP57_RECEIPT_ID_MISMATCH")


def render_offline_evidence_bundle_json(receipt: MetaOfflineEvidenceBundleReceipt) -> str:
    validate_offline_evidence_bundle_receipt(receipt)
    return canonical_json(receipt.to_dict()) + "\n"
