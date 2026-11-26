from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from pathlib import Path

import precollection_analysis_plan_gate as GATE
from research_storage import canonical_json_bytes

ROOT = Path(__file__).resolve().parent
UNIT_TEST_FIXTURE_NON_EVIDENCE = True
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_current():
    return (
        json.loads((ROOT / "form_contract.json").read_text(encoding="utf-8")),
        json.loads((ROOT / "PROD_ACTIVATION_MANIFEST_DRAFT.json").read_text(encoding="utf-8")),
        json.loads((ROOT / "COLLECTION_FRAME_DRAFT.json").read_text(encoding="utf-8")),
        json.loads((ROOT / "NEED_ANALYSIS_PLAN_DRAFT.json").read_text(encoding="utf-8")),
        json.loads((ROOT / "PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json").read_text(encoding="utf-8")),
    )


def approved_fixture():
    contract, manifest, frame, plan, lock = [copy.deepcopy(item) for item in load_current()]
    contract["production_enabled"] = True
    manifest["state"] = "APPROVED_FOR_PROD"
    manifest["approved_for_prod"] = True
    manifest["collection_enabled"] = True
    manifest["real_collection_authorized"] = True
    manifest["approval_timestamp"] = "2026-08-20T12:00:00+00:00"
    frame["frame_status"] = "APPROVED_FOR_PROD"
    frame["collection_enabled"] = True

    plan["status"] = "APPROVED_FOR_PROD"
    plan["approval"] = {
        "approved": True,
        "approved_for_prod": True,
        "approved_at": "2026-08-20T10:00:00+00:00",
        "approver_reference": "UNIT-TEST-PLAN-APPROVAL-NON-EVIDENCE",
    }
    lock["state"] = "LOCKED_BEFORE_PROD_ACTIVATION"
    lock["need_analysis_plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    lock["collection_frame_sha256"] = hashlib.sha256(canonical_json_bytes(frame)).hexdigest()
    lock["approved_at"] = "2026-08-20T11:00:00+00:00"
    lock["approver_reference"] = "UNIT-TEST-DUAL-METHOD-LOCK-NON-EVIDENCE"
    return contract, manifest, frame, plan, lock


class PrecollectionAnalysisPlanGateTests(unittest.TestCase):
    def test_current_repository_method_is_approved_dual_locked_and_collection_stays_off(self):
        contract, manifest, frame, plan, lock = load_current()
        self.assertTrue(GATE._activation_requested(contract, manifest, frame))
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertEqual(errors, [])
        self.assertFalse(contract["production_enabled"])
        self.assertFalse(manifest["approved_for_prod"])
        self.assertFalse(manifest["collection_enabled"])
        self.assertFalse(manifest["real_collection_authorized"])
        self.assertEqual(plan["status"], "APPROVED_FOR_PROD")
        self.assertTrue(plan["approval"]["approved_for_prod"])
        self.assertEqual(frame["frame_status"], "APPROVED_FOR_PROD")
        self.assertTrue(frame["approval"]["approved_for_prod"])
        self.assertFalse(frame["collection_enabled"])
        self.assertFalse(frame["nf06_handoff"]["eligible_now"])
        self.assertEqual(lock["schema_version"], "eucons.ai4work_precollection_analysis_plan_lock.v0.2")
        self.assertEqual(lock["state"], "LOCKED_BEFORE_PROD_ACTIVATION")
        self.assertEqual(lock["collection_frame_reference"], "COLLECTION_FRAME_DRAFT.json")
        self.assertRegex(lock["need_analysis_plan_sha256"], SHA256_RE)
        self.assertRegex(lock["collection_frame_sha256"], SHA256_RE)
        self.assertEqual(lock["post_hoc_threshold_exception"], "FORBIDDEN")
        GATE.assert_repository_fail_closed_or_prelocked()

    def test_production_claim_with_broken_dual_method_lock_is_rejected(self):
        contract, manifest, frame, plan, lock = [copy.deepcopy(item) for item in load_current()]
        contract["production_enabled"] = True
        lock["state"] = "OPEN_NOT_LOCKED"
        lock["need_analysis_plan_sha256"] = None
        lock["collection_frame_sha256"] = None
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertIn("plan_lock_not_approved", errors)
        self.assertIn("plan_lock_sha256_missing_or_invalid", errors)
        self.assertIn("collection_frame_lock_sha256_missing_or_invalid", errors)

    def test_exact_dual_lock_allows_only_frozen_precollection_method(self):
        contract, manifest, frame, plan, lock = approved_fixture()
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertEqual(errors, [])
        self.assertFalse(plan["synthetic_records_allowed"])
        self.assertEqual(plan["test_twin_evidence_class"], "TEST_TWIN_NON_EVIDENCE")
        self.assertFalse(plan["project_activity_as_need_evidence"])
        self.assertFalse(plan["core_skill_ranking"]["secondary_evidence_can_change_numeric_order"])
        self.assertFalse(frame["sampling_design"]["synthetic_records_allowed_in_prod"])
        self.assertFalse(frame["sampling_design"]["project_activity_as_need_evidence"])
        self.assertEqual(frame["sampling_design"]["provisional_readiness_thresholds"]["status"], "METHOD_RULE_NOT_EVIDENCE")
        self.assertEqual(lock["post_hoc_threshold_exception"], "FORBIDDEN")

    def test_post_lock_analysis_plan_drift_is_rejected(self):
        contract, manifest, frame, plan, lock = approved_fixture()
        plan["core_skill_ranking"]["cross_population_combination"] = "post_hoc_changed_rule"
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertIn("plan_lock_sha256_mismatch", errors)

    def test_post_lock_collection_frame_threshold_drift_is_rejected(self):
        contract, manifest, frame, plan, lock = approved_fixture()
        frame["sampling_design"]["provisional_readiness_thresholds"]["adults_total_valid_min"] = 60
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertIn("collection_frame_lock_sha256_mismatch", errors)

    def test_post_hoc_threshold_exception_cannot_be_enabled(self):
        contract, manifest, frame, plan, lock = approved_fixture()
        lock["post_hoc_threshold_exception"] = "ALLOWED_AFTER_REVIEW"
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertIn("post_hoc_threshold_exception_not_forbidden", errors)

    def test_lock_created_after_prod_activation_approval_is_rejected(self):
        contract, manifest, frame, plan, lock = approved_fixture()
        lock["approved_at"] = "2026-08-20T13:00:00+00:00"
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertIn("plan_locked_after_prod_activation_approval", errors)

    def test_secondary_evidence_cannot_be_enabled_as_numeric_rank_input(self):
        contract, manifest, frame, plan, lock = approved_fixture()
        plan["core_skill_ranking"]["secondary_evidence_can_change_numeric_order"] = True
        lock["need_analysis_plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
        errors = GATE.precollection_errors(
            contract=contract,
            manifest=manifest,
            collection_frame=frame,
            need_analysis_plan=plan,
            plan_lock=lock,
        )
        self.assertIn("secondary_evidence_rank_influence_not_frozen_false", errors)


if __name__ == "__main__":
    unittest.main()
