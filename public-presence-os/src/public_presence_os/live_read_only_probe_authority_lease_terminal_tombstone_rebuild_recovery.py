from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_expiry_revocation import (
    compile_live_read_only_probe_authority_lease_expiry_revocation,
)
from .live_read_only_probe_authority_lease_replay_stale_receipt import (
    build_authority_lease_replay_stale_receipt_dry_run,
    compile_live_read_only_probe_authority_lease_replay_stale_receipt,
)
from .live_read_only_probe_authority_lease_terminal_tombstone_reconciliation import (
    CHECKPOINT as CP73_CHECKPOINT,
    STATE as CP73_STATE,
    LedgerEntry,
    TerminalTombstone,
    build_authority_lease_terminal_tombstone_reconciliation_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation,
    validate_authority_lease_terminal_tombstone_reconciliation_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-rebuild-recovery-dry-run-v1.0.0"
STATE = "PASS_CP74_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN_LOCAL_ONLY_EXACT_REBUILD_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP74"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP75_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_DRY_RUN"
RECOVERY_PHASES = (
    "CP73_PARENT_EXACT_BOUND",
    "EXPIRY_MISSING_TOMBSTONE_REBUILT",
    "EXPIRY_CORRUPTED_TOMBSTONE_REBUILT",
    "REVOCATION_MISSING_TOMBSTONE_REBUILT",
    "REVOCATION_CORRUPTED_TOMBSTONE_REBUILT",
    "EXACT_CANONICAL_TOMBSTONE_HASH_REPRODUCED",
    "SIMULATED_RESTORE_ONLY_NO_STORAGE_WRITE",
    "ZERO_IO_OBSERVED",
    "AUTHORITY_REMAINS_INACTIVE",
)
RECOVERY_CASES = (
    ("EXPIRY_PATH", "MISSING_TOMBSTONE"),
    ("EXPIRY_PATH", "CORRUPTED_TOMBSTONE"),
    ("REVOCATION_PATH", "MISSING_TOMBSTONE"),
    ("REVOCATION_PATH", "CORRUPTED_TOMBSTONE"),
)
REQUIRED_BLOCKERS = (
    "HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
    "HOLD_CP74_RECOVERY_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP74_REBUILD_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold(ValueError):
    pass


@dataclass(frozen=True)
class TombstoneRecoveryCase:
    scenario: str
    failure_mode: str
    original_tombstone_id: str
    original_tombstone_hash: str
    observed_tombstone_hash: str | None
    rebuilt_tombstone: TerminalTombstone
    ledger_terminal_entry_hash: str
    exact_rebuild: bool
    recovery_action: str = "SIMULATED_RESTORE_ONLY"
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rebuilt_tombstone"] = self.rebuilt_tombstone.to_dict()
        return d


@dataclass(frozen=True)
class AuthorityLeaseTerminalTombstoneRebuildRecoveryDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp73_contract_id: str
    cp73_contract_hash: str
    cp73_dry_run_id: str
    cp73_dry_run_hash: str
    lease_id: str
    lease_hash: str
    recovery_cases: tuple[TombstoneRecoveryCase, ...]
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
        d["recovery_cases"] = [x.to_dict() for x in self.recovery_cases]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryContract:
    contract_id: str
    contract_hash: str
    cp73_contract_id: str
    cp73_contract_hash: str
    cp73_dry_run_id: str
    cp73_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp73_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP73_CHECKPOINT
    parent_cp73_state: str = CP73_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    exact_rebuild_validated: bool = True
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
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_POLICY_V1",
        CHECKPOINT,
        "M43_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP73_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE or tuple(policy.get("recovery_phases", ())) != RECOVERY_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_SCOPE_OR_PHASE_DRIFT")
    if tuple(tuple(x) for x in policy.get("recovery_cases", ())) != RECOVERY_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_RECOVERY_CASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP73_CHECKPOINT or policy.get("next_after_cp74") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CONTINUITY_DRIFT")
    g = policy.get("recovery_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp73_tombstone_ledger_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp73_contract_binding_required", "exact_cp73_dry_run_binding_required",
        "exact_lease_binding_required", "recovery_source_ledger_only", "terminal_entry_unique_required",
        "missing_tombstone_rebuild_required", "corrupted_tombstone_rebuild_required",
        "exact_original_tombstone_hash_reproduction_required", "simulated_restore_only",
        "storage_write_forbidden", "runtime_mutation_forbidden", "registry_mutation_forbidden",
        "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged", "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled", "publish_must_remain_disabled", "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted", "secret_resolution_forbidden", "environment_read_forbidden",
        "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden", "network_forbidden",
        "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(g.get(k) is not True for k in required):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_GUARD_WEAKENED")
    if tuple(g.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_METHOD_DRIFT")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_RUNTIME_POLICY")
    if any(runtime.get(k) is not False for k in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CONTROL_PROMOTION")
    if states.get("M42_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION") != "CP73_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_DRY_RUN_LOCAL_ONLY_LEDGER_CONSISTENT_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CP73_STATE")
    if states.get("M43_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY") != "CP74_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN_LOCAL_ONLY_EXACT_REBUILD_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_MODULE_STATE")


