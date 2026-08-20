import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.semantic_provider import StaticNeedDecisionProvider
from adapters.partener_call import normalize_call_intelligence
from core.need_synthesis import build_need_hypotheses, promote_decision_set, validate_need_decision
from core.research_requirements import build_research_request
from core.semantic_orchestrator import run_need_synthesis


ROOT = Path(__file__).resolve().parents[1]


def request_and_policy():
    profile = json.loads((ROOT / "profiles" / "peo_ipt_work_based_learning.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "profiles" / "peo_ipt_need_synthesis.json").read_text(encoding="utf-8"))
    call = normalize_call_intelligence({
        "call_code": "PEO/76", "title": "Stagii", "specific_objective": "ESO4.5",
        "target_group": "elevi IPT", "indicators": ["EECO06+07"], "source_snapshot_ids": ["CALL@1"]
    })
    request = build_research_request(
        {"project_id":"SYNTH-NEEDS","territory":"Synthetic County","target_group":"elevi IPT","partner_school":"Synthetic School"},
        call, profile, historical_cutoff="2024-01-12"
    )
    return request, policy


def direct_evidence(construct, evidence_id):
    return {
        "id": evidence_id,
        "source": "Synthetic primary research",
        "source_type": "primary_research",
        "tier": "A",
        "health": "PASS",
        "quarantined": False,
        "territory": "Synthetic School",
        "scope": "school",
        "period": "2023-2024",
        "constructs": [construct],
        "direct_measurement": True,
        "measures": [
            {"name":"top2_share","measure_type":"share","source_measure_type":"share","value":0.75,"numerator":3,"denominator_universe":"valid responses","unit":"proportion","calculated":True}
        ]
    }


class NeedSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.request, self.policy = request_and_policy()
        self.evidence = {
            "E-GUID": direct_evidence("career_guidance_need", "E-GUID"),
            "E-PRAC": direct_evidence("practice_quality", "E-PRAC"),
            "E-SKILL": direct_evidence("skills_baseline", "E-SKILL"),
            "E-CAREER": direct_evidence("career_intention", "E-CAREER"),
            "E-LABOUR": {
                "id":"E-LABOUR","source":"County source","tier":"A1","health":"PASS","quarantined":False,
                "territory":"Synthetic County","scope":"county","period":"2023","constructs":["labour_demand"],"direct_measurement":True,"measures":[]
            }
        }
        self.hypotheses = build_need_hypotheses(self.request, self.evidence, self.policy)

    def test_context_constructs_do_not_create_need_hypotheses(self):
        constructs = {item["construct"] for item in self.hypotheses["hypotheses"]}
        self.assertEqual(constructs, {"career_guidance_need","practice_quality","skills_baseline","career_intention"})
        self.assertNotIn("labour_demand", constructs)

    def test_direct_local_evidence_makes_all_four_hypotheses_ready(self):
        self.assertEqual(len(self.hypotheses["hypotheses"]), 4)
        self.assertTrue(all(item["status"] == "EVIDENCE_AVAILABLE" for item in self.hypotheses["hypotheses"]))

    def supported_decision(self, hypothesis):
        evidence_id = hypothesis["evidence_ids"][0]
        return {
            "hypothesis_id": hypothesis["hypothesis_id"],
            "decision": "supported",
            "need_title": f"Need for {hypothesis['construct']}",
            "need_statement": f"Evidence supports a material need related to {hypothesis['construct']}.",
            "evidence_ids": [evidence_id],
            "confidence": 0.8,
            "ranking_dimensions": {"magnitude":0.7,"severity":0.6,"gap_strength":0.7,"call_relevance":0.9},
            "ranking_evidence": {
                "magnitude":[evidence_id],"severity":[evidence_id],"gap_strength":[evidence_id],"call_relevance":[evidence_id]
            },
            "prohibited_overclaim": hypothesis["prohibited_overclaim"]
        }

    def test_valid_supported_decision_promotes_need(self):
        hypothesis = self.hypotheses["hypotheses"][0]
        decision = self.supported_decision(hypothesis)
        result = promote_decision_set({"hypotheses":[hypothesis]}, [decision], self.evidence)
        self.assertEqual(result["state"], "READY_FOR_RANKING")
        self.assertEqual(len(result["needs"]), 1)
        need = result["needs"][0]
        self.assertTrue(need["id"].startswith("NEED-"))
        self.assertFalse(need["created_from_indicator"])
        self.assertEqual(need["prohibited_overclaim"], hypothesis["prohibited_overclaim"])

    def test_cause_field_is_forbidden(self):
        hypothesis = self.hypotheses["hypotheses"][0]
        decision = self.supported_decision(hypothesis)
        decision["causes"] = ["invented cause"]
        validation = validate_need_decision(decision, hypothesis, self.evidence)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["failure"] == "causal_fields_forbidden_at_need_synthesis" for item in validation["failures"]))

    def test_unknown_evidence_reference_is_forbidden(self):
        hypothesis = self.hypotheses["hypotheses"][0]
        decision = self.supported_decision(hypothesis)
        decision["evidence_ids"] = ["E-INVENTED"]
        validation = validate_need_decision(decision, hypothesis, self.evidence)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["failure"] == "decision_uses_unapproved_evidence" for item in validation["failures"]))

    def test_overclaim_limit_cannot_be_changed(self):
        hypothesis = self.hypotheses["hypotheses"][0]
        decision = self.supported_decision(hypothesis)
        decision["prohibited_overclaim"] = "weaker limit"
        validation = validate_need_decision(decision, hypothesis, self.evidence)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["failure"] == "prohibited_overclaim_not_preserved" for item in validation["failures"]))

    def test_ranking_dimension_requires_evidence_basis(self):
        hypothesis = self.hypotheses["hypotheses"][0]
        decision = self.supported_decision(hypothesis)
        decision["ranking_evidence"]["severity"] = []
        validation = validate_need_decision(decision, hypothesis, self.evidence)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["failure"] == "ranking_dimension_without_evidence" for item in validation["failures"]))

    def test_not_supported_decision_does_not_promote_need(self):
        hypothesis = self.hypotheses["hypotheses"][0]
        decision = {
            "hypothesis_id": hypothesis["hypothesis_id"],
            "decision": "not_supported",
            "evidence_ids": hypothesis["evidence_ids"],
            "prohibited_overclaim": hypothesis["prohibited_overclaim"]
        }
        result = promote_decision_set({"hypotheses":[hypothesis]}, [decision], self.evidence)
        self.assertEqual(result["state"], "NO_SUPPORTED_NEEDS")
        self.assertEqual(result["needs"], [])

    def test_orchestrator_only_promotes_valid_provider_decisions(self):
        decisions = {}
        for index, hypothesis in enumerate(self.hypotheses["hypotheses"]):
            if index == 0:
                decisions[hypothesis["hypothesis_id"]] = self.supported_decision(hypothesis)
            else:
                decisions[hypothesis["hypothesis_id"]] = {
                    "hypothesis_id": hypothesis["hypothesis_id"],
                    "decision": "not_supported",
                    "evidence_ids": hypothesis["evidence_ids"],
                    "prohibited_overclaim": hypothesis["prohibited_overclaim"]
                }
        provider = StaticNeedDecisionProvider(decisions)
        result = run_need_synthesis(self.hypotheses, self.evidence, provider)
        self.assertEqual(result["state"], "READY_FOR_RANKING")
        self.assertEqual(len(result["needs"]), 1)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(result["provider_errors"], [])


if __name__ == "__main__":
    unittest.main()
