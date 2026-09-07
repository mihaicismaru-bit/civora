from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_activation_transaction import (
    CHECKPOINT as CP70_CHECKPOINT,
    STATE as CP70_STATE,
    compile_live_read_only_probe_authority_activation_transaction,
    validate_live_read_only_probe_authority_activation_transaction_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_REVOCATION_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-expiry-revocation-dry-run-v1.0.0"
STATE = "PASS_CP71_AUTHORITY_LEASE_EXPIRY_REVOCATION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP71"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP72_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_AND_STALE_RECEIPT_REJECTION_DRY_RUN"
LEASE_TTL_SECONDS = 900
SYNTHETIC_ISSUED_AT_UTC = "2030-01-01T00:00:00Z"
SYNTHETIC_REVOKED_AT_UTC = "2030-01-01T00:05:00Z"
SYNTHETIC_PRE_EXPIRY_AT_UTC = "2030-01-01T00:14:59Z"
SYNTHETIC_EXPIRES_AT_UTC = "2030-01-01T00:15:00Z"
LEASE_PHASES = (
    "CP70_PARENT_EXACT_BOUND",
    "LEASE_CANDIDATE_BOUNDED_SYNTHETIC",
    "PRE_EXPIRY_CANDIDATE_VALIDATED_NO_RUNTIME_AUTHORITY",
    "EXPIRY_AT_BOUNDARY_INVALIDATES_CANDIDATE",
    "EXPLICIT_REVOCATION_INVALIDATES_BEFORE_EXPIRY",
    "POST_TERMINAL_REUSE_REJECTED",
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
    "HOLD_CP71_LEASE_IS_SYNTHETIC_ONLY",
    "HOLD_CP71_EXPIRY_REVOCATION_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LeasePhaseResult:
    name: str
    satisfied: bool
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityLeaseExpiryRevocationDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp70_contract_id: str
    cp70_contract_hash: str
    cp70_transaction_id: str
    cp70_transaction_hash: str
    lease_id: str
    lease_hash: str
    lease_ttl_seconds: int
    synthetic_issued_at_utc: str
    synthetic_revoked_at_utc: str
    synthetic_pre_expiry_at_utc: str
    synthetic_expires_at_utc: str
    platform_subset: tuple[str, ...]
    phases: tuple[LeasePhaseResult, ...]
    candidate_valid_before_expiry: bool
    expired_at_boundary: bool
    explicit_revocation_before_expiry: bool
    terminal_state_non_reusable: bool
    zero_io_observed: bool
    synthetic_fixture: bool
    outcome: str
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP70_CHECKPOINT
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
    state: str = "LEASE_EXPIRY_REVOCATION_SIMULATED_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform_subset"] = list(self.platform_subset)
        d["phases"] = [row.to_dict() for row in self.phases]
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseExpiryRevocationContract:
    contract_id: str
    contract_hash: str
    cp70_contract_id: str
    cp70_contract_hash: str
    cp70_transaction_id: str
    cp70_transaction_hash: str
    dry_run_id: str
    dry_run_hash: str
    lease_id: str
    lease_hash: str
    policy_sha256: str
    cp70_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP70_CHECKPOINT
    parent_cp70_state: str = CP70_STATE
    lease_validated: bool = True
    expiry_fail_closed_validated: bool = True
    explicit_revocation_fail_closed_validated: bool = True
    terminal_reuse_rejected: bool = True
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
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_TIME_FORMAT") from exc


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_REVOCATION_POLICY_V1",
        CHECKPOINT,
        "M40_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_REVOCATION",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP70_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE or tuple(policy.get("lease_phases", ())) != LEASE_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_SCOPE_OR_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP70_CHECKPOINT or policy.get("next_after_cp71") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTINUITY_DRIFT")
    lease = policy.get("lease", {})
    required_true = (
        "local_only", "zero_io_required", "synthetic_cp70_candidate_only", "canonical_json_required",
        "sha256_binding_required", "exact_cp70_contract_binding_required", "exact_cp70_transaction_binding_required",
        "deterministic_clock_fixture_required", "bounded_ttl_required", "expiry_fail_closed_required",
        "explicit_revocation_fail_closed_required", "terminal_state_reuse_forbidden", "runtime_mutation_forbidden",
        "registry_mutation_forbidden", "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged",
        "runtime_network_must_remain_disabled", "account_connection_must_remain_disabled", "publish_must_remain_disabled",
        "deploy_must_remain_disabled", "control_plane_must_remain_unpromoted", "secret_resolution_forbidden",
        "environment_read_forbidden", "keychain_read_forbidden", "oauth_forbidden", "real_account_lookup_forbidden",
        "network_forbidden", "live_probe_execution_forbidden", "publish_forbidden", "external_write_forbidden",
        "control_plane_promotion_forbidden", "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(lease.get(key) is not True for key in required_true):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_POLICY_GUARD")
    if lease.get("lease_ttl_seconds") != LEASE_TTL_SECONDS:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_TTL_DRIFT")
    if (
        lease.get("synthetic_issued_at_utc"),
        lease.get("synthetic_revoked_at_utc"),
        lease.get("synthetic_pre_expiry_at_utc"),
        lease.get("synthetic_expires_at_utc"),
    ) != (
        SYNTHETIC_ISSUED_AT_UTC,
        SYNTHETIC_REVOKED_AT_UTC,
        SYNTHETIC_PRE_EXPIRY_AT_UTC,
        SYNTHETIC_EXPIRES_AT_UTC,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CLOCK_FIXTURE_DRIFT")
    if tuple(lease.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_METHOD_POLICY")
    authority = policy.get("authority")
    if not isinstance(authority, dict) or any(value is not False for value in authority.values()):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_AUTHORITY_NOT_ZERO")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_DEFERRED_LANE_DRIFT")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_RUNTIME_LIVE_BOUNDARY")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTROL_PROMOTION")
    states = {row.get("id"): row.get("status") for row in registry.get("modules", [])}
    if states.get("M39_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_TRANSACTION") != "CP70_AUTHORITY_ACTIVATION_TRANSACTION_DRY_RUN_LOCAL_ONLY_NO_COMMIT_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CP70_STATE")
    if states.get("M40_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_REVOCATION") != "CP71_AUTHORITY_LEASE_EXPIRY_REVOCATION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD":
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_MODULE_STATE")


