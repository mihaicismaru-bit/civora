from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_expiry_revocation import (
    CHECKPOINT as CP71_CHECKPOINT,
    STATE as CP71_STATE,
    SYNTHETIC_EXPIRES_AT_UTC,
    SYNTHETIC_ISSUED_AT_UTC,
    SYNTHETIC_PRE_EXPIRY_AT_UTC,
    SYNTHETIC_REVOKED_AT_UTC,
    compile_live_read_only_probe_authority_lease_expiry_revocation,
    validate_live_read_only_probe_authority_lease_expiry_revocation_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-replay-stale-receipt-rejection-dry-run-v1.0.0"
STATE = "PASS_CP72_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP72"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP73_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_DRY_RUN"
SYNTHETIC_PRE_REVOCATION_AT_UTC = "2030-01-01T00:04:59Z"
REPLAY_PHASES = (
    "CP71_PARENT_EXACT_BOUND",
    "EXPIRY_TERMINAL_RECEIPT_ACCEPTED_ONCE",
    "EXPIRY_EXACT_REPLAY_REJECTED",
    "EXPIRY_STALE_ACTIVE_RECEIPT_REJECTED",
    "REVOCATION_TERMINAL_RECEIPT_ACCEPTED_ONCE",
    "REVOCATION_EXACT_REPLAY_REJECTED",
    "REVOCATION_STALE_ACTIVE_RECEIPT_REJECTED",
    "TERMINAL_STATE_RESURRECTION_REJECTED",
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
    "HOLD_CP72_RECEIPT_LEDGER_SYNTHETIC_ONLY",
    "HOLD_CP72_REPLAY_STALE_REJECTION_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ReplayPhaseResult:
    name: str
    satisfied: bool
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SyntheticLeaseReceipt:
    receipt_id: str
    receipt_hash: str
    lease_id: str
    lease_hash: str
    scenario: str
    claim_state: str
    observed_at_utc: str
    presented_at_utc: str
    terminal: bool
    active_claim: bool
    synthetic_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityLeaseReplayStaleReceiptDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp71_contract_id: str
    cp71_contract_hash: str
    cp71_dry_run_id: str
    cp71_dry_run_hash: str
    lease_id: str
    lease_hash: str
    expiry_terminal_receipt: SyntheticLeaseReceipt
    expiry_stale_receipt: SyntheticLeaseReceipt
    revocation_terminal_receipt: SyntheticLeaseReceipt
    revocation_stale_receipt: SyntheticLeaseReceipt
    platform_subset: tuple[str, ...]
    phases: tuple[ReplayPhaseResult, ...]
    expiry_terminal_accepted_once: bool
    expiry_exact_replay_rejected: bool
    expiry_stale_active_rejected: bool
    revocation_terminal_accepted_once: bool
    revocation_exact_replay_rejected: bool
    revocation_stale_active_rejected: bool
    terminal_state_resurrection_rejected: bool
    zero_io_observed: bool
    synthetic_fixture: bool
    outcome: str
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP71_CHECKPOINT
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
    state: str = "LEASE_REPLAY_STALE_RECEIPT_REJECTION_SIMULATED_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform_subset"] = list(self.platform_subset)
        d["phases"] = [row.to_dict() for row in self.phases]
        d["expiry_terminal_receipt"] = self.expiry_terminal_receipt.to_dict()
        d["expiry_stale_receipt"] = self.expiry_stale_receipt.to_dict()
        d["revocation_terminal_receipt"] = self.revocation_terminal_receipt.to_dict()
        d["revocation_stale_receipt"] = self.revocation_stale_receipt.to_dict()
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptContract:
    contract_id: str
    contract_hash: str
    cp71_contract_id: str
    cp71_contract_hash: str
    cp71_dry_run_id: str
    cp71_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp71_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP71_CHECKPOINT
    parent_cp71_state: str = CP71_STATE
    replay_rejection_validated: bool = True
    stale_receipt_rejection_validated: bool = True
    terminal_resurrection_rejected: bool = True
    terminal_receipt_single_acceptance_validated: bool = True
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


def _epoch(value: str) -> int:
    try:
        return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError) as exc:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_TIME_FORMAT") from exc


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_POLICY_V1",
        CHECKPOINT,
        "M41_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP71_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE or tuple(policy.get("replay_phases", ())) != REPLAY_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_SCOPE_OR_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP71_CHECKPOINT or policy.get("next_after_cp72") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTINUITY_DRIFT")
    guard = policy.get("receipt_guard", {})
    required_true = (
        "local_only", "zero_io_required", "synthetic_cp71_lease_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp71_contract_binding_required", "exact_cp71_dry_run_binding_required",
        "exact_cp71_lease_binding_required", "deterministic_clock_fixture_required", "exact_replay_rejection_required",
        "stale_receipt_rejection_required", "terminal_state_resurrection_forbidden",
        "terminal_receipt_single_acceptance_required", "runtime_mutation_forbidden", "registry_mutation_forbidden",
        "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged", "runtime_network_must_remain_disabled",
        "account_connection_must_remain_disabled", "publish_must_remain_disabled", "deploy_must_remain_disabled",
        "control_plane_must_remain_unpromoted", "secret_resolution_forbidden", "environment_read_forbidden",
        "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden", "network_forbidden",
        "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(guard.get(key) is not True for key in required_true):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_POLICY_GUARD")
    if guard.get("synthetic_pre_revocation_at_utc") != SYNTHETIC_PRE_REVOCATION_AT_UTC:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CLOCK_FIXTURE_DRIFT")
    if tuple(guard.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_METHOD_POLICY")
    if tuple(guard.get("terminal_states", ())) != ("EXPIRED", "REVOKED"):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_TERMINAL_STATE_POLICY")
    authority = policy.get("authority")
    if not isinstance(authority, dict) or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_DEFERRED_LANE_DRIFT")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RUNTIME_LIVE_BOUNDARY")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTROL_PROMOTION")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M40_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_REVOCATION") != "CP71_AUTHORITY_LEASE_EXPIRY_REVOCATION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CP71_STATE")
    if states.get("M41_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION") != "CP72_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_MODULE_STATE")


