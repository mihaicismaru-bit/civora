import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import engine, narrative


class NarrativeCompilerTests(unittest.TestCase):
    def pack(self):
        return {
            "schema_version": "nf.narrative_ready_pack.v0.1",
            "project_id": "SYNTH-001",
            "territory": "Synthetic County",
            "target_group": "synthetic students",
            "claim_ledger": [
                {
                    "need_id": "N1",
                    "rank": 1,
                    "score": 72.5,
                    "confidence_used": 0.8,
                    "title": "Practică relevantă",
                    "statement": "Elevii au nevoie de experiență practică relevantă calificării.",
                    "scope": "school",
                    "prohibited_overclaim": "Nu afirma un deficit obiectiv de competențe dintr-o autoevaluare.",
                    "evidence_refs": [
                        {
                            "evidence_id": "E1",
                            "source": "Synthetic primary research",
                            "source_type": "primary_research",
                            "source_document_id": "SURVEY-1",
                            "source_url": None,
                            "territory": "Synthetic Technical School",
                            "scope": "school",
                            "period": "2023-2024",
                            "tier": "A",
                            "constructs": ["practice_quality"],
                            "direct_measurement": True,
                            "population_snapshot_id": "POP-1",
                            "measures": [
                                {"name":"valid_responses","measure_type":"count","value":4,"unit":"responses","calculated":True},
                                {"name":"top2_share","measure_type":"share","source_measure_type":"share","value":0.75,"numerator":3,"denominator_universe":"valid responses to Q04","unit":"proportion","calculated":True}
                            ],
                        }
                    ],
                },
                {
                    "need_id": "N2",
                    "rank": 2,
                    "score": 61.0,
                    "confidence_used": 0.7,
                    "title": "Orientare profesională",
                    "statement": "Elevii au nevoie de orientare conectată la traseele profesionale.",
                    "scope": "school",
                    "prohibited_overclaim": "Intenția declarată nu este predicție certă de angajare.",
                    "evidence_refs": [
                        {
                            "evidence_id": "E2",
                            "source": "Synthetic guidance survey",
                            "source_type": "primary_research",
                            "source_document_id": "SURVEY-1",
                            "source_url": None,
                            "territory": "Synthetic Technical School",
                            "scope": "school",
                            "period": "2023-2024",
                            "tier": "A",
                            "constructs": ["career_guidance_need"],
                            "direct_measurement": True,
                            "population_snapshot_id": "POP-1",
                            "measures": [
                                {"name":"median","measure_type":"score","value":4,"unit":"Likert 1-5","calculated":True}
                            ],
                        }
                    ],
                },
            ],
            "causal_validation": {
                "valid": True,
                "failures": [],
                "warnings": [{"node_id":"N1","warning":"priority_need_cause_not_established"}],
            },
            "traceability_validation": {"valid": True, "failures": []},
            "release_gate": {"ready_for_narrative": True, "blocking_failures": [], "blocking_evidence_gaps": []},
            "narrative_policy": {"generate_only_from_claim_ledger": True},
            "pack_sha256": "synthetic-pack-hash",
        }

    def test_compile_is_deterministic_and_valid(self):
        first = narrative.compile_analysis(self.pack())
        second = narrative.compile_analysis(self.pack())
        self.assertTrue(first["validation"]["valid"])
        self.assertEqual(first["markdown"], second["markdown"])
        self.assertEqual(first["markdown_sha256"], second["markdown_sha256"])
        self.assertIn("[NEED:N1]", first["markdown"])
        self.assertIn("[EV:E1]", first["markdown"])
        self.assertIn("75.0%", first["markdown"])
        self.assertIn("valid responses to Q04", first["markdown"])

    def test_unknown_evidence_tag_fails(self):
        compiled = narrative.compile_analysis(self.pack())
        tampered = compiled["markdown"].replace("[EV:E1]", "[EV:INVENTED]", 1)
        validation = narrative.validate_compiled_narrative(tampered, self.pack())
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["failure"] == "unknown_evidence_tags" for item in validation["failures"]))

    def test_duplicate_need_marker_fails(self):
        compiled = narrative.compile_analysis(self.pack())
        tampered = compiled["markdown"] + "\n### Extra [NEED:N1]\ntext\n"
        validation = narrative.validate_compiled_narrative(tampered, self.pack())
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["failure"] == "need_marker_not_exactly_once" for item in validation["failures"]))

    def test_missing_interpretation_limit_fails(self):
        pack = self.pack()
        compiled = narrative.compile_analysis(pack)
        limitation = pack["claim_ledger"][0]["prohibited_overclaim"]
        tampered = compiled["markdown"].replace(limitation, "limit removed", 1)
        validation = narrative.validate_compiled_narrative(tampered, pack)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["failure"] == "need_section_missing_interpretation_limit" for item in validation["failures"]))

    def test_release_gate_blocks_compiler(self):
        pack = self.pack()
        pack["release_gate"]["ready_for_narrative"] = False
        with self.assertRaises(engine.NeedsFactoryValidationError):
            narrative.compile_analysis(pack)


if __name__ == "__main__":
    unittest.main()
