from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery import (
    compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract,
)
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback import (
    CHECKPOINT as CP75_CHECKPOINT,
    STATE as CP75_STATE,
    _build_cp74_dry_run,
    build_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback,
    validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-crash-consistency-dry-run-v1.0.0"
STATE = "PASS_CP76_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_DRY_RUN_LOCAL_ONLY_NO_TORN_STATE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP76"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP77_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_DRY_RUN"
CRASH_POINTS = (
    "AFTER_PREPARE_BEFORE_STAGE",
    "AFTER_STAGE_BEFORE_COMMIT_MARKER",
    "AFTER_COMMIT_MARKER_BEFORE_ACK",
)
PARENT_RECOVERY_CASES = (
    ("EXPIRY_PATH", "MISSING_TOMBSTONE"),
    ("EXPIRY_PATH", "CORRUPTED_TOMBSTONE"),
    ("REVOCATION_PATH", "MISSING_TOMBSTONE"),
    ("REVOCATION_PATH", "CORRUPTED_TOMBSTONE"),
)
VALIDATION_CASES = tuple((scenario, failure_mode, crash_point) for scenario, failure_mode in PARENT_RECOVERY_CASES for crash_point in CRASH_POINTS)
VALIDATION_PHASES = (
    "CP75_PARENT_EXACT_BOUND",
    "PREPARE_CRASH_RESTART_CONVERGES",
    "STAGED_PRECOMMIT_CRASH_ROLLS_BACK_THEN_REPLAYS",
    "POST_COMMIT_MARKER_CRASH_FINALIZES_IDEMPOTENTLY",
    "ALL_FOUR_RECOVERY_CASES_CRASH_CONSISTENT",
    "TORN_STATE_REJECTED",
    "DUPLICATE_RECOVERY_EFFECT_REJECTED",
    "SIMULATED_ONLY_NO_STORAGE_WRITE",
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
    "HOLD_CP76_CRASH_RECOVERY_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP76_CRASH_CONSISTENCY_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold(ValueError):
    pass


@dataclass(frozen=True)
class RecoveryCrashConsistencyCase:
    scenario: str
    failure_mode: str
    crash_point: str
    transaction_id: str
    baseline_snapshot_hash: str
    intended_recovery_result_hash: str
    prepare_record_hash: str
    staged_record_hash: str | None
    commit_marker_hash: str | None
    restart_action: str
    restart_converged_result_hash: str
    recovery_effect_count: int
    crash_consistent: bool
    torn_state_observed: bool = False
    duplicate_recovery_effect_observed: bool = False
    simulated_journal_only: bool = True
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp75_contract_id: str
    cp75_contract_hash: str
    cp75_dry_run_id: str
    cp75_dry_run_hash: str
    lease_id: str
    lease_hash: str
    crash_cases: tuple[RecoveryCrashConsistencyCase, ...]
    phases: tuple[str, ...]
    outcome: str
    global_kill_switch_engaged: bool = True
    zero_io_observed: bool = True
    simulated_journal_only: bool = True
    torn_state_observed: bool = False
    duplicate_recovery_effect_observed: bool = False
    storage_write_allowed: bool = False
    storage_write_performed: bool = False
    runtime_authorization_effective: bool = False
    authority_activated: bool = False
    network_allowed: bool = False
    account_connection_allowed: bool = False
    publish_allowed: bool = False
    external_write_allowed: bool = False
    deploy_allowed: bool = False
    control_plane_promoted: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["crash_cases"] = [x.to_dict() for x in self.crash_cases]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyContract:
    contract_id: str
    contract_hash: str
    cp75_contract_id: str
    cp75_contract_hash: str
    cp75_dry_run_id: str
    cp75_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp75_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP75_CHECKPOINT
    parent_cp75_state: str = CP75_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    crash_consistency_validated: bool = True
    no_torn_state_validated: bool = True
    no_duplicate_effect_validated: bool = True
    simulated_journal_only: bool = True
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
    storage_write_allowed: bool = False
    storage_write_performed: bool = False
    control_plane_promoted: bool = False
    deploy_allowed: bool = False
    deploy_performed: bool = False
    paid_service_used: bool = False
    authority_activated: bool = False
    runtime_mutated: bool = False
    state: str = STATE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["active_platforms"] = list(self.active_platforms)
        d["blockers"] = list(self.blockers)
        return d


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _without(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in keys}


def _hex(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_POLICY_V1",
        CHECKPOINT,
        "M45_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP75_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_SCOPE_DRIFT")
    if tuple(policy.get("crash_points", ())) != CRASH_POINTS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CRASH_POINT_DRIFT")
    if tuple(tuple(x) for x in policy.get("validation_cases", ())) != VALIDATION_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CASE_DRIFT")
    if tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP75_CHECKPOINT or policy.get("next_after_cp76") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CONTINUITY_DRIFT")
    guard = policy.get("crash_consistency_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp75_recovery_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp75_contract_binding_required", "exact_cp75_dry_run_binding_required",
        "exact_lease_binding_required", "three_bounded_crash_points_required",
        "precommit_restart_must_replay_deterministically", "postcommit_restart_must_finalize_idempotently",
        "restart_must_converge_to_cp75_recovery_result", "torn_state_forbidden",
        "duplicate_recovery_effect_forbidden", "corrupt_commit_marker_forbidden", "baseline_drift_forbidden",
        "simulated_journal_only", "storage_write_forbidden", "runtime_mutation_forbidden",
        "registry_mutation_forbidden", "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged",
        "runtime_network_must_remain_disabled", "account_connection_must_remain_disabled",
        "publish_must_remain_disabled", "deploy_must_remain_disabled", "control_plane_must_remain_unpromoted",
        "secret_resolution_forbidden", "environment_read_forbidden", "keychain_read_forbidden", "oauth_forbidden",
        "real_account_lookup_forbidden", "network_forbidden", "live_probe_execution_forbidden", "publish_forbidden",
        "external_write_forbidden", "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden",
        "authority_activation_forbidden",
    )
    if any(guard.get(key) is not True for key in required):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_GUARD_WEAKENED")
    if tuple(guard.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_METHOD_DRIFT")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CONTROL_PROMOTION")
    if states.get("M44_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK") != "CP75_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_DRY_RUN_LOCAL_ONLY_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CP75_STATE")
    if states.get("M45_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY") != "CP76_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_DRY_RUN_LOCAL_ONLY_NO_TORN_STATE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_MODULE_STATE")


