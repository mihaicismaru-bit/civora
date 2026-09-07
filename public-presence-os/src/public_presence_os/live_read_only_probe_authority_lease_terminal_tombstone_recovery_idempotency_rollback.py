from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery import (
    CHECKPOINT as CP74_CHECKPOINT,
    STATE as CP74_STATE,
    _build_cp73_dry_run,
    build_authority_lease_terminal_tombstone_rebuild_recovery_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery,
    validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract,
)
from .live_read_only_probe_authority_lease_terminal_tombstone_reconciliation import (
    compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-idempotency-rollback-dry-run-v1.0.0"
STATE = "PASS_CP75_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_DRY_RUN_LOCAL_ONLY_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP75"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP76_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_DRY_RUN"
VALIDATION_CASES = (
    ("EXPIRY_PATH", "MISSING_TOMBSTONE"),
    ("EXPIRY_PATH", "CORRUPTED_TOMBSTONE"),
    ("REVOCATION_PATH", "MISSING_TOMBSTONE"),
    ("REVOCATION_PATH", "CORRUPTED_TOMBSTONE"),
)
VALIDATION_PHASES = (
    "CP74_PARENT_EXACT_BOUND",
    "EXPIRY_MISSING_RECOVERY_IDEMPOTENCY_VALIDATED",
    "EXPIRY_CORRUPTED_RECOVERY_IDEMPOTENCY_VALIDATED",
    "REVOCATION_MISSING_RECOVERY_IDEMPOTENCY_VALIDATED",
    "REVOCATION_CORRUPTED_RECOVERY_IDEMPOTENCY_VALIDATED",
    "NO_DUPLICATE_RECOVERY_EFFECT_VALIDATED",
    "ROLLBACK_BASELINE_EXACTLY_RESTORED",
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
    "HOLD_CP75_RECOVERY_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP75_IDEMPOTENCY_ROLLBACK_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold(ValueError):
    pass


@dataclass(frozen=True)
class RecoveryIdempotencyRollbackCase:
    scenario: str
    failure_mode: str
    original_tombstone_hash: str
    pre_recovery_observed_tombstone_hash: str | None
    baseline_snapshot_hash: str
    canonical_rebuild_hash: str
    first_apply_proposal_hash: str
    second_apply_proposal_hash: str
    first_apply_result_hash: str
    second_apply_result_hash: str
    rollback_result_hash: str
    idempotent: bool
    duplicate_recovery_effect_observed: bool
    rollback_exact: bool
    simulated_apply_count: int = 2
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp74_contract_id: str
    cp74_contract_hash: str
    cp74_dry_run_id: str
    cp74_dry_run_hash: str
    lease_id: str
    lease_hash: str
    validation_cases: tuple[RecoveryIdempotencyRollbackCase, ...]
    phases: tuple[str, ...]
    outcome: str
    global_kill_switch_engaged: bool = True
    zero_io_observed: bool = True
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
        d["validation_cases"] = [x.to_dict() for x in self.validation_cases]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackContract:
    contract_id: str
    contract_hash: str
    cp74_contract_id: str
    cp74_contract_hash: str
    cp74_dry_run_id: str
    cp74_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp74_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP74_CHECKPOINT
    parent_cp74_state: str = CP74_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    idempotency_validated: bool = True
    rollback_validated: bool = True
    simulated_recovery_only: bool = True
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


def _hex(v: Any) -> bool:
    return isinstance(v, str) and HEX64.fullmatch(v) is not None


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_POLICY_V1",
        CHECKPOINT,
        "M44_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP74_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_SCOPE_DRIFT")
    if tuple(tuple(x) for x in policy.get("validation_cases", ())) != VALIDATION_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CASE_DRIFT")
    if tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP74_CHECKPOINT or policy.get("next_after_cp75") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CONTINUITY_DRIFT")
    g = policy.get("idempotency_rollback_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp74_recovery_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp74_contract_binding_required", "exact_cp74_dry_run_binding_required",
        "exact_lease_binding_required", "identical_recovery_replay_required", "duplicate_recovery_effect_forbidden",
        "rollback_baseline_exact_restore_required", "rollback_after_simulated_apply_only", "simulated_restore_only",
        "storage_write_forbidden", "runtime_mutation_forbidden", "registry_mutation_forbidden",
        "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged", "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled", "publish_must_remain_disabled", "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted", "secret_resolution_forbidden", "environment_read_forbidden",
        "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden", "network_forbidden",
        "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(g.get(k) is not True for k in required):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_GUARD_WEAKENED")
    if tuple(g.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_METHOD_DRIFT")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_RUNTIME_POLICY")
    if any(runtime.get(k) is not False for k in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CONTROL_PROMOTION")
    if states.get("M43_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY") != "CP74_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN_LOCAL_ONLY_EXACT_REBUILD_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CP74_STATE")
    if states.get("M44_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK") != "CP75_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_DRY_RUN_LOCAL_ONLY_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_MODULE_STATE")


