from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
import re

import pytest

from public_presence_os.pilot_package_acceptance import (
    ACCEPTANCE_CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    PilotPackageAcceptanceHold,
    compile_pilot_package_acceptance,
    render_pilot_package_acceptance_json,
    validate_pilot_package_acceptance_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def cp59_policy() -> dict:
    return load("pilot_package_acceptance_policy.json")


def test_cp59_compiles_deterministic_final_offline_acceptance_receipt():
    policy = cp59_policy()
    first = compile_pilot_package_acceptance(ROOT, policy)
    second = compile_pilot_package_acceptance(ROOT, policy)

    assert first == second
    assert first.state == STATE
    assert first.acceptance_checkpoint == ACCEPTANCE_CHECKPOINT
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT
    assert first.global_control_checkpoint == PARENT_CONTROL_CHECKPOINT
    assert first.final_offline_acceptance_passed is True
    assert first.global_kill_switch_engaged is True
    assert first.blockers == REQUIRED_BLOCKERS
    assert first.next_unit == NEXT_UNIT
    assert first.source_manifest_sha256 == second.source_manifest_sha256
    assert first.acceptance_hash == second.acceptance_hash
    assert first.acceptance_id == second.acceptance_id


def test_cp59_binds_complete_pipeline_and_m28_registry_state():
    receipt = compile_pilot_package_acceptance(ROOT, cp59_policy())
    states = {item.module_id: item.state for item in receipt.module_bindings}

    for module_id in (
        "M01_RADAR", "M02_RESEARCH", "M03_SCORING", "M04_MASTER_DRAFT", "M05_NATIVE_ADAPT",
        "M13_RIGHTS", "M06_VISUAL", "M07_QA", "M12_APPROVAL", "M08_QUEUE", "M09_PUBLISHER",
        "M10_ANALYTICS", "M11_LEARNING", "M19_META_ADAPTERS", "M20_META_CONNECTIONS",
        "M21_META_PREFLIGHT", "M22_META_OPERATOR_PROVISIONING", "M23_META_TRANSPORT_TWIN",
        "M24_META_READ_ONLY_GATE", "M25_META_LIVE_READ_ONLY_PROBE", "M26_META_OFFLINE_EVIDENCE_VALIDATOR",
        "M27_META_PILOT_READINESS", "M28_PILOT_PACKAGE_ACCEPTANCE",
    ):
        assert module_id in states

    assert states["M27_META_PILOT_READINESS"] == "CP58_OFFLINE_READINESS_AGGREGATED_LIVE_CONNECTION_HOLD"
    assert states["M28_PILOT_PACKAGE_ACCEPTANCE"] == "CP59_FINAL_OFFLINE_ACCEPTANCE_PASS_LIVE_GATES_HOLD"


def test_cp59_required_artifacts_are_sha256_bound():
    policy = cp59_policy()
    receipt = compile_pilot_package_acceptance(ROOT, policy)
    bindings = {item.path: item.sha256 for item in receipt.artifact_bindings}

    assert set(bindings) == set(policy["required_artifacts"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in bindings.values())
    assert "src/public_presence_os/pilot_package_acceptance.py" in bindings
    assert "docs/OPERATOR_INSTALLATION_CONFIGURATION_RECOVERY.md" in bindings
    assert "tests/test_cp59_pilot_package_acceptance.py" in bindings


def test_cp59_policy_and_parent_control_state_remain_fail_closed():
    policy = cp59_policy()
    registry = load("module_registry.json")
    priority = load("reimplementation_priority.json")
    runtime = load("runtime_policy.json")

    assert policy["checkpoint"] == "CP59"
    assert policy["parent_control_checkpoint"] == "CP58"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert policy["excluded_platforms"] == {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }
    assert all(value is False for value in policy["authority"].values())

    assert registry["checkpoint"] == "CP58"
    assert any(
        row["id"] == "M28_PILOT_PACKAGE_ACCEPTANCE"
        and row["status"] == "CP59_FINAL_OFFLINE_ACCEPTANCE_PASS_LIVE_GATES_HOLD"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP58"
    assert priority["next"] == "CP59_PILOT_PACKAGE_COMPLETENESS_MANIFEST_AND_FINAL_OFFLINE_ACCEPTANCE_SUITE"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp59_receipt_tampering_cannot_grant_live_or_paid_authority():
    receipt = compile_pilot_package_acceptance(ROOT, cp59_policy())

    for field in (
        "network_attempted",
        "account_connected",
        "publish_attempted",
        "external_write_performed",
        "deploy_performed",
        "paid_service_used",
        "live_connection_authorized",
        "final_pilot_authorization_present",
        "pilot_publish_ready",
    ):
        with pytest.raises(PilotPackageAcceptanceHold, match="HOLD_CP59_RECEIPT_EXTERNAL_OR_LIVE_AUTHORITY_FORBIDDEN"):
            validate_pilot_package_acceptance_receipt(replace(receipt, **{field: True}))


def test_cp59_policy_drift_fails_closed():
    policy = cp59_policy()

    drifted = dict(policy)
    drifted["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(PilotPackageAcceptanceHold, match="HOLD_CP59_ACTIVE_PLATFORM_DRIFT"):
        compile_pilot_package_acceptance(ROOT, drifted)

    drifted = dict(policy)
    drifted["authority"] = dict(policy["authority"])
    drifted["authority"]["network_allowed"] = True
    with pytest.raises(PilotPackageAcceptanceHold, match="HOLD_CP59_EXTERNAL_AUTHORITY_NOT_ZERO"):
        compile_pilot_package_acceptance(ROOT, drifted)


def test_cp59_rendered_receipt_is_canonical_and_has_zero_live_authority():
    receipt = compile_pilot_package_acceptance(ROOT, cp59_policy())
    rendered = render_pilot_package_acceptance_json(receipt)
    data = json.loads(rendered)

    assert data["acceptance_hash"] == receipt.acceptance_hash
    assert data["final_offline_acceptance_passed"] is True
    assert data["network_attempted"] is False
    assert data["account_connected"] is False
    assert data["publish_attempted"] is False
    assert data["deploy_performed"] is False
    assert data["paid_service_used"] is False
    assert data["live_connection_authorized"] is False
    assert data["pilot_publish_ready"] is False
    assert "ENV:PPOS_META" not in rendered
    assert "OS_KEYCHAIN:ppos/meta" not in rendered


def test_cp59_source_contains_no_network_secret_resolution_or_live_execution():
    import public_presence_os.pilot_package_acceptance as module

    src = inspect.getsource(module)
    forbidden_import_roots = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    for package in forbidden_import_roots:
        pattern = rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
        assert not re.search(pattern, src, re.I | re.M)
    for forbidden_literal in ("os.environ", "os.getenv", "keyring", "subprocess"):
        assert forbidden_literal not in src
    for forbidden_function in (
        "resolve_secret(", "read_secret(", "refresh_token(", "oauth_exchange(",
        "execute_http(", "perform_request(", "run_live_probe(", "publish_live(",
        "connect_account(", "authorize_live_connection(", "disengage_kill_switch(",
    ):
        assert forbidden_function not in src