def _restart_action(crash_point: str) -> str:
    if crash_point == "AFTER_PREPARE_BEFORE_STAGE":
        return "DISCARD_PREPARE_AND_REPLAY_CP75_RECOVERY"
    if crash_point == "AFTER_STAGE_BEFORE_COMMIT_MARKER":
        return "DISCARD_STAGED_ROLLBACK_BASELINE_AND_REPLAY_CP75_RECOVERY"
    if crash_point == "AFTER_COMMIT_MARKER_BEFORE_ACK":
        return "FINALIZE_COMMITTED_RESULT_IDEMPOTENTLY"
    raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_UNKNOWN_CRASH_POINT")


def _case_from_cp75(parent_case: Any, crash_point: str, lease_id: str, lease_hash: str) -> RecoveryCrashConsistencyCase:
    tx_seed = {
        "scenario": parent_case.scenario,
        "failure_mode": parent_case.failure_mode,
        "crash_point": crash_point,
        "lease_id": lease_id,
        "lease_hash": lease_hash,
        "baseline_snapshot_hash": parent_case.baseline_snapshot_hash,
        "intended_recovery_result_hash": parent_case.first_apply_result_hash,
    }
    tx_digest = _hash(tx_seed)
    transaction_id = f"cp76_tx_{tx_digest[:24]}"
    prepare_record = {
        "transaction_id": transaction_id,
        "phase": "PREPARED",
        "baseline_snapshot_hash": parent_case.baseline_snapshot_hash,
        "intended_recovery_result_hash": parent_case.first_apply_result_hash,
        "storage_write_allowed": False,
    }
    prepare_hash = _hash(prepare_record)
    staged_hash: str | None = None
    commit_hash: str | None = None
    if crash_point in ("AFTER_STAGE_BEFORE_COMMIT_MARKER", "AFTER_COMMIT_MARKER_BEFORE_ACK"):
        staged_hash = _hash({
            "transaction_id": transaction_id,
            "phase": "STAGED",
            "prepare_record_hash": prepare_hash,
            "recovery_result_hash": parent_case.first_apply_result_hash,
            "persisted": False,
        })
    if crash_point == "AFTER_COMMIT_MARKER_BEFORE_ACK":
        commit_hash = _hash({
            "transaction_id": transaction_id,
            "phase": "COMMIT_MARKED",
            "prepare_record_hash": prepare_hash,
            "staged_record_hash": staged_hash,
            "committed_result_hash": parent_case.first_apply_result_hash,
            "persisted": False,
        })
    out = RecoveryCrashConsistencyCase(
        scenario=parent_case.scenario,
        failure_mode=parent_case.failure_mode,
        crash_point=crash_point,
        transaction_id=transaction_id,
        baseline_snapshot_hash=parent_case.baseline_snapshot_hash,
        intended_recovery_result_hash=parent_case.first_apply_result_hash,
        prepare_record_hash=prepare_hash,
        staged_record_hash=staged_hash,
        commit_marker_hash=commit_hash,
        restart_action=_restart_action(crash_point),
        restart_converged_result_hash=parent_case.first_apply_result_hash,
        recovery_effect_count=1,
        crash_consistent=True,
    )
    _validate_case(out, parent_case)
    return out


