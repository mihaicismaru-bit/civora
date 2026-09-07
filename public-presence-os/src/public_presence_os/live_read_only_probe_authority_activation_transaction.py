from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_activation_precondition import (
    CHECKPOINT as CP69_CHECKPOINT,
    STATE as CP69_STATE,
    compile_live_read_only_probe_authority_activation_precondition_matrix,
    evaluate_from_root as evaluate_cp69_from_root,
    validate_live_read_only_probe_authority_activation_precondition_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_TRANSACTION_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-activation-transaction-dry-run-v1.0.0"
STATE = "PASS_CP70_AUTHORITY_ACTIVATION_TRANSACTION_DRY_RUN_LOCAL_ONLY_NO_COMMIT_LIVE_HOLD"
CHECKPOINT = "CP70"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP71_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_AND_REVOCATION_DRY_RUN"
TRANSACTION_PHASES = (
    "CP69_PARENT_EXACT_BOUND",
    "PREPARE_RUNTIME_GUARDS_LOCKED",
    "COMMIT_CANDIDATE_CONSTRUCTED_IN_MEMORY",
    "COMMIT_SIDE_EFFECTS_SUPPRESSED",
    "ROLLBACK_RESTORES_BASELINE_SNAPSHOT",
    "ZERO_IO_OBSERVED",
    "AUTHORITY_REMAINS_INACTIVE",
)
REQUIRED_BLOCKERS = (
    "HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
    "HOLD_CP70_TRANSACTION_PASS_IS_SIMULATION_ONLY",
    "HOLD_CP70_COMMIT_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityActivationTransactionHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TransactionPhaseResult:
    name: str
    satisfied: bool
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityActivationTransactionDryRun:
    transaction_id: str
    transaction_hash: str
    cp69_contract_id: str
    cp69_contract_hash: str
    cp69_matrix_id: str
    cp69_matrix_hash: str
    baseline_snapshot_sha256: str
    commit_candidate_sha256: str
    rollback_snapshot_sha256: str
    platform_subset: tuple[str, ...]
    phases: tuple[TransactionPhaseResult, ...]
    prepare_passed: bool
    commit_simulated: bool
    rollback_simulated: bool
    rollback_exact: bool
    zero_io_observed: bool
    synthetic_fixture: bool
    outcome: str
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_precondition_checkpoint: str = CP69_CHECKPOINT
    global_kill_switch_engaged: bool = True
    runtime_authorization_effective: bool = False
    authority_activated: bool = False
    network_allowed: bool = False
    live_probe_allowed: bool = False
    account_connection_allowed: bool = False
    publish_allowed: bool = False
    external_write_allowed: bool = False
    deploy_allowed: bool = False
    control_plane_promoted: bool = False
    runtime_mutated: bool = False
    registry_mutated: bool = False
    policy_mutated: bool = False
    state: str = "PREPARE_COMMIT_ROLLBACK_SIMULATED_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform_subset"] = list(self.platform_subset)
        d["phases"] = [row.to_dict() for row in self.phases]
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityActivationTransactionContract:
    contract_id: str
    contract_hash: str
    cp69_contract_id: str
    cp69_contract_hash: str
    cp69_matrix_id: str
    cp69_matrix_hash: str
    transaction_id: str
    transaction_hash: str
    policy_sha256: str
    cp69_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_precondition_checkpoint: str = CP69_CHECKPOINT
    parent_cp69_state: str = CP69_STATE
    transaction_validated: bool = True
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
    runtime_mutated: bool = False
    registry_mutated: bool = False
    policy_mutated: bool = False
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


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_TRANSACTION_POLICY_V1",
        CHECKPOINT,
        "M39_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_TRANSACTION",
    ):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_POLICY_IDENTITY")
    if policy.get("parent_precondition_checkpoint") != CP69_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE or tuple(policy.get("transaction_phases", ())) != TRANSACTION_PHASES:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_SCOPE_OR_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP69_CHECKPOINT or policy.get("next_after_cp70") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTINUITY_DRIFT")
    transaction = policy.get("transaction", {})
    required_true = (
        "local_only", "zero_io_required", "synthetic_cp69_candidate_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp69_contract_binding_required", "exact_cp69_matrix_binding_required",
        "all_cp69_preconditions_required", "prepare_phase_required", "commit_simulation_required",
        "rollback_simulation_required", "baseline_snapshot_must_equal_rollback_snapshot",
        "runtime_mutation_forbidden", "registry_mutation_forbidden", "policy_mutation_forbidden",
        "global_kill_switch_must_remain_engaged", "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled", "publish_must_remain_disabled", "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted", "secret_resolution_forbidden", "environment_read_forbidden",
        "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden", "network_forbidden",
        "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(transaction.get(key) is not True for key in required_true):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_POLICY_GUARD")
    if tuple(transaction.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_METHOD_POLICY")
    authority = policy.get("authority")
    if not isinstance(authority, dict) or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_DEFERRED_LANE_DRIFT")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_RUNTIME_LIVE_BOUNDARY")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTROL_PROMOTION")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M38_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX") != "CP69_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX_ZERO_IO_DRY_RUN_LOCAL_ONLY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CP69_STATE")
    if states.get("M39_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_TRANSACTION") != "CP70_AUTHORITY_ACTIVATION_TRANSACTION_DRY_RUN_LOCAL_ONLY_NO_COMMIT_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_MODULE_STATE")


