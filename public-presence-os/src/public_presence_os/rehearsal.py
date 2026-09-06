from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .control import EXPECTED_ACTIVE, load_json
from .import_registry import validate_registry, import_candidates
from .preflight import evaluate_preflight

REQUIRED_PIPELINE = (
    "M01_RADAR","M02_RESEARCH","M03_SCORING","M04_MASTER_DRAFT","M05_NATIVE_ADAPT","M06_VISUAL",
    "M07_QA","M08_QUEUE","M09_PUBLISHER","M10_ANALYTICS","M11_LEARNING","M12_APPROVAL","M13_RIGHTS","M14_EXPERIMENTS"
)

EXECUTABLE_STAGE_STATUSES = {
    "M01_RADAR": {"CP34_MINIMAL_EXECUTABLE_SLICE"},
    "M02_RESEARCH": {"CP35_MINIMAL_EXECUTABLE_SLICE"},
    "M03_SCORING": {"CP36_MINIMAL_EXECUTABLE_SLICE"},
    "M04_MASTER_DRAFT": {"CP37_MINIMAL_EXECUTABLE_SLICE"},
    "M05_NATIVE_ADAPT": {"CP38_MINIMAL_EXECUTABLE_SLICE"},
    "M06_VISUAL": {"CP40_MINIMAL_EXECUTABLE_SLICE", "CP49_IDENTITY_V2_RUNTIME_ACTIVE_EXACT_BINDING"},
    "M07_QA": {"CP41_MINIMAL_EXECUTABLE_SLICE", "CP49_IDENTITY_V2_EXACT_QA_GATE_ACTIVE"},
    "M08_QUEUE": {"CP43_MINIMAL_EXECUTABLE_SLICE"},
    "M09_PUBLISHER": {"CP44_MINIMAL_EXECUTABLE_SLICE"},
    "M10_ANALYTICS": {"CP45_MINIMAL_EXECUTABLE_SLICE"},
    "M11_LEARNING": {"CP46_MINIMAL_EXECUTABLE_SLICE"},
    "M12_APPROVAL": {"CP42_MINIMAL_EXECUTABLE_SLICE"},
    "M13_RIGHTS": {"CP39_MINIMAL_EXECUTABLE_SLICE"},
    "M14_EXPERIMENTS": {"CP47_MINIMAL_EXECUTABLE_SLICE"},
}

HISTORICAL_ONLY_STATUSES = {
    "VALIDATED_PREVIOUS_CHECKPOINTS","CP29_LOCKED","DRY_RUN_ONLY","SYNTHETIC_ONLY",
    "SHADOW_ONLY","LOCAL_ONLY","DOCUMENTARY_ONLY"
}

@dataclass(frozen=True)
class StageResult:
    module_id: str
    state: str
    reason: str

@dataclass(frozen=True)
class RehearsalReport:
    control_plane_state: str
    pilot_state: str
    stages: tuple[StageResult, ...]
    blockers: tuple[str, ...]
    active_platforms: tuple[str, ...]
    imported_checkpoint_sources: tuple[str, ...]
    execution_authority: bool = False
    network_authority: bool = False
    account_connection_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False

    @property
    def golden_path_complete(self) -> bool:
        return self.pilot_state == "PASS_PILOT_PREFLIGHT"


