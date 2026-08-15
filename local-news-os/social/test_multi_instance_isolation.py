#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS multi-instance social runtime isolation."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).with_name("multi_instance_isolation.py")
spec = importlib.util.spec_from_file_location("multi_instance_isolation", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def channel(instance_id: str, platform: str, root: str) -> dict:
    return {
        "schema_version": "1.0",
        "channel_id": f"{instance_id}-{platform}",
        "instance_id": instance_id,
        "platform": platform,
        "status": "active",
        "publication_state": {
            "outbox_path": f"{root}/social/shared_outbox.json",
            "state_path": f"{root}/social/{platform}_state.json",
            "dedupe_by_id": True,
        },
        "zero_paid_dependency": True,
    }


def direct(instance_id: str, platform: str, root: str, credential_prefix: str) -> dict:
    return {
        "channel_id": platform,
        "status": "active",
        "direct_publication_enabled": True,
        "publication_mode": "native_api",
        "config": f"{root}/social/channels/{platform}.json",
        "adapter": f"{root}/social/{platform}_publish.py",
        "outbox": f"{root}/social/shared_outbox.json",
        "state": f"{root}/social/{platform}_state.json",
        "credentials": {
            "access_token_secret": f"{credential_prefix}{platform.upper()}_ACCESS_TOKEN",
        },
    }


def adapter_registry(instance_id: str, domain: str, root: str, credential_prefix: str) -> dict:
    return {
        "schema_version": 2,
        "instance_id": instance_id,
        "canonical_domain": domain,
        "execution_owner": "civora_site_engine",
        "scheduler": "github_actions",
        "state_owner": "repository",
        "required_active_direct_channels": ["facebook"],
        "policy": {
            "verified_fact_kernel_required": True,
            "channel_native_copy_required": True,
            "cross_post_verbatim_forbidden": True,
            "idempotency_required": True,
            "deduplication_required": True,
            "correction_propagation_required": True,
            "paid_social_scheduler_required": False,
            "paid_llm_api_required": False,
            "fail_closed_on_missing_credentials": True,
            "fail_closed_on_missing_adapter": True,
        },
        "channels": [direct(instance_id, "facebook", root, credential_prefix)],
    }


def runtime_entry(instance_id: str, domain: str, root: str, credential_prefix: str) -> dict:
    return {
        "instance_id": instance_id,
        "canonical_domain": domain,
        "instance_root": root,
        "channel_registry": f"{root}/social/channel_registry.json",
        "credential_namespace": credential_prefix,
        "metrics_namespace": instance_id,
        "correction_target_namespace": f"{instance_id}:",
        "resource_namespaces": {
            "outbox": f"{root}/social",
            "state": f"{root}/social",
            "media": f"{root}/social/photos",
            "metrics": f"{root}/social/metrics",
            "corrections": f"{root}/social/corrections",
        },
    }


def fixture() -> tuple[dict, dict[str, dict], set[str]]:
    instances = [
        ("valcea", "valceaclar.ro", "sites/valcea", "VALCEA_"),
        ("alba", "albaclar.ro", "sites/alba", "ALBA_"),
    ]
    runtime = {
        "schema_version": "1.0",
        "policy": {
            "zero_paid_dependency": True,
            "cross_instance_resource_sharing_forbidden": True,
            "cross_instance_credentials_forbidden": True,
            "observed_metrics_instance_scoped": True,
            "correction_targets_instance_scoped": True,
        },
        "instances": [
            runtime_entry(instance_id, domain, root, prefix)
            for instance_id, domain, root, prefix in instances
        ],
    }

    store: dict[str, dict] = {}
    files: set[str] = set()
    for instance_id, domain, root, prefix in instances:
        registry_path = f"{root}/social/channel_registry.json"
        config_path = f"{root}/social/channels/facebook.json"
        adapter_path = f"{root}/social/facebook_publish.py"
        store[registry_path] = adapter_registry(instance_id, domain, root, prefix)
        store[config_path] = channel(instance_id, "facebook", root)
        files.update({registry_path, config_path, adapter_path})
    return runtime, store, files


def evaluate(runtime: dict, store: dict[str, dict], files: set[str]) -> dict:
    return mod.validate_runtime(
        copy.deepcopy(runtime),
        load_json=lambda path: copy.deepcopy(store[path]),
        file_exists=lambda path: path in files,
    )


def expect_block(mutator, code_fragment: str) -> dict:
    runtime, store, files = fixture()
    mutator(runtime, store, files)
    result = evaluate(runtime, store, files)
    assert result["status"] == "BLOCKED", result
    assert any(code_fragment in error for error in result["errors"]), result
    return result


def second(runtime: dict) -> dict:
    return runtime["instances"][1]


def test_two_independent_instances_pass() -> None:
    runtime, store, files = fixture()
    result = evaluate(runtime, store, files)
    assert result["status"] == "PASS", result
    assert [item["instance_id"] for item in result["instances"]] == ["alba", "valcea"]
    assert all(item["credential_values_exposed"] is False for item in result["instances"])
    assert len({item["isolation_key"] for item in result["instances"]}) == 2
    assert result["guards"]["zero_paid_dependency"] is True


def test_duplicate_instance_id_fails_closed() -> None:
    expect_block(lambda runtime, store, files: second(runtime).__setitem__("instance_id", "valcea"), "DUPLICATE_INSTANCE_ID:valcea")


def test_instance_roots_cannot_overlap() -> None:
    expect_block(lambda runtime, store, files: second(runtime).__setitem__("instance_root", "sites/valcea/child"), "INSTANCE_ROOT_COLLISION")


def test_channel_registry_must_stay_inside_instance_root() -> None:
    expect_block(lambda runtime, store, files: second(runtime).__setitem__("channel_registry", "sites/valcea/social/channel_registry.json"), "CHANNEL_REGISTRY_OUTSIDE_INSTANCE")


def test_registry_instance_identity_must_match_runtime() -> None:
    def mutate(runtime, store, files):
        store["sites/alba/social/channel_registry.json"]["instance_id"] = "valcea"
    expect_block(mutate, "REGISTRY_INSTANCE_MISMATCH")


def test_registry_domain_identity_must_match_runtime() -> None:
    def mutate(runtime, store, files):
        store["sites/alba/social/channel_registry.json"]["canonical_domain"] = "other.example"
    expect_block(mutate, "REGISTRY_DOMAIN_MISMATCH")


def test_channel_config_instance_mismatch_bubbles_up() -> None:
    def mutate(runtime, store, files):
        store["sites/alba/social/channels/facebook.json"]["instance_id"] = "valcea"
    expect_block(mutate, "CHANNEL_INSTANCE_MISMATCH:facebook")


def test_resource_namespaces_must_stay_inside_instance_root() -> None:
    def mutate(runtime, store, files):
        second(runtime)["resource_namespaces"]["media"] = "sites/valcea/social/photos"
    expect_block(mutate, "MEDIA_NAMESPACE_OUTSIDE_INSTANCE")


def test_outbox_must_stay_inside_declared_namespace() -> None:
    def mutate(runtime, store, files):
        path = "sites/alba/private/outbox.json"
        store["sites/alba/social/channel_registry.json"]["channels"][0]["outbox"] = path
        store["sites/alba/social/channels/facebook.json"]["publication_state"]["outbox_path"] = path
    expect_block(mutate, "OUTBOX_OUTSIDE_DECLARED_NAMESPACE")


def test_state_must_stay_inside_declared_namespace() -> None:
    def mutate(runtime, store, files):
        path = "sites/alba/private/state.json"
        store["sites/alba/social/channel_registry.json"]["channels"][0]["state"] = path
        store["sites/alba/social/channels/facebook.json"]["publication_state"]["state_path"] = path
    expect_block(mutate, "STATE_OUTSIDE_DECLARED_NAMESPACE")


def test_cross_instance_outbox_collision_is_explicitly_blocked() -> None:
    def mutate(runtime, store, files):
        entry = second(runtime)
        entry["instance_root"] = "sites"
        entry["resource_namespaces"]["outbox"] = "sites/valcea/social"
        path = "sites/valcea/social/shared_outbox.json"
        store["sites/alba/social/channel_registry.json"]["channels"][0]["outbox"] = path
        store["sites/alba/social/channels/facebook.json"]["publication_state"]["outbox_path"] = path
    expect_block(mutate, "CROSS_INSTANCE_OUTBOX_COLLISION")


def test_cross_instance_state_collision_is_explicitly_blocked() -> None:
    def mutate(runtime, store, files):
        entry = second(runtime)
        entry["instance_root"] = "sites"
        entry["resource_namespaces"]["state"] = "sites/valcea/social"
        path = "sites/valcea/social/facebook_state.json"
        store["sites/alba/social/channel_registry.json"]["channels"][0]["state"] = path
        store["sites/alba/social/channels/facebook.json"]["publication_state"]["state_path"] = path
    expect_block(mutate, "CROSS_INSTANCE_STATE_COLLISION")


def test_credential_reference_reuse_across_instances_is_blocked() -> None:
    def mutate(runtime, store, files):
        store["sites/alba/social/channel_registry.json"]["channels"][0]["credentials"]["access_token_secret"] = "VALCEA_FACEBOOK_ACCESS_TOKEN"
    expect_block(mutate, "CROSS_INSTANCE_CREDENTIAL_REFERENCE")


def test_credential_reference_must_match_instance_namespace() -> None:
    def mutate(runtime, store, files):
        store["sites/alba/social/channel_registry.json"]["channels"][0]["credentials"]["access_token_secret"] = "OTHER_FACEBOOK_ACCESS_TOKEN"
    expect_block(mutate, "CREDENTIAL_OUTSIDE_NAMESPACE")


def test_credential_namespaces_cannot_overlap() -> None:
    def mutate(runtime, store, files):
        second(runtime)["credential_namespace"] = "VALCEA_"
        store["sites/alba/social/channel_registry.json"]["channels"][0]["credentials"]["access_token_secret"] = "VALCEA_ALBA_FACEBOOK_ACCESS_TOKEN"
    expect_block(mutate, "CREDENTIAL_NAMESPACE_OVERLAP")


def test_media_namespaces_cannot_overlap_across_instances() -> None:
    def mutate(runtime, store, files):
        entry = second(runtime)
        entry["instance_root"] = "sites"
        entry["resource_namespaces"]["media"] = "sites/valcea/social/photos"
    expect_block(mutate, "CROSS_INSTANCE_MEDIA_NAMESPACE_OVERLAP")


def test_metrics_logical_namespace_is_unique_per_instance() -> None:
    expect_block(lambda runtime, store, files: second(runtime).__setitem__("metrics_namespace", "valcea"), "METRICS_NAMESPACE_COLLISION")


def test_correction_target_namespace_is_unique_per_instance() -> None:
    expect_block(lambda runtime, store, files: second(runtime).__setitem__("correction_target_namespace", "valcea:"), "CORRECTION_TARGET_NAMESPACE_COLLISION")


def test_canonical_domain_cannot_be_shared_by_instances() -> None:
    def mutate(runtime, store, files):
        second(runtime)["canonical_domain"] = "valceaclar.ro"
        store["sites/alba/social/channel_registry.json"]["canonical_domain"] = "valceaclar.ro"
    expect_block(mutate, "CANONICAL_DOMAIN_COLLISION")


def test_zero_paid_dependency_is_mandatory_at_runtime_level() -> None:
    def mutate(runtime, store, files):
        runtime["policy"]["zero_paid_dependency"] = False
    expect_block(mutate, "POLICY_MUST_BE_TRUE:zero_paid_dependency")


def test_path_traversal_is_rejected() -> None:
    def mutate(runtime, store, files):
        second(runtime)["resource_namespaces"]["metrics"] = "../shared/metrics"
    expect_block(mutate, "INVALID_METRICS_NAMESPACE")


def test_per_instance_adapter_contract_failure_fails_the_fleet() -> None:
    def mutate(runtime, store, files):
        store["sites/alba/social/channel_registry.json"]["policy"]["paid_social_scheduler_required"] = True
    expect_block(mutate, "ADAPTER_CONTRACT:POLICY_MUST_BE_FALSE:paid_social_scheduler_required")


def test_secret_like_values_never_appear_in_report() -> None:
    fake_secret = "EAA-fake-secret-value-for-test"
    def mutate(runtime, store, files):
        store["sites/alba/social/channel_registry.json"]["channels"][0]["credentials"]["access_token_secret"] = fake_secret
    result = expect_block(mutate, "CREDENTIAL_REFERENCE_NOT_NAME")
    assert fake_secret not in json.dumps(result, ensure_ascii=False)


def test_result_is_deterministic() -> None:
    runtime, store, files = fixture()
    first = evaluate(runtime, store, files)
    runtime["instances"].reverse()
    second_result = evaluate(runtime, store, files)
    assert first == second_result


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Multi-Instance Isolation acceptance tests: PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
