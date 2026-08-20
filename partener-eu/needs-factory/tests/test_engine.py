import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import causal, engine, package as nf_package, pipeline, primary_research, ranking


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

    def test_plan_requires_population_snapshot_count_when_missing(self):
        plan = primary_research.generate_primary_research_plan(
            [{"gap_id": "G1", "gap_type": "career_guidance"}],
            {"snapshot_id": "POP-UNKNOWN"},
        )
        self.assertEqual(plan["sampling_strategy"], "population_snapshot_required")

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


class PipelineTests(unittest.TestCase):
    def _run(self):
        return pipeline.PipelineRun(
            project_input={"project_id": "310224", "target": 251},
            call_snapshot={"call_code": "PEO/76", "indicators": ["EECO06+07", "EECR03"]},
            ruleset_version="0.2",
            source_snapshot_ids=["SRC-B", "SRC-A"],
            historical_cutoff="2024-01-12",
        )

    def test_run_id_is_deterministic_and_source_order_independent(self):
        first = self._run()
        second = pipeline.PipelineRun(
            project_input={"project_id": "310224", "target": 251},
            call_snapshot={"call_code": "PEO/76", "indicators": ["EECO06+07", "EECR03"]},
            ruleset_version="0.2",
            source_snapshot_ids=["SRC-A", "SRC-B"],
            historical_cutoff="2024-01-12",
        )
        self.assertEqual(first.run_id, second.run_id)

    def test_local_gap_adds_population_snapshot_gate(self):
        run = self._run()
        gaps = run.gap_detection(
            claims=[{
                "id": "C1",
                "scope": "school",
                "requires_direct_local": True,
                "evidence_ids": ["E1"],
                "gap_type": "career_guidance",
                "priority": True,
            }],
            evidence_by_id={"E1": {"scope": "national"}},
            population_snapshot={"snapshot_id": "POP-UNRESOLVED"},
        )
        gap_ids = {item["gap_id"] for item in gaps["gaps"]}
        self.assertIn("GAP-C1", gap_ids)
        self.assertIn("GAP-POPULATION-SNAPSHOT", gap_ids)
        plan = run.primary_research_plan(gaps, {"snapshot_id": "POP-UNRESOLVED"})
        self.assertEqual(plan["sampling_strategy"], "population_snapshot_required")

    def test_end_to_end_pre_narrative_pass(self):
        run = self._run()
        evidence = {
            "E1": {"id": "E1", "tier": "A1", "scope": "county"},
            "E2": {"id": "E2", "tier": "A2", "scope": "national"},
        }
        needs = [
            {"id": "N1", "priority": True, "evidence_ids": ["E1"]},
            {"id": "N2", "priority": True, "evidence_ids": ["E1", "E2"]},
        ]
        need_validation = run.validate_needs(needs, evidence)
        self.assertFalse(need_validation["failures"])

        trace = run.traceability(
            chains=[
                {"need_id":"N1","evidence_ids":["E1"],"intervention":"work-based learning","indicator_id":"EECO06+07"},
                {"need_id":"N2","evidence_ids":["E1","E2"],"intervention":"practice at employers","indicator_id":"EECR03"},
            ],
            need_ids=["N1", "N2"],
            indicator_ids=["EECO06+07", "EECR03"],
        )
        self.assertTrue(trace["valid"])

        release = run.release_gate({"failures": [], "evidence_gaps": []})
        self.assertTrue(release["ready_for_narrative"])
        manifest = run.manifest()
        self.assertEqual(manifest["run_id"], run.run_id)
        self.assertIn("NF11_ADVERSARIAL_QA", manifest["closed_checkpoints"])
        self.assertTrue(any(event["event"] == "NF_QA_PASSED" for event in manifest["events"]))


