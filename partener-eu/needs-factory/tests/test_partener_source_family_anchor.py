import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.partener_source_gate import reconcile_receipt_with_source_registry


NOW = datetime(2026, 8, 20, 6, 30, tzinfo=timezone.utc)


def registry():
    return {
        "schema_version": "1.3",
        "observed_at": "2026-08-20T06:00:00Z",
        "sources": [
            {
                "id": "SRC-ANOFM-VALCEA-STATS",
                "tier": "T1B",
                "class": "official_county_employment_statistics",
                "url": "https://www.anofm.ro/valcea/categorie/statistica-somaj/",
                "final_url": "https://www.anofm.ro/valcea/categorie/statistica-somaj/",
                "source_families": ["AJOFM", "ANOFM"],
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
        ],
    }


def receipt(source_family):
    return {
        "candidate_id": "CAND-1",
        "requirement_id": "REQ-LM-001",
        "source": "AJOFM Vâlcea",
        "source_family": source_family,
        "source_registry_id": "SRC-ANOFM-VALCEA-STATS",
        "final_url": "https://www.anofm.ro/valcea/rata-somajului-iunie-2026/",
        "health": "PASS",
        "quarantined": False,
        "raw_sha256": "x" * 64,
        "semantic_sha256": "y" * 64,
    }


class PartenerSourceFamilyAnchorTests(unittest.TestCase):
    def test_registered_family_is_authorized(self):
        result = reconcile_receipt_with_source_registry(receipt("AJOFM"), registry(), now=NOW)
        self.assertTrue(result["source_registry_gate"]["valid"])
        self.assertEqual(
            result["source_registry_gate"]["registry_source_families"],
            ["AJOFM", "ANOFM"],
        )

    def test_wrong_family_cannot_borrow_healthy_registry_root(self):
        result = reconcile_receipt_with_source_registry(receipt("MIPE"), registry(), now=NOW)
        self.assertFalse(result["source_registry_gate"]["valid"])
        self.assertIn(
            "registry_source_family_mismatch",
            result["source_registry_gate"]["failures"],
        )
        self.assertEqual(result["health"], "FAIL")
        self.assertTrue(result["quarantined"])


if __name__ == "__main__":
    unittest.main()
