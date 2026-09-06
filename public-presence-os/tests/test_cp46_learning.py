from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sqlite3

import pytest

import public_presence_os.learning as learning_module
from public_presence_os.analytics import (
    ANALYTICS_ENGINE_VERSION,
    ANALYTICS_MODEL_VERSION,
    LocalAnalyticsSnapshot,
    _hash as analytics_hash,
    _not_connected_metrics,
    _snapshot_body_from_snapshot,
)
from public_presence_os.learning import (
    LEARNING_MODEL_VERSION,
    LearningHold,
    LocalShadowLearningStore,
    validate_learning_event,
    validate_learning_input,
    validate_learning_record,
)

ROOT = Path(__file__).resolve().parents[1]
OBSERVED_AT = "2026-09-06T13:00:00Z"
LEARNED_AT = "2026-09-06T13:01:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def analytics_snapshot(*, platform="FACEBOOK_PAGE") -> LocalAnalyticsSnapshot:
    base = LocalAnalyticsSnapshot(
        snapshot_id="pending",
        snapshot_hash="0" * 64,
        model_version=ANALYTICS_MODEL_VERSION,
        engine_version=ANALYTICS_ENGINE_VERSION,
        receipt_id="pdr_" + h("receipt46")[:24],
        receipt_hash=h("receipt46"),
        outbox_item_id="obi_" + h("outbox46")[:24],
        outbox_item_hash=h("outbox46"),
        platform=platform,
        mode="TEXT_CARD",
        request_id="cp45-source-046",
        observed_at_utc=OBSERVED_AT,
        publisher_attempted_at_utc="2026-09-06T12:57:00Z",
        local_receipt_age_seconds=180,
        publisher_state="DRY_RUN_RECORDED",
        execution_mode="LOCAL_DRY_RUN",
        external_analytics_state="NOT_CONNECTED",
        external_metrics=_not_connected_metrics(),
        derived_metrics_state="NOT_COMPUTABLE_NOT_CONNECTED",
        performance_evidence_ready=False,
        learning_input_ready=True,
        learning_scope="LOCAL_OPERATIONAL_TELEMETRY_ONLY",
    )
    digest = analytics_hash(_snapshot_body_from_snapshot(base))
    return replace(base, snapshot_hash=digest, snapshot_id="ans_" + digest[:24])


def test_clean_m10_snapshot_produces_shadow_learning_record_only():
    snapshot = analytics_snapshot()
    validate_learning_input(snapshot)
    store = LocalShadowLearningStore.memory()
    try:
        record = store.create_record(snapshot, request_id="cp46-learning-001", learned_at_utc=LEARNED_AT)
        validate_learning_record(record)
        assert record.model_version == LEARNING_MODEL_VERSION
        assert record.snapshot_hash == snapshot.snapshot_hash
        assert record.observation_scope == "LOCAL_OPERATIONAL_TELEMETRY_ONLY"
        assert record.performance_evidence_state == "UNAVAILABLE_NOT_CONNECTED"
        assert record.performance_conclusion == "NO_PERFORMANCE_CONCLUSION"
        assert record.optimization_recommendation == "NO_OPTIMIZATION_RECOMMENDATION"
        assert record.experiment_input_ready is True
        assert record.experiment_scope == "LOCAL_CONTROL_VALIDATION_ONLY"
        assert record.external_experiment_ready is False
        assert record.local_learning_authority is True
        assert not any((record.performance_learning_authority, record.strategy_mutation_authority,
                        record.experiment_execution_authority, record.network_authority,
                        record.account_connection_authority, record.publish_authority, record.deploy_authority))
        events = store.events_for(record)
        assert len(events) == 1
        validate_learning_event(events[0])
        assert events[0].outcome == "NO_PERFORMANCE_CONCLUSION"
    finally:
        store.close()


