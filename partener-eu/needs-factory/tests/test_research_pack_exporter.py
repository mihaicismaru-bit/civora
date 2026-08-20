import tempfile
import unittest
from pathlib import Path

from exporters.research_pack import export_primary_research_pack


class ResearchPackExporterTests(unittest.TestCase):
    def plan(self):
        return {
            "schema_version":"nf.primary_research_plan.v0.1",
            "sampling_strategy":"population_snapshot_required",
            "population_snapshot_id":"POP-SYNTH",
            "questions":[
                {"question_id":"Q01","construct":"career_guidance_need","prompt":"Cât de utilă ar fi orientarea profesională personalizată?","response_type":"likert_1_5"},
                {"question_id":"Q02","construct":"career_intention","prompt":"În ce măsură intenționezi să lucrezi în domeniul calificării?","response_type":"likert_1_5"},
                {"question_id":"Q03","construct":"employer_exposure","prompt":"Ai desfășurat până acum practică la un operator economic?","response_type":"yes_no"}
            ]
        }

    def test_pack_is_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = export_primary_research_pack(self.plan(), Path(a), project_id="SYNTH")
            second = export_primary_research_pack(self.plan(), Path(b), project_id="SYNTH")
            self.assertEqual(first["files"], second["files"])
            self.assertEqual(first["package_zip"]["sha256"], second["package_zip"]["sha256"])

    def test_pack_contains_collection_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            result = export_primary_research_pack(self.plan(), Path(directory), project_id="SYNTH")
            expected = {
                "CHESTIONAR_ELEVI.md","CHESTIONAR_ELEVI.docx","POPULATION_SNAPSHOT_TEMPLATE.csv",
                "POPULATION_SNAPSHOT_METADATA.json","RAW_RESPONSES_TEMPLATE.csv","README_RESEARCH.md","RESEARCH_PACK_MANIFEST.json"
            }
            self.assertEqual(set(result["files"]) | {"RESEARCH_PACK_MANIFEST.json"}, expected)
            for name in expected:
                self.assertTrue((Path(directory) / name).exists(), name)
            self.assertTrue((Path(directory) / "PRIMARY_RESEARCH_PACK.zip").exists())

    def test_questionnaire_preserves_question_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            export_primary_research_pack(self.plan(), Path(directory), project_id="SYNTH")
            text = (Path(directory) / "CHESTIONAR_ELEVI.md").read_text(encoding="utf-8")
            for qid in ("Q01","Q02","Q03"):
                self.assertIn(qid, text)

    def test_templates_exclude_direct_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            export_primary_research_pack(self.plan(), Path(directory), project_id="SYNTH")
            header = (Path(directory) / "RAW_RESPONSES_TEMPLATE.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertNotIn("name", header.lower())
            self.assertNotIn("cnp", header.lower())
            self.assertIn("respondent_id", header)


if __name__ == "__main__":
    unittest.main()
