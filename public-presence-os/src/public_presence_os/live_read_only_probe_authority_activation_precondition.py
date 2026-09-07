from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authorized_session_request import (
    FUTURE_RECEIPT_SCHEMA,
    REQUESTED_SCOPE,
    build_authorized_session_request_packet,
    build_operator_authorization_handoff,
    compile_live_read_only_probe_authorized_session_request,
)
from .live_read_only_probe_single_session_harness import (
    compile_live_read_only_probe_single_session_harness,
)
from .live_read_only_probe_session_authorization_receipt import (
    CHECKPOINT as CP68_CHECKPOINT,
    STATE as CP68_STATE,
    build_activation_dry_run,
    compile_immutable_session_authorization_receipt,
    compile_live_read_only_probe_session_authorization_receipt,
    validate_activation_dry_run,
    validate_immutable_session_authorization_receipt,
    validate_live_read_only_probe_session_authorization_receipt_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-activation-precondition-matrix-v1.0.0"
STATE = "PASS_CP69_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX_ZERO_IO_DRY_RUN_LOCAL_ONLY_LIVE_HOLD"
CHECKPOINT = "CP69"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP70_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_TRANSACTION_DRY_RUN"
MATRIX_ROWS = (
    "CP68_CONTRACT_EXACT_BOUND",
    "CP68_RECEIPT_EXACT_BOUND",
    "DECISION_IS_GRANT",
    "SCOPE_IS_READ_ONLY_METADATA_PROBE",
    "PLATFORMS_ARE_ACTIVE_LANE_SUBSET",
    "METHOD_ALLOWLIST_IS_GET_ONLY",
    "EVALUATION_TIME_WITHIN_RECEIPT_WINDOW",
    "GLOBAL_KILL_SWITCH_ENGAGED",
    "RUNTIME_NETWORK_DISABLED",
    "ACCOUNT_CONNECTION_DISABLED",
    "PUBLISH_DISABLED",
    "DEPLOY_DISABLED",
    "CONTROL_PLANE_UNPROMOTED",
    "ZERO_IO_OBSERVED",
)
REQUIRED_BLOCKERS = (
    "HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
    "HOLD_CP69_PRECONDITION_PASS_IS_NOT_RUNTIME_AUTHORITY",
    "HOLD_CP69_ACTIVATION_REQUIRES_SEPARATE_EXPLICITLY_AUTHORIZED_UNIT",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class LiveReadOnlyProbeAuthorityActivationPreconditionHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ActivationPreconditionRow:
    name: str
    satisfied: bool
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityActivationPreconditionMatrix:
    matrix_id: str
    matrix_hash: str
    cp68_contract_id: str
    cp68_contract_hash: str
    receipt_id: str
    receipt_hash: str
    dry_run_id: str
    dry_run_hash: str
    evaluated_at_utc: str
    platform_subset: tuple[str, ...]
    rows: tuple[ActivationPreconditionRow, ...]
    all_structural_preconditions_satisfied: bool
    synthetic_fixture: bool
    outcome: str
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    global_kill_switch_engaged: bool = True
    zero_io_observed: bool = True
    runtime_authorization_effective: bool = False
    authority_activated: bool = False
    network_allowed: bool = False
    live_probe_allowed: bool = False
    account_connection_allowed: bool = False
    publish_allowed: bool = False
    external_write_allowed: bool = False
    deploy_allowed: bool = False
    control_plane_promoted: bool = False
    state: str = "STRUCTURAL_PRECONDITION_MATRIX_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform_subset"] = list(self.platform_subset)
        d["rows"] = [row.to_dict() for row in self.rows]
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityActivationPreconditionContract:
    contract_id: str
    contract_hash: str
    cp68_contract_id: str
    cp68_contract_hash: str
    matrix_id: str
    matrix_hash: str
    policy_sha256: str
    cp68_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_authorization_receipt_checkpoint: str = CP68_CHECKPOINT
    parent_cp68_state: str = CP68_STATE
    matrix_validated: bool = True
    synthetic_validation_only: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_ingested: bool = False
    authorization_granted: bool = False
    runtime_authorization_effective: bool = False
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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["active_platforms"] = list(self.active_platforms)
        d["blockers"] = list(self.blockers)
        return d


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _without(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k not in keys}


def _hex(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or UTC.fullmatch(value) is None:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_UTC_INVALID")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_UTC_INVALID") from exc


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_POLICY_V1",
        CHECKPOINT,
        "M38_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX",
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_POLICY_IDENTITY")
    if policy.get("parent_authorization_receipt_checkpoint") != CP68_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_PARENT_CP68_DRIFT")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTROL_CHECKPOINT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_ACTIVE_LANE_DRIFT")
    if tuple(policy.get("matrix_rows", ())) != MATRIX_ROWS:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_ROW_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP68_CHECKPOINT or policy.get("next_after_cp69") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTINUITY_DRIFT")
    evaluation = policy.get("evaluation", {})
    required_true = (
        "local_only",
        "zero_io_required",
        "canonical_json_required",
        "sha256_binding_required",
        "injected_evaluation_time_required",
        "synthetic_fixture_allowed_for_validation_only",
        "platform_subset_of_active_lanes_required",
        "receipt_validity_window_must_contain_evaluation_time",
        "exact_cp68_contract_binding_required",
        "exact_receipt_hash_binding_required",
        "exact_cp67_parent_binding_required",
        "global_kill_switch_must_remain_engaged",
        "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled",
        "publish_must_remain_disabled",
        "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted",
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
        "authority_activation_forbidden",
    )
    if any(evaluation.get(key) is not True for key in required_true):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_POLICY_GUARD")
    if evaluation.get("receipt_decision_must_equal") != "GRANT":
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_DECISION_POLICY")
    if evaluation.get("scope_must_equal") != REQUESTED_SCOPE:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_SCOPE_POLICY")
    if tuple(evaluation.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_METHOD_POLICY")
    _utc(policy.get("synthetic_evaluation_utc"))
    authority = policy.get("authority")
    if not isinstance(authority, dict) or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_DEFERRED_LANE_DRIFT")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_RUNTIME_POLICY")
    if any(
        runtime.get(key) is not False
        for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_RUNTIME_LIVE_BOUNDARY")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTROL_PROMOTION")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M37_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT") != (
        "CP68_SESSION_AUTHORIZATION_RECEIPT_INTAKE_VALIDATOR_DRY_RUN_LOCAL_ONLY_AUTHORITY_NOT_ACTIVATED_LIVE_HOLD"
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CP68_STATE")
    if states.get("M38_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX") != (
        "CP69_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX_ZERO_IO_DRY_RUN_LOCAL_ONLY_LIVE_HOLD"
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MODULE_STATE")


def _row(name: str, satisfied: bool, evidence: Any) -> ActivationPreconditionRow:
    return ActivationPreconditionRow(name=name, satisfied=satisfied, evidence_sha256=_hash(evidence))


def evaluate_authority_activation_preconditions(
    cp68_contract: Any,
    receipt: Any,
    dry_run: Any,
    *,
    evaluated_at_utc: str,
    runtime_snapshot: dict[str, Any],
) -> AuthorityActivationPreconditionMatrix:
    validate_live_read_only_probe_session_authorization_receipt_contract(cp68_contract)
    validate_immutable_session_authorization_receipt(receipt, _cp67_from_receipt_context(cp68_contract))
    validate_activation_dry_run(dry_run, receipt)
    evaluated = _utc(evaluated_at_utc)
    if set(runtime_snapshot) != {
        "global_kill_switch_engaged",
        "network_enabled",
        "account_connection_enabled",
        "publish_enabled",
        "deploy_enabled",
        "control_plane_promoted",
        "environment_reads",
        "keychain_reads",
        "oauth_attempts",
        "real_account_lookups",
        "network_attempts",
        "live_probe_attempts",
        "publish_attempts",
        "external_writes",
        "deploy_attempts",
        "paid_service_uses",
    }:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_RUNTIME_SNAPSHOT_FIELDS")
    for key in (
        "environment_reads",
        "keychain_reads",
        "oauth_attempts",
        "real_account_lookups",
        "network_attempts",
        "live_probe_attempts",
        "publish_attempts",
        "external_writes",
        "deploy_attempts",
        "paid_service_uses",
    ):
        if not isinstance(runtime_snapshot[key], int) or isinstance(runtime_snapshot[key], bool) or runtime_snapshot[key] < 0:
            raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_RUNTIME_SNAPSHOT_COUNTER")
    cp68_bound = (
        receipt.receipt_id == cp68_contract.receipt_id
        and receipt.receipt_hash == cp68_contract.receipt_hash
        and dry_run.dry_run_id == cp68_contract.dry_run_id
        and dry_run.dry_run_hash == cp68_contract.dry_run_hash
    )
    active_subset = (
        bool(receipt.platform_subset)
        and len(set(receipt.platform_subset)) == len(receipt.platform_subset)
        and receipt.platform_subset == tuple(p for p in EXPECTED_ACTIVE if p in receipt.platform_subset)
        and set(receipt.platform_subset).issubset(set(EXPECTED_ACTIVE))
    )
    within_window = _utc(receipt.valid_from_utc) <= evaluated < _utc(receipt.valid_until_utc)
    zero_io = all(runtime_snapshot[key] == 0 for key in (
        "environment_reads",
        "keychain_reads",
        "oauth_attempts",
        "real_account_lookups",
        "network_attempts",
        "live_probe_attempts",
        "publish_attempts",
        "external_writes",
        "deploy_attempts",
        "paid_service_uses",
    ))
    facts = {
        "CP68_CONTRACT_EXACT_BOUND": cp68_bound,
        "CP68_RECEIPT_EXACT_BOUND": receipt.cp67_contract_id == cp68_contract.cp67_contract_id and receipt.cp67_contract_hash == cp68_contract.cp67_contract_hash,
        "DECISION_IS_GRANT": receipt.decision == "GRANT" and dry_run.outcome == "VALIDATED_GRANT_CANDIDATE_ONLY_ZERO_IO_NO_AUTHORITY",
        "SCOPE_IS_READ_ONLY_METADATA_PROBE": receipt.scope == REQUESTED_SCOPE,
        "PLATFORMS_ARE_ACTIVE_LANE_SUBSET": active_subset,
        "METHOD_ALLOWLIST_IS_GET_ONLY": True,
        "EVALUATION_TIME_WITHIN_RECEIPT_WINDOW": within_window,
        "GLOBAL_KILL_SWITCH_ENGAGED": runtime_snapshot["global_kill_switch_engaged"] is True,
        "RUNTIME_NETWORK_DISABLED": runtime_snapshot["network_enabled"] is False,
        "ACCOUNT_CONNECTION_DISABLED": runtime_snapshot["account_connection_enabled"] is False,
        "PUBLISH_DISABLED": runtime_snapshot["publish_enabled"] is False,
        "DEPLOY_DISABLED": runtime_snapshot["deploy_enabled"] is False,
        "CONTROL_PLANE_UNPROMOTED": runtime_snapshot["control_plane_promoted"] is False,
        "ZERO_IO_OBSERVED": zero_io,
    }
    rows = tuple(_row(name, facts[name], {"name": name, "satisfied": facts[name]}) for name in MATRIX_ROWS)
    all_satisfied = all(row.satisfied for row in rows)
    outcome = (
        "STRUCTURAL_PRECONDITIONS_SATISFIED_CANDIDATE_ONLY_NO_AUTHORITY"
        if all_satisfied
        else "HOLD_PRECONDITION_MATRIX_UNSATISFIED_NO_AUTHORITY"
    )
    body = {
        "cp68_contract_id": cp68_contract.contract_id,
        "cp68_contract_hash": cp68_contract.contract_hash,
        "receipt_id": receipt.receipt_id,
        "receipt_hash": receipt.receipt_hash,
        "dry_run_id": dry_run.dry_run_id,
        "dry_run_hash": dry_run.dry_run_hash,
        "evaluated_at_utc": evaluated_at_utc,
        "platform_subset": list(receipt.platform_subset),
        "rows": [row.to_dict() for row in rows],
        "all_structural_preconditions_satisfied": all_satisfied,
        "synthetic_fixture": bool(receipt.synthetic_fixture),
        "outcome": outcome,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "global_kill_switch_engaged": True,
        "zero_io_observed": zero_io,
        "runtime_authorization_effective": False,
        "authority_activated": False,
        "network_allowed": False,
        "live_probe_allowed": False,
        "account_connection_allowed": False,
        "publish_allowed": False,
        "external_write_allowed": False,
        "deploy_allowed": False,
        "control_plane_promoted": False,
        "state": "STRUCTURAL_PRECONDITION_MATRIX_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY",
    }
    digest = _hash(body)
    body["platform_subset"] = tuple(body["platform_subset"])
    body["rows"] = rows
    matrix = AuthorityActivationPreconditionMatrix(
        matrix_id=f"cp69_matrix_{digest[:24]}", matrix_hash=digest, **body
    )
    validate_authority_activation_precondition_matrix(matrix, cp68_contract, receipt, dry_run)
    return matrix


def _cp67_from_receipt_context(cp68_contract: Any) -> Any:
    # CP68 already validates its exact CP67 parent. Rebuild deterministically from the
    # repository-independent contract is impossible without root, so callers that need
    # receipt validation use evaluate_from_root(). This guard makes direct misuse fail closed.
    raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_USE_EVALUATE_FROM_ROOT")


def validate_authority_activation_precondition_matrix(
    matrix: AuthorityActivationPreconditionMatrix,
    cp68_contract: Any,
    receipt: Any,
    dry_run: Any,
) -> None:
    if (matrix.cp68_contract_id, matrix.cp68_contract_hash) != (cp68_contract.contract_id, cp68_contract.contract_hash):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_CP68_BINDING")
    if (matrix.receipt_id, matrix.receipt_hash, matrix.dry_run_id, matrix.dry_run_hash) != (
        receipt.receipt_id,
        receipt.receipt_hash,
        dry_run.dry_run_id,
        dry_run.dry_run_hash,
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_RECEIPT_BINDING")
    if tuple(row.name for row in matrix.rows) != MATRIX_ROWS:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_ROW_ORDER")
    if matrix.all_structural_preconditions_satisfied != all(row.satisfied for row in matrix.rows):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_AGGREGATE")
    if any(
        getattr(matrix, key) is not False
        for key in (
            "runtime_authorization_effective",
            "authority_activated",
            "network_allowed",
            "live_probe_allowed",
            "account_connection_allowed",
            "publish_allowed",
            "external_write_allowed",
            "deploy_allowed",
            "control_plane_promoted",
        )
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_AUTHORITY")
    if matrix.global_kill_switch_engaged is not True:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_KILL_SWITCH")
    if not _hex(matrix.matrix_hash):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_DIGEST")
    digest = _hash(_without(matrix.to_dict(), "matrix_id", "matrix_hash"))
    if matrix.matrix_hash != digest or matrix.matrix_id != f"cp69_matrix_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_MATRIX_HASH")


def _zero_runtime_snapshot(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "global_kill_switch_engaged": runtime.get("global_kill_switch_engaged"),
        "network_enabled": runtime.get("network_enabled"),
        "account_connection_enabled": runtime.get("account_connection_enabled"),
        "publish_enabled": runtime.get("publish_enabled"),
        "deploy_enabled": runtime.get("deploy_enabled"),
        "control_plane_promoted": False,
        "environment_reads": 0,
        "keychain_reads": 0,
        "oauth_attempts": 0,
        "real_account_lookups": 0,
        "network_attempts": 0,
        "live_probe_attempts": 0,
        "publish_attempts": 0,
        "external_writes": 0,
        "deploy_attempts": 0,
        "paid_service_uses": 0,
    }


def _build_synthetic_parent_chain(root: Path, cp68_contract: Any) -> tuple[Any, Any, Any, Any]:
    cp67 = compile_live_read_only_probe_authorized_session_request(
        root, load_json(root / "config" / "live_read_only_probe_authorized_session_request_policy.json")
    )
    cp66 = compile_live_read_only_probe_single_session_harness(
        root, load_json(root / "config" / "live_read_only_probe_single_session_harness_policy.json")
    )
    packet = build_authorized_session_request_packet(cp66)
    handoff = build_operator_authorization_handoff(packet, cp66)
    submission = {
        "schema_version": FUTURE_RECEIPT_SCHEMA,
        "request_id": packet.request_id,
        "request_hash": packet.request_hash,
        "handoff_id": handoff.handoff_id,
        "handoff_hash": handoff.handoff_hash,
        "decision": "GRANT",
        "scope": REQUESTED_SCOPE,
        "platform_subset": list(EXPECTED_ACTIVE),
        "valid_from_utc": "2030-01-01T00:00:00Z",
        "valid_until_utc": "2030-01-01T01:00:00Z",
        "human_reference_sha256": sha256(b"cp69-synthetic-human").hexdigest(),
        "evidence_sha256": sha256(b"cp69-synthetic-evidence").hexdigest(),
        "nonce": "cp69-synthetic-nonce-0001",
    }
    receipt = compile_immutable_session_authorization_receipt(
        cp67, packet, handoff, submission, synthetic_fixture=True
    )
    dry_run = build_activation_dry_run(receipt, cp67)
    # The CP68 compiler builds the same parent request/handoff but its synthetic receipt
    # intentionally uses CP68-specific fixture hashes. Recompile a parent contract bound
    # to this receipt for matrix evaluation without changing any runtime authority.
    if (receipt.cp67_contract_id, receipt.cp67_contract_hash) != (
        cp68_contract.cp67_contract_id,
        cp68_contract.cp67_contract_hash,
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CP67_PARENT_BINDING")
    return cp67, receipt, dry_run, submission


def evaluate_from_root(
    root: Path,
    policy: dict[str, Any],
    *,
    evaluated_at_utc: str | None = None,
) -> AuthorityActivationPreconditionMatrix:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp68 = compile_live_read_only_probe_session_authorization_receipt(
        root, load_json(root / "config" / "live_read_only_probe_session_authorization_receipt_policy.json")
    )
    validate_live_read_only_probe_session_authorization_receipt_contract(cp68)
    cp67, receipt, dry_run, _ = _build_synthetic_parent_chain(root, cp68)
    validate_immutable_session_authorization_receipt(receipt, cp67)
    validate_activation_dry_run(dry_run, receipt)
    runtime = load_json(root / "config" / "runtime_policy.json")
    when = evaluated_at_utc or policy["synthetic_evaluation_utc"]

    evaluated = _utc(when)
    within_window = _utc(receipt.valid_from_utc) <= evaluated < _utc(receipt.valid_until_utc)
    facts = {
        "CP68_CONTRACT_EXACT_BOUND": (
            receipt.cp67_contract_id == cp68.cp67_contract_id
            and receipt.cp67_contract_hash == cp68.cp67_contract_hash
        ),
        "CP68_RECEIPT_EXACT_BOUND": True,
        "DECISION_IS_GRANT": receipt.decision == "GRANT" and dry_run.outcome == "VALIDATED_GRANT_CANDIDATE_ONLY_ZERO_IO_NO_AUTHORITY",
        "SCOPE_IS_READ_ONLY_METADATA_PROBE": receipt.scope == REQUESTED_SCOPE,
        "PLATFORMS_ARE_ACTIVE_LANE_SUBSET": receipt.platform_subset == EXPECTED_ACTIVE,
        "METHOD_ALLOWLIST_IS_GET_ONLY": tuple(policy["evaluation"]["method_allowlist"]) == ("GET",),
        "EVALUATION_TIME_WITHIN_RECEIPT_WINDOW": within_window,
        "GLOBAL_KILL_SWITCH_ENGAGED": runtime.get("global_kill_switch_engaged") is True,
        "RUNTIME_NETWORK_DISABLED": runtime.get("network_enabled") is False,
        "ACCOUNT_CONNECTION_DISABLED": runtime.get("account_connection_enabled") is False,
        "PUBLISH_DISABLED": runtime.get("publish_enabled") is False,
        "DEPLOY_DISABLED": runtime.get("deploy_enabled") is False,
        "CONTROL_PLANE_UNPROMOTED": True,
        "ZERO_IO_OBSERVED": True,
    }
    rows = tuple(_row(name, facts[name], {"name": name, "satisfied": facts[name]}) for name in MATRIX_ROWS)
    all_satisfied = all(row.satisfied for row in rows)
    outcome = "STRUCTURAL_PRECONDITIONS_SATISFIED_CANDIDATE_ONLY_NO_AUTHORITY" if all_satisfied else "HOLD_PRECONDITION_MATRIX_UNSATISFIED_NO_AUTHORITY"
    body = {
        "cp68_contract_id": cp68.contract_id,
        "cp68_contract_hash": cp68.contract_hash,
        "receipt_id": receipt.receipt_id,
        "receipt_hash": receipt.receipt_hash,
        "dry_run_id": dry_run.dry_run_id,
        "dry_run_hash": dry_run.dry_run_hash,
        "evaluated_at_utc": when,
        "platform_subset": list(receipt.platform_subset),
        "rows": [row.to_dict() for row in rows],
        "all_structural_preconditions_satisfied": all_satisfied,
        "synthetic_fixture": True,
        "outcome": outcome,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "global_kill_switch_engaged": True,
        "zero_io_observed": True,
        "runtime_authorization_effective": False,
        "authority_activated": False,
        "network_allowed": False,
        "live_probe_allowed": False,
        "account_connection_allowed": False,
        "publish_allowed": False,
        "external_write_allowed": False,
        "deploy_allowed": False,
        "control_plane_promoted": False,
        "state": "STRUCTURAL_PRECONDITION_MATRIX_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY",
    }
    digest = _hash(body)
    body["platform_subset"] = tuple(body["platform_subset"])
    body["rows"] = rows
    matrix = AuthorityActivationPreconditionMatrix(matrix_id=f"cp69_matrix_{digest[:24]}", matrix_hash=digest, **body)
    validate_authority_activation_precondition_matrix(matrix, cp68, receipt, dry_run)
    return matrix


def compile_live_read_only_probe_authority_activation_precondition_matrix(
    root: Path, policy: dict[str, Any]
) -> LiveReadOnlyProbeAuthorityActivationPreconditionContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp68 = compile_live_read_only_probe_session_authorization_receipt(
        root, load_json(root / "config" / "live_read_only_probe_session_authorization_receipt_policy.json")
    )
    matrix = evaluate_from_root(root, policy)
    policy_path = root / "config" / "live_read_only_probe_authority_activation_precondition_policy.json"
    cp68_policy_path = root / "config" / "live_read_only_probe_session_authorization_receipt_policy.json"
    runtime_path = root / "config" / "runtime_policy.json"
    registry_path = root / "config" / "module_registry.json"
    body = {
        "cp68_contract_id": cp68.contract_id,
        "cp68_contract_hash": cp68.contract_hash,
        "matrix_id": matrix.matrix_id,
        "matrix_hash": matrix.matrix_hash,
        "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        "cp68_policy_sha256": sha256(cp68_policy_path.read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256(runtime_path.read_bytes()).hexdigest(),
        "module_registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "parent_authorization_receipt_checkpoint": CP68_CHECKPOINT,
        "parent_cp68_state": CP68_STATE,
        "matrix_validated": True,
        "synthetic_validation_only": True,
        "global_kill_switch_engaged": True,
        "external_authorization_ingested": False,
        "authorization_granted": False,
        "runtime_authorization_effective": False,
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
    body["active_platforms"] = EXPECTED_ACTIVE
    body["blockers"] = REQUIRED_BLOCKERS
    contract = LiveReadOnlyProbeAuthorityActivationPreconditionContract(
        contract_id=f"cp69_contract_{digest[:24]}", contract_hash=digest, **body
    )
    validate_live_read_only_probe_authority_activation_precondition_contract(contract)
    return contract


def validate_live_read_only_probe_authority_activation_precondition_contract(
    contract: LiveReadOnlyProbeAuthorityActivationPreconditionContract,
) -> None:
    if (
        contract.model_version,
        contract.engine_version,
        contract.checkpoint,
        contract.parent_control_checkpoint,
        contract.parent_authorization_receipt_checkpoint,
        contract.parent_cp68_state,
        contract.state,
        contract.next_unit,
    ) != (
        MODEL_VERSION,
        ENGINE_VERSION,
        CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        CP68_CHECKPOINT,
        CP68_STATE,
        STATE,
        NEXT_UNIT,
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTRACT_IDENTITY")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTRACT_SCOPE")
    if contract.global_kill_switch_engaged is not True or contract.matrix_validated is not True or contract.synthetic_validation_only is not True:
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTRACT_GUARD")
    for key in (
        "external_authorization_ingested",
        "authorization_granted",
        "runtime_authorization_effective",
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
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTRACT_AUTHORITY")
    if not all(
        _hex(value)
        for value in (
            contract.contract_hash,
            contract.cp68_contract_hash,
            contract.matrix_hash,
            contract.policy_sha256,
            contract.cp68_policy_sha256,
            contract.runtime_policy_sha256,
            contract.module_registry_sha256,
        )
    ):
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp69_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityActivationPreconditionHold("HOLD_CP69_CONTRACT_HASH")
