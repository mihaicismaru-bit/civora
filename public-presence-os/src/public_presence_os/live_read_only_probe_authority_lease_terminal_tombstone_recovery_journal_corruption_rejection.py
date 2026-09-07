from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback import (
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback,
)
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency import (
    CHECKPOINT as CP76_CHECKPOINT,
    STATE as CP76_STATE,
    _build_cp75_dry_run,
    build_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency,
    validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-journal-corruption-rejection-dry-run-v1.0.0"
STATE = "PASS_CP77_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_DRY_RUN_LOCAL_ONLY_FAIL_CLOSED_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP77"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP78_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_DRY_RUN"
JOURNAL_SCHEMA_VERSION = "PPOS_CP77_SYNTHETIC_RECOVERY_JOURNAL_V1"
CORRUPTION_CLASSES = (
    "MALFORMED_SCHEMA_VERSION",
    "MISSING_REQUIRED_FIELD",
    "DUPLICATE_CONFLICTING_ENTRY",
    "ILLEGAL_PHASE_ORDER",
    "BASELINE_HASH_MISMATCH",
    "PAYLOAD_HASH_TAMPER",
    "INVALID_COMMIT_MARKER_BINDING",
    "TERMINAL_BINDING_MISMATCH",
)
EXPECTED_HOLDS = {
    "MALFORMED_SCHEMA_VERSION": "HOLD_CP77_JOURNAL_SCHEMA",
    "MISSING_REQUIRED_FIELD": "HOLD_CP77_REQUIRED_FIELD",
    "DUPLICATE_CONFLICTING_ENTRY": "HOLD_CP77_DUPLICATE_CONFLICTING_TRANSACTION",
    "ILLEGAL_PHASE_ORDER": "HOLD_CP77_PHASE_ORDER",
    "BASELINE_HASH_MISMATCH": "HOLD_CP77_PARENT_BINDING",
    "PAYLOAD_HASH_TAMPER": "HOLD_CP77_PAYLOAD_HASH",
    "INVALID_COMMIT_MARKER_BINDING": "HOLD_CP77_PARENT_RECORD_BINDING",
    "TERMINAL_BINDING_MISMATCH": "HOLD_CP77_TERMINAL_BINDING",
}
VALIDATION_PHASES = (
    "CP76_PARENT_EXACT_BOUND",
    "VALID_JOURNAL_POSITIVE_CONTROL_ACCEPTED",
    "EIGHT_CORRUPTION_CLASSES_INJECTED_DETERMINISTICALLY",
    "SEMANTIC_CORRUPTION_REJECTED_FAIL_CLOSED",
    "DIGEST_CORRUPTION_REJECTED_FAIL_CLOSED",
    "DUPLICATE_CONFLICT_REJECTED_BEFORE_RECOVERY",
    "BASELINE_PRESERVED_ON_ALL_REJECTIONS",
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
    "HOLD_CP77_RECOVERY_JOURNAL_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP77_CORRUPTION_REJECTION_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold(ValueError):
    pass


@dataclass(frozen=True)
class JournalCorruptionRejectionCase:
    corruption_class: str
    parent_transaction_id: str
    parent_journal_hash: str
    corrupted_journal_hash: str
    expected_hold: str
    observed_hold: str
    rejected: bool
    rejection_before_recovery_effect: bool
    baseline_snapshot_hash: str
    baseline_preserved: bool
    recovery_effect_count: int = 0
    simulated_journal_only: bool = True
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp76_contract_id: str
    cp76_contract_hash: str
    cp76_dry_run_id: str
    cp76_dry_run_hash: str
    lease_id: str
    lease_hash: str
    positive_control_journal_hashes: tuple[str, ...]
    rejection_cases: tuple[JournalCorruptionRejectionCase, ...]
    phases: tuple[str, ...]
    outcome: str
    all_corruptions_rejected: bool = True
    baseline_preserved: bool = True
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
        d["positive_control_journal_hashes"] = list(self.positive_control_journal_hashes)
        d["rejection_cases"] = [x.to_dict() for x in self.rejection_cases]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionContract:
    contract_id: str
    contract_hash: str
    cp76_contract_id: str
    cp76_contract_hash: str
    cp76_dry_run_id: str
    cp76_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp76_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP76_CHECKPOINT
    parent_cp76_state: str = CP76_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    valid_journal_positive_control_validated: bool = True
    corruption_rejection_validated: bool = True
    all_eight_corruption_classes_validated: bool = True
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


def _without(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in keys}


def _hex(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_POLICY_V1",
        CHECKPOINT,
        "M46_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP76_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_SCOPE_DRIFT")
    if tuple(policy.get("corruption_classes", ())) != CORRUPTION_CLASSES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CORRUPTION_CLASS_DRIFT")
    if tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP76_CHECKPOINT or policy.get("next_after_cp77") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CONTINUITY_DRIFT")
    guard = policy.get("journal_corruption_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp76_journal_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp76_contract_binding_required", "exact_cp76_dry_run_binding_required",
        "exact_lease_binding_required", "valid_positive_control_required", "all_eight_corruption_classes_required",
        "schema_drift_rejection_required", "missing_required_field_rejection_required",
        "duplicate_conflicting_entry_rejection_required", "illegal_phase_order_rejection_required",
        "baseline_hash_mismatch_rejection_required", "payload_hash_tamper_rejection_required",
        "invalid_commit_marker_binding_rejection_required", "terminal_binding_mismatch_rejection_required",
        "rejection_must_precede_recovery_effect", "baseline_preservation_required", "simulated_journal_only",
        "storage_write_forbidden", "runtime_mutation_forbidden", "registry_mutation_forbidden",
        "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged", "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled", "publish_must_remain_disabled", "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted", "secret_resolution_forbidden", "environment_read_forbidden",
        "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden", "network_forbidden",
        "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(guard.get(key) is not True for key in required):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_GUARD_WEAKENED")
    if tuple(guard.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_METHOD_DRIFT")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CONTROL_PROMOTION")
    if states.get("M45_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY") != "CP76_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_DRY_RUN_LOCAL_ONLY_NO_TORN_STATE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CP76_STATE")
    if states.get("M46_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION") != "CP77_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_DRY_RUN_LOCAL_ONLY_FAIL_CLOSED_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_MODULE_STATE")