def _phase(name: str, satisfied: bool) -> ReplayPhaseResult:
    return ReplayPhaseResult(name=name, satisfied=satisfied, evidence_sha256=_hash({"name": name, "satisfied": satisfied}))


def _receipt(
    *,
    lease_id: str,
    lease_hash: str,
    scenario: str,
    claim_state: str,
    observed_at_utc: str,
    presented_at_utc: str,
    terminal: bool,
    active_claim: bool,
) -> SyntheticLeaseReceipt:
    body = {
        "lease_id": lease_id,
        "lease_hash": lease_hash,
        "scenario": scenario,
        "claim_state": claim_state,
        "observed_at_utc": observed_at_utc,
        "presented_at_utc": presented_at_utc,
        "terminal": terminal,
        "active_claim": active_claim,
        "synthetic_only": True,
    }
    digest = _hash(body)
    return SyntheticLeaseReceipt(receipt_id=f"cp72_receipt_{digest[:24]}", receipt_hash=digest, **body)


def validate_synthetic_lease_receipt(receipt: SyntheticLeaseReceipt, cp71_contract: Any) -> None:
    if (receipt.lease_id, receipt.lease_hash) != (cp71_contract.lease_id, cp71_contract.lease_hash):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RECEIPT_LEASE_BINDING")
    if receipt.scenario not in ("EXPIRY_PATH", "REVOCATION_PATH"):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RECEIPT_SCENARIO")
    if receipt.claim_state not in ("ACTIVE", "EXPIRED", "REVOKED"):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RECEIPT_STATE")
    observed = _epoch(receipt.observed_at_utc)
    presented = _epoch(receipt.presented_at_utc)
    if observed > presented:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RECEIPT_TIME_ORDER")
    if receipt.claim_state == "ACTIVE":
        if receipt.terminal or not receipt.active_claim:
            raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_ACTIVE_RECEIPT_SHAPE")
    else:
        if not receipt.terminal or receipt.active_claim:
            raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_TERMINAL_RECEIPT_SHAPE")
        if (receipt.scenario, receipt.claim_state) not in (("EXPIRY_PATH", "EXPIRED"), ("REVOCATION_PATH", "REVOKED")):
            raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_TERMINAL_SCENARIO_STATE")
    if receipt.synthetic_only is not True or not _hex(receipt.receipt_hash):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RECEIPT_DIGEST")
    digest = _hash(_without(receipt.to_dict(), "receipt_id", "receipt_hash"))
    if receipt.receipt_hash != digest or receipt.receipt_id != f"cp72_receipt_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_RECEIPT_HASH")


