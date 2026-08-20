import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import engine, product_mode


class ProductModeTests(unittest.TestCase):
    def data(self):
        project = {"project_id":"SYNTH-MODE","territory":"Synthetic County","target_group":"students"}
        evidence = {
            "E1": {
                "id":"E1","source":"Synthetic direct research","tier":"A","scope":"school","territory":"Synthetic School",
                "constructs":["practice_quality"],"direct_measurement":True,
                "territory_fit":1.0,"population_fit":1.0,"recency_score":1.0,"directness":1.0,
                "measures":[{"name":"metric","measure_type":"count","value":10,"unit":"responses","calculated":False}]
            }
        }
        need = {
            "id":"N1","title":"Practică relevantă","statement":"Este necesară o experiență practică relevantă.","scope":"school","priority":True,
            "evidence_ids":["E1"],"confidence":0.8,
            "ranking_dimensions":{"magnitude":0.7,"severity":0.6,"gap_strength":0.7,"call_relevance":0.9},
            "prohibited_overclaim":"Nu extrapola dincolo de școala măsurată."
        }
        ranked = {"blocked":False,"ranked":[{"need_id":"N1","rank":1,"score":60.0,"confidence_used":0.8}]}
        release = {"ready_for_narrative":True,"blocking_failures":[],"blocking_evidence_gaps":[]}
        return project, evidence, need, ranked, release

    def test_needs_analysis_does_not_require_activity_or_indicator_traceability(self):
        project, evidence, need, ranked, release = self.data()
        pack = product_mode.build_product_narrative_pack(
            "NEEDS_ANALYSIS", project, ranked, {"N1":need}, evidence,
            causal_validation=None, traceability_validation=None, release_gate=release,
        )
        self.assertEqual(pack["product_mode"], "NEEDS_ANALYSIS")
        self.assertTrue(pack["solution_leakage_guard"]["intervention_traceability_is_downstream"])
        self.assertEqual(pack["causal_validation"]["mode"], "NOT_REQUIRED_FOR_NEEDS_ANALYSIS")
        self.assertEqual(pack["traceability_validation"]["mode"], "NOT_REQUIRED_FOR_NEEDS_ANALYSIS")
        self.assertEqual(len(pack["pack_sha256"]), 64)

    def test_proposal_support_still_requires_causal_and_traceability_validation(self):
        project, evidence, need, ranked, release = self.data()
        with self.assertRaises(engine.NeedsFactoryValidationError):
            product_mode.build_product_narrative_pack(
                "PROPOSAL_SUPPORT", project, ranked, {"N1":need}, evidence,
                causal_validation=None, traceability_validation=None, release_gate=release,
            )

    def test_activity_and_indicator_presence_only_warns_in_needs_mode(self):
        validation = product_mode.validate_mode_inputs(
            "NEEDS_ANALYSIS", has_activity_plan=True, has_indicator_plan=True, need_count=2
        )
        self.assertTrue(validation["valid"])
        self.assertIn("activity_plan_present_but_not_used_to_create_needs", validation["warnings"])
        self.assertIn("indicator_plan_present_but_not_used_to_create_needs", validation["warnings"])
        self.assertFalse(validation["policy"]["activities_may_create_needs"])
        self.assertFalse(validation["policy"]["indicators_may_create_needs"])

    def test_no_validated_needs_blocks_product_mode(self):
        validation = product_mode.validate_mode_inputs(
            "NEEDS_ANALYSIS", has_activity_plan=False, has_indicator_plan=False, need_count=0
        )
        self.assertFalse(validation["valid"])
        self.assertIn("no_validated_needs", validation["failures"])


if __name__ == "__main__":
    unittest.main()
