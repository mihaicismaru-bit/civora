import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.civora_provider import StaticDiscoveryProvider
from adapters.partener_call import normalize_call_intelligence
from core.research_orchestrator import run_research_cycle
from core.research_requirements import build_research_request


ROOT = Path(__file__).resolve().parents[1]


def build_request():
    profile = json.loads((ROOT / "profiles" / "peo_ipt_work_based_learning.json").read_text(encoding="utf-8"))
    call = normalize_call_intelligence({
        "call_code": "PEO/76",
        "title": "Stagii de practica",
        "specific_objective": "ESO4.5",
        "target_group": "elevi IPT",
        "indicators": ["EECO06+07", "EECR03"],
        "source_snapshot_ids": ["CALL@1"],
    })
    return build_research_request(
        {
            "project_id": "SYNTH-RESEARCH",
            "territory": "Vâlcea",
            "target_group": "elevi IPT",
            "partner_school": "Synthetic School",
            "qualifications": ["Mecanic auto"],
        },
        call,
        profile,
        historical_cutoff="2024-01-12",
    )


def receipt_for(task, *, candidate_suffix="1"):
    scope = task["preferred_scopes"][0]
    direct = bool(task["direct_local_required"])
    measure_type = task["allowed_measure_types"][0] if task["allowed_measure_types"] else "count"
    if measure_type == "share":
        measure = {"name":"metric","measure_type":"share","source_measure_type":"share","value":0.5,"numerator":5,"denominator_universe":"source population","unit":"proportion","calculated":True}
    elif measure_type == "rate":
        measure = {"name":"metric","measure_type":"rate","source_measure_type":"rate","value":0.2,"numerator":2,"denominator_universe":"source population","unit":"proportion","calculated":True}
    elif measure_type == "score":
        measure = {"name":"metric","measure_type":"score","value":4,"unit":"score","calculated":False}
    elif measure_type == "qualitative":
        measure = {"name":"finding","measure_type":"qualitative","value":"documented finding","unit":None,"calculated":False}
    else:
        measure = {"name":"metric","measure_type":"count","value":10,"unit":"persons","calculated":False}
    return {
        "candidate_id": f"CAND-{task['requirement_id']}-{candidate_suffix}",
        "requirement_id": task["requirement_id"],
        "source": "Synthetic official source",
        "source_family": task["preferred_source_families"][0],
        "official": True,
        "tier": "A1",
        "final_url": "https://example.test/source",
        "source_document_id": f"DOC-{task['requirement_id']}",
        "health": "PASS",
        "quarantined": False,
        "raw_sha256": "r" * 64,
        "semantic_sha256": "s" * 64,
        "scope": scope,
        "territory": "Synthetic School" if scope == "school" else "Vâlcea",
        "population": "relevant population",
        "constructs": [task["construct"]],
        "direct_measurement": direct,
        "publication_date": "2023-12-01",
        "period": "2023",
        "facts": [
            {
                "construct": task["construct"],
                "territory": "Synthetic School" if scope == "school" else "Vâlcea",
                "scope": scope,
                "period": "2023",
                "measures": [measure],
            }
        ],
    }


class ResearchOrchestratorTests(unittest.TestCase):
    def test_external_tasks_execute_and_pure_primary_tasks_do_not(self):
        request = build_request()
        receipts = {}
        hybrid_req = None
        external_req_ids = []
        pure_primary_ids = []
        for task in request["tasks"]:
            if task["task_type"] == "PRIMARY_RESEARCH":
                pure_primary_ids.append(task["requirement_id"])
                continue
            external_req_ids.append(task["requirement_id"])
            if task["task_type"] == "DISCOVERY_THEN_PRIMARY_IF_GAP":
                hybrid_req = task["requirement_id"]
                receipts[task["requirement_id"]] = []
            else:
                receipts[task["requirement_id"]] = [receipt_for(task)]
        provider = StaticDiscoveryProvider(receipts)
        result = run_research_cycle(request, provider)
        self.assertEqual(set(provider.calls), set(external_req_ids))
        self.assertTrue(set(pure_primary_ids).isdisjoint(provider.calls))
        self.assertEqual(result["state"], "READY_FOR_PRIMARY_RESEARCH")
        queued = {item["requirement_id"] for item in result["primary_research_queue"]}
        self.assertTrue(set(pure_primary_ids).issubset(queued))
        self.assertIn(hybrid_req, queued)
        self.assertEqual(result["unresolved_external_primary"], [])
        self.assertGreater(result["counts"]["evidence_records"], 0)

    def test_missing_primary_external_evidence_blocks_discovery(self):
        request = build_request()
        provider = StaticDiscoveryProvider({})
        result = run_research_cycle(request, provider)
        self.assertEqual(result["state"], "BLOCKED_DISCOVERY")
        self.assertGreater(len(result["unresolved_external_primary"]), 0)
        self.assertEqual(result["counts"]["evidence_records"], 0)

    def test_rejected_candidate_does_not_become_evidence(self):
        request = build_request()
        tasks = {task["requirement_id"]: task for task in request["tasks"]}
        target = tasks["REQ-LM-001"]
        bad = receipt_for(target)
        bad["health"] = "FAIL"
        provider = StaticDiscoveryProvider({"REQ-LM-001": [bad]})
        result = run_research_cycle(request, provider)
        self.assertEqual(result["state"], "BLOCKED_DISCOVERY")
        self.assertEqual(result["counts"]["evidence_records"], 0)
        self.assertEqual(result["counts"]["rejected_candidates"], 1)

    def test_supporting_gap_alone_does_not_block_when_primary_external_is_covered(self):
        request = build_request()
        receipts = {}
        for task in request["tasks"]:
            if task["task_type"] == "PRIMARY_RESEARCH":
                continue
            if task["priority"] == "supporting":
                receipts[task["requirement_id"]] = []
            elif task["task_type"] == "DISCOVERY_THEN_PRIMARY_IF_GAP":
                receipts[task["requirement_id"]] = []
            else:
                receipts[task["requirement_id"]] = [receipt_for(task)]
        result = run_research_cycle(request, StaticDiscoveryProvider(receipts))
        self.assertEqual(result["state"], "READY_FOR_PRIMARY_RESEARCH")
        self.assertEqual(result["unresolved_external_primary"], [])
        self.assertGreater(len(result["unresolved_external_supporting"]), 0)


if __name__ == "__main__":
    unittest.main()
