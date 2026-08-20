import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.partener_source_gate import (
    PartenerSourceGateProvider,
    reconcile_receipt_with_source_registry,
)


NOW = datetime(2026, 8, 20, 6, 30, tzinfo=timezone.utc)


def registry_source(**overrides):
    source = {
        "id": "SRC-AUTH-TEST",
        "tier": "T1",
        "class": "authoritative_test_source",
        "url": "https://official.example/source",
        "final_url": "https://official.example/source",
        "material_fact_use": True,
        "ok": True,
        "health": "PASS",
        "quarantined": False,
        "content_quality_ok": True,
        "semantic_hash_changed": False,
        "resolution_task_required": False,
        "raw_sha256": "a" * 64,
        "semantic_sha256": "b" * 64,
    }
    source.update(overrides)
    return source


def registry(*sources, observed_at="2026-08-20T06:00:00Z"):
    return {
        "schema_version": "1.3",
        "observed_at": observed_at,
        "policy": "health-and-hash-only-no-material-fact-autoupdate-low-information-fail-closed",
        "sources": list(sources),
    }


def receipt(**overrides):
    item = {
        "candidate_id": "CAND-1",
        "requirement_id": "REQ-1",
        "source": "Provider-reported source",
        "final_url": "https://official.example/source/",
        "health": "PASS",
        "quarantined": False,
        "raw_sha256": "x" * 64,
        "semantic_sha256": "y" * 64,
    }
    item.update(overrides)
    return item


class PartenerSourceGateTests(unittest.TestCase):
    def test_healthy_registered_source_is_authorized_and_central_hashes_win(self):
        result = reconcile_receipt_with_source_registry(
            receipt(), registry(registry_source()), now=NOW
        )
        self.assertEqual(result["source_registry_id"], "SRC-AUTH-TEST")
        self.assertEqual(result["health"], "PASS")
        self.assertFalse(result["quarantined"])
        self.assertEqual(result["raw_sha256"], "a" * 64)
        self.assertEqual(result["semantic_sha256"], "b" * 64)
        self.assertTrue(result["source_registry_gate"]["valid"])
        self.assertEqual(result["material_fact_state"], "PARTENER_REGISTRY_VERIFIED")

    def test_explicit_registry_id_can_authorize_discovered_child_document(self):
        result = reconcile_receipt_with_source_registry(
            receipt(
                source_registry_id="SRC-AUTH-TEST",
                final_url="https://official.example/source/document.pdf",
            ),
            registry(registry_source()),
            now=NOW,
        )
        self.assertTrue(result["source_registry_gate"]["valid"])
        self.assertEqual(result["source_registry_id"], "SRC-AUTH-TEST")

    def test_unregistered_source_fails_closed_even_if_provider_says_pass(self):
        result = reconcile_receipt_with_source_registry(
            receipt(final_url="https://unknown.example/data"),
            registry(registry_source()),
            now=NOW,
        )
        self.assertEqual(result["health"], "FAIL")
        self.assertTrue(result["quarantined"])
        self.assertIn("unregistered_source", result["source_registry_gate"]["failures"])

    def test_quarantined_or_low_quality_registry_source_fails_closed(self):
        result = reconcile_receipt_with_source_registry(
            receipt(),
            registry(registry_source(health="FAIL", ok=False, quarantined=True, content_quality_ok=False)),
            now=NOW,
        )
        failures = result["source_registry_gate"]["failures"]
        self.assertIn("registry_health_not_pass", failures)
        self.assertIn("registry_source_quarantined", failures)
        self.assertIn("registry_content_quality_not_ok", failures)
        self.assertEqual(result["health"], "FAIL")

    def test_material_semantic_change_requires_reconciliation(self):
        result = reconcile_receipt_with_source_registry(
            receipt(),
            registry(registry_source(semantic_hash_changed=True, resolution_task_required=True)),
            now=NOW,
        )
        failures = result["source_registry_gate"]["failures"]
        self.assertIn("registry_resolution_required", failures)
        self.assertIn("material_fact_reconciliation_required", failures)
        self.assertFalse(result["source_registry_gate"]["valid"])

    def test_stale_registry_snapshot_fails_closed(self):
        result = reconcile_receipt_with_source_registry(
            receipt(),
            registry(registry_source(), observed_at="2026-08-19T23:00:00Z"),
            now=NOW,
            max_registry_age_hours=6,
        )
        self.assertIn("registry_snapshot_stale", result["source_registry_gate"]["failures"])
        self.assertEqual(result["health"], "FAIL")

    def test_wrapper_does_not_swallow_provider_errors(self):
        class RaisingProvider:
            def discover(self, task):
                raise RuntimeError("provider unavailable")

        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            registry_path.write_text(
                json.dumps(registry(registry_source())), encoding="utf-8"
            )
            provider = PartenerSourceGateProvider(
                RaisingProvider(),
                registry_path=registry_path,
                now_provider=lambda: NOW,
            )
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                provider.discover({"requirement_id": "REQ-1"})


if __name__ == "__main__":
    unittest.main()
