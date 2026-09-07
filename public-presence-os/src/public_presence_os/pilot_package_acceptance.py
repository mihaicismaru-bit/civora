from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import (
    EXPECTED_ACTIVE,
    build_source_manifest,
    canonical_json,
    load_json,
    manifest_hash,
    validate_policy,
    validate_repo,
)

MODEL_VERSION = "PPOS_PILOT_PACKAGE_ACCEPTANCE_V1"
ENGINE_VERSION = "ppos-pilot-package-acceptance-v1.0.0"
STATE = "PASS_CP59_FINAL_OFFLINE_ACCEPTANCE_LIVE_GATES_HOLD"
ACCEPTANCE_CHECKPOINT = "CP59"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP60_OPERATOR_PILOT_HANDOFF_AND_EXPLICIT_AUTHORIZATION_PACKET"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_BLOCKERS = (
    "HOLD_LIVE_EVIDENCE_NOT_CAPTURED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_FINAL_PILOT_AUTHORIZATION_REQUIRED",
    "HOLD_GLOBAL_CONTROL_CHECKPOINT_PROMOTION",
)

FORBIDDEN_IMPORT_ROOTS = (
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "http.client",
    "socket",
    "boto3",
    "stripe",
)

RAW_SECRET_PATTERNS = (
    re.compile(r"authorization\s*:\s*bearer\s+[a-z0-9._~+/=-]{16,}", re.I),
    re.compile(r"(?:client_secret|access_token|refresh_token)\s*=\s*[\"'][^\"']{16,}[\"']", re.I),
)


class PilotPackageAcceptanceError(ValueError):
    pass


