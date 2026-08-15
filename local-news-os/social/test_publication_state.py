#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS publication state/retry/dedupe engine."""
from __future__ import annotations

import copy
import hashlib
import json

from publication_state import (
    apply_attempt,
    empty_ledger,
    import_legacy_facebook_state,
    prepare_publication,
    release_retry,
    requeue_after_auth_repair,
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def channel(platform: str = "facebook", *, status: str = "active", instance: str = "valcea") -> dict:
    return {
        "instance_id": instance,
        "channel_id": f"{instance}-{platform}",
        "platform": platform,
        "status": status,
    }


def formatted(ch: dict | None = None, *, human_review: bool = False, story_id: str = "story-1") -> dict:
    ch = ch or channel()
    product = {
        "product_id": f"social-product:{ch['channel_id']}:{story_id}",
        "native_format": "single_photo" if ch["platform"] != "instagram" else "carousel",
        "format_family": "feed_post",
        "hook": {"text": "Programul local pentru weekend"},
        "content_blocks": [{"text": "Accesul este liber."}],
        "visual_requirement": {"required": False},
        "link_requirement": {"mode": "optional"},
        "approval": {
            "human_review_required_before_publish": human_review,
            "corrections_priority": True,
        },
        "correction": False,
        "cross_post_policy": "NATIVE_PRODUCT_ONLY",
        "verbatim_cross_platform_reuse_allowed": False,
        "invented_claims_allowed": False,
        "analytics_used": False,
        "format_status": "FORMAT_READY",
        "next_gate": "PUBLICATION_STATE",
    }
    product["product_fingerprint_sha256"] = digest(product)
    return {
        "schema_version": "1.0",
        "instance_id": ch["instance_id"],
        "story_id": story_id,
        "channel_id": ch["channel_id"],
        "platform": ch["platform"],
        "blocked": False,
        "hard_blocks": [],
        "product": product,
    }


def virality(fmt: dict, ch: dict | None = None, *, action: str = "ELIGIBLE", blocked: bool = False) -> dict:
    ch = ch or channel()
    result = {
        "schema_version": "1.0",
        "instance_id": ch["instance_id"],
        "story_id": fmt["story_id"],
        "channel_id": ch["channel_id"],
        "platform": ch["platform"],
        "product_id": fmt["product"]["product_id"],
        "blocked": blocked,
        "hard_blocks": ["TEST_BLOCK"] if blocked else [],
        "score": 72.0,
        "publication_action": "BLOCKED" if blocked else action,
        "guards": {
            "editorial_gates_weakened": False,
            "rage_bait_allowed": False,
            "fake_urgency_allowed": False,
            "fake_exclusivity_allowed": False,
            "misleading_thumbnail_allowed": False,
            "fabricated_engagement_allowed": False,
            "zero_paid_dependency": True,
        },
    }
    result["decision_fingerprint_sha256"] = digest(result)
    return result


def test_registers_channel_local_ready_record() -> None:
    ch = channel()
    fmt = formatted(ch)
    result = prepare_publication(fmt, virality(fmt, ch), ch)
    assert result["blocked"] is False
    assert result["decision"] == "REGISTERED_READY"
    assert result["record"]["status"] == "READY"
    assert len(result["ledger"]["records"]) == 1
    assert result["record"]["instance_id"] == "valcea"
    assert result["record"]["channel_id"] == "valcea-facebook"


def test_duplicate_prepare_is_idempotent() -> None:
    ch = channel()
    fmt = formatted(ch)
    first = prepare_publication(fmt, virality(fmt, ch), ch)
    second = prepare_publication(fmt, virality(fmt, ch), ch, first["ledger"])
    assert second["decision"] == "DEDUPE_EXISTING"
    assert len(second["ledger"]["records"]) == 1
    assert second["record"]["publication_id"] == first["record"]["publication_id"]


def test_same_story_has_independent_channel_state() -> None:
    fb = channel("facebook")
    ig = channel("instagram")
    fb_fmt = formatted(fb, story_id="shared-story")
    ig_fmt = formatted(ig, story_id="shared-story")
    fb_result = prepare_publication(fb_fmt, virality(fb_fmt, fb), fb)
    ig_result = prepare_publication(ig_fmt, virality(ig_fmt, ig), ig)
    assert fb_result["record"]["publication_id"] != ig_result["record"]["publication_id"]
    assert fb_result["record"]["channel_id"] != ig_result["record"]["channel_id"]


def test_instance_mismatch_fails_closed_without_mutation() -> None:
    ch = channel()
    fmt = formatted(ch)
    foreign = channel(instance="cluj")
    ledger = empty_ledger("valcea", "valcea-facebook", "facebook")
    before = copy.deepcopy(ledger)
    result = prepare_publication(fmt, virality(fmt, ch), foreign, ledger)
    assert result["blocked"] is True
    assert "LEDGER_INSTANCE_MISMATCH" in result["hard_blocks"]
    assert result["ledger"] == before


def test_outbox_only_never_becomes_dispatchable() -> None:
    ch = channel(status="outbox_only")
    fmt = formatted(ch)
    result = prepare_publication(fmt, virality(fmt, ch, action="OUTBOX_ONLY"), ch)
    assert result["record"]["status"] == "OUTBOX_READY"
    attempt = apply_attempt(
        result["ledger"],
        result["record"]["publication_id"],
        "2026-08-15T18:00:00Z",
        success=True,
        remote_publication_id="should-not-send",
    )
    assert attempt["blocked"] is True
    assert "PUBLICATION_NOT_DISPATCHABLE" in attempt["hard_blocks"]


def test_human_review_is_durable_gate_and_can_promote() -> None:
    ch = channel()
    fmt = formatted(ch, human_review=True)
    first = prepare_publication(fmt, virality(fmt, ch), ch)
    assert first["record"]["status"] == "AWAITING_APPROVAL"
    second = prepare_publication(fmt, virality(fmt, ch), ch, first["ledger"], human_approved=True)
    assert second["decision"] == "PROMOTED_READY"
    assert second["record"]["status"] == "READY"


def test_timing_hold_promotes_without_duplicate() -> None:
    ch = channel()
    fmt = formatted(ch)
    hold = prepare_publication(fmt, virality(fmt, ch, action="HOLD_TIMING"), ch)
    assert hold["record"]["status"] == "HOLD_TIMING"
    ready = prepare_publication(fmt, virality(fmt, ch, action="ELIGIBLE"), ch, hold["ledger"])
    assert ready["decision"] == "PROMOTED_READY"
    assert len(ready["ledger"]["records"]) == 1


def test_transient_failure_uses_deterministic_backoff_and_due_release() -> None:
    ch = channel()
    fmt = formatted(ch)
    prepared = prepare_publication(fmt, virality(fmt, ch), ch)
    pid = prepared["record"]["publication_id"]
    failed = apply_attempt(
        prepared["ledger"],
        pid,
        "2026-08-15T18:00:00Z",
        success=False,
        http_status=503,
    )
    assert failed["decision"] == "RETRY_SCHEDULED"
    assert failed["record"]["status"] == "RETRY_WAIT"
    assert failed["record"]["next_attempt_at"] == "2026-08-15T18:01:00Z"
    early = release_retry(failed["ledger"], pid, "2026-08-15T18:00:59Z")
    assert early["decision"] == "RETRY_NOT_DUE"
    due = release_retry(failed["ledger"], pid, "2026-08-15T18:01:00Z")
    assert due["decision"] == "RETRY_READY"


def test_retry_after_is_honoured_with_bound() -> None:
    ch = channel()
    fmt = formatted(ch)
    prepared = prepare_publication(fmt, virality(fmt, ch), ch)
    failed = apply_attempt(
        prepared["ledger"],
        prepared["record"]["publication_id"],
        "2026-08-15T18:00:00Z",
        success=False,
        http_status=429,
        retry_after_seconds=600,
    )
    assert failed["record"]["next_attempt_at"] == "2026-08-15T18:10:00Z"


def test_auth_failure_stops_automatic_retry_until_explicit_repair() -> None:
    ch = channel()
    fmt = formatted(ch)
    prepared = prepare_publication(fmt, virality(fmt, ch), ch)
    pid = prepared["record"]["publication_id"]
    blocked = apply_attempt(
        prepared["ledger"],
        pid,
        "2026-08-15T18:00:00Z",
        success=False,
        http_status=401,
        error_code="TOKEN_EXPIRED",
    )
    assert blocked["decision"] == "BLOCKED_AUTH"
    assert blocked["record"]["next_attempt_at"] is None
    repaired = requeue_after_auth_repair(blocked["ledger"], pid)
    assert repaired["decision"] == "READY"
    assert repaired["record"]["status"] == "READY"


def test_permanent_client_failure_is_terminal() -> None:
    ch = channel()
    fmt = formatted(ch)
    prepared = prepare_publication(fmt, virality(fmt, ch), ch)
    failed = apply_attempt(
        prepared["ledger"],
        prepared["record"]["publication_id"],
        "2026-08-15T18:00:00Z",
        success=False,
        http_status=400,
    )
    assert failed["decision"] == "FAILED_TERMINAL"
    assert failed["record"]["state_reason"] == "PERMANENT_FAILURE"


def test_retry_exhaustion_is_terminal() -> None:
    ch = channel()
    fmt = formatted(ch)
    current = prepare_publication(fmt, virality(fmt, ch), ch)
    pid = current["record"]["publication_id"]
    times = [
        "2026-08-15T18:00:00Z",
        "2026-08-15T18:01:00Z",
        "2026-08-15T18:03:00Z",
    ]
    for index, when in enumerate(times):
        failed = apply_attempt(
            current["ledger"],
            pid,
            when,
            success=False,
            http_status=500,
            max_attempts=3,
        )
        if index < 2:
            assert failed["decision"] == "RETRY_SCHEDULED"
            current = release_retry(failed["ledger"], pid, failed["record"]["next_attempt_at"])
            assert current["decision"] == "RETRY_READY"
        else:
            assert failed["decision"] == "FAILED_TERMINAL"
            assert failed["record"]["state_reason"] == "RETRY_EXHAUSTED"


def test_success_requires_remote_id_and_dedupes_future_runs() -> None:
    ch = channel()
    fmt = formatted(ch)
    prepared = prepare_publication(fmt, virality(fmt, ch), ch)
    pid = prepared["record"]["publication_id"]
    published = apply_attempt(
        prepared["ledger"],
        pid,
        "2026-08-15T18:00:00Z",
        success=True,
        remote_publication_id="123_456",
    )
    assert published["decision"] == "PUBLISHED"
    assert published["record"]["remote_publication_id"] == "123_456"
    again = prepare_publication(fmt, virality(fmt, ch), ch, published["ledger"])
    assert again["decision"] == "DEDUPE_ALREADY_PUBLISHED"
    assert len(again["ledger"]["records"]) == 1


def test_success_without_remote_id_does_not_claim_publication() -> None:
    ch = channel()
    fmt = formatted(ch)
    prepared = prepare_publication(fmt, virality(fmt, ch), ch)
    failed_proof = apply_attempt(
        prepared["ledger"],
        prepared["record"]["publication_id"],
        "2026-08-15T18:00:00Z",
        success=True,
    )
    assert failed_proof["blocked"] is True
    assert "MISSING_REMOTE_PUBLICATION_ID" in failed_proof["hard_blocks"]
    assert failed_proof["record"]["status"] == "READY"
    assert failed_proof["record"]["attempt_count"] == 0


def test_tampered_product_fingerprint_fails_closed() -> None:
    ch = channel()
    fmt = formatted(ch)
    fmt["product"]["hook"]["text"] = "text changed after fingerprint"
    result = prepare_publication(fmt, virality(formatted(ch), ch), ch)
    assert result["blocked"] is True
    assert "PRODUCT_FINGERPRINT_INVALID" in result["hard_blocks"]


def test_virality_hard_block_cannot_be_bypassed() -> None:
    ch = channel()
    fmt = formatted(ch)
    result = prepare_publication(fmt, virality(fmt, ch, blocked=True), ch)
    assert result["blocked"] is True
    assert "VIRALITY_BLOCKED" in result["hard_blocks"]
    assert not result["ledger"]["records"]


def test_predictive_fields_do_not_change_publication_identity() -> None:
    ch = channel()
    fmt = formatted(ch)
    base_v = virality(fmt, ch)
    first = prepare_publication(fmt, base_v, ch)
    poisoned = copy.deepcopy(base_v)
    poisoned["predicted_views"] = 999999999
    poisoned["virality_probability"] = 1.0
    poisoned.pop("decision_fingerprint_sha256")
    poisoned["decision_fingerprint_sha256"] = digest(poisoned)
    second = prepare_publication(fmt, poisoned, ch, first["ledger"])
    assert second["record"]["publication_id"] == first["record"]["publication_id"]
    assert second["decision"] == "DEDUPE_EXISTING"


def test_legacy_facebook_state_normalizes_without_mutating_source() -> None:
    legacy = {
        "schema_version": "1.0",
        "published": {
            "editia-de-dimineata-20260815": {
                "facebook_post_id": "123_789",
                "published_at": "2026-08-15T09:39:57Z",
            },
            "invalid": {"published_at": "2026-08-15T10:00:00Z"},
        },
        "auth": {"status": "EXPIRED"},
    }
    before = copy.deepcopy(legacy)
    ledger = import_legacy_facebook_state(
        legacy,
        instance_id="valcea",
        channel_id="valcea-facebook",
    )
    assert legacy == before
    assert len(ledger["records"]) == 1
    record = next(iter(ledger["records"].values()))
    assert record["status"] == "PUBLISHED"
    assert record["remote_publication_id"] == "123_789"
    assert record["legacy_source_key"] == "editia-de-dimineata-20260815"


def main() -> int:
    tests = [
        test_registers_channel_local_ready_record,
        test_duplicate_prepare_is_idempotent,
        test_same_story_has_independent_channel_state,
        test_instance_mismatch_fails_closed_without_mutation,
        test_outbox_only_never_becomes_dispatchable,
        test_human_review_is_durable_gate_and_can_promote,
        test_timing_hold_promotes_without_duplicate,
        test_transient_failure_uses_deterministic_backoff_and_due_release,
        test_retry_after_is_honoured_with_bound,
        test_auth_failure_stops_automatic_retry_until_explicit_repair,
        test_permanent_client_failure_is_terminal,
        test_retry_exhaustion_is_terminal,
        test_success_requires_remote_id_and_dedupes_future_runs,
        test_success_without_remote_id_does_not_claim_publication,
        test_tampered_product_fingerprint_fails_closed,
        test_virality_hard_block_cannot_be_bypassed,
        test_predictive_fields_do_not_change_publication_identity,
        test_legacy_facebook_state_normalizes_without_mutating_source,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Publication State acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