class RankingTests(unittest.TestCase):
    def _need(self):
        return {
            "id": "N1",
            "scope": "county",
            "evidence_ids": ["E1", "E2", "E3"],
            "confidence": 1.0,
            "ranking_dimensions": {
                "magnitude": 0.8,
                "severity": 0.7,
                "gap_strength": 0.6,
                "call_relevance": 1.0,
            },
        }

    def test_duplicate_source_does_not_inflate_evidence_count(self):
        evidence = {
            "E1": {"tier":"A1","scope":"county","source_url":"https://example/a","territory_fit":1,"population_fit":1,"recency_score":1,"directness":1},
            "E2": {"tier":"A1","scope":"county","source_url":"https://example/a","territory_fit":1,"population_fit":1,"recency_score":1,"directness":1},
            "E3": {"tier":"A2","scope":"county","source_url":"https://example/b","territory_fit":1,"population_fit":1,"recency_score":1,"directness":1},
        }
        confidence = ranking.evidence_confidence(self._need()["evidence_ids"], evidence, "county")
        self.assertEqual(confidence["independent_evidence_count"], 2)
        self.assertLessEqual(confidence["confidence_cap"], 1.0)

    def test_missing_ranking_dimension_blocks_need(self):
        need = self._need()
        del need["ranking_dimensions"]["gap_strength"]
        result = ranking.score_need(need, {})
        self.assertFalse(result["rankable"])
        self.assertIn("gap_strength", result["missing_dimensions"])

    def test_evidence_confidence_caps_final_score(self):
        evidence = {
            "E1": {"tier":"A1","scope":"county","source_url":"https://example/a","territory_fit":1,"population_fit":1,"recency_score":1,"directness":1},
            "E2": {"tier":"A2","scope":"county","source_url":"https://example/b","territory_fit":1,"population_fit":1,"recency_score":1,"directness":1},
            "E3": {"tier":"B","scope":"national","source_url":"https://example/c","territory_fit":0.5,"population_fit":0.5,"recency_score":0.5,"directness":0.5},
        }
        result = ranking.score_need(self._need(), evidence)
        self.assertTrue(result["rankable"])
        self.assertLess(result["score"], result["substantive_score"])
        self.assertEqual(result["confidence_used"], result["confidence_cap"])


class CausalGraphTests(unittest.TestCase):
    def _valid_graph(self):
        return {
            "nodes": [
                {"id":"C1","type":"cause"},
                {"id":"N1","type":"need","priority":True},
                {"id":"I1","type":"intervention"},
                {"id":"O1","type":"output"},
                {"id":"R1","type":"result"},
                {"id":"IND1","type":"indicator"},
            ],
            "edges": [
                {"source":"C1","target":"N1","relation":"CAUSES","evidence_ids":["E1"]},
                {"source":"I1","target":"N1","relation":"TARGETS"},
                {"source":"I1","target":"O1","relation":"PRODUCES"},
                {"source":"O1","target":"R1","relation":"CONTRIBUTES_TO"},
                {"source":"R1","target":"IND1","relation":"MEASURED_BY"},
            ],
        }

    def test_valid_causal_graph_passes(self):
        result = causal.validate_causal_graph(self._valid_graph())
        self.assertTrue(result["valid"])

    def test_causal_claim_without_evidence_fails(self):
        graph = self._valid_graph()
        graph["edges"][0].pop("evidence_ids")
        result = causal.validate_causal_graph(graph)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["failure"] == "causal_edge_without_evidence" for item in result["failures"]))

    def test_cycle_is_detected(self):
        graph = self._valid_graph()
        graph["nodes"].append({"id":"EFFECT1","type":"effect"})
        graph["edges"].extend([
            {"source":"N1","target":"EFFECT1","relation":"LEADS_TO","evidence_ids":["E2"]},
            {"source":"EFFECT1","target":"C1","relation":"CAUSES","evidence_ids":["E3"]},
        ])
        result = causal.validate_causal_graph(graph)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["failure"] == "causal_graph_cycle" for item in result["failures"]))


class NarrativePackTests(unittest.TestCase):
    def test_package_requires_release_gate(self):
        with self.assertRaises(engine.NeedsFactoryValidationError):
            nf_package.build_narrative_ready_pack({}, {"ranked":[],"blocked":[]}, {}, {}, {"valid":True}, {"valid":True}, {"ready_for_narrative":False})

    def test_package_builds_from_validated_claim_ledger(self):
        ranked = {"ranked":[{"need_id":"N1","rank":1,"score":72.0,"confidence_used":0.8}],"blocked":[]}
        needs = {"N1":{"id":"N1","title":"Practică relevantă","statement":"Este necesară expunerea practică relevantă.","scope":"county","evidence_ids":["E1"],"prohibited_overclaim":"Nu extrapola la nivel de școală."}}
        evidence = {"E1":{"source":"AJOFM","source_url":"https://example/e1","territory":"Vâlcea","period":"2023","tier":"A1"}}
        pack = nf_package.build_narrative_ready_pack(
            {"project_id":"310224","territory":"Vâlcea","target_group":"elevi IPT"},
            ranked,
            needs,
            evidence,
            {"valid":True,"failures":[]},
            {"valid":True,"failures":[]},
            {"ready_for_narrative":True},
        )
        self.assertEqual(pack["claim_ledger"][0]["need_id"], "N1")
        self.assertTrue(pack["pack_sha256"])
        self.assertTrue(pack["narrative_policy"]["do_not_fill_evidence_gaps"])


if __name__ == "__main__":
    unittest.main()
