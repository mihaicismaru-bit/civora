from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import needs_synthesis_gate as NEEDS
import profile_coverage_control as COVERAGE
from research_storage import canonical_json_bytes
from test_primary_evidence_readiness import ADULT_FORM, EMPLOYER_FORM, approved_method_frame, channel_register
from test_real_batch_synthesis_gate import bound_collection_frame, bound_manifest, real_records

ROOT = Path(__file__).resolve().parent
UNIT_TEST_FIXTURE_NON_EVIDENCE = True


def frozen_forms() -> dict:
    return json.loads((ROOT / "forms_definition.json").read_text(encoding="utf-8"))


def full_profile_records() -> list[dict]:
    """PROD-shaped unit-test fixtures only; never empirical evidence or exportable PROD data."""
    records = real_records()
    for record in records:
        if record["form_id"] == ADULT_FORM:
            record["profile"].update(
                {
                    "status": "persoană ocupată potențial eligibilă",
                    "age_band": "40-49",
                    "occupational_family": "administrativ/back-office",
                }
            )
        elif record["form_id"] == EMPLOYER_FORM:
            record["profile"].update(
                {
                    "sector_aggregated": "servicii profesionale/tehnice",
                    "size_band": "10-49",
                    "respondent_role": "management",
                }
            )
    return records


def approved_method_lock(method_frame: dict, collection_frame: dict) -> dict:
    return {
        "schema_version": "eucons.ai4work_method_frame_lock.v0.1",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "status": "APPROVED_BEFORE_COLLECTION",
        "evidence_class": "METHOD_CONTROL_NOT_EVIDENCE",
        "collection_frame_id": collection_frame["collection_frame_id"],
        "method_frame_sha256": hashlib.sha256(canonical_json_bytes(method_frame)).hexdigest(),
        "approved_at": "2026-08-19T12:00:00+00:00",
        "approver_reference": "UNIT-TEST-METHOD-LOCK-NON-EVIDENCE",
    }


def approved_need_analysis_plan() -> dict:
    plan = json.loads((ROOT / "NEED_ANALYSIS_PLAN_DRAFT.json").read_text(encoding="utf-8"))
    plan["status"] = "APPROVED_FOR_PROD"
    plan["approval"] = {
        "approved": True,
        "approved_for_prod": True,
        "approved_at": "2026-08-19T11:00:00+00:00",
        "approver_reference": "UNIT-TEST-PLAN-APPROVAL-NON-EVIDENCE",
    }
    return plan


def approved_need_analysis_plan_lock(plan: dict, collection_frame: dict) -> dict:
    return {
        "schema_version": "eucons.ai4work_need_analysis_plan_lock.v0.1",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "status": "APPROVED_BEFORE_COLLECTION",
        "evidence_class": "METHOD_CONTROL_NOT_EVIDENCE",
        "collection_frame_id": collection_frame["collection_frame_id"],
        "need_analysis_plan_sha256": hashlib.sha256(canonical_json_bytes(plan)).hexdigest(),
        "approved_at": "2026-08-19T11:30:00+00:00",
        "approver_reference": "UNIT-TEST-PLAN-LOCK-NON-EVIDENCE",
    }


def synthesis_kwargs(frame: dict, method_frame: dict) -> dict:
    plan = approved_need_analysis_plan()
    return {
        "method_frame_lock": approved_method_lock(method_frame, frame),
        "need_analysis_plan": plan,
        "need_analysis_plan_lock": approved_need_analysis_plan_lock(plan, frame),
    }


