from __future__ import annotations
from pathlib import Path
from public_presence_os.rehearsal import *

ROOT=Path(__file__).resolve().parents[1]


def test_control_plane_passes_but_pilot_holds_on_validation_gate():
    r=run_synthetic_rehearsal(ROOT)
    assert r.control_plane_state=="PASS_SYNTHETIC_CONTROL_PLANE"
    assert r.pilot_state=="HOLD_PILOT_VALIDATION_GATES"
    assert r.golden_path_complete is False


def test_active_platforms_exact():
    r=run_synthetic_rehearsal(ROOT)
    assert r.active_platforms==("FACEBOOK_PAGE","INSTAGRAM_PROFESSIONAL","THREADS")


def test_all_pipeline_modules_now_have_executable_source():
    r=run_synthetic_rehearsal(ROOT)
    pipeline={s.module_id:s for s in r.stages}
    for module_id in REQUIRED_PIPELINE:
        assert pipeline[module_id].state=="PASS_EXECUTABLE_SOURCE"
        assert f"{module_id}:EXECUTABLE_SOURCE_UNAVAILABLE" not in r.blockers


def test_current_canonical_modules_execute():
    r=run_synthetic_rehearsal(ROOT)
    stages={s.module_id:s.state for s in r.stages}
    assert stages["M15_SOURCE_INGEST"]=="PASS_REGISTRY_VALIDATED"
    assert stages["M16_OPERATIONS"]=="PASS_PREFLIGHT"


def test_no_false_import_claims():
    r=run_synthetic_rehearsal(ROOT)
    assert r.imported_checkpoint_sources==()


def test_no_execution_authority():
    r=run_synthetic_rehearsal(ROOT)
    assert not any((r.execution_authority,r.network_authority,r.account_connection_authority,r.publish_authority,r.deploy_authority))


def test_report_contract():
    p=report_dict(run_synthetic_rehearsal(ROOT))
    assert p["golden_path_complete"] is False
    assert p["pilot_state"]=="HOLD_PILOT_VALIDATION_GATES"
    assert len(p["stages"])==16
    assert p["blockers"]==["HOLD_OPERATOR_EXACT_LOCAL_FONT_FILES_REQUIRED"]
