from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import adversarial_qa as QA
import need_ranking_engine as ENGINE
import nf06_preingest as NF06
import response_integrity_control as INTEGRITY
from research_storage import canonical_json_bytes

ROOT = Path(__file__).resolve().parent
TEST_TWIN_FIXTURES_NON_EVIDENCE = True


def approved_plan() -> dict:
    plan = json.loads((ROOT / "NEED_ANALYSIS_PLAN_DRAFT.json").read_text(encoding="utf-8"))
    plan["status"] = "APPROVED_FOR_PROD"
    plan["approval"] = {
        "approved": True,
        "approved_for_prod": True,
        "approved_at": "2026-08-19T11:00:00+00:00",
        "approver_reference": "TEST-TWIN-ONLY-NON-EVIDENCE",
    }
    return plan


def approved_frame() -> dict:
    frame = json.loads((ROOT / "COLLECTION_FRAME_DRAFT.json").read_text(encoding="utf-8"))
    frame["frame_status"] = "APPROVED_FOR_PROD"
    frame["collection_enabled"] = False
    frame["approval"]["approved"] = True
    frame["approval"]["approved_for_prod"] = True
    frame["approval"]["controller_approval_reference"] = "TEST-TWIN-ONLY-NON-EVIDENCE"
    return frame


def _adult_answers(*, h1: int = 5, h2: int = 4, h3: int = 3, h4: int = 2, h5: int = 1) -> dict:
    return {
        "Q10": {
            "utilizare_digitala_functionala": h5,
            "utilizarea_instrumentelor_AI": h1,
            "verificarea_rezultatelor_AI": h2,
            "protectia_datelor_confidentialitate": h3,
            "integrarea_AI_in_flux_de_lucru": h4,
        }
    }


def _employer_answers(*, h1: int = 5, h2: int = 4, h3: int = 3, h4: int = 2, h5: int = 1) -> dict:
    return {
        "E03": {
            "formularea_cerintelor": h1,
            "verificarea_calitatii": h2,
            "protectia_datelor": h3,
            "limitele_si_riscurile_AI": h3,
            "integrarea_in_procese": h4,
            "definirea_fluxului_asistat_AI": h4,
            "competente_digitale_generale": h5,
        }
    }


def prod_shaped_records(*, per_region_population: int = 5, dominant_pattern: bool = False) -> list[dict]:
    records: list[dict] = []
    sequence = 0
    for region in ENGINE.TARGET_REGIONS:
        for form_id in (ENGINE.ADULT_FORM, ENGINE.EMPLOYER_FORM):
            for local_index in range(per_region_population):
                sequence += 1
                if dominant_pattern:
                    dominant_count = int(per_region_population * 0.75)
                    is_dominant = local_index < dominant_count
                    channel = "CH-DOMINANT01" if is_dominant else "CH-ALTERNATE01"
                    if is_dominant:
                        ratings = dict(h1=5, h2=2, h3=3, h4=2, h5=1)
                    else:
                        ratings = dict(h1=1, h2=5, h3=3, h4=2, h5=1)
                else:
                    channel = "CH-UNITA0001" if local_index % 2 == 0 else "CH-UNITB0001"
                    ratings = dict(h1=5, h2=4, h3=3, h4=2, h5=1)

                if form_id == ENGINE.ADULT_FORM:
                    profile = {
                        "region": region,
                        "status": "persoană ocupată potențial eligibilă",
                        "age_band": "40-49",
                        "occupational_family": "administrativ/back-office",
                    }
                    answers = _adult_answers(**ratings)
                    prefix = "adult"
                else:
                    profile = {
                        "region": region,
                        "sector_aggregated": "servicii profesionale/tehnice",
                        "size_band": "10-49",
                        "respondent_role": "management",
                    }
                    answers = _employer_answers(**ratings)
                    prefix = "employer"

                records.append(
                    {
                        "research_id": "AI4WORK-STEP-NF-RUN-001",
                        "form_id": form_id,
                        "response_id": hashlib.sha256(f"{prefix}-{region}-{sequence}".encode()).hexdigest(),
                        "received_at": "2026-08-23T12:00:00+00:00",
                        "recruitment_channel_id": channel,
                        "profile": profile,
                        "answers": answers,
                        "synthetic": False,
                    }
                )
    return records


def gate_result(records: list[dict], plan: dict, frame: dict) -> dict:
    return {
        "schema_version": "eucons.ai4work_needs_synthesis_gate.v0.5",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "source_evidence_class": "PROD_REAL_EVIDENCE",
        "ready_for_needs_synthesis": True,
        "source_export_sha256": hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest(),
        "collection_frame_sha256": hashlib.sha256(canonical_json_bytes(frame)).hexdigest(),
        "method_frame_sha256": "2" * 64,
        "need_analysis_plan_sha256": hashlib.sha256(canonical_json_bytes(plan)).hexdigest(),
        "representativeness_claim_allowed": False,
        "weighting_allowed": False,
    }


def ranking_result(records: list[dict], plan: dict, frame: dict) -> dict:
    return ENGINE.compute_core_need_ranking(
        records,
        synthesis_gate_result=gate_result(records, plan, frame),
        need_analysis_plan=plan,
    )


