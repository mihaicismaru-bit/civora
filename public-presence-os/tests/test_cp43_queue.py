from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from public_presence_os.approval import (
    APPROVAL_ENGINE_VERSION,
    APPROVAL_MODEL_VERSION,
    ApprovalReviewReceipt,
    ReviewState,
)
from public_presence_os.queue import (
    QUEUE_MODEL_VERSION,
    LocalOutboxStore,
    QueueHold,
    _approval_receipt_body,
    _hash,
    validate_approval_receipt,
    validate_outbox_item,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-09-06T11:45:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def receipt(*, platform="FACEBOOK_PAGE", approved=True, holds=()) -> ApprovalReviewReceipt:
    base = ApprovalReviewReceipt(
        receipt_id="pending",
        receipt_hash="0" * 64,
        model_version=APPROVAL_MODEL_VERSION,
        engine_version=APPROVAL_ENGINE_VERSION,
        report_id="vqr_" + h("report")[:24],
        report_hash=h("report"),
        asset_id="ma_fixture43",
        platform=platform,
        mode="TEXT_CARD",
        qa_verdict="PASS" if approved else "HOLD",
        qa_holds=tuple(sorted(holds)),
        current_state=ReviewState.APPROVED_LOCAL.value if approved else ReviewState.HOLD_REVIEW.value,
        last_event_id="are_" + h("approval-event")[:24] if approved else None,
        event_count=1 if approved else 0,
        local_approval_complete=approved,
        queue_input_ready=approved,
    )
    digest = _hash(_approval_receipt_body(base))
    return replace(base, receipt_hash=digest, receipt_id="arr_" + digest[:24])


def test_clean_m12_receipt_enqueues_deterministically_without_publish_authority():
    approved = receipt()
    validate_approval_receipt(approved)
    store = LocalOutboxStore.memory()
    try:
        item = store.enqueue(approved, request_id="cp43-enqueue-001", queued_at_utc=T0)
        validate_outbox_item(item)
        assert item.model_version == QUEUE_MODEL_VERSION
        assert item.platform == "FACEBOOK_PAGE"
        assert item.queue_state == "QUEUED_LOCAL"
        assert item.publisher_input_ready is True
        assert item.local_queue_authority is True
        assert item.publisher_authority is False
        assert item.publish_authority is False
        assert item.public_publish_eligible is False
        assert item.network_authority is False
        assert item.account_connection_authority is False
        assert item.deploy_authority is False
        assert store.pending_items() == (item,)
        events = store.events_for(item)
        assert len(events) == 1
        assert events[0].event_type == "ENQUEUE_LOCAL"
        assert events[0].resulting_state == "QUEUED_LOCAL"
    finally:
        store.close()


def test_enqueue_retry_is_idempotent_for_exact_request_payload():
    approved = receipt()
    store = LocalOutboxStore.memory()
    try:
        first = store.enqueue(approved, request_id="cp43-retry-001", queued_at_utc=T0)
        retry = store.enqueue(approved, request_id="cp43-retry-001", queued_at_utc=T0)
        assert retry == first
        assert len(store.pending_items()) == 1
        assert len(store.events_for(first)) == 1
    finally:
        store.close()


def test_request_id_reuse_with_timestamp_drift_fails_closed():
    approved = receipt()
    store = LocalOutboxStore.memory()
    try:
        store.enqueue(approved, request_id="cp43-reuse-001", queued_at_utc=T0)
        with pytest.raises(QueueHold, match="HOLD_QUEUE_REQUEST_ID_REUSE_MISMATCH"):
            store.enqueue(approved, request_id="cp43-reuse-001", queued_at_utc="2026-09-06T11:46:00Z")
    finally:
        store.close()


def test_same_approval_receipt_cannot_create_duplicate_outbox_item():
    approved = receipt()
    store = LocalOutboxStore.memory()
    try:
        store.enqueue(approved, request_id="cp43-dedup-001", queued_at_utc=T0)
        with pytest.raises(QueueHold, match="HOLD_APPROVAL_RECEIPT_ALREADY_ENQUEUED"):
            store.enqueue(approved, request_id="cp43-dedup-002", queued_at_utc=T0)
        assert len(store.pending_items()) == 1
    finally:
        store.close()


def test_tampered_m12_receipt_fails_hash_validation():
    approved = receipt()
    forged = replace(approved, asset_id="forged")
    with pytest.raises(QueueHold, match="HOLD_M12_RECEIPT_HASH_MISMATCH"):
        validate_approval_receipt(forged)


def test_hold_or_nonapproved_m12_receipt_cannot_enter_queue():
    blocked = receipt(approved=False, holds=("HOLD_IDENTITY_EQUIVALENCE",))
    store = LocalOutboxStore.memory()
    try:
        with pytest.raises(QueueHold, match="HOLD_M12_QA_HOLDS_PRESENT"):
            store.enqueue(blocked, request_id="cp43-blocked-001", queued_at_utc=T0)
        assert store.pending_items() == ()
    finally:
        store.close()


def test_deferred_networks_are_rejected_by_active_platform_gate():
    linked_in = receipt(platform="LINKEDIN")
    with pytest.raises(QueueHold, match="HOLD_M12_PLATFORM_NOT_ACTIVE"):
        validate_approval_receipt(linked_in)


def test_queue_tables_and_event_log_are_append_only():
    approved = receipt()
    store = LocalOutboxStore.memory()
    try:
        item = store.enqueue(approved, request_id="cp43-append-001", queued_at_utc=T0)
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("UPDATE outbox_items SET queued_at_utc='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("DELETE FROM queue_events")
        assert len(store.events_for(item)) == 1
    finally:
        store.close()


def test_tampered_outbox_item_fails_closed():
    approved = receipt()
    store = LocalOutboxStore.memory()
    try:
        item = store.enqueue(approved, request_id="cp43-tamper-001", queued_at_utc=T0)
        forged = replace(item, asset_id="forged")
        with pytest.raises(QueueHold, match="HOLD_QUEUE_ITEM_HASH_MISMATCH"):
            validate_outbox_item(forged)
    finally:
        store.close()


def test_cp43_policy_is_local_only_and_advances_to_publisher():
    policy = json.loads((ROOT / "config" / "queue_policy.json").read_text())
    assert policy["checkpoint"] == "CP43"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["input_contract"]["required_module"] == "M12_APPROVAL"
    assert policy["input_contract"]["require_zero_qa_holds"] is True
    assert policy["input_contract"]["require_queue_input_ready"] is True
    assert policy["storage"]["backend"] == "SQLITE_LOCAL"
    assert policy["storage"]["outbox_items_append_only"] is True
    assert policy["storage"]["event_log_append_only"] is True
    assert policy["outbox"]["mode"] == "LOCAL_DRY_RUN_ONLY"
    assert policy["outbox"]["public_publish_eligible"] is False
    assert policy["authority"]["local_queue_authority"] is True
    for key in ("publisher_authority", "publish_authority", "network_authority", "real_account_connection_authority", "deploy_authority"):
        assert policy["authority"][key] is False
    assert policy["platform_policy"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["platform_policy"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["platform_policy"]["BLUESKY"] == "HOLD_ROI"
    assert policy["next_dependency"] == "M09_PUBLISHER"
