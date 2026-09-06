from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sqlite3

import pytest

import public_presence_os.publisher as publisher_module
from public_presence_os.publisher import (
    PUBLISHER_MODEL_VERSION,
    LocalDryRunPublisherStore,
    PublisherHold,
    validate_attempt_event,
    validate_publish_receipt,
    validate_publisher_input,
)
from public_presence_os.queue import (
    QUEUE_ENGINE_VERSION,
    QUEUE_MODEL_VERSION,
    LocalOutboxItem,
    _hash as queue_hash,
    _item_body_from_item,
    validate_outbox_item,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-09-06T12:00:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def outbox_item(*, platform="FACEBOOK_PAGE", ready=True, asset_id="ma_fixture44") -> LocalOutboxItem:
    base = LocalOutboxItem(
        item_id="pending",
        item_hash="0" * 64,
        model_version=QUEUE_MODEL_VERSION,
        engine_version=QUEUE_ENGINE_VERSION,
        approval_receipt_id="arr_" + h("approval")[:24],
        approval_receipt_hash=h("approval"),
        report_id="vqr_" + h("report")[:24],
        report_hash=h("report"),
        asset_id=asset_id,
        platform=platform,
        mode="TEXT_CARD",
        request_id="cp43-source-001",
        queued_at_utc="2026-09-06T11:45:00Z",
        queue_state="QUEUED_LOCAL",
        publisher_input_ready=ready,
    )
    digest = queue_hash(_item_body_from_item(base))
    item = replace(base, item_hash=digest, item_id="obi_" + digest[:24])
    if ready and platform in ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"):
        validate_outbox_item(item)
    return item


def test_clean_m08_item_produces_truthful_local_dry_run_receipt():
    item = outbox_item()
    validate_publisher_input(item)
    store = LocalDryRunPublisherStore.memory()
    try:
        receipt = store.dry_run_publish(item, request_id="cp44-publish-001", attempted_at_utc=T0)
        validate_publish_receipt(receipt)
        assert receipt.model_version == PUBLISHER_MODEL_VERSION
        assert receipt.platform == "FACEBOOK_PAGE"
        assert receipt.outbox_item_hash == item.item_hash
        assert receipt.execution_mode == "LOCAL_DRY_RUN"
        assert receipt.publisher_state == "DRY_RUN_RECORDED"
        assert receipt.analytics_input_ready is True
        assert receipt.local_dry_run_publisher_authority is True
        assert receipt.network_attempted is False
        assert receipt.external_write_performed is False
        assert receipt.account_connected is False
        assert receipt.delivered is False
        assert receipt.external_post_id is None
        assert receipt.external_publisher_authority is False
        assert receipt.publish_authority is False
        assert receipt.network_authority is False
        assert receipt.account_connection_authority is False
        assert receipt.deploy_authority is False
        events = store.events_for(receipt)
        assert len(events) == 1
        validate_attempt_event(events[0])
        assert events[0].event_type == "DRY_RUN_ATTEMPT_RECORDED"
        assert events[0].outcome == "NOT_DELIVERED_LOCAL_DRY_RUN"
    finally:
        store.close()


@pytest.mark.parametrize("platform", ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"])
def test_exact_active_platform_set_is_supported(platform):
    item = outbox_item(platform=platform)
    store = LocalDryRunPublisherStore.memory()
    try:
        receipt = store.dry_run_publish(item, request_id=f"cp44-{platform.lower()}-001", attempted_at_utc=T0)
        assert receipt.platform == platform
        assert receipt.delivered is False
    finally:
        store.close()


def test_deferred_platform_is_rejected_before_publisher_receipt():
    item = outbox_item(platform="LINKEDIN")
    with pytest.raises(PublisherHold, match="HOLD_M08_OUTBOX_INVALID"):
        validate_publisher_input(item)


def test_not_ready_or_tampered_outbox_input_fails_closed():
    not_ready = outbox_item(ready=False)
    with pytest.raises(PublisherHold, match="HOLD_M08_OUTBOX_INVALID"):
        validate_publisher_input(not_ready)
    valid = outbox_item()
    forged = replace(valid, asset_id="forged")
    with pytest.raises(PublisherHold, match="HOLD_M08_OUTBOX_INVALID:HOLD_QUEUE_ITEM_HASH_MISMATCH"):
        validate_publisher_input(forged)


def test_retry_is_idempotent_for_exact_request_item_and_timestamp():
    item = outbox_item()
    store = LocalDryRunPublisherStore.memory()
    try:
        first = store.dry_run_publish(item, request_id="cp44-retry-001", attempted_at_utc=T0)
        retry = store.dry_run_publish(item, request_id="cp44-retry-001", attempted_at_utc=T0)
        assert retry == first
        assert store.receipts() == (first,)
        assert len(store.events_for(first)) == 1
    finally:
        store.close()


def test_request_id_reuse_with_payload_drift_fails_closed():
    item = outbox_item()
    store = LocalDryRunPublisherStore.memory()
    try:
        store.dry_run_publish(item, request_id="cp44-reuse-001", attempted_at_utc=T0)
        with pytest.raises(PublisherHold, match="HOLD_PUBLISHER_REQUEST_ID_REUSE_MISMATCH"):
            store.dry_run_publish(item, request_id="cp44-reuse-001", attempted_at_utc="2026-09-06T12:01:00Z")
    finally:
        store.close()


def test_same_outbox_item_cannot_create_second_dry_run_receipt():
    item = outbox_item()
    store = LocalDryRunPublisherStore.memory()
    try:
        store.dry_run_publish(item, request_id="cp44-dedup-001", attempted_at_utc=T0)
        with pytest.raises(PublisherHold, match="HOLD_M08_OUTBOX_ALREADY_DRY_RUN_RECORDED"):
            store.dry_run_publish(item, request_id="cp44-dedup-002", attempted_at_utc=T0)
        assert len(store.receipts()) == 1
    finally:
        store.close()


def test_receipt_tamper_cannot_turn_dry_run_into_delivery():
    item = outbox_item()
    store = LocalDryRunPublisherStore.memory()
    try:
        receipt = store.dry_run_publish(item, request_id="cp44-tamper-001", attempted_at_utc=T0)
        forged = replace(receipt, delivered=True, external_post_id="fake-post")
        with pytest.raises(PublisherHold, match="HOLD_PUBLISHER_FALSE_EXTERNAL_STATE"):
            validate_publish_receipt(forged)
    finally:
        store.close()


def test_publisher_tables_and_attempt_log_are_append_only():
    item = outbox_item()
    store = LocalDryRunPublisherStore.memory()
    try:
        receipt = store.dry_run_publish(item, request_id="cp44-append-001", attempted_at_utc=T0)
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("UPDATE dry_run_publish_receipts SET attempted_at_utc='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("DELETE FROM publish_attempt_events")
        assert len(store.events_for(receipt)) == 1
    finally:
        store.close()


def test_publisher_source_has_no_network_client_path():
    source = inspect.getsource(publisher_module)
    for token in ("import requests", "import httpx", "urllib.request", "socket.", "urlopen("):
        assert token not in source


def test_cp44_policy_is_truthful_local_only_and_advances_to_analytics():
    policy = json.loads((ROOT / "config" / "publisher_policy.json").read_text())
    assert policy["checkpoint"] == "CP44"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["input_contract"]["required_module"] == "M08_QUEUE"
    assert policy["input_contract"]["require_publisher_input_ready"] is True
    assert policy["execution"]["mode"] == "LOCAL_DRY_RUN_ONLY"
    assert policy["execution"]["global_kill_switch_must_remain_engaged"] is True
    for key in ("network_attempted", "external_write_performed", "real_account_connected", "delivered", "public_publish_eligible"):
        assert policy["execution"][key] is False
    assert policy["execution"]["external_post_id"] is None
    assert policy["storage"]["backend"] == "SQLITE_LOCAL"
    assert policy["storage"]["dry_run_receipts_append_only"] is True
    assert policy["storage"]["attempt_event_log_append_only"] is True
    assert policy["authority"]["local_dry_run_publisher_authority"] is True
    for key in ("external_publisher_authority", "publish_authority", "network_authority", "real_account_connection_authority", "deploy_authority"):
        assert policy["authority"][key] is False
    assert policy["platform_policy"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["platform_policy"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["platform_policy"]["BLUESKY"] == "HOLD_ROI"
    assert policy["next_dependency"] == "M10_ANALYTICS"