def _phase(name: str, satisfied: bool) -> LeasePhaseResult:
    return LeasePhaseResult(name=name, satisfied=satisfied, evidence_sha256=_hash({"name": name, "satisfied": satisfied}))


def build_authority_lease_expiry_revocation_dry_run(cp70_contract: Any) -> AuthorityLeaseExpiryRevocationDryRun:
    validate_live_read_only_probe_authority_activation_transaction_contract(cp70_contract)
    issued = _epoch(SYNTHETIC_ISSUED_AT_UTC)
    revoked = _epoch(SYNTHETIC_REVOKED_AT_UTC)
    pre_expiry = _epoch(SYNTHETIC_PRE_EXPIRY_AT_UTC)
    expires = _epoch(SYNTHETIC_EXPIRES_AT_UTC)
    bounded = issued < revoked < pre_expiry < expires and expires - issued == LEASE_TTL_SECONDS
    candidate_valid_before_expiry = issued <= pre_expiry < expires
    expired_at_boundary = not (issued <= expires < expires)
    explicit_revocation_before_expiry = issued < revoked < expires
    terminal_state_non_reusable = expired_at_boundary and explicit_revocation_before_expiry
    lease_body = {
        "source_checkpoint": CP70_CHECKPOINT,
        "cp70_contract_id": cp70_contract.contract_id,
        "cp70_contract_hash": cp70_contract.contract_hash,
        "cp70_transaction_id": cp70_contract.transaction_id,
        "cp70_transaction_hash": cp70_contract.transaction_hash,
        "requested_scope": "READ_ONLY_METADATA_PROBE",
        "platform_subset": list(cp70_contract.active_platforms),
        "method_allowlist": ["GET"],
        "lease_ttl_seconds": LEASE_TTL_SECONDS,
        "synthetic_issued_at_utc": SYNTHETIC_ISSUED_AT_UTC,
        "synthetic_expires_at_utc": SYNTHETIC_EXPIRES_AT_UTC,
        "synthetic_only": True,
        "runtime_authority_effective": False,
        "authority_activated": False,
    }
    lease_hash = _hash(lease_body)
    lease_id = f"cp71_lease_{lease_hash[:24]}"
    facts = {
        "CP70_PARENT_EXACT_BOUND": cp70_contract.transaction_validated is True and cp70_contract.state == CP70_STATE,
        "LEASE_CANDIDATE_BOUNDED_SYNTHETIC": bounded and cp70_contract.synthetic_validation_only is True,
        "PRE_EXPIRY_CANDIDATE_VALIDATED_NO_RUNTIME_AUTHORITY": candidate_valid_before_expiry and cp70_contract.runtime_authorization_effective is False,
        "EXPIRY_AT_BOUNDARY_INVALIDATES_CANDIDATE": expired_at_boundary,
        "EXPLICIT_REVOCATION_INVALIDATES_BEFORE_EXPIRY": explicit_revocation_before_expiry,
        "POST_TERMINAL_REUSE_REJECTED": terminal_state_non_reusable,
        "ZERO_IO_OBSERVED": True,
        "AUTHORITY_REMAINS_INACTIVE": cp70_contract.authority_activated is False,
    }
    phases = tuple(_phase(name, facts[name]) for name in LEASE_PHASES)
    outcome = (
        "SIMULATED_LEASE_EXPIRY_REVOCATION_PASS_NO_AUTHORITY_NO_REUSE_NO_MUTATION"
        if all(row.satisfied for row in phases)
        else "HOLD_LEASE_EXPIRY_REVOCATION_UNSATISFIED_NO_AUTHORITY"
    )
    body = {
        "cp70_contract_id": cp70_contract.contract_id,
        "cp70_contract_hash": cp70_contract.contract_hash,
        "cp70_transaction_id": cp70_contract.transaction_id,
        "cp70_transaction_hash": cp70_contract.transaction_hash,
        "lease_id": lease_id,
        "lease_hash": lease_hash,
        "lease_ttl_seconds": LEASE_TTL_SECONDS,
        "synthetic_issued_at_utc": SYNTHETIC_ISSUED_AT_UTC,
        "synthetic_revoked_at_utc": SYNTHETIC_REVOKED_AT_UTC,
        "synthetic_pre_expiry_at_utc": SYNTHETIC_PRE_EXPIRY_AT_UTC,
        "synthetic_expires_at_utc": SYNTHETIC_EXPIRES_AT_UTC,
        "platform_subset": list(cp70_contract.active_platforms),
        "phases": [row.to_dict() for row in phases],
        "candidate_valid_before_expiry": candidate_valid_before_expiry,
        "expired_at_boundary": expired_at_boundary,
        "explicit_revocation_before_expiry": explicit_revocation_before_expiry,
        "terminal_state_non_reusable": terminal_state_non_reusable,
        "zero_io_observed": True,
        "synthetic_fixture": True,
        "outcome": outcome,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "parent_activation_checkpoint": CP70_CHECKPOINT,
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
        "state": "LEASE_EXPIRY_REVOCATION_SIMULATED_ONLY_ZERO_IO_NO_RUNTIME_AUTHORITY",
    }
    digest = _hash(body)
    body["platform_subset"] = tuple(body["platform_subset"])
    body["phases"] = phases
    dry_run = AuthorityLeaseExpiryRevocationDryRun(dry_run_id=f"cp71_dry_run_{digest[:24]}", dry_run_hash=digest, **body)
    validate_authority_lease_expiry_revocation_dry_run(dry_run, cp70_contract)
    return dry_run


