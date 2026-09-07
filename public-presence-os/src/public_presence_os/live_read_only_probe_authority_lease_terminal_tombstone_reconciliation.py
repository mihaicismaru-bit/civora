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
    CHECKPOINT as CP72_CHECKPOINT,
    STATE as CP72_STATE,
    build_authority_lease_replay_stale_receipt_dry_run,
    compile_live_read_only_probe_authority_lease_replay_stale_receipt,
    validate_authority_lease_replay_stale_receipt_dry_run,
    validate_live_read_only_probe_authority_lease_replay_stale_receipt_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-reconciliation-dry-run-v1.0.0"
STATE = "PASS_CP73_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_DRY_RUN_LOCAL_ONLY_LEDGER_CONSISTENT_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP73"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP74_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN"
TERMINAL_STATES = ("EXPIRED", "REVOKED")
RECONCILIATION_PHASES = (
    "CP72_PARENT_EXACT_BOUND",
    "EXPIRY_LEDGER_TERMINAL_UNIQUE",
    "EXPIRY_TOMBSTONE_EXACT_MATCH",
    "REVOCATION_LEDGER_TERMINAL_UNIQUE",
    "REVOCATION_TOMBSTONE_EXACT_MATCH",
    "REPLAY_AND_STALE_REJECTIONS_PRESERVED",
    "CONFLICTING_TERMINAL_STATE_REJECTED",
    "POST_TERMINAL_ACTIVE_ACCEPTANCE_REJECTED",
    "TERMINAL_TOMBSTONE_IMMUTABLE_HASH_BOUND",
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
    "HOLD_CP73_TOMBSTONE_LEDGER_SYNTHETIC_ONLY",
    "HOLD_CP73_RECONCILIATION_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold(ValueError):
    pass


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    entry_hash: str
    receipt_id: str
    receipt_hash: str
    claim_state: str
    decision: str
    reason: str
    observed_at_utc: str
    presented_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TerminalTombstone:
    tombstone_id: str
    tombstone_hash: str
    scenario: str
    lease_id: str
    lease_hash: str
    terminal_state: str
    terminal_at_utc: str
    terminal_receipt_id: str
    terminal_receipt_hash: str
    ledger_terminal_entry_hash: str
    cp72_dry_run_hash: str
    immutable: bool = True
    synthetic_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityLeaseTerminalTombstoneReconciliationDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp72_contract_id: str
    cp72_contract_hash: str
    cp72_dry_run_id: str
    cp72_dry_run_hash: str
    lease_id: str
    lease_hash: str
    expiry_ledger: tuple[LedgerEntry, ...]
    revocation_ledger: tuple[LedgerEntry, ...]
    expiry_tombstone: TerminalTombstone
    revocation_tombstone: TerminalTombstone
    phases: tuple[str, ...]
    outcome: str
    global_kill_switch_engaged: bool = True
    zero_io_observed: bool = True
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
        d["expiry_ledger"] = [x.to_dict() for x in self.expiry_ledger]
        d["revocation_ledger"] = [x.to_dict() for x in self.revocation_ledger]
        d["expiry_tombstone"] = self.expiry_tombstone.to_dict()
        d["revocation_tombstone"] = self.revocation_tombstone.to_dict()
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationContract:
    contract_id: str
    contract_hash: str
    cp72_contract_id: str
    cp72_contract_hash: str
    cp72_dry_run_id: str
    cp72_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp72_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP72_CHECKPOINT
    parent_cp72_state: str = CP72_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    terminal_tombstone_reconciliation_validated: bool = True
    receipt_ledger_consistency_validated: bool = True
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
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_POLICY_V1",
        CHECKPOINT,
        "M42_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP72_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE or tuple(policy.get("reconciliation_phases", ())) != RECONCILIATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_SCOPE_OR_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP72_CHECKPOINT or policy.get("next_after_cp73") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CONTINUITY_DRIFT")
    g = policy.get("tombstone_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp72_receipt_ledger_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp72_contract_binding_required", "exact_cp72_dry_run_binding_required",
        "exact_lease_binding_required", "terminal_entry_unique_required", "terminal_tombstone_exact_match_required",
        "replay_rejection_preservation_required", "stale_rejection_preservation_required",
        "conflicting_terminal_state_rejection_required", "post_terminal_active_acceptance_forbidden",
        "terminal_tombstone_immutable_required", "runtime_mutation_forbidden", "registry_mutation_forbidden",
        "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged", "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled", "publish_must_remain_disabled", "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted", "secret_resolution_forbidden", "environment_read_forbidden",
        "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden", "network_forbidden",
        "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(g.get(k) is not True for k in required):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_GUARD_WEAKENED")
    if tuple(g.get("method_allowlist", ())) != ("GET",) or tuple(g.get("terminal_states", ())) != TERMINAL_STATES or tuple(g.get("ledger_decisions", ())) != ("ACCEPTED", "REJECTED"):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_METHOD_OR_LEDGER_DRIFT")
    if policy.get("excluded_platforms") != {"LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS", "X": "EXCLUDED_WHILE_API_IS_PAID", "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES"}:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_RUNTIME_POLICY")
    if any(runtime.get(k) is not False for k in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CONTROL_PROMOTION")
    if states.get("M41_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION") != "CP72_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CP72_STATE")
    if states.get("M42_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION") != "CP73_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_DRY_RUN_LOCAL_ONLY_LEDGER_CONSISTENT_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_MODULE_STATE")