def _expected_phases(crash_point: str) -> tuple[str, ...]:
    if crash_point == "AFTER_PREPARE_BEFORE_STAGE":
        return ("PREPARED",)
    if crash_point == "AFTER_STAGE_BEFORE_COMMIT_MARKER":
        return ("PREPARED", "STAGED")
    if crash_point == "AFTER_COMMIT_MARKER_BEFORE_ACK":
        return ("PREPARED", "STAGED", "COMMIT_MARKED")
    raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CRASH_POINT")


def _parent_record_hashes(case: Any) -> tuple[str, ...]:
    values = [case.prepare_record_hash]
    if case.staged_record_hash is not None:
        values.append(case.staged_record_hash)
    if case.commit_marker_hash is not None:
        values.append(case.commit_marker_hash)
    return tuple(values)


def _terminal_binding_hash(case: Any, cp76_contract: Any) -> str:
    return _hash({
        "transaction_id": case.transaction_id,
        "lease_id": cp76_contract.lease_id,
        "lease_hash": cp76_contract.lease_hash,
        "baseline_snapshot_hash": case.baseline_snapshot_hash,
        "intended_recovery_result_hash": case.intended_recovery_result_hash,
        "restart_converged_result_hash": case.restart_converged_result_hash,
    })


def _reseal_journal(journal: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(journal)
    out["payload_hash"] = _hash(_without(out, "payload_hash", "journal_hash"))
    out["journal_hash"] = _hash(_without(out, "journal_hash"))
    return out


def build_valid_recovery_journal(case: Any, cp76_contract: Any) -> dict[str, Any]:
    phases = _expected_phases(case.crash_point)
    parent_hashes = _parent_record_hashes(case)
    records = []
    for sequence, (phase, parent_record_hash) in enumerate(zip(phases, parent_hashes), start=1):
        core = {"sequence": sequence, "phase": phase, "parent_record_hash": parent_record_hash, "transaction_id": case.transaction_id}
        records.append({**core, "entry_hash": _hash(core)})
    journal = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "cp76_contract_id": cp76_contract.contract_id,
        "cp76_contract_hash": cp76_contract.contract_hash,
        "lease_id": cp76_contract.lease_id,
        "lease_hash": cp76_contract.lease_hash,
        "transaction_id": case.transaction_id,
        "scenario": case.scenario,
        "failure_mode": case.failure_mode,
        "crash_point": case.crash_point,
        "baseline_snapshot_hash": case.baseline_snapshot_hash,
        "intended_recovery_result_hash": case.intended_recovery_result_hash,
        "phase_sequence": list(phases),
        "records": records,
        "terminal_binding_hash": _terminal_binding_hash(case, cp76_contract),
        "simulated_only": True,
        "storage_write_performed": False,
        "runtime_mutated": False,
    }
    return _reseal_journal(journal)


