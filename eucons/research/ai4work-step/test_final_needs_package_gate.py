from __future__ import annotations

import copy
import hashlib
import io
import json
import unittest
import zipfile

import final_needs_package_gate as FINAL
from research_storage import RESEARCH_ID, canonical_json_bytes

TEST_TWIN_FIXTURES_NON_EVIDENCE = True


def records() -> list[dict]:
    result: list[dict] = []
    seq = 0
    for region in ("Sud-Vest Oltenia", "Sud-Muntenia", "Centru"):
        for form_id in ("AI4WORK_ADULTS_V1", "AI4WORK_EMPLOYERS_V1"):
            for _ in range(2):
                seq += 1
                result.append(
                    {
                        "research_id": RESEARCH_ID,
                        "form_id": form_id,
                        "response_id": hashlib.sha256(f"TEST-TWIN-{seq}".encode()).hexdigest(),
                        "received_at": "2026-08-31T00:00:00+00:00",
                        "recruitment_channel_id": "TEST-TWIN-CHANNEL",
                        "profile": {"region": region},
                        "answers": {"TEST_TWIN_ONLY": seq},
                        "synthetic": True,
                    }
                )
    return result


def rank_rows() -> list[dict]:
    return [
        {"need_id": need_id, "rank": index, "score_exact_fraction": f"{101-index}/1", "score_display_0_100": f"{101-index}.00"}
        for index, need_id in enumerate(("H1", "H2", "H3", "H4", "H5"), start=1)
    ]


def ranking() -> dict:
    dimensions = {
        need_id: {"label": f"TEST TWIN {need_id}", "combined_score_display_0_100": row["score_display_0_100"]}
        for need_id, row in zip(("H1", "H2", "H3", "H4", "H5"), rank_rows())
    }
    return {
        "schema_version": "TEST_TWIN_NON_EVIDENCE",
        "research_id": RESEARCH_ID,
        "evidence_class": FINAL.TEST_MODE,
        "source_evidence_class": FINAL.TEST_MODE,
        "dimensions": dimensions,
        "pooled_equal_population_rank": rank_rows(),
        "adult_component_rank": rank_rows(),
        "employer_component_rank": rank_rows(),
        "regional_equal_population_views": {
            region: {"rank": rank_rows()} for region in ("Sud-Vest Oltenia", "Sud-Muntenia", "Centru")
        },
        "rank_basis": "TEST TWIN mechanics only",
        "tie_rule": "TEST TWIN mechanics only",
        "public_release_authorized": False,
    }


def qa() -> dict:
    return {
        "schema_version": "TEST_TWIN_NON_EVIDENCE",
        "research_id": RESEARCH_ID,
        "evidence_class": FINAL.TEST_MODE,
        "source_evidence_class": FINAL.TEST_MODE,
        "qa_completed": True,
        "collection_must_continue": False,
        "needs_analysis_may_proceed": True,
        "overall_stability_label": "STABLE",
        "competing_orders_required": False,
        "single_definitive_rank_allowed": True,
        "dominant_channel_triggered": False,
        "repeated_signature_triggered": False,
        "sparse_profile_triggered": False,
        "zero_profile_cell_caveats": [],
        "public_release_authorized": False,
    }


def source_register() -> dict:
    return {
        "schema_version": FINAL.SOURCE_REGISTER_SCHEMA,
        "research_id": RESEARCH_ID,
        "status": FINAL.TEST_MODE,
        "test_twin_evidence_eligible": False,
        "entries": [
            {
                "source_id": "S99",
                "publisher": "TEST TWIN",
                "title": "Synthetic source-register mechanics fixture",
                "publication_date": "2026-08-31",
                "url": "https://example.invalid/test-twin-non-evidence",
                "evidence_role": "TEST_TWIN_NON_EVIDENCE",
                "h1_h5_numeric_points": 0,
                "project_activity_as_need_evidence": False,
                "numeric_rank_eligible": False,
            }
        ],
    }


