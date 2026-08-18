#!/usr/bin/env python3
"""Acceptance tests for durable native correction outbox materialization."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

import correction_outbox_materializer as materializer


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def route(
    channel: str = "facebook",
    *,
    platform: str | None = None,
    story: str = "correction-1",
    publication: str = "publication-1",
    remote: str = "remote-1",
    outbox: str = "valcea-clar/social/facebook_outbox.json",
    decision: str = "MATERIALIZE_NATIVE_CORRECTION_OUTBOX",
) -> dict:
    platform = platform or channel
    return {
        "route_id": f"route:{channel}:{story}:{publication}",
        "action_id": f"action:{channel}:{story}:{publication}",
        "decision": decision,
        "instance_id": "valcea",
        "channel_id": channel,
        "platform": platform,
        "correction_story_id": story,
        "affected_story_id": "story-1",
        "affected_publication_id": publication,
        "remote_publication_id": remote,
        "adapter": None,
        "outbox": outbox,
        "fact_kernel_sha256": sha("corrected fact kernel"),
        "native_regeneration_required": True,
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "network_dispatch_performed": False,
        "credential_values_read": False,
        "zero_paid_dependency": True,
        "dispatchable": False,
    }


def plan(routes: list[dict], *, fingerprint_seed: str = "plan") -> dict:
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "blocked": False,
        "instance_id": "valcea",
        "dispatch_plan_fingerprint_sha256": sha(fingerprint_seed),
        "routes": routes,
        "holds": [],
        "guards": {
            "network_calls_performed": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "prior_social_copy_reused": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    }


def test_materializes_channel_local_sidecar_without_overwriting_normal_outbox() -> None:
    result = materializer.materialize_native_correction_outboxes(plan([route()]))
    assert result["status"] == "PASS", result
    assert result["materialized_outbox_count"] == 1
    outbox = result["outboxes"][0]
    assert outbox["path"] == "valcea-clar/social/corrections/facebook.json"
    document = outbox["document"]
    assert document["declared_publication_outbox"] == "valcea-clar/social/facebook_outbox.json"
    assert document["guards"]["normal_publication_outbox_overwritten"] is False
    assert document["items"][0]["status"] == "READY_FOR_NATIVE_REGENERATION"
    assert document["items"][0]["dispatch"]["network_dispatch_allowed"] is False


def test_shared_normal_publication_outbox_still_yields_isolated_channel_correction_state() -> None:
    result = materializer.materialize_native_correction_outboxes(plan([
        route("facebook"),
        route(
            "instagram",
            publication="publication-ig",
            remote="remote-ig",
            outbox="valcea-clar/social/facebook_outbox.json",
        ),
        route(
            "tiktok",
            publication="publication-tt",
            remote="remote-tt",
            outbox="valcea-clar/social/facebook_outbox.json",
        ),
    ]))
    assert result["status"] == "PASS", result
    assert [row["path"] for row in result["outboxes"]] == [
        "valcea-clar/social/corrections/facebook.json",
        "valcea-clar/social/corrections/instagram.json",
        "valcea-clar/social/corrections/tiktok.json",
    ]


def test_multiple_corrections_for_same_channel_are_merged_deterministically() -> None:
    result = materializer.materialize_native_correction_outboxes(plan([
        route("facebook", story="correction-1", publication="publication-1", remote="remote-1"),
        route("facebook", story="correction-2", publication="publication-2", remote="remote-2"),
    ]))
    assert result["status"] == "PASS", result
    assert result["materialized_outbox_count"] == 1
    items = result["outboxes"][0]["document"]["items"]
    assert [row["correction_story_id"] for row in items] == ["correction-1", "correction-2"]
    assert len({row["item_id"] for row in items}) == 2


def test_repeat_materialization_is_idempotent_and_dedupe_safe() -> None:
    first = materializer.materialize_native_correction_outboxes(plan([route()]))
    existing = {row["path"]: row["document"] for row in first["outboxes"]}
    second = materializer.materialize_native_correction_outboxes(plan([route()]), existing)
    assert second["status"] == "PASS", second
    assert second["changed_outbox_count"] == 0
    assert second["outboxes"][0]["document"] == first["outboxes"][0]["document"]


def test_tampered_existing_durable_state_fails_closed() -> None:
    first = materializer.materialize_native_correction_outboxes(plan([route()]))
    existing = {row["path"]: copy.deepcopy(row["document"]) for row in first["outboxes"]}
    path = first["outboxes"][0]["path"]
    existing[path]["items"][0]["remote_publication_id"] = "tampered"
    result = materializer.materialize_native_correction_outboxes(plan([route()]), existing)
    assert result["status"] == "BLOCKED", result
    assert "EXISTING_CORRECTION_OUTBOX_FINGERPRINT_INVALID" in result["holds"][0]["reasons"]


def test_cross_instance_route_is_held_without_partial_state_write() -> None:
    item = route()
    item["instance_id"] = "cluj"
    result = materializer.materialize_native_correction_outboxes(plan([item]))
    assert result["status"] == "BLOCKED", result
    assert result["outboxes"] == []
    assert "CORRECTION_ROUTE_INSTANCE_MISMATCH" in result["holds"][0]["reasons"]


def test_copy_or_secret_fields_are_never_materialized() -> None:
    with_copy = route()
    with_copy["caption"] = "reuse this old caption"
    result = materializer.materialize_native_correction_outboxes(plan([with_copy]))
    assert result["status"] == "BLOCKED", result
    assert "CORRECTION_ROUTE_CONTAINS_EDITORIAL_COPY" in result["holds"][0]["reasons"]

    with_secret = route()
    with_secret["access_token"] = "never-store-me"
    result = materializer.materialize_native_correction_outboxes(plan([with_secret]))
    assert result["status"] == "BLOCKED", result
    assert "CORRECTION_DISPATCH_PLAN_CONTAINS_SECRET_FIELD" in result["hard_blocks"]


def test_non_materialization_routes_are_not_promoted_into_correction_outboxes() -> None:
    item = route(decision="STATE_ONLY_SUPERSEDE")
    result = materializer.materialize_native_correction_outboxes(plan([item]))
    assert result["status"] == "PASS", result
    assert result["outboxes"] == []
    assert result["skipped_non_materialization_route_count"] == 1


def test_path_traversal_and_absolute_outbox_paths_fail_closed() -> None:
    traversal = route(outbox="../escape.json")
    result = materializer.materialize_native_correction_outboxes(plan([traversal]))
    assert result["status"] == "BLOCKED", result
    assert "CORRECTION_DECLARED_OUTBOX_PATH_INVALID" in result["holds"][0]["reasons"]

    absolute = route(outbox="/tmp/escape.json")
    result = materializer.materialize_native_correction_outboxes(plan([absolute]))
    assert result["status"] == "BLOCKED", result
    assert "CORRECTION_DECLARED_OUTBOX_PATH_INVALID" in result["holds"][0]["reasons"]


def test_atomic_persistence_readback_writes_only_correction_sidecars() -> None:
    result = materializer.materialize_native_correction_outboxes(plan([
        route("facebook"),
        route(
            "instagram",
            publication="publication-ig",
            remote="remote-ig",
            outbox="valcea-clar/social/facebook_outbox.json",
        ),
    ]))
    with tempfile.TemporaryDirectory() as td:
        receipt = materializer.persist_materialized_outboxes(result, td)
        assert receipt["status"] == "PASS", receipt
        assert receipt["persisted_count"] == 2
        root = Path(td)
        assert not (root / "valcea-clar/social/facebook_outbox.json").exists()
        for row in result["outboxes"]:
            persisted = root / row["path"]
            assert persisted.exists()
            assert json.loads(persisted.read_text(encoding="utf-8")) == row["document"]


def test_blocked_materialization_can_never_be_persisted() -> None:
    blocked = materializer.materialize_native_correction_outboxes(plan([route(outbox="../escape.json")]))
    with tempfile.TemporaryDirectory() as td:
        try:
            materializer.persist_materialized_outboxes(blocked, td)
        except ValueError as exc:
            assert "MUST_NOT_PERSIST" in str(exc)
        else:
            raise AssertionError("blocked correction materialization unexpectedly persisted")


def test_guards_remain_network_free_copy_free_and_zero_paid() -> None:
    result = materializer.materialize_native_correction_outboxes(plan([route()]))
    assert result["guards"] == {
        "channel_local_state": True,
        "network_calls_performed": False,
        "credential_values_read": False,
        "editorial_copy_materialized": False,
        "normal_publication_outbox_overwritten": False,
        "zero_paid_dependency": True,
    }
    item = result["outboxes"][0]["document"]["items"][0]
    serialized = json.dumps(item, ensure_ascii=False).lower()
    assert "reuse this old caption" not in serialized
    assert item["native_regeneration"]["source"] == "VERIFIED_CORRECTED_FACT_KERNEL"
    assert item["native_regeneration"]["reuse_prior_copy"] is False


def main() -> int:
    tests = [
        test_materializes_channel_local_sidecar_without_overwriting_normal_outbox,
        test_shared_normal_publication_outbox_still_yields_isolated_channel_correction_state,
        test_multiple_corrections_for_same_channel_are_merged_deterministically,
        test_repeat_materialization_is_idempotent_and_dedupe_safe,
        test_tampered_existing_durable_state_fails_closed,
        test_cross_instance_route_is_held_without_partial_state_write,
        test_copy_or_secret_fields_are_never_materialized,
        test_non_materialization_routes_are_not_promoted_into_correction_outboxes,
        test_path_traversal_and_absolute_outbox_paths_fail_closed,
        test_atomic_persistence_readback_writes_only_correction_sidecars,
        test_blocked_materialization_can_never_be_persisted,
        test_guards_remain_network_free_copy_free_and_zero_paid,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Correction Outbox Materializer acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
