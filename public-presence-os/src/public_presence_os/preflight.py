from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sys

from .control import EXPECTED_ACTIVE, load_json, validate_policy


@dataclass(frozen=True)
class PreflightResult:
    state: str
    checks: tuple[str, ...]
    holds: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.state == "PASS_PRE_PILOT_LOCAL"


def _version_tuple(value: str) -> tuple[int, int]:
    major, minor, *_ = value.split(".")
    return int(major), int(minor)


def validate_operator_profile(profile: dict) -> PreflightResult:
    checks: list[str] = []
    holds: list[str] = []

    if profile.get("schema_version") == "PPOS_OPERATOR_PROFILE_V1":
        checks.append("operator_profile_schema")
    else:
        holds.append("HOLD_OPERATOR_PROFILE_SCHEMA")

    if profile.get("mode") == "PRE_PILOT_LOCAL":
        checks.append("pre_pilot_local_mode")
    else:
        holds.append("HOLD_OPERATOR_MODE")

    if profile.get("evidence_mode") == "SYNTHETIC_ONLY":
        checks.append("synthetic_only")
    else:
        holds.append("HOLD_EVIDENCE_MODE")

    network = profile.get("network", {})
    if network.get("allow_live_api_calls") is False and network.get("allow_oauth") is False:
        checks.append("network_and_oauth_disabled")
    else:
        holds.append("HOLD_NETWORK_POLICY")

    operator = profile.get("operator", {})
    if operator.get("kill_switch_required") is True and operator.get("approval_surface") == "LOCAL_ONLY":
        checks.append("operator_boundary")
    else:
        holds.append("HOLD_OPERATOR_BOUNDARY")

    database = profile.get("database", {})
    if database.get("backend") == "sqlite" and str(database.get("path", "")).startswith("var/"):
        checks.append("sqlite_local_database")
    else:
        holds.append("HOLD_DATABASE_PROFILE")

    backup = profile.get("backup", {})
    if backup.get("enabled") is True and backup.get("verify_after_copy") is True and int(backup.get("retention_count", 0)) >= 3:
        checks.append("verified_backup_policy")
    else:
        holds.append("HOLD_BACKUP_POLICY")

    recovery = profile.get("recovery", {})
    if recovery.get("require_preflight_after_restore") is True and recovery.get("require_verified_backup") is True:
        checks.append("recovery_revalidation_required")
    else:
        holds.append("HOLD_RECOVERY_POLICY")

    directories = tuple(profile.get("directories", ()))
    required_dirs = ("var", "var/artifacts", "var/backups", "var/logs")
    if directories == required_dirs:
        checks.append("directory_contract_exact")
    else:
        holds.append("HOLD_DIRECTORY_CONTRACT")

    return PreflightResult("PASS_PROFILE" if not holds else "HOLD_PROFILE", tuple(checks), tuple(holds))


def evaluate_preflight(root: Path, *, python_version: tuple[int, int] | None = None) -> PreflightResult:
    checks: list[str] = []
    holds: list[str] = []
    policy_path = root / "config" / "runtime_policy.json"
    profile_path = root / "config" / "operator_profile.example.json"

    if not policy_path.is_file():
        holds.append("HOLD_RUNTIME_POLICY_MISSING")
    if not profile_path.is_file():
        holds.append("HOLD_OPERATOR_PROFILE_MISSING")
    if holds:
        return PreflightResult("HOLD_MISSING_INPUT", tuple(checks), tuple(holds))

    policy = load_json(policy_path)
    policy_result = validate_policy(policy)
    checks.extend(policy_result.checks)
    holds.extend(f"HOLD_RUNTIME_POLICY:{e}" for e in policy_result.errors)

    profile = load_json(profile_path)
    profile_result = validate_operator_profile(profile)
    checks.extend(profile_result.checks)
    holds.extend(profile_result.holds)

    version = python_version or (sys.version_info.major, sys.version_info.minor)
    minimum = _version_tuple(profile.get("python_min", "3.11"))
    if version >= minimum:
        checks.append(f"python_{version[0]}.{version[1]}_meets_minimum")
    else:
        holds.append("HOLD_PYTHON_VERSION")

    if tuple(policy.get("active_platforms", ())) == EXPECTED_ACTIVE:
        checks.append("active_platforms_exact")
    else:
        holds.append("HOLD_PLATFORM_SET")

    if policy.get("global_kill_switch_engaged") is True:
        checks.append("kill_switch_engaged")
    else:
        holds.append("HOLD_KILL_SWITCH")

    state = "PASS_PRE_PILOT_LOCAL" if not holds else "HOLD_PRE_PILOT"
    return PreflightResult(state, tuple(dict.fromkeys(checks)), tuple(dict.fromkeys(holds)))


def recovery_action(error_class: str) -> str:
    mapping = {
        "POLICY_DRIFT": "ENGAGE_KILL_SWITCH_AND_RESTORE_LAST_KNOWN_GOOD_CONFIG",
        "DATABASE_CORRUPTION": "STOP_RUNTIME_AND_RESTORE_LAST_VERIFIED_BACKUP",
        "QUEUE_DRIFT": "PRESERVE_EVENT_LOG_AND_REBUILD_DRY_RUN_QUEUE",
        "RIGHTS_DRIFT": "HOLD_AFFECTED_ASSETS_AND_REVALIDATE_RIGHTS_REGISTRY",
        "PUBLISHER_UNEXPECTED_WRITE": "ENGAGE_KILL_SWITCH_PRESERVE_EVIDENCE_AND_AUDIT",
        "UNKNOWN": "ENGAGE_KILL_SWITCH_PRESERVE_STATE_AND_DIAGNOSE",
    }
    return mapping.get(error_class, mapping["UNKNOWN"])


def preflight_report(root: Path) -> dict:
    result = evaluate_preflight(root)
    return {
        "state": result.state,
        "ok": result.ok,
        "checks": list(result.checks),
        "holds": list(result.holds),
        "execution_authority": False,
        "network_authority": False,
        "account_connection_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
    }
