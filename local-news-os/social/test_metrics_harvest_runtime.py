#!/usr/bin/env python3
"""Acceptance tests for crash-safe metrics harvest execution/checkpoint persistence."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = _load("metrics_harvest_runtime", "metrics_harvest_runtime.py")
scheduler = runtime.metrics_harvest_scheduler
collector = runtime.observed_metrics_collector


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


def attestation(**overrides) -> dict:
    value = {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }
    value.update(overrides)
    return value


def plan(ch: dict | None = None, state: dict | None = None, *, now: str = "2026-08-16T10:00:00Z") -> dict:
    ch = ch or channel()
    state = state or publication_state(ch["platform"], ch["instance_id"])
    result = scheduler.plan_harvest(ch, state, attestation(), now=now)
    assert result["status"] == "HARVEST_READY", result
    assert len(result["jobs"]) == 1, result
    return result


def observed_transport(calls: list[str] | None = None):
    def fake(ch, pub, auth, credential, **kwargs):
        if calls is not None:
            calls.append(pub["publication_id"])
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
    return fake


def read_json(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def test_success_claims_before_network_persists_observation_then_completes_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        calls: list[str] = []
        result = runtime.execute_plan_durably(
            plan(ch), ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "runtime-token", transport_call=observed_transport(calls),
        )
        assert result["status"] == "HARVEST_RUNTIME_EXECUTED", result
        assert calls == ["publication:facebook:1"], calls
        assert result["results"][0]["checkpoint_status"] == "COMPLETED", result
        checkpoint = read_json(root, runtime.expected_checkpoint_state_path(ch))
        entry = next(iter(checkpoint["entries"].values()))
        assert entry["status"] == "COMPLETED", checkpoint
        observed_path = collector.expected_observation_store_path(ch)
        observed = read_json(root, observed_path)
        assert len(observed["observations"]) == 1, observed
        assert result["guards"]["claim_persisted_before_network"] is True
        assert result["publication_blocked"] is False


def test_completed_checkpoint_is_idempotent_and_never_hits_transport_again() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        p = plan(ch)
        calls: list[str] = []
        first = runtime.execute_plan_durably(
            p, ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "token", transport_call=observed_transport(calls),
        )
        assert first["results"][0]["checkpoint_status"] == "COMPLETED", first
        second = runtime.execute_plan_durably(
            p, ch, attestation(), repo_root=root, now="2026-08-16T10:05:00Z",
            credential_resolver=lambda name: (_ for _ in ()).throw(AssertionError("resolver must not run")),
            transport_call=lambda *a, **k: (_ for _ in ()).throw(AssertionError("transport must not run")),
        )
        assert second["results"][0]["status"] == "ALREADY_COMPLETED", second
        assert calls == ["publication:facebook:1"], calls


def test_no_data_checkpoint_is_completed_and_not_polled_repeatedly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        p = plan(ch)
        calls: list[int] = []

        def no_data(*args, **kwargs):
            calls.append(1)
            return {"status": "NO_OBSERVED_METRICS", "hard_blocks": [], "metric_issues": [], "publication_blocked": False}

        first = runtime.execute_plan_durably(p, ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z", credential_resolver=lambda name: "token", transport_call=no_data)
        assert first["results"][0]["checkpoint_status"] == "COMPLETED_NO_DATA", first
        second = runtime.execute_plan_durably(p, ch, attestation(), repo_root=root, now="2026-08-16T10:10:00Z", credential_resolver=lambda name: "token", transport_call=no_data)
        assert second["results"][0]["status"] == "ALREADY_COMPLETED_NO_DATA", second
        assert len(calls) == 1, calls


def test_active_lease_blocks_second_worker_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        first = runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:00:00Z", lease_minutes=15)
        second = runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:05:00Z", lease_minutes=15)
        assert first["claimed"] is True, first
        assert second["claimed"] is False and second["status"] == "LEASE_ACTIVE", second


def test_expired_lease_is_reclaimed_with_incremented_attempt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        first = runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:00:00Z", lease_minutes=15)
        second = runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:16:00Z", lease_minutes=15)
        assert first["entry"]["attempt"] == 1, first
        assert second["claimed"] is True and second["entry"]["attempt"] == 2, second


def test_same_checkpoint_with_changed_job_fingerprint_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        assert runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:00:00Z")["claimed"] is True
        changed = copy.deepcopy(job)
        changed["metric_candidates"].append("profile_visits")
        changed["job_fingerprint_sha256"] = runtime._digest({k: v for k, v in changed.items() if k != "job_fingerprint_sha256"})
        conflict = runtime.claim_checkpoint(root, ch, changed, now="2026-08-16T10:20:00Z")
        assert conflict["status"] == "HOLD_CHECKPOINT_IDENTITY_CONFLICT", conflict


def test_tampered_checkpoint_state_blocks_only_analytics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        assert runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:00:00Z")["claimed"] is True
        path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["channel_id"] = "alpha-instagram"
        path.write_text(json.dumps(state), encoding="utf-8")
        result = runtime.execute_plan_durably(plan(ch), ch, attestation(), repo_root=root, now="2026-08-16T10:20:00Z")
        assert result["status"] == "HOLD_HARVEST_RUNTIME", result
        assert result["publication_blocked"] is False, result
        assert any("CHECKPOINT_STATE_" in code for code in result["hard_blocks"]), result


def test_transient_retry_is_durable_and_suppressed_until_retry_time() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        p = plan(ch)
        calls: list[int] = []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return {"status": "RETRY_LATER", "hard_blocks": [], "metric_issues": [{"code": "TRANSIENT_PROVIDER_FAILURE"}]}
            return {"status": "NO_OBSERVED_METRICS", "hard_blocks": [], "metric_issues": []}

        first = runtime.execute_plan_durably(p, ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z", credential_resolver=lambda name: "token", transport_call=flaky)
        assert first["results"][0]["checkpoint_status"] == "RETRY_WAIT", first
        second = runtime.execute_plan_durably(p, ch, attestation(), repo_root=root, now="2026-08-16T10:05:00Z", credential_resolver=lambda name: "token", transport_call=flaky)
        assert second["results"][0]["status"] == "RETRY_WAIT", second
        assert len(calls) == 1, calls
        third = runtime.execute_plan_durably(p, ch, attestation(), repo_root=root, now="2026-08-16T10:16:00Z", credential_resolver=lambda name: "token", transport_call=flaky)
        assert third["results"][0]["checkpoint_status"] == "COMPLETED_NO_DATA", third
        assert len(calls) == 2, calls


def test_auth_failure_is_analytics_only_and_has_bounded_retry_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        p = plan(ch)
        result = runtime.execute_plan_durably(
            p, ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "", transport_call=lambda *a, **k: {"status": "BLOCKED_AUTH", "hard_blocks": ["MISSING_RUNTIME_CREDENTIAL"], "metric_issues": [], "publication_blocked": False},
        )
        assert result["results"][0]["checkpoint_status"] == "BLOCKED_AUTH", result
        assert result["publication_blocked"] is False, result
        state = read_json(root, runtime.expected_checkpoint_state_path(ch))
        entry = next(iter(state["entries"].values()))
        assert entry["retry_after_at"] == "2026-08-16T11:00:00Z", entry


def test_observation_persistence_failure_never_marks_checkpoint_complete() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        result = runtime.execute_plan_durably(
            plan(ch), ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "token", transport_call=observed_transport(),
            persist_bundle_call=lambda *a, **k: (_ for _ in ()).throw(OSError("disk failure")),
        )
        assert result["results"][0]["status"] == "RECOVERY_REQUIRED", result
        assert result["results"][0]["checkpoint_status"] == "RECOVERY_REQUIRED", result
        state = read_json(root, runtime.expected_checkpoint_state_path(ch))
        assert next(iter(state["entries"].values()))["status"] == "RECOVERY_REQUIRED", state
        assert result["publication_blocked"] is False, result


def test_transport_secret_echo_is_not_returned_or_persisted() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        secret = "runtime-super-secret"
        result = runtime.execute_plan_durably(
            plan(ch), ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: secret,
            transport_call=lambda *a, **k: {"status": "HOLD_TRANSPORT", "debug": secret},
        )
        assert result["results"][0]["status"] == "HOLD_SECRET_EXPOSURE", result
        assert secret not in json.dumps(result, ensure_ascii=False), result
        state_text = (root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8")
        assert secret not in state_text, state_text


def test_instagram_has_independent_checkpoint_namespace_and_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel("instagram")
        p = plan(ch, publication_state("instagram"))
        result = runtime.execute_plan_durably(
            p, ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z",
            credential_resolver=lambda name: "ig-token",
            transport_call=lambda *a, **k: {"status": "NO_OBSERVED_METRICS", "hard_blocks": [], "metric_issues": []},
        )
        assert result["checkpoint_state_path"] == "alpha/social/instagram_state_metrics_harvest_state.json", result
        assert p["jobs"][0]["source"] == "instagram_graph_api", p
        assert (root / result["checkpoint_state_path"]).exists()
        assert not (root / "alpha/social/facebook_state_metrics_harvest_state.json").exists()


def test_cross_instance_checkpoint_state_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        beta = channel(instance="beta")
        target = root / runtime.expected_checkpoint_state_path(beta)
        target.parent.mkdir(parents=True, exist_ok=True)
        wrong = runtime.empty_checkpoint_state(channel(instance="alpha"))
        wrong["storage_path"] = runtime.expected_checkpoint_state_path(beta)
        wrong["state_fingerprint_sha256"] = runtime._state_fingerprint(wrong)
        target.write_text(json.dumps(wrong), encoding="utf-8")
        checked = runtime.load_checkpoint_state(root, beta)
        assert "CHECKPOINT_STATE_INSTANCE_MISMATCH" in checked[1], checked


def test_zero_paid_violation_cannot_execute_analytics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = channel()
        p = plan(good)
        bad = copy.deepcopy(good)
        bad["zero_paid_dependency"] = False
        result = runtime.execute_plan_durably(p, bad, attestation(), repo_root=root, now="2026-08-16T10:00:00Z")
        assert result["status"] == "HOLD_HARVEST_RUNTIME", result
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"], result
        assert result["publication_blocked"] is False, result


def test_physical_lock_prevents_claim_race() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        job = plan(ch)["jobs"][0]
        target = root / runtime.expected_checkpoint_state_path(ch)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = target.with_name(target.name + ".lock")
        lock.write_text("busy", encoding="utf-8")
        claim = runtime.claim_checkpoint(root, ch, job, now="2026-08-16T10:00:00Z")
        assert claim["claimed"] is False, claim
        assert claim["status"] == "HOLD_CHECKPOINT_STATE_LOCK_BUSY", claim


def test_plan_fingerprint_tampering_fails_before_claim_or_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        p = plan(ch)
        p["planned_at"] = "2026-08-16T10:00:01Z"
        result = runtime.execute_plan_durably(p, ch, attestation(), repo_root=root, now="2026-08-16T10:00:00Z")
        assert result["status"] == "HOLD_HARVEST_RUNTIME", result
        assert "PLAN_FINGERPRINT_MISMATCH" in result["hard_blocks"], result
        assert not (root / runtime.expected_checkpoint_state_path(ch)).exists()


def test_checkpoint_key_and_empty_state_are_deterministic() -> None:
    ch = channel()
    job = plan(ch)["jobs"][0]
    assert runtime.checkpoint_key(job) == runtime.checkpoint_key(copy.deepcopy(job))
    assert runtime.empty_checkpoint_state(ch) == runtime.empty_checkpoint_state(copy.deepcopy(ch))


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS metrics harvest runtime acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
