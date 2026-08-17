#!/usr/bin/env python3
"""Acceptance tests for deterministic observed-metrics harvest scheduling."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scheduler = _load("metrics_harvest_scheduler", "metrics_harvest_scheduler.py")
collector = scheduler.observed_metrics_collector


def channel(platform: str = "facebook", **overrides) -> dict:
    source = "meta_graph_api" if platform == "facebook" else "instagram_graph_api"
    value = {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": f"alpha-{platform}",
        "platform": platform,
        "status": "active",
        "credentials_ref": f"github-actions-secret:ALPHA_{platform.upper()}_ACCESS_TOKEN",
        "publication_state": {
            "outbox_path": f"alpha/social/{platform}_outbox.json",
            "state_path": f"alpha/social/{platform}_state.json",
            "dedupe_by_id": True,
            "last_known_good": True,
        },
        "metrics": {"observed_only": True, "sources": [source]},
        "zero_paid_dependency": True,
    }
    value.update(overrides)
    return value


def publication(platform: str = "facebook", idx: int = 1, **overrides) -> dict:
    value = {
        "instance_id": "alpha",
        "channel_id": f"alpha-{platform}",
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
    value.update(overrides)
    return value


def state(platform: str = "facebook", records: list[dict] | None = None, **overrides) -> dict:
    rows = records if records is not None else [publication(platform)]
    value = {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": f"alpha-{platform}",
        "platform": platform,
        "records": {row["publication_id"]: copy.deepcopy(row) for row in rows},
    }
    value.update(overrides)
    return value


def attestation(**overrides) -> dict:
    value = {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }
    value.update(overrides)
    return value


def observed_store(ch: dict, pub: dict, observed_at: str) -> dict:
    built = collector.materialize_bundle(
        ch,
        pub,
        {"metrics": {"impressions": 100, "reach": 80}},
        source=ch["metrics"]["sources"][0],
        observed_at=observed_at,
        collected_at=observed_at,
        window_start_at=pub["published_at"],
        window_end_at=observed_at,
        now=observed_at,
        min_samples=99,
    )
    assert not built.get("hard_blocks"), built
    return built["observation_store"]


def test_schedules_latest_due_checkpoint_not_every_missed_window() -> None:
    plan = scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-16T15:00:00Z")
    assert plan["status"] == "HARVEST_READY", plan
    job = plan["jobs"][0]
    assert job["checkpoint"]["checkpoint_hours"] == 6, job
    assert job["checkpoint"]["covered_checkpoints_hours"] == [1, 6], job
    assert len(plan["jobs"]) == 1, plan


def test_delayed_first_run_catches_up_directly_to_72h_checkpoint() -> None:
    plan = scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-20T09:00:00Z")
    assert plan["jobs"][0]["checkpoint"]["checkpoint_hours"] == 72, plan
    assert plan["jobs"][0]["checkpoint"]["covered_checkpoints_hours"] == [1, 6, 24, 72], plan


def test_nothing_is_scheduled_before_first_checkpoint() -> None:
    plan = scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-16T08:30:00Z")
    assert plan["status"] == "NO_HARVEST_DUE", plan
    assert plan["jobs"] == [], plan


def test_existing_observation_covers_prior_cumulative_checkpoints() -> None:
    pub = publication()
    store = observed_store(channel(), pub, "2026-08-16T14:15:00Z")
    plan = scheduler.plan_harvest(
        channel(), state(records=[pub]), attestation(),
        now="2026-08-16T15:00:00Z", observation_store=store,
    )
    assert plan["status"] == "NO_HARVEST_DUE", plan
    later = scheduler.plan_harvest(
        channel(), state(records=[pub]), attestation(),
        now="2026-08-17T09:00:00Z", observation_store=store,
    )
    assert later["jobs"][0]["checkpoint"]["checkpoint_hours"] == 24, later


def test_only_confirmed_descriptor_complete_publications_are_enumerated() -> None:
    good = publication(idx=1)
    not_published = publication(idx=2, status="READY")
    incomplete = publication(idx=3)
    incomplete.pop("native_format")
    result = scheduler.enumerate_publications(channel(), state(records=[good, not_published, incomplete]))
    assert [row["publication_id"] for row in result["publications"]] == [good["publication_id"]], result
    codes = {code for row in result["skipped"] for code in row["hard_blocks"]}
    assert "PUBLICATION_NOT_CONFIRMED" in codes, result
    assert "MISSING_NATIVE_FORMAT" in codes, result


def test_legacy_adapter_state_is_not_reverse_engineered_or_fabricated() -> None:
    legacy = {
        "platform": "facebook",
        "published": {"story-old": {"facebook_post_id": "page_post", "published_at": "2026-08-16T08:00:00Z"}},
    }
    result = scheduler.enumerate_publications(channel(), legacy)
    assert result["publications"] == [], result
    assert result["skipped"][0]["reason"] == "LEGACY_STATE_DESCRIPTOR_NOT_FABRICATED", result


def test_cross_channel_state_identity_fails_closed_for_harvest_only() -> None:
    bad_state = state(channel_id="alpha-instagram")
    plan = scheduler.plan_harvest(channel(), bad_state, attestation(), now="2026-08-16T15:00:00Z")
    assert plan["status"] == "HOLD_HARVEST", plan
    assert "STATE_CHANNEL_MISMATCH" in plan["hard_blocks"], plan
    assert plan["publication_blocked"] is False, plan


def test_tampered_observation_store_blocks_collection_not_publication() -> None:
    pub = publication()
    store = observed_store(channel(), pub, "2026-08-16T09:10:00Z")
    store["channel_id"] = "alpha-instagram"
    plan = scheduler.plan_harvest(
        channel(), state(records=[pub]), attestation(),
        now="2026-08-16T15:00:00Z", observation_store=store,
    )
    assert plan["status"] == "HOLD_OBSERVATION_STORE", plan
    assert plan["publication_blocked"] is False, plan


def test_transport_access_gate_is_applied_before_job_emission() -> None:
    plan = scheduler.plan_harvest(
        channel(), state(), attestation(facebook_ready=False), now="2026-08-16T15:00:00Z"
    )
    assert plan["jobs"] == [], plan
    row = next(item for item in plan["skipped"] if item.get("publication_id"))
    assert row["reason"] == "TRANSPORT_NOT_ELIGIBLE", row
    assert "PLATFORM_ACCESS_NOT_READY" in row["hard_blocks"], row
    assert plan["publication_blocked"] is False, plan


def test_zero_paid_dependency_is_mandatory_but_never_blocks_publication() -> None:
    plan = scheduler.plan_harvest(
        channel(zero_paid_dependency=False), state(), attestation(), now="2026-08-16T15:00:00Z"
    )
    assert plan["status"] == "HOLD_HARVEST", plan
    assert "ZERO_PAID_DEPENDENCY_VIOLATION" in plan["hard_blocks"], plan
    assert plan["publication_blocked"] is False, plan


def test_predictive_fields_do_not_enter_descriptor_or_change_plan_fingerprint() -> None:
    clean = publication()
    noisy = publication(predicted_views=999999, expected_reach=123456)
    first = scheduler.plan_harvest(channel(), state(records=[clean]), attestation(), now="2026-08-16T15:00:00Z")
    second = scheduler.plan_harvest(channel(), state(records=[noisy]), attestation(), now="2026-08-16T15:00:00Z")
    assert first["plan_fingerprint_sha256"] == second["plan_fingerprint_sha256"], (first, second)
    encoded = json.dumps(second, ensure_ascii=False)
    assert "predicted_views" not in encoded and "expected_reach" not in encoded, encoded


def test_per_run_budget_is_deterministic_and_defers_extra_publications() -> None:
    pubs = [
        publication(idx=3, published_at="2026-08-16T07:00:00Z"),
        publication(idx=1, published_at="2026-08-16T06:00:00Z"),
        publication(idx=2, published_at="2026-08-16T06:30:00Z"),
    ]
    plan = scheduler.plan_harvest(
        channel(), state(records=pubs), attestation(),
        now="2026-08-16T15:00:00Z", max_publications=2,
    )
    assert [row["publication_id"] for row in plan["jobs"]] == [
        "publication:facebook:1", "publication:facebook:2"
    ], plan
    assert any(row["reason"] == "DEFERRED_BY_RUN_BUDGET" for row in plan["skipped"]), plan


def test_instagram_uses_independent_native_source_and_credential_reference() -> None:
    plan = scheduler.plan_harvest(
        channel("instagram"), state("instagram"), attestation(), now="2026-08-16T15:00:00Z"
    )
    assert plan["status"] == "HARVEST_READY", plan
    job = plan["jobs"][0]
    assert job["source"] == "instagram_graph_api", job
    assert job["credential_env_name"] == "ALPHA_INSTAGRAM_ACCESS_TOKEN", job


def test_unsupported_channel_has_no_fake_native_metrics_job() -> None:
    ch = channel("threads", credentials_ref="github-actions-secret:ALPHA_THREADS_ACCESS_TOKEN", metrics={"observed_only": True, "sources": ["threads_api"]})
    pub = publication("threads")
    plan = scheduler.plan_harvest(ch, state("threads", [pub]), attestation(), now="2026-08-16T15:00:00Z")
    assert plan["jobs"] == [], plan
    row = next(item for item in plan["skipped"] if item.get("publication_id"))
    assert "UNSUPPORTED_METRICS_TRANSPORT" in row["hard_blocks"], row


def test_invalid_windows_and_budget_are_rejected_deterministically() -> None:
    try:
        scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-16T15:00:00Z", windows_hours=[1, 1])
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate windows must fail")
    try:
        scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-16T15:00:00Z", max_publications=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("zero budget must fail")


def test_execute_harvest_resolves_secret_only_at_boundary_and_never_returns_it() -> None:
    plan = scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-16T15:00:00Z")
    calls: list[tuple[str, str]] = []
    secret = "runtime-super-secret"

    def resolver(name: str) -> str:
        calls.append(("resolver", name))
        return secret

    def fake_transport(ch, pub, auth, credential, **kwargs):
        assert credential == secret
        calls.append(("transport", pub["publication_id"]))
        return {"status": "NO_OBSERVED_METRICS", "metric_issues": [], "hard_blocks": [], "publication_blocked": False}

    result = scheduler.execute_harvest(
        plan, channel(), attestation(), now="2026-08-16T15:00:00Z",
        credential_resolver=resolver, transport_call=fake_transport,
    )
    assert result["status"] == "HARVEST_EXECUTED", result
    assert calls[0] == ("resolver", "ALPHA_FACEBOOK_ACCESS_TOKEN"), calls
    assert secret not in json.dumps(result, ensure_ascii=False), result
    assert result["guards"]["credential_values_returned"] is False, result


def test_missing_runtime_secret_blocks_only_analytics_job() -> None:
    plan = scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-16T15:00:00Z")

    def fake_transport(ch, pub, auth, credential, **kwargs):
        assert credential == ""
        return {
            "status": "BLOCKED_AUTH",
            "hard_blocks": ["MISSING_RUNTIME_CREDENTIAL"],
            "metric_issues": [],
            "publication_blocked": False,
        }

    result = scheduler.execute_harvest(
        plan, channel(), attestation(), now="2026-08-16T15:00:00Z",
        credential_resolver=lambda name: "", transport_call=fake_transport,
    )
    assert result["results"][0]["status"] == "BLOCKED_AUTH", result
    assert result["results"][0]["publication_blocked"] is False, result


def test_transport_secret_echo_is_discarded_before_persistence_or_output() -> None:
    plan = scheduler.plan_harvest(channel(), state(), attestation(), now="2026-08-16T15:00:00Z")
    secret = "must-not-leak"

    def bad_transport(ch, pub, auth, credential, **kwargs):
        return {"status": "HOLD_TRANSPORT", "debug": credential}

    result = scheduler.execute_harvest(
        plan, channel(), attestation(), now="2026-08-16T15:00:00Z",
        credential_resolver=lambda name: secret, transport_call=bad_transport,
    )
    assert result["results"][0]["status"] == "HOLD_SECRET_EXPOSURE", result
    assert secret not in json.dumps(result, ensure_ascii=False), result


def test_plan_is_deterministic_for_identical_inputs() -> None:
    args = (channel(), state(), attestation())
    first = scheduler.plan_harvest(*args, now="2026-08-16T15:00:00Z")
    second = scheduler.plan_harvest(*copy.deepcopy(args), now="2026-08-16T15:00:00Z")
    assert first == second, (first, second)


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS metrics harvest scheduler acceptance suite ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