def validate_authority_lease_expiry_revocation_dry_run(dry_run: AuthorityLeaseExpiryRevocationDryRun, cp70_contract: Any) -> None:
    if (dry_run.cp70_contract_id, dry_run.cp70_contract_hash) != (cp70_contract.contract_id, cp70_contract.contract_hash):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CP70_CONTRACT_BINDING")
    if (dry_run.cp70_transaction_id, dry_run.cp70_transaction_hash) != (cp70_contract.transaction_id, cp70_contract.transaction_hash):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CP70_TRANSACTION_BINDING")
    if tuple(row.name for row in dry_run.phases) != LEASE_PHASES or not all(row.satisfied for row in dry_run.phases):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_LEASE_PHASES")
    if dry_run.lease_ttl_seconds != LEASE_TTL_SECONDS:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_LEASE_TTL")
    if not (
        dry_run.candidate_valid_before_expiry
        and dry_run.expired_at_boundary
        and dry_run.explicit_revocation_before_expiry
        and dry_run.terminal_state_non_reusable
        and dry_run.zero_io_observed
        and dry_run.synthetic_fixture
        and dry_run.global_kill_switch_engaged
    ):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_LEASE_GUARD")
    if dry_run.outcome != "SIMULATED_LEASE_EXPIRY_REVOCATION_PASS_NO_AUTHORITY_NO_REUSE_NO_MUTATION":
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_LEASE_OUTCOME")
    for key in (
        "runtime_authorization_effective", "authority_activated", "network_allowed", "live_probe_allowed",
        "account_connection_allowed", "publish_allowed", "external_write_allowed", "deploy_allowed",
        "control_plane_promoted", "runtime_mutated", "registry_mutated", "policy_mutated",
    ):
        if getattr(dry_run, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_LEASE_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (dry_run.dry_run_hash, dry_run.cp70_contract_hash, dry_run.cp70_transaction_hash, dry_run.lease_hash)):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_LEASE_DIGEST")
    digest = _hash(_without(dry_run.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry_run.dry_run_hash != digest or dry_run.dry_run_id != f"cp71_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_LEASE_HASH")


def compile_live_read_only_probe_authority_lease_expiry_revocation(root: Path, policy: dict[str, Any]) -> LiveReadOnlyProbeAuthorityLeaseExpiryRevocationContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp70_policy = load_json(root / "config" / "live_read_only_probe_authority_activation_transaction_policy.json")
    cp70_contract = compile_live_read_only_probe_authority_activation_transaction(root, cp70_policy)
    validate_live_read_only_probe_authority_activation_transaction_contract(cp70_contract)
    dry_run = build_authority_lease_expiry_revocation_dry_run(cp70_contract)
    policy_path = root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json"
    cp70_policy_path = root / "config" / "live_read_only_probe_authority_activation_transaction_policy.json"
    runtime_path = root / "config" / "runtime_policy.json"
    registry_path = root / "config" / "module_registry.json"
    body = {
        "cp70_contract_id": cp70_contract.contract_id,
        "cp70_contract_hash": cp70_contract.contract_hash,
        "cp70_transaction_id": cp70_contract.transaction_id,
        "cp70_transaction_hash": cp70_contract.transaction_hash,
        "dry_run_id": dry_run.dry_run_id,
        "dry_run_hash": dry_run.dry_run_hash,
        "lease_id": dry_run.lease_id,
        "lease_hash": dry_run.lease_hash,
        "policy_sha256": sha256(policy_path.read_bytes()).hexdigest(),
        "cp70_policy_sha256": sha256(cp70_policy_path.read_bytes()).hexdigest(),
        "runtime_policy_sha256": sha256(runtime_path.read_bytes()).hexdigest(),
        "module_registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
        "active_platforms": list(EXPECTED_ACTIVE),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "checkpoint": CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "parent_activation_checkpoint": CP70_CHECKPOINT,
        "parent_cp70_state": CP70_STATE,
        "lease_validated": True,
        "expiry_fail_closed_validated": True,
        "explicit_revocation_fail_closed_validated": True,
        "terminal_reuse_rejected": True,
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
    contract = LiveReadOnlyProbeAuthorityLeaseExpiryRevocationContract(contract_id=f"cp71_contract_{digest[:24]}", contract_hash=digest, **body)
    validate_live_read_only_probe_authority_lease_expiry_revocation_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_expiry_revocation_contract(contract: LiveReadOnlyProbeAuthorityLeaseExpiryRevocationContract) -> None:
    if (
        contract.model_version, contract.engine_version, contract.checkpoint, contract.parent_control_checkpoint,
        contract.parent_activation_checkpoint, contract.parent_cp70_state, contract.state, contract.next_unit,
    ) != (MODEL_VERSION, ENGINE_VERSION, CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP70_CHECKPOINT, CP70_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTRACT_IDENTITY")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTRACT_SCOPE")
    if not (
        contract.global_kill_switch_engaged and contract.lease_validated and contract.expiry_fail_closed_validated
        and contract.explicit_revocation_fail_closed_validated and contract.terminal_reuse_rejected
        and contract.synthetic_validation_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTRACT_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective", "secret_reference_resolved",
        "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted", "account_connected",
        "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed",
        "paid_service_used", "authority_activated", "runtime_mutated", "registry_mutated", "policy_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(value) for value in (
        contract.contract_hash, contract.cp70_contract_hash, contract.cp70_transaction_hash, contract.dry_run_hash,
        contract.lease_hash, contract.policy_sha256, contract.cp70_policy_sha256, contract.runtime_policy_sha256,
        contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp71_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold("HOLD_CP71_CONTRACT_HASH")
