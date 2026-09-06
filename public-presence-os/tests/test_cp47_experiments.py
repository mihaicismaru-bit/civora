from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sqlite3

import pytest

import public_presence_os.experiments as experiments_module
from public_presence_os.experiments import (
    CONTROL_CHECKS,
    EXPERIMENT_MODEL_VERSION,
    ExperimentHold,
    LocalControlExperimentLedger,
    validate_experiment_event,
    validate_experiment_input,
    validate_experiment_plan,
)
from public_presence_os.learning import (
    LEARNING_ENGINE_VERSION,
    LEARNING_MODEL_VERSION,
    ShadowLearningRecord,
    _hash as learning_hash,
    _record_body_from_record,
    validate_learning_record,
)

ROOT = Path(__file__).resolve().parents[1]
LEARNED_AT = "2026-09-06T14:01:00Z"
CREATED_AT = "2026-09-06T14:02:00Z"


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def learning_record(*, platform: str = "FACEBOOK_PAGE") -> ShadowLearningRecord:
    base = ShadowLearningRecord(
        record_id="pending",
        record_hash="0" * 64,
        model_version=LEARNING_MODEL_VERSION,
        engine_version=LEARNING_ENGINE_VERSION,
        snapshot_id="ans_" + h("snapshot47")[:24],
        snapshot_hash=h("snapshot47"),
        receipt_id="pdr_" + h("receipt47")[:24],
        receipt_hash=h("receipt47"),
        platform=platform,
        request_id="cp46-source-047",
        learned_at_utc=LEARNED_AT,
        source_observed_at_utc="2026-09-06T14:00:00Z",
        local_receipt_age_seconds=180,
        observation_scope="LOCAL_OPERATIONAL_TELEMETRY_ONLY",
        observations=(
            "LOCAL_DRY_RUN_RECEIPT_TELEMETRY_PRESENT",
            "LOCAL_RECEIPT_AGE_SECONDS:180",
            "REMOTE_ANALYTICS_NOT_CONNECTED",
            "PERFORMANCE_EVIDENCE_UNAVAILABLE",
        ),
        performance_evidence_state="UNAVAILABLE_NOT_CONNECTED",
        performance_conclusion="NO_PERFORMANCE_CONCLUSION",
        optimization_recommendation="NO_OPTIMIZATION_RECOMMENDATION",
        experiment_input_ready=True,
        experiment_scope="LOCAL_CONTROL_VALIDATION_ONLY",
        external_experiment_ready=False,
    )
    digest = learning_hash(_record_body_from_record(base))
    return replace(base, record_hash=digest, record_id="lrn_" + digest[:24])


def test_clean_m11_record_produces_local_control_experiment_plan_only():
    record = learning_record()
    validate_learning_record(record)
    validate_experiment_input(record)
    ledger = LocalControlExperimentLedger.memory()
    try:
        plan = ledger.create_plan(record, request_id="cp47-plan-001", created_at_utc=CREATED_AT)
        validate_experiment_plan(plan)
        assert plan.model_version == EXPERIMENT_MODEL_VERSION
        assert plan.learning_record_hash == record.record_hash
        assert plan.mode == "LOCAL_CONTROL_VALIDATION_ONLY"
        assert plan.control_checks == CONTROL_CHECKS
        assert plan.performance_evidence_state == "UNAVAILABLE_NOT_CONNECTED"
        assert plan.performance_hypothesis == "NO_PERFORMANCE_HYPOTHESIS"
        assert plan.optimization_recommendation == "NO_OPTIMIZATION_RECOMMENDATION"
        assert plan.content_variant_count == 0
        assert plan.performance_metric is None
        assert plan.audience_segment is None
        assert plan.local_control_validation_ready is True
        assert plan.external_experiment_ready is False
        assert plan.local_experiment_ledger_authority is True
        assert plan.local_control_plan_authority is True
        assert not any((
            plan.performance_experiment_authority,
            plan.content_mutation_authority,
            plan.strategy_mutation_authority,
            plan.network_authority,
            plan.account_connection_authority,
            plan.queue_authority,
            plan.publish_authority,
            plan.deploy_authority,
        ))
        events = ledger.events_for(plan)
        assert len(events) == 1
        validate_experiment_event(events[0])
        assert events[0].outcome == "CONTROL_PLAN_RECORDED_NOT_EXTERNALLY_EXECUTED"
    finally:
        ledger.close()