def _entry(receipt: Any, decision: str, reason: str) -> LedgerEntry:
    body = {
        "receipt_id": receipt.receipt_id, "receipt_hash": receipt.receipt_hash, "claim_state": receipt.claim_state,
        "decision": decision, "reason": reason, "observed_at_utc": receipt.observed_at_utc,
        "presented_at_utc": receipt.presented_at_utc,
    }
    digest = _hash(body)
    return LedgerEntry(entry_id=f"cp73_entry_{digest[:24]}", entry_hash=digest, **body)


def _tombstone(scenario: str, terminal: LedgerEntry, cp72: Any) -> TerminalTombstone:
    body = {
        "scenario": scenario, "lease_id": cp72.lease_id, "lease_hash": cp72.lease_hash,
        "terminal_state": terminal.claim_state, "terminal_at_utc": terminal.presented_at_utc,
        "terminal_receipt_id": terminal.receipt_id, "terminal_receipt_hash": terminal.receipt_hash,
        "ledger_terminal_entry_hash": terminal.entry_hash, "cp72_dry_run_hash": cp72.dry_run_hash,
        "immutable": True, "synthetic_only": True,
    }
    digest = _hash(body)
    return TerminalTombstone(tombstone_id=f"cp73_tombstone_{digest[:24]}", tombstone_hash=digest, **body)


def _validate_ledger(ledger: tuple[LedgerEntry, ...], tombstone: TerminalTombstone) -> None:
    if len(ledger) != 3 or sum(x.decision == "ACCEPTED" and x.claim_state in TERMINAL_STATES for x in ledger) != 1:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_TERMINAL_NOT_UNIQUE")
    terminal = next(x for x in ledger if x.decision == "ACCEPTED")
    if (terminal.claim_state, terminal.receipt_id, terminal.receipt_hash, terminal.entry_hash, terminal.presented_at_utc) != (
        tombstone.terminal_state, tombstone.terminal_receipt_id, tombstone.terminal_receipt_hash,
        tombstone.ledger_terminal_entry_hash, tombstone.terminal_at_utc,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_TOMBSTONE_MISMATCH")
    if not any(x.decision == "REJECTED" and x.reason == "EXACT_TERMINAL_RECEIPT_REPLAY" and x.receipt_hash == terminal.receipt_hash for x in ledger):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_REPLAY_NOT_PRESERVED")
    if not any(x.decision == "REJECTED" and x.reason == "STALE_ACTIVE_RECEIPT_AFTER_TERMINAL" and x.claim_state == "ACTIVE" for x in ledger):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_STALE_NOT_PRESERVED")
    if any(x.decision == "ACCEPTED" and x.claim_state == "ACTIVE" and x.presented_at_utc >= tombstone.terminal_at_utc for x in ledger):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_POST_TERMINAL_ACTIVE")
    for x in ledger:
        if x.entry_hash != _hash(_without(x.to_dict(), "entry_id", "entry_hash")) or x.entry_id != f"cp73_entry_{x.entry_hash[:24]}":
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_LEDGER_HASH")
    if not tombstone.immutable or not tombstone.synthetic_only:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_TOMBSTONE_MUTABLE")
    digest = _hash(_without(tombstone.to_dict(), "tombstone_id", "tombstone_hash"))
    if tombstone.tombstone_hash != digest or tombstone.tombstone_id != f"cp73_tombstone_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_TOMBSTONE_HASH")


