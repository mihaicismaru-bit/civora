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
    "M13_RIGHTS": {"CP39_MINIMAL_EXECUTABLE_SLICE"},
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

    control_ok = preflight.ok and reg_result.ok and platforms == EXPECTED_ACTIVE
    pilot_ok = control_ok and not blockers
    return RehearsalReport(
        control_plane_state="PASS_SYNTHETIC_CONTROL_PLANE" if control_ok else "HOLD_CONTROL_PLANE",
        pilot_state="PASS_PILOT_PREFLIGHT" if pilot_ok else "HOLD_PILOT_EXECUTABLE_GAPS",
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
