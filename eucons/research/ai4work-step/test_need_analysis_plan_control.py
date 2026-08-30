from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import need_analysis_plan_control as PLAN
from research_storage import canonical_json_bytes
from test_primary_evidence_readiness import approved_method_frame, channel_register
from test_profile_coverage_control import approved_method_lock, frozen_forms, full_profile_records
from test_real_batch_synthesis_gate import bound_collection_frame, bound_manifest

ROOT = Path(__file__).resolve().parent
UNIT_TEST_FIXTURE_NON_EVIDENCE = True


def approved_plan() -> dict:
    plan = json.loads((ROOT / "NEED_ANALYSIS_PLAN_DRAFT.json").read_text(encoding="utf-8"))
    plan["status"] = "APPROVED_FOR_PROD"
    plan["approval"] = {
        "approved": True,
        "approved_for_prod": True,
        "approved_at": "2026-08-19T11:00:00+00:00",
        "approver_reference": "UNIT-TEST-PLAN-APPROVAL-NON-EVIDENCE",
    }
    return plan


def approved_plan_lock(plan: dict, frame: dict) -> dict:
    return {
        "schema_version": "eucons.ai4work_need_analysis_plan_lock.v0.1",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "status": "APPROVED_BEFORE_COLLECTION",
        "evidence_class": "METHOD_CONTROL_NOT_EVIDENCE",
        "collection_frame_id": frame["collection_frame_id"],
        "need_analysis_plan_sha256": hashlib.sha256(canonical_json_bytes(plan)).hexdigest(),
        "approved_at": "2026-08-19T11:30:00+00:00",
        "approver_reference": "UNIT-TEST-PLAN-LOCK-NON-EVIDENCE",
    }


class NeedAnalysisPlanControlTests(unittest.TestCase):
    def test_plan_maps_only_frozen_questions_and_is_locked_before_collection(self):
        records = full_profile_records()
        register = channel_register()
        frame = bound_collection_frame(register, records)
        plan = approved_plan()
        result = PLAN.assert_need_analysis_plan_locked_before_collection(
            plan,
            plan_lock=approved_plan_lock(plan, frame),
            collection_frame=frame,
            forms_definition=frozen_forms(),
        )
        self.assertTrue(result["need_analysis_plan_locked_before_collection"])
        self.assertEqual(result["core_skill_rank_dimensions"], ["H1", "H2", "H3", "H4", "H5"])
        self.assertEqual(result["design_dimensions"], ["H6", "H7"])
        self.assertFalse(result["secondary_evidence_can_change_numeric_order"])
        self.assertFalse(result["respondent_weighting_allowed"])
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertFalse(result["test_twin_allowed"])

    def test_plan_rejects_post_lock_question_mapping_drift(self):
        records = full_profile_records()
        register = channel_register()
        frame = bound_collection_frame(register, records)
        plan = approved_plan()
        lock = approved_plan_lock(plan, frame)
        plan["core_dimensions"]["H1"]["adult_direct"][0]["row_id"] = "verificarea_rezultatelor_AI"
        with self.assertRaisesRegex(PLAN.NeedAnalysisPlanControlError, "bytes do not match"):
            PLAN.assert_need_analysis_plan_locked_before_collection(
                plan,
                plan_lock=lock,
                collection_frame=frame,
                forms_definition=frozen_forms(),
            )

    def test_plan_rejects_reference_absent_from_frozen_instrument(self):
        records = full_profile_records()
        register = channel_register()
        frame = bound_collection_frame(register, records)
        plan = approved_plan()
        plan["core_dimensions"]["H2"]["supporting_adult"].append({"question_id": "Q99"})
        lock = approved_plan_lock(plan, frame)
        with self.assertRaisesRegex(PLAN.NeedAnalysisPlanControlError, "absent from the frozen instrument"):
            PLAN.assert_need_analysis_plan_locked_before_collection(
                plan,
                plan_lock=lock,
                collection_frame=frame,
                forms_definition=frozen_forms(),
            )

    def test_plan_rejects_post_start_approval(self):
        records = full_profile_records()
        register = channel_register()
        frame = bound_collection_frame(register, records)
        plan = approved_plan()
        plan["approval"]["approved_at"] = "2026-08-21T00:00:00+00:00"
        lock = approved_plan_lock(plan, frame)
        with self.assertRaisesRegex(PLAN.NeedAnalysisPlanControlError, "not approved and locked before collection started"):
            PLAN.assert_need_analysis_plan_locked_before_collection(
                plan,
                plan_lock=lock,
                collection_frame=frame,
                forms_definition=frozen_forms(),
            )

    def test_plan_keeps_h6_h7_outside_core_skill_rank(self):
        records = full_profile_records()
        register = channel_register()
        frame = bound_collection_frame(register, records)
        plan = approved_plan()
        plan["design_dimensions"]["H6"]["ranking_scope"] = "mix into H1-H5"
        lock = approved_plan_lock(plan, frame)
        with self.assertRaisesRegex(PLAN.NeedAnalysisPlanControlError, "H6 must remain outside"):
            PLAN.assert_need_analysis_plan_locked_before_collection(
                plan,
                plan_lock=lock,
                collection_frame=frame,
                forms_definition=frozen_forms(),
            )


if __name__ == "__main__":
    unittest.main()
