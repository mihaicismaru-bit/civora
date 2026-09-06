from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sqlite3

import pytest

import public_presence_os.analytics as analytics_module
from public_presence_os.analytics import (
    ANALYTICS_MODEL_VERSION,
    REMOTE_METRICS,
    AnalyticsHold,
    LocalReceiptAnalyticsStore,
    validate_analytics_event,
    validate_analytics_input,
    validate_analytics_snapshot,
)
from public_presence_os.publisher import LocalDryRunPublisherStore
from public_presence_os.queue import (
    QUEUE_ENGINE_VERSION,
    QUEUE_MODEL_VERSION,
    LocalOutboxItem,
    _hash as queue_hash,
    _item_body_from_item,
)

ROOT = Path(__file__).resolve().parents[1]
PUBLISH_AT = "2026-09-06T12:00:00Z"
OBSERVE_AT = "2026-09-06T12:03:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def outbox_item(*, platform="FACEBOOK_PAGE") -> LocalOutboxItem:
    base = LocalOutboxItem(
        item_id="pending",
        item_hash="0" * 64,
        model_version=QUEUE_MODEL_VERSION,
        engine_version=QUEUE_ENGINE_VERSION,
        approval_receipt_id="arr_" + h("approval45")[:24],
        approval_receipt_hash=h("approval45"),
        report_id="vqr_" + h("report45")[:24],
        report_hash=h("report45"),
        asset_id="ma_fixture45",
        platform=platform,
        mode="TEXT_CARD",
        request_id="cp43-source-045",
        queued_at_utc="2026-09-06T11:45:00Z",
        queue_state="QUEUED_LOCAL",
        publisher_input_ready=True,
    )
    digest = queue_hash(_item_body_from_item(base))
    return replace(base, item_hash=digest, item_id="obi_" + digest[:24])


def dry_run_receipt(*, platform="FACEBOOK_PAGE"):
    item = outbox_item(platform=platform)
    store = LocalDryRunPublisherStore.memory()
    receipt = store.dry_run_publish(
        item,
        request_id="cp44-source-" + platform.lower(),
        attempted_at_utc=PUBLISH_AT,
    )
    store.close()
    return receipt


def test_clean_m09_receipt_produces_local_analytics_snapshot_without_remote_metrics():
    receipt = dry_run_receipt()
    validate_analytics_input(receipt)
    store = LocalReceiptAnalyticsStore.memory()
    try:
        snapshot = store.ingest_receipt(
            receipt,
            request_id="cp45-analytics-001",
            observed_at_utc=OBSERVE_AT,
        )
        validate_analytics_snapshot(snapshot)
        assert snapshot.model_version == ANALYTICS_MODEL_VERSION
        assert snapshot.receipt_hash == receipt.receipt_hash
        assert snapshot.platform == "FACEBOOK_PAGE"
        assert snapshot.local_receipt_age_seconds == 180
        assert snapshot.external_analytics_state == "NOT_CONNECTED"
        assert snapshot.performance_evidence_ready is False
        assert snapshot.learning_input_ready is True
        assert snapshot.learning_scope == "LOCAL_OPERATIONAL_TELEMETRY_ONLY"
        assert snapshot.local_analytics_authority is True
        assert snapshot.external_analytics_authority is False
        assert snapshot.learning_write_authority is False
        assert snapshot.strategy_mutation_authority is False
        assert snapshot.network_authority is False
        assert snapshot.account_connection_authority is False
        assert snapshot.publish_authority is False
        assert snapshot.deploy_authority is False
        assert set(snapshot.external_metrics) == set(REMOTE_METRICS)
        assert all(v["availability"] == "NOT_CONNECTED" for v in snapshot.external_metrics.values())
        assert all(v["value"] is None for v in snapshot.external_metrics.values())
        events = store.events_for(snapshot)
        assert len(events) == 1
        validate_analytics_event(events[0])
        assert events[0].outcome == "REMOTE_ANALYTICS_NOT_CONNECTED"
    finally:
        store.close()


