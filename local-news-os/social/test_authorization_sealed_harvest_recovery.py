#!/usr/bin/env python3
"""Acceptance tests for authorization-sealed harvest recovery/reconciliation."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import authorization_sealed_harvest_recovery as recovery
import metrics_harvest_runtime as runtime

scheduler = runtime.metrics_harvest_scheduler
collector = runtime.observed_metrics_collector
FP1 = "sha256:" + "1" * 64
FP2 = "sha256:" + "2" * 64


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
    return {"status": "VALID", "facebook_ready": True, "instagram_ready": True, "secret_material_persisted": False}


def plan(ch: dict, now: str = "2026-08-16T10:00:00Z") -> dict:
    value = scheduler.plan_harvest(ch, publication_state(ch), attestation(), now=now)
    assert value["status"] == "HARVEST_READY", value
    assert len(value["jobs"]) == 1, value
    return value


def job(ch: dict) -> dict:
    return plan(ch)["jobs"][0]


def read_state(root: Path, ch: dict) -> dict:
    return json.loads((root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8"))


def make_recovery(root: Path, ch: dict, jb: dict, fp: str = FP1) -> dict:
    first = receipt.claim_checkpoint_sealed(root, ch, jb, authorization_fingerprint=fp, now="2026-08-16T10:00:00Z", lease_minutes=15)
    assert first["claimed"] is True, first
    started = receipt.mark_network_started(root, ch, jb, authorization_fingerprint=fp, now="2026-08-16T10:00:00Z")
    assert started["persisted"] is True, started
    expired = receipt.claim_checkpoint_sealed(root, ch, jb, authorization_fingerprint=fp, now="2026-08-16T10:16:00Z", lease_minutes=15)
    assert expired["status"] == "RECOVERY_REQUIRED", expired
    return expired


def persist_observation(root: Path, ch: dict, jb: dict, observed_at: str, *, remote_id: str | None = None) -> dict:
    pub = copy.deepcopy(jb["publication"])
    if remote_id is not None:
        pub["remote_publication_id"] = remote_id
    bundle = collector.materialize_bundle(
        ch,
        pub,
        {"metrics": {"impressions": 120, "reach": 90, "shares": 7}},
        source=jb["source"],
        observed_at=observed_at,
        collected_at=observed_at,
        window_start_at=pub["published_at"],
        window_end_at=observed_at,
        now=observed_at,
        min_samples=2,
    )
    assert not bundle.get("hard_blocks"), bundle
    persisted = collector.persist_bundle(root, bundle)
    assert persisted["persisted"] is True, persisted
    return bundle


def test_exact_durable_observation_recovers_without_provider_read() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        assert result["status"] == "RECOVERED_COMPLETED", result
        assert result["recovery_evidence"]["kind"] == "EXACT_ATTEMPT_OBSERVATION", result
        assert result["guards"]["provider_network_calls_performed"] is False
        entry = next(iter(read_state(root, ch)["entries"].values()))
        assert entry["status"] == "COMPLETED"
        assert receipt.validate_sealed_entry(entry, FP1)["valid"] is True


def test_later_cumulative_observation_recovers_without_reread() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T11:00:00Z")
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T11:05:00Z")
        assert result["status"] == "RECOVERED_COMPLETED", result
        assert result["recovery_evidence"]["kind"] == "CUMULATIVE_COVERAGE_OBSERVATION"
        assert result["provider_reread_authorized"] is False


def test_missing_observation_stays_recovery_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        before = read_state(root, ch)
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        after = read_state(root, ch)
        assert result["status"] == "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION", result
        assert result["provider_reread_authorized"] is False
        assert before == after
        assert next(iter(after["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_legacy_direct_reread_flag_is_fail_closed_and_handoff_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        before = read_state(root, ch)
        result = recovery.reconcile_recovery(
            root, ch, jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:20:00Z",
            authorize_provider_reread=True,
        )
        after = read_state(root, ch)
        assert result["status"] == "HOLD_EXPLICIT_REREAD_HANDOFF_REQUIRED", result
        assert result["hard_blocks"] == ["EXPLICIT_PROVIDER_REREAD_HANDOFF_REQUIRED"]
        assert result["provider_reread_authorized"] is False
        assert result["guards"]["explicit_reread_handoff_required"] is True
        assert before == after
        assert next(iter(after["entries"].values()))["status"] == "RECOVERY_REQUIRED"
        reclaimed = receipt.claim_checkpoint_sealed(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        assert reclaimed["claimed"] is False, reclaimed
        assert reclaimed["status"] == "RECOVERY_REQUIRED", reclaimed


def test_earlier_observation_does_not_cover_due_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T08:30:00Z")
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        assert result["status"] == "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION", result


def test_authorization_drift_fails_before_ledger_reconciliation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP2, now="2026-08-16T10:20:00Z", authorize_provider_reread=True)
        assert result["status"] == "HOLD_RECOVERY_AUTHORIZATION_CHANGED", result
        assert result["provider_reread_authorized"] is False


def test_receipt_and_observation_store_tamper_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(path.read_text(encoding="utf-8"))
        next(iter(state["entries"].values()))["execution_receipts"][-1]["updated_at"] = "2026-08-16T10:17:00Z"
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        path.write_text(json.dumps(state), encoding="utf-8")
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z", authorize_provider_reread=True)
        assert result["status"] == "HOLD_RECOVERY_RECEIPT_TAMPERED", result
        assert "SEALED_RECEIPT_FINGERPRINT_MISMATCH" in result["hard_blocks"]
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        path = root / collector.expected_observation_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        store["observations"][0]["metrics"]["impressions"] = 999999
        path.write_text(json.dumps(store), encoding="utf-8")
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z", authorize_provider_reread=True)
        assert result["status"] == "HOLD_RECOVERY_OBSERVATION_LEDGER", result


def test_remote_proof_conflict_and_cross_instance_store_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        bad = copy.deepcopy(jb)
        bad["publication"]["remote_publication_id"] = "different_remote"
        persist_observation(root, ch, bad, "2026-08-16T10:00:00Z")
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z", authorize_provider_reread=True)
        assert result["status"] == "HOLD_RECOVERY_OBSERVATION_CONFLICT", result
        assert "RECOVERY_OBSERVATION_REMOTE_PROOF_CONFLICT" in result["hard_blocks"]
    with tempfile.TemporaryDirectory() as tmp:
        root, alpha = Path(tmp), channel(instance="alpha")
        alpha_job = job(alpha)
        make_recovery(root, alpha, alpha_job)
        beta = channel(instance="beta")
        beta_job = job(beta)
        bundle = collector.materialize_bundle(
            beta, beta_job["publication"], {"metrics": {"impressions": 10, "reach": 8}},
            source=beta_job["source"], observed_at="2026-08-16T10:00:00Z", collected_at="2026-08-16T10:00:00Z",
            window_start_at=beta_job["publication"]["published_at"], window_end_at="2026-08-16T10:00:00Z", now="2026-08-16T10:00:00Z", min_samples=2,
        )
        target = root / collector.expected_observation_store_path(alpha)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(bundle["observation_store"]), encoding="utf-8")
        result = recovery.reconcile_recovery(root, alpha, alpha_job, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        assert result["status"] == "HOLD_RECOVERY_OBSERVATION_LEDGER", result


def test_zero_paid_and_job_fingerprint_tamper_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = channel()
        jb = job(good)
        make_recovery(root, good, jb)
        bad = copy.deepcopy(good)
        bad["zero_paid_dependency"] = False
        result = recovery.reconcile_recovery(root, bad, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z", authorize_provider_reread=True)
        assert result["status"] == "HOLD_RECOVERY_JOB", result
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"]
        tampered = copy.deepcopy(jb)
        tampered["checkpoint"]["checkpoint_at"] = "2026-08-16T09:01:00Z"
        result = recovery.reconcile_recovery(root, good, tampered, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        assert result["status"] == "HOLD_RECOVERY_JOB", result
        assert "RECOVERY_JOB_FINGERPRINT_MISMATCH" in result["hard_blocks"]


def test_recovered_checkpoint_is_idempotently_terminal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        first = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        second = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:21:00Z", authorize_provider_reread=True)
        assert first["status"] == "RECOVERED_COMPLETED", first
        assert second["status"] == "ALREADY_COMPLETED", second
        assert second["provider_reread_authorized"] is False


def test_output_state_and_evidence_are_secret_free_and_deterministic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        result = recovery.reconcile_recovery(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z", authorize_provider_reread=True)
        text = json.dumps(result, ensure_ascii=False) + (root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8")
        assert '"credential_value":' not in text
        assert '"access_token":' not in text.lower()
        assert result["guards"]["credential_values_read"] is False
        assert result["guards"]["provider_payload_persisted"] is False
    evidence_a = recovery._recovery_evidence(kind="NO_DURABLE_COVERAGE_OBSERVATION", store=None, observation=None, checked_at="2026-08-16T10:20:00Z", provider_reread_authorized=False)
    evidence_b = recovery._recovery_evidence(kind="NO_DURABLE_COVERAGE_OBSERVATION", store=None, observation=None, checked_at="2026-08-16T10:20:00Z", provider_reread_authorized=False)
    assert evidence_a == evidence_b
    assert len(evidence_a["recovery_evidence_fingerprint_sha256"]) == 64


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS authorization-sealed harvest recovery acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
