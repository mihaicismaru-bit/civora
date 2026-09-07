from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
import re

import pytest

from public_presence_os.control_plane_authorization_intake import (
    CHECKPOINT,
    EXPECTED_GATE_CODES,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    PARENT_HANDOFF_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    AuthorizationIntakeHold,
    compile_control_plane_authorization_intake,
    render_control_plane_authorization_intake_json,
    validate_authorization_shape_receipt,
    validate_authorization_submission_shape,
    validate_control_plane_authorization_intake_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def cp61_policy() -> dict:
    return load("control_plane_authorization_intake_policy.json")


def submission_for(contract, gate_code: str = "LIVE_READ_ONLY_CONNECTION_PROBE") -> dict:
    template = next(item for item in contract.intake_templates if item.gate_code == gate_code)
    return {
        "authorization_id": "auth_pilot_cp61_001",
        "gate_code": gate_code,
        "decision": "GRANT",
        "allowed_platforms": ["FACEBOOK_PAGE", "THREADS"],
        "scope": template.scope,
        "authorizer_reference": "HUMAN:operator-review-001",
        "authorized_at": "2026-09-07T04:00:00Z",
        "expires_at": "2026-09-07T05:00:00Z",
        "authorization_evidence_sha256": "a" * 64,
        "cp60_packet_id": contract.cp60_packet_id,
        "cp60_packet_hash": contract.cp60_packet_hash,
        "nonce": "cp61-synthetic-nonce-0001",
    }


def test_cp61_compiles_deterministic_intake_contract():
    policy = cp61_policy()
    first = compile_control_plane_authorization_intake(ROOT, policy)
    second = compile_control_plane_authorization_intake(ROOT, policy)

    assert first == second
    assert first.state == STATE
    assert first.checkpoint == CHECKPOINT
    assert first.parent_handoff_checkpoint == PARENT_HANDOFF_CHECKPOINT
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT
    assert first.cp60_handoff_validated is True
    assert first.intake_schema_ready is True
    assert first.global_kill_switch_engaged is True
    assert first.blockers == REQUIRED_BLOCKERS
    assert first.next_unit == NEXT_UNIT
    assert first.contract_id == second.contract_id
    assert first.contract_hash == second.contract_hash


def test_cp61_binds_exact_cp60_handoff_while_global_control_stays_cp58():
    contract = compile_control_plane_authorization_intake(ROOT, cp61_policy())
    registry = load("module_registry.json")

    assert contract.cp60_packet_id.startswith("oph_")
    assert re.fullmatch(r"[0-9a-f]{64}", contract.cp60_packet_hash)
    assert registry["checkpoint"] == "CP58"
    assert any(
        row["id"] == "M30_CONTROL_PLANE_AUTHORIZATION_INTAKE"
        and row["status"] == "CP61_AUTHORIZATION_INTAKE_CONTRACT_LOCAL_ONLY_CONTROL_PROMOTION_HOLD"
        for row in registry["modules"]
    )
    assert contract.control_plane_promoted is False
    assert contract.external_authorization_ingested is False


def test_cp61_keeps_read_only_and_publish_intake_templates_separate_without_authority():
    contract = compile_control_plane_authorization_intake(ROOT, cp61_policy())

    assert tuple(item.gate_code for item in contract.intake_templates) == EXPECTED_GATE_CODES
    assert contract.intake_templates[0].scope == "READ_ONLY_CONNECTION_AND_EVIDENCE_CAPTURE_ONLY"
    assert contract.intake_templates[1].scope == "PILOT_PUBLISH_ONLY_AFTER_SEPARATE_LIVE_VALIDATION"
    assert contract.intake_templates[0].grant_effect == "ELIGIBLE_FOR_CP62_VALIDATION_ONLY"
    assert contract.intake_templates[1].grant_effect == "HOLD_UNTIL_LIVE_EVIDENCE_AND_LATER_PROMOTION_GATE"
    assert all(item.state == "AWAITING_EXTERNAL_HUMAN_DECISION" for item in contract.intake_templates)
    assert all(item.decision_source == "EXTERNAL_HUMAN_ONLY" for item in contract.intake_templates)
    assert all(item.may_publish is False and item.may_deploy is False for item in contract.intake_templates)


def test_cp61_synthetic_grant_shape_validation_never_activates_authority():
    contract = compile_control_plane_authorization_intake(ROOT, cp61_policy())
    receipt = validate_authorization_submission_shape(contract, submission_for(contract))

    assert receipt.structurally_valid is True
    assert receipt.decision == "GRANT"
    assert receipt.state == "VALIDATED_SHAPE_ONLY_NO_AUTHORITY"
    assert receipt.authority_activated is False
    assert receipt.control_promotion_allowed is False
    assert receipt.live_probe_allowed is False
    assert receipt.network_allowed is False
    assert receipt.publish_allowed is False
    assert receipt.deploy_allowed is False
    assert receipt.nonce_sha256 != "cp61-synthetic-nonce-0001"
    validate_authorization_shape_receipt(receipt)


def test_cp61_submission_drift_fails_closed():
    contract = compile_control_plane_authorization_intake(ROOT, cp61_policy())

    bad = submission_for(contract)
    bad["allowed_platforms"] = ["LINKEDIN"]
    with pytest.raises(AuthorizationIntakeHold, match="HOLD_CP61_SUBMISSION_PLATFORM_OUTSIDE_ACTIVE_LANES"):
        validate_authorization_submission_shape(contract, bad)

    bad = submission_for(contract)
    bad["scope"] = "PILOT_PUBLISH_ONLY_AFTER_SEPARATE_LIVE_VALIDATION"
    with pytest.raises(AuthorizationIntakeHold, match="HOLD_CP61_SUBMISSION_SCOPE_MISMATCH"):
        validate_authorization_submission_shape(contract, bad)

    bad = submission_for(contract)
    bad["cp60_packet_hash"] = "b" * 64
    with pytest.raises(AuthorizationIntakeHold, match="HOLD_CP61_CP60_BINDING_MISMATCH"):
        validate_authorization_submission_shape(contract, bad)

    bad = submission_for(contract)
    bad["expires_at"] = bad["authorized_at"]
    with pytest.raises(AuthorizationIntakeHold, match="HOLD_CP61_AUTHORIZATION_WINDOW_INVALID"):
        validate_authorization_submission_shape(contract, bad)


def test_cp61_policy_and_contract_tampering_cannot_promote_control():
    policy = cp61_policy()
    drifted = json.loads(json.dumps(policy))
    drifted["authority"]["control_plane_promoted"] = True
    with pytest.raises(AuthorizationIntakeHold, match="HOLD_CP61_AUTHORITY_NOT_ZERO"):
        compile_control_plane_authorization_intake(ROOT, drifted)

    contract = compile_control_plane_authorization_intake(ROOT, policy)
    for field in (
        "external_authorization_ingested",
        "authorization_activated",
        "live_evidence_captured",
        "secret_reference_resolved",
        "environment_read",
        "keychain_read",
        "oauth_attempted",
        "real_account_lookup_attempted",
        "account_connected",
        "network_attempted",
        "live_probe_attempted",
        "publish_attempted",
        "external_write_performed",
        "control_plane_promoted",
        "deploy_performed",
        "paid_service_used",
        "self_authorization_performed",
    ):
        with pytest.raises(AuthorizationIntakeHold, match="HOLD_CP61_CONTRACT_EXTERNAL_OR_AUTHORITY_FORBIDDEN"):
            validate_control_plane_authorization_intake_contract(replace(contract, **{field: True}))


def test_cp61_rendered_contract_contains_no_credentials_or_live_authority_claim():
    contract = compile_control_plane_authorization_intake(ROOT, cp61_policy())
    rendered = render_control_plane_authorization_intake_json(contract)
    data = json.loads(rendered)

    assert data["state"] == STATE
    assert data["external_authorization_ingested"] is False
    assert data["network_attempted"] is False
    assert data["publish_attempted"] is False
    assert data["control_plane_promoted"] is False
    assert "bearer " not in rendered.lower()
    assert "oauth_token" not in rendered.lower()


def test_cp61_source_contains_no_network_secret_resolution_or_live_execution():
    import public_presence_os.control_plane_authorization_intake as module

    src = inspect.getsource(module)
    forbidden_import_roots = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    for package in forbidden_import_roots:
        pattern = rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
        assert not re.search(pattern, src, re.I | re.M)
    for forbidden_literal in ("os.environ", "os.getenv", "keyring", "subprocess"):
        assert forbidden_literal not in src
    for forbidden_function in (
        "resolve_secret(",
        "read_secret(",
        "oauth_exchange(",
        "execute_http(",
        "perform_request(",
        "run_live_probe(",
        "publish_live(",
        "connect_account(",
        "disengage_kill_switch(",
    ):
        assert forbidden_function not in src