def _rebuild_tombstone(scenario: str, ledger: tuple[LedgerEntry, ...], cp73_dry_run: Any) -> TerminalTombstone:
    accepted = [x for x in ledger if x.decision == "ACCEPTED" and x.claim_state in ("EXPIRED", "REVOKED")]
    if len(accepted) != 1:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_TERMINAL_NOT_UNIQUE")
    terminal = accepted[0]
    body = {
        "scenario": scenario,
        "lease_id": cp73_dry_run.lease_id,
        "lease_hash": cp73_dry_run.lease_hash,
        "terminal_state": terminal.claim_state,
        "terminal_at_utc": terminal.presented_at_utc,
        "terminal_receipt_id": terminal.receipt_id,
        "terminal_receipt_hash": terminal.receipt_hash,
        "ledger_terminal_entry_hash": terminal.entry_hash,
        "cp72_dry_run_hash": cp73_dry_run.cp72_dry_run_hash,
        "immutable": True,
        "synthetic_only": True,
    }
    digest = _hash(body)
    return TerminalTombstone(tombstone_id=f"cp73_tombstone_{digest[:24]}", tombstone_hash=digest, **body)


def _case(scenario: str, failure_mode: str, ledger: tuple[LedgerEntry, ...], original: TerminalTombstone, cp73_dry_run: Any) -> TombstoneRecoveryCase:
    rebuilt = _rebuild_tombstone(scenario, ledger, cp73_dry_run)
    observed = None if failure_mode == "MISSING_TOMBSTONE" else _hash(
        {"synthetic_corruption_of": original.tombstone_hash, "scenario": scenario}
    )
    terminal = next(x for x in ledger if x.decision == "ACCEPTED")
    case = TombstoneRecoveryCase(
        scenario=scenario,
        failure_mode=failure_mode,
        original_tombstone_id=original.tombstone_id,
        original_tombstone_hash=original.tombstone_hash,
        observed_tombstone_hash=observed,
        rebuilt_tombstone=rebuilt,
        ledger_terminal_entry_hash=terminal.entry_hash,
        exact_rebuild=rebuilt.to_dict() == original.to_dict(),
    )
    _validate_case(case, original)
    return case


