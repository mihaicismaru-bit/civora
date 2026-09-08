from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection import build_valid_recovery_journal
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection import (
    CHECKPOINT as CP78_CHECKPOINT,
    STATE as CP78_STATE,
    TRUNCATION_CLASSES,
    _build_cp78_evidence,
    _cut_offset,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection,
    serialize_recovery_journal,
    validate_complete_serialized_recovery_journal,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-journal-complete-write-atomic-visibility-dry-run-v1.0.0"
STATE = "PASS_CP79_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY_DRY_RUN_LOCAL_ONLY_NO_TORN_VISIBILITY_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP79"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP80_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW_DRY_RUN"
VISIBILITY_PHASES = (
    "BEFORE_STAGE",
    "STAGED_NOT_COMMITTED",
    "COMMIT_BOUNDARY",
    "AFTER_COMMIT",
)
VALIDATION_PHASES = (
    "CP78_PARENT_EXACT_BOUND",
    "TWELVE_COMPLETE_JOURNALS_REVALIDATED",
    "FOUR_VISIBILITY_PHASES_APPLIED_TO_EACH_PARENT_JOURNAL",
    "FORTY_EIGHT_VISIBILITY_OBSERVATIONS_VALIDATED",
    "NO_STRICT_PREFIX_OR_TORN_STATE_VISIBLE",
    "COMMIT_BOUNDARY_EXPOSES_ONLY_COMPLETE_CANONICAL_BYTES",
    "BASELINE_PRESERVED_BEFORE_COMMIT",
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
    "HOLD_CP79_RECOVERY_JOURNAL_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP79_ATOMIC_VISIBILITY_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold(ValueError):
    pass


@dataclass(frozen=True)
class AtomicVisibilityObservation:
    phase: str
    visible_state: str
    visible_length: int
    visible_sha256: str | None
    complete_visible: bool
    partial_visible: bool
    baseline_preserved: bool
    simulated_only: bool = True
    storage_read_performed: bool = False
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JournalCompleteWriteAtomicVisibilityCase:
    parent_transaction_id: str
    baseline_snapshot_hash: str
    complete_serialized_length: int
    complete_serialized_sha256: str
    forbidden_prefix_sha256s: tuple[str, ...]
    observations: tuple[AtomicVisibilityObservation, ...]
    atomic_visibility_validated: bool = True
    zero_partial_visibility_observed: bool = True
    commit_exposes_complete_bytes_only: bool = True
    simulated_journal_only: bool = True
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["forbidden_prefix_sha256s"] = list(self.forbidden_prefix_sha256s)
        d["observations"] = [x.to_dict() for x in self.observations]
        return d


@dataclass(frozen=True)
class AuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp76_contract_id: str
    cp76_contract_hash: str
    cp78_contract_id: str
    cp78_contract_hash: str
    cp78_dry_run_id: str
    cp78_dry_run_hash: str
    lease_id: str
    lease_hash: str
    visibility_cases: tuple[JournalCompleteWriteAtomicVisibilityCase, ...]
    phases: tuple[str, ...]
    outcome: str
    all_twelve_complete_journals_validated: bool = True
    all_forty_eight_observations_validated: bool = True
    zero_partial_visibility_observed: bool = True
    all_commit_snapshots_exact: bool = True
    baseline_preserved_before_commit: bool = True
    global_kill_switch_engaged: bool = True
    zero_io_observed: bool = True
    simulated_journal_only: bool = True
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
        d["visibility_cases"] = [x.to_dict() for x in self.visibility_cases]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityContract:
    contract_id: str
    contract_hash: str
    cp76_contract_id: str
    cp76_contract_hash: str
    cp78_contract_id: str
    cp78_contract_hash: str
    cp78_dry_run_id: str
    cp78_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp78_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP78_CHECKPOINT
    parent_cp78_state: str = CP78_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    complete_write_atomic_visibility_validated: bool = True
    all_twelve_parent_journals_validated: bool = True
    all_four_visibility_phases_validated: bool = True
    all_forty_eight_observations_validated: bool = True
    zero_partial_visibility_observed: bool = True
    baseline_preservation_validated: bool = True
    synthetic_validation_only: bool = True
    simulated_journal_only: bool = True
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


def _raw_hash(value: bytes) -> str:
    return sha256(value).hexdigest()


def _without(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in keys}


def _hex(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY_POLICY_V1",
        CHECKPOINT,
        "M48_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP78_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_SCOPE_DRIFT")
    if tuple(policy.get("visibility_phases", ())) != VISIBILITY_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_VISIBILITY_PHASE_DRIFT")
    if tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP78_CHECKPOINT or policy.get("next_after_cp79") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CONTINUITY_DRIFT")
    guard = policy.get("atomic_visibility_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp78_journal_only", "canonical_json_required",
        "serialized_sha256_required", "exact_serialized_length_required", "exact_cp78_contract_binding_required",
        "exact_cp78_dry_run_binding_required", "exact_cp76_contract_binding_required", "exact_lease_binding_required",
        "all_twelve_parent_journals_required", "all_four_visibility_phases_required",
        "exactly_forty_eight_observations_required", "precommit_visibility_must_be_absent",
        "postcommit_visibility_must_be_complete", "strict_prefix_visibility_forbidden", "torn_visibility_forbidden",
        "commit_boundary_exact_bytes_required", "baseline_preservation_before_commit_required", "simulated_journal_only",
        "storage_write_forbidden", "runtime_mutation_forbidden", "registry_mutation_forbidden", "policy_mutation_forbidden",
        "global_kill_switch_must_remain_engaged", "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled", "publish_must_remain_disabled", "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted", "secret_resolution_forbidden", "environment_read_forbidden",
        "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden", "network_forbidden",
        "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(guard.get(key) is not True for key in required):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_GUARD_WEAKENED")
    if tuple(guard.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_METHOD_DRIFT")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CONTROL_PROMOTION")
    if states.get("M47_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION") != CP78_STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CP78_STATE")
    if states.get("M48_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY") != STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_MODULE_STATE")


def _build_visibility_case(journal: dict[str, Any], parent_case: Any, cp76_contract: Any) -> JournalCompleteWriteAtomicVisibilityCase:
    raw = serialize_recovery_journal(journal)
    complete_hash = _raw_hash(raw)
    validate_complete_serialized_recovery_journal(raw, len(raw), complete_hash, parent_case, cp76_contract)
    forbidden_prefixes = tuple(_raw_hash(raw[:_cut_offset(raw, cls)]) for cls in TRUNCATION_CLASSES)
    observations = (
        AtomicVisibilityObservation("BEFORE_STAGE", "ABSENT", 0, None, False, False, True),
        AtomicVisibilityObservation("STAGED_NOT_COMMITTED", "ABSENT", 0, None, False, False, True),
        AtomicVisibilityObservation("COMMIT_BOUNDARY", "COMPLETE", len(raw), complete_hash, True, False, True),
        AtomicVisibilityObservation("AFTER_COMMIT", "COMPLETE", len(raw), complete_hash, True, False, True),
    )
    result = JournalCompleteWriteAtomicVisibilityCase(
        parent_transaction_id=parent_case.transaction_id,
        baseline_snapshot_hash=parent_case.baseline_snapshot_hash,
        complete_serialized_length=len(raw),
        complete_serialized_sha256=complete_hash,
        forbidden_prefix_sha256s=forbidden_prefixes,
        observations=observations,
    )
    _validate_visibility_case(result)
    return result


def _validate_visibility_case(case: JournalCompleteWriteAtomicVisibilityCase) -> None:
    if case.complete_serialized_length <= 1 or not _hex(case.complete_serialized_sha256) or not _hex(case.baseline_snapshot_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CASE_IDENTITY")
    if len(case.forbidden_prefix_sha256s) != len(TRUNCATION_CLASSES) or not all(_hex(x) for x in case.forbidden_prefix_sha256s):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_FORBIDDEN_PREFIX_SET")
    if tuple(x.phase for x in case.observations) != VISIBILITY_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_OBSERVATION_PHASE_SET")
    for index, obs in enumerate(case.observations):
        if obs.partial_visible or not obs.baseline_preserved or not obs.simulated_only or obs.storage_read_performed or obs.storage_write_performed or obs.runtime_mutated:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_TORN_OR_MUTATING_OBSERVATION")
        if index < 2:
            if obs.visible_state != "ABSENT" or obs.visible_length != 0 or obs.visible_sha256 is not None or obs.complete_visible:
                raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_PRECOMMIT_VISIBILITY")
        else:
            if (
                obs.visible_state != "COMPLETE" or obs.visible_length != case.complete_serialized_length
                or obs.visible_sha256 != case.complete_serialized_sha256 or not obs.complete_visible
            ):
                raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_POSTCOMMIT_VISIBILITY")
            if obs.visible_sha256 in case.forbidden_prefix_sha256s:
                raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_PREFIX_BECAME_VISIBLE")
    if not case.atomic_visibility_validated or not case.zero_partial_visibility_observed or not case.commit_exposes_complete_bytes_only:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CASE_GUARD")
    if not case.simulated_journal_only or case.storage_write_performed or case.runtime_mutated:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CASE_MUTATION")


def build_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
    cp76_contract: Any,
    cp76_dry_run: Any,
    cp78_contract: Any,
    cp78_dry_run: Any,
) -> AuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_contract(cp78_contract)
    if (cp78_contract.dry_run_id, cp78_contract.dry_run_hash) != (cp78_dry_run.dry_run_id, cp78_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CP78_DRY_RUN_BINDING")
    journals = tuple(build_valid_recovery_journal(case, cp76_contract) for case in cp76_dry_run.crash_cases)
    cases = tuple(_build_visibility_case(journal, parent_case, cp76_contract) for journal, parent_case in zip(journals, cp76_dry_run.crash_cases))
    dry = AuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityDryRun(
        dry_run_id="",
        dry_run_hash="",
        cp76_contract_id=cp76_contract.contract_id,
        cp76_contract_hash=cp76_contract.contract_hash,
        cp78_contract_id=cp78_contract.contract_id,
        cp78_contract_hash=cp78_contract.contract_hash,
        cp78_dry_run_id=cp78_dry_run.dry_run_id,
        cp78_dry_run_hash=cp78_dry_run.dry_run_hash,
        lease_id=cp76_contract.lease_id,
        lease_hash=cp76_contract.lease_hash,
        visibility_cases=cases,
        phases=VALIDATION_PHASES,
        outcome="SIMULATED_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY_PASS_12_OF_12_48_OF_48_NO_TORN_VISIBILITY_NO_STORAGE_WRITE_NO_AUTHORITY",
    )
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    dry = replace(dry, dry_run_id=f"cp79_dry_run_{digest[:24]}", dry_run_hash=digest)
    validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
        dry, cp76_contract, cp76_dry_run, cp78_contract, cp78_dry_run
    )
    return dry


def validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
    dry: AuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityDryRun,
    cp76_contract: Any,
    cp76_dry_run: Any,
    cp78_contract: Any,
    cp78_dry_run: Any,
) -> None:
    if (
        dry.cp76_contract_id, dry.cp76_contract_hash, dry.cp78_contract_id, dry.cp78_contract_hash,
        dry.cp78_dry_run_id, dry.cp78_dry_run_hash, dry.lease_id, dry.lease_hash,
    ) != (
        cp76_contract.contract_id, cp76_contract.contract_hash, cp78_contract.contract_id, cp78_contract.contract_hash,
        cp78_dry_run.dry_run_id, cp78_dry_run.dry_run_hash, cp76_contract.lease_id, cp76_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_PARENT_BINDING")
    if len(dry.visibility_cases) != len(cp76_dry_run.crash_cases) or len(dry.visibility_cases) != 12:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CASE_SET")
    for case in dry.visibility_cases:
        _validate_visibility_case(case)
    if sum(len(x.observations) for x in dry.visibility_cases) != 48:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_OBSERVATION_COUNT")
    if dry.phases != VALIDATION_PHASES or dry.outcome != "SIMULATED_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY_PASS_12_OF_12_48_OF_48_NO_TORN_VISIBILITY_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_OUTCOME_OR_PHASES")
    if (
        not dry.all_twelve_complete_journals_validated or not dry.all_forty_eight_observations_validated
        or not dry.zero_partial_visibility_observed or not dry.all_commit_snapshots_exact
        or not dry.baseline_preserved_before_commit or not dry.global_kill_switch_engaged
        or not dry.zero_io_observed or not dry.simulated_journal_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_ZERO_IO_OR_GUARD")
    for key in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed", "deploy_allowed",
        "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp79_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_DRY_RUN_HASH")


def _build_cp79_evidence(root: Path) -> tuple[Any, Any, Any, Any, Any, Any]:
    cp76, cp76_dry, cp77_dry, cp78_dry = _build_cp78_evidence(root)
    cp78_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_policy.json")
    cp78_contract = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection(root, cp78_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_contract(cp78_contract)
    dry = build_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
        cp76, cp76_dry, cp78_contract, cp78_dry
    )
    return cp76, cp76_dry, cp77_dry, cp78_contract, cp78_dry, dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp76, cp76_dry, _cp77_dry, cp78_contract, cp78_dry, dry = _build_cp79_evidence(root)
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityContract(
        contract_id="",
        contract_hash="",
        cp76_contract_id=cp76.contract_id,
        cp76_contract_hash=cp76.contract_hash,
        cp78_contract_id=cp78_contract.contract_id,
        cp78_contract_hash=cp78_contract.contract_hash,
        cp78_dry_run_id=cp78_dry.dry_run_id,
        cp78_dry_run_hash=cp78_dry.dry_run_hash,
        lease_id=cp76.lease_id,
        lease_hash=cp76.lease_hash,
        dry_run_id=dry.dry_run_id,
        dry_run_hash=dry.dry_run_hash,
        policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_policy.json").read_bytes()).hexdigest(),
        cp78_policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_policy.json").read_bytes()).hexdigest(),
        runtime_policy_sha256=sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        module_registry_sha256=sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        active_platforms=EXPECTED_ACTIVE,
        blockers=REQUIRED_BLOCKERS,
    )
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    contract = replace(contract, contract_id=f"cp79_contract_{digest[:24]}", contract_hash=digest)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityContract,
) -> None:
    if (
        contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint,
        contract.parent_cp78_state, contract.state, contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP78_CHECKPOINT, CP78_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only or not contract.simulated_journal_only
        or not contract.complete_write_atomic_visibility_validated or not contract.all_twelve_parent_journals_validated
        or not contract.all_four_visibility_phases_validated or not contract.all_forty_eight_observations_validated
        or not contract.zero_partial_visibility_observed or not contract.baseline_preservation_validated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CONTRACT_SCOPE_OR_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted",
        "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted",
        "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed", "storage_write_allowed",
        "storage_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used",
        "authority_activated", "runtime_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(getattr(contract, key)) for key in (
        "cp76_contract_hash", "cp78_contract_hash", "cp78_dry_run_hash", "lease_hash", "dry_run_hash",
        "policy_sha256", "cp78_policy_sha256", "runtime_policy_sha256", "module_registry_sha256",
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp79_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold("HOLD_CP79_CONTRACT_HASH")
