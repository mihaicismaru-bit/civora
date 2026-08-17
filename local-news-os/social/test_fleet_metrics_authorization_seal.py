#!/usr/bin/env python3
"""Acceptance tests for fleet metrics authorization fingerprint / TOCTOU binding."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import fleet_metrics_authorization_seal as seal
import fleet_metrics_credential_binding as binding
import test_fleet_metrics_credential_binding as fixtures

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CAPABILITY_REGISTRY = json.loads((HERE / "metrics_transport_capabilities.json").read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture(repo_root: Path) -> tuple[dict, dict, dict, dict, dict, dict]:
    rt = fixtures.runtime()
    rt["instances"][0]["metrics_harvest"] = {
        "access_attestations": {
            "meta_graph_api": "alpha/social/meta_auth_state.json",
            "instagram_graph_api": "alpha/social/meta_auth_state.json",
        }
    }
    reg = fixtures.registry()
    fr = fixtures.fleet_result()
    cap = fixtures.capability_result(fr)
    plan = binding.plan_credential_bindings(rt, reg, fr, cap)
    assert plan["status"] == "CREDENTIAL_BINDINGS_READY", plan

    channel_registry = {
        "schema_version": 1,
        "instance_id": "alpha",
        "channels": [
            {"channel_id": "facebook", "config": "alpha/social/channels/facebook.json"},
            {"channel_id": "instagram", "config": "alpha/social/channels/instagram.json"},
        ],
    }
    facebook = {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "platform": "facebook",
        "credentials_ref": "github-actions-secret:ALPHA_FACEBOOK_ACCESS_TOKEN",
        "metrics": {"observed_only": True, "sources": ["meta_graph_api"]},
        "zero_paid_dependency": True,
    }
    instagram = {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": "alpha-instagram",
        "platform": "instagram",
        "credentials_ref": "github-actions-secret:ALPHA_INSTAGRAM_ACCESS_TOKEN",
        "metrics": {"observed_only": True, "sources": ["instagram_graph_api"]},
        "zero_paid_dependency": True,
    }
    attestation = {
        "schema_version": "1.0",
        "execution_owner": "test",
        "token_source": "durable_page",
        "page_id": "page-alpha",
        "page_name": "Alpha News",
        "instagram_account_id": "ig-alpha",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
        "status": "VALID",
    }
    _write_json(repo_root / "alpha/social/channel_registry.json", channel_registry)
    _write_json(repo_root / "alpha/social/channels/facebook.json", facebook)
    _write_json(repo_root / "alpha/social/channels/instagram.json", instagram)
    _write_json(repo_root / "alpha/social/meta_auth_state.json", attestation)
    return rt, reg, fr, cap, plan, copy.deepcopy(CAPABILITY_REGISTRY)


def _sealed(repo_root: Path) -> tuple[dict, dict, dict, dict, dict, dict]:
    rt, reg, fr, cap, plan, capability_registry = _fixture(repo_root)
    result = seal.seal_plan(repo_root, plan, rt, reg, cap, capability_registry)
    assert result["status"] == "CREDENTIAL_BINDINGS_READY", result
    return result, rt, reg, fr, cap, capability_registry


def _fingerprint(plan: dict) -> str:
    value = plan["workflow_matrix"][0]["authorization_fingerprint"]
    assert seal.FINGERPRINT_RE.fullmatch(value), value
    return value


def test_seal_is_deterministic_and_propagates_to_execution_matrix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first, rt, reg, _fr, cap, capability_registry = _sealed(root)
        second = seal.seal_plan(root, binding.plan_credential_bindings(rt, reg, fixtures.fleet_result(), cap), rt, reg, cap, capability_registry)
        assert _fingerprint(first) == _fingerprint(second)
        assert first["capability_authorizations"][0]["authorization_fingerprint"] == _fingerprint(first)
        assert first["guards"]["authorization_fingerprint_required_for_execution"] is True
        assert first["guards"]["authorization_recheck_immediately_before_network"] is True
        assert first["guards"]["authorization_material_secret_values_included"] is False


def test_verified_access_attestation_identity_change_rotates_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first, rt, reg, _fr, cap, capability_registry = _sealed(root)
        attestation_path = root / "alpha/social/meta_auth_state.json"
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation["page_id"] = "page-alpha-rotated"
        _write_json(attestation_path, attestation)
        second = seal.seal_plan(root, binding.plan_credential_bindings(rt, reg, fixtures.fleet_result(), cap), rt, reg, cap, capability_registry)
        assert second["status"] == "CREDENTIAL_BINDINGS_READY", second
        assert _fingerprint(second) != _fingerprint(first)


def test_invalidated_access_attestation_fails_closed_in_seal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _first, rt, reg, _fr, cap, capability_registry = _sealed(root)
        attestation_path = root / "alpha/social/meta_auth_state.json"
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation["status"] = "EXPIRED"
        attestation["facebook_ready"] = False
        _write_json(attestation_path, attestation)
        second = seal.seal_plan(root, binding.plan_credential_bindings(rt, reg, fixtures.fleet_result(), cap), rt, reg, cap, capability_registry)
        assert second["status"] == "CREDENTIAL_BINDINGS_HOLD", second
        assert second["workflow_matrix"] == [], second
        assert any("AUTHORIZATION_ACCESS_ATTESTATION_INVALID" in code for code in second["hard_blocks"]), second


def test_capability_registry_identity_change_rotates_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first, rt, reg, fr, cap, capability_registry = _sealed(root)
        new_id = "meta-facebook-observed-metrics-v1-rotated"
        for row in capability_registry["capabilities"]:
            if row["platform"] == "facebook":
                row["capability_id"] = new_id
        for row in cap["approved_channels"]:
            if row["platform"] == "facebook":
                row["transport_capability_id"] = new_id
        for grant in reg["bindings"][0]["capability_grants"]:
            if grant["metric_source"] == "meta_graph_api":
                grant["transport_capability_id"] = new_id
        plan = binding.plan_credential_bindings(rt, reg, fr, cap)
        assert plan["status"] == "CREDENTIAL_BINDINGS_READY", plan
        second = seal.seal_plan(root, plan, rt, reg, cap, capability_registry)
        assert second["status"] == "CREDENTIAL_BINDINGS_READY", second
        assert _fingerprint(second) != _fingerprint(first)


def test_channel_credential_reference_change_rotates_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first, rt, reg, fr, _cap, capability_registry = _sealed(root)
        facebook_path = root / "alpha/social/channels/facebook.json"
        facebook = json.loads(facebook_path.read_text(encoding="utf-8"))
        facebook["credentials_ref"] = "github-actions-secret:ALPHA_FACEBOOK_ALT_ACCESS_TOKEN"
        _write_json(facebook_path, facebook)
        for row in fr["channels"]:
            if row["platform"] == "facebook":
                row["credential_env_name"] = "ALPHA_FACEBOOK_ALT_ACCESS_TOKEN"
        cap = fixtures.capability_result(fr)
        for grant in reg["bindings"][0]["capability_grants"]:
            if grant["metric_source"] == "meta_graph_api":
                grant["credential_env_name"] = "ALPHA_FACEBOOK_ALT_ACCESS_TOKEN"
        plan = binding.plan_credential_bindings(rt, reg, fr, cap)
        assert plan["status"] == "CREDENTIAL_BINDINGS_READY", plan
        second = seal.seal_plan(root, plan, rt, reg, cap, capability_registry)
        assert second["status"] == "CREDENTIAL_BINDINGS_READY", second
        assert _fingerprint(second) != _fingerprint(first)


def test_secretish_material_in_attestation_is_rejected_without_echoing_value() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _first, rt, reg, _fr, cap, capability_registry = _sealed(root)
        attestation_path = root / "alpha/social/meta_auth_state.json"
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation["token_value"] = "must-never-appear"
        _write_json(attestation_path, attestation)
        result = seal.seal_plan(root, binding.plan_credential_bindings(rt, reg, fixtures.fleet_result(), cap), rt, reg, cap, capability_registry)
        assert result["status"] == "CREDENTIAL_BINDINGS_HOLD", result
        assert "must-never-appear" not in json.dumps(result, ensure_ascii=False)
        assert "AUTHORIZATION_ACCESS_ATTESTATION_SECRETISH_FIELDS_FORBIDDEN" in result["hard_blocks"]


def _fake_orchestrator(calls: list[bool]):
    def call(repo_root, selected_runtime, isolation_result, **kwargs):
        execute = bool(kwargs.get("execute"))
        calls.append(execute)
        instance = selected_runtime["instances"][0]["instance_id"]
        return {
            "status": "FLEET_EXECUTED" if execute else "FLEET_IDLE",
            "hard_blocks": [],
            "publication_blocked": False,
            "durable_paths": [f"{instance}/social/metrics/result.json"] if execute else [],
            "required_credential_env_names": [
                "ALPHA_FACEBOOK_ACCESS_TOKEN",
                "ALPHA_INSTAGRAM_ACCESS_TOKEN",
            ],
        }
    return call


def test_execute_requires_planned_fingerprint_before_any_orchestrator_call() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, rt, *_ = _sealed(root)
        calls: list[bool] = []
        result = seal.execute_sealed_instance(
            root,
            rt,
            {"status": "PASS", "errors": []},
            plan,
            "alpha-meta-v1",
            expected_authorization_fingerprint="",
            now="2026-08-17T06:00:00Z",
            execute=True,
            recheck_fingerprint_call=lambda: _fingerprint(plan),
            orchestrate_call=_fake_orchestrator(calls),
        )
        assert calls == []
        assert result["status"] == "HOLD_CREDENTIAL_AUTHORIZATION"
        assert result["hard_blocks"] == ["EXPECTED_AUTHORIZATION_FINGERPRINT_REQUIRED"]


def test_stale_planned_fingerprint_stops_before_preflight() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, rt, *_ = _sealed(root)
        calls: list[bool] = []
        stale = "sha256:" + "0" * 64
        result = seal.execute_sealed_instance(
            root,
            rt,
            {"status": "PASS", "errors": []},
            plan,
            "alpha-meta-v1",
            expected_authorization_fingerprint=stale,
            now="2026-08-17T06:00:00Z",
            execute=True,
            recheck_fingerprint_call=lambda: _fingerprint(plan),
            orchestrate_call=_fake_orchestrator(calls),
        )
        assert calls == []
        assert result["hard_blocks"] == ["AUTHORIZATION_FINGERPRINT_CHANGED_SINCE_PLAN"]


def test_pre_network_recheck_detects_toctou_after_preflight_without_provider_call() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, rt, *_ = _sealed(root)
        calls: list[bool] = []
        result = seal.execute_sealed_instance(
            root,
            rt,
            {"status": "PASS", "errors": []},
            plan,
            "alpha-meta-v1",
            expected_authorization_fingerprint=_fingerprint(plan),
            now="2026-08-17T06:00:00Z",
            execute=True,
            recheck_fingerprint_call=lambda: "sha256:" + "f" * 64,
            orchestrate_call=_fake_orchestrator(calls),
        )
        assert calls == [False], calls
        assert result["status"] == "HOLD_CREDENTIAL_AUTHORIZATION", result
        assert result["hard_blocks"] == ["AUTHORIZATION_CHANGED_BEFORE_NETWORK"]


def test_current_fingerprint_and_pre_network_recheck_allow_exact_bound_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, rt, *_ = _sealed(root)
        calls: list[bool] = []
        fingerprint = _fingerprint(plan)
        result = seal.execute_sealed_instance(
            root,
            rt,
            {"status": "PASS", "errors": []},
            plan,
            "alpha-meta-v1",
            expected_authorization_fingerprint=fingerprint,
            now="2026-08-17T06:00:00Z",
            execute=True,
            recheck_fingerprint_call=lambda: fingerprint,
            orchestrate_call=_fake_orchestrator(calls),
        )
        assert calls == [False, True], calls
        assert result["status"] == "BOUND_INSTANCE_EXECUTED", result
        assert result["authorization_fingerprint_verified"] is True
        assert result["pre_network_authorization_recheck"] is True
        assert result["authorization_fingerprint"] == fingerprint


def test_real_valcea_plan_is_sealed_without_secret_values() -> None:
    plan, _runtime = seal.build_sealed_plan(
        REPO_ROOT,
        now="2026-08-17T06:00:00Z",
    )
    assert plan["status"] == "CREDENTIAL_BINDINGS_READY", plan
    assert plan["authorization_seal_status"] == "AUTHORIZATION_SEAL_READY", plan
    assert plan["workflow_matrix"][0]["binding_id"] == "valcea-meta-observed-metrics-v1"
    assert seal.FINGERPRINT_RE.fullmatch(plan["workflow_matrix"][0]["authorization_fingerprint"])
    serialized = json.dumps(plan, ensure_ascii=False)
    assert "authorization_material_secret_values_included" in serialized
    assert "must-never-appear" not in serialized
    assert plan["publication_blocked"] is False
    assert plan["guards"]["zero_paid_dependency"] is True


def test_operational_workflow_passes_planned_fingerprint_into_sealed_executor() -> None:
    workflow = (REPO_ROOT / ".github/workflows/valcea-clar-observed-metrics-harvest.yml").read_text(encoding="utf-8")
    assert "fleet_metrics_authorization_seal.py" in workflow
    assert "AUTHORIZATION_FINGERPRINT: ${{ matrix.authorization_fingerprint }}" in workflow
    assert '--expected-authorization-fingerprint "$AUTHORIZATION_FINGERPRINT"' in workflow
    assert "authorization_fingerprint" in workflow
    assert "toJSON(secrets)" not in workflow


def run() -> None:
    tests = [
        test_seal_is_deterministic_and_propagates_to_execution_matrix,
        test_verified_access_attestation_identity_change_rotates_fingerprint,
        test_invalidated_access_attestation_fails_closed_in_seal,
        test_capability_registry_identity_change_rotates_fingerprint,
        test_channel_credential_reference_change_rotates_fingerprint,
        test_secretish_material_in_attestation_is_rejected_without_echoing_value,
        test_execute_requires_planned_fingerprint_before_any_orchestrator_call,
        test_stale_planned_fingerprint_stops_before_preflight,
        test_pre_network_recheck_detects_toctou_after_preflight_without_provider_call,
        test_current_fingerprint_and_pre_network_recheck_allow_exact_bound_execution,
        test_real_valcea_plan_is_sealed_without_secret_values,
        test_operational_workflow_passes_planned_fingerprint_into_sealed_executor,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} fleet metrics authorization seal acceptance tests passed")


if __name__ == "__main__":
    run()
