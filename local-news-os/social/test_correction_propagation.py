#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS correction propagation."""
from __future__ import annotations

import copy
import hashlib

from correction_propagation import propagate_correction


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def correction(*, instance: str = "valcea", story_id: str = "corr-1", target: str = "story-1") -> dict:
    return {
        "instance_id": instance,
        "story_id": story_id,
        "correction": True,
        "lifecycle": "correction",
        "verified": True,
        "editorial_gate": "PASS",
        "fact_kernel_sha256": sha("verified corrected fact kernel"),
        "corrects_story_ids": [target],
        "zero_paid_dependency": True,
        "predicted_views": 999999,
    }


def record(
    channel: str,
    platform: str,
    *,
    story_id: str = "story-1",
    status: str = "READY",
    publication_id: str | None = None,
    remote_id: str | None = None,
    instance: str = "valcea",
) -> dict:
    publication_id = publication_id or f"publication:{channel}:{story_id}"
    return {
        "publication_id": publication_id,
        "instance_id": instance,
        "channel_id": channel,
        "platform": platform,
        "story_id": story_id,
        "status": status,
        "remote_publication_id": remote_id,
        "next_attempt_at": "2026-08-15T20:00:00Z" if status == "RETRY_WAIT" else None,
        "attempt_count": 1 if status in {"RETRY_WAIT", "PUBLISHED"} else 0,
    }


def ledger(channel: str, platform: str, records: list[dict], *, instance: str = "valcea") -> dict:
    return {
        "schema_version": "1.0",
        "instance_id": instance,
        "channel_id": channel,
        "platform": platform,
        "records": {item["publication_id"]: item for item in records},
        "guards": {"zero_paid_dependency": True},
    }


def test_unpublished_outbox_is_superseded_and_not_dispatchable() -> None:
    source = ledger("valcea-instagram", "instagram", [record("valcea-instagram", "instagram", status="OUTBOX_READY")])
    result = propagate_correction(correction(), [source])
    updated = next(iter(result["updated_ledgers"][0]["records"].values()))
    assert result["blocked"] is False
    assert updated["status"] == "SUPERSEDED_CORRECTION"
    assert updated["next_attempt_at"] is None
    assert result["actions"][0]["action"] == "SUPERSEDE_UNPUBLISHED"
    assert result["actions"][0]["native_regeneration"]["required"] is True


def test_ready_and_retry_wait_are_both_superseded() -> None:
    first = record("valcea-facebook", "facebook", status="READY", publication_id="publication:fb:1")
    second = record("valcea-facebook", "facebook", status="RETRY_WAIT", publication_id="publication:fb:2")
    source = ledger("valcea-facebook", "facebook", [first, second])
    result = propagate_correction(correction(), [source])
    statuses = {item["status"] for item in result["updated_ledgers"][0]["records"].values()}
    assert statuses == {"SUPERSEDED_CORRECTION"}
    assert len([item for item in result["actions"] if item["action"] == "SUPERSEDE_UNPUBLISHED"]) == 2


def test_published_remote_record_gets_native_correction_action() -> None:
    source = ledger(
        "valcea-facebook",
        "facebook",
        [record("valcea-facebook", "facebook", status="PUBLISHED", remote_id="123_456")],
    )
    result = propagate_correction(correction(), [source])
    action = result["actions"][0]
    updated = next(iter(result["updated_ledgers"][0]["records"].values()))
    assert action["action"] == "CORRECT_PUBLISHED_NATIVE"
    assert action["adapter_instruction"] == "EDIT_WHEN_SAFE_AND_SUPPORTED_ELSE_PUBLISH_NATIVE_CORRECTION"
    assert action["remote_publication_id"] == "123_456"
    assert action["native_regeneration"]["reuse_prior_copy"] is False
    assert updated["status"] == "PUBLISHED"
    assert updated["correction_state"] == "CORRECTION_REQUIRED"