class FinalNeedsPackageTests(unittest.TestCase):
    def test_test_twin_builds_deterministic_package_but_can_never_be_promoted(self):
        self.assertTrue(TEST_TWIN_FIXTURES_NON_EVIDENCE)
        first = FINAL.build_final_needs_package(
            records(),
            ranking_result=ranking(),
            adversarial_qa_result=qa(),
            source_register=source_register(),
            evidence_mode=FINAL.TEST_MODE,
        )
        second = FINAL.build_final_needs_package(
            records(),
            ranking_result=ranking(),
            adversarial_qa_result=qa(),
            source_register=source_register(),
            evidence_mode=FINAL.TEST_MODE,
        )
        manifest, analysis, docx_bytes, package_bytes = first
        self.assertEqual(package_bytes, second[3])
        self.assertEqual(manifest["evidence_class"], FINAL.TEST_MODE)
        self.assertFalse(manifest["prod_promotion_allowed"])
        self.assertFalse(manifest["public_release_authorized"])
        self.assertFalse(manifest["test_twin_evidence_eligible"])
        self.assertEqual(analysis["evidence_mode"], FINAL.TEST_MODE)
        self.assertFalse(analysis["public_release_authorized"])
        self.assertTrue(docx_bytes.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "NEEDS_ANALYSIS.json",
                    "NEEDS_ANALYSIS.docx",
                    "SOURCE_REGISTER.json",
                    "FINAL_PACKAGE_MANIFEST.json",
                },
            )
            embedded = json.loads(archive.read("FINAL_PACKAGE_MANIFEST.json"))
            self.assertFalse(embedded["prod_promotion_allowed"])
            self.assertFalse(embedded["public_release_authorized"])
            self.assertNotIn("response_id", archive.read("NEEDS_ANALYSIS.json").decode("utf-8"))

    def test_prod_mode_rejects_test_twin_records_before_any_release_claim(self):
        with self.assertRaisesRegex(FINAL.FinalNeedsPackageError, "synthetic=false"):
            FINAL.build_final_needs_package(
                records(),
                ranking_result=ranking(),
                adversarial_qa_result=qa(),
                source_register=source_register(),
                evidence_mode=FINAL.PROD_MODE,
            )

    def test_direct_identifier_or_tracking_key_is_rejected_even_in_test_twin(self):
        batch = records()
        batch[0]["email"] = "not-a-real-address@example.invalid"
        with self.assertRaisesRegex(FINAL.FinalNeedsPackageError, "forbidden identifier/tracking"):
            FINAL.build_final_needs_package(
                batch,
                ranking_result=ranking(),
                adversarial_qa_result=qa(),
                source_register=source_register(),
                evidence_mode=FINAL.TEST_MODE,
            )

    def test_source_register_cannot_turn_project_activity_into_need_evidence(self):
        register = source_register()
        register["entries"][0]["project_activity_as_need_evidence"] = True
        with self.assertRaisesRegex(FINAL.FinalNeedsPackageError, "project activity"):
            FINAL.build_final_needs_package(
                records(),
                ranking_result=ranking(),
                adversarial_qa_result=qa(),
                source_register=register,
                evidence_mode=FINAL.TEST_MODE,
            )

    def test_source_register_cannot_add_secondary_numeric_rank_points(self):
        register = source_register()
        register["entries"][0]["h1_h5_numeric_points"] = 1
        with self.assertRaisesRegex(FINAL.FinalNeedsPackageError, "numeric points"):
            FINAL.build_final_needs_package(
                records(),
                ranking_result=ranking(),
                adversarial_qa_result=qa(),
                source_register=register,
                evidence_mode=FINAL.TEST_MODE,
            )

    def test_competing_orders_cannot_coexist_with_single_definitive_rank(self):
        qa_fixture = qa()
        qa_fixture["competing_orders_required"] = True
        qa_fixture["single_definitive_rank_allowed"] = True
        with self.assertRaisesRegex(FINAL.FinalNeedsPackageError, "competing orders"):
            FINAL.build_final_needs_package(
                records(),
                ranking_result=ranking(),
                adversarial_qa_result=qa_fixture,
                source_register=source_register(),
                evidence_mode=FINAL.TEST_MODE,
            )

    def test_needs_analysis_contains_only_disclosure_controlled_sample_tables(self):
        manifest, analysis, _, _ = FINAL.build_final_needs_package(
            records(),
            ranking_result=ranking(),
            adversarial_qa_result=qa(),
            source_register=source_register(),
            evidence_mode=FINAL.TEST_MODE,
        )
        self.assertFalse(analysis["respondent_level_records_in_public_artifacts"])
        tables = analysis["sample"]["public_disclosure_controlled_tables"]
        for table in tables.values():
            for cell in table["cells"]:
                if cell["status"].startswith("SUPPRESSED"):
                    self.assertIsNone(cell["n"])
        self.assertEqual(manifest["secondary_evidence_numeric_points"], 0)
        self.assertEqual(manifest["project_activity_numeric_points"], 0)


if __name__ == "__main__":
    unittest.main()