def _phase(name: str, satisfied: bool) -> TransactionPhaseResult:
    return TransactionPhaseResult(name=name, satisfied=satisfied, evidence_sha256=_hash({"name": name, "satisfied": satisfied}))


def _baseline_snapshot(root: Path) -> dict[str, Any]:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    return {
        "global_kill_switch_engaged": runtime.get("global_kill_switch_engaged"),
        "network_enabled": runtime.get("network_enabled"),
        "account_connection_enabled": runtime.get("account_connection_enabled"),
        "publish_enabled": runtime.get("publish_enabled"),
        "deploy_enabled": runtime.get("deploy_enabled"),
        "control_checkpoint": registry.get("checkpoint"),
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


def build_authority_activation_transaction_dry_run(
    cp69_contract: Any,
    cp69_matrix: Any,
    *,
    baseline_snapshot: dict[str, Any],
) -> AuthorityActivationTransactionDryRun:
    validate_live_read_only_probe_authority_activation_precondition_contract(cp69_contract)
    required_snapshot = {
        "global_kill_switch_engaged", "network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled",
        "control_checkpoint", "environment_reads", "keychain_reads", "oauth_attempts", "real_account_lookups",
        "network_attempts", "live_probe_attempts", "publish_attempts", "external_writes", "deploy_attempts", "paid_service_uses",
    }
    if set(baseline_snapshot) != required_snapshot:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_BASELINE_FIELDS")
    counters = (
        "environment_reads", "keychain_reads", "oauth_attempts", "real_account_lookups", "network_attempts",
        "live_probe_attempts", "publish_attempts", "external_writes", "deploy_attempts", "paid_service_uses",
    )
    for key in counters:
        value = baseline_snapshot[key]
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_ZERO_IO_BASELINE")
    parent_bound = (
        (cp69_contract.matrix_id, cp69_contract.matrix_hash) == (cp69_matrix.matrix_id, cp69_matrix.matrix_hash)
        and cp69_matrix.all_structural_preconditions_satisfied is True
        and cp69_matrix.outcome == "STRUCTURAL_PRECONDITIONS_SATISFIED_CANDIDATE_ONLY_NO_AUTHORITY"
    )
    guards_locked = (
        baseline_snapshot["global_kill_switch_engaged"] is True
        and baseline_snapshot["network_enabled"] is False
        and baseline_snapshot["account_connection_enabled"] is False
        and baseline_snapshot["publish_enabled"] is False
        and baseline_snapshot["deploy_enabled"] is False
        and baseline_snapshot["control_checkpoint"] == PARENT_CONTROL_CHECKPOINT
    )
    baseline_hash = _hash(baseline_snapshot)
    candidate = {
        "source_checkpoint": CP69_CHECKPOINT,
        "requested_scope": "READ_ONLY_METADATA_PROBE",
        "platform_subset": list(cp69_matrix.platform_subset),
        "method_allowlist": ["GET"],
        "simulation_only": True,
        "would_require_separate_runtime_authority": True,
        "runtime_mutation_performed": False,
        "network_attempted": False,
        "authority_activated": False,
    }
    candidate_hash = _hash(candidate)
    rollback_snapshot = dict(baseline_snapshot)
    rollback_hash = _hash(rollback_snapshot)
    zero_io = all(baseline_snapshot[key] == 0 for key in counters)
    facts = {
        "CP69_PARENT_EXACT_BOUND": parent_bound,
        "PREPARE_RUNTIME_GUARDS_LOCKED": guards_locked,
        "COMMIT_CANDIDATE_CONSTRUCTED_IN_MEMORY": candidate["simulation_only"] is True and candidate["runtime_mutation_performed"] is False,
        "COMMIT_SIDE_EFFECTS_SUPPRESSED": candidate["network_attempted"] is False and candidate["authority_activated"] is False,
        "ROLLBACK_RESTORES_BASELINE_SNAPSHOT": baseline_hash == rollback_hash,
        "ZERO_IO_OBSERVED": zero_io,
        "AUTHORITY_REMAINS_INACTIVE": cp69_matrix.authority_activated is False and cp69_contract.authority_activated is False,
    }
    phases = tuple(_phase(name, facts[name]) for name in TRANSACTION_PHASES)
    prepare_passed = facts["CP69_PARENT_EXACT_BOUND"] and facts["PREPARE_RUNTIME_GUARDS_LOCKED"]
    all_passed = all(row.satisfied for row in phases)
    outcome = "SIMULATED_PREPARE_COMMIT_ROLLBACK_PASS_NO_AUTHORITY_NO_MUTATION" if all_passed else "HOLD_TRANSACTION_DRY_RUN_UNSATISFIED_NO_AUTHORITY"
    body = {
        "cp69_contract_id": cp69_contract.contract_id,
        "cp69_contract_hash": cp69_contract.contract_hash,
        "cp69_matrix_id": cp69_matrix.matrix_id,
        "cp69_matrix_hash": cp69_matrix.matrix_hash,
        "baseline_snapshot_sha256": baseline_hash,
        "commit_candidate_sha256": candidate_hash,
        "rollback_snapshot_sha256": rollback_hash,
        "platform_subset": list(cp69_matrix.platform_subset),
        "phases": [row.to_dict() for row in phases],
        "prepare_passed": prepare_passed,
        "commit_simulated": True,
        "rollback_simulated": True,
        "rollback_exact": baseline_hash == rollback_hash,
        "zero_io_observed": zero_io,
        "synthetic_fixture": bool(cp69_matrix.synthetic_fixture),
        "outcome": outcome,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "parent_precondition_checkpoint": CP69_CHECKPOINT,
        "global_kill_switch_engaged": True,
        "runtime_authorization_effective": False,
        "authority_activated": False,
        "network_allowed": False,
        "live_probe_allowed": False,
        "account_connection_allowed": False,
        "publish_allowed": False,
        "external_write_allowed": False,
        "deploy_allowed": False,
        "control_plane_promoted": False,
        "runtime_mutated": False,
        "registry_mutated": False,
        "policy_mutated": False,
        "state": "PREPARE_COMMIT_ROLLBACK_SIMULATED_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY",
    }
    digest = _hash(body)
    body["platform_subset"] = tuple(body["platform_subset"])
    body["phases"] = phases
    transaction = AuthorityActivationTransactionDryRun(transaction_id=f"cp70_transaction_{digest[:24]}", transaction_hash=digest, **body)
    validate_authority_activation_transaction_dry_run(transaction, cp69_contract, cp69_matrix)
    return transaction


def validate_authority_activation_transaction_dry_run(transaction: AuthorityActivationTransactionDryRun, cp69_contract: Any, cp69_matrix: Any) -> None:
    if (transaction.cp69_contract_id, transaction.cp69_contract_hash) != (cp69_contract.contract_id, cp69_contract.contract_hash):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_CP69_CONTRACT_BINDING")
    if (transaction.cp69_matrix_id, transaction.cp69_matrix_hash) != (cp69_matrix.matrix_id, cp69_matrix.matrix_hash):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_CP69_MATRIX_BINDING")
    if tuple(row.name for row in transaction.phases) != TRANSACTION_PHASES or not all(row.satisfied for row in transaction.phases):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_PHASES")
    if transaction.prepare_passed is not True or transaction.commit_simulated is not True or transaction.rollback_simulated is not True:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_NOT_COMPLETE")
    if transaction.rollback_exact is not True or transaction.baseline_snapshot_sha256 != transaction.rollback_snapshot_sha256:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_ROLLBACK_NOT_EXACT")
    if transaction.zero_io_observed is not True or transaction.global_kill_switch_engaged is not True:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_GUARD")
    if transaction.outcome != "SIMULATED_PREPARE_COMMIT_ROLLBACK_PASS_NO_AUTHORITY_NO_MUTATION":
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_OUTCOME")
    for key in (
        "runtime_authorization_effective", "authority_activated", "network_allowed", "live_probe_allowed", "account_connection_allowed",
        "publish_allowed", "external_write_allowed", "deploy_allowed", "control_plane_promoted", "runtime_mutated", "registry_mutated", "policy_mutated",
    ):
        if getattr(transaction, key) is not False:
            raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (
        transaction.transaction_hash, transaction.cp69_contract_hash, transaction.cp69_matrix_hash,
        transaction.baseline_snapshot_sha256, transaction.commit_candidate_sha256, transaction.rollback_snapshot_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_DIGEST")
    digest = _hash(_without(transaction.to_dict(), "transaction_id", "transaction_hash"))
    if transaction.transaction_hash != digest or transaction.transaction_id != f"cp70_transaction_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_TRANSACTION_HASH")


def compile_live_read_only_probe_authority_activation_transaction(root: Path, policy: dict[str, Any]) -> LiveReadOnlyProbeAuthorityActivationTransactionContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp69_policy = load_json(root / "config" / "live_read_only_probe_authority_activation_precondition_policy.json")
    cp69_contract = compile_live_read_only_probe_authority_activation_precondition_matrix(root, cp69_policy)
    validate_live_read_only_probe_authority_activation_precondition_contract(cp69_contract)
    cp69_matrix = evaluate_cp69_from_root(root, cp69_policy)
    if (cp69_contract.matrix_id, cp69_contract.matrix_hash) != (cp69_matrix.matrix_id, cp69_matrix.matrix_hash):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CP69_EXACT_BINDING")
    transaction = build_authority_activation_transaction_dry_run(
        cp69_contract,
        cp69_matrix,
        baseline_snapshot=_baseline_snapshot(root),
    )
    policy_path = root / "config" / "live_read_only_probe_authority_activation_transaction_policy.json"
    cp69_policy_path = root / "config" / "live_read_only_probe_authority_activation_precondition_policy.json"
    runtime_path = root / "config" / "runtime_policy.json"
    registry_path = root / "config" / "module_registry.json"
    body = {
        "cp69_contract_id": cp69_contract.contract_id,
        "cp69_contract_hash": cp69_contract.contract_hash,
        "cp69_matrix_id": cp69_matrix.matrix_id,
        "cp69_matrix_hash": cp69_matrix.matrix_hash,
        "transaction_id": transaction.transaction_id,
        "transaction_hash": transaction.transaction_hash,
        "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        "cp69_policy_sha256": sha256(cp69_policy_path.read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256(runtime_path.read_bytes()).hexdigest(),
        "module_registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "parent_precondition_checkpoint": CP69_CHECKPOINT,
        "parent_cp69_state": CP69_STATE,
        "transaction_validated": True,
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
        "runtime_mutated": False,
        "registry_mutated": False,
        "policy_mutated": False,
        "state": STATE,
    }
    digest = _hash(body)
    body["active_platforms"] = EXPECTED_ACTIVE
    body["blockers"] = REQUIRED_BLOCKERS
    contract = LiveReadOnlyProbeAuthorityActivationTransactionContract(contract_id=f"cp70_contract_{digest[:24]}", contract_hash=digest, **body)
    validate_live_read_only_probe_authority_activation_transaction_contract(contract)
    return contract


def validate_live_read_only_probe_authority_activation_transaction_contract(contract: LiveReadOnlyProbeAuthorityActivationTransactionContract) -> None:
    if (
        contract.model_version, contract.engine_version, contract.checkpoint, contract.parent_control_checkpoint,
        contract.parent_precondition_checkpoint, contract.parent_cp69_state, contract.state, contract.next_unit,
    ) != (MODEL_VERSION, ENGINE_VERSION, CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP69_CHECKPOINT, CP69_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTRACT_IDENTITY")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTRACT_SCOPE")
    if contract.global_kill_switch_engaged is not True or contract.transaction_validated is not True or contract.synthetic_validation_only is not True:
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTRACT_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective", "secret_reference_resolved",
        "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted", "account_connected",
        "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed",
        "paid_service_used", "authority_activated", "runtime_mutated", "registry_mutated", "policy_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (
        contract.contract_hash, contract.cp69_contract_hash, contract.cp69_matrix_hash, contract.transaction_hash,
        contract.policy_sha256, contract.cp69_policy_sha256, contract.runtime_policy_sha256, contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp70_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityActivationTransactionHold("HOLD_CP70_CONTRACT_HASH")
