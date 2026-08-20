import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.civora_discovery import validate_discovery_receipt


def task():
    return {
        "requirement_id": "REQ-LM-001",
        "construct": "labour_demand",
        "priority": "primary",
        "preferred_scopes": ["county", "region", "national"],
        "preferred_source_families": ["AJOFM", "ANOFM", "INS", "Eurostat"],
        "direct_local_required": False,
        "allowed_measure_types": ["count"],
    }


def receipt(source_family="AJOFM"):
    return {
        "candidate_id": "CAND-1",
        "requirement_id": "REQ-LM-001",
        "source": "Official source",
        "source_family": source_family,
        "final_url": "https://official.example/document",
        "health": "PASS",
        "quarantined": False,
        "semantic_sha256": "s" * 64,
        "scope": "county",
        "territory": "Vâlcea",
        "constructs": ["labour_demand"],
        "direct_measurement": True,
        "publication_date": "2023-12-01",
        "facts": [
            {
                "construct": "labour_demand",
                "territory": "Vâlcea",
                "scope": "county",
                "period": "2023",
                "measures": [
                    {
                        "name": "vacancies",
                        "measure_type": "count",
                        "value": 10,
                        "unit": "jobs",
                        "calculated": False,
                    }
                ],
            }
        ],
    }


class DiscoverySourceFamilyGateTests(unittest.TestCase):
    def test_preferred_source_family_passes(self):
        result = validate_discovery_receipt(receipt("AJOFM"), task(), historical_cutoff="2024-01-12")
        self.assertTrue(result["valid"])

    def test_healthy_but_wrong_source_family_fails_closed(self):
        result = validate_discovery_receipt(receipt("MIPE"), task(), historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertIn("source_family_not_preferred_for_task", result["failures"])


if __name__ == "__main__":
    unittest.main()