def _validate_case(case: RecoveryCrashConsistencyCase, parent_case: Any) -> None:
    if (case.scenario, case.failure_mode, case.crash_point) not in VALIDATION_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CASE_IDENTITY")
    if (case.scenario, case.failure_mode) != (parent_case.scenario, parent_case.failure_mode):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PARENT_CASE_IDENTITY")
    if case.baseline_snapshot_hash != parent_case.baseline_snapshot_hash or case.intended_recovery_result_hash != parent_case.first_apply_result_hash:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PARENT_CASE_BINDING")
    for value in (case.baseline_snapshot_hash, case.intended_recovery_result_hash, case.prepare_record_hash, case.restart_converged_result_hash):
        if not _hex(value):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CASE_DIGEST")
    if not case.transaction_id.startswith("cp76_tx_") or len(case.transaction_id) != len("cp76_tx_") + 24:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_TRANSACTION_ID")
    if case.crash_point == "AFTER_PREPARE_BEFORE_STAGE":
        if case.staged_record_hash is not None or case.commit_marker_hash is not None:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PREPARE_CRASH_TORN_STATE")
    elif case.crash_point == "AFTER_STAGE_BEFORE_COMMIT_MARKER":
        if not _hex(case.staged_record_hash) or case.commit_marker_hash is not None:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_STAGED_CRASH_TORN_STATE")
    elif case.crash_point == "AFTER_COMMIT_MARKER_BEFORE_ACK":
        if not _hex(case.staged_record_hash) or not _hex(case.commit_marker_hash):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_COMMIT_MARKER_MISSING")
    if case.restart_action != _restart_action(case.crash_point):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_RESTART_ACTION_DRIFT")
    if not case.crash_consistent or case.restart_converged_result_hash != case.intended_recovery_result_hash:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_RESTART_DID_NOT_CONVERGE")
    if case.torn_state_observed:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_TORN_STATE")
    if case.duplicate_recovery_effect_observed or case.recovery_effect_count != 1:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_DUPLICATE_EFFECT")
    if not case.simulated_journal_only or case.storage_write_performed or case.runtime_mutated:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_MUTATION")


def build_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(
    cp75_contract: Any,
    cp75_dry_run: Any,
) -> AuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_contract(cp75_contract)
    if (cp75_contract.dry_run_id, cp75_contract.dry_run_hash) != (cp75_dry_run.dry_run_id, cp75_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CP75_DRY_RUN_BINDING")
    parent_map = {(x.scenario, x.failure_mode): x for x in cp75_dry_run.validation_cases}
    if tuple(parent_map) != PARENT_RECOVERY_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PARENT_CASE_SET")
    cases = tuple(
        _case_from_cp75(parent_map[(scenario, failure_mode)], crash_point, cp75_contract.lease_id, cp75_contract.lease_hash)
        for scenario, failure_mode, crash_point in VALIDATION_CASES
    )
    body = {
        "cp75_contract_id": cp75_contract.contract_id,
        "cp75_contract_hash": cp75_contract.contract_hash,
        "cp75_dry_run_id": cp75_dry_run.dry_run_id,
        "cp75_dry_run_hash": cp75_dry_run.dry_run_hash,
        "lease_id": cp75_contract.lease_id,
        "lease_hash": cp75_contract.lease_hash,
        "crash_cases": [x.to_dict() for x in cases],
        "phases": list(VALIDATION_PHASES),
        "outcome": "SIMULATED_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_PASS_NO_TORN_STATE_NO_DUPLICATE_EFFECT_NO_STORAGE_WRITE_NO_AUTHORITY",
        "global_kill_switch_engaged": True,
        "zero_io_observed": True,
        "simulated_journal_only": True,
        "torn_state_observed": False,
        "duplicate_recovery_effect_observed": False,
        "storage_write_allowed": False,
        "storage_write_performed": False,
        "runtime_authorization_effective": False,
        "authority_activated": False,
        "network_allowed": False,
        "account_connection_allowed": False,
        "publish_allowed": False,
        "external_write_allowed": False,
        "deploy_allowed": False,
        "control_plane_promoted": False,
        "runtime_mutated": False,
    }
    digest = _hash(body)
    body["crash_cases"] = cases
    body["phases"] = VALIDATION_PHASES
    dry = AuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyDryRun(
        dry_run_id=f"cp76_dry_run_{digest[:24]}",
        dry_run_hash=digest,
        **body,
    )
    validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(dry, cp75_contract, cp75_dry_run)
    return dry


def validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(
    dry: AuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyDryRun,
    cp75_contract: Any,
    cp75_dry_run: Any,
) -> None:
    if (dry.cp75_contract_id, dry.cp75_contract_hash, dry.cp75_dry_run_id, dry.cp75_dry_run_hash, dry.lease_id, dry.lease_hash) != (
        cp75_contract.contract_id, cp75_contract.contract_hash, cp75_dry_run.dry_run_id, cp75_dry_run.dry_run_hash,
        cp75_contract.lease_id, cp75_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PARENT_BINDING")
    if tuple((x.scenario, x.failure_mode, x.crash_point) for x in dry.crash_cases) != VALIDATION_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CASE_SET")
    parent_map = {(x.scenario, x.failure_mode): x for x in cp75_dry_run.validation_cases}
    for case in dry.crash_cases:
        _validate_case(case, parent_map[(case.scenario, case.failure_mode)])
    if dry.phases != VALIDATION_PHASES or dry.outcome != "SIMULATED_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_PASS_NO_TORN_STATE_NO_DUPLICATE_EFFECT_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_OUTCOME_OR_PHASES")
    if not dry.global_kill_switch_engaged or not dry.zero_io_observed or not dry.simulated_journal_only:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_ZERO_IO_OR_KILL_SWITCH")
    if dry.torn_state_observed or dry.duplicate_recovery_effect_observed:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_DRY_RUN_INCONSISTENT")
    for key in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed",
        "deploy_allowed", "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp76_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_DRY_RUN_HASH")