def test_three_channels_get_distinct_channel_local_actions() -> None:
    ledgers = [
        ledger("valcea-facebook", "facebook", [record("valcea-facebook", "facebook", status="PUBLISHED", remote_id="fb-1")]),
        ledger("valcea-instagram", "instagram", [record("valcea-instagram", "instagram", status="OUTBOX_READY")]),
        ledger("valcea-tiktok", "tiktok", [record("valcea-tiktok", "tiktok", status="PUBLISHED", remote_id="tt-1")]),
    ]
    result = propagate_correction(correction(), ledgers)
    assert {item["channel_id"] for item in result["actions"]} == {
        "valcea-facebook", "valcea-instagram", "valcea-tiktok"
    }
    assert len({item["action_id"] for item in result["actions"]}) == 3
    assert all(item["native_regeneration"]["verbatim_cross_platform_reuse_allowed"] is False for item in result["actions"])


def test_foreign_instance_is_ignored_and_unchanged() -> None:
    local = ledger("valcea-facebook", "facebook", [record("valcea-facebook", "facebook", status="READY")])
    foreign_record = record("cluj-facebook", "facebook", status="READY", instance="cluj")
    foreign = ledger("cluj-facebook", "facebook", [foreign_record], instance="cluj")
    before = copy.deepcopy(foreign)
    result = propagate_correction(correction(), [local, foreign])
    assert result["updated_ledgers"][1] == before
    assert result["ignored_foreign_ledgers"] == [{"instance_id": "cluj", "channel_id": "cluj-facebook"}]
    assert all(item["instance_id"] == "valcea" for item in result["actions"])


def test_published_without_remote_id_fails_closed_for_that_record() -> None:
    source = ledger(
        "valcea-facebook",
        "facebook",
        [record("valcea-facebook", "facebook", status="PUBLISHED", remote_id=None)],
    )
    before = copy.deepcopy(source)
    result = propagate_correction(correction(), [source])
    assert result["blocked"] is True
    assert result["actions"] == []
    assert result["updated_ledgers"][0] == before
    assert result["unresolved"][0]["reason"] == "PUBLISHED_WITHOUT_REMOTE_ID"


def test_in_flight_requires_reconciliation_not_false_supersede() -> None:
    source = ledger(
        "valcea-facebook",
        "facebook",
        [record("valcea-facebook", "facebook", status="PUBLISHING")],
    )
    result = propagate_correction(correction(), [source])
    action = result["actions"][0]
    updated = next(iter(result["updated_ledgers"][0]["records"].values()))
    assert action["action"] == "RECONCILE_IN_FLIGHT"
    assert updated["status"] == "PUBLISHING"
    assert updated["correction_state"] == "RECONCILIATION_REQUIRED"


def test_requires_explicit_verified_target_and_fact_kernel() -> None:
    bad = correction()
    bad["verified"] = False
    bad["corrects_story_ids"] = []
    bad.pop("fact_kernel_sha256")
    source = ledger("valcea-facebook", "facebook", [record("valcea-facebook", "facebook")])
    before = copy.deepcopy(source)
    result = propagate_correction(bad, [source])
    assert result["blocked"] is True
    assert set(result["hard_blocks"]) == {
        "CORRECTION_NOT_VERIFIED",
        "MISSING_EXPLICIT_CORRECTION_TARGET",
        "MISSING_FACT_KERNEL_FINGERPRINT",
    }
    assert result["updated_ledgers"][0] == before


def test_unrelated_story_is_not_touched() -> None:
    source = ledger(
        "valcea-facebook",
        "facebook",
        [record("valcea-facebook", "facebook", story_id="story-other", status="PUBLISHED", remote_id="fb-x")],
    )
    before = copy.deepcopy(source)
    result = propagate_correction(correction(target="story-1"), [source])
    assert result["updated_ledgers"][0] == before
    assert result["actions"] == []
    assert result["affected_count"] == 0
    assert result["unresolved"] == [{"reason": "NO_AFFECTED_PUBLICATIONS_FOUND"}]