class PilotPackageAcceptanceHold(PilotPackageAcceptanceError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ArtifactBinding:
    path: str
    sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ModuleBinding:
    module_id: str
    state: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PilotPackageAcceptanceReceipt:
    acceptance_id: str
    acceptance_hash: str
    model_version: str
    engine_version: str
    acceptance_checkpoint: str
    parent_control_checkpoint: str
    global_control_checkpoint: str
    source_manifest_sha256: str
    policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    priority_sha256: str
    active_platforms: tuple[str, ...]
    module_bindings: tuple[ModuleBinding, ...]
    artifact_bindings: tuple[ArtifactBinding, ...]
    checks: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str
    final_offline_acceptance_passed: bool = True
    global_kill_switch_engaged: bool = True
    live_evidence_captured: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
    oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    network_attempted: bool = False
    publish_attempted: bool = False
    external_write_performed: bool = False
    deploy_performed: bool = False
    paid_service_used: bool = False
    live_connection_authorized: bool = False
    final_pilot_authorization_present: bool = False
    pilot_publish_ready: bool = False
    state: str = STATE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["active_platforms"] = list(self.active_platforms)
        data["module_bindings"] = [item.to_dict() for item in self.module_bindings]
        data["artifact_bindings"] = [item.to_dict() for item in self.artifact_bindings]
        data["checks"] = list(self.checks)
        data["blockers"] = list(self.blockers)
        return data


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_policy(policy: dict) -> None:
    if policy.get("schema_version") != "PPOS_PILOT_PACKAGE_ACCEPTANCE_POLICY_V1":
        raise PilotPackageAcceptanceHold("HOLD_CP59_POLICY_SCHEMA")
    if policy.get("checkpoint") != ACCEPTANCE_CHECKPOINT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_POLICY_CHECKPOINT")
    if policy.get("module_id") != "M28_PILOT_PACKAGE_ACCEPTANCE":
        raise PilotPackageAcceptanceHold("HOLD_CP59_POLICY_MODULE_ID")
    if policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_PARENT_CHECKPOINT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise PilotPackageAcceptanceHold("HOLD_CP59_ACTIVE_PLATFORM_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise PilotPackageAcceptanceHold("HOLD_CP59_BLOCKER_SET_DRIFT")
    if policy.get("next_after_cp59") != NEXT_UNIT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_NEXT_UNIT_DRIFT")

    contract = policy.get("acceptance_contract", {})
    required_true = (
        "offline_only",
        "deterministic_source_manifest_required",
        "exact_module_state_binding_required",
        "exact_active_lane_policy_required",
        "deferred_lane_gates_required",
        "global_kill_switch_must_remain_engaged",
        "repository_layout_validation_required",
        "forbidden_network_client_import_scan_required",
        "secret_material_scan_required",
        "full_pytest_required_by_ci",
        "reproducible_package_required_by_ci",
        "automatic_live_authorization_forbidden",
        "self_authorization_forbidden",
        "final_offline_acceptance_may_not_promote_live_authority",
    )
    if any(contract.get(key) is not True for key in required_true):
        raise PilotPackageAcceptanceHold("HOLD_CP59_ACCEPTANCE_GUARD_MISSING")

    authority = policy.get("authority", {})
    if not authority or any(value is not False for value in authority.values()):
        raise PilotPackageAcceptanceHold("HOLD_CP59_EXTERNAL_AUTHORITY_NOT_ZERO")

    excluded = policy.get("excluded_platforms", {})
    if excluded != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise PilotPackageAcceptanceHold("HOLD_CP59_DEFERRED_LANE_POLICY_DRIFT")


def _validate_runtime(runtime: dict) -> None:
    result = validate_policy(runtime)
    if not result.ok:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RUNTIME_POLICY_INVALID")
    if runtime.get("global_kill_switch_engaged") is not True:
        raise PilotPackageAcceptanceHold("HOLD_CP59_KILL_SWITCH_NOT_ENGAGED")
    if tuple(runtime.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RUNTIME_ACTIVE_PLATFORM_DRIFT")
    if runtime.get("deferred_platforms") != {
        "LINKEDIN": "PRODUCTION_API_ACCESS_REQUIRED",
        "X": "EXCLUDED_WHILE_API_PAID",
        "BLUESKY": "HOLD_ROI",
    }:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RUNTIME_DEFERRED_PLATFORM_DRIFT")


def _validate_registry(registry: dict, policy: dict) -> tuple[ModuleBinding, ...]:
    if registry.get("schema_version") != "PPOS_MODULE_REGISTRY_V1":
        raise PilotPackageAcceptanceHold("HOLD_CP59_REGISTRY_SCHEMA")
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_PARENT_CONTROL_CHECKPOINT_DRIFT")

    rows = registry.get("modules", [])
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)):
        raise PilotPackageAcceptanceHold("HOLD_CP59_REGISTRY_DUPLICATE_MODULE_ID")
    actual = {row.get("id"): row.get("status") for row in rows}
    expected = policy.get("required_module_states", {})
    if actual.keys() < expected.keys():
        raise PilotPackageAcceptanceHold("HOLD_CP59_REQUIRED_MODULE_MISSING")
    for module_id, state in expected.items():
        if actual.get(module_id) != state:
            raise PilotPackageAcceptanceHold(f"HOLD_CP59_MODULE_STATE_DRIFT:{module_id}")
    return tuple(ModuleBinding(module_id, expected[module_id]) for module_id in expected)


def _validate_priority(priority: dict) -> None:
    if priority.get("schema_version") != "PPOS_REIMPLEMENTATION_PRIORITY_V1":
        raise PilotPackageAcceptanceHold("HOLD_CP59_PRIORITY_SCHEMA")
    if priority.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_PRIORITY_PARENT_CHECKPOINT_DRIFT")
    if priority.get("next") != "CP59_PILOT_PACKAGE_COMPLETENESS_MANIFEST_AND_FINAL_OFFLINE_ACCEPTANCE_SUITE":
        raise PilotPackageAcceptanceHold("HOLD_CP59_PRIORITY_TARGET_DRIFT")
    rules = priority.get("rules", {})
    if rules.get("no_live_network_or_accounts_pre_pilot") is not True:
        raise PilotPackageAcceptanceHold("HOLD_CP59_PRIORITY_LIVE_GUARD_MISSING")


def _artifact_bindings(root: Path, policy: dict) -> tuple[ArtifactBinding, ...]:
    bindings: list[ArtifactBinding] = []
    for rel in policy.get("required_artifacts", []):
        path = root / rel
        if not path.is_file():
            raise PilotPackageAcceptanceHold(f"HOLD_CP59_REQUIRED_ARTIFACT_MISSING:{rel}")
        bindings.append(ArtifactBinding(rel, sha256(path.read_bytes()).hexdigest()))
    if len({item.path for item in bindings}) != len(bindings):
        raise PilotPackageAcceptanceHold("HOLD_CP59_DUPLICATE_REQUIRED_ARTIFACT")
    return tuple(bindings)


def _scan_source_for_network_clients(root: Path) -> None:
    for path in (root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for package in FORBIDDEN_IMPORT_ROOTS:
            pattern = rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
            if re.search(pattern, text, re.I | re.M):
                raise PilotPackageAcceptanceHold(f"HOLD_CP59_NETWORK_CLIENT_IMPORT:{path.relative_to(root)}")


def _scan_for_raw_secret_material(root: Path) -> None:
    suffixes = {".py", ".json", ".toml", ".yml", ".yaml", ".md", ".txt"}
    for base_name in ("src", "config", "docs", ".github"):
        base = root / base_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in RAW_SECRET_PATTERNS:
                if pattern.search(text):
                    raise PilotPackageAcceptanceHold(f"HOLD_CP59_RAW_SECRET_MATERIAL:{path.relative_to(root)}")


def _receipt_body(
    *,
    source_manifest_sha256: str,
    policy_sha256: str,
    runtime_policy_sha256: str,
    module_registry_sha256: str,
    priority_sha256: str,
    module_bindings: tuple[ModuleBinding, ...],
    artifact_bindings: tuple[ArtifactBinding, ...],
    checks: tuple[str, ...],
    global_control_checkpoint: str,
) -> dict:
    return {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "acceptance_checkpoint": ACCEPTANCE_CHECKPOINT,
        "parent_control_checkpoint": PARENT_CONTROL_CHECKPOINT,
        "global_control_checkpoint": global_control_checkpoint,
        "source_manifest_sha256": source_manifest_sha256,
        "policy_sha256": policy_sha256,
        "runtime_policy_sha256": runtime_policy_sha256,
        "module_registry_sha256": module_registry_sha256,
        "priority_sha256": priority_sha256,
        "active_platforms": list(EXPECTED_ACTIVE),
        "module_bindings": [item.to_dict() for item in module_bindings],
        "artifact_bindings": [item.to_dict() for item in artifact_bindings],
        "checks": list(checks),
        "blockers": list(REQUIRED_BLOCKERS),
        "next_unit": NEXT_UNIT,
        "final_offline_acceptance_passed": True,
        "global_kill_switch_engaged": True,
        "live_evidence_captured": False,
        "secret_reference_resolved": False,
        "environment_read": False,
        "keychain_read": False,
        "oauth_attempted": False,
        "real_account_lookup_attempted": False,
        "account_connected": False,
        "network_attempted": False,
        "publish_attempted": False,
        "external_write_performed": False,
        "deploy_performed": False,
        "paid_service_used": False,
        "live_connection_authorized": False,
        "final_pilot_authorization_present": False,
        "pilot_publish_ready": False,
        "state": STATE,
    }


def compile_pilot_package_acceptance(root: Path, policy: dict) -> PilotPackageAcceptanceReceipt:
    root = root.resolve()
    _validate_policy(policy)

    repo_result = validate_repo(root)
    if not repo_result.ok:
        raise PilotPackageAcceptanceHold("HOLD_CP59_REPOSITORY_LAYOUT_INVALID")

    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    priority = load_json(root / "config" / "reimplementation_priority.json")
    _validate_runtime(runtime)
    module_bindings = _validate_registry(registry, policy)
    _validate_priority(priority)
    artifact_bindings = _artifact_bindings(root, policy)
    _scan_source_for_network_clients(root)
    _scan_for_raw_secret_material(root)

    first_manifest = build_source_manifest(root)
    second_manifest = build_source_manifest(root)
    if first_manifest != second_manifest:
        raise PilotPackageAcceptanceHold("HOLD_CP59_SOURCE_MANIFEST_NONDETERMINISTIC")
    source_manifest_sha256 = manifest_hash(first_manifest)
    if not HEX64.fullmatch(source_manifest_sha256):
        raise PilotPackageAcceptanceHold("HOLD_CP59_SOURCE_MANIFEST_HASH_INVALID")

    checks = (
        "cp59_policy_valid",
        "repository_layout_valid",
        "runtime_fail_closed_valid",
        "active_lanes_exact",
        "deferred_lane_gates_exact",
        "module_registry_states_exact",
        "pipeline_modules_present",
        "required_artifacts_present_and_sha256_bound",
        "source_manifest_deterministic",
        "source_manifest_sha256_bound",
        "network_client_import_scan_pass",
        "raw_secret_material_scan_pass",
        "global_kill_switch_engaged",
        "live_authority_zero",
        "paid_services_zero",
        "parent_control_checkpoint_preserved",
        "final_offline_acceptance_pass",
    )

    policy_sha256 = _hash(policy)
    runtime_policy_sha256 = _hash(runtime)
    module_registry_sha256 = _hash(registry)
    priority_sha256 = _hash(priority)
    body = _receipt_body(
        source_manifest_sha256=source_manifest_sha256,
        policy_sha256=policy_sha256,
        runtime_policy_sha256=runtime_policy_sha256,
        module_registry_sha256=module_registry_sha256,
        priority_sha256=priority_sha256,
        module_bindings=module_bindings,
        artifact_bindings=artifact_bindings,
        checks=checks,
        global_control_checkpoint=registry["checkpoint"],
    )
    acceptance_hash = _hash(body)
    receipt = PilotPackageAcceptanceReceipt(
        acceptance_id="ppa_" + acceptance_hash[:24],
        acceptance_hash=acceptance_hash,
        model_version=MODEL_VERSION,
        engine_version=ENGINE_VERSION,
        acceptance_checkpoint=ACCEPTANCE_CHECKPOINT,
        parent_control_checkpoint=PARENT_CONTROL_CHECKPOINT,
        global_control_checkpoint=registry["checkpoint"],
        source_manifest_sha256=source_manifest_sha256,
        policy_sha256=policy_sha256,
        runtime_policy_sha256=runtime_policy_sha256,
        module_registry_sha256=module_registry_sha256,
        priority_sha256=priority_sha256,
        active_platforms=EXPECTED_ACTIVE,
        module_bindings=module_bindings,
        artifact_bindings=artifact_bindings,
        checks=checks,
        blockers=REQUIRED_BLOCKERS,
        next_unit=NEXT_UNIT,
    )
    validate_pilot_package_acceptance_receipt(receipt)
    return receipt


def validate_pilot_package_acceptance_receipt(receipt: PilotPackageAcceptanceReceipt) -> None:
    if receipt.model_version != MODEL_VERSION or receipt.engine_version != ENGINE_VERSION:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_VERSION_DRIFT")
    if receipt.acceptance_checkpoint != ACCEPTANCE_CHECKPOINT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_CHECKPOINT_DRIFT")
    if receipt.parent_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_PARENT_DRIFT")
    if receipt.global_control_checkpoint != PARENT_CONTROL_CHECKPOINT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_GLOBAL_CONTROL_PROMOTION_FORBIDDEN")
    if tuple(receipt.active_platforms) != EXPECTED_ACTIVE:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_ACTIVE_PLATFORM_DRIFT")
    if receipt.blockers != REQUIRED_BLOCKERS:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_BLOCKER_DRIFT")
    if receipt.next_unit != NEXT_UNIT:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_NEXT_UNIT_DRIFT")
    if not receipt.final_offline_acceptance_passed or not receipt.global_kill_switch_engaged:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_ACCEPTANCE_OR_KILL_SWITCH_DRIFT")

    forbidden = (
        receipt.live_evidence_captured,
        receipt.secret_reference_resolved,
        receipt.environment_read,
        receipt.keychain_read,
        receipt.oauth_attempted,
        receipt.real_account_lookup_attempted,
        receipt.account_connected,
        receipt.network_attempted,
        receipt.publish_attempted,
        receipt.external_write_performed,
        receipt.deploy_performed,
        receipt.paid_service_used,
        receipt.live_connection_authorized,
        receipt.final_pilot_authorization_present,
        receipt.pilot_publish_ready,
    )
    if any(forbidden):
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_EXTERNAL_OR_LIVE_AUTHORITY_FORBIDDEN")

    hashes = (
        receipt.acceptance_hash,
        receipt.source_manifest_sha256,
        receipt.policy_sha256,
        receipt.runtime_policy_sha256,
        receipt.module_registry_sha256,
        receipt.priority_sha256,
        *(item.sha256 for item in receipt.artifact_bindings),
    )
    if any(not HEX64.fullmatch(value) for value in hashes):
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_HASH_FORMAT")

    body = receipt.to_dict()
    body.pop("acceptance_id")
    body.pop("acceptance_hash")
    if _hash(body) != receipt.acceptance_hash:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_HASH_MISMATCH")
    if receipt.acceptance_id != "ppa_" + receipt.acceptance_hash[:24]:
        raise PilotPackageAcceptanceHold("HOLD_CP59_RECEIPT_ID_MISMATCH")


def render_pilot_package_acceptance_json(receipt: PilotPackageAcceptanceReceipt) -> str:
    validate_pilot_package_acceptance_receipt(receipt)
    return canonical_json(receipt.to_dict())