@pytest.mark.parametrize("platform", ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"])
def test_exact_active_platform_set_is_supported(platform):
    store = LocalShadowLearningStore.memory()
    try:
        record = store.create_record(
            analytics_snapshot(platform=platform),
            request_id="cp46-" + platform.lower(),
            learned_at_utc=LEARNED_AT,
        )
        assert record.platform == platform
        assert record.performance_conclusion == "NO_PERFORMANCE_CONCLUSION"
    finally:
        store.close()


def test_performance_evidence_cannot_be_invented_from_not_connected_snapshot():
    snapshot = replace(analytics_snapshot(), performance_evidence_ready=True)
    with pytest.raises(LearningHold, match="HOLD_M10_SNAPSHOT_INVALID"):
        validate_learning_input(snapshot)


def test_learning_cannot_predate_analytics_observation():
    store = LocalShadowLearningStore.memory()
    try:
        with pytest.raises(LearningHold, match="HOLD_LEARNING_BEFORE_ANALYTICS_OBSERVATION"):
            store.create_record(
                analytics_snapshot(), request_id="cp46-time-order", learned_at_utc="2026-09-06T12:59:59Z"
            )
    finally:
        store.close()


def test_retry_is_idempotent_for_exact_snapshot_request_and_timestamp():
    snapshot = analytics_snapshot()
    store = LocalShadowLearningStore.memory()
    try:
        first = store.create_record(snapshot, request_id="cp46-retry-001", learned_at_utc=LEARNED_AT)
        retry = store.create_record(snapshot, request_id="cp46-retry-001", learned_at_utc=LEARNED_AT)
        assert retry == first
        assert store.records() == (first,)
        assert len(store.events_for(first)) == 1
    finally:
        store.close()


def test_request_id_reuse_with_timestamp_drift_fails_closed():
    snapshot = analytics_snapshot()
    store = LocalShadowLearningStore.memory()
    try:
        store.create_record(snapshot, request_id="cp46-reuse-001", learned_at_utc=LEARNED_AT)
        with pytest.raises(LearningHold, match="HOLD_LEARNING_REQUEST_ID_REUSE_MISMATCH"):
            store.create_record(snapshot, request_id="cp46-reuse-001", learned_at_utc="2026-09-06T13:02:00Z")
    finally:
        store.close()


def test_same_snapshot_cannot_create_second_learning_record():
    snapshot = analytics_snapshot()
    store = LocalShadowLearningStore.memory()
    try:
        store.create_record(snapshot, request_id="cp46-dedup-001", learned_at_utc=LEARNED_AT)
        with pytest.raises(LearningHold, match="HOLD_M10_SNAPSHOT_ALREADY_LEARNED"):
            store.create_record(snapshot, request_id="cp46-dedup-002", learned_at_utc=LEARNED_AT)
        assert len(store.records()) == 1
    finally:
        store.close()


def test_record_tamper_cannot_create_performance_or_optimization_claim():
    store = LocalShadowLearningStore.memory()
    try:
        record = store.create_record(analytics_snapshot(), request_id="cp46-tamper-001", learned_at_utc=LEARNED_AT)
        with pytest.raises(LearningHold, match="HOLD_LEARNING_FALSE_PERFORMANCE_CONCLUSION"):
            validate_learning_record(replace(record, performance_conclusion="FACEBOOK_WINS"))
        with pytest.raises(LearningHold, match="HOLD_LEARNING_FALSE_OPTIMIZATION_RECOMMENDATION"):
            validate_learning_record(replace(record, optimization_recommendation="POST_MORE"))
    finally:
        store.close()


def test_learning_tables_and_event_log_are_append_only():
    store = LocalShadowLearningStore.memory()
    try:
        record = store.create_record(analytics_snapshot(), request_id="cp46-append-001", learned_at_utc=LEARNED_AT)
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("UPDATE learning_records SET learned_at_utc='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            store.connection.execute("DELETE FROM learning_events")
        assert len(store.events_for(record)) == 1
    finally:
        store.close()


def test_learning_source_has_no_network_or_external_client_path():
    source = inspect.getsource(learning_module)
    for token in ("import requests", "import httpx", "import aiohttp", "urllib.request", "http.client", "socket.", "urlopen("):
        assert token not in source


def test_cp46_policy_is_local_shadow_only_and_advances_to_experiments():
    policy = json.loads((ROOT / "config" / "learning_policy.json").read_text())
    assert policy["checkpoint"] == "CP46"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["input_contract"]["required_module"] == "M10_ANALYTICS"
    assert policy["input_contract"]["require_learning_input_ready"] is True
    assert policy["input_contract"]["require_performance_evidence_ready"] is False
    assert policy["learning"]["mode"] == "LOCAL_SHADOW_LEARNING_ONLY"
    assert policy["learning"]["performance_conclusion"] == "NO_PERFORMANCE_CONCLUSION"
    assert policy["learning"]["optimization_recommendation"] == "NO_OPTIMIZATION_RECOMMENDATION"
    assert policy["learning"]["auto_strategy_mutation"] is False
    assert policy["experiment_handoff"]["scope"] == "LOCAL_CONTROL_VALIDATION_ONLY"
    assert policy["experiment_handoff"]["external_experiment_ready"] is False
    assert policy["storage"]["backend"] == "SQLITE_LOCAL"
    assert policy["storage"]["learning_records_append_only"] is True
    assert policy["storage"]["event_log_append_only"] is True
    assert policy["privacy"]["aggregate_content_level_only"] is True
    assert policy["privacy"]["individual_profiling"] is False
    assert policy["privacy"]["demographic_dimensions"] is False
    assert policy["authority"]["local_learning_authority"] is True
    for key in ("performance_learning_authority", "strategy_mutation_authority", "experiment_execution_authority",
                "network_authority", "real_account_connection_authority", "publish_authority", "deploy_authority"):
        assert policy["authority"][key] is False
    assert policy["platform_policy"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["platform_policy"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["platform_policy"]["BLUESKY"] == "HOLD_ROI"
    assert policy["next_dependency"] == "M14_EXPERIMENTS"
