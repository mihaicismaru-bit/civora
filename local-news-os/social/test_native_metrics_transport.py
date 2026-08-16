#!/usr/bin/env python3
"""Acceptance tests for the native/free observed-metrics transport boundary."""
from __future__ import annotations

import copy
import importlib.util
import json
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transport = _load("native_metrics_transport", "native_metrics_transport.py")


def channel(platform: str = "facebook", **overrides) -> dict:
    source = "meta_graph_api" if platform == "facebook" else "instagram_graph_api"
    value = {
        "schema_version": "1.0",
        "channel_id": f"alpha-{platform}",
        "instance_id": "alpha",
        "platform": platform,
        "status": "active",
        "cadence": {"timezone": "Europe/Bucharest"},
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


def attestation(**overrides) -> dict:
    value = {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }
    value.update(overrides)
    return value


class FakeMeta:
    def __init__(self, responses: dict[str, tuple[int, dict]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, dict]:
        self.calls.append((url, copy.deepcopy(headers)))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        metric = query.get("metric", [""])[0]
        return self.responses.get(metric, (400, {"error": {"code": 100, "message": "unsupported"}}))


def graph_value(name: str, value: int) -> tuple[int, dict]:
    return 200, {"data": [{"name": name, "values": [{"value": value}]}]}


def facebook_client() -> FakeMeta:
    return FakeMeta({
        "post_impressions": graph_value("post_impressions", 1000),
        "post_impressions_unique": graph_value("post_impressions_unique", 800),
    })


def instagram_client() -> FakeMeta:
    return FakeMeta({
        "reach": graph_value("reach", 900),
        "saved": graph_value("saved", 12),
    })


def test_facebook_plan_is_secret_free_and_uses_declared_native_source() -> None:
    result = transport.build_transport_plan(channel(), publication(), attestation())
    assert result["status"] == "TRANSPORT_PLANNED", result
    plan = result["plan"]
    assert plan["source"] == "meta_graph_api", plan
    assert plan["metric_candidates"] == ["post_impressions", "post_impressions_unique"], plan
    assert plan["credential_env_name"] == "ALPHA_FACEBOOK_ACCESS_TOKEN", plan
    encoded = json.dumps(result, ensure_ascii=False)
    assert "Bearer" not in encoded and "access_token=" not in encoded, encoded


def test_instagram_has_independent_profile_and_credential_reference() -> None:
    result = transport.build_transport_plan(channel("instagram"), publication("instagram"), attestation())
    assert result["status"] == "TRANSPORT_PLANNED", result
    plan = result["plan"]
    assert plan["source"] == "instagram_graph_api", plan
    assert plan["metric_candidates"] == ["reach", "saved"], plan
    assert plan["credential_env_name"] == "ALPHA_INSTAGRAM_ACCESS_TOKEN", plan


def test_unverified_platform_access_fails_closed_before_network() -> None:
    result = transport.build_transport_plan(channel(), publication(), attestation(facebook_ready=False))
    assert result["status"] == "HOLD_TRANSPORT", result
    assert "PLATFORM_ACCESS_NOT_READY" in result["hard_blocks"], result
    assert result["publication_blocked"] is False, result


def test_secret_material_in_access_attestation_is_rejected() -> None:
    result = transport.build_transport_plan(channel(), publication(), attestation(secret_material_persisted=True))
    assert result["status"] == "HOLD_TRANSPORT", result
    assert "SECRET_MATERIAL_PERSISTED" in result["hard_blocks"], result


def test_zero_paid_dependency_is_mandatory() -> None:
    result = transport.build_transport_plan(channel(zero_paid_dependency=False), publication(), attestation())
    assert result["status"] == "HOLD_TRANSPORT", result
    assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"], result


def test_undeclared_source_is_rejected() -> None:
    bad = channel(metrics={"observed_only": True, "sources": ["manual_export"]})
    result = transport.build_transport_plan(bad, publication(), attestation())
    assert result["status"] == "HOLD_TRANSPORT", result
    assert "UNDECLARED_METRIC_SOURCE" in result["hard_blocks"], result


def test_cross_channel_publication_is_rejected_before_transport() -> None:
    result = transport.build_transport_plan(channel(), publication(channel_id="alpha-instagram"), attestation())
    assert result["status"] == "HOLD_TRANSPORT", result
    assert "CHANNEL_MISMATCH" in result["hard_blocks"], result


def test_only_runtime_github_secret_references_are_accepted_for_meta_transport() -> None:
    bad = channel(credentials_ref="connector:meta-token")
    result = transport.build_transport_plan(bad, publication(), attestation())
    assert result["status"] == "HOLD_TRANSPORT", result
    assert "METRICS_TRANSPORT_REQUIRES_GITHUB_ACTIONS_SECRET_REF" in result["hard_blocks"], result


def test_facebook_fetch_uses_bearer_header_and_never_puts_token_in_url() -> None:
    plan = transport.build_transport_plan(channel(), publication(), attestation())["plan"]
    client = facebook_client()
    secret = "super-secret-runtime-token"
    result = transport.fetch_provider_payload(plan, secret, http_get=client)
    assert result["status"] == "OBSERVED_PAYLOAD_READY", result
    assert len(client.calls) == 2, client.calls
    for url, headers in client.calls:
        assert secret not in url, url
        assert "access_token=" not in url.lower(), url
        assert headers["Authorization"] == f"Bearer {secret}", headers
    assert secret not in json.dumps(result, ensure_ascii=False), result


def test_unsupported_metric_is_skipped_without_discarding_direct_observation() -> None:
    plan = transport.build_transport_plan(channel(), publication(), attestation())["plan"]
    client = FakeMeta({
        "post_impressions": (400, {"error": {"code": 100, "message": "metric unavailable"}}),
        "post_impressions_unique": graph_value("post_impressions_unique", 777),
    })
    result = transport.fetch_provider_payload(plan, "runtime-token", http_get=client)
    assert result["status"] == "OBSERVED_PAYLOAD_READY", result
    assert result["provider_payload"]["data"] == [
        {"name": "post_impressions_unique", "values": [{"value": 777}]}
    ], result
    assert result["metric_issues"] == [
        {"metric": "post_impressions", "code": "UNSUPPORTED_OR_UNAVAILABLE"}
    ], result


def test_auth_failure_blocks_collection_but_not_publication_and_never_echoes_secret() -> None:
    plan = transport.build_transport_plan(channel(), publication(), attestation())["plan"]
    client = FakeMeta({
        "post_impressions": (401, {"error": {"code": 190, "message": "token expired runtime-token"}}),
    })
    result = transport.fetch_provider_payload(plan, "runtime-token", http_get=client)
    assert result["status"] == "BLOCKED_AUTH", result
    assert "NATIVE_METRICS_AUTH_OR_PERMISSION_FAILURE" in result["hard_blocks"], result
    assert result["publication_blocked"] is False, result
    assert "runtime-token" not in json.dumps(result, ensure_ascii=False), result


def test_transient_provider_failure_requests_retry_without_blocking_publication() -> None:
    plan = transport.build_transport_plan(channel(), publication(), attestation())["plan"]
    client = FakeMeta({"post_impressions": (503, {"error": {"code": 2, "message": "temporary"}})})
    result = transport.fetch_provider_payload(plan, "runtime-token", http_get=client)
    assert result["status"] == "RETRY_LATER", result
    assert result["publication_blocked"] is False, result
    assert result["hard_blocks"] == [], result


def test_no_supported_provider_metric_is_a_noop_not_a_publication_failure() -> None:
    plan = transport.build_transport_plan(channel(), publication(), attestation())["plan"]
    client = FakeMeta({
        "post_impressions": (400, {"error": {"code": 100, "message": "unsupported"}}),
        "post_impressions_unique": (400, {"error": {"code": 100, "message": "unsupported"}}),
    })
    result = transport.fetch_provider_payload(plan, "runtime-token", http_get=client)
    assert result["status"] == "NO_OBSERVED_METRICS", result
    assert result["publication_blocked"] is False, result
    assert result["provider_payload"] is None, result


def test_facebook_native_payload_flows_into_durable_observation_without_raw_secret() -> None:
    client = facebook_client()
    secret = "never-persist-this"
    result = transport.collect_and_materialize(
        channel(), publication(), attestation(), secret,
        now="2026-08-16T12:00:00Z", http_get=client, min_samples=2,
    )
    assert result["status"] == "COLLECTED_AND_MATERIALIZED", result
    bundle = result["materialization"]
    observation = bundle["observation_store"]["observations"][0]
    assert observation["metrics"]["impressions"] == 1000, observation
    assert observation["metrics"]["reach"] == 800, observation
    assert observation["source"] == "meta_graph_api", observation
    assert bundle["guards"]["publication_blocked"] is False, bundle
    assert secret not in json.dumps(result, ensure_ascii=False), result


def test_instagram_native_payload_keeps_learning_isolated_to_instagram() -> None:
    result = transport.collect_and_materialize(
        channel("instagram"), publication("instagram"), attestation(), "ig-runtime-token",
        now="2026-08-16T12:00:00Z", http_get=instagram_client(), min_samples=2,
    )
    assert result["status"] == "COLLECTED_AND_MATERIALIZED", result
    observation = result["materialization"]["observation_store"]["observations"][0]
    assert observation["platform"] == "instagram", observation
    assert observation["channel_id"] == "alpha-instagram", observation
    assert observation["metrics"]["reach"] == 900, observation
    assert observation["metrics"]["saves"] == 12, observation
    assert observation["source"] == "instagram_graph_api", observation


def test_replay_of_same_remote_snapshot_is_idempotent() -> None:
    first = transport.collect_and_materialize(
        channel(), publication(), attestation(), "runtime-token",
        now="2026-08-16T12:00:00Z", http_get=facebook_client(), min_samples=2,
    )
    store = first["materialization"]["observation_store"]
    snapshot = first["materialization"].get("snapshot_to_persist")
    second = transport.collect_and_materialize(
        channel(), publication(), attestation(), "runtime-token",
        now="2026-08-16T12:00:00Z", http_get=facebook_client(), min_samples=2,
        existing_store=store, existing_snapshot=snapshot,
    )
    assert second["status"] == "COLLECTED_AND_MATERIALIZED", second
    materialization = second["materialization"]
    assert materialization["observation_action"] == "IDEMPOTENT", materialization
    assert len(materialization["observation_store"]["observations"]) == 1, materialization


def test_provider_cannot_smuggle_predictive_field_into_observation() -> None:
    plan = transport.build_transport_plan(channel(), publication(), attestation())["plan"]
    client = FakeMeta({
        "post_impressions": (200, {"data": [{"name": "post_impressions", "values": [{"value": 100}]}], "predicted_views": 999999}),
        "post_impressions_unique": graph_value("post_impressions_unique", 80),
    })
    # Transport passes only the exact requested data entries, so unrelated provider metadata is
    # discarded before the collector and can never become a learning signal.
    result = transport.fetch_provider_payload(plan, "runtime-token", http_get=client)
    encoded = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "OBSERVED_PAYLOAD_READY", result
    assert "predicted_views" not in encoded, encoded


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS native metrics transport acceptance suite ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
