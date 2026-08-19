import unittest

from partener_eu_needs_factory_compat import engine, primary_research


class NeedsFactoryEngineTests(unittest.TestCase):
    def test_legacy_241_vs_200_fails_closed(self):
        result = engine.validate_sample_consistency({"analysis": 241, "cf": 200, "chart": 241})
        self.assertFalse(result["valid"])
        self.assertEqual(result["failure"], "sample_n_inconsistent")

    def test_share_cannot_be_relabelled_rate(self):
        failures = engine.validate_measure({
            "measure_type": "rate",
            "source_measure_type": "share",
            "value": 24.73,
            "denominator_universe": "registered unemployed",
        })
        self.assertIn("share_relabelled_as_rate", failures)

    def test_local_claim_without_local_evidence_becomes_gap(self):
        claims = [{
            "id": "C1", "scope": "school", "requires_direct_local": True,
            "evidence_ids": ["E1"], "gap_type": "career_guidance", "priority": True,
        }]
        evidence = {"E1": {"scope": "national"}}
        gaps = engine.detect_evidence_gaps(claims, evidence)
        self.assertEqual(len(gaps), 1)
        self.assertTrue(gaps[0]["blocking"])

    def test_indicator_cannot_create_need(self):
        need = {"id": "N1", "priority": True, "evidence_ids": ["E1"], "created_from_indicator": True}
        evidence = {"E1": {"tier": "A1"}}
        result = engine.validate_need(need, evidence)
        self.assertFalse(result["valid"])
        self.assertIn("indicator_used_to_create_need", result["failures"])

    def test_priority_need_requires_official_or_primary_evidence(self):
        need = {"id": "N1", "priority": True, "evidence_ids": ["E1"]}
        evidence = {"E1": {"tier": "B"}}
        result = engine.validate_need(need, evidence)
        self.assertIn("priority_need_without_official_or_primary_evidence", result["failures"])

    def test_traceability_requires_every_need(self):
        result = engine.validate_traceability(
            [{"need_id": "N1", "evidence_ids": ["E1"], "intervention": "practice", "indicator_id": "I1"}],
            ["N1", "N2"],
            ["I1"],
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any(f.get("value") == "N2" for f in result["failures"]))

    def test_release_blocks_high_unwaived_and_evidence_gap(self):
        result = engine.validate_release({
            "failures": [{"severity": "high", "rule": "QAR-X"}],
            "evidence_gaps": [{"gap_id": "G1", "blocking": True}],
        })
        self.assertFalse(result["ready_for_narrative"])


class PrimaryResearchTests(unittest.TestCase):
    def setUp(self):
        self.plan = primary_research.generate_primary_research_plan(
            [{"gap_id": "G1", "gap_type": "career_guidance"}],
            {"snapshot_id": "POP-1", "eligible_population_n": 2},
        )

    def test_plan_is_census_preferred_for_small_population(self):
        self.assertEqual(self.plan["sampling_strategy"], "census_preferred")
        self.assertGreaterEqual(len(self.plan["questions"]), 2)

    def test_duplicate_response_fails(self):
        qid = self.plan["questions"][0]["question_id"]
        rows = [
            {"respondent_id":"R1","population_snapshot_id":"POP-1","grade":"X","qualification":"Q","question_id":qid,"value":"3"},
            {"respondent_id":"R1","population_snapshot_id":"POP-1","grade":"X","qualification":"Q","question_id":qid,"value":"4"},
        ]
        result = primary_research.validate_raw_responses(rows, self.plan)
        self.assertFalse(result["valid"])
        self.assertTrue(any(f["failure"] == "duplicate_respondent_question" for f in result["failures"]))

    def test_deterministic_aggregate_totals(self):
        rows = []
        for respondent, values in [("R1", ["4", "5"]), ("R2", ["3", "4"])]:
            for question, value in zip(self.plan["questions"], values):
                rows.append({
                    "respondent_id": respondent,
                    "population_snapshot_id": "POP-1",
                    "grade": "X",
                    "qualification": "Q",
                    "question_id": question["question_id"],
                    "value": value,
                })
        aggregate = primary_research.aggregate_responses(rows, self.plan)
        self.assertEqual(aggregate["response_n"], 2)
        self.assertEqual(aggregate["coverage"], 1.0)
        for record in aggregate["aggregates"].values():
            self.assertEqual(record["valid_n"], 2)


if __name__ == "__main__":
    unittest.main()
