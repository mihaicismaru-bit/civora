#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS generic publishing-adapter contract."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

MODULE = Path(__file__).with_name("publishing_adapters.py")
spec = importlib.util.spec_from_file_location("publishing_adapters", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

INSTANCE_ROOT = "valcea-clar"


def channel(platform: str) -> dict:
    return {
        "schema_version": "1.0",
        "channel_id": f"valcea-{platform}",
        "instance_id": "valcea",
        "platform": platform,
        "status": "active",
        "publication_state": {
            "outbox_path": "valcea-clar/social/shared_outbox.json",
            "state_path": f"valcea-clar/social/{platform}_state.json",
            "dedupe_by_id": True,
        },
        "zero_paid_dependency": True,
    }


def direct(platform: str, *, mode: str = "native_api") -> dict:
    return {
        "channel_id": platform,
        "status": "active",
        "direct_publication_enabled": True,
        "publication_mode": mode,
        "config": f"valcea-clar/social/channels/{platform}.json",
        "adapter": f"valcea-clar/social/{platform}_publish.py",
        "outbox": "valcea-clar/social/shared_outbox.json",
        "state": f"valcea-clar/social/{platform}_state.json",
        "credentials": {
            "access_token_secret": f"VALCEA_{platform.upper()}_ACCESS_TOKEN"
        },
    }


def registry() -> tuple[dict, dict[str, dict], set[str]]:
    entries = [
        direct("facebook"),
        direct("instagram", mode="native_api_fail_closed"),
        direct("tiktok", mode="native_api_gated_by_site_consent_and_app_audit"),
        {
            "channel_id": "threads",
            "status": "blocked_until_verified_adapter_and_credentials",
            "direct_publication_enabled": False,
            "publication_mode": "durable_outbox_only",
            "adapter": None,
            "credentials": None,
        },
    ]
    value = {
        "schema_version": 2,
        "execution_owner": "civora_site_engine",
        "scheduler": "github_actions",
        "state_owner": "repository",
        "required_active_direct_channels": ["facebook", "instagram", "tiktok"],
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
        "channels": entries,
    }
    configs = {entry["config"]: channel(entry["channel_id"]) for entry in entries if entry.get("config")}
    files = set(configs)
    files.update(entry["adapter"] for entry in entries if entry.get("adapter"))
    return value, configs, files


def evaluate(value: dict, configs: dict[str, dict], files: set[str]) -> dict:
    return mod.validate_registry(
        value,
        load_channel=lambda path: copy.deepcopy(configs[path]),
        file_exists=lambda path: path in files,
        instance_root=INSTANCE_ROOT,
    )


def expect_block(mutator, code_fragment: str) -> None:
    value, configs, files = registry()
    mutator(value, configs, files)
    result = evaluate(value, configs, files)
    assert result["status"] == "BLOCKED", result
    assert any(code_fragment in error for error in result["errors"]), result


def test_reference_fixture_passes_and_preserves_independent_state() -> None:
    value, configs, files = registry()
    result = evaluate(value, configs, files)
    assert result["status"] == "PASS", result
    direct_rows = [row for row in result["dispatch"] if row["dispatch_mode"] == "DIRECT_RUNTIME_GATED"]
    assert len(direct_rows) == 3
    assert len({row["state"] for row in direct_rows}) == 3
    # A shared upstream source outbox is allowed because native platform routing lives inside it.
    assert len({row["outbox"] for row in direct_rows}) == 1
    assert all(row["credential_values_exposed"] is False for row in direct_rows)


def test_missing_adapter_fails_closed() -> None:
    expect_block(lambda value, configs, files: files.remove("valcea-clar/social/facebook_publish.py"), "ADAPTER_FILE_MISSING")


def test_adapter_path_cannot_escape_instance() -> None:
    def mutate(value, configs, files):
        value["channels"][0]["adapter"] = "../steal.py"
        files.add("../steal.py")
    expect_block(mutate, "ADAPTER_OUTSIDE_INSTANCE")


def test_channel_config_platform_must_match_registry_route() -> None:
    def mutate(value, configs, files):
        configs[value["channels"][0]["config"]]["platform"] = "instagram"
    expect_block(mutate, "CONFIG_PLATFORM_MISMATCH")


def test_instance_identity_is_required() -> None:
    def mutate(value, configs, files):
        configs[value["channels"][0]["config"]]["instance_id"] = ""
    expect_block(mutate, "CONFIG_MISSING_INSTANCE_ID")


def test_zero_paid_dependency_is_mandatory_per_active_publication() -> None:
    def mutate(value, configs, files):
        configs[value["channels"][1]["config"]]["zero_paid_dependency"] = False
    expect_block(mutate, "ZERO_PAID_DEPENDENCY_REQUIRED")


def test_state_paths_cannot_collide_between_publications() -> None:
    def mutate(value, configs, files):
        value["channels"][1]["state"] = value["channels"][0]["state"]
        configs[value["channels"][1]["config"]]["publication_state"]["state_path"] = value["channels"][0]["state"]
    expect_block(mutate, "STATE_COLLISION")


def test_registry_and_channel_config_state_must_agree() -> None:
    def mutate(value, configs, files):
        configs[value["channels"][0]["config"]]["publication_state"]["state_path"] = "valcea-clar/social/other.json"
    expect_block(mutate, "STATE_PATH_MISMATCH")


def test_direct_channel_requires_dedupe() -> None:
    def mutate(value, configs, files):
        configs[value["channels"][0]["config"]]["publication_state"]["dedupe_by_id"] = False
    expect_block(mutate, "DEDUPE_NOT_ENABLED")


def test_unverified_channel_cannot_smuggle_adapter() -> None:
    def mutate(value, configs, files):
        value["channels"][3]["adapter"] = "valcea-clar/social/threads_publish.py"
        files.add("valcea-clar/social/threads_publish.py")
    expect_block(mutate, "UNVERIFIED_CHANNEL_HAS_ADAPTER")


def test_unverified_channel_must_remain_durable_outbox_only() -> None:
    def mutate(value, configs, files):
        value["channels"][3]["publication_mode"] = "native_api"
    expect_block(mutate, "DISABLED_CHANNEL_MUST_BE_OUTBOX_ONLY")


def test_required_active_direct_channels_are_enforced() -> None:
    def mutate(value, configs, files):
        value["channels"][2]["direct_publication_enabled"] = False
        value["channels"][2]["publication_mode"] = "durable_outbox_only"
        value["channels"][2]["adapter"] = None
        value["channels"][2]["credentials"] = None
    expect_block(mutate, "REQUIRED_DIRECT_CHANNELS_MISSING:tiktok")


def test_direct_channel_requires_reference_names_not_secret_values() -> None:
    def mutate(value, configs, files):
        value["channels"][0]["credentials"]["access_token_secret"] = "EAA-this-is-a-token-value-not-a-secret-name"
    expect_block(mutate, "CREDENTIAL_REFERENCE_NOT_NAME")


def test_paid_scheduler_policy_is_rejected() -> None:
    def mutate(value, configs, files):
        value["policy"]["paid_social_scheduler_required"] = True
    expect_block(mutate, "POLICY_MUST_BE_FALSE:paid_social_scheduler_required")


def test_cross_post_verbatim_policy_cannot_be_weakened() -> None:
    def mutate(value, configs, files):
        value["policy"]["cross_post_verbatim_forbidden"] = False
    expect_block(mutate, "POLICY_MUST_BE_TRUE:cross_post_verbatim_forbidden")


def test_runtime_gate_reports_only_missing_reference_names() -> None:
    value, _, _ = registry()
    entry = value["channels"][0]
    decision = mod.runtime_gate(entry, set())
    assert decision == {
        "channel_id": "facebook",
        "decision": "BLOCKED_MISSING_CREDENTIALS",
        "missing_references": ["VALCEA_FACEBOOK_ACCESS_TOKEN"],
    }


def test_runtime_gate_allows_only_when_declared_refs_are_present() -> None:
    value, _, _ = registry()
    entry = value["channels"][1]
    decision = mod.runtime_gate(entry, {"VALCEA_INSTAGRAM_ACCESS_TOKEN"})
    assert decision["decision"] == "DIRECT_READY"
    assert decision["missing_references"] == []


def test_outbox_only_runtime_gate_never_requests_credentials() -> None:
    value, _, _ = registry()
    decision = mod.runtime_gate(value["channels"][3], set())
    assert decision == {"channel_id": "threads", "decision": "OUTBOX_ONLY", "missing_references": []}


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Publishing Adapter Contract acceptance tests: PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
