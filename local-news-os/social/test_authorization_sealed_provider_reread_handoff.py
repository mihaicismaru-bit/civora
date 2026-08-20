#!/usr/bin/env python3
"""Acceptance tests for explicit single-use provider re-read authorization handoffs."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import authorization_sealed_provider_reread_handoff as handoff
import metrics_harvest_runtime as runtime

scheduler = runtime.metrics_harvest_scheduler
collector = runtime.observed_metrics_collector
FP1 = "sha256:" + "1" * 64
FP2 = "sha256:" + "2" * 64
REASON = "AMBIGUOUS_PROVIDER_READ_RETRY_APPROVED"


def channel(platform: str = "facebook", instance: str = "alpha", **overrides) -> dict:
    source = "meta_graph_api" if platform == "facebook" else "instagram_graph_api"
    value = {
        "schema_version": "1.0",
        "instance_id": instance,
        "channel_id": f"{instance}-{platform}",
        "platform": platform,
        "status": "active",
        "credentials_ref": f"github-actions-secret:{instance.upper()}_{platform.upper()}_ACCESS_TOKEN",
        "publication_state": {
            "outbox_path": f"{instance}/social/{platform}_outbox.json",
            "state_path": f"{instance}/social/{platform}_state.json",
            "dedupe_by_id": True,
            "last_known_good": True,
        },
        "metrics": {"observed_only": True, "sources": [source]},
        "zero_paid_dependency": True,
    }
    value.update(overrides)
    return value


def publication(platform: str = "facebook", instance: str = "alpha", idx: int = 1) -> dict:
    return {
        "instance_id": instance,
        "channel_id": f"{instance}-{platform}",
        "platform": platform,
        "status": "PUBLISHED",
        "publication_id": f"publication:{platform}:{idx}",
        "remote_publication_id": f"remote_{platform}_{idx}",
        "story_id": f"story:{idx}",
        "product_id": f"product:{platform}:{idx}",
        "published_at": "2026-08-16T08:00:00Z",
        "native_format": "single_photo",
        "topic_keys": ["service_journalism"],
        "series_id": None,
    }


def publication_state(ch: dict) -> dict:
    pub = publication(ch["platform"], ch["instance_id"])
    return {
        "schema_version": "1.0",
        "instance_id": ch["instance_id"],
        "channel_id": ch["channel_id"],
        "platform": ch["platform"],
        "records": {pub["publication_id"]: pub},
    }


def attestation() -> dict:
    return {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }


def job(ch: dict) -> dict:
    plan = scheduler.plan_harvest(ch, publication_state(ch), attestation(), now="2026-08-16T10:00:00Z")
    assert plan["status"] == "HARVEST_READY", plan
    assert len(plan["jobs"]) == 1, plan
    return plan["jobs"][0]


def read_checkpoint(root: Path, ch: dict) -> dict:
    return json.loads((root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8"))


def read_handoffs(root: Path, ch: dict) -> dict:
    return json.loads((root / handoff.expected_handoff_store_path(ch)).read_text(encoding="utf-8"))


def make_recovery(root: Path, ch: dict, jb: dict, fp: str = FP1) -> None:
    first = receipt.claim_checkpoint_sealed(
        root, ch, jb, authorization_fingerprint=fp, now="2026-08-16T10:00:00Z", lease_minutes=15,
    )
    assert first["claimed"] is True, first
    started = receipt.mark_network_started(
        root, ch, jb, authorization_fingerprint=fp, now="2026-08-16T10:00:00Z",
    )
    assert started["persisted"] is True, started
    expired = receipt.claim_checkpoint_sealed(
        root, ch, jb, authorization_fingerprint=fp, now="2026-08-16T10:16:00Z", lease_minutes=15,
    )
    assert expired["status"] == "RECOVERY_REQUIRED", expired


def issue(root: Path, ch: dict, jb: dict, *, decision: str = "incident:alpha:1", now: str = "2026-08-16T10:20:00Z", ttl: int = 30) -> dict:
    return handoff.issue_provider_reread_handoff(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        decision_reference=decision,
        reason_code=REASON,
        now=now,
        ttl_minutes=ttl,
    )


def persist_observation(root: Path, ch: dict, jb: dict, observed_at: str) -> None:
    bundle = collector.materialize_bundle(
        ch,
        jb["publication"],
        {"metrics": {"impressions": 120, "reach": 90, "shares": 7}},
        source=jb["source"],
        observed_at=observed_at,
        collected_at=observed_at,
        window_start_at=jb["publication"]["published_at"],
        window_end_at=observed_at,
        now=observed_at,
        min_samples=2,
    )
    assert not bundle.get("hard_blocks"), bundle
    persisted = collector.persist_bundle(root, bundle)
    assert persisted["persisted"] is True, persisted


def test_issue_is_durable_but_does_not_make_provider_reread_eligible() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        result = issue(root, ch, jb)
        assert result["status"] == "REREAD_HANDOFF_AUTHORIZED", result
        assert result["provider_reread_eligible"] is False
        assert result["provider_network_calls_performed"] is False
        checkpoint = next(iter(read_checkpoint(root, ch)["entries"].values()))
        assert checkpoint["status"] == "RECOVERY_REQUIRED", checkpoint
        store = read_handoffs(root, ch)
        assert handoff.validate_handoff_store(ch, store)["valid"] is True, store
        authorized = store["entries"][result["handoff_id"]]
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["target_attempt"] == 2


def test_same_explicit_decision_is_idempotent_and_does_not_refresh_authorization() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        first = issue(root, ch, jb)
        before = read_handoffs(root, ch)
        second = issue(root, ch, jb, now="2026-08-16T10:21:00Z")
        after = read_handoffs(root, ch)
        assert second["status"] == "REREAD_HANDOFF_ALREADY_AUTHORIZED", second
        assert second["handoff_id"] == first["handoff_id"]
        assert before == after
        assert second["handoff"]["issued_at"] == "2026-08-16T10:20:00Z"


def test_distinct_live_authorization_for_same_checkpoint_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        first = issue(root, ch, jb, decision="incident:alpha:1")
        assert first["status"] == "REREAD_HANDOFF_AUTHORIZED", first
        second = issue(root, ch, jb, decision="incident:alpha:2", now="2026-08-16T10:21:00Z")
        assert second["status"] == "HOLD_REREAD_HANDOFF_ACTIVE_EXISTS", second
        assert "REREAD_HANDOFF_ACTIVE_AUTHORIZATION_EXISTS" in second["hard_blocks"]


def test_consumption_is_single_use_and_only_then_makes_retry_eligible() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        consumed = handoff.consume_provider_reread_handoff(
            root,
            ch,
            jb,
            handoff_id=issued["handoff_id"],
            authorization_fingerprint=FP1,
            now="2026-08-16T10:22:00Z",
        )
        assert consumed["status"] == "REREAD_HANDOFF_CONSUMED", consumed
        assert consumed["provider_reread_eligible"] is True
        assert consumed["provider_network_calls_performed"] is False
        checkpoint = next(iter(read_checkpoint(root, ch)["entries"].values()))
        assert checkpoint["status"] == "RETRY_WAIT", checkpoint
        store = read_handoffs(root, ch)
        assert store["entries"][issued["handoff_id"]]["status"] == "CONSUMED"
        reclaimed = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert reclaimed["claimed"] is True, reclaimed
        assert reclaimed["entry"]["attempt"] == 2, reclaimed


def test_consumed_handoff_cannot_be_reused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        first = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert first["status"] == "REREAD_HANDOFF_CONSUMED", first
        before = read_handoffs(root, ch)
        second = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:23:00Z",
        )
        after = read_handoffs(root, ch)
        assert second["status"] == "REREAD_HANDOFF_ALREADY_CONSUMED", second
        assert second["provider_reread_eligible"] is False
        assert before == after


def test_handoff_expires_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb, ttl=1)
        result = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_EXPIRED", result
        assert next(iter(read_checkpoint(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_authorization_fingerprint_drift_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        result = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP2, now="2026-08-16T10:22:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_AUTHORIZATION_CHANGED", result
        assert result["provider_reread_eligible"] is False


def test_receipt_drift_after_issue_rejected_before_retry_eligibility() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(path.read_text(encoding="utf-8"))
        entry = next(iter(state["entries"].values()))
        entry["execution_receipts"][-1]["updated_at"] = "2026-08-16T10:17:00Z"
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        path.write_text(json.dumps(state), encoding="utf-8")
        result = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_RECOVERY", result
        assert result["provider_reread_eligible"] is False


def test_handoff_store_tamper_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        path = root / handoff.expected_handoff_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        store["entries"][issued["handoff_id"]]["target_attempt"] = 99
        path.write_text(json.dumps(store), encoding="utf-8")
        result = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_STORE", result
        assert any("FINGERPRINT" in code for code in result["hard_blocks"]), result


def test_new_durable_observation_after_issue_cancels_need_for_reread() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:21:00Z")
        result = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert result["status"] == "NO_REREAD_NEEDED_DURABLE_OBSERVATION", result
        assert result["provider_reread_eligible"] is False
        assert next(iter(read_checkpoint(root, ch)["entries"].values()))["status"] == "COMPLETED"


def test_cross_instance_handoff_store_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        alpha, beta = channel(instance="alpha"), channel(instance="beta")
        alpha_job, beta_job = job(alpha), job(beta)
        make_recovery(root, alpha, alpha_job)
        make_recovery(root, beta, beta_job)
        issued = issue(root, alpha, alpha_job)
        alpha_store = read_handoffs(root, alpha)
        beta_path = root / handoff.expected_handoff_store_path(beta)
        beta_path.parent.mkdir(parents=True, exist_ok=True)
        beta_path.write_text(json.dumps(alpha_store), encoding="utf-8")
        result = handoff.consume_provider_reread_handoff(
            root, beta, beta_job, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_STORE", result
        assert any("INSTANCE_MISMATCH" in code for code in result["hard_blocks"]), result


def test_checkpoint_persistence_failure_after_consumption_fails_closed_without_reusable_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)

        def fail_checkpoint(*args, **kwargs):
            return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE_CAS_CONFLICT", "hard_blocks": ["CHECKPOINT_STATE_COMPARE_AND_SWAP_CONFLICT"]}

        result = handoff.consume_provider_reread_handoff(
            root,
            ch,
            jb,
            handoff_id=issued["handoff_id"],
            authorization_fingerprint=FP1,
            now="2026-08-16T10:22:00Z",
            checkpoint_persist_call=fail_checkpoint,
        )
        assert result["status"] == "HOLD_REREAD_CHECKPOINT_AFTER_HANDOFF_CONSUMED", result
        assert result["handoff_consumed"] is True
        assert result["provider_reread_eligible"] is False
        assert next(iter(read_checkpoint(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"
        store = read_handoffs(root, ch)
        assert store["entries"][issued["handoff_id"]]["status"] == "CONSUMED"
        again = handoff.consume_provider_reread_handoff(
            root, ch, jb, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:23:00Z",
        )
        assert again["status"] == "REREAD_HANDOFF_ALREADY_CONSUMED", again


def test_job_fingerprint_drift_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        changed = copy.deepcopy(jb)
        changed["publication"]["native_format"] = "text"
        unsigned = copy.deepcopy(changed)
        unsigned.pop("job_fingerprint_sha256", None)
        changed["job_fingerprint_sha256"] = runtime._digest(unsigned)
        result = handoff.consume_provider_reread_handoff(
            root, ch, changed, handoff_id=issued["handoff_id"], authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z",
        )
        assert result["status"] in {"HOLD_REREAD_HANDOFF_JOB_CHANGED", "HOLD_REREAD_HANDOFF_CHECKPOINT"}, result
        assert result["provider_reread_eligible"] is False


def test_zero_paid_dependency_violation_cannot_issue_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        unsafe = copy.deepcopy(ch)
        unsafe["zero_paid_dependency"] = False
        result = handoff.issue_provider_reread_handoff(
            root,
            unsafe,
            jb,
            authorization_fingerprint=FP1,
            decision_reference="incident:alpha:1",
            reason_code=REASON,
            now="2026-08-16T10:20:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_RECOVERY", result
        assert any("ZERO_PAID_DEPENDENCY" in code for code in result["hard_blocks"]), result


def test_invalid_reason_code_is_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        result = handoff.issue_provider_reread_handoff(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            decision_reference="incident:alpha:1",
            reason_code="JUST_RETRY_IT",
            now="2026-08-16T10:20:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_DECISION", result
        assert result["provider_reread_eligible"] is False


def test_handoff_store_contains_no_credential_values_or_provider_payload() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        assert issued["status"] == "REREAD_HANDOFF_AUTHORIZED", issued
        encoded = json.dumps(read_handoffs(root, ch), sort_keys=True).lower()
        assert "super-secret-token" not in encoded
        assert "provider_payload" not in encoded
        assert "access_token_value" not in encoded
        assert "credential_value" not in encoded


def run() -> None:
    tests = [
        test_issue_is_durable_but_does_not_make_provider_reread_eligible,
        test_same_explicit_decision_is_idempotent_and_does_not_refresh_authorization,
        test_distinct_live_authorization_for_same_checkpoint_is_rejected,
        test_consumption_is_single_use_and_only_then_makes_retry_eligible,
        test_consumed_handoff_cannot_be_reused,
        test_handoff_expires_fail_closed,
        test_authorization_fingerprint_drift_rejected,
        test_receipt_drift_after_issue_rejected_before_retry_eligibility,
        test_handoff_store_tamper_rejected,
        test_new_durable_observation_after_issue_cancels_need_for_reread,
        test_cross_instance_handoff_store_is_rejected,
        test_checkpoint_persistence_failure_after_consumption_fails_closed_without_reusable_handoff,
        test_job_fingerprint_drift_rejected,
        test_zero_paid_dependency_violation_cannot_issue_handoff,
        test_invalid_reason_code_is_fail_closed,
        test_handoff_store_contains_no_credential_values_or_provider_payload,
    ]
    for test in tests:
        test()
    print(f"PROVIDER_REREAD_HANDOFF_ACCEPTANCE_PASS {len(tests)}")


if __name__ == "__main__":
    run()