def _build_cp75_dry_run(root: Path, cp75_contract: Any) -> Any:
    cp74_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_policy.json")
    cp74 = compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(root, cp74_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract(cp74)
    cp74_dry = _build_cp74_dry_run(root, cp74)
    cp75_dry = build_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(cp74, cp74_dry)
    validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(cp75_dry, cp74, cp74_dry)
    if (cp75_contract.dry_run_id, cp75_contract.dry_run_hash) != (cp75_dry.dry_run_id, cp75_dry.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_PARENT_REBUILD_DRIFT")
    return cp75_dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp75_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_policy.json")
    cp75 = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(root, cp75_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_contract(cp75)
    cp75_dry = _build_cp75_dry_run(root, cp75)
    dry = build_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(cp75, cp75_dry)
    body = {
        "cp75_contract_id": cp75.contract_id,
        "cp75_contract_hash": cp75.contract_hash,
        "cp75_dry_run_id": cp75_dry.dry_run_id,
        "cp75_dry_run_hash": cp75_dry.dry_run_hash,
        "lease_id": cp75.lease_id,
        "lease_hash": cp75.lease_hash,
        "dry_run_id": dry.dry_run_id,
        "dry_run_hash": dry.dry_run_hash,
        "policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_policy.json").read_bytes()).hexdigest(),
        "cp75_policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_policy.json").read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        "module_registry_sha256": sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
    }
    defaults = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyContract.__dataclass_fields__
    for key in (
        "next_unit", "checkpoint", "parent_control_checkpoint", "parent_activation_checkpoint", "parent_cp75_state",
        "model_version", "engine_version", "crash_consistency_validated", "no_torn_state_validated",
        "no_duplicate_effect_validated", "simulated_journal_only", "synthetic_validation_only",
        "global_kill_switch_engaged", "external_authorization_ingested", "authorization_granted",
        "runtime_authorization_effective", "secret_reference_resolved", "environment_read", "keychain_read",
        "oauth_attempted", "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
        "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted", "external_write_allowed",
        "external_write_performed", "storage_write_allowed", "storage_write_performed", "control_plane_promoted",
        "deploy_allowed", "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated", "state",
    ):
        body[key] = defaults[key].default
    digest = _hash(body)
    body["active_platforms"] = EXPECTED_ACTIVE
    body["blockers"] = REQUIRED_BLOCKERS
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyContract(
        contract_id=f"cp76_contract_{digest[:24]}",
        contract_hash=digest,
        **body,
    )
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyContract,
) -> None:
    if (
        contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint,
        contract.parent_cp75_state, contract.state, contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP75_CHECKPOINT, CP75_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only
        or not contract.crash_consistency_validated or not contract.no_torn_state_validated
        or not contract.no_duplicate_effect_validated or not contract.simulated_journal_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CONTRACT_SCOPE_OR_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
        "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "storage_write_allowed", "storage_write_performed",
        "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used",
        "authority_activated", "runtime_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (
        contract.contract_hash, contract.cp75_contract_hash, contract.cp75_dry_run_hash, contract.lease_hash,
        contract.dry_run_hash, contract.policy_sha256, contract.cp75_policy_sha256,
        contract.runtime_policy_sha256, contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp76_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold("HOLD_CP76_CONTRACT_HASH")