def _validate_case(case: TombstoneRecoveryCase, original: TerminalTombstone) -> None:
    if (case.scenario, case.failure_mode) not in RECOVERY_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CASE_IDENTITY")
    if (case.original_tombstone_id, case.original_tombstone_hash) != (original.tombstone_id, original.tombstone_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_ORIGINAL_BINDING")
    if case.failure_mode == "MISSING_TOMBSTONE":
        if case.observed_tombstone_hash is not None:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_MISSING_OBSERVATION")
    else:
        if not _hex(case.observed_tombstone_hash) or case.observed_tombstone_hash == original.tombstone_hash:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CORRUPTION_NOT_DISTINCT")
    if not case.exact_rebuild or case.rebuilt_tombstone.to_dict() != original.to_dict():
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_REBUILD_NOT_EXACT")
    if case.recovery_action != "SIMULATED_RESTORE_ONLY" or case.storage_write_performed or case.runtime_mutated:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_RECOVERY_MUTATION")
    if case.rebuilt_tombstone.ledger_terminal_entry_hash != case.ledger_terminal_entry_hash:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_LEDGER_BINDING")


def _cp72_contract_for_validation(cp73_dry_run: Any) -> Any:
    class _Parent:
        contract_id = cp73_dry_run.cp72_contract_id
        contract_hash = cp73_dry_run.cp72_contract_hash
        lease_id = cp73_dry_run.lease_id
        lease_hash = cp73_dry_run.lease_hash
    return _Parent()


def build_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(
    cp73_contract: Any,
    cp73_dry_run: Any,
) -> AuthorityLeaseTerminalTombstoneRebuildRecoveryDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_contract(cp73_contract)
    validate_authority_lease_terminal_tombstone_reconciliation_dry_run(
        cp73_dry_run,
        _cp72_contract_for_validation(cp73_dry_run),
    )
    if (cp73_contract.dry_run_id, cp73_contract.dry_run_hash) != (cp73_dry_run.dry_run_id, cp73_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CP73_DRY_RUN_BINDING")
    cases = (
        _case("EXPIRY_PATH", "MISSING_TOMBSTONE", cp73_dry_run.expiry_ledger, cp73_dry_run.expiry_tombstone, cp73_dry_run),
        _case("EXPIRY_PATH", "CORRUPTED_TOMBSTONE", cp73_dry_run.expiry_ledger, cp73_dry_run.expiry_tombstone, cp73_dry_run),
        _case("REVOCATION_PATH", "MISSING_TOMBSTONE", cp73_dry_run.revocation_ledger, cp73_dry_run.revocation_tombstone, cp73_dry_run),
        _case("REVOCATION_PATH", "CORRUPTED_TOMBSTONE", cp73_dry_run.revocation_ledger, cp73_dry_run.revocation_tombstone, cp73_dry_run),
    )
    body = {
        "cp73_contract_id": cp73_contract.contract_id,
        "cp73_contract_hash": cp73_contract.contract_hash,
        "cp73_dry_run_id": cp73_dry_run.dry_run_id,
        "cp73_dry_run_hash": cp73_dry_run.dry_run_hash,
        "lease_id": cp73_contract.lease_id,
        "lease_hash": cp73_contract.lease_hash,
        "recovery_cases": [x.to_dict() for x in cases],
        "phases": list(RECOVERY_PHASES),
        "outcome": "SIMULATED_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_PASS_EXACT_REBUILD_NO_STORAGE_WRITE_NO_AUTHORITY",
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
    body["recovery_cases"] = cases
    body["phases"] = RECOVERY_PHASES
    dry = AuthorityLeaseTerminalTombstoneRebuildRecoveryDryRun(
        dry_run_id=f"cp74_dry_run_{digest[:24]}",
        dry_run_hash=digest,
        **body,
    )
    validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(dry, cp73_contract, cp73_dry_run)
    return dry


def validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(
    dry: AuthorityLeaseTerminalTombstoneRebuildRecoveryDryRun,
    cp73_contract: Any,
    cp73_dry_run: Any,
) -> None:
    if (dry.cp73_contract_id, dry.cp73_contract_hash, dry.cp73_dry_run_id, dry.cp73_dry_run_hash, dry.lease_id, dry.lease_hash) != (
        cp73_contract.contract_id, cp73_contract.contract_hash, cp73_dry_run.dry_run_id, cp73_dry_run.dry_run_hash,
        cp73_contract.lease_id, cp73_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_PARENT_BINDING")
    originals = {
        "EXPIRY_PATH": cp73_dry_run.expiry_tombstone,
        "REVOCATION_PATH": cp73_dry_run.revocation_tombstone,
    }
    if tuple((x.scenario, x.failure_mode) for x in dry.recovery_cases) != RECOVERY_CASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CASE_SET")
    for case in dry.recovery_cases:
        _validate_case(case, originals[case.scenario])
    if dry.phases != RECOVERY_PHASES or dry.outcome != "SIMULATED_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_PASS_EXACT_REBUILD_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_OUTCOME_OR_PHASES")
    if not dry.global_kill_switch_engaged or not dry.zero_io_observed:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_ZERO_IO_OR_KILL_SWITCH")
    for k in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed",
        "deploy_allowed", "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, k) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp74_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_DRY_RUN_HASH")


def _build_cp73_dry_run(root: Path, cp73_contract: Any) -> Any:
    cp72_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_replay_stale_receipt_policy.json")
    cp72 = compile_live_read_only_probe_authority_lease_replay_stale_receipt(root, cp72_policy)
    cp71_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json")
    cp71 = compile_live_read_only_probe_authority_lease_expiry_revocation(root, cp71_policy)
    cp72_dry = build_authority_lease_replay_stale_receipt_dry_run(cp71)
    cp73_dry = build_authority_lease_terminal_tombstone_reconciliation_dry_run(cp72, cp72_dry)
    if (cp73_contract.dry_run_id, cp73_contract.dry_run_hash) != (cp73_dry.dry_run_id, cp73_dry.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_PARENT_REBUILD_DRIFT")
    return cp73_dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp73_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_policy.json")
    cp73 = compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(root, cp73_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_contract(cp73)
    cp73_dry = _build_cp73_dry_run(root, cp73)
    dry = build_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(cp73, cp73_dry)
    body = {
        "cp73_contract_id": cp73.contract_id,
        "cp73_contract_hash": cp73.contract_hash,
        "cp73_dry_run_id": cp73_dry.dry_run_id,
        "cp73_dry_run_hash": cp73_dry.dry_run_hash,
        "lease_id": cp73.lease_id,
        "lease_hash": cp73.lease_hash,
        "dry_run_id": dry.dry_run_id,
        "dry_run_hash": dry.dry_run_hash,
        "policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_policy.json").read_bytes()).hexdigest(),
        "cp73_policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_policy.json").read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        "module_registry_sha256": sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
    }
    defaults = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryContract.__dataclass_fields__
    for k in (
        "next_unit", "checkpoint", "parent_control_checkpoint", "parent_activation_checkpoint", "parent_cp73_state",
        "model_version", "engine_version", "exact_rebuild_validated", "simulated_recovery_only",
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
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryContract(
        contract_id=f"cp74_contract_{digest[:24]}",
        contract_hash=digest,
        **body,
    )
    validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryContract,
) -> None:
    if (
        contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint,
        contract.parent_cp73_state, contract.state, contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP73_CHECKPOINT, CP73_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only
        or not contract.exact_rebuild_validated or not contract.simulated_recovery_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CONTRACT_SCOPE_OR_GUARD")
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
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(x) for x in (
        contract.contract_hash, contract.cp73_contract_hash, contract.cp73_dry_run_hash, contract.lease_hash,
        contract.dry_run_hash, contract.policy_sha256, contract.cp73_policy_sha256,
        contract.runtime_policy_sha256, contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp74_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold("HOLD_CP74_CONTRACT_HASH")