def run_synthetic_rehearsal(root: Path) -> RehearsalReport:
    preflight = evaluate_preflight(root)
    registry = load_json(root / "config" / "checkpoint_source_registry.json")
    reg_result = validate_registry(registry)
    modules = load_json(root / "config" / "module_registry.json")
    status_by_id = {m["id"]: m["status"] for m in modules.get("modules", [])}

    stages: list[StageResult] = []
    blockers: list[str] = []
    imported = import_candidates(registry) if reg_result.ok else ()

    if not preflight.ok:
        blockers.extend(preflight.holds)
    if not reg_result.ok:
        blockers.extend(f"HOLD_SOURCE_REGISTRY:{e}" for e in reg_result.errors)

    for module_id in REQUIRED_PIPELINE:
        status = status_by_id.get(module_id)
        if status in EXECUTABLE_STAGE_STATUSES.get(module_id, set()):
            state = "PASS_EXECUTABLE_SOURCE"
            reason = f"{module_id} has canonical executable source in GitHub"
        elif status in HISTORICAL_ONLY_STATUSES:
            state = "HOLD_EXECUTABLE_SOURCE_UNAVAILABLE"
            reason = f"{module_id} has historical maturity evidence but no canonical executable source imported into GitHub"
            blockers.append(f"{module_id}:EXECUTABLE_SOURCE_UNAVAILABLE")
        else:
            state = "HOLD_MODULE_REGISTRY"
            reason = f"{module_id} registry state is not recognized for rehearsal"
            blockers.append(f"{module_id}:REGISTRY_STATE")
        stages.append(StageResult(module_id,state,reason))

    stages.append(StageResult("M15_SOURCE_INGEST","PASS_REGISTRY_VALIDATED" if reg_result.ok else "HOLD_SOURCE_REGISTRY",
                              f"exact import candidates={len(imported)}"))
    stages.append(StageResult("M16_OPERATIONS","PASS_PREFLIGHT" if preflight.ok else "HOLD_PREFLIGHT",preflight.state))

    platforms = tuple(load_json(root / "config" / "runtime_policy.json").get("active_platforms", ()))
    if platforms != EXPECTED_ACTIVE:
        blockers.append("ACTIVE_PLATFORM_SET_MISMATCH")

    identity_runtime_path = root / "config" / "identity_runtime_policy.json"
    identity_runtime_status = status_by_id.get("M18_VISUAL_IDENTITY")
    if identity_runtime_status == "CP49_V2_RUNTIME_ACTIVE_LOCAL_ONLY":
        if not identity_runtime_path.is_file():
            blockers.append("HOLD_IDENTITY_RUNTIME_POLICY_MISSING")
        else:
            identity_runtime = load_json(identity_runtime_path)
            exact_runtime_contract = (
                identity_runtime.get("checkpoint") == "CP49"
                and identity_runtime.get("identity_name") == "EDITORIAL_LEDGER_V2"
                and identity_runtime.get("activation_state") == "LOCAL_RUNTIME_ACTIVE_EXACT_BINDING_ONLY"
                and identity_runtime.get("legacy_identity_hold_supersession", {}).get("only_when_exact_v2_manifest_passes") is True
                and identity_runtime.get("authority", {}).get("network_fetch_allowed") is False
                and identity_runtime.get("authority", {}).get("real_account_connection_allowed") is False
                and identity_runtime.get("authority", {}).get("public_publish_allowed") is False
                and identity_runtime.get("authority", {}).get("deploy_allowed") is False
            )
            if exact_runtime_contract:
                blockers.append("HOLD_OPERATOR_EXACT_LOCAL_FONT_FILES_REQUIRED")
            else:
                blockers.append("HOLD_IDENTITY_V2_RUNTIME_CONTRACT")
    else:
        identity_path = root / "config" / "visual_identity_policy.json"
        if not identity_path.is_file():
            blockers.append("HOLD_VISUAL_IDENTITY_POLICY_MISSING")
        else:
            identity = load_json(identity_path)
            identity_bound = (
                identity.get("production_identity_equivalence_asserted") is True
                and not str(identity.get("font_binding_state", "")).startswith("HOLD_")
            )
            if not identity_bound:
                blockers.append("HOLD_IDENTITY_EQUIVALENCE")

    control_ok = preflight.ok and reg_result.ok and platforms == EXPECTED_ACTIVE
    pilot_ok = control_ok and not blockers
    executable_gap = any(
        blocker.endswith(":EXECUTABLE_SOURCE_UNAVAILABLE") or blocker.endswith(":REGISTRY_STATE")
        for blocker in blockers
    )
    if pilot_ok:
        pilot_state = "PASS_PILOT_PREFLIGHT"
    elif executable_gap:
        pilot_state = "HOLD_PILOT_EXECUTABLE_GAPS"
    else:
        pilot_state = "HOLD_PILOT_VALIDATION_GATES"
    return RehearsalReport(
        control_plane_state="PASS_SYNTHETIC_CONTROL_PLANE" if control_ok else "HOLD_CONTROL_PLANE",
        pilot_state=pilot_state,
        stages=tuple(stages),
        blockers=tuple(dict.fromkeys(blockers)),
        active_platforms=platforms,
        imported_checkpoint_sources=tuple(imported),
    )


def report_dict(report: RehearsalReport) -> dict:
    return {
        "control_plane_state": report.control_plane_state,
        "pilot_state": report.pilot_state,
        "golden_path_complete": report.golden_path_complete,
        "active_platforms": list(report.active_platforms),
        "imported_checkpoint_sources": list(report.imported_checkpoint_sources),
        "stages": [s.__dict__ for s in report.stages],
        "blockers": list(report.blockers),
        "execution_authority": report.execution_authority,
        "network_authority": report.network_authority,
        "account_connection_authority": report.account_connection_authority,
        "publish_authority": report.publish_authority,
        "deploy_authority": report.deploy_authority,
    }