def build_authority_lease_terminal_tombstone_reconciliation_dry_run(cp72_contract: Any, cp72_dry_run: Any) -> AuthorityLeaseTerminalTombstoneReconciliationDryRun:
    validate_live_read_only_probe_authority_lease_replay_stale_receipt_contract(cp72_contract)
    if (cp72_contract.dry_run_id, cp72_contract.dry_run_hash) != (cp72_dry_run.dry_run_id, cp72_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CP72_DRY_RUN_BINDING")
    expiry = (
        _entry(cp72_dry_run.expiry_terminal_receipt, "ACCEPTED", "TERMINAL_RECEIPT_ACCEPTED_ONCE"),
        _entry(cp72_dry_run.expiry_terminal_receipt, "REJECTED", "EXACT_TERMINAL_RECEIPT_REPLAY"),
        _entry(cp72_dry_run.expiry_stale_receipt, "REJECTED", "STALE_ACTIVE_RECEIPT_AFTER_TERMINAL"),
    )
    revocation = (
        _entry(cp72_dry_run.revocation_terminal_receipt, "ACCEPTED", "TERMINAL_RECEIPT_ACCEPTED_ONCE"),
        _entry(cp72_dry_run.revocation_terminal_receipt, "REJECTED", "EXACT_TERMINAL_RECEIPT_REPLAY"),
        _entry(cp72_dry_run.revocation_stale_receipt, "REJECTED", "STALE_ACTIVE_RECEIPT_AFTER_TERMINAL"),
    )
    et, rt = _tombstone("EXPIRY_PATH", expiry[0], cp72_contract), _tombstone("REVOCATION_PATH", revocation[0], cp72_contract)
    _validate_ledger(expiry, et); _validate_ledger(revocation, rt)
    if et.terminal_state == rt.terminal_state:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_TERMINAL_SCENARIO_COLLISION")
    body = {
        "cp72_contract_id": cp72_contract.contract_id, "cp72_contract_hash": cp72_contract.contract_hash,
        "cp72_dry_run_id": cp72_dry_run.dry_run_id, "cp72_dry_run_hash": cp72_dry_run.dry_run_hash,
        "lease_id": cp72_contract.lease_id, "lease_hash": cp72_contract.lease_hash,
        "expiry_ledger": [x.to_dict() for x in expiry], "revocation_ledger": [x.to_dict() for x in revocation],
        "expiry_tombstone": et.to_dict(), "revocation_tombstone": rt.to_dict(),
        "phases": list(RECONCILIATION_PHASES),
        "outcome": "SIMULATED_TERMINAL_TOMBSTONE_RECONCILIATION_PASS_LEDGER_CONSISTENT_NO_AUTHORITY_NO_MUTATION",
        "global_kill_switch_engaged": True, "zero_io_observed": True,
        "runtime_authorization_effective": False, "authority_activated": False, "network_allowed": False,
        "account_connection_allowed": False, "publish_allowed": False, "external_write_allowed": False,
        "deploy_allowed": False, "control_plane_promoted": False, "runtime_mutated": False,
    }
    digest = _hash(body)
    body["expiry_ledger"], body["revocation_ledger"] = expiry, revocation
    body["expiry_tombstone"], body["revocation_tombstone"] = et, rt
    body["phases"] = RECONCILIATION_PHASES
    dry = AuthorityLeaseTerminalTombstoneReconciliationDryRun(dry_run_id=f"cp73_dry_run_{digest[:24]}", dry_run_hash=digest, **body)
    validate_authority_lease_terminal_tombstone_reconciliation_dry_run(dry, cp72_contract)
    return dry


def validate_authority_lease_terminal_tombstone_reconciliation_dry_run(dry: AuthorityLeaseTerminalTombstoneReconciliationDryRun, cp72_contract: Any) -> None:
    if (dry.cp72_contract_id, dry.cp72_contract_hash, dry.lease_id, dry.lease_hash) != (cp72_contract.contract_id, cp72_contract.contract_hash, cp72_contract.lease_id, cp72_contract.lease_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_PARENT_BINDING")
    _validate_ledger(dry.expiry_ledger, dry.expiry_tombstone); _validate_ledger(dry.revocation_ledger, dry.revocation_tombstone)
    if dry.phases != RECONCILIATION_PHASES or dry.outcome != "SIMULATED_TERMINAL_TOMBSTONE_RECONCILIATION_PASS_LEDGER_CONSISTENT_NO_AUTHORITY_NO_MUTATION":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_OUTCOME_OR_PHASES")
    if not dry.global_kill_switch_engaged or not dry.zero_io_observed:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_ZERO_IO_OR_KILL_SWITCH")
    for k in ("runtime_authorization_effective", "authority_activated", "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed", "deploy_allowed", "control_plane_promoted", "runtime_mutated"):
        if getattr(dry, k) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp73_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_DRY_RUN_HASH")


def compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(root: Path, policy: dict[str, Any]) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationContract:
    root = root.resolve(); _validate_policy(policy); _validate_root(root)
    cp72_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_replay_stale_receipt_policy.json")
    cp72 = compile_live_read_only_probe_authority_lease_replay_stale_receipt(root, cp72_policy)
    validate_live_read_only_probe_authority_lease_replay_stale_receipt_contract(cp72)
    cp71_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json")
    cp71 = compile_live_read_only_probe_authority_lease_expiry_revocation(root, cp71_policy)
    cp72_dry = build_authority_lease_replay_stale_receipt_dry_run(cp71)
    validate_authority_lease_replay_stale_receipt_dry_run(cp72_dry, cp71)
    dry = build_authority_lease_terminal_tombstone_reconciliation_dry_run(cp72, cp72_dry)
    body = {
        "cp72_contract_id": cp72.contract_id, "cp72_contract_hash": cp72.contract_hash,
        "cp72_dry_run_id": cp72_dry.dry_run_id, "cp72_dry_run_hash": cp72_dry.dry_run_hash,
        "lease_id": cp72.lease_id, "lease_hash": cp72.lease_hash, "dry_run_id": dry.dry_run_id, "dry_run_hash": dry.dry_run_hash,
        "policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_policy.json").read_bytes()).hexdigest(),
        "cp72_policy_sha256": sha256((root / "config" / "live_read_only_probe_authority_lease_replay_stale_receipt_policy.json").read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        "module_registry_sha256": sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE), "blockers": list(REQUIRED_BLOCKERS),
    }
    defaults = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationContract.__dataclass_fields__
    for k in ("next_unit", "checkpoint", "parent_control_checkpoint", "parent_activation_checkpoint", "parent_cp72_state", "model_version", "engine_version", "terminal_tombstone_reconciliation_validated", "receipt_ledger_consistency_validated", "synthetic_validation_only", "global_kill_switch_engaged", "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective", "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated", "state"):
        body[k] = defaults[k].default
    digest = _hash(body); body["active_platforms"] = EXPECTED_ACTIVE; body["blockers"] = REQUIRED_BLOCKERS
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationContract(contract_id=f"cp73_contract_{digest[:24]}", contract_hash=digest, **body)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_contract(contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationContract) -> None:
    if (contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint, contract.parent_cp72_state, contract.state, contract.next_unit) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP72_CHECKPOINT, CP72_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CONTRACT_IDENTITY")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CONTRACT_SCOPE_OR_GUARD")
    for k in ("external_authorization_ingested", "authorization_granted", "runtime_authorization_effective", "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated"):
        if getattr(contract, k) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(x) for x in (contract.contract_hash, contract.cp72_contract_hash, contract.cp72_dry_run_hash, contract.lease_hash, contract.dry_run_hash, contract.policy_sha256, contract.cp72_policy_sha256, contract.runtime_policy_sha256, contract.module_registry_sha256)):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp73_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold("HOLD_CP73_CONTRACT_HASH")