class ProfileCoverageControlTests(unittest.TestCase):
    def test_full_frozen_profile_dimensions_are_machine_validated_and_sparse_cells_are_surfaced(self):
        result = COVERAGE.assert_profile_coverage_control(
            full_profile_records(),
            method_frame=approved_method_frame(),
            forms_definition=frozen_forms(),
        )
        self.assertEqual(result["schema_version"], "eucons.ai4work_profile_coverage_control.v0.1")
        self.assertEqual(result["evidence_class"], "CONTROL_ARTIFACT_NOT_EVIDENCE")
        self.assertFalse(result["public_release_authorized"])
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertTrue(result["profile_coverage_qa_required"])
        self.assertEqual(result["validated_dimensions"]["adults"], ["region", "status", "age_band", "occupational_family"])
        self.assertEqual(result["validated_dimensions"]["employers"], ["region", "sector_aggregated", "size_band", "respondent_role"])
        self.assertTrue(result["zero_cell_scopes"])

    def test_missing_declared_profile_dimension_is_rejected(self):
        records = full_profile_records()
        del records[0]["profile"]["age_band"]
        with self.assertRaisesRegex(COVERAGE.ProfileCoverageControlError, "missing frozen coverage dimension"):
            COVERAGE.assert_profile_coverage_control(records, method_frame=approved_method_frame(), forms_definition=frozen_forms())

    def test_value_outside_frozen_profile_options_is_rejected(self):
        records = full_profile_records()
        records[0]["profile"]["occupational_family"] = "invented-test-category"
        with self.assertRaisesRegex(COVERAGE.ProfileCoverageControlError, "outside frozen options"):
            COVERAGE.assert_profile_coverage_control(records, method_frame=approved_method_frame(), forms_definition=frozen_forms())

    def test_method_frame_cannot_silently_add_unknown_coverage_dimension(self):
        frame = approved_method_frame()
        frame["sampling_design"]["coverage_dimensions"]["adults"].append("unreviewed_dimension")
        with self.assertRaisesRegex(COVERAGE.ProfileCoverageControlError, "absent from frozen instrument"):
            COVERAGE.assert_profile_coverage_control(full_profile_records(), method_frame=frame, forms_definition=frozen_forms())

    def test_canonical_needs_synthesis_wrapper_requires_profile_coverage_precollection_method_and_analysis_plan_locks_and_integrity(self):
        register = channel_register()
        records = full_profile_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        method_frame = approved_method_frame()
        result = NEEDS.assert_real_batch_ready_for_needs_synthesis(
            records,
            manifest=manifest,
            collection_frame=frame,
            method_frame=method_frame,
            channel_register=register,
            forms_definition=frozen_forms(),
            **synthesis_kwargs(frame, method_frame),
        )
        self.assertTrue(result["ready_for_needs_synthesis"])
        self.assertEqual(result["schema_version"], "eucons.ai4work_needs_synthesis_gate.v0.4")
        self.assertEqual(result["method_frame_lock_control_schema_version"], "eucons.ai4work_method_frame_lock_control.v0.1")
        self.assertEqual(result["need_analysis_plan_control_schema_version"], "eucons.ai4work_need_analysis_plan_control.v0.1")
        self.assertEqual(result["profile_coverage_control_schema_version"], "eucons.ai4work_profile_coverage_control.v0.1")
        self.assertEqual(result["response_integrity_control_schema_version"], "eucons.ai4work_response_integrity_control.v0.1")
        self.assertTrue(result["method_frame_locked_before_collection"])
        self.assertTrue(result["need_analysis_plan_locked_before_collection"])
        self.assertEqual(result["core_skill_rank_dimensions"], ["H1", "H2", "H3", "H4", "H5"])
        self.assertEqual(result["design_dimensions"], ["H6", "H7"])
        self.assertTrue(result["profile_coverage_qa_required"])
        self.assertTrue(result["response_integrity_qa_required"])
        self.assertFalse(result["automatic_duplicate_exclusion_authorized"])
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertFalse(result["public_release_authorized"])

    def test_canonical_wrapper_rejects_method_frame_drift_after_lock(self):
        register = channel_register()
        records = full_profile_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        method_frame = approved_method_frame()
        kwargs = synthesis_kwargs(frame, method_frame)
        method_frame["sampling_design"]["provisional_readiness_thresholds"]["adults_total_valid_min"] = 1
        with self.assertRaisesRegex(NEEDS.NeedsSynthesisGateError, "method_frame bytes do not match"):
            NEEDS.assert_real_batch_ready_for_needs_synthesis(records, manifest=manifest, collection_frame=frame, method_frame=method_frame, channel_register=register, forms_definition=frozen_forms(), **kwargs)

    def test_canonical_wrapper_rejects_need_analysis_plan_drift_after_lock(self):
        register = channel_register()
        records = full_profile_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        method_frame = approved_method_frame()
        plan = approved_need_analysis_plan()
        plan_lock = approved_need_analysis_plan_lock(plan, frame)
        plan["core_dimensions"]["H1"]["adult_direct"][0]["row_id"] = "verificarea_rezultatelor_AI"
        with self.assertRaisesRegex(NEEDS.NeedsSynthesisGateError, "bytes do not match"):
            NEEDS.assert_real_batch_ready_for_needs_synthesis(
                records, manifest=manifest, collection_frame=frame, method_frame=method_frame,
                method_frame_lock=approved_method_lock(method_frame, frame), need_analysis_plan=plan,
                need_analysis_plan_lock=plan_lock, channel_register=register, forms_definition=frozen_forms()
            )

    def test_canonical_wrapper_rejects_method_lock_approved_after_collection_started(self):
        register = channel_register()
        records = full_profile_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        method_frame = approved_method_frame()
        kwargs = synthesis_kwargs(frame, method_frame)
        kwargs["method_frame_lock"]["approved_at"] = "2026-08-21T00:00:00+00:00"
        with self.assertRaisesRegex(NEEDS.NeedsSynthesisGateError, "not locked before collection started"):
            NEEDS.assert_real_batch_ready_for_needs_synthesis(records, manifest=manifest, collection_frame=frame, method_frame=method_frame, channel_register=register, forms_definition=frozen_forms(), **kwargs)

    def test_canonical_wrapper_rejects_missing_profile_field_after_hashes_are_rebound(self):
        register = channel_register()
        records = full_profile_records()
        del records[0]["profile"]["age_band"]
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        method_frame = approved_method_frame()
        with self.assertRaisesRegex(NEEDS.NeedsSynthesisGateError, "missing frozen coverage dimension"):
            NEEDS.assert_real_batch_ready_for_needs_synthesis(records, manifest=manifest, collection_frame=frame, method_frame=method_frame, channel_register=register, forms_definition=frozen_forms(), **synthesis_kwargs(frame, method_frame))


if __name__ == "__main__":
    unittest.main()
