#!/usr/bin/env python3
"""Acceptance tests for the operational observed-metrics harvest trigger."""
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


trigger = _load("operational_metrics_harvest_trigger", "operational_metrics_harvest_trigger.py")
collector = trigger.observed_metrics_collector
catalog_mod = trigger.publication_metrics_catalog


def channel(platform: str = "facebook", instance: str = "alpha") -> dict:
    source = "meta_graph_api" if platform == "facebook" else "instagram_graph_api"
    return {
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


def publication(ch: dict, idx: int = 1, published_at: str = "2026-08-16T08:00:00Z") -> dict:
    return {
        "schema_version": "1.0",
        "instance_id": ch["instance_id"],
        "channel_id": ch["channel_id"],
        "platform": ch["platform"],
        "status": "PUBLISHED",
        "publication_id": f"publication:{ch['platform']}:{idx}",
        "remote_publication_id": f"remote_{ch['platform']}_{idx}",
        "story_id": f"story:{idx}",
        "product_id": f"product:{ch['platform']}:{idx}",
        "published_at": published_at,
        "native_format": "single_photo",
        "topic_keys": ["service_journalism"],
        "series_id": None,
    }


def catalog(ch: dict, idx: int = 1, published_at: str = "2026-08-16T08:00:00Z") -> dict:
    cat = catalog_mod.empty_catalog(ch)
    row = publication(ch, idx, published_at)
    row["descriptor_fingerprint_sha256"] = catalog_mod._descriptor_fingerprint(row)
    cat["records"] = {row["publication_id"]: row}
    cat["catalog_fingerprint_sha256"] = catalog_mod._catalog_fingerprint(cat)
    checked = catalog_mod.validate_catalog(ch, cat)
    assert checked["valid"], checked
    return cat


def auth() -> dict:
    return {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }


def write_json(root: Path, relative: str, value: dict) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def fake_transport(calls: list[str], with_data: bool = False):
    def transport(ch, pub, attestation, credential, **kwargs):
        calls.append(pub["publication_id"])
        if not with_data:
            return {
                "status": "NO_OBSERVED_METRICS",
                "hard_blocks": [],
                "metric_issues": [],
                "publication_blocked": False,
            }
        bundle = collector.materialize_bundle(
            ch,
            pub,
            {"metrics": {"impressions": 100, "reach": 80, "shares": 4}},
            source=ch["metrics"]["sources"][0],
            observed_at=kwargs["now"],
            collected_at=kwargs["now"],
            window_start_at=pub["published_at"],
            window_end_at=kwargs["now"],
            now=kwargs["now"],
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
    return transport


def test_missing_catalog_is_idle_and_does_not_fabricate_legacy_descriptors() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        result = trigger.evaluate_channel(root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True)
        assert result["status"] == "NO_AUTHORITATIVE_PUBLICATION_CATALOG", result
        assert result["publication_blocked"] is False
        assert not (root / catalog_mod.expected_catalog_path(ch)).exists()


def test_due_catalog_executes_once_and_persists_checkpoint_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        write_json(root, catalog_mod.expected_catalog_path(ch), catalog(ch))
        calls: list[str] = []
        result = trigger.evaluate_channel(
            root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True,
            credential_resolver=lambda name: "runtime-only-token",
            transport_call=fake_transport(calls),
        )
        assert result["status"] == "HARVEST_EXECUTED", result
        assert calls == ["publication:facebook:1"], calls
        assert result["runtime_results"][0]["checkpoint_status"] == "COMPLETED_NO_DATA", result
        checkpoint = root / trigger.metrics_harvest_runtime.expected_checkpoint_state_path(ch)
        assert checkpoint.exists(), result
        assert "runtime-only-token" not in checkpoint.read_text(encoding="utf-8")


def test_replay_of_completed_checkpoint_never_calls_transport_again() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        write_json(root, catalog_mod.expected_catalog_path(ch), catalog(ch))
        calls: list[str] = []
        kwargs = dict(
            now="2026-08-16T10:00:00Z", execute=True,
            credential_resolver=lambda name: "token",
            transport_call=fake_transport(calls),
        )
        first = trigger.evaluate_channel(root, ch, auth(), **kwargs)
        second = trigger.evaluate_channel(root, ch, auth(), **kwargs)
        assert first["status"] == "HARVEST_EXECUTED", first
        assert second["status"] == "HARVEST_EXECUTED", second
        assert second["runtime_results"][0]["status"] == "ALREADY_COMPLETED_NO_DATA", second
        assert len(calls) == 1, calls


def test_observed_data_materializes_channel_local_ledger_and_snapshot_boundary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        write_json(root, catalog_mod.expected_catalog_path(ch), catalog(ch))
        calls: list[str] = []
        result = trigger.evaluate_channel(
            root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True,
            credential_resolver=lambda name: "token", transport_call=fake_transport(calls, with_data=True),
        )
        assert result["status"] == "HARVEST_EXECUTED", result
        observed = root / collector.expected_observation_store_path(ch)
        assert observed.exists(), result
        stored = json.loads(observed.read_text(encoding="utf-8"))
        assert len(stored["observations"]) == 1, stored
        assert stored["channel_id"] == ch["channel_id"]
        assert result["publication_blocked"] is False


def test_no_due_checkpoint_does_not_resolve_credentials_or_touch_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        write_json(root, catalog_mod.expected_catalog_path(ch), catalog(ch, published_at="2026-08-16T09:30:00Z"))
        result = trigger.evaluate_channel(
            root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True,
            credential_resolver=lambda name: (_ for _ in ()).throw(AssertionError("credential resolver must not run")),
            transport_call=lambda *a, **k: (_ for _ in ()).throw(AssertionError("network must not run")),
        )
        assert result["status"] == "NO_HARVEST_DUE", result


def test_tampered_catalog_fails_closed_only_for_analytics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        tampered = catalog(ch)
        tampered["records"]["publication:facebook:1"]["product_id"] = "tampered"
        write_json(root, catalog_mod.expected_catalog_path(ch), tampered)
        result = trigger.evaluate_channel(root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True)
        assert result["status"] == "HOLD_PUBLICATION_CATALOG", result
        assert result["publication_blocked"] is False
        assert any("FINGERPRINT" in code for code in result["hard_blocks"]), result


def test_zero_paid_violation_is_rejected_before_scheduling() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        ch["zero_paid_dependency"] = False
        result = trigger.evaluate_channel(root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True)
        assert result["status"] == "HOLD_CHANNEL_POLICY", result
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"]


def test_unsupported_platform_is_skipped_without_inventing_transport() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        ch["platform"] = "youtube"
        ch["channel_id"] = "alpha-youtube"
        result = trigger.evaluate_channel(root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True)
        assert result["status"] == "SKIP_UNSUPPORTED_NATIVE_METRICS_TRANSPORT", result
        assert result["hard_blocks"] == []


def test_facebook_and_instagram_use_independent_catalog_checkpoint_and_observation_namespaces() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fb = channel("facebook")
        ig = channel("instagram")
        write_json(root, catalog_mod.expected_catalog_path(fb), catalog(fb))
        write_json(root, catalog_mod.expected_catalog_path(ig), catalog(ig))
        calls: list[str] = []
        for ch in (fb, ig):
            result = trigger.evaluate_channel(
                root, ch, auth(), now="2026-08-16T10:00:00Z", execute=True,
                credential_resolver=lambda name: "token",
                transport_call=fake_transport(calls),
            )
            assert result["status"] == "HARVEST_EXECUTED", result
        assert trigger.metrics_harvest_runtime.expected_checkpoint_state_path(fb) != trigger.metrics_harvest_runtime.expected_checkpoint_state_path(ig)
        assert collector.expected_observation_store_path(fb) != collector.expected_observation_store_path(ig)
        assert catalog_mod.expected_catalog_path(fb) != catalog_mod.expected_catalog_path(ig)
        assert len(calls) == 2, calls


def test_trigger_aggregates_channels_without_leaking_runtime_secret() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fb = channel("facebook")
        ig = channel("instagram")
        fb_path = write_json(root, "config/facebook.json", fb)
        ig_path = write_json(root, "config/instagram.json", ig)
        auth_path = write_json(root, "config/auth.json", auth())
        write_json(root, catalog_mod.expected_catalog_path(fb), catalog(fb))
        write_json(root, catalog_mod.expected_catalog_path(ig), catalog(ig))
        result = trigger.run_trigger(
            root, [fb_path, ig_path], auth_path,
            now="2026-08-16T10:00:00Z", execute=True,
            credential_resolver=lambda name: "super-secret-runtime-value",
            transport_call=fake_transport([]),
        )
        assert result["status"] == "TRIGGER_EXECUTED", result
        encoded = json.dumps(result, ensure_ascii=False)
        assert "super-secret-runtime-value" not in encoded
        assert result["guards"]["native_free_transport_only"] is True
        assert result["guards"]["zero_paid_dependency"] is True
        assert result["publication_blocked"] is False


def run() -> None:
    tests = [
        test_missing_catalog_is_idle_and_does_not_fabricate_legacy_descriptors,
        test_due_catalog_executes_once_and_persists_checkpoint_before_network,
        test_replay_of_completed_checkpoint_never_calls_transport_again,
        test_observed_data_materializes_channel_local_ledger_and_snapshot_boundary,
        test_no_due_checkpoint_does_not_resolve_credentials_or_touch_network,
        test_tampered_catalog_fails_closed_only_for_analytics,
        test_zero_paid_violation_is_rejected_before_scheduling,
        test_unsupported_platform_is_skipped_without_inventing_transport,
        test_facebook_and_instagram_use_independent_catalog_checkpoint_and_observation_namespaces,
        test_trigger_aggregates_channels_without_leaking_runtime_secret,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} operational metrics harvest trigger acceptance tests passed")


if __name__ == "__main__":
    run()