def _simulate_terminal_path(
    *,
    terminal_receipt: SyntheticLeaseReceipt,
    stale_receipt: SyntheticLeaseReceipt,
    terminal_at_utc: str,
) -> tuple[bool, bool, bool]:
    seen: set[str] = set()
    accepted_once = terminal_receipt.receipt_hash not in seen
    if accepted_once:
        seen.add(terminal_receipt.receipt_hash)
    exact_replay_rejected = terminal_receipt.receipt_hash in seen
    terminal_at = _epoch(terminal_at_utc)
    stale_active_rejected = (
        stale_receipt.claim_state == "ACTIVE"
        and stale_receipt.active_claim
        and _epoch(stale_receipt.observed_at_utc) < terminal_at
        and _epoch(stale_receipt.presented_at_utc) >= terminal_at
    )
    return accepted_once, exact_replay_rejected, stale_active_rejected


def build_authority_lease_replay_stale_receipt_dry_run(cp71_contract: Any) -> AuthorityLeaseReplayStaleReceiptDryRun:
    validate_live_read_only_probe_authority_lease_expiry_revocation_contract(cp71_contract)
    expiry_terminal = _receipt(
        lease_id=cp71_contract.lease_id,
        lease_hash=cp71_contract.lease_hash,
        scenario="EXPIRY_PATH",
        claim_state="EXPIRED",
        observed_at_utc=SYNTHETIC_EXPIRES_AT_UTC,
        presented_at_utc=SYNTHETIC_EXPIRES_AT_UTC,
        terminal=True,
        active_claim=False,
    )
    expiry_stale = _receipt(
        lease_id=cp71_contract.lease_id,
        lease_hash=cp71_contract.lease_hash,
        scenario="EXPIRY_PATH",
        claim_state="ACTIVE",
        observed_at_utc=SYNTHETIC_PRE_EXPIRY_AT_UTC,
        presented_at_utc=SYNTHETIC_EXPIRES_AT_UTC,
        terminal=False,
        active_claim=True,
    )
    revocation_terminal = _receipt(
        lease_id=cp71_contract.lease_id,
        lease_hash=cp71_contract.lease_hash,
        scenario="REVOCATION_PATH",
        claim_state="REVOKED",
        observed_at_utc=SYNTHETIC_REVOKED_AT_UTC,
        presented_at_utc=SYNTHETIC_REVOKED_AT_UTC,
        terminal=True,
        active_claim=False,
    )
    revocation_stale = _receipt(
        lease_id=cp71_contract.lease_id,
        lease_hash=cp71_contract.lease_hash,
        scenario="REVOCATION_PATH",
        claim_state="ACTIVE",
        observed_at_utc=SYNTHETIC_PRE_REVOCATION_AT_UTC,
        presented_at_utc=SYNTHETIC_REVOKED_AT_UTC,
        terminal=False,
        active_claim=True,
    )
    for receipt in (expiry_terminal, expiry_stale, revocation_terminal, revocation_stale):
        validate_synthetic_lease_receipt(receipt, cp71_contract)
    expiry_once, expiry_replay_rejected, expiry_stale_rejected = _simulate_terminal_path(
        terminal_receipt=expiry_terminal,
        stale_receipt=expiry_stale,
        terminal_at_utc=SYNTHETIC_EXPIRES_AT_UTC,
    )
    revocation_once, revocation_replay_rejected, revocation_stale_rejected = _simulate_terminal_path(
        terminal_receipt=revocation_terminal,
        stale_receipt=revocation_stale,
        terminal_at_utc=SYNTHETIC_REVOKED_AT_UTC,
    )
    terminal_state_resurrection_rejected = expiry_stale_rejected and revocation_stale_rejected
    facts = {
        "CP71_PARENT_EXACT_BOUND": cp71_contract.lease_validated is True and cp71_contract.state == CP71_STATE,
        "EXPIRY_TERMINAL_RECEIPT_ACCEPTED_ONCE": expiry_once,
        "EXPIRY_EXACT_REPLAY_REJECTED": expiry_replay_rejected,
        "EXPIRY_STALE_ACTIVE_RECEIPT_REJECTED": expiry_stale_rejected,
        "REVOCATION_TERMINAL_RECEIPT_ACCEPTED_ONCE": revocation_once,
        "REVOCATION_EXACT_REPLAY_REJECTED": revocation_replay_rejected,
        "REVOCATION_STALE_ACTIVE_RECEIPT_REJECTED": revocation_stale_rejected,
        "TERMINAL_STATE_RESURRECTION_REJECTED": terminal_state_resurrection_rejected,
        "ZERO_IO_OBSERVED": True,
        "AUTHORITY_REMAINS_INACTIVE": cp71_contract.authority_activated is False,
    }
    phases = tuple(_phase(name, facts[name]) for name in REPLAY_PHASES)
    outcome = (
        "SIMULATED_REPLAY_STALE_RECEIPT_REJECTION_PASS_NO_AUTHORITY_NO_RESURRECTION_NO_MUTATION"
        if all(row.satisfied for row in phases)
        else "HOLD_REPLAY_STALE_RECEIPT_REJECTION_UNSATISFIED_NO_AUTHORITY"
    )
    body = {
        "cp71_contract_id": cp71_contract.contract_id,
        "cp71_contract_hash": cp71_contract.contract_hash,
        "cp71_dry_run_id": cp71_contract.dry_run_id,
        "cp71_dry_run_hash": cp71_contract.dry_run_hash,
        "lease_id": cp71_contract.lease_id,
        "lease_hash": cp71_contract.lease_hash,
        "expiry_terminal_receipt": expiry_terminal.to_dict(),
        "expiry_stale_receipt": expiry_stale.to_dict(),
        "revocation_terminal_receipt": revocation_terminal.to_dict(),
        "revocation_stale_receipt": revocation_stale.to_dict(),
        "platform_subset": list(cp71_contract.active_platforms),
        "phases": [row.to_dict() for row in phases],
        "expiry_terminal_accepted_once": expiry_once,
        "expiry_exact_replay_rejected": expiry_replay_rejected,
        "expiry_stale_active_rejected": expiry_stale_rejected,
        "revocation_terminal_accepted_once": revocation_once,
        "revocation_exact_replay_rejected": revocation_replay_rejected,
        "revocation_stale_active_rejected": revocation_stale_rejected,
        "terminal_state_resurrection_rejected": terminal_state_resurrection_rejected,
        "zero_io_observed": True,
        "synthetic_fixture": True,
        "outcome": outcome,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "parent_activation_checkpoint": CP71_CHECKPOINT,
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
        "state": "LEASE_REPLAY_STALE_RECEIPT_REJECTION_SIMULATED_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY",
    }
    digest = _hash(body)
    body["expiry_terminal_receipt"] = expiry_terminal
    body["expiry_stale_receipt"] = expiry_stale
    body["revocation_terminal_receipt"] = revocation_terminal
    body["revocation_stale_receipt"] = revocation_stale
    body["platform_subset"] = tuple(body["platform_subset"])
    body["phases"] = phases
    dry_run = AuthorityLeaseReplayStaleReceiptDryRun(
        dry_run_id=f"cp72_dry_run_{digest[:24]}", dry_run_hash=digest, **body
    )
    validate_authority_lease_replay_stale_receipt_dry_run(dry_run, cp71_contract)
    return dry_run


