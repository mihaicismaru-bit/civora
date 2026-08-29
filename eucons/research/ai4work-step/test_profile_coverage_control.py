from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import needs_synthesis_gate as NEEDS
import profile_coverage_control as COVERAGE
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
        self.assertEqual(
            result["validated_dimensions"]["adults"],
            ["region", "status", "age_band", "occupational_family"],
        )
        self.assertEqual(
            result["validated_dimensions"]["employers"],
            ["region", "sector_aggregated", "size_band", "respondent_role"],
        )
        self.assertTrue(result["zero_cell_scopes"])

    def test_missing_declared_profile_dimension_is_rejected(self):
        records = full_profile_records()
        del records[0]["profile"]["age_band"]
        with self.assertRaisesRegex(COVERAGE.ProfileCoverageControlError, "missing frozen coverage dimension"):
            COVERAGE.assert_profile_coverage_control(
                records,
                method_frame=approved_method_frame(),
                forms_definition=frozen_forms(),
            )

    def test_value_outside_frozen_profile_options_is_rejected(self):
        records = full_profile_records()
        records[0]["profile"]["occupational_family"] = "invented-test-category"
        with self.assertRaisesRegex(COVERAGE.ProfileCoverageControlError, "outside frozen options"):
            COVERAGE.assert_profile_coverage_control(
                records,
                method_frame=approved_method_frame(),
                forms_definition=frozen_forms(),
            )

    def test_method_frame_cannot_silently_add_unknown_coverage_dimension(self):
        frame = approved_method_frame()
        frame["sampling_design"]["coverage_dimensions"]["adults"].append("unreviewed_dimension")
        with self.assertRaisesRegex(COVERAGE.ProfileCoverageControlError, "absent from frozen instrument"):
            COVERAGE.assert_profile_coverage_control(
                full_profile_records(),
                method_frame=frame,
                forms_definition=frozen_forms(),
            )

    def test_canonical_needs_synthesis_wrapper_requires_profile_coverage_control(self):
        register = channel_register()
        records = full_profile_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        result = NEEDS.assert_real_batch_ready_for_needs_synthesis(
            records,
            manifest=manifest,
            collection_frame=frame,
            method_frame=approved_method_frame(),
            channel_register=register,
            forms_definition=frozen_forms(),
        )
        self.assertTrue(result["ready_for_needs_synthesis"])
        self.assertEqual(result["schema_version"], "eucons.ai4work_needs_synthesis_gate.v0.1")
        self.assertEqual(
            result["profile_coverage_control_schema_version"],
            "eucons.ai4work_profile_coverage_control.v0.1",
        )
        self.assertTrue(result["profile_coverage_qa_required"])
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertFalse(result["public_release_authorized"])

    def test_canonical_wrapper_rejects_missing_profile_field_after_hashes_are_rebound(self):
        register = channel_register()
        records = full_profile_records()
        del records[0]["profile"]["age_band"]
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        with self.assertRaisesRegex(NEEDS.NeedsSynthesisGateError, "missing frozen coverage dimension"):
            NEEDS.assert_real_batch_ready_for_needs_synthesis(
                records,
                manifest=manifest,
                collection_frame=frame,
                method_frame=approved_method_frame(),
                channel_register=register,
                forms_definition=frozen_forms(),
            )


if __name__ == "__main__":
    unittest.main()
