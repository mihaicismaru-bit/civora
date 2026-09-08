from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection import (
    CHECKPOINT as CP77_CHECKPOINT,
    STATE as CP77_STATE,
    _build_cp76_parent,
    build_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run,
    build_valid_recovery_journal,
    validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run,
    validate_recovery_journal,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-journal-partial-write-truncation-rejection-dry-run-v1.0.0"
STATE = "PASS_CP78_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_DRY_RUN_LOCAL_ONLY_FAIL_CLOSED_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP78"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP79_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY_DRY_RUN"
TRUNCATION_CLASSES = (
    "EMPTY_WRITE",
    "ONE_BYTE_PREFIX",
    "MIDPOINT_PREFIX",
    "JOURNAL_HASH_VALUE_PREFIX",
    "FINAL_BYTE_MISSING",
)
EXPECTED_HOLD = "HOLD_CP78_PARTIAL_WRITE_LENGTH"
VALIDATION_PHASES = (
    "CP77_PARENT_EXACT_BOUND",
    "TWELVE_COMPLETE_JOURNALS_ACCEPTED_AS_POSITIVE_CONTROLS",
    "FIVE_TRUNCATION_CLASSES_APPLIED_TO_EACH_PARENT_JOURNAL",
    "SIXTY_PARTIAL_WRITES_REJECTED_BEFORE_PARSE_OR_RECOVERY",
    "EXACT_SERIALIZED_LENGTH_AND_SHA256_REQUIRED",
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
    "HOLD_CP78_RECOVERY_JOURNAL_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP78_PARTIAL_WRITE_TRUNCATION_REJECTION_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold(ValueError):
    pass


@dataclass(frozen=True)
class JournalPartialWriteTruncationRejectionCase:
    truncation_class: str
    parent_transaction_id: str
    parent_serialized_sha256: str
    partial_serialized_sha256: str
    expected_length: int
    observed_length: int
    expected_hold: str
    observed_hold: str
    rejected: bool
    rejection_before_parse: bool
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
class AuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp76_contract_id: str
    cp76_contract_hash: str
    cp77_dry_run_id: str
    cp77_dry_run_hash: str
    lease_id: str
    lease_hash: str
    positive_control_serialized_sha256s: tuple[str, ...]
    rejection_cases: tuple[JournalPartialWriteTruncationRejectionCase, ...]
    phases: tuple[str, ...]
    outcome: str
    all_complete_controls_accepted: bool = True
    all_partial_writes_rejected: bool = True
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
        d["positive_control_serialized_sha256s"] = list(self.positive_control_serialized_sha256s)
        d["rejection_cases"] = [x.to_dict() for x in self.rejection_cases]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionContract:
    contract_id: str
    contract_hash: str
    cp76_contract_id: str
    cp76_contract_hash: str
    cp77_dry_run_id: str
    cp77_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp77_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP77_CHECKPOINT
    parent_cp77_state: str = CP77_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    complete_journal_positive_controls_validated: bool = True
    partial_write_truncation_rejection_validated: bool = True
    all_five_truncation_classes_validated: bool = True
    all_twelve_parent_journals_validated: bool = True
    all_sixty_partial_writes_rejected: bool = True
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
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_POLICY_V1",
        CHECKPOINT,
        "M47_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP77_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_SCOPE_DRIFT")
    if tuple(policy.get("truncation_classes", ())) != TRUNCATION_CLASSES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_TRUNCATION_CLASS_DRIFT")
    if tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP77_CHECKPOINT or policy.get("next_after_cp78") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CONTINUITY_DRIFT")
    guard = policy.get("partial_write_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp77_journal_only", "canonical_json_required",
        "serialized_sha256_required", "exact_serialized_length_required", "exact_cp77_dry_run_binding_required",
        "exact_cp76_contract_binding_required", "exact_lease_binding_required", "complete_positive_control_required",
        "all_five_truncation_classes_required", "all_twelve_parent_journals_required",
        "strict_prefix_only_for_negative_cases", "partial_write_rejection_before_parse_required",
        "partial_write_rejection_before_recovery_effect_required", "baseline_preservation_required",
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
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_GUARD_WEAKENED")
    if tuple(guard.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_METHOD_DRIFT")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CONTROL_PROMOTION")
    if states.get("M46_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION") != CP77_STATE.removeprefix("PASS_"):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CP77_STATE")
    if states.get("M47_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION") != STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_MODULE_STATE")


def serialize_recovery_journal(journal: dict[str, Any]) -> bytes:
    return canonical_json(journal).encode("utf-8")


def validate_complete_serialized_recovery_journal(
    raw: bytes,
    expected_length: int,
    expected_sha256: str,
    case: Any,
    cp76_contract: Any,
) -> dict[str, Any]:
    if len(raw) != expected_length:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold(EXPECTED_HOLD)
    if _raw_hash(raw) != expected_sha256:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_SERIALIZED_SHA256")
    try:
        decoded = raw.decode("utf-8")
        journal = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_SERIALIZED_PARSE") from None
    if not isinstance(journal, dict) or serialize_recovery_journal(journal) != raw:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_NON_CANONICAL_SERIALIZATION")
    validate_recovery_journal(journal, case, cp76_contract)
    return journal


def _cut_offset(raw: bytes, truncation_class: str) -> int:
    if len(raw) < 2:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_PARENT_SERIALIZATION_TOO_SHORT")
    if truncation_class == "EMPTY_WRITE":
        return 0
    if truncation_class == "ONE_BYTE_PREFIX":
        return 1
    if truncation_class == "MIDPOINT_PREFIX":
        return max(1, len(raw) // 2)
    if truncation_class == "JOURNAL_HASH_VALUE_PREFIX":
        marker = b'"journal_hash":"'
        start = raw.find(marker)
        if start < 0:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_JOURNAL_HASH_MARKER")
        return min(len(raw) - 1, start + len(marker) + 16)
    if truncation_class == "FINAL_BYTE_MISSING":
        return len(raw) - 1
    raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_UNKNOWN_TRUNCATION_CLASS")


def _exercise_partial_write(
    journal: dict[str, Any],
    case: Any,
    cp76_contract: Any,
    truncation_class: str,
) -> JournalPartialWriteTruncationRejectionCase:
    raw = serialize_recovery_journal(journal)
    expected_sha = _raw_hash(raw)
    cut = _cut_offset(raw, truncation_class)
    if not 0 <= cut < len(raw):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_NOT_STRICT_PREFIX")
    partial = raw[:cut]
    try:
        validate_complete_serialized_recovery_journal(partial, len(raw), expected_sha, case, cp76_contract)
    except LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold as exc:
        observed = str(exc)
    else:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_PARTIAL_WRITE_ACCEPTED")
    if observed != EXPECTED_HOLD:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_UNEXPECTED_REJECTION_REASON")
    return JournalPartialWriteTruncationRejectionCase(
        truncation_class=truncation_class,
        parent_transaction_id=case.transaction_id,
        parent_serialized_sha256=expected_sha,
        partial_serialized_sha256=_raw_hash(partial),
        expected_length=len(raw),
        observed_length=len(partial),
        expected_hold=EXPECTED_HOLD,
        observed_hold=observed,
        rejected=True,
        rejection_before_parse=True,
        rejection_before_recovery_effect=True,
        baseline_snapshot_hash=case.baseline_snapshot_hash,
        baseline_preserved=True,
    )


def build_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_dry_run(
    cp76_contract: Any,
    cp76_dry_run: Any,
    cp77_dry_run: Any,
) -> AuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionDryRun:
    validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(
        cp77_dry_run, cp76_contract, cp76_dry_run
    )
    journals = tuple(build_valid_recovery_journal(case, cp76_contract) for case in cp76_dry_run.crash_cases)
    positive_hashes: list[str] = []
    rejection_cases: list[JournalPartialWriteTruncationRejectionCase] = []
    for journal, case in zip(journals, cp76_dry_run.crash_cases):
        validate_recovery_journal(journal, case, cp76_contract)
        raw = serialize_recovery_journal(journal)
        raw_hash = _raw_hash(raw)
        validate_complete_serialized_recovery_journal(raw, len(raw), raw_hash, case, cp76_contract)
        positive_hashes.append(raw_hash)
        for truncation_class in TRUNCATION_CLASSES:
            rejection_cases.append(_exercise_partial_write(journal, case, cp76_contract, truncation_class))
    dry = AuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionDryRun(
        dry_run_id="",
        dry_run_hash="",
        cp76_contract_id=cp76_contract.contract_id,
        cp76_contract_hash=cp76_contract.contract_hash,
        cp77_dry_run_id=cp77_dry_run.dry_run_id,
        cp77_dry_run_hash=cp77_dry_run.dry_run_hash,
        lease_id=cp76_contract.lease_id,
        lease_hash=cp76_contract.lease_hash,
        positive_control_serialized_sha256s=tuple(positive_hashes),
        rejection_cases=tuple(rejection_cases),
        phases=VALIDATION_PHASES,
        outcome="SIMULATED_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_PASS_60_OF_60_FAIL_CLOSED_BASELINE_PRESERVED_NO_STORAGE_WRITE_NO_AUTHORITY",
    )
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    dry = replace(dry, dry_run_id=f"cp78_dry_run_{digest[:24]}", dry_run_hash=digest)
    validate_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_dry_run(
        dry, cp76_contract, cp76_dry_run, cp77_dry_run
    )
    return dry


def validate_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_dry_run(
    dry: AuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionDryRun,
    cp76_contract: Any,
    cp76_dry_run: Any,
    cp77_dry_run: Any,
) -> None:
    if (
        dry.cp76_contract_id, dry.cp76_contract_hash, dry.cp77_dry_run_id, dry.cp77_dry_run_hash,
        dry.lease_id, dry.lease_hash,
    ) != (
        cp76_contract.contract_id, cp76_contract.contract_hash, cp77_dry_run.dry_run_id, cp77_dry_run.dry_run_hash,
        cp76_contract.lease_id, cp76_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_PARENT_BINDING")
    if len(dry.positive_control_serialized_sha256s) != len(cp76_dry_run.crash_cases) or not all(
        _hex(x) for x in dry.positive_control_serialized_sha256s
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_POSITIVE_CONTROL_SET")
    expected_classes = TRUNCATION_CLASSES * len(cp76_dry_run.crash_cases)
    if tuple(x.truncation_class for x in dry.rejection_cases) != expected_classes or len(dry.rejection_cases) != 60:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_REJECTION_CASE_SET")
    for case in dry.rejection_cases:
        if (
            not case.rejected or not case.rejection_before_parse or not case.rejection_before_recovery_effect
            or not case.baseline_preserved or case.recovery_effect_count != 0
        ):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_REJECTION_NOT_FAIL_CLOSED")
        if case.expected_hold != EXPECTED_HOLD or case.observed_hold != EXPECTED_HOLD:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_REJECTION_REASON_DRIFT")
        if not all(_hex(x) for x in (case.parent_serialized_sha256, case.partial_serialized_sha256, case.baseline_snapshot_hash)):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_REJECTION_DIGEST")
        if not 0 <= case.observed_length < case.expected_length:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_NOT_STRICT_PREFIX")
        if not case.simulated_journal_only or case.storage_write_performed or case.runtime_mutated:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_REJECTION_MUTATION")
    if dry.phases != VALIDATION_PHASES or dry.outcome != "SIMULATED_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_PASS_60_OF_60_FAIL_CLOSED_BASELINE_PRESERVED_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_OUTCOME_OR_PHASES")
    if (
        not dry.all_complete_controls_accepted or not dry.all_partial_writes_rejected or not dry.baseline_preserved
        or not dry.global_kill_switch_engaged or not dry.zero_io_observed or not dry.simulated_journal_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_ZERO_IO_OR_GUARD")
    for key in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed", "deploy_allowed",
        "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp78_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_DRY_RUN_HASH")


def _build_cp78_evidence(root: Path) -> tuple[Any, Any, Any, Any]:
    cp76, cp76_dry = _build_cp76_parent(root)
    cp77_dry = build_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(cp76, cp76_dry)
    validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(cp77_dry, cp76, cp76_dry)
    cp78_dry = build_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_dry_run(
        cp76, cp76_dry, cp77_dry
    )
    return cp76, cp76_dry, cp77_dry, cp78_dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp76, cp76_dry, cp77_dry, dry = _build_cp78_evidence(root)
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionContract(
        contract_id="",
        contract_hash="",
        cp76_contract_id=cp76.contract_id,
        cp76_contract_hash=cp76.contract_hash,
        cp77_dry_run_id=cp77_dry.dry_run_id,
        cp77_dry_run_hash=cp77_dry.dry_run_hash,
        lease_id=cp76.lease_id,
        lease_hash=cp76.lease_hash,
        dry_run_id=dry.dry_run_id,
        dry_run_hash=dry.dry_run_hash,
        policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_policy.json").read_bytes()).hexdigest(),
        cp77_policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_policy.json").read_bytes()).hexdigest(),
        runtime_policy_sha256=sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        module_registry_sha256=sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        active_platforms=EXPECTED_ACTIVE,
        blockers=REQUIRED_BLOCKERS,
    )
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    contract = replace(contract, contract_id=f"cp78_contract_{digest[:24]}", contract_hash=digest)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionContract,
) -> None:
    if (
        contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint,
        contract.parent_cp77_state, contract.state, contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP77_CHECKPOINT, CP77_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only or not contract.simulated_journal_only
        or not contract.complete_journal_positive_controls_validated
        or not contract.partial_write_truncation_rejection_validated
        or not contract.all_five_truncation_classes_validated or not contract.all_twelve_parent_journals_validated
        or not contract.all_sixty_partial_writes_rejected or not contract.baseline_preservation_validated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CONTRACT_SCOPE_OR_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted",
        "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted",
        "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed", "storage_write_allowed",
        "storage_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used",
        "authority_activated", "runtime_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(getattr(contract, key)) for key in (
        "cp76_contract_hash", "cp77_dry_run_hash", "lease_hash", "dry_run_hash", "policy_sha256",
        "cp77_policy_sha256", "runtime_policy_sha256", "module_registry_sha256",
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp78_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold("HOLD_CP78_CONTRACT_HASH")
