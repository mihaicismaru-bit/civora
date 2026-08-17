#!/usr/bin/env python3
"""Acceptance tests for the operational observed-metrics harvest trigger."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import metrics_harvest_runtime
import operational_metrics_harvest as trigger
import publication_metrics_catalog as catalog_core


def channel(platform: str = "facebook", *, instance: str = "alpha") -> dict:
    source = "meta_graph_api" if platform == "facebook" else "instagram_graph_api"
    return {
        "schema_version": "1.0",
        "channel_id": f"{instance}-{platform}",
        "instance_id": instance,
        "platform": platform,
        "status": "active",
        "cadence": {"timezone": "Europe/Bucharest"},
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


def attestation(**overrides) -> dict:
    value = {
        "status": "VALID",
        "facebook_ready": True,
        "instagram_ready": True,
        "secret_material_persisted": False,
    }
    value.update(overrides)
    return value


def descriptor(ch: dict, *, idx: int = 1, published_at: str = "2026-08-16T08:00:00Z") -> dict:
    platform = ch["platform"]
    value = {
        "schema_version": "1.0",
        "instance_id": ch["instance_id"],
        "channel_id": ch["channel_id"],
        "platform": platform,
        "status": "PUBLISHED",
        "publication_id": f"publication:{platform}:{idx}",
        "remote_publication_id": f"remote-{platform}-{idx}",
        "story_id": f"story:{idx}",
        "product_id": f"product:{platform}:{idx}",
        "published_at": published_at,
        "native_format": "carousel" if platform == "instagram" else "single_photo",
        "topic_keys": ["service_journalism"],
        "series_id": None,
        "binding_provenance": {
            "fact_kernel_sha256": "a" * 64,
            "product_fingerprint_sha256": "b" * 64,
            "publication_dedupe_key": f"dedupe:{platform}:{idx}",
            "binding_method": "verified_fact_kernel_plus_native_product_plus_remote_proof",
        },
        "guards": {
            "observed_metrics_context_only": True,
            "native_product_only": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "predictive_or_estimated_analytics_used": False,
            "credential_values_persisted": False,
            "legacy_descriptor_fabricated": False,
            "publication_blocked_by_descriptor": False,
            "zero_paid_dependency": True,
        },
    }
    value["descriptor_fingerprint_sha256"] = catalog_core._descriptor_fingerprint(value)
    return value


def write_catalog(root: Path, ch: dict, *rows: dict) -> Path:
    value = catalog_core.empty_catalog(ch)
    for row in rows:
        value["records"][row["publication_id"]] = copy.deepcopy(row)
    value["catalog_fingerprint_sha256"] = catalog_core._catalog_fingerprint(value)
    path = root / catalog_core.expected_catalog_path(ch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class FakeNoDataTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.credentials: list[str] = []

    def __call__(self, ch, publication, access, credential, **kwargs):
        self.calls.append(copy.deepcopy(publication))
        self.credentials.append(credential)
        return {
            "status": "NO_OBSERVED_METRICS",
            "hard_blocks": [],
            "metric_issues": [],
            "publication_blocked": False,
        }


class OperationalMetricsHarvestAcceptance(unittest.TestCase):
    def test_missing_catalog_is_clean_noop_and_never_fabricates_legacy_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeNoDataTransport()
            result = trigger.run_channel(
                channel(), attestation(), repo_root=Path(tmp), now="2026-08-16T15:00:00Z",
                transport_call=fake, credential_resolver=lambda _: "secret",
            )
            self.assertEqual("NO_AUTHORITATIVE_CATALOG", result["status"])
            self.assertFalse(result["legacy_backfill_attempted"])
            self.assertFalse(result["publication_blocked"])
            self.assertEqual([], fake.calls)

    def test_descriptor_complete_catalog_executes_latest_due_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ch = channel(); write_catalog(root, ch, descriptor(ch))
            fake = FakeNoDataTransport()
            result = trigger.run_channel(
                ch, attestation(), repo_root=root, now="2026-08-16T15:00:00Z",
                transport_call=fake, credential_resolver=lambda _: "runtime-token",
            )
            self.assertEqual("HARVEST_RUNTIME_EXECUTED", result["status"], result)
            self.assertEqual(1, len(fake.calls))
            self.assertEqual(6, result["plan"]["jobs"][0]["checkpoint"]["checkpoint_hours"])
            checkpoint = root / metrics_harvest_runtime.expected_checkpoint_state_path(ch)
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual("COMPLETED_NO_DATA", next(iter(state["entries"].values()))["status"])

    def test_completed_no_data_checkpoint_is_not_fetched_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ch = channel(); write_catalog(root, ch, descriptor(ch))
            fake = FakeNoDataTransport(); resolver = lambda _: "runtime-token"
            first = trigger.run_channel(ch, attestation(), repo_root=root, now="2026-08-16T15:00:00Z", transport_call=fake, credential_resolver=resolver)
            second = trigger.run_channel(ch, attestation(), repo_root=root, now="2026-08-16T15:00:00Z", transport_call=fake, credential_resolver=resolver)
            self.assertEqual("HARVEST_RUNTIME_EXECUTED", first["status"])
            self.assertEqual("HARVEST_RUNTIME_EXECUTED", second["status"])
            self.assertEqual(1, len(fake.calls))
            self.assertTrue(second["runtime"]["results"][0]["status"].startswith("ALREADY_"))

    def test_dry_run_plans_without_network_or_checkpoint_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ch = channel(); write_catalog(root, ch, descriptor(ch)); fake = FakeNoDataTransport()
            result = trigger.run_channel(ch, attestation(), repo_root=root, now="2026-08-16T15:00:00Z", execute=False, transport_call=fake)
            self.assertEqual("HARVEST_READY", result["status"])
            self.assertIsNone(result["runtime"])
            self.assertEqual([], fake.calls)
            self.assertFalse((root / metrics_harvest_runtime.expected_checkpoint_state_path(ch)).exists())

    def test_tampered_catalog_fails_closed_before_scheduler_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ch = channel(); path = write_catalog(root, ch, descriptor(ch)); fake = FakeNoDataTransport()
            value = json.loads(path.read_text(encoding="utf-8")); row = next(iter(value["records"].values())); row["topic_keys"] = ["tampered"]
            path.write_text(json.dumps(value), encoding="utf-8")
            result = trigger.run_channel(ch, attestation(), repo_root=root, now="2026-08-16T15:00:00Z", transport_call=fake)
            self.assertEqual("HOLD_CATALOG", result["status"])
            self.assertEqual([], fake.calls)
            self.assertFalse(result["publication_blocked"])

    def test_cross_instance_catalog_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ch = channel(); path = write_catalog(root, ch, descriptor(ch))
            value = json.loads(path.read_text(encoding="utf-8")); value["instance_id"] = "foreign"; value["catalog_fingerprint_sha256"] = catalog_core._catalog_fingerprint(value)
            path.write_text(json.dumps(value), encoding="utf-8")
            result = trigger.run_channel(ch, attestation(), repo_root=root, now="2026-08-16T15:00:00Z")
            self.assertEqual("HOLD_CATALOG", result["status"])
            self.assertIn("CATALOG_INSTANCE_MISMATCH", result["hard_blocks"])

    def test_zero_paid_dependency_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ch = channel(); ch["zero_paid_dependency"] = False
            result = trigger.run_channel(ch, attestation(), repo_root=Path(tmp), now="2026-08-16T15:00:00Z")
            self.assertEqual("HOLD_TRIGGER_POLICY", result["status"])
            self.assertIn("ZERO_PAID_DEPENDENCY_VIOLATION", result["hard_blocks"])

    def test_unverified_meta_access_never_reaches_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ch = channel(); write_catalog(root, ch, descriptor(ch)); fake = FakeNoDataTransport()
            result = trigger.run_channel(ch, attestation(facebook_ready=False), repo_root=root, now="2026-08-16T15:00:00Z", transport_call=fake)
            self.assertEqual("NO_HARVEST_DUE", result["status"])
            self.assertEqual([], fake.calls)
            self.assertTrue(any(item["reason"] == "TRANSPORT_NOT_ELIGIBLE" for item in result["plan"]["skipped"]))

    def test_runtime_secret_value_is_not_returned_or_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ch = channel(); write_catalog(root, ch, descriptor(ch)); fake = FakeNoDataTransport(); secret = "super-secret-runtime-token"
            result = trigger.run_channel(ch, attestation(), repo_root=root, now="2026-08-16T15:00:00Z", transport_call=fake, credential_resolver=lambda _: secret)
            encoded = json.dumps(result, ensure_ascii=False)
            checkpoint = (root / metrics_harvest_runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8")
            self.assertNotIn(secret, encoded)
            self.assertNotIn(secret, checkpoint)
            self.assertEqual([secret], fake.credentials)

    def test_facebook_and_instagram_keep_separate_catalog_and_checkpoint_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fb = channel("facebook"); ig = channel("instagram")
            write_catalog(root, fb, descriptor(fb)); write_catalog(root, ig, descriptor(ig)); fake = FakeNoDataTransport()
            report = trigger.run_operational_harvest([ig, fb], attestation(), repo_root=root, now="2026-08-16T15:00:00Z", transport_call=fake, credential_resolver=lambda _: "token")
            self.assertEqual("HARVEST_EXECUTED", report["status"], report)
            self.assertEqual(2, len(fake.calls))
            paths = {item["platform"]: item["durable_paths"]["checkpoint"] for item in report["channels"]}
            self.assertNotEqual(paths["facebook"], paths["instagram"])
            self.assertTrue((root / paths["facebook"]).exists())
            self.assertTrue((root / paths["instagram"]).exists())

    def test_one_channel_integrity_hold_does_not_stop_sibling_harvest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fb = channel("facebook"); ig = channel("instagram")
            fb_path = write_catalog(root, fb, descriptor(fb)); write_catalog(root, ig, descriptor(ig)); fake = FakeNoDataTransport()
            broken = json.loads(fb_path.read_text(encoding="utf-8")); broken["catalog_fingerprint_sha256"] = "0" * 64; fb_path.write_text(json.dumps(broken), encoding="utf-8")
            report = trigger.run_operational_harvest([fb, ig], attestation(), repo_root=root, now="2026-08-16T15:00:00Z", transport_call=fake, credential_resolver=lambda _: "token")
            self.assertEqual("PARTIAL_ANALYTICS_HOLD", report["status"])
            self.assertEqual(1, len(fake.calls))
            self.assertEqual("instagram", fake.calls[0]["platform"])
            self.assertFalse(report["publication_blocked"])

    def test_outbox_only_unsupported_channel_is_not_promoted_into_metrics_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ch = channel("facebook"); ch["platform"] = "telegram"; ch["channel_id"] = "alpha-telegram"
            result = trigger.run_channel(ch, attestation(), repo_root=Path(tmp), now="2026-08-16T15:00:00Z")
            self.assertEqual("HOLD_TRIGGER_POLICY", result["status"])
            self.assertIn("UNSUPPORTED_NATIVE_METRICS_CHANNEL", result["hard_blocks"])

    def test_report_guards_keep_analytics_outside_publication_critical_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = trigger.run_operational_harvest([channel()], attestation(), repo_root=Path(tmp), now="2026-08-16T15:00:00Z")
            self.assertFalse(report["publication_blocked"])
            self.assertFalse(report["guards"]["publication_state_mutated"])
            self.assertFalse(report["guards"]["legacy_backfill_attempted"])
            self.assertTrue(report["guards"]["analytics_advisory_only"])
            self.assertTrue(report["guards"]["zero_paid_dependency"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