def _case_from_cp74(case: Any, lease_id: str, lease_hash: str) -> RecoveryIdempotencyRollbackCase:
    baseline = {
        "scenario": case.scenario,
        "failure_mode": case.failure_mode,
        "lease_id": lease_id,
        "lease_hash": lease_hash,
        "observed_tombstone_hash": case.observed_tombstone_hash,
    }
    baseline_hash = _hash(baseline)
    proposal = {
        "operation": "SIMULATED_RESTORE_ONLY",
        "baseline_snapshot_hash": baseline_hash,
        "target_tombstone": case.rebuilt_tombstone.to_dict(),
        "storage_write_allowed": False,
    }
    first_proposal_hash = _hash(proposal)
    second_proposal_hash = _hash(proposal)
    simulated_result = {
        "scenario": case.scenario,
        "failure_mode": case.failure_mode,
        "observed_tombstone_hash": case.rebuilt_tombstone.tombstone_hash,
        "tombstone": case.rebuilt_tombstone.to_dict(),
        "persisted": False,
    }
    first_result_hash = _hash(simulated_result)
    second_result_hash = _hash(simulated_result)
    rollback_result_hash = _hash(baseline)
    out = RecoveryIdempotencyRollbackCase(
        scenario=case.scenario,
        failure_mode=case.failure_mode,
        original_tombstone_hash=case.original_tombstone_hash,
        pre_recovery_observed_tombstone_hash=case.observed_tombstone_hash,
        baseline_snapshot_hash=baseline_hash,
        canonical_rebuild_hash=case.rebuilt_tombstone.tombstone_hash,
        first_apply_proposal_hash=first_proposal_hash,
        second_apply_proposal_hash=second_proposal_hash,
        first_apply_result_hash=first_result_hash,
        second_apply_result_hash=second_result_hash,
        rollback_result_hash=rollback_result_hash,
        idempotent=first_proposal_hash == second_proposal_hash and first_result_hash == second_result_hash,
        duplicate_recovery_effect_observed=False,
        rollback_exact=rollback_result_hash == baseline_hash,
    )
    _validate_case(out)
    return out


