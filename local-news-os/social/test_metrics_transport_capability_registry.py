#!/usr/bin/env python3
"""Acceptance tests for explicit fleet native metrics transport capabilities."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cap = _load("metrics_transport_capability_registry", "metrics_transport_capability_registry.py")
gate = _load("fleet_metrics_transport_capability_gate", "fleet_metrics_transport_capability_gate.py")


def registry() -> dict:
    return json.loads((HERE / "metrics_transport_capabilities.json").read_text(encoding="utf-8"))


def runtime(root_name: str = "alpha") -> dict:
    return {
        "instances": [{
            "instance_id": root_name,
            "instance_root": root_name,
            "credential_namespace": root_name.upper() + "_",
        }]
    }


def fleet_row(root_name: str = "alpha", platform: str = "facebook") -> dict:
    source = "meta_graph_api" if platform == "facebook" else "instagram_graph_api"
    ready_status = "NO_AUTHORITATIVE_PUBLICATION_CATALOG"
    return {
        "status": "FLEET_IDLE",
        "publication_blocked": False,
        "guards": {
            "zero_paid_dependency": True,
            "native_free_transport_only": True,
            "credential_values_returned": False,
        },
        "channels": [{
            "instance_id": root_name,
            "channel_id": f"{root_name}-{platform}",
            "platform": platform,
            "metric_source": source,
            "credential_env_name": f"{root_name.upper()}_{platform.upper()}_ACCESS_TOKEN",
            "access_attestation_path": f"{root_name}/social/meta_auth_state.json",
            "status": ready_status,
            "eligible": True,
            "publication_blocked": False,
        }],
    }


def write_attestation(root: Path, root_name: str = "alpha", **overrides) -> None:
    value = {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }
    value.update(overrides)
    target = root / root_name / "social/meta_auth_state.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value), encoding="utf-8")


def test_checked_in_registry_matches_current_implemented_profiles() -> None:
    result = cap.validate_registry(registry())
    assert result["status"] == "PASS", result
    assert [(row["platform"], row["metric_source"]) for row in result["capabilities"]] == [
        ("facebook", "meta_graph_api"),
        ("instagram", "instagram_graph_api"),
    ], result
    assert result["guards"]["implicit_transport_enablement_allowed"] is False


def test_implemented_profile_without_registry_entry_stays_unregistered() -> None:
    profiles = copy.deepcopy(cap.native_metrics_transport.META_PROFILES)
    profiles["youtube"] = {
        "source": "youtube_analytics_api",
        "metric_candidates": ("views",),
        "ready_key": "youtube_ready",
    }
    result = cap.validate_registry(registry(), profiles)
    assert result["status"] == "PASS", result
    assert "youtube" in result["implemented_unregistered_platforms"], result
    assert cap.capability_for_platform(result, "youtube") is None


def test_registry_cannot_claim_an_unimplemented_transport() -> None:
    value = registry()
    value["capabilities"].append({
        "capability_id": "youtube-observed-metrics-v1",
        "platform": "youtube",
        "metric_source": "youtube_analytics_api",
        "transport_module": "native_metrics_transport",
        "transport_profile": "youtube",
        "network_boundary": "native_free_api",
        "credential_ref_kind": "github-actions-secret",
        "access_ready_key": "youtube_ready",
        "metric_candidates": ["views"],
        "requires_remote_publication_proof": True,
        "observed_only": True,
        "zero_paid_dependency": True,
    })
    result = cap.validate_registry(value)
    assert result["status"] == "HOLD", result
    assert any("CAPABILITY_HAS_NO_IMPLEMENTED_TRANSPORT_PROFILE" in row["hard_blocks"] for row in result["capability_holds"])


def test_registry_cannot_change_implemented_metric_source() -> None:
    value = registry()
    value["capabilities"][0]["metric_source"] = "paid_social_analytics"
    result = cap.validate_registry(value)
    assert result["status"] == "HOLD", result
    assert "CAPABILITY_SOURCE_IMPLEMENTATION_MISMATCH" in result["capability_holds"][0]["hard_blocks"]


def test_registry_cannot_broaden_metric_candidates_silently() -> None:
    value = registry()
    value["capabilities"][1]["metric_candidates"].append("predicted_reach")
    result = cap.validate_registry(value)
    assert result["status"] == "HOLD", result
    assert "CAPABILITY_METRICS_IMPLEMENTATION_MISMATCH" in result["capability_holds"][0]["hard_blocks"]


def test_non_native_free_boundary_is_rejected() -> None:
    value = registry()
    value["capabilities"][0]["network_boundary"] = "paid_scheduler_api"
    result = cap.validate_registry(value)
    assert result["status"] == "HOLD", result
    assert "NON_NATIVE_FREE_NETWORK_BOUNDARY" in result["capability_holds"][0]["hard_blocks"]


def test_secret_material_field_is_rejected_and_value_never_returned() -> None:
    value = registry()
    value["capabilities"][0]["token_value"] = "super-secret-value"
    result = cap.validate_registry(value)
    assert result["status"] == "HOLD", result
    assert "super-secret-value" not in json.dumps(result, ensure_ascii=False)
    assert any(code.startswith("SECRET_MATERIAL_FIELD_FORBIDDEN:") for code in result["capability_holds"][0]["hard_blocks"])


def test_access_attestation_requires_valid_status_and_platform_ready() -> None:
    validation = cap.validate_registry(registry())
    capability = cap.capability_for_platform(validation, "facebook")
    assert capability
    assert cap.validate_access_attestation(capability, {"status": "VALID", "facebook_ready": True, "secret_material_persisted": False}) == []
    blocked = cap.validate_access_attestation(capability, {"status": "EXPIRED", "facebook_ready": False, "secret_material_persisted": False})
    assert "UNVERIFIED_NATIVE_METRICS_ACCESS" in blocked
    assert "NATIVE_METRICS_ACCESS_NOT_READY" in blocked


def test_gate_approves_only_registry_backed_ready_channel_before_credential_binding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_attestation(root)
        validation = cap.validate_registry(registry())
        result = gate.evaluate_capability_gate(root, runtime(), fleet_row(), validation)
        assert result["status"] == "CAPABILITY_GATE_READY", result
        assert result["approved_channels"][0]["transport_capability_id"] == "meta-facebook-observed-metrics-v1"
        assert result["approved_channels"][0]["transport_implementation_verified"] is True
        assert result["approved_channels"][0]["verified_access_attestation"] is True
        assert result["guards"]["explicit_credential_binding_still_required"] is True
        assert result["publication_blocked"] is False


def test_gate_rejects_unverified_access_before_secret_matrix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_attestation(root, status="EXPIRED", facebook_ready=False)
        result = gate.evaluate_capability_gate(
            root, runtime(), fleet_row(), cap.validate_registry(registry())
        )
        assert result["status"] == "CAPABILITY_GATE_PARTIAL_HOLD", result
        assert result["approved_channels"] == []
        blocks = result["channel_holds"][0]["hard_blocks"]
        assert "UNVERIFIED_NATIVE_METRICS_ACCESS" in blocks
        assert "NATIVE_METRICS_ACCESS_NOT_READY" in blocks


def test_gate_rejects_fleet_source_drift_even_when_platform_is_supported() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_attestation(root)
        fleet = fleet_row()
        fleet["channels"][0]["metric_source"] = "instagram_graph_api"
        result = gate.evaluate_capability_gate(root, runtime(), fleet, cap.validate_registry(registry()))
        assert result["status"] == "CAPABILITY_GATE_PARTIAL_HOLD", result
        assert "FLEET_METRIC_SOURCE_CAPABILITY_MISMATCH" in result["channel_holds"][0]["hard_blocks"]


def test_gate_rejects_runtime_hold_before_secret_binding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_attestation(root)
        fleet = fleet_row()
        fleet["channels"][0]["status"] = "HOLD_TRANSPORT"
        result = gate.evaluate_capability_gate(root, runtime(), fleet, cap.validate_registry(registry()))
        assert result["status"] == "CAPABILITY_GATE_PARTIAL_HOLD", result
        assert any(code.startswith("FLEET_CHANNEL_NOT_RUNTIME_READY:") for code in result["channel_holds"][0]["hard_blocks"])


def test_gate_rejects_access_attestation_path_outside_instance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_attestation(root)
        fleet = fleet_row()
        fleet["channels"][0]["access_attestation_path"] = "shared/meta_auth_state.json"
        result = gate.evaluate_capability_gate(root, runtime(), fleet, cap.validate_registry(registry()))
        assert "CAPABILITY_GATE_ACCESS_ATTESTATION_OUTSIDE_INSTANCE" in result["channel_holds"][0]["hard_blocks"], result


def test_real_valcea_gate_is_ready_for_facebook_and_instagram_only() -> None:
    result = gate.run_gate(
        REPO_ROOT,
        Path("local-news-os/social/social_runtime_registry.json"),
        Path("local-news-os/social/metrics_transport_capabilities.json"),
        now="2026-08-17T07:00:00Z",
    )
    assert result["status"] == "CAPABILITY_GATE_READY", result
    approved = {(row["instance_id"], row["platform"], row["metric_source"]) for row in result["approved_channels"]}
    assert approved == {
        ("valcea", "facebook", "meta_graph_api"),
        ("valcea", "instagram", "instagram_graph_api"),
    }, result
    assert result["guards"]["credential_values_read"] is False
    assert result["guards"]["zero_paid_dependency"] is True


def test_invalid_registry_is_analytics_hold_not_publication_block() -> None:
    bad = registry()
    bad["policy"]["zero_paid_dependency"] = False
    validation = cap.validate_registry(bad)
    result = gate.evaluate_capability_gate(Path("."), runtime(), fleet_row(), validation)
    assert result["status"] == "CAPABILITY_GATE_HOLD", result
    assert result["approved_channels"] == []
    assert "TRANSPORT_CAPABILITY_REGISTRY_INVALID" in result["hard_blocks"]
    assert result["publication_blocked"] is False


def run() -> None:
    tests = [
        test_checked_in_registry_matches_current_implemented_profiles,
        test_implemented_profile_without_registry_entry_stays_unregistered,
        test_registry_cannot_claim_an_unimplemented_transport,
        test_registry_cannot_change_implemented_metric_source,
        test_registry_cannot_broaden_metric_candidates_silently,
        test_non_native_free_boundary_is_rejected,
        test_secret_material_field_is_rejected_and_value_never_returned,
        test_access_attestation_requires_valid_status_and_platform_ready,
        test_gate_approves_only_registry_backed_ready_channel_before_credential_binding,
        test_gate_rejects_unverified_access_before_secret_matrix,
        test_gate_rejects_fleet_source_drift_even_when_platform_is_supported,
        test_gate_rejects_runtime_hold_before_secret_binding,
        test_gate_rejects_access_attestation_path_outside_instance,
        test_real_valcea_gate_is_ready_for_facebook_and_instagram_only,
        test_invalid_registry_is_analytics_hold_not_publication_block,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} metrics transport capability acceptance tests passed")


if __name__ == "__main__":
    run()
