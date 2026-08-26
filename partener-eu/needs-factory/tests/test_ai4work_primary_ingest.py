import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "ingest_primary_responses.py"
SCHEMA = ROOT / "runs" / "AI4WORK-STEP" / "NF-RUN-001" / "EUCONS_PRIMARY_DATA_SCHEMA.json"
REGIONS = ["Sud-Vest Oltenia", "Sud-Muntenia", "Centru"]


def adult_record(index: int, region: str, *, synthetic: bool = False) -> dict:
    return {
        "schema_version": 1,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "form_id": "AI4WORK_ADULTS_V1",
        "form_version": 1,
        "response_id": f"adult-{index}",
        "received_at": "2026-08-26T14:00:00+00:00",
        "profile": {
            "region": region,
            "status": "șomer înregistrat",
            "age_band": "30-39",
            "occupational_family": "administrativ",
        },
        "answers": {
            "Q01": 3,
            "Q02": 0,
            "Q03": 2,
            "Q04": 2,
            "Q05": 2,
            "Q06": 2,
            "Q07": False,
            "Q07_topic": "",
            "Q08": ["lipsa timpului"],
            "Q09": ["nu am folosit AI"],
            "Q10": {
                "utilizare_digitala_functionala": 3,
                "utilizarea_instrumentelor_AI": 4,
                "verificarea_rezultatelor_AI": 4,
                "protectia_datelor_confidentialitate": 4,
                "integrarea_AI_in_flux_de_lucru": 4,
            },
            "Q11": "adaptare mai bună la postul actual",
            "Q12": "Sarcini repetitive de raportare",
        },
        "synthetic": synthetic,
    }


def employer_record(index: int, region: str, *, synthetic: bool = False) -> dict:
    return {
        "schema_version": 1,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "form_id": "AI4WORK_EMPLOYERS_V1",
        "form_version": 1,
        "response_id": f"employer-{index}",
        "received_at": "2026-08-26T14:00:00Z",
        "profile": {
            "region": region,
            "sector_aggregated": "servicii profesionale",
            "size_band": "10-49",
            "respondent_role": "management",
        },
        "answers": {
            "E01": "pilot/test",
            "E02": ["documente/compliance"],
            "E03": {
                "formularea_cerintelor": 4,
                "verificarea_calitatii": 5,
                "protectia_datelor": 4,
                "limitele_si_riscurile_AI": 4,
                "integrarea_in_procese": 4,
                "definirea_fluxului_asistat_AI": 4,
                "competente_digitale_generale": 3,
            },
            "E04": "da",
            "E04_detail": "Verificarea rezultatelor și integrarea în procese",
            "E05": "nu",
            "E06": ["timp disponibil"],
            "E07": "moderat",
            "E08": ["verificarea factuală/calității", "protecția datelor"],
            "E09": "Revizuirea documentelor și controlul calității",
            "E10": "posibil",
        },
        "synthetic": synthetic,
    }


class AI4WorkPrimaryIngestTests(unittest.TestCase):
    def run_ingest(self, records: list[dict], stream: str, mode: str = "prod"):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "raw.json"
            output = directory / "normalized.jsonl"
            report = directory / "report.json"
            source.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    str(source),
                    "--schema",
                    str(SCHEMA),
                    "--stream",
                    stream,
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                    "--mode",
                    mode,
                ],
                capture_output=True,
                text=True,
            )
            parsed_report = json.loads(report.read_text(encoding="utf-8"))
            rows = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            return result, parsed_report, rows

    def test_adult_runtime_export_transforms_to_nf06_schema(self):
        records = [adult_record(i, region) for i, region in enumerate(REGIONS)]
        result, report, rows = self.run_ingest(records, "adults")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["coverage_gate"], "THREE_REGION_COVERAGE_PASS")
        self.assertTrue(report["promotion_allowed"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["answers"]["Q07"], "nu")
        self.assertTrue(rows[0]["answers"]["privacy_ack"])
        self.assertEqual(rows[0]["answers"]["Q10_verification"], 4)
        self.assertNotIn("profile", rows[0])

    def test_employer_runtime_export_transforms_to_nf06_schema(self):
        records = [employer_record(i, region) for i, region in enumerate(REGIONS)]
        result, report, rows = self.run_ingest(records, "employers")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["promotion_allowed"])
        self.assertEqual(rows[0]["answers"]["E03_verification"], 5)
        self.assertEqual(rows[0]["answers"]["size"], "10-49")

    def test_prod_rejects_synthetic_marker_true(self):
        records = [adult_record(i, region, synthetic=True) for i, region in enumerate(REGIONS)]
        result, report, rows = self.run_ingest(records, "adults")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["promotion_allowed"])
        self.assertEqual(rows, [])
        self.assertTrue(any("synthetic must be false" in err for row in report["errors"] for err in row["errors"]))

    def test_test_twin_requires_synthetic_true_and_never_promotes(self):
        records = [adult_record(i, region, synthetic=True) for i, region in enumerate(REGIONS)]
        result, report, rows = self.run_ingest(records, "adults", mode="test-twin")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["evidence_classification"], "TEST_TWIN_NON_EVIDENCE")
        self.assertFalse(report["promotion_allowed"])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["synthetic"] is True for row in rows))

    def test_pii_like_text_fails_closed(self):
        records = [adult_record(i, region) for i, region in enumerate(REGIONS)]
        records[0]["profile"]["occupational_family"] = "contact test@example.com"
        result, report, rows = self.run_ingest(records, "adults")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["promotion_allowed"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("PII-like token detected" in err for row in report["errors"] for err in row["errors"]))


if __name__ == "__main__":
    unittest.main()
