#!/usr/bin/env python3
"""Acceptance tests for fail-closed correction dispatch routing."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import correction_dispatch_router as router


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def action(platform: str, channel_id: str, kind: str = "CORRECT_PUBLISHED_NATIVE") -> dict:
    return {
        "action_id": f"action:{platform}",
        "action": kind,
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "affected_story_id": "story-1",
        "affected_publication_id": f"publication:{platform}:1",
        "remote_publication_id": f"remote-{platform}" if kind == "CORRECT_PUBLISHED_NATIVE" else None,
        "correction_story_id": "correction-1",
        "native_regeneration": {
            "required": True,
            "source": "VERIFIED_FACT_KERNEL",
            "fact_kernel_sha256": sha("corrected fact kernel"),
            "reuse_prior_copy": False,
            "verbatim_cross_platform_reuse_allowed": False,
        },
        "guards": {
            "editorial_gates_weakened": False,
            "prior_copy_reused": False,
            "analytics_used": False,
            "zero_paid_dependency": True,
        },
    }


def propagation(actions: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "blocked": False,
        "instance_id": "valcea",
        "correction_story_id": "correction-1",
        "propagation_fingerprint_sha256": sha("propagation"),
        "actions": actions,
        "guards": {"zero_paid_dependency": True},
    }


def registry() -> dict:
    return {
        "instance_id": "valcea",
        "policy": {
            "correction_propagation_required": True,
            "paid_social_scheduler_required": False,
            "paid_llm_api_required": False,
        },
        "channels": [
            {
                "channel_id": "facebook",
                "status": "active",
                "direct_publication_enabled": True,
                "publication_mode": "native_api",
                "adapter": "valcea-clar/social/facebook_editorial_publish.py",
                "outbox": "valcea-clar/social/facebook_outbox.json",
            },
            {
                "channel_id": "instagram",
                "status": "active",
                "direct_publication_enabled": True,
                "publication_mode": "native_api",
                "adapter": "valcea-clar/social/instagram_editorial_publish.py",
                "outbox": "valcea-clar/social/facebook_outbox.json",
            },
            {
                "channel_id": "linkedin",
                "status": "outbox_only",
                "direct_publication_enabled": False,
                "publication_mode": "durable_outbox_only",
                "adapter": None,
                "outbox": "valcea-clar/social/linkedin_outbox.json",
            },
        ],
    }


def capabilities() -> dict:
    correction = {
        "remote_edit_supported": False,
        "remote_edit_verified": False,
        "native_correction_direct_publish_supported": False,
        "durable_native_correction_outbox_supported": True,
        "requires_regenerated_native_product": True,
    }
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "policy": {
            "credential_values_allowed": False,
            "zero_paid_dependency": True,
        },
        "adapters": [
            {
                "platform": "facebook",
                "channel_id": "valcea-facebook",
                "adapter": "valcea-clar/social/facebook_editorial_publish.py",
                "correction_capabilities": copy.deepcopy(correction),
            },
            {
                "platform": "instagram",
                "channel_id": "valcea-instagram",
                "adapter": "valcea-clar/social/instagram_editorial_publish.py",
                "correction_capabilities": copy.deepcopy(correction),
            },
        ],
    }


def test_published_direct_channel_falls_back_to_durable_native_correction_outbox() -> None:
    result = router.build_correction_dispatch_plan(
        propagation([action("facebook", "valcea-facebook")]), registry(), capabilities()
    )
    assert result["status"] == "PASS", result
    route = result["routes"][0]
    assert route["decision"] == "MATERIALIZE_NATIVE_CORRECTION_OUTBOX"
    assert route["dispatchable"] is False
    assert route["remote_edit_claimed"] is False
    assert route["reuse_prior_copy"] is False


def test_outbox_only_sister_publication_stays_outbox_only() -> None:
    result = router.build_correction_dispatch_plan(
        propagation([action("linkedin", "valcea-linkedin")]), registry(), capabilities()
    )
    assert result["status"] == "PASS", result
    route = result["routes"][0]
    assert route["decision"] == "MATERIALIZE_NATIVE_CORRECTION_OUTBOX"
    assert route["publication_mode"] == "durable_outbox_only"
    assert route["adapter"] is None


def test_unpublished_supersede_is_state_only_and_never_network_dispatchable() -> None:
    item = action("facebook", "valcea-facebook", "SUPERSEDE_UNPUBLISHED")
    result = router.build_correction_dispatch_plan(propagation([item]), registry(), capabilities())
    assert result["status"] == "PASS", result
    route = result["routes"][0]
    assert route["decision"] == "STATE_ONLY_SUPERSEDE"
    assert route["dispatchable"] is False
    assert route["network_dispatch_performed"] is False


def test_inflight_correction_requires_reconciliation_before_delivery() -> None:
    item = action("facebook", "valcea-facebook", "RECONCILE_IN_FLIGHT")
    result = router.build_correction_dispatch_plan(propagation([item]), registry(), capabilities())
    assert result["routes"][0]["decision"] == "RECONCILE_BEFORE_CORRECTION"
    assert result["routes"][0]["dispatchable"] is False


def test_missing_direct_correction_capability_fails_closed_globally() -> None:
    caps = capabilities()
    caps["adapters"] = [row for row in caps["adapters"] if row["platform"] != "facebook"]
    result = router.build_correction_dispatch_plan(
        propagation([action("facebook", "valcea-facebook")]), registry(), caps
    )
    assert result["status"] == "BLOCKED"
    assert "facebook:DIRECT_CORRECTION_CAPABILITY_MISSING" in result["hard_blocks"]


def test_remote_edit_requires_explicit_verified_capability() -> None:
    caps = capabilities()
    contract = caps["adapters"][0]["correction_capabilities"]
    contract["remote_edit_supported"] = True
    contract["remote_edit_verified"] = False
    report = router.validate_correction_capability_registry(registry(), caps)
    assert report["status"] == "BLOCKED"
    assert "facebook:REMOTE_EDIT_SUPPORT_REQUIRES_VERIFIED_PROOF" in report["errors"]


def test_explicit_verified_remote_edit_can_route_but_router_still_does_no_network_io() -> None:
    caps = capabilities()
    contract = caps["adapters"][0]["correction_capabilities"]
    contract["remote_edit_supported"] = True
    contract["remote_edit_verified"] = True
    result = router.build_correction_dispatch_plan(
        propagation([action("facebook", "valcea-facebook")]), registry(), caps
    )
    route = result["routes"][0]
    assert route["decision"] == "EDIT_REMOTE_PUBLICATION"
    assert route["dispatchable"] is True
    assert route["network_dispatch_performed"] is False


def test_prior_copy_reuse_tamper_is_held_per_action() -> None:
    item = action("facebook", "valcea-facebook")
    item["native_regeneration"]["reuse_prior_copy"] = True
    result = router.build_correction_dispatch_plan(propagation([item]), registry(), capabilities())
    assert result["status"] == "BLOCKED"
    assert result["routes"] == []
    assert "CORRECTION_PRIOR_COPY_REUSE_FORBIDDEN" in result["holds"][0]["reasons"]


def test_cross_instance_registry_is_blocked_before_any_route() -> None:
    reg = registry()
    reg["instance_id"] = "cluj"
    result = router.build_correction_dispatch_plan(
        propagation([action("facebook", "valcea-facebook")]), reg, capabilities()
    )
    assert result["status"] == "BLOCKED"
    assert "CORRECTION_REGISTRY_INSTANCE_MISMATCH" in result["hard_blocks"]
    assert result["routes"] == []


def test_channel_routes_are_distinct_and_copy_free() -> None:
    result = router.build_correction_dispatch_plan(
        propagation([
            action("facebook", "valcea-facebook"),
            action("instagram", "valcea-instagram"),
            action("linkedin", "valcea-linkedin"),
        ]),
        registry(),
        capabilities(),
    )
    assert result["status"] == "PASS", result
    assert len(result["routes"]) == 3
    assert len({row["route_id"] for row in result["routes"]}) == 3
    assert all(row["reuse_prior_copy"] is False for row in result["routes"])
    assert all("text" not in row and "caption" not in row and "message" not in row for row in result["routes"])


def test_valcea_required_direct_channels_have_explicit_safe_correction_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    reg = json.loads((repo_root / "valcea-clar/social/channel_registry.json").read_text(encoding="utf-8"))
    caps = json.loads((repo_root / "valcea-clar/social/adapter_capabilities.json").read_text(encoding="utf-8"))
    report = router.validate_correction_capability_registry(reg, caps)
    assert report["status"] == "PASS", report
    assert set(report["direct_platforms"]) == {"facebook", "instagram", "threads", "tiktok"}
    for row in caps["adapters"]:
        contract = row["correction_capabilities"]
        assert contract["remote_edit_supported"] is False
        assert contract["remote_edit_verified"] is False
        assert contract["native_correction_direct_publish_supported"] is False
        assert contract["durable_native_correction_outbox_supported"] is True
        assert contract["requires_regenerated_native_product"] is True


def test_guards_remain_secret_free_network_free_and_zero_paid() -> None:
    result = router.build_correction_dispatch_plan(
        propagation([action("facebook", "valcea-facebook")]), registry(), capabilities()
    )
    guards = result["guards"]
    assert guards == {
        "network_calls_performed": False,
        "credential_values_read": False,
        "credential_values_exposed": False,
        "prior_social_copy_reused": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "remote_edit_requires_explicit_verified_capability": True,
        "unverified_direct_correction_falls_back_to_durable_outbox": True,
        "zero_paid_dependency": True,
    }


def main() -> int:
    tests = [
        test_published_direct_channel_falls_back_to_durable_native_correction_outbox,
        test_outbox_only_sister_publication_stays_outbox_only,
        test_unpublished_supersede_is_state_only_and_never_network_dispatchable,
        test_inflight_correction_requires_reconciliation_before_delivery,
        test_missing_direct_correction_capability_fails_closed_globally,
        test_remote_edit_requires_explicit_verified_capability,
        test_explicit_verified_remote_edit_can_route_but_router_still_does_no_network_io,
        test_prior_copy_reuse_tamper_is_held_per_action,
        test_cross_instance_registry_is_blocked_before_any_route,
        test_channel_routes_are_distinct_and_copy_free,
        test_valcea_required_direct_channels_have_explicit_safe_correction_contract,
        test_guards_remain_secret_free_network_free_and_zero_paid,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Correction Dispatch Router acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