def test_explicit_publication_target_works_without_story_match() -> None:
    corr = correction(target="not-this-story")
    corr["corrects_publication_ids"] = ["publication:fb:special"]
    source = ledger(
        "valcea-facebook",
        "facebook",
        [record("valcea-facebook", "facebook", story_id="story-77", status="PUBLISHED", publication_id="publication:fb:special", remote_id="fb-77")],
    )
    result = propagate_correction(corr, [source])
    assert result["affected_count"] == 1
    assert result["actions"][0]["affected_publication_id"] == "publication:fb:special"


def test_repeated_propagation_is_idempotent() -> None:
    source = ledger(
        "valcea-facebook",
        "facebook",
        [record("valcea-facebook", "facebook", status="PUBLISHED", remote_id="fb-1")],
    )
    first = propagate_correction(correction(), [source])
    second = propagate_correction(correction(), first["updated_ledgers"])
    assert second["actions"][0]["action"] == "ALREADY_PROPAGATED"
    assert second["actions"][0]["decision"] == "IDEMPOTENT_NOOP"
    first_record = next(iter(first["updated_ledgers"][0]["records"].values()))
    second_record = next(iter(second["updated_ledgers"][0]["records"].values()))
    assert second_record == first_record


def test_predictive_analytics_do_not_affect_plan_identity() -> None:
    source = ledger(
        "valcea-facebook",
        "facebook",
        [record("valcea-facebook", "facebook", status="PUBLISHED", remote_id="fb-1")],
    )
    a = correction()
    b = correction()
    a["predicted_views"] = 1
    b["predicted_views"] = 100000000
    first = propagate_correction(a, [source])
    second = propagate_correction(b, [source])
    assert first["actions"] == second["actions"]
    assert first["propagation_fingerprint_sha256"] == second["propagation_fingerprint_sha256"]


def test_deterministic_order_across_ledger_input_order() -> None:
    fb = ledger("valcea-facebook", "facebook", [record("valcea-facebook", "facebook", status="PUBLISHED", remote_id="fb-1")])
    ig = ledger("valcea-instagram", "instagram", [record("valcea-instagram", "instagram", status="OUTBOX_READY")])
    first = propagate_correction(correction(), [fb, ig])
    second = propagate_correction(correction(), [ig, fb])
    first_actions = [(item["channel_id"], item["action_id"]) for item in first["actions"]]
    second_actions = [(item["channel_id"], item["action_id"]) for item in second["actions"]]
    assert first_actions == second_actions


def test_record_identity_mismatch_is_not_mutated() -> None:
    bad_record = record("valcea-facebook", "facebook", status="READY")
    bad_record["instance_id"] = "cluj"
    source = ledger("valcea-facebook", "facebook", [bad_record])
    before = copy.deepcopy(source)
    result = propagate_correction(correction(), [source])
    assert result["blocked"] is True
    assert result["updated_ledgers"][0] == before
    assert result["unresolved"][0]["reason"] == "RECORD_IDENTITY_MISMATCH"


def main() -> int:
    tests = [
        test_unpublished_outbox_is_superseded_and_not_dispatchable,
        test_ready_and_retry_wait_are_both_superseded,
        test_published_remote_record_gets_native_correction_action,
        test_three_channels_get_distinct_channel_local_actions,
        test_foreign_instance_is_ignored_and_unchanged,
        test_published_without_remote_id_fails_closed_for_that_record,
        test_in_flight_requires_reconciliation_not_false_supersede,
        test_requires_explicit_verified_target_and_fact_kernel,
        test_unrelated_story_is_not_touched,
        test_explicit_publication_target_works_without_story_match,
        test_repeated_propagation_is_idempotent,
        test_predictive_analytics_do_not_affect_plan_identity,
        test_deterministic_order_across_ledger_input_order,
        test_record_identity_mismatch_is_not_mutated,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Correction Propagation acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
