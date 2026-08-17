#!/usr/bin/env python3
"""Acceptance tests for capability-bound fleet metrics credential grants."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


binding = _load("fleet_metrics_credential_binding", "fleet_metrics_credential_binding.py")

CAPABILITY_BY_PLATFORM = {
    "facebook": "meta-facebook-observed-metrics-v1",
    "instagram": "meta-instagram-observed-metrics-v1",
}
SOURCE_BY_PLATFORM = {
    "facebook": "meta_graph_api",
    "instagram": "instagram_graph_api",
}


def runtime(instances: tuple[str, ...] = ("alpha",)) -> dict:
    return {
        "schema_version": "1.0",
        "product": "test fleet",
        "policy": {"zero_paid_dependency": True},
        "instances": [
            {
                "instance_id": instance,
                "instance_root": instance,
                "channel_registry": f"{instance}/social/channel_registry.json",
                "credential_namespace": f"{instance.upper()}_",
            }
            for instance in instances
        ],
    }


def fleet_result(instances: tuple[str, ...] = ("alpha",)) -> dict:
    channels = []
    for instance in instances:
        for platform, source in SOURCE_BY_PLATFORM.items():
            channels.append({
                "instance_id": instance,
                "channel_id": f"{instance}-{platform}",
                "platform": platform,
                "eligible": True,
                "credential_env_name": f"{instance.upper()}_{platform.upper()}_ACCESS_TOKEN",
                "metric_source": source,
                "status": "NO_AUTHORITATIVE_PUBLICATION_CATALOG",
                "publication_blocked": False,
                "durable_paths": [],
            })
    return {
        "status": "FLEET_IDLE",
        "publication_blocked": False,
        "channels": channels,
        "guards": {
            "zero_paid_dependency": True,
            "native_free_transport_only": True,
            "credential_values_returned": False,
        },
    }


def capability_result(fr: dict, *, excluded: set[tuple[str, str]] | None = None) -> dict:
    excluded = excluded or set()
    approved = []
    holds = []
    for row in fr["channels"]:
        if row.get("eligible") is not True:
            continue
        platform = row["platform"]
        key = (row["instance_id"], platform)
        payload = {
            "instance_id": row["instance_id"],
            "channel_id": row["channel_id"],
            "platform": platform,
            "metric_source": row["metric_source"],
            "transport_capability_id": CAPABILITY_BY_PLATFORM[platform],
            "credential_env_name": row["credential_env_name"],
            "access_attestation_path": f"{row['instance_id']}/social/meta_auth_state.json",
            "hard_blocks": [],
        }
        if key in excluded:
            payload["hard_blocks"] = ["UNVERIFIED_NATIVE_METRICS_ACCESS"]
            holds.append(payload)
        else:
            payload["transport_implementation_verified"] = True
            payload["verified_access_attestation"] = True
            approved.append(payload)
    return {
        "status": "CAPABILITY_GATE_PARTIAL_HOLD" if holds else ("CAPABILITY_GATE_READY" if approved else "CAPABILITY_GATE_IDLE"),
        "publication_blocked": False,
        "hard_blocks": [],
        "approved_channels": approved,
        "channel_holds": holds,
        "guards": {
            "explicit_transport_registration_required": True,
            "transport_implementation_match_required": True,
            "verified_access_attestation_required": True,
            "explicit_credential_binding_still_required": True,
            "credential_values_read": False,
            "credential_values_returned": False,
            "native_free_transport_only": True,
            "zero_paid_dependency": True,
        },
    }


def registry(instances: tuple[str, ...] = ("alpha",)) -> dict:
    rows = []
    for instance in instances:
        rows.append({
            "binding_id": f"{instance}-meta-v1",
            "instance_id": instance,
            "credential_namespace": f"{instance.upper()}_",
            "capability_grants": [
                {
                    "transport_capability_id": CAPABILITY_BY_PLATFORM[platform],
                    "metric_source": source,
                    "credential_env_name": f"{instance.upper()}_{platform.upper()}_ACCESS_TOKEN",
                }
                for platform, source in SOURCE_BY_PLATFORM.items()
            ],
        })
    return {
        "schema_version": "1.0",
        "product": "test bindings",
        "policy": {
            "explicit_per_instance_grant_required": True,
            "transport_capability_binding_required": True,
            "cross_instance_secret_sharing_forbidden": True,
            "secret_values_in_registry_forbidden": True,
            "dynamic_secret_enumeration_forbidden": True,
            "analytics_advisory_only": True,
            "zero_paid_dependency": True,
        },
        "bindings": rows,
    }


def make_plan(rt: dict | None = None, reg: dict | None = None, fr: dict | None = None, cap: dict | None = None) -> dict:
    rt = rt or runtime()
    fr = fr or fleet_result(tuple(row["instance_id"] for row in rt["instances"]))
    reg = reg or registry(tuple(row["instance_id"] for row in rt["instances"]))
    cap = cap if cap is not None else capability_result(fr)
    return binding.plan_credential_bindings(rt, reg, fr, cap)


def test_two_instances_get_deterministic_separate_secret_name_matrices() -> None:
    rt = runtime(("beta", "alpha"))
    fr = fleet_result(("beta", "alpha"))
    plan = make_plan(rt, registry(("beta", "alpha")), fr, capability_result(fr))
    assert plan["status"] == "CREDENTIAL_BINDINGS_READY", plan
    assert [row["instance_id"] for row in plan["workflow_matrix"]] == ["alpha", "beta"], plan
    alpha, beta = plan["workflow_matrix"]
    assert set(alpha["credential_env_names"]).isdisjoint(beta["credential_env_names"])
    assert plan["guards"]["transport_capability_binding_required"] is True
    assert plan["guards"]["capability_gate_bypass_allowed"] is False
    assert plan["guards"]["secret_values_read_by_binding_engine"] is False


def test_plan_without_capability_gate_result_fails_closed() -> None:
    plan = binding.plan_credential_bindings(runtime(), registry(), fleet_result(), None)
    assert plan["status"] == "CREDENTIAL_BINDINGS_HOLD", plan
    assert plan["workflow_matrix"] == [], plan
    assert "CAPABILITY_GATE_RESULT_REQUIRED" in plan["hard_blocks"]


def test_future_eligible_instance_without_binding_gets_no_implicit_grant() -> None:
    rt = runtime(("alpha", "beta"))
    fr = fleet_result(("alpha", "beta"))
    plan = make_plan(rt, registry(("alpha",)), fr, capability_result(fr))
    assert plan["status"] == "CREDENTIAL_BINDINGS_PARTIAL", plan
    assert plan["unbound_instances"] == ["beta"], plan
    assert [row["instance_id"] for row in plan["workflow_matrix"]] == ["alpha"], plan


def test_binding_cannot_overgrant_unused_credential() -> None:
    reg = registry()
    reg["bindings"][0]["capability_grants"].append({
        "transport_capability_id": "unused-native-metrics-v1",
        "metric_source": "unused_native_api",
        "credential_env_name": "ALPHA_UNUSED_ACCESS_TOKEN",
    })
    plan = make_plan(reg=reg)
    assert plan["workflow_matrix"] == [], plan
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert any(code.startswith("BINDING_OVERGRANTS_CREDENTIALS:") for code in blocks), plan
    assert any(code.startswith("BINDING_OVERGRANTS_CAPABILITY_GRANTS:") for code in blocks), plan


def test_binding_cannot_omit_required_credential() -> None:
    reg = registry()
    reg["bindings"][0]["capability_grants"] = reg["bindings"][0]["capability_grants"][:1]
    plan = make_plan(reg=reg)
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert any(code.startswith("BINDING_MISSING_REQUIRED_CREDENTIALS:") for code in blocks), plan
    assert any(code.startswith("BINDING_MISSING_REQUIRED_CAPABILITIES:") for code in blocks), plan


def test_binding_cannot_escape_instance_namespace() -> None:
    reg = registry()
    reg["bindings"][0]["capability_grants"][0]["credential_env_name"] = "BETA_FACEBOOK_ACCESS_TOKEN"
    plan = make_plan(reg=reg)
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert "BINDING_CREDENTIAL_OUTSIDE_INSTANCE_NAMESPACE" in blocks, plan


def test_cross_instance_secret_name_reuse_is_rejected() -> None:
    reg = registry(("alpha", "beta"))
    reg["bindings"][1]["capability_grants"][0]["credential_env_name"] = "ALPHA_FACEBOOK_ACCESS_TOKEN"
    fr = fleet_result(("alpha", "beta"))
    for row in fr["channels"]:
        if row["instance_id"] == "beta" and row["platform"] == "facebook":
            row["credential_env_name"] = "ALPHA_FACEBOOK_ACCESS_TOKEN"
    plan = make_plan(runtime(("alpha", "beta")), reg, fr, capability_result(fr))
    beta_hold = next(row for row in plan["binding_holds"] if row["instance_id"] == "beta")
    assert any(code.startswith("CROSS_INSTANCE_CREDENTIAL_REUSE:") for code in beta_hold["hard_blocks"]), plan


def test_unknown_fields_cannot_smuggle_secret_material() -> None:
    reg = registry()
    reg["bindings"][0]["capability_grants"][0]["secret_value"] = "must-never-be-here"
    plan = make_plan(reg=reg)
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert any(code.startswith("UNKNOWN_CAPABILITY_GRANT_FIELDS:") for code in blocks), plan
    assert "must-never-be-here" not in json.dumps(plan, ensure_ascii=False)


def test_structural_policy_fault_invalidates_complete_matrix() -> None:
    rt = runtime(("alpha", "beta"))
    fr = fleet_result(("alpha", "beta"))
    reg = registry(("alpha", "beta"))
    reg["policy"]["transport_capability_binding_required"] = False
    plan = make_plan(rt, reg, fr, capability_result(fr))
    assert plan["status"] == "CREDENTIAL_BINDINGS_HOLD", plan
    assert plan["workflow_matrix"] == [], plan
    assert "BINDING_POLICY_REQUIRED:transport_capability_binding_required" in plan["hard_blocks"]


def test_metric_source_overgrant_is_rejected() -> None:
    reg = registry()
    reg["bindings"][0]["capability_grants"][0]["metric_source"] = "paid_social_analytics"
    plan = make_plan(reg=reg)
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert any(code.startswith("BINDING_OVERGRANTS_SOURCES:") for code in blocks), plan
    assert any(code.startswith("BINDING_OVERGRANTS_CAPABILITY_GRANTS:") for code in blocks), plan


def test_unapproved_capability_id_is_rejected_even_when_source_and_credential_match() -> None:
    reg = registry()
    reg["bindings"][0]["capability_grants"][0]["transport_capability_id"] = "fake-facebook-metrics-v1"
    plan = make_plan(reg=reg)
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert any(code.startswith("BINDING_MISSING_REQUIRED_CAPABILITIES:") for code in blocks), plan
    assert any(code.startswith("BINDING_OVERGRANTS_CAPABILITIES:") for code in blocks), plan


def test_credentials_cannot_be_swapped_between_capabilities_even_when_flat_sets_match() -> None:
    reg = registry()
    first, second = reg["bindings"][0]["capability_grants"]
    first["credential_env_name"], second["credential_env_name"] = second["credential_env_name"], first["credential_env_name"]
    plan = make_plan(reg=reg)
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert any(code.startswith("BINDING_MISSING_REQUIRED_CAPABILITY_GRANTS:") for code in blocks), plan
    assert any(code.startswith("BINDING_OVERGRANTS_CAPABILITY_GRANTS:") for code in blocks), plan
    assert not any(code.startswith("BINDING_OVERGRANTS_CREDENTIALS:") for code in blocks), plan


def test_partial_capability_gate_cannot_grant_held_channel_secret() -> None:
    fr = fleet_result()
    cap = capability_result(fr, excluded={("alpha", "instagram")})
    plan = make_plan(fr=fr, cap=cap)
    assert plan["status"] == "CREDENTIAL_BINDINGS_PARTIAL", plan
    blocks = plan["binding_holds"][0]["hard_blocks"]
    assert any("instagram_graph_api" in code for code in blocks if code.startswith("BINDING_OVERGRANTS")), plan


def test_capability_gate_approval_must_match_same_fleet_channel() -> None:
    fr = fleet_result()
    cap = capability_result(fr)
    cap["approved_channels"][0]["credential_env_name"] = "ALPHA_OTHER_ACCESS_TOKEN"
    plan = make_plan(fr=fr, cap=cap)
    assert plan["status"] == "CREDENTIAL_BINDINGS_HOLD", plan
    assert "CAPABILITY_GATE_APPROVAL_NOT_IN_FLEET" in plan["hard_blocks"]


def test_execution_is_scoped_to_exactly_one_bound_instance() -> None:
    rt = runtime(("alpha", "beta"))
    fr = fleet_result(("alpha", "beta"))
    plan = make_plan(rt, registry(("alpha", "beta")), fr, capability_result(fr))
    seen: list[tuple[tuple[str, ...], bool]] = []

    def fake_orchestrate(repo_root, selected_runtime, isolation_result, **kwargs):
        instance_ids = tuple(row["instance_id"] for row in selected_runtime["instances"])
        seen.append((instance_ids, bool(kwargs.get("execute"))))
        instance = instance_ids[0]
        return {
            "status": "FLEET_EXECUTED" if kwargs.get("execute") else "FLEET_IDLE",
            "hard_blocks": [],
            "publication_blocked": False,
            "durable_paths": [f"{instance}/social/{instance}_metrics.json"] if kwargs.get("execute") else [],
            "required_credential_env_names": [
                f"{instance.upper()}_FACEBOOK_ACCESS_TOKEN",
                f"{instance.upper()}_INSTAGRAM_ACCESS_TOKEN",
            ],
        }

    result = binding.execute_bound_instance(
        Path("."),
        rt,
        {"status": "PASS", "errors": []},
        plan,
        "alpha-meta-v1",
        now="2026-08-17T06:00:00Z",
        execute=True,
        orchestrate_call=fake_orchestrate,
    )
    assert seen == [(("alpha",), False), (("alpha",), True)], seen
    assert result["instance_id"] == "alpha"
    assert result["status"] == "BOUND_INSTANCE_EXECUTED"
    assert result["transport_capability_ids"] == [
        "meta-facebook-observed-metrics-v1",
        "meta-instagram-observed-metrics-v1",
    ]


def test_execution_requires_capability_authorization_sidecar() -> None:
    plan = make_plan()
    plan["capability_authorizations"] = []
    calls: list[bool] = []

    def fake_orchestrate(*args, **kwargs):
        calls.append(True)
        raise AssertionError("must not execute")

    result = binding.execute_bound_instance(
        Path("."),
        runtime(),
        {"status": "PASS", "errors": []},
        plan,
        "alpha-meta-v1",
        now="2026-08-17T06:00:00Z",
        execute=True,
        orchestrate_call=fake_orchestrate,
    )
    assert calls == []
    assert result["status"] == "HOLD_CREDENTIAL_BINDING"
    assert result["hard_blocks"] == ["BINDING_CAPABILITY_AUTHORIZATION_MISSING"]


def test_changed_runtime_credential_requirement_stops_before_execute() -> None:
    rt = runtime()
    plan = make_plan(rt)
    calls: list[bool] = []

    def fake_orchestrate(repo_root, selected_runtime, isolation_result, **kwargs):
        calls.append(bool(kwargs.get("execute")))
        return {
            "status": "FLEET_IDLE",
            "hard_blocks": [],
            "publication_blocked": False,
            "durable_paths": [],
            "required_credential_env_names": ["ALPHA_DIFFERENT_ACCESS_TOKEN"],
        }

    result = binding.execute_bound_instance(
        Path("."),
        rt,
        {"status": "PASS", "errors": []},
        plan,
        "alpha-meta-v1",
        now="2026-08-17T06:00:00Z",
        execute=True,
        orchestrate_call=fake_orchestrate,
    )
    assert calls == [False], calls
    assert result["status"] == "HOLD_CREDENTIAL_BINDING", result
    assert "BOUND_INSTANCE_CREDENTIAL_REQUIREMENTS_CHANGED" in result["hard_blocks"]


def test_unauthorized_binding_never_reaches_fleet_executor() -> None:
    calls: list[bool] = []

    def fake_orchestrate(*args, **kwargs):
        calls.append(True)
        raise AssertionError("must not execute")

    result = binding.execute_bound_instance(
        Path("."),
        runtime(),
        {"status": "PASS", "errors": []},
        make_plan(),
        "not-authorized",
        now="2026-08-17T06:00:00Z",
        execute=True,
        orchestrate_call=fake_orchestrate,
    )
    assert calls == []
    assert result["status"] == "HOLD_CREDENTIAL_BINDING"


def test_real_valcea_binding_matches_current_verified_native_metrics_channels() -> None:
    plan, _runtime, registry_value, _fleet_result = binding.run_plan(
        REPO_ROOT,
        Path("local-news-os/social/social_runtime_registry.json"),
        Path("local-news-os/social/metrics_credential_bindings.json"),
        Path("local-news-os/social/metrics_transport_capabilities.json"),
        now="2026-08-17T06:00:00Z",
    )
    assert plan["status"] == "CREDENTIAL_BINDINGS_READY", plan
    assert plan["capability_gate_status"] == "CAPABILITY_GATE_READY", plan
    assert plan["workflow_matrix"] == [{
        "binding_id": "valcea-meta-observed-metrics-v1",
        "instance_id": "valcea",
        "credential_env_names": ["VALCEA_FB_PAGE_ACCESS_TOKEN", "VALCEA_IG_ACCESS_TOKEN"],
        "metric_sources": ["instagram_graph_api", "meta_graph_api"],
    }], plan
    assert plan["capability_authorizations"][0]["transport_capability_ids"] == [
        "meta-facebook-observed-metrics-v1",
        "meta-instagram-observed-metrics-v1",
    ]
    assert registry_value["policy"]["transport_capability_binding_required"] is True
    assert registry_value["policy"]["zero_paid_dependency"] is True


def test_workflow_never_enumerates_all_secrets_and_binding_standalone_self_gates() -> None:
    workflow = (REPO_ROOT / ".github/workflows/valcea-clar-observed-metrics-harvest.yml").read_text(encoding="utf-8")
    module_text = (HERE / "fleet_metrics_credential_binding.py").read_text(encoding="utf-8")
    compact = re.sub(r"\s+", "", workflow).lower()
    assert "tojson(secrets)" not in compact
    assert "max-parallel: 1" in workflow
    assert "fleet_metrics_credential_binding.py" in workflow
    assert "fleet_metrics_transport_capability_gate as capability_gate" in module_text
    assert "capability_gate.run_gate(" in module_text
    assert "matrix.binding_id == 'valcea-meta-observed-metrics-v1'" in workflow
    assert workflow.count("${{ secrets.VALCEA_FB_PAGE_ACCESS_TOKEN }}") == 1
    assert workflow.count("${{ secrets.VALCEA_IG_ACCESS_TOKEN }}") == 1
    assert "\n    env:\n      VALCEA_FB_PAGE_ACCESS_TOKEN:" not in workflow


def test_plan_is_deterministic() -> None:
    rt = runtime(("beta", "alpha"))
    reg = registry(("beta", "alpha"))
    fr = fleet_result(("beta", "alpha"))
    cap = capability_result(fr)
    first = binding.plan_credential_bindings(copy.deepcopy(rt), copy.deepcopy(reg), copy.deepcopy(fr), copy.deepcopy(cap))
    second = binding.plan_credential_bindings(copy.deepcopy(rt), copy.deepcopy(reg), copy.deepcopy(fr), copy.deepcopy(cap))
    assert first == second


def run() -> None:
    tests = [
        test_two_instances_get_deterministic_separate_secret_name_matrices,
        test_plan_without_capability_gate_result_fails_closed,
        test_future_eligible_instance_without_binding_gets_no_implicit_grant,
        test_binding_cannot_overgrant_unused_credential,
        test_binding_cannot_omit_required_credential,
        test_binding_cannot_escape_instance_namespace,
        test_cross_instance_secret_name_reuse_is_rejected,
        test_unknown_fields_cannot_smuggle_secret_material,
        test_structural_policy_fault_invalidates_complete_matrix,
        test_metric_source_overgrant_is_rejected,
        test_unapproved_capability_id_is_rejected_even_when_source_and_credential_match,
        test_credentials_cannot_be_swapped_between_capabilities_even_when_flat_sets_match,
        test_partial_capability_gate_cannot_grant_held_channel_secret,
        test_capability_gate_approval_must_match_same_fleet_channel,
        test_execution_is_scoped_to_exactly_one_bound_instance,
        test_execution_requires_capability_authorization_sidecar,
        test_changed_runtime_credential_requirement_stops_before_execute,
        test_unauthorized_binding_never_reaches_fleet_executor,
        test_real_valcea_binding_matches_current_verified_native_metrics_channels,
        test_workflow_never_enumerates_all_secrets_and_binding_standalone_self_gates,
        test_plan_is_deterministic,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} capability-bound fleet metrics credential acceptance tests passed")


if __name__ == "__main__":
    run()
