import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document

from core import narrative
from exporters import docx_exporter


class DocxExporterTests(unittest.TestCase):
    def compiled(self):
        pack = {
            "schema_version": "nf.narrative_ready_pack.v0.1",
            "project_id": "SYNTH-DOCX-001",
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
                            ]
                        }
                    ]
                }
            ],
            "causal_validation": {"valid": True, "failures": [], "warnings": []},
            "traceability_validation": {"valid": True, "failures": []},
            "release_gate": {"ready_for_narrative": True, "blocking_failures": [], "blocking_evidence_gaps": []},
            "narrative_policy": {"generate_only_from_claim_ledger": True},
            "pack_sha256": "synthetic-pack-hash"
        }
        return narrative.compile_analysis(pack)

    def test_export_is_byte_deterministic(self):
        compiled = self.compiled()
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = docx_exporter.export_final_package(compiled, Path(first_dir), basename="ANALIZA_NEVOI")
            second = docx_exporter.export_final_package(compiled, Path(second_dir), basename="ANALIZA_NEVOI")
            self.assertEqual(
                first["files"]["ANALIZA_NEVOI.docx"]["sha256"],
                second["files"]["ANALIZA_NEVOI.docx"]["sha256"],
            )
            self.assertEqual(
                first["files"]["SOURCE_REGISTER.docx"]["sha256"],
                second["files"]["SOURCE_REGISTER.docx"]["sha256"],
            )
            self.assertEqual(first["package_zip"]["sha256"], second["package_zip"]["sha256"])

    def test_docx_preserves_audit_markers_and_limits(self):
        compiled = self.compiled()
        with tempfile.TemporaryDirectory() as directory:
            manifest = docx_exporter.export_final_package(compiled, Path(directory))
            validation = manifest["docx_validation"]["ANALIZA_NEVOI.docx"]
            self.assertTrue(validation["valid"])
            self.assertEqual(validation["need_marker_count"], 1)
            self.assertEqual(validation["evidence_marker_count"], 1)
            self.assertEqual(validation["interpretation_limit_count"], 1)

    def test_docx_is_a4_with_20mm_margins(self):
        compiled = self.compiled()
        with tempfile.TemporaryDirectory() as directory:
            docx_exporter.export_final_package(compiled, Path(directory))
            document = Document(Path(directory) / "ANALIZA_NEVOI.docx")
            section = document.sections[0]
            self.assertAlmostEqual(section.page_width.mm, 210, places=0)
            self.assertAlmostEqual(section.page_height.mm, 297, places=0)
            self.assertAlmostEqual(section.left_margin.mm, 20, places=0)
            self.assertAlmostEqual(section.right_margin.mm, 20, places=0)

    def test_invalid_compiled_analysis_cannot_export(self):
        compiled = self.compiled()
        compiled["validation"]["valid"] = False
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(docx_exporter.ExportValidationError):
                docx_exporter.export_final_package(compiled, Path(directory))


if __name__ == "__main__":
    unittest.main()
