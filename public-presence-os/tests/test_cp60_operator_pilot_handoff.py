from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
import re

import pytest

from public_presence_os.operator_pilot_handoff import (
    CHECKPOINT,
    EXPECTED_GATE_CODES,
    NEXT_UNIT,
    PARENT_ACCEPTANCE_CHECKPOINT,
    PARENT_CONTROL_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    OperatorPilotHandoffHold,
    compile_operator_pilot_handoff,
    render_operator_pilot_handoff_json,
    validate_operator_pilot_handoff_packet,
)

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def cp60_policy() -> dict:
    return load("operator_pilot_handoff_policy.json")


def test_cp60_compiles_deterministic_operator_handoff_packet():
    policy = cp60_policy()
    first = compile_operator_pilot_handoff(ROOT, policy)
    second = compile_operator_pilot_handoff(ROOT, policy)

    assert first == second
    assert first.state == STATE
    assert first.checkpoint == CHECKPOINT
    assert first.parent_acceptance_checkpoint == PARENT_ACCEPTANCE_CHECKPOINT
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT
    assert first.cp59_final_offline_acceptance_validated is True
    assert first.operator_handoff_ready is True
    assert first.global_kill_switch_engaged is True
    assert first.blockers == REQUIRED_BLOCKERS
    assert first.next_unit == NEXT_UNIT
    assert first.packet_hash == second.packet_hash
    assert first.packet_id == second.packet_id


def test_cp60_binds_exact_cp59_acceptance_and_preserves_control_hold():
    packet = compile_operator_pilot_handoff(ROOT, cp60_policy())
    registry = load("module_registry.json")
    priority = load("reimplementation_priority.json")

    assert packet.cp59_acceptance_id.startswith("ppa_")
    assert re.fullmatch(r"[0-9a-f]{64}", packet.cp59_acceptance_hash)
    assert re.fullmatch(r"[0-9a-f]{64}", packet.cp59_source_manifest_sha256)
    assert registry["checkpoint"] == "CP58"
    assert any(
        row["id"] == "M29_OPERATOR_PILOT_HANDOFF"
        and row["status"] == "CP60_OPERATOR_HANDOFF_READY_AUTHORIZATION_HOLD"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP58"
    assert priority["next"] == "CP59_PILOT_PACKAGE_COMPLETENESS_MANIFEST_AND_FINAL_OFFLINE_ACCEPTANCE_SUITE"


def test_cp60_authorization_gates_are_separate_and_ungranted():
    packet = compile_operator_pilot_handoff(ROOT, cp60_policy())

    assert tuple(gate.gate_code for gate in packet.authorization_gates) == EXPECTED_GATE_CODES
    assert packet.authorization_gates[0].scope == "READ_ONLY_CONNECTION_AND_EVIDENCE_CAPTURE_ONLY"
    assert packet.authorization_gates[1].scope == "PILOT_PUBLISH_ONLY_AFTER_SEPARATE_LIVE_VALIDATION"
    for gate in packet.authorization_gates:
        assert gate.state == "NOT_GRANTED"
        assert gate.decision_source == "EXTERNAL_HUMAN_ONLY"
        assert gate.authorizer_reference is None
        assert gate.authorized_at is None
        assert gate.authorization_evidence_sha256 is None
        assert gate.may_publish is False
        assert gate.may_deploy is False


def test_cp60_checklist_is_complete_and_review_only():
    packet = compile_operator_pilot_handoff(ROOT, cp60_policy())
    codes = {item.code for item in packet.checklist}

    assert len(codes) == 8
    assert "VERIFY_CP59_ACCEPTANCE" in codes
    assert "VERIFY_KILL_SWITCH_ENGAGED" in codes
    assert "VERIFY_READ_ONLY_AUTHORIZATION_ABSENT" in codes
    assert "VERIFY_PUBLISH_AUTHORIZATION_ABSENT" in codes
    assert all(item.required for item in packet.checklist)
    assert all(item.status == "READY_FOR_OPERATOR_REVIEW" for item in packet.checklist)


def test_cp60_policy_drift_fails_closed():
    policy = cp60_policy()

    drifted = dict(policy)
    drifted["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(OperatorPilotHandoffHold, match="HOLD_CP60_ACTIVE_PLATFORM_DRIFT"):
        compile_operator_pilot_handoff(ROOT, drifted)

    drifted = dict(policy)
    drifted["authority"] = dict(policy["authority"])
    drifted["authority"]["network_allowed"] = True
    with pytest.raises(OperatorPilotHandoffHold, match="HOLD_CP60_EXTERNAL_AUTHORITY_NOT_ZERO"):
        compile_operator_pilot_handoff(ROOT, drifted)

    drifted = dict(policy)
    drifted["authorization_gates"] = [dict(row) for row in policy["authorization_gates"]]
    drifted["authorization_gates"][0]["default_state"] = "GRANTED"
    with pytest.raises(OperatorPilotHandoffHold, match="HOLD_CP60_AUTHORIZATION_DEFAULT_NOT_HOLD"):
        compile_operator_pilot_handoff(ROOT, drifted)


def test_cp60_packet_tampering_cannot_grant_authority():
    packet = compile_operator_pilot_handoff(ROOT, cp60_policy())

    for field in (
        "live_evidence_captured",
        "secret_reference_resolved",
        "environment_read",
        "keychain_read",
        "oauth_attempted",
        "real_account_lookup_attempted",
        "account_connected",
        "network_attempted",
        "publish_attempted",
        "external_write_performed",
        "deploy_performed",
        "paid_service_used",
        "live_read_only_authorization_granted",
        "pilot_publish_authorization_granted",
        "self_authorization_performed",
    ):
        with pytest.raises(OperatorPilotHandoffHold, match="HOLD_CP60_PACKET_EXTERNAL_OR_AUTHORITY_FORBIDDEN"):
            validate_operator_pilot_handoff_packet(replace(packet, **{field: True}))


def test_cp60_rendered_packet_contains_no_credentials_or_authorization_claim():
    packet = compile_operator_pilot_handoff(ROOT, cp60_policy())
    rendered = render_operator_pilot_handoff_json(packet)
    data = json.loads(rendered)

    assert data["state"] == STATE
    assert data["network_attempted"] is False
    assert data["account_connected"] is False
    assert data["publish_attempted"] is False
    assert data["live_read_only_authorization_granted"] is False
    assert data["pilot_publish_authorization_granted"] is False
    assert "access_token" not in rendered.lower()
    assert "client_secret" not in rendered.lower()
    assert "bearer " not in rendered.lower()


def test_cp60_source_contains_no_network_secret_resolution_or_live_execution():
    import public_presence_os.operator_pilot_handoff as module

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
