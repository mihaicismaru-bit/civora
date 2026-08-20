import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import civora_discovery, partener_call
from core import research_requirements


ROOT = Path(__file__).resolve().parents[1]


class ResearchPlannerTests(unittest.TestCase):
    def profile(self):
        return json.loads((ROOT / "profiles" / "peo_ipt_work_based_learning.json").read_text(encoding="utf-8"))

    def call(self):
        return partener_call.normalize_call_intelligence({
            "call_code": "PEO/76/PEO_P8/OP4/ESO4.5/PEO_A3",
            "title": "Stagii de practica pentru elevi",
            "program": "PEO",
            "priority": "P8",
            "specific_objective": "ESO4.5",
            "target_group": "elevi IPT inclusiv dual",
            "indicators": ["EECO06+07", "EECR03"],
            "eligible_activities": ["programe de invatare la locul de munca"],
            "evaluation_criteria": ["fundamentarea nevoilor"],
            "evidence_constructs": ["labour_demand", "ipt_system_relevance", "qualification_offer"],
            "source_snapshot_ids": ["SRC-MYSMIS-CALLS@abc", "GUIDE-PEO76@def"],
            "guide_version": "historical",
            "guide_date": "2023-08-18",
        })

    def request(self):
        return research_requirements.build_research_request(
            {
                "project_id": "310224",
                "territory": "Vâlcea / Râmnicu Vâlcea",
                "target_group": "elevi IPT inclusiv dual",
                "beneficiary": "CCI Vâlcea",
                "partner_school": "Liceul Tehnologic Căpitan Nicolae Pleșoianu",
                "qualifications": ["Mecanic auto", "Electrician auto"],
            },
            self.call(),
            self.profile(),
            historical_cutoff="2024-01-12",
        )

    def test_profile_is_valid_and_request_is_deterministic(self):
        validation = research_requirements.validate_profile(self.profile())
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["requirement_count"], 9)
        first = self.request()
        second = self.request()
        self.assertEqual(first["request_sha256"], second["request_sha256"])
        self.assertEqual(len(first["tasks"]), 9)

    def test_primary_research_tasks_are_explicit(self):
        request = self.request()
        tasks = {task["requirement_id"]: task for task in request["tasks"]}
        self.assertEqual(tasks["REQ-PR-001"]["task_type"], "PRIMARY_RESEARCH")
        self.assertEqual(tasks["REQ-PR-002"]["task_type"], "PRIMARY_RESEARCH")
        self.assertEqual(tasks["REQ-PR-004"]["task_type"], "PRIMARY_RESEARCH")
        self.assertEqual(tasks["REQ-PR-003"]["task_type"], "DISCOVERY_THEN_PRIMARY_IF_GAP")

    def test_partener_call_requires_provenance(self):
        with self.assertRaises(partener_call.PartenerCallError):
            partener_call.normalize_call_intelligence({
                "call_code": "X", "title": "X", "specific_objective": "X", "target_group": "X", "indicators": ["I"]
            })

    def test_call_snapshot_lineage_rejects_unknown_source(self):
        call = self.call()
        result = partener_call.validate_call_snapshot_lineage(call, ["SRC-MYSMIS-CALLS@abc"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["unknown_source_snapshot_ids"], ["GUIDE-PEO76@def"])


class CivoraDiscoveryAdapterTests(unittest.TestCase):
    def task(self):
        request = ResearchPlannerTests().request()
        return {task["requirement_id"]: task for task in request["tasks"]}["REQ-LM-001"]

    def valid_receipt(self):
        return {
            "candidate_id": "AJOFM-VL-2023-01",
            "requirement_id": "REQ-LM-001",
            "source": "AJOFM Vâlcea",
            "source_family": "AJOFM",
            "official": True,
            "tier": "A1",
            "final_url": "https://example.test/ajofm",
            "source_document_id": "AJOFM-VL-2023",
            "health": "PASS",
            "quarantined": False,
            "raw_sha256": "r" * 64,
            "semantic_sha256": "s" * 64,
            "scope": "county",
            "territory": "Vâlcea",
            "population": "registered unemployed / employers",
            "constructs": ["labour_demand"],
            "direct_measurement": True,
            "publication_date": "2023-12-01",
            "period": "2023",
            "last_success": "2023-12-01T12:00:00Z",
            "material_fact_state": "STABLE_LAST_KNOWN_GOOD",
            "facts": [
                {
                    "construct": "labour_demand",
                    "territory": "Vâlcea",
                    "scope": "county",
                    "period": "2023",
                    "measures": [
                        {"name":"vacancies","measure_type":"count","value":120,"unit":"jobs","calculated":False},
                        {"name":"technical_share","measure_type":"share","source_measure_type":"share","value":0.42,"numerator":50,"denominator_universe":"reported vacancies","unit":"proportion","calculated":True}
                    ]
                }
            ]
        }

    def test_valid_official_receipt_promotes_to_evidence(self):
        result = civora_discovery.promote_discovery_receipt(self.valid_receipt(), self.task(), historical_cutoff="2024-01-12")
        self.assertEqual(len(result["evidence"]), 1)
        evidence = result["evidence"][0]
        self.assertEqual(evidence["tier"], "A1")
        self.assertEqual(evidence["scope"], "county")
        self.assertEqual(evidence["constructs"], ["labour_demand"])
        self.assertEqual(evidence["semantic_sha256"], "s" * 64)

    def test_quarantined_source_fails(self):
        receipt = self.valid_receipt()
        receipt["quarantined"] = True
        result = civora_discovery.validate_discovery_receipt(receipt, self.task(), historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertIn("source_quarantined", result["failures"])

    def test_post_cutoff_source_fails(self):
        receipt = self.valid_receipt()
        receipt["publication_date"] = "2024-02-01"
        result = civora_discovery.validate_discovery_receipt(receipt, self.task(), historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertIn("post_cutoff_source", result["failures"])

    def test_wrong_construct_fails(self):
        receipt = self.valid_receipt()
        receipt["constructs"] = ["career_guidance_need"]
        result = civora_discovery.validate_discovery_receipt(receipt, self.task(), historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertIn("construct_not_supported", result["failures"])

    def test_invalid_share_semantics_fail(self):
        receipt = self.valid_receipt()
        receipt["facts"][0]["measures"][1].pop("denominator_universe")
        result = civora_discovery.validate_discovery_receipt(receipt, self.task(), historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertTrue(any("missing_denominator_universe" in failure for failure in result["failures"]))

    def test_media_cannot_support_primary_requirement(self):
        receipt = self.valid_receipt()
        receipt["source_family"] = "media"
        receipt["official"] = False
        result = civora_discovery.validate_discovery_receipt(receipt, self.task(), historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertIn("media_cannot_support_priority_requirement", result["failures"])

    def test_direct_school_requirement_rejects_nonlocal_receipt(self):
        request = ResearchPlannerTests().request()
        task = {task["requirement_id"]: task for task in request["tasks"]}["REQ-EDU-002"]
        receipt = self.valid_receipt()
        receipt["requirement_id"] = "REQ-EDU-002"
        receipt["constructs"] = ["qualification_offer"]
        result = civora_discovery.validate_discovery_receipt(receipt, task, historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertIn("scope_not_acceptable_for_task", result["failures"])


if __name__ == "__main__":
    unittest.main()