def _validate_case(case: RecoveryIdempotencyRollbackCase) -> None:
    if (case.scenario, case.failure_mode) not in VALIDATION_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CASE_IDENTITY")
    for value in (
        case.original_tombstone_hash,
        case.baseline_snapshot_hash,
        case.canonical_rebuild_hash,
        case.first_apply_proposal_hash,
        case.second_apply_proposal_hash,
        case.first_apply_result_hash,
        case.second_apply_result_hash,
        case.rollback_result_hash,
    ):
        if not _hex(value):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CASE_DIGEST")
    if case.failure_mode == "MISSING_TOMBSTONE":
        if case.pre_recovery_observed_tombstone_hash is not None:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_MISSING_BASELINE")
    elif not _hex(case.pre_recovery_observed_tombstone_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CORRUPTED_BASELINE")
    if not case.idempotent or case.first_apply_proposal_hash != case.second_apply_proposal_hash:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_PROPOSAL_NOT_IDEMPOTENT")
    if case.first_apply_result_hash != case.second_apply_result_hash:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_RESULT_NOT_IDEMPOTENT")
    if case.duplicate_recovery_effect_observed:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_DUPLICATE_EFFECT")
    if not case.rollback_exact or case.rollback_result_hash != case.baseline_snapshot_hash:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_ROLLBACK_NOT_EXACT")
    if case.simulated_apply_count != 2 or case.storage_write_performed or case.runtime_mutated:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_MUTATION_OR_APPLY_COUNT")


def build_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(
    cp74_contract: Any,
    cp74_dry_run: Any,
) -> AuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract(cp74_contract)
    if (cp74_contract.dry_run_id, cp74_contract.dry_run_hash) != (cp74_dry_run.dry_run_id, cp74_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CP74_DRY_RUN_BINDING")
    cases = tuple(_case_from_cp74(x, cp74_contract.lease_id, cp74_contract.lease_hash) for x in cp74_dry_run.recovery_cases)
    body = {
        "cp74_contract_id": cp74_contract.contract_id,
        "cp74_contract_hash": cp74_contract.contract_hash,
        "cp74_dry_run_id": cp74_dry_run.dry_run_id,
        "cp74_dry_run_hash": cp74_dry_run.dry_run_hash,
        "lease_id": cp74_contract.lease_id,
        "lease_hash": cp74_contract.lease_hash,
        "validation_cases": [x.to_dict() for x in cases],
        "phases": list(VALIDATION_PHASES),
        "outcome": "SIMULATED_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_PASS_NO_DUPLICATE_EFFECT_NO_STORAGE_WRITE_NO_AUTHORITY",
        "global_kill_switch_engaged": True,
        "zero_io_observed": True,
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
    body["validation_cases"] = cases
    body["phases"] = VALIDATION_PHASES
    dry = AuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackDryRun(
        dry_run_id=f"cp75_dry_run_{digest[:24]}",
        dry_run_hash=digest,
        **body,
    )
    validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(dry, cp74_contract, cp74_dry_run)
    return dry


def validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(
    dry: AuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackDryRun,
    cp74_contract: Any,
    cp74_dry_run: Any,
) -> None:
    if (dry.cp74_contract_id, dry.cp74_contract_hash, dry.cp74_dry_run_id, dry.cp74_dry_run_hash, dry.lease_id, dry.lease_hash) != (
        cp74_contract.contract_id, cp74_contract.contract_hash, cp74_dry_run.dry_run_id, cp74_dry_run.dry_run_hash,
        cp74_contract.lease_id, cp74_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_PARENT_BINDING")
    if tuple((x.scenario, x.failure_mode) for x in dry.validation_cases) != VALIDATION_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CASE_SET")
    for case in dry.validation_cases:
        _validate_case(case)
    if dry.phases != VALIDATION_PHASES or dry.outcome != "SIMULATED_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_PASS_NO_DUPLICATE_EFFECT_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_OUTCOME_OR_PHASES")
    if not dry.global_kill_switch_engaged or not dry.zero_io_observed:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_ZERO_IO_OR_KILL_SWITCH")
    for k in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed",
        "deploy_allowed", "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, k) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp75_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_DRY_RUN_HASH")


def _build_cp74_dry_run(root: Path, cp74_contract: Any) -> Any:
    cp73_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_policy.json")
    cp73 = compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(root, cp73_policy)
    cp73_dry = _build_cp73_dry_run(root, cp73)
    cp74_dry = build_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(cp73, cp73_dry)
    validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(cp74_dry, cp73, cp73_dry)
    if (cp74_contract.dry_run_id, cp74_contract.dry_run_hash) != (cp74_dry.dry_run_id, cp74_dry.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_PARENT_REBUILD_DRIFT")
    return cp74_dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp74_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_policy.json")
    cp74 = compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(root, cp74_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract(cp74)
    cp74_dry = _build_cp74_dry_run(root, cp74)
    dry = build_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(cp74, cp74_dry)
    body = {
        "cp74_contract_id": cp74.contract_id,
        "cp74_contract_hash": cp74.contract_hash,
        "cp74_dry_run_id": cp74_dry.dry_run_id,
        "cp74_dry_run_hash": cp74_dry.dry_run_hash,
        "lease_id": cp74.lease_id,
        "lease_hash": cp74.lease_hash,
        "dry_run_id": dry.dry_run_id,
        "dry_run_hash": dry.dry_run_hash,
        "policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_policy.json").read_bytes()).hexdigest(),
        "cp74_policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_policy.json").read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        "module_registry_sha256": sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
    }
    defaults = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackContract.__dataclass_fields__
    for k in (
        "next_unit", "checkpoint", "parent_control_checkpoint", "parent_activation_checkpoint", "parent_cp74_state",
        "model_version", "engine_version", "idempotency_validated", "rollback_validated", "simulated_recovery_only",
        "synthetic_validation_only", "global_kill_switch_engaged", "external_authorization_ingested",
        "authorization_granted", "runtime_authorization_effective", "secret_reference_resolved", "environment_read",
        "keychain_read", "oauth_attempted", "real_account_lookup_attempted", "account_connected", "network_allowed",
        "network_attempted", "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "storage_write_allowed", "storage_write_performed",
        "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used", "authority_activated",
        "runtime_mutated", "state",
    ):
        body[k] = defaults[k].default
    digest = _hash(body)
    body["active_platforms"] = EXPECTED_ACTIVE
    body["blockers"] = REQUIRED_BLOCKERS
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackContract(
        contract_id=f"cp75_contract_{digest[:24]}",
        contract_hash=digest,
        **body,
    )
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackContract,
) -> None:
    if (
        contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint,
        contract.parent_cp74_state, contract.state, contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP74_CHECKPOINT, CP74_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only
        or not contract.idempotency_validated or not contract.rollback_validated or not contract.simulated_recovery_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CONTRACT_SCOPE_OR_GUARD")
    for k in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
        "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "storage_write_allowed", "storage_write_performed",
        "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used",
        "authority_activated", "runtime_mutated",
    ):
        if getattr(contract, k) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(x) for x in (
        contract.contract_hash, contract.cp74_contract_hash, contract.cp74_dry_run_hash, contract.lease_hash,
        contract.dry_run_hash, contract.policy_sha256, contract.cp74_policy_sha256,
        contract.runtime_policy_sha256, contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp75_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold("HOLD_CP75_CONTRACT_HASH")
