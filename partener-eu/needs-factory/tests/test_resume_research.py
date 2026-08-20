import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import engine, pipeline, population, primary_research, research_evidence, resume


class PopulationSnapshotTests(unittest.TestCase):
    def valid_snapshot(self):
        return {
            "snapshot_id": "POP-SYNTH-1",
            "as_of_date": "2024-01-03",
            "school_year": "2023-2024",
            "school_identity": "Synthetic Technical School",
            "eligible_population_n": 4,
            "grades_in_scope": ["X", "XI"],
            "qualifications_in_scope": ["Mecanic auto", "Electrician auto"],
            "count_by_grade_and_qualification": [
                {"grade": "X", "qualification": "Mecanic auto", "count": 2},
                {"grade": "XI", "qualification": "Electrician auto", "count": 2},
            ],
            "source_document_id": "SYNTHETIC-AUTH-ROSTER",
            "source_date": "2024-01-05",
            "source_hash_or_receipt": "sha256:synthetic-roster",
        }

    def test_target_number_alone_is_not_population_snapshot(self):
        result = population.validate_population_snapshot(
            {"eligible_population_n": 251},
            historical_cutoff="2024-01-12",
        )
        self.assertFalse(result["valid"])
        missing = {item.get("field") for item in result["failures"] if item["failure"] == "missing_required_field"}
        self.assertIn("source_document_id", missing)
        self.assertIn("count_by_grade_and_qualification", missing)
        self.assertIn("source_hash_or_receipt", missing)

    def test_strata_must_sum_to_population(self):
        snapshot = self.valid_snapshot()
        snapshot["count_by_grade_and_qualification"][1]["count"] = 1
        result = population.validate_population_snapshot(snapshot, historical_cutoff="2024-01-12")
        self.assertFalse(result["valid"])
        self.assertTrue(any(item["failure"] == "strata_total_mismatch" for item in result["failures"]))

    def test_valid_snapshot_gets_stable_hash(self):
        first = population.validate_population_snapshot(self.valid_snapshot(), historical_cutoff="2024-01-12")
        second = population.validate_population_snapshot(self.valid_snapshot(), historical_cutoff="2024-01-12")
        self.assertTrue(first["valid"])
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])


class PrimaryResearchEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = PopulationSnapshotTests().valid_snapshot()
        self.pop_validation = population.validate_population_snapshot(self.snapshot, historical_cutoff="2024-01-12")
        self.gaps = [
            {"gap_id":"G1","gap_type":"career_guidance"},
            {"gap_id":"G2","gap_type":"practice_quality"},
            {"gap_id":"G3","gap_type":"skills_baseline"},
            {"gap_id":"G4","gap_type":"career_intention"},
        ]
        self.plan = primary_research.generate_primary_research_plan(self.gaps, self.pop_validation["normalized_snapshot"])

    def rows(self):
        responses = {
            "R1": ("X", "Mecanic auto", ["4", "4", "yes", "4", "5", "3"]),
            "R2": ("X", "Mecanic auto", ["5", "4", "yes", "5", "5", "4"]),
            "R3": ("XI", "Electrician auto", ["3", "3", "no", "3", "4", "3"]),
            "R4": ("XI", "Electrician auto", ["4", "5", "yes", "4", "5", "4"]),
        }
        rows = []
        for respondent, (grade, qualification, values) in responses.items():
            for question, value in zip(self.plan["questions"], values):
                rows.append({
                    "respondent_id": respondent,
                    "population_snapshot_id": self.snapshot["snapshot_id"],
                    "grade": grade,
                    "qualification": qualification,
                    "question_id": question["question_id"],
                    "value": value,
                })
        return rows

    def promote(self, rows):
        return research_evidence.promote_primary_research_evidence(
            rows,
            self.plan,
            self.pop_validation,
            territory="Synthetic County",
            school_identity="Synthetic Technical School",
            period="2023-2024",
            source_document_id="SYNTHETIC-SURVEY-RAW",
        )

    def test_raw_hash_is_order_independent(self):
        rows = self.rows()
        first = self.promote(rows)
        second = self.promote(list(reversed(rows)))
        self.assertEqual(first["raw_response_sha256"], second["raw_response_sha256"])
        self.assertEqual(first["aggregate_sha256"], second["aggregate_sha256"])

    def test_respondents_cannot_exceed_population_stratum(self):
        rows = self.rows()
        for question, value in zip(self.plan["questions"], ["4", "4", "yes", "4", "4", "4"]):
            rows.append({
                "respondent_id": "R5",
                "population_snapshot_id": self.snapshot["snapshot_id"],
                "grade": "X",
                "qualification": "Mecanic auto",
                "question_id": question["question_id"],
                "value": value,
            })
        with self.assertRaises(ValueError):
            self.promote(rows)

    def test_promoted_evidence_is_direct_school_evidence(self):
        promoted = self.promote(self.rows())
        self.assertEqual(len(promoted["evidence"]), 6)
        for record in promoted["evidence"].values():
            self.assertEqual(record["scope"], "school")
            self.assertEqual(record["tier"], "A")
            self.assertEqual(record["source_type"], "primary_research")
            self.assertTrue(record["direct_measurement"])
            self.assertEqual(record["population_snapshot_id"], "POP-SYNTH-1")

    def test_primary_evidence_resolves_matching_local_claims(self):
        promoted = self.promote(self.rows())
        claims = [
            {"id":"C1","scope":"school","construct":"career_guidance_need","requires_direct_local":True,"priority":True,"gap_type":"career_guidance","evidence_ids":[]},
            {"id":"C2","scope":"school","construct":"practice_quality","requires_direct_local":True,"priority":True,"gap_type":"practice_quality","evidence_ids":[]},
            {"id":"C3","scope":"school","construct":"skills_baseline","requires_direct_local":True,"priority":True,"gap_type":"skills_baseline","evidence_ids":[]},
            {"id":"C4","scope":"school","construct":"career_intention","requires_direct_local":True,"priority":True,"gap_type":"career_intention","evidence_ids":[]},
        ]
        resolved = research_evidence.attach_matching_research_evidence(claims, {}, promoted["evidence"])
        self.assertEqual(resolved["unresolved_gaps"], [])
        for claim in resolved["claims"]:
            self.assertTrue(claim["evidence_ids"])


class ResumePlannerTests(unittest.TestCase):
    def previous_manifest(self):
        return {
            "run_id": "NF-PREVIOUS",
            "closed_checkpoints": ["NF05_GAP_DETECTION", "NF06_PRIMARY_RESEARCH"],
            "artifact_hashes": {"EVIDENCE_GAPS.json": "gap-hash", "PRIMARY_RESEARCH_PLAN.json": "plan-hash"},
            "events": [
                {"checkpoint":"NF05_GAP_DETECTION","artifact_path":"EVIDENCE_GAPS.json"},
                {"checkpoint":"NF06_PRIMARY_RESEARCH","artifact_path":"PRIMARY_RESEARCH_PLAN.json"},
            ],
        }

    def test_primary_data_change_restarts_at_nf06_only(self):
        plan = resume.build_resume_plan(
            self.previous_manifest(),
            changed_inputs=["population_snapshot", "primary_research_raw"],
            successor_run_id="NF-SUCCESSOR",
        )
        self.assertTrue(resume.validate_resume_plan(plan)["valid"])
        self.assertEqual(plan["restart_stage"], "NF06_PRIMARY_RESEARCH")
        self.assertEqual(plan["reusable_closed_checkpoints"], ["NF05_GAP_DETECTION"])
        self.assertEqual(plan["preserved_artifact_hashes"], {"EVIDENCE_GAPS.json": "gap-hash"})
        self.assertIn("NF12_PACKAGE", plan["invalidated_stages"])
        self.assertNotIn("NF05_GAP_DETECTION", plan["invalidated_stages"])

    def test_successor_must_be_new_run_version(self):
        plan = resume.build_resume_plan(
            self.previous_manifest(),
            changed_inputs=["primary_research_raw"],
            successor_run_id="NF-PREVIOUS",
        )
        validation = resume.validate_resume_plan(plan)
        self.assertFalse(validation["valid"])
        self.assertIn("successor_must_be_new_version", validation["failures"])


if __name__ == "__main__":
    unittest.main()
