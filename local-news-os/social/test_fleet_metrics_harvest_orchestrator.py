#!/usr/bin/env python3
"""Acceptance tests for fleet-level observed-metrics harvest orchestration."""
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


fleet = _load("fleet_metrics_harvest_orchestrator", "fleet_metrics_harvest_orchestrator.py")


def write_json(root: Path, relative: str, value: dict) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def channel(instance: str, platform: str) -> dict:
    source = "meta_graph_api" if platform == "facebook" else "instagram_graph_api"
    return {
        "schema_version": "1.0",
        "instance_id": instance,
        "channel_id": f"{instance}-{platform}",
        "platform": platform,
        "status": "active",
        "credentials_ref": f"github-actions-secret:{instance.upper()}_{platform.upper()}_ACCESS_TOKEN",
        "publication_state": {
            "outbox_path": f"{instance}/social/{platform}_outbox.json",
            "state_path": f"{instance}/social/{platform}_state.json",
            "dedupe_by_id": True,
            "last_known_good": True,
        },
        "metrics": {"observed_only": True, "sources": [source]},
        "zero_paid_dependency": True,
    }


def runtime(instances: tuple[str, ...] = ("alpha",)) -> dict:
    rows = []
    for instance in instances:
        rows.append({
            "instance_id": instance,
            "canonical_domain": f"{instance}.example",
            "instance_root": instance,
            "channel_registry": f"{instance}/social/channel_registry.json",
            "credential_namespace": f"{instance.upper()}_",
            "metrics_namespace": instance,
            "correction_target_namespace": f"{instance}:",
            "resource_namespaces": {
                "outbox": f"{instance}/social",
                "state": f"{instance}/social",
                "media": f"{instance}/social/media",
                "metrics": f"{instance}/social/metrics",
                "corrections": f"{instance}/social/corrections",
            },
            "metrics_harvest": {
                "access_attestations": {
                    "meta_graph_api": f"{instance}/social/meta_auth_state.json",
                    "instagram_graph_api": f"{instance}/social/meta_auth_state.json",
                }
            },
        })
    return {
        "schema_version": "1.0",
        "product": "test fleet",
        "policy": {
            "zero_paid_dependency": True,
            "cross_instance_resource_sharing_forbidden": True,
            "cross_instance_credentials_forbidden": True,
            "observed_metrics_instance_scoped": True,
            "correction_targets_instance_scoped": True,
        },
        "instances": rows,
    }


def materialize_instance(root: Path, instance: str, platforms: tuple[str, ...] = ("facebook", "instagram")) -> None:
    channels = []
    for platform in platforms:
        config = channel(instance, platform) if platform in {"facebook", "instagram"} else {
            "schema_version": "1.0",
            "instance_id": instance,
            "channel_id": f"{instance}-{platform}",
            "platform": platform,
            "status": "active",
            "publication_state": {
                "outbox_path": f"{instance}/social/{platform}_outbox.json",
                "state_path": f"{instance}/social/{platform}_state.json",
                "dedupe_by_id": True,
                "last_known_good": True,
            },
            "metrics": {"observed_only": True, "sources": []},
            "zero_paid_dependency": True,
        }
        config_path = f"{instance}/social/channels/{platform}.json"
        write_json(root, config_path, config)
        channels.append({"channel_id": platform, "config": config_path})
    write_json(root, f"{instance}/social/channel_registry.json", {
        "instance_id": instance,
        "canonical_domain": f"{instance}.example",
        "channels": channels,
    })
    write_json(root, f"{instance}/social/meta_auth_state.json", {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
        "instance_marker": instance,
    })


def isolation_pass() -> dict:
    return {"status": "PASS", "errors": [], "guards": {"zero_paid_dependency": True}}


def fake_evaluator(calls: list[tuple[str, str, str]], status: str = "NO_AUTHORITATIVE_PUBLICATION_CATALOG"):
    def evaluate(repo_root, ch, attestation, **kwargs):
        calls.append((ch["instance_id"], ch["platform"], attestation.get("instance_marker", "")))
        return {
            "instance_id": ch["instance_id"],
            "channel_id": ch["channel_id"],
            "platform": ch["platform"],
            "status": status,
            "hard_blocks": [],
            "publication_blocked": False,
            "durable_paths": [],
        }
    return evaluate