@pytest.mark.parametrize("platform", ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"])
def test_exact_active_platform_set_is_supported(platform):
    receipt = dry_run_receipt(platform=platform)
    store = LocalReceiptAnalyticsStore.memory()
    try:
        snapshot = store.ingest_receipt(
            receipt,
            request_id="cp45-" + platform.lower(),
            observed_at_utc=OBSERVE_AT,
        )
        assert snapshot.platform == platform
        assert snapshot.external_analytics_state == "NOT_CONNECTED"
    finally:
        store.close()


def test_remote_metric_unknown_is_not_zero():
    snapshot_store = LocalReceiptAnalyticsStore.memory()
    try:
        snapshot = snapshot_store.ingest_receipt(
            dry_run_receipt(),
            request_id="cp45-null-not-zero",
            observed_at_utc=OBSERVE_AT,
        )
        for metric in REMOTE_METRICS:
            assert snapshot.external_metrics[metric]["availability"] == "NOT_CONNECTED"
            assert snapshot.external_metrics[metric]["value"] is None
            assert snapshot.external_metrics[metric]["value"] != 0
    finally:
        snapshot_store.close()


def test_tampered_or_false_delivery_receipt_fails_closed():
    receipt = dry_run_receipt()
    forged = replace(receipt, delivered=True, external_post_id="fake-post")
    with pytest.raises(AnalyticsHold, match="HOLD_M09_RECEIPT_INVALID"):
        validate_analytics_input(forged)


def test_observation_cannot_predate_local_publisher_attempt():
    receipt = dry_run_receipt()
    store = LocalReceiptAnalyticsStore.memory()
    try:
        with pytest.raises(AnalyticsHold, match="HOLD_ANALYTICS_OBSERVED_BEFORE_PUBLISHER_ATTEMPT"):
            store.ingest_receipt(
                receipt,
                request_id="cp45-time-order",
                observed_at_utc="2026-09-06T11:59:59Z",
            )
    finally:
        store.close()


def test_retry_is_idempotent_for_exact_request_receipt_and_timestamp():
    receipt = dry_run_receipt()
    store = LocalReceiptAnalyticsStore.memory()
    try:
        first = store.ingest_receipt(
            receipt,
            request_id="cp45-retry-001",
            observed_at_utc=OBSERVE_AT,
        )
        retry = store.ingest_receipt(
            receipt,
            request_id="cp45-retry-001",
            observed_at_utc=OBSERVE_AT,
        )
        assert retry == first
        assert store.snapshots() == (first,)
        assert len(store.events_for(first)) == 1
    finally:
        store.close()


def test_request_id_reuse_with_timestamp_drift_fails_closed():
    receipt = dry_run_receipt()
    store = LocalReceiptAnalyticsStore.memory()
    try:
        store.ingest_receipt(
            receipt,
            request_id="cp45-reuse-001",
            observed_at_utc=OBSERVE_AT,
        )
        with pytest.raises(AnalyticsHold, match="HOLD_ANALYTICS_REQUEST_ID_REUSE_MISMATCH"):
            store.ingest_receipt(
                receipt,
                request_id="cp45-reuse-001",
                observed_at_utc="2026-09-06T12:04:00Z",
            )
    finally:
        store.close()


def test_same_receipt_cannot_create_second_snapshot():
    receipt = dry_run_receipt()
    store = LocalReceiptAnalyticsStore.memory()
    try:
        store.ingest_receipt(
            receipt,
            request_id="cp45-dedup-001",
            observed_at_utc=OBSERVE_AT,
        )
        with pytest.raises(AnalyticsHold, match="HOLD_M09_RECEIPT_ALREADY_INGESTED"):
            store.ingest_receipt(
                receipt,
                request_id="cp45-dedup-002",
                observed_at_utc=OBSERVE_AT,
            )
        assert len(store.snapshots()) == 1
    finally:
        store.close()


def test_snapshot_tamper_cannot_invent_reach_or_performance_evidence():
    receipt = dry_run_receipt()
    store = LocalReceiptAnalyticsStore.memory()
    try:
        snapshot = store.ingest_receipt(
            receipt,
            request_id="cp45-tamper-001",
            observed_at_utc=OBSERVE_AT,
        )
        fake_metrics = {k: dict(v) for k, v in snapshot.external_metrics.items()}
        fake_metrics["REACH"] = {
            "availability": "PRESENT",
            "value": 123,
            "source_metric_name": "reach",
        }
        forged = replace(snapshot, external_metrics=fake_metrics, performance_evidence_ready=True)
        with pytest.raises(AnalyticsHold):
            validate_analytics_snapshot(forged)
    finally:
        store.close()


def test_analytics_tables_and_event_log_are_append_only():
    receipt = dry_run_receipt()
    store = LocalReceiptAnalyticsStore.memory()
    try:
        snapshot = store.ingest_receipt(
            receipt,
            request_id="cp45-append-001",
            observed_at_utc=OBSERVE_AT,
        )
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("UPDATE analytics_snapshots SET observed_at_utc='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("DELETE FROM analytics_events")
        assert len(store.events_for(snapshot)) == 1
    finally:
        store.close()


def test_analytics_source_has_no_network_or_live_analytics_client_path():
    source = inspect.getsource(analytics_module)
    for token in (
        "import requests",
        "import httpx",
        "import aiohttp",
        "urllib.request",
        "http.client",
        "socket.",
        "urlopen(",
    ):
        assert token not in source


def test_cp45_policy_is_truthful_local_only_and_advances_to_learning():
    policy = json.loads((ROOT / "config" / "analytics_policy.json").read_text())
    assert policy["checkpoint"] == "CP45"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["input_contract"]["required_module"] == "M09_PUBLISHER"
    assert policy["input_contract"]["require_analytics_input_ready"] is True
    assert policy["collection"]["mode"] == "LOCAL_RECEIPT_TELEMETRY_ONLY"
    for key in (
        "network_analytics_lookup",
        "real_account_connected",
        "external_post_lookup",
        "learning_feedback_write",
        "strategy_mutation",
    ):
        assert policy["collection"][key] is False
    assert policy["remote_metrics"]["availability"] == "NOT_CONNECTED"
    assert policy["remote_metrics"]["null_is_not_zero"] is True
    assert set(policy["remote_metrics"]["metric_names"]) == set(REMOTE_METRICS)
    assert policy["storage"]["backend"] == "SQLITE_LOCAL"
    assert policy["storage"]["snapshots_append_only"] is True
    assert policy["storage"]["event_log_append_only"] is True
    assert policy["privacy"]["aggregate_content_level_only"] is True
    assert policy["privacy"]["individual_profiling"] is False
    assert policy["privacy"]["demographic_dimensions"] is False
    assert policy["authority"]["local_analytics_authority"] is True
    for key in (
        "external_analytics_authority",
        "learning_write_authority",
        "strategy_mutation_authority",
        "network_authority",
        "real_account_connection_authority",
        "publish_authority",
        "deploy_authority",
    ):
        assert policy["authority"][key] is False
    assert policy["platform_policy"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["platform_policy"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["platform_policy"]["BLUESKY"] == "HOLD_ROI"
    assert policy["next_dependency"] == "M11_LEARNING"