def validate_recovery_journal(journal: dict[str, Any], case: Any, cp76_contract: Any) -> None:
    required_fields = {
        "schema_version", "cp76_contract_id", "cp76_contract_hash", "lease_id", "lease_hash", "transaction_id",
        "scenario", "failure_mode", "crash_point", "baseline_snapshot_hash", "intended_recovery_result_hash",
        "phase_sequence", "records", "terminal_binding_hash", "simulated_only", "storage_write_performed",
        "runtime_mutated", "payload_hash", "journal_hash",
    }
    if set(journal) != required_fields:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_REQUIRED_FIELD")
    if journal.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_JOURNAL_SCHEMA")
    if (journal.get("cp76_contract_id"), journal.get("cp76_contract_hash"), journal.get("lease_id"), journal.get("lease_hash")) != (
        cp76_contract.contract_id, cp76_contract.contract_hash, cp76_contract.lease_id, cp76_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CP76_BINDING")
    if (
        journal.get("transaction_id"), journal.get("scenario"), journal.get("failure_mode"), journal.get("crash_point"),
        journal.get("baseline_snapshot_hash"), journal.get("intended_recovery_result_hash"),
    ) != (
        case.transaction_id, case.scenario, case.failure_mode, case.crash_point,
        case.baseline_snapshot_hash, case.intended_recovery_result_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PARENT_BINDING")
    expected_phases = _expected_phases(case.crash_point)
    if tuple(journal.get("phase_sequence", ())) != expected_phases:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PHASE_ORDER")
    records = journal.get("records")
    if not isinstance(records, list) or len(records) != len(expected_phases):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_RECORD_SET")
    parent_hashes = _parent_record_hashes(case)
    for index, (record, phase, parent_record_hash) in enumerate(zip(records, expected_phases, parent_hashes), start=1):
        if not isinstance(record, dict) or set(record) != {"sequence", "phase", "parent_record_hash", "transaction_id", "entry_hash"}:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_RECORD_SCHEMA")
        if (record.get("sequence"), record.get("phase"), record.get("parent_record_hash"), record.get("transaction_id")) != (
            index, phase, parent_record_hash, case.transaction_id,
        ):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PARENT_RECORD_BINDING")
        if not _hex(record.get("entry_hash")) or record["entry_hash"] != _hash(_without(record, "entry_hash")):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_RECORD_HASH")
    if journal.get("terminal_binding_hash") != _terminal_binding_hash(case, cp76_contract):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_TERMINAL_BINDING")
    if journal.get("simulated_only") is not True or journal.get("storage_write_performed") is not False or journal.get("runtime_mutated") is not False:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_MUTATION")
    if not all(_hex(journal.get(key)) for key in ("baseline_snapshot_hash", "intended_recovery_result_hash", "terminal_binding_hash", "payload_hash", "journal_hash")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_DIGEST")
    if journal.get("payload_hash") != _hash(_without(journal, "payload_hash", "journal_hash")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PAYLOAD_HASH")
    if journal.get("journal_hash") != _hash(_without(journal, "journal_hash")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_JOURNAL_HASH")


def validate_recovery_journal_ledger(journals: tuple[dict[str, Any], ...]) -> None:
    seen: dict[str, str] = {}
    for journal in journals:
        tx = journal.get("transaction_id")
        digest = journal.get("journal_hash")
        if isinstance(tx, str) and tx in seen and seen[tx] != digest:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_DUPLICATE_CONFLICTING_TRANSACTION")
        if isinstance(tx, str) and isinstance(digest, str):
            seen[tx] = digest


def _representative_case(cp76_dry_run: Any, corruption_class: str) -> Any:
    if corruption_class == "INVALID_COMMIT_MARKER_BINDING":
        return next(x for x in cp76_dry_run.crash_cases if x.crash_point == "AFTER_COMMIT_MARKER_BEFORE_ACK")
    return cp76_dry_run.crash_cases[CORRUPTION_CLASSES.index(corruption_class) % len(cp76_dry_run.crash_cases)]


def _inject_corruption(valid: dict[str, Any], corruption_class: str) -> dict[str, Any]:
    out = deepcopy(valid)
    if corruption_class == "MALFORMED_SCHEMA_VERSION":
        out["schema_version"] = "PPOS_CP77_SYNTHETIC_RECOVERY_JOURNAL_V0"
        return _reseal_journal(out)
    if corruption_class == "MISSING_REQUIRED_FIELD":
        out.pop("transaction_id")
        return _reseal_journal(out)
    if corruption_class == "DUPLICATE_CONFLICTING_ENTRY":
        out["intended_recovery_result_hash"] = "0" * 64
        return _reseal_journal(out)
    if corruption_class == "ILLEGAL_PHASE_ORDER":
        out["phase_sequence"] = ["COMMIT_MARKED"] + list(out["phase_sequence"])
        return _reseal_journal(out)
    if corruption_class == "BASELINE_HASH_MISMATCH":
        out["baseline_snapshot_hash"] = "0" * 64
        return _reseal_journal(out)
    if corruption_class == "PAYLOAD_HASH_TAMPER":
        out = _reseal_journal(out)
        out["payload_hash"] = "0" * 64
        out["journal_hash"] = _hash(_without(out, "journal_hash"))
        return out
    if corruption_class == "INVALID_COMMIT_MARKER_BINDING":
        out["records"][-1]["parent_record_hash"] = "0" * 64
        out["records"][-1]["entry_hash"] = _hash(_without(out["records"][-1], "entry_hash"))
        return _reseal_journal(out)
    if corruption_class == "TERMINAL_BINDING_MISMATCH":
        out["terminal_binding_hash"] = "0" * 64
        return _reseal_journal(out)
    raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_UNKNOWN_CORRUPTION_CLASS")


def _exercise_corruption(corruption_class: str, cp76_dry_run: Any, cp76_contract: Any) -> JournalCorruptionRejectionCase:
    case = _representative_case(cp76_dry_run, corruption_class)
    valid = build_valid_recovery_journal(case, cp76_contract)
    validate_recovery_journal(valid, case, cp76_contract)
    corrupted = _inject_corruption(valid, corruption_class)
    try:
        if corruption_class == "DUPLICATE_CONFLICTING_ENTRY":
            validate_recovery_journal_ledger((valid, corrupted))
        else:
            validate_recovery_journal(corrupted, case, cp76_contract)
    except LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold as exc:
        observed = str(exc)
    else:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CORRUPTION_ACCEPTED")
    expected = EXPECTED_HOLDS[corruption_class]
    if observed != expected:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_UNEXPECTED_REJECTION_REASON")
    return JournalCorruptionRejectionCase(
        corruption_class=corruption_class,
        parent_transaction_id=case.transaction_id,
        parent_journal_hash=valid["journal_hash"],
        corrupted_journal_hash=corrupted["journal_hash"],
        expected_hold=expected,
        observed_hold=observed,
        rejected=True,
        rejection_before_recovery_effect=True,
        baseline_snapshot_hash=case.baseline_snapshot_hash,
        baseline_preserved=True,
    )


def build_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(
    cp76_contract: Any,
    cp76_dry_run: Any,
) -> AuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_contract(cp76_contract)
    if (cp76_contract.dry_run_id, cp76_contract.dry_run_hash) != (cp76_dry_run.dry_run_id, cp76_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CP76_DRY_RUN_BINDING")
    positive = tuple(build_valid_recovery_journal(case, cp76_contract) for case in cp76_dry_run.crash_cases)
    for journal, case in zip(positive, cp76_dry_run.crash_cases):
        validate_recovery_journal(journal, case, cp76_contract)
    validate_recovery_journal_ledger(positive)
    rejection_cases = tuple(_exercise_corruption(kind, cp76_dry_run, cp76_contract) for kind in CORRUPTION_CLASSES)
    body = {
        "cp76_contract_id": cp76_contract.contract_id,
        "cp76_contract_hash": cp76_contract.contract_hash,
        "cp76_dry_run_id": cp76_dry_run.dry_run_id,
        "cp76_dry_run_hash": cp76_dry_run.dry_run_hash,
        "lease_id": cp76_contract.lease_id,
        "lease_hash": cp76_contract.lease_hash,
        "positive_control_journal_hashes": [x["journal_hash"] for x in positive],
        "rejection_cases": [x.to_dict() for x in rejection_cases],
        "phases": list(VALIDATION_PHASES),
        "outcome": "SIMULATED_RECOVERY_JOURNAL_CORRUPTION_REJECTION_PASS_ALL_EIGHT_FAIL_CLOSED_BASELINE_PRESERVED_NO_STORAGE_WRITE_NO_AUTHORITY",
        "all_corruptions_rejected": True,
        "baseline_preserved": True,
        "global_kill_switch_engaged": True,
        "zero_io_observed": True,
        "simulated_journal_only": True,
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
    body["positive_control_journal_hashes"] = tuple(body["positive_control_journal_hashes"])
    body["rejection_cases"] = rejection_cases
    body["phases"] = VALIDATION_PHASES
    dry = AuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionDryRun(
        dry_run_id=f"cp77_dry_run_{digest[:24]}", dry_run_hash=digest, **body
    )
    validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(dry, cp76_contract, cp76_dry_run)
    return dry


def validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(
    dry: AuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionDryRun,
    cp76_contract: Any,
    cp76_dry_run: Any,
) -> None:
    if (
        dry.cp76_contract_id, dry.cp76_contract_hash, dry.cp76_dry_run_id, dry.cp76_dry_run_hash, dry.lease_id, dry.lease_hash,
    ) != (
        cp76_contract.contract_id, cp76_contract.contract_hash, cp76_dry_run.dry_run_id, cp76_dry_run.dry_run_hash,
        cp76_contract.lease_id, cp76_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PARENT_BINDING")
    if len(dry.positive_control_journal_hashes) != len(cp76_dry_run.crash_cases) or not all(_hex(x) for x in dry.positive_control_journal_hashes):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_POSITIVE_CONTROL_SET")
    if tuple(x.corruption_class for x in dry.rejection_cases) != CORRUPTION_CLASSES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_REJECTION_CASE_SET")
    for case in dry.rejection_cases:
        if not case.rejected or not case.rejection_before_recovery_effect or not case.baseline_preserved or case.recovery_effect_count != 0:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_REJECTION_NOT_FAIL_CLOSED")
        if case.expected_hold != EXPECTED_HOLDS[case.corruption_class] or case.observed_hold != case.expected_hold:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_REJECTION_REASON_DRIFT")
        if not all(_hex(x) for x in (case.parent_journal_hash, case.corrupted_journal_hash, case.baseline_snapshot_hash)):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_REJECTION_DIGEST")
        if not case.simulated_journal_only or case.storage_write_performed or case.runtime_mutated:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_REJECTION_MUTATION")
    if dry.phases != VALIDATION_PHASES or dry.outcome != "SIMULATED_RECOVERY_JOURNAL_CORRUPTION_REJECTION_PASS_ALL_EIGHT_FAIL_CLOSED_BASELINE_PRESERVED_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_OUTCOME_OR_PHASES")
    if not dry.all_corruptions_rejected or not dry.baseline_preserved or not dry.global_kill_switch_engaged or not dry.zero_io_observed or not dry.simulated_journal_only:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_ZERO_IO_OR_GUARD")
    for key in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed", "deploy_allowed",
        "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp77_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_DRY_RUN_HASH")


def _build_cp76_parent(root: Path) -> tuple[Any, Any]:
    cp76_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_policy.json")
    cp76 = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency(root, cp76_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_contract(cp76)
    cp75_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_policy.json")
    cp75 = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(root, cp75_policy)
    cp75_dry = _build_cp75_dry_run(root, cp75)
    cp76_dry = build_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(cp75, cp75_dry)
    validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(cp76_dry, cp75, cp75_dry)
    if (cp76.dry_run_id, cp76.dry_run_hash) != (cp76_dry.dry_run_id, cp76_dry.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_PARENT_REBUILD_DRIFT")
    return cp76, cp76_dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp76, cp76_dry = _build_cp76_parent(root)
    dry = build_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(cp76, cp76_dry)
    body = {
        "cp76_contract_id": cp76.contract_id,
        "cp76_contract_hash": cp76.contract_hash,
        "cp76_dry_run_id": cp76_dry.dry_run_id,
        "cp76_dry_run_hash": cp76_dry.dry_run_hash,
        "lease_id": cp76.lease_id,
        "lease_hash": cp76.lease_hash,
        "dry_run_id": dry.dry_run_id,
        "dry_run_hash": dry.dry_run_hash,
        "policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_policy.json").read_bytes()).hexdigest(),
        "cp76_policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_policy.json").read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        "module_registry_sha256": sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
    }
    defaults = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionContract.__dataclass_fields__
    for key in (
        "next_unit", "checkpoint", "parent_control_checkpoint", "parent_activation_checkpoint", "parent_cp76_state",
        "model_version", "engine_version", "valid_journal_positive_control_validated", "corruption_rejection_validated",
        "all_eight_corruption_classes_validated", "baseline_preservation_validated", "synthetic_validation_only",
        "simulated_journal_only", "global_kill_switch_engaged", "external_authorization_ingested", "authorization_granted",
        "runtime_authorization_effective", "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted", "live_probe_allowed",
        "live_probe_attempted", "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed",
        "storage_write_allowed", "storage_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed",
        "paid_service_used", "authority_activated", "runtime_mutated", "state",
    ):
        body[key] = defaults[key].default
    digest = _hash(body)
    body["active_platforms"] = EXPECTED_ACTIVE
    body["blockers"] = REQUIRED_BLOCKERS
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionContract(
        contract_id=f"cp77_contract_{digest[:24]}", contract_hash=digest, **body
    )
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionContract,
) -> None:
    if (
        contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint,
        contract.parent_cp76_state, contract.state, contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP76_CHECKPOINT, CP76_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only or not contract.simulated_journal_only
        or not contract.valid_journal_positive_control_validated or not contract.corruption_rejection_validated
        or not contract.all_eight_corruption_classes_validated or not contract.baseline_preservation_validated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CONTRACT_SCOPE_OR_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted",
        "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted",
        "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed", "storage_write_allowed",
        "storage_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used",
        "authority_activated", "runtime_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (
        contract.contract_hash, contract.cp76_contract_hash, contract.cp76_dry_run_hash, contract.lease_hash,
        contract.dry_run_hash, contract.policy_sha256, contract.cp76_policy_sha256, contract.runtime_policy_sha256,
        contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp77_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold("HOLD_CP77_CONTRACT_HASH")
