from __future__ import annotations

from pathlib import Path
import json

from public_presence_os.preflight import evaluate_preflight, recovery_action, validate_operator_profile

ROOT = Path(__file__).resolve().parents[1]


def load_profile() -> dict:
    return json.loads((ROOT / "config" / "operator_profile.example.json").read_text(encoding="utf-8"))


def test_cp32_preflight_passes_on_canonical_local_profile():
    r = evaluate_preflight(ROOT, python_version=(3, 12))
    assert r.ok
    assert r.state == "PASS_PRE_PILOT_LOCAL"
    assert not r.holds


def test_operator_profile_is_fail_closed():
    p = load_profile()
    r = validate_operator_profile(p)
    assert r.state == "PASS_PROFILE"
    assert not r.holds
    assert p["network"]["allow_live_api_calls"] is False
    assert p["network"]["allow_oauth"] is False
    assert p["operator"]["kill_switch_required"] is True
    assert p["evidence_mode"] == "SYNTHETIC_ONLY"


def test_network_relaxation_holds():
    p = load_profile()
    p["network"]["allow_live_api_calls"] = True
    r = validate_operator_profile(p)
    assert "HOLD_NETWORK_POLICY" in r.holds


def test_oauth_relaxation_holds():
    p = load_profile()
    p["network"]["allow_oauth"] = True
    r = validate_operator_profile(p)
    assert "HOLD_NETWORK_POLICY" in r.holds


def test_backup_contract_cannot_be_weakened():
    p = load_profile()
    p["backup"]["verify_after_copy"] = False
    assert "HOLD_BACKUP_POLICY" in validate_operator_profile(p).holds


def test_restore_requires_new_preflight():
    p = load_profile()
    p["recovery"]["require_preflight_after_restore"] = False
    assert "HOLD_RECOVERY_POLICY" in validate_operator_profile(p).holds


def test_directory_contract_exact():
    p = load_profile()
    p["directories"] = ["var"]
    assert "HOLD_DIRECTORY_CONTRACT" in validate_operator_profile(p).holds


def test_python_floor_holds():
    r = evaluate_preflight(ROOT, python_version=(3, 10))
    assert not r.ok
    assert "HOLD_PYTHON_VERSION" in r.holds


def test_recovery_matrix_is_deterministic():
    expected = {
        "POLICY_DRIFT": "ENGAGE_KILL_SWITCH_AND_RESTORE_LAST_KNOWN_GOOD_CONFIG",
        "DATABASE_CORRUPTION": "STOP_RUNTIME_AND_RESTORE_LAST_VERIFIED_BACKUP",
        "QUEUE_DRIFT": "PRESERVE_EVENT_LOG_AND_REBUILD_DRY_RUN_QUEUE",
        "RIGHTS_DRIFT": "HOLD_AFFECTED_ASSETS_AND_REVALIDATE_RIGHTS_REGISTRY",
        "PUBLISHER_UNEXPECTED_WRITE": "ENGAGE_KILL_SWITCH_PRESERVE_EVIDENCE_AND_AUDIT",
        "UNKNOWN": "ENGAGE_KILL_SWITCH_PRESERVE_STATE_AND_DIAGNOSE",
    }
    assert {k: recovery_action(k) for k in expected} == expected
    assert recovery_action("SOMETHING_NEW") == expected["UNKNOWN"]


def test_manual_contains_required_operator_sections():
    text = (ROOT / "docs" / "OPERATOR_INSTALLATION_CONFIGURATION_RECOVERY.md").read_text(encoding="utf-8")
    for section in (
        "Zero-cost local prerequisites",
        "Preflight",
        "Backup contract",
        "Restore contract",
        "Recovery matrix",
        "Kill switch drill",
        "Future Meta connection procedure",
        "Facebook Page lane",
        "Instagram Professional lane",
        "Threads lane",
        "Secret handling rules",
        "Pilot-entry gate",
    ):
        assert section in text


def test_manual_does_not_claim_current_activation():
    text = (ROOT / "docs" / "OPERATOR_INSTALLATION_CONFIGURATION_RECOVERY.md").read_text(encoding="utf-8")
    assert "Do not execute these steps during CP32" in text
    assert "PRE-PILOT / LOCAL-ONLY / FAIL-CLOSED" in text


def test_preflight_script_has_no_network_dependency():
    text = (ROOT / "src" / "public_presence_os" / "preflight.py").read_text(encoding="utf-8").lower()
    for forbidden in ("requests", "httpx", "aiohttp", "urllib.request", "socket"):
        assert forbidden not in text