def test_discovers_supported_channels_and_skips_unsupported_without_inventing_transport() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime()
        materialize_instance(root, "alpha", ("facebook", "instagram", "youtube"))
        calls: list[tuple[str, str, str]] = []
        result = fleet.orchestrate_fleet(root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=fake_evaluator(calls))
        assert {(row[0], row[1]) for row in calls} == {("alpha", "facebook"), ("alpha", "instagram")}, calls
        assert [row["platform"] for row in result["skipped_channels"]] == ["youtube"], result
        assert result["guards"]["hardcoded_instance_or_platform_selection"] is False
        assert result["publication_blocked"] is False


def test_two_instances_are_discovered_deterministically_with_their_own_attestations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime(("beta", "alpha"))
        materialize_instance(root, "alpha")
        materialize_instance(root, "beta")
        calls: list[tuple[str, str, str]] = []
        result = fleet.orchestrate_fleet(root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=fake_evaluator(calls))
        assert calls == [
            ("alpha", "facebook", "alpha"),
            ("alpha", "instagram", "alpha"),
            ("beta", "facebook", "beta"),
            ("beta", "instagram", "beta"),
        ], calls
        assert [row["instance_id"] for row in result["instances"]] == ["alpha", "beta"]
        assert result["required_credential_env_names"] == [
            "ALPHA_FACEBOOK_ACCESS_TOKEN", "ALPHA_INSTAGRAM_ACCESS_TOKEN",
            "BETA_FACEBOOK_ACCESS_TOKEN", "BETA_INSTAGRAM_ACCESS_TOKEN",
        ]


def test_fleet_isolation_failure_stops_before_channel_evaluation_but_never_blocks_publication() -> None:
    calls: list[tuple[str, str, str]] = []
    result = fleet.orchestrate_fleet(
        Path("."), runtime(), {"status": "BLOCKED", "errors": ["INSTANCE_ROOT_COLLISION:alpha:beta"]},
        now="2026-08-17T06:00:00Z", evaluate_channel_call=fake_evaluator(calls),
    )
    assert result["status"] == "FLEET_HOLD", result
    assert calls == []
    assert result["publication_blocked"] is False
    assert "FLEET_ISOLATION_BLOCKED" in result["hard_blocks"]


def test_access_attestation_must_be_explicitly_declared() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime()
        rt["instances"][0]["metrics_harvest"]["access_attestations"].pop("meta_graph_api")
        materialize_instance(root, "alpha", ("facebook",))
        result = fleet.orchestrate_fleet(root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=fake_evaluator([]))
        assert result["channels"][0]["status"] == "HOLD_FLEET_DISCOVERY", result
        assert "METRICS_ACCESS_ATTESTATION_NOT_DECLARED" in result["channels"][0]["hard_blocks"]
        assert result["publication_blocked"] is False


def test_attestation_path_outside_instance_is_fail_closed_for_analytics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime()
        rt["instances"][0]["metrics_harvest"]["access_attestations"]["meta_graph_api"] = "shared/meta_auth.json"
        materialize_instance(root, "alpha", ("facebook",))
        write_json(root, "shared/meta_auth.json", {"status": "VALID", "facebook_ready": True, "secret_material_persisted": False})
        result = fleet.orchestrate_fleet(root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=fake_evaluator([]))
        assert "METRICS_ACCESS_ATTESTATION_OUTSIDE_INSTANCE" in result["channels"][0]["hard_blocks"], result
        assert result["publication_blocked"] is False


def test_credential_reference_must_stay_inside_instance_namespace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime()
        materialize_instance(root, "alpha", ("facebook",))
        config_path = root / "alpha/social/channels/facebook.json"
        ch = json.loads(config_path.read_text(encoding="utf-8"))
        ch["credentials_ref"] = "github-actions-secret:BETA_FACEBOOK_ACCESS_TOKEN"
        write_json(root, "alpha/social/channels/facebook.json", ch)
        result = fleet.orchestrate_fleet(root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=fake_evaluator([]))
        assert "CREDENTIAL_OUTSIDE_INSTANCE_NAMESPACE" in result["channels"][0]["hard_blocks"], result


def test_zero_paid_dependency_is_enforced_before_evaluation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime()
        materialize_instance(root, "alpha", ("facebook",))
        config_path = root / "alpha/social/channels/facebook.json"
        ch = json.loads(config_path.read_text(encoding="utf-8"))
        ch["zero_paid_dependency"] = False
        write_json(root, "alpha/social/channels/facebook.json", ch)
        calls: list[tuple[str, str, str]] = []
        result = fleet.orchestrate_fleet(root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=fake_evaluator(calls))
        assert calls == []
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["channels"][0]["hard_blocks"], result


