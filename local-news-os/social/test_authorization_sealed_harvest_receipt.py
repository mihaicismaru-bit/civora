#!/usr/bin/env python3
"""Acceptance tests for authorization-sealed harvest execution receipts."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
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


def publication_state(platform: str = "facebook", instance: str = "alpha", idx: int = 1) -> dict:
    pub = publication(platform, instance, idx)
    return {
        "schema_version": "1.0",
        "instance_id": instance,
        "channel_id": f"{instance}-{platform}",
        "platform": platform,
        "records": {pub["publication_id"]: pub},
    }


def attestation() -> dict:
    return {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }


def plan(ch: dict | None = None, *, now: str = "2026-08-16T10:00:00Z") -> dict:
    ch = ch or channel()
    state = publication_state(ch["platform"], ch["instance_id"])
    result = scheduler.plan_harvest(ch, state, attestation(), now=now)
    assert result["status"] == "HARVEST_READY", result
    assert len(result["jobs"]) == 1, result
    return result


def read_state(root: Path, ch: dict) -> dict:
    return json.loads((root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8"))


def no_data(*args, **kwargs) -> dict:
    return {"status": "NO_OBSERVED_METRICS", "hard_blocks": [], "metric_issues": [], "publication_blocked": False}


def observed_transport(*args, **kwargs) -> dict:
    ch, pub = args[0], args[1]
    now = kwargs["now"]
    bundle = collector.materialize_bundle(
        ch,
        pub,
        {"metrics": {"impressions": 120, "reach": 90, "shares": 7}},
        source=ch["metrics"]["sources"][0],
        observed_at=now,
        collected_at=now,
        window_start_at=pub["published_at"],
        window_end_at=now,
        now=now,
        existing_store=kwargs.get("existing_store"),
        existing_snapshot=kwargs.get("existing_snapshot"),
        ttl_hours=kwargs.get("ttl_hours", 72),
        min_samples=kwargs.get("min_samples", 3),
    )
    assert not bundle.get("hard_blocks"), bundle
    return {
        "status": "COLLECTED_AND_MATERIALIZED",
        "hard_blocks": [],
        "metric_issues": [],
        "publication_blocked": False,
        "materialization": bundle,
    }


def test_no_data_execution_has_final_sealed_receipt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        result = receipt.execute_plan_durably_sealed(
            plan(ch), ch, attestation(), authorization_fingerprint=FP1,
            repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "runtime-token", transport_call=no_data,
        )
        assert result["status"] == "HARVEST_RUNTIME_EXECUTED", result
        assert result["results"][0]["checkpoint_status"] == "COMPLETED_NO_DATA", result
        state = read_state(root, ch)
        entry = next(iter(state["entries"].values()))
        assert entry["authorization_fingerprint"] == FP1, entry
        assert len(entry["execution_receipts"]) == 1, entry
        sealed = entry["execution_receipts"][0]
        assert sealed["status"] == "COMPLETED_NO_DATA", sealed
        assert sealed["network_started_at"] == "2026-08-16T10:00:00Z", sealed
        assert receipt.validate_sealed_entry(entry, FP1)["valid"] is True
        assert result["guards"]["blind_retry_after_ambiguous_sealed_network_call"] is False


def test_network_start_receipt_is_durable_before_transport_call() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        seen: list[str] = []

        def inspect_before_provider(*args, **kwargs):
            state = read_state(root, ch)
            entry = next(iter(state["entries"].values()))
            latest = entry["execution_receipts"][-1]
            assert entry["status"] == "IN_FLIGHT", entry
            assert latest["status"] == "NETWORK_CALL_STARTED", latest
            assert latest["authorization_fingerprint"] == FP1, latest
            seen.append(latest["execution_id"])
            return no_data(*args, **kwargs)

        result = receipt.execute_plan_durably_sealed(
            plan(ch), ch, attestation(), authorization_fingerprint=FP1,
            repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "runtime-token", transport_call=inspect_before_provider,
        )
        assert result["results"][0]["checkpoint_status"] == "COMPLETED_NO_DATA", result
        assert len(seen) == 1, seen


def test_expired_network_started_attempt_requires_recovery_and_never_blind_retries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        first = receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z", lease_minutes=15)
        assert first["claimed"] is True, first
        started = receipt.mark_network_started(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z")
        assert started["persisted"] is True, started
        retry = receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:16:00Z", lease_minutes=15)
        assert retry["claimed"] is False, retry
        assert retry["status"] == "RECOVERY_REQUIRED", retry
        state = read_state(root, ch)
        entry = next(iter(state["entries"].values()))
        assert entry["status"] == "RECOVERY_REQUIRED", entry
        assert entry["attempt"] == 1, entry
        assert entry["execution_receipts"][-1]["provider_result_status"] == "AMBIGUOUS_NETWORK_EXECUTION", entry


def test_expired_claim_without_network_start_is_safely_reclaimable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        first = receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z", lease_minutes=15)
        second = receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:16:00Z", lease_minutes=15)
        assert first["entry"]["attempt"] == 1, first
        assert second["claimed"] is True, second
        assert second["entry"]["attempt"] == 2, second
        assert [row["status"] for row in second["entry"]["execution_receipts"]] == ["CLAIMED", "CLAIMED"], second


def test_authorization_context_change_holds_before_reclaim() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        assert receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z")["claimed"] is True
        changed = receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP2, now="2026-08-16T10:20:00Z")
        assert changed["claimed"] is False, changed
        assert changed["status"] == "HOLD_AUTHORIZATION_CONTEXT_CHANGED", changed


def test_receipt_fingerprint_tamper_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        assert receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z")["claimed"] is True
        path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(path.read_text(encoding="utf-8"))
        entry = next(iter(state["entries"].values()))
        entry["execution_receipts"][-1]["updated_at"] = "2026-08-16T10:00:01Z"
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        path.write_text(json.dumps(state), encoding="utf-8")
        held = receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z")
        assert held["claimed"] is False, held
        assert held["status"] == "HOLD_SEALED_RECEIPT_TAMPERED", held
        assert "SEALED_RECEIPT_FINGERPRINT_MISMATCH" in held["hard_blocks"], held


def test_known_retry_preserves_receipt_history_and_new_attempt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        p = plan(ch)
        calls: list[int] = []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return {"status": "RETRY_LATER", "hard_blocks": [], "metric_issues": [{"code": "TRANSIENT_PROVIDER_FAILURE"}]}
            return no_data(*args, **kwargs)

        first = receipt.execute_plan_durably_sealed(
            p, ch, attestation(), authorization_fingerprint=FP1, repo_root=root,
            now="2026-08-16T10:00:00Z", credential_resolver=lambda name: "token", transport_call=flaky,
        )
        assert first["results"][0]["checkpoint_status"] == "RETRY_WAIT", first
        blocked = receipt.execute_plan_durably_sealed(
            p, ch, attestation(), authorization_fingerprint=FP1, repo_root=root,
            now="2026-08-16T10:05:00Z", credential_resolver=lambda name: "token", transport_call=flaky,
        )
        assert blocked["results"][0]["status"] == "RETRY_WAIT", blocked
        second = receipt.execute_plan_durably_sealed(
            p, ch, attestation(), authorization_fingerprint=FP1, repo_root=root,
            now="2026-08-16T10:16:00Z", credential_resolver=lambda name: "token", transport_call=flaky,
        )
        assert second["results"][0]["checkpoint_status"] == "COMPLETED_NO_DATA", second
        state = read_state(root, ch)
        entry = next(iter(state["entries"].values()))
        assert [row["attempt"] for row in entry["execution_receipts"]] == [1, 2], entry
        assert [row["status"] for row in entry["execution_receipts"]] == ["RETRY_WAIT", "COMPLETED_NO_DATA"], entry
        assert len(calls) == 2, calls


def test_legacy_unsealed_expired_claim_can_migrate_without_rewriting_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        legacy = runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:00:00Z", lease_minutes=15)
        assert legacy["claimed"] is True, legacy
        migrated = receipt.claim_checkpoint_sealed(root, ch, job, authorization_fingerprint=FP1, now="2026-08-16T10:16:00Z", lease_minutes=15)
        assert migrated["claimed"] is True, migrated
        assert migrated["entry"]["attempt"] == 2, migrated
        assert migrated["entry"]["execution_receipts"][0]["attempt"] == 2, migrated
        assert receipt.validate_sealed_entry(migrated["entry"], FP1)["valid"] is True


def test_materialized_observation_receipt_contains_only_hash_not_payload() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        result = receipt.execute_plan_durably_sealed(
            plan(ch), ch, attestation(), authorization_fingerprint=FP1,
            repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "runtime-token", transport_call=observed_transport,
        )
        assert result["results"][0]["checkpoint_status"] == "COMPLETED", result
        state = read_state(root, ch)
        sealed = next(iter(state["entries"].values()))["execution_receipts"][-1]
        assert len(sealed["materialization_fingerprint_sha256"]) == 64, sealed
        text = json.dumps(sealed, ensure_ascii=False)
        assert "impressions" not in text and "reach" not in text and "shares" not in text, sealed
        assert sealed["guards"]["provider_payload_persisted"] is False


def test_runtime_secret_never_enters_receipt_or_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        secret = "runtime-super-secret"
        result = receipt.execute_plan_durably_sealed(
            plan(ch), ch, attestation(), authorization_fingerprint=FP1,
            repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: secret,
            transport_call=lambda *a, **k: {"status": "HOLD_TRANSPORT", "debug": secret},
        )
        assert result["results"][0]["status"] == "HOLD_SECRET_EXPOSURE", result
        assert secret not in json.dumps(result, ensure_ascii=False), result
        assert secret not in (root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8")


def test_context_manager_routes_existing_runtime_and_restores_it() -> None:
    original = runtime.execute_plan_durably
    with receipt.authorization_sealed_execution(FP1):
        assert runtime.execute_plan_durably is not original
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ch = channel()
            result = runtime.execute_plan_durably(
                plan(ch), ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z",
                credential_resolver=lambda name: "token", transport_call=no_data,
            )
            assert result["runtime_id"] == receipt.RECEIPT_ID, result
            assert result["authorization_fingerprint"] == FP1, result
    assert runtime.execute_plan_durably is original


def test_invalid_authorization_fingerprint_holds_without_state_or_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        calls: list[int] = []
        result = receipt.execute_plan_durably_sealed(
            plan(ch), ch, attestation(), authorization_fingerprint="sha256:bad",
            repo_root=root, now="2026-08-16T10:00:00Z",
            transport_call=lambda *a, **k: calls.append(1) or no_data(*a, **k),
        )
        assert result["status"] == "HOLD_AUTHORIZATION_CONTEXT", result
        assert calls == [], calls
        assert not (root / runtime.expected_checkpoint_state_path(ch)).exists()


def test_zero_paid_violation_remains_fail_closed_and_publication_unblocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = channel()
        p = plan(good)
        bad = copy.deepcopy(good)
        bad["zero_paid_dependency"] = False
        result = receipt.execute_plan_durably_sealed(
            p, bad, attestation(), authorization_fingerprint=FP1,
            repo_root=root, now="2026-08-16T10:00:00Z",
        )
        assert result["status"] == "HOLD_HARVEST_RUNTIME", result
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"], result
        assert result["publication_blocked"] is False


def test_facebook_and_instagram_receipts_stay_in_independent_namespaces() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fb = channel("facebook")
        ig = channel("instagram")
        for ch in (fb, ig):
            result = receipt.execute_plan_durably_sealed(
                plan(ch), ch, attestation(), authorization_fingerprint=FP1,
                repo_root=root, now="2026-08-16T10:00:00Z",
                credential_resolver=lambda name: "token", transport_call=no_data,
            )
            assert result["status"] == "HARVEST_RUNTIME_EXECUTED", result
        fb_state = read_state(root, fb)
        ig_state = read_state(root, ig)
        assert fb_state["channel_id"] == "alpha-facebook", fb_state
        assert ig_state["channel_id"] == "alpha-instagram", ig_state
        assert runtime.expected_checkpoint_state_path(fb) != runtime.expected_checkpoint_state_path(ig)


def test_receipt_identity_is_deterministic_for_same_authorized_attempt() -> None:
    ch = channel()
    job = plan(ch)["jobs"][0]
    a = receipt._new_receipt(job, FP1, 1, "2026-08-16T10:00:00Z")
    b = receipt._new_receipt(copy.deepcopy(job), FP1, 1, "2026-08-16T10:00:00Z")
    assert a == b
    assert a["execution_id"] == b["execution_id"]
    assert a["receipt_fingerprint_sha256"] == b["receipt_fingerprint_sha256"]


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS authorization-sealed harvest receipt acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