@pytest.mark.parametrize("platform", ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"])
def test_exact_active_platform_set_is_supported(platform):
    ledger = LocalControlExperimentLedger.memory()
    try:
        plan = ledger.create_plan(
            learning_record(platform=platform),
            request_id="cp47-" + platform.lower(),
            created_at_utc=CREATED_AT,
        )
        assert plan.platform == platform
        assert plan.content_variant_count == 0
    finally:
        ledger.close()


def test_performance_claim_cannot_enter_experiment_input():
    record = replace(learning_record(), performance_conclusion="FACEBOOK_WINS")
    with pytest.raises(ExperimentHold, match="HOLD_M11_LEARNING_RECORD_INVALID"):
        validate_experiment_input(record)


def test_external_experiment_readiness_cannot_be_invented():
    record = replace(learning_record(), external_experiment_ready=True)
    with pytest.raises(ExperimentHold, match="HOLD_M11_LEARNING_RECORD_INVALID"):
        validate_experiment_input(record)


def test_experiment_plan_cannot_predate_learning_record():
    ledger = LocalControlExperimentLedger.memory()
    try:
        with pytest.raises(ExperimentHold, match="HOLD_EXPERIMENT_BEFORE_LEARNING_RECORD"):
            ledger.create_plan(
                learning_record(),
                request_id="cp47-time-order",
                created_at_utc="2026-09-06T14:00:59Z",
            )
    finally:
        ledger.close()


def test_retry_is_idempotent_for_exact_record_request_and_timestamp():
    record = learning_record()
    ledger = LocalControlExperimentLedger.memory()
    try:
        first = ledger.create_plan(record, request_id="cp47-retry-001", created_at_utc=CREATED_AT)
        retry = ledger.create_plan(record, request_id="cp47-retry-001", created_at_utc=CREATED_AT)
        assert retry == first
        assert ledger.plans() == (first,)
        assert len(ledger.events_for(first)) == 1
    finally:
        ledger.close()


def test_request_id_reuse_with_timestamp_drift_fails_closed():
    record = learning_record()
    ledger = LocalControlExperimentLedger.memory()
    try:
        ledger.create_plan(record, request_id="cp47-reuse-001", created_at_utc=CREATED_AT)
        with pytest.raises(ExperimentHold, match="HOLD_EXPERIMENT_REQUEST_ID_REUSE_MISMATCH"):
            ledger.create_plan(record, request_id="cp47-reuse-001", created_at_utc="2026-09-06T14:03:00Z")
    finally:
        ledger.close()


def test_same_learning_record_cannot_create_second_plan():
    record = learning_record()
    ledger = LocalControlExperimentLedger.memory()
    try:
        ledger.create_plan(record, request_id="cp47-dedup-001", created_at_utc=CREATED_AT)
        with pytest.raises(ExperimentHold, match="HOLD_M11_LEARNING_RECORD_ALREADY_PLANNED"):
            ledger.create_plan(record, request_id="cp47-dedup-002", created_at_utc=CREATED_AT)
        assert len(ledger.plans()) == 1
    finally:
        ledger.close()


def test_plan_tamper_cannot_create_variant_targeting_or_performance_hypothesis():
    ledger = LocalControlExperimentLedger.memory()
    try:
        plan = ledger.create_plan(learning_record(), request_id="cp47-tamper-001", created_at_utc=CREATED_AT)
        with pytest.raises(ExperimentHold, match="HOLD_EXPERIMENT_VARIANT_OR_TARGETING_NOT_ALLOWED"):
            validate_experiment_plan(replace(plan, content_variant_count=2))
        with pytest.raises(ExperimentHold, match="HOLD_EXPERIMENT_VARIANT_OR_TARGETING_NOT_ALLOWED"):
            validate_experiment_plan(replace(plan, audience_segment="high_value_followers"))
        with pytest.raises(ExperimentHold, match="HOLD_EXPERIMENT_FALSE_PERFORMANCE_HYPOTHESIS"):
            validate_experiment_plan(replace(plan, performance_hypothesis="PHOTO_OUTPERFORMS_TEXT"))
    finally:
        ledger.close()


def test_experiment_tables_and_event_log_are_append_only():
    ledger = LocalControlExperimentLedger.memory()
    try:
        plan = ledger.create_plan(learning_record(), request_id="cp47-append-001", created_at_utc=CREATED_AT)
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            ledger.connection.execute("UPDATE experiment_plans SET created_at_utc='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            ledger.connection.execute("DELETE FROM experiment_events")
        assert len(ledger.events_for(plan)) == 1
    finally:
        ledger.close()


def test_experiment_source_has_no_network_or_external_client_path():
    source = inspect.getsource(experiments_module)
    for token in ("import requests", "import httpx", "import aiohttp", "urllib.request", "http.client", "socket.", "urlopen("):
        assert token not in source


def test_cp47_policy_is_local_control_only_and_keeps_external_execution_off():
    policy = json.loads((ROOT / "config" / "experiment_policy.json").read_text())
    assert policy["checkpoint"] == "CP47"
    assert policy["active_platforms"] == ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"]
    assert policy["input_contract"]["required_module"] == "M11_LEARNING"
    assert policy["input_contract"]["require_experiment_input_ready"] is True
    assert policy["input_contract"]["require_external_experiment_ready"] is False
    assert policy["experiment"]["mode"] == "LOCAL_CONTROL_VALIDATION_ONLY"
    assert policy["experiment"]["content_variant_generation"] is False
    assert policy["experiment"]["performance_metric_selection"] is False
    assert policy["experiment"]["audience_segmentation"] is False
    assert policy["storage"]["backend"] == "SQLITE_LOCAL"
    assert policy["storage"]["experiment_plans_append_only"] is True
    assert policy["storage"]["event_log_append_only"] is True
    assert policy["privacy"]["aggregate_content_level_only"] is True
    assert policy["privacy"]["individual_profiling"] is False
    assert policy["privacy"]["demographic_dimensions"] is False
    assert policy["authority"]["local_experiment_ledger_authority"] is True
    assert policy["authority"]["local_control_plan_authority"] is True
    for key in (
        "performance_experiment_authority",
        "content_mutation_authority",
        "strategy_mutation_authority",
        "network_authority",
        "real_account_connection_authority",
        "queue_authority",
        "publish_authority",
        "deploy_authority",
    ):
        assert policy["authority"][key] is False
    assert policy["platform_policy"]["LINKEDIN"] == "PRODUCTION_API_ACCESS_REQUIRED"
    assert policy["platform_policy"]["X"] == "EXCLUDED_WHILE_API_PAID"
    assert policy["platform_policy"]["BLUESKY"] == "HOLD_ROI"
    assert policy["pilot_gate"]["production_identity_equivalence_required"] is True
    assert policy["next_dependency"] == "PILOT_VALIDATION_GATES"