def validate_authority_lease_replay_stale_receipt_dry_run(
    dry_run: AuthorityLeaseReplayStaleReceiptDryRun, cp71_contract: Any
) -> None:
    if (dry_run.cp71_contract_id, dry_run.cp71_contract_hash) != (cp71_contract.contract_id, cp71_contract.contract_hash):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CP71_CONTRACT_BINDING")
    if (dry_run.cp71_dry_run_id, dry_run.cp71_dry_run_hash) != (cp71_contract.dry_run_id, cp71_contract.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CP71_DRY_RUN_BINDING")
    if (dry_run.lease_id, dry_run.lease_hash) != (cp71_contract.lease_id, cp71_contract.lease_hash):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CP71_LEASE_BINDING")
    for receipt in (
        dry_run.expiry_terminal_receipt,
        dry_run.expiry_stale_receipt,
        dry_run.revocation_terminal_receipt,
        dry_run.revocation_stale_receipt,
    ):
        validate_synthetic_lease_receipt(receipt, cp71_contract)
    if tuple(row.name for row in dry_run.phases) != REPLAY_PHASES or not all(row.satisfied for row in dry_run.phases):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_REPLAY_PHASES")
    if not (
        dry_run.expiry_terminal_accepted_once
        and dry_run.expiry_exact_replay_rejected
        and dry_run.expiry_stale_active_rejected
        and dry_run.revocation_terminal_accepted_once
        and dry_run.revocation_exact_replay_rejected
        and dry_run.revocation_stale_active_rejected
        and dry_run.terminal_state_resurrection_rejected
        and dry_run.zero_io_observed
        and dry_run.synthetic_fixture
        and dry_run.global_kill_switch_engaged
    ):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_REPLAY_GUARD")
    if dry_run.outcome != "SIMULATED_REPLAY_STALE_RECEIPT_REJECTION_PASS_NO_AUTHORITY_NO_RESURRECTION_NO_MUTATION":
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_REPLAY_OUTCOME")
    for key in (
        "runtime_authorization_effective", "authority_activated", "network_allowed", "live_probe_allowed",
        "account_connection_allowed", "publish_allowed", "external_write_allowed", "deploy_allowed",
        "control_plane_promoted", "runtime_mutated", "registry_mutated", "policy_mutated",
    ):
        if getattr(dry_run, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_REPLAY_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (
        dry_run.dry_run_hash,
        dry_run.cp71_contract_hash,
        dry_run.cp71_dry_run_hash,
        dry_run.lease_hash,
        dry_run.expiry_terminal_receipt.receipt_hash,
        dry_run.expiry_stale_receipt.receipt_hash,
        dry_run.revocation_terminal_receipt.receipt_hash,
        dry_run.revocation_stale_receipt.receipt_hash,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_REPLAY_DIGEST")
    digest = _hash(_without(dry_run.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry_run.dry_run_hash != digest or dry_run.dry_run_id != f"cp72_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_REPLAY_HASH")


def compile_live_read_only_probe_authority_lease_replay_stale_receipt(
    root: Path, policy: dict[str, Any]
) -> LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp71_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json")
    cp71_contract = compile_live_read_only_probe_authority_lease_expiry_revocation(root, cp71_policy)
    validate_live_read_only_probe_authority_lease_expiry_revocation_contract(cp71_contract)
    dry_run = build_authority_lease_replay_stale_receipt_dry_run(cp71_contract)
    policy_path = root / "config" / "live_read_only_probe_authority_lease_replay_stale_receipt_policy.json"
    cp71_policy_path = root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json"
    runtime_path = root / "config" / "runtime_policy.json"
    registry_path = root / "config" / "module_registry.json"
    body = {
        "cp71_contract_id": cp71_contract.contract_id,
        "cp71_contract_hash": cp71_contract.contract_hash,
        "cp71_dry_run_id": cp71_contract.dry_run_id,
        "cp71_dry_run_hash": cp71_contract.dry_run_hash,
        "lease_id": cp71_contract.lease_id,
        "lease_hash": cp71_contract.lease_hash,
        "dry_run_id": dry_run.dry_run_id,
        "dry_run_hash": dry_run.dry_run_hash,
        "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        "cp71_policy_sha256": sha256(cp71_policy_path.read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256(runtime_path.read_bytes()).hexdigest(),
        "module_registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "parent_activation_checkpoint": CP71_CHECKPOINT,
        "parent_cp71_state": CP71_STATE,
        "replay_rejection_validated": True,
        "stale_receipt_rejection_validated": True,
        "terminal_resurrection_rejected": True,
        "terminal_receipt_single_acceptance_validated": True,
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
    contract = LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptContract(
        contract_id=f"cp72_contract_{digest[:24]}", contract_hash=digest, **body
    )
    validate_live_read_only_probe_authority_lease_replay_stale_receipt_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_replay_stale_receipt_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptContract,
) -> None:
    if (
        contract.model_version,
        contract.engine_version,
        contract.checkpoint,
        contract.parent_control_checkpoint,
        contract.parent_activation_checkpoint,
        contract.parent_cp71_state,
        contract.state,
        contract.next_unit,
    ) != (
        MODEL_VERSION,
        ENGINE_VERSION,
        CHECKPOINT,
        PARENT_CONTROL_CHECKPOINT,
        CP71_CHECKPOINT,
        CP71_STATE,
        STATE,
        NEXT_UNIT,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTRACT_IDENTITY")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTRACT_SCOPE")
    if not (
        contract.global_kill_switch_engaged
        and contract.replay_rejection_validated
        and contract.stale_receipt_rejection_validated
        and contract.terminal_resurrection_rejected
        and contract.terminal_receipt_single_acceptance_validated
        and contract.synthetic_validation_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTRACT_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
        "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed",
        "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated",
        "registry_mutated", "policy_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (
        contract.contract_hash,
        contract.cp71_contract_hash,
        contract.cp71_dry_run_hash,
        contract.lease_hash,
        contract.dry_run_hash,
        contract.policy_sha256,
        contract.cp71_policy_sha256,
        contract.runtime_policy_sha256,
        contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp72_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold("HOLD_CP72_CONTRACT_HASH")