def test_returned_runtime_path_cannot_escape_owning_instance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime()
        materialize_instance(root, "alpha", ("facebook",))
        def evaluator(repo_root, ch, attestation, **kwargs):
            return {
                "status": "HARVEST_EXECUTED", "hard_blocks": [], "publication_blocked": False,
                "durable_paths": ["other-instance/leaked.json"],
            }
        result = fleet.orchestrate_fleet(root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", execute=True, evaluate_channel_call=evaluator)
        row = result["channels"][0]
        assert row["status"] == "HOLD_FLEET_DISCOVERY", row
        assert "RETURNED_DURABLE_PATH_OUTSIDE_INSTANCE" in row["hard_blocks"]
        assert result["durable_paths"] == []


def test_execute_passes_runtime_boundaries_without_returning_secret_values() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime(("alpha", "beta"))
        materialize_instance(root, "alpha", ("facebook",))
        materialize_instance(root, "beta", ("facebook",))
        seen: list[tuple[str, str, str]] = []
        secret = "runtime-only-super-secret"
        def evaluator(repo_root, ch, attestation, **kwargs):
            resolver = kwargs.get("credential_resolver")
            resolved = resolver(ch["credentials_ref"].split(":", 1)[1]) if resolver else ""
            seen.append((ch["instance_id"], attestation["instance_marker"], resolved))
            return {"status": "HARVEST_EXECUTED", "hard_blocks": [], "publication_blocked": False, "durable_paths": []}
        result = fleet.orchestrate_fleet(
            root, rt, isolation_pass(), now="2026-08-17T06:00:00Z", execute=True,
            evaluate_channel_call=evaluator, credential_resolver=lambda name: secret,
        )
        assert seen == [("alpha", "alpha", secret), ("beta", "beta", secret)], seen
        assert secret not in json.dumps(result, ensure_ascii=False)
        assert result["guards"]["credential_values_returned"] is False


def test_output_is_deterministic_for_same_fleet_and_time() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rt = runtime(("beta", "alpha"))
        materialize_instance(root, "alpha")
        materialize_instance(root, "beta")
        def evaluator(repo_root, ch, attestation, **kwargs):
            return {"status": "NO_AUTHORITATIVE_PUBLICATION_CATALOG", "hard_blocks": [], "publication_blocked": False, "durable_paths": []}
        first = fleet.orchestrate_fleet(root, copy.deepcopy(rt), isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=evaluator)
        second = fleet.orchestrate_fleet(root, copy.deepcopy(rt), isolation_pass(), now="2026-08-17T06:00:00Z", evaluate_channel_call=evaluator)
        assert first == second


def test_real_valcea_fleet_discovers_meta_channels_without_network_or_catalog_fabrication() -> None:
    result = fleet.run_fleet(
        REPO_ROOT,
        Path("local-news-os/social/social_runtime_registry.json"),
        now="2026-08-17T06:00:00Z",
        execute=False,
    )
    eligible = {(row["instance_id"], row["platform"]) for row in result["channels"] if row.get("eligible") is True}
    assert ("valcea", "facebook") in eligible, result
    assert ("valcea", "instagram") in eligible, result
    assert result["guards"]["fleet_discovery_from_registry"] is True
    assert result["guards"]["native_free_transport_only"] is True
    assert result["publication_blocked"] is False
    assert not any(row.get("platform") in {"youtube", "linkedin", "telegram", "whatsapp"} for row in result["channels"] if row.get("eligible") is True)


def run() -> None:
    tests = [
        test_discovers_supported_channels_and_skips_unsupported_without_inventing_transport,
        test_two_instances_are_discovered_deterministically_with_their_own_attestations,
        test_fleet_isolation_failure_stops_before_channel_evaluation_but_never_blocks_publication,
        test_access_attestation_must_be_explicitly_declared,
        test_attestation_path_outside_instance_is_fail_closed_for_analytics,
        test_credential_reference_must_stay_inside_instance_namespace,
        test_zero_paid_dependency_is_enforced_before_evaluation,
        test_returned_runtime_path_cannot_escape_owning_instance,
        test_execute_passes_runtime_boundaries_without_returning_secret_values,
        test_output_is_deterministic_for_same_fleet_and_time,
        test_real_valcea_fleet_discovers_meta_channels_without_network_or_catalog_fabrication,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} fleet metrics harvest orchestrator acceptance tests passed")


if __name__ == "__main__":
    run()