def integrity_result(records: list[dict]) -> dict:
    source_sha = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    return INTEGRITY.assert_response_integrity_control(
        records,
        source_export_sha256=source_sha,
    )


class AdversarialQATests(unittest.TestCase):
    def test_stable_balanced_test_twin_exercises_prod_mechanics_without_becoming_evidence(self):
        self.assertTrue(TEST_TWIN_FIXTURES_NON_EVIDENCE)
        records = prod_shaped_records(per_region_population=5)
        plan = approved_plan()
        frame = approved_frame()
        result = QA.run_adversarial_qa(
            records,
            ranking_result=ranking_result(records, plan, frame),
            need_analysis_plan=plan,
            collection_frame=frame,
            response_integrity_result=integrity_result(records),
        )
        self.assertEqual(result["schema_version"], "eucons.ai4work_adversarial_qa.v0.1")
        self.assertEqual(result["source_evidence_class"], "PROD_REAL_EVIDENCE")
        self.assertEqual(result["evidence_class"], "CONTROL_ARTIFACT_NOT_EVIDENCE")
        self.assertEqual(result["overall_stability_label"], "STABLE")
        self.assertTrue(result["qa_completed"])
        self.assertTrue(result["needs_analysis_may_proceed"])
        self.assertFalse(result["collection_must_continue"])
        self.assertFalse(result["dominant_channel_triggered"])
        self.assertTrue(result["repeated_signature_triggered"])
        self.assertFalse(result["sparse_profile_triggered"])
        self.assertGreater(len(result["zero_profile_cell_caveats"]), 0)
        self.assertFalse(result["automatic_record_exclusion_applied"])
        self.assertFalse(result["identity_or_device_linkage_used"])
        self.assertFalse(result["respondent_weighting_applied"])
        self.assertEqual(result["secondary_evidence_numeric_points"], 0)
        self.assertEqual(result["project_activity_numeric_points"], 0)
        self.assertFalse(result["test_twin_evidence_eligible"])
        self.assertFalse(result["public_release_authorized"])

    def test_dominant_channel_that_changes_top_rank_forces_collection_to_continue(self):
        records = prod_shaped_records(per_region_population=8, dominant_pattern=True)
        plan = approved_plan()
        frame = approved_frame()
        result = QA.run_adversarial_qa(
            records,
            ranking_result=ranking_result(records, plan, frame),
            need_analysis_plan=plan,
            collection_frame=frame,
            response_integrity_result=integrity_result(records),
        )
        self.assertTrue(result["dominant_channel_triggered"])
        self.assertTrue(result["collection_must_continue"])
        self.assertFalse(result["needs_analysis_may_proceed"])
        labels = {
            view["comparison"]["stability_label"]
            for view in result["dominant_channel_sensitivity_views"]
        }
        self.assertIn("UNSTABLE", labels)
        self.assertFalse(result["single_definitive_rank_allowed"])

    def test_synthetic_record_is_rejected_before_any_prod_qa_claim(self):
        records = prod_shaped_records(per_region_population=5)
        plan = approved_plan()
        frame = approved_frame()
        rank = ranking_result(records, plan, frame)
        integrity = integrity_result(records)
        records[0]["synthetic"] = True
        with self.assertRaisesRegex(QA.AdversarialQAError, "NON-EVIDENCE"):
            QA.run_adversarial_qa(
                records,
                ranking_result=rank,
                need_analysis_plan=plan,
                collection_frame=frame,
                response_integrity_result=integrity,
            )

    def test_source_export_drift_is_rejected(self):
        records = prod_shaped_records(per_region_population=5)
        plan = approved_plan()
        frame = approved_frame()
        rank = ranking_result(records, plan, frame)
        integrity = integrity_result(records)
        records[0]["answers"]["Q10"]["utilizarea_instrumentelor_AI"] = 1
        with self.assertRaisesRegex(QA.AdversarialQAError, "source export"):
            QA.run_adversarial_qa(
                records,
                ranking_result=rank,
                need_analysis_plan=plan,
                collection_frame=frame,
                response_integrity_result=integrity,
            )

    def test_tampered_response_integrity_diagnostic_is_rejected(self):
        records = prod_shaped_records(per_region_population=5)
        plan = approved_plan()
        frame = approved_frame()
        integrity = integrity_result(records)
        integrity["repeated_signature_cluster_count"] += 1
        with self.assertRaisesRegex(QA.AdversarialQAError, "does not reconcile"):
            QA.run_adversarial_qa(
                records,
                ranking_result=ranking_result(records, plan, frame),
                need_analysis_plan=plan,
                collection_frame=frame,
                response_integrity_result=integrity,
            )

    def test_draft_frame_cannot_drive_prod_adversarial_qa(self):
        records = prod_shaped_records(per_region_population=5)
        plan = approved_plan()
        approved = approved_frame()
        rank = ranking_result(records, plan, approved)
        draft = json.loads((ROOT / "COLLECTION_FRAME_DRAFT.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(QA.AdversarialQAError, "APPROVED_FOR_PROD"):
            QA.run_adversarial_qa(
                records,
                ranking_result=rank,
                need_analysis_plan=plan,
                collection_frame=draft,
                response_integrity_result=integrity_result(records),
            )


if __name__ == "__main__":
    unittest.main()
