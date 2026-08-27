from __future__ import annotations

import copy
import hashlib
import unittest

import nf06_preingest as NF06
import runtime as RUNTIME
from test_runtime import adult_payload, employer_payload


def normalized_records(*, synthetic: bool = False) -> list[dict]:
    adult = RUNTIME.validate_submission(adult_payload())
    employer = RUNTIME.validate_submission(employer_payload())
    adult["response_id"] = "resp-adult-001"
    adult["received_at"] = "2026-08-28T09:00:00+00:00"
    employer["response_id"] = "resp-employer-001"
    employer["received_at"] = "2026-08-28T10:00:00+00:00"
    adult["synthetic"] = synthetic
    employer["synthetic"] = synthetic
    return [adult, employer]


def collection_frame(records: list[dict], *, prod: bool) -> tuple[dict, bytes]:
    source_bytes = NF06.canonical_export_bytes(records)
    frame = {
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "collection_frame_id": "AI4WORK-CF-PROD-001" if prod else "AI4WORK-CF-TEST-001",
        "frame_status": "APPROVED_FOR_PROD" if prod else "TEST_TWIN_ONLY",
        "evidence_class": "PROD_REAL_EVIDENCE" if prod else "TEST_TWIN_NON_EVIDENCE",
        "instrument_versions": {
            "AI4WORK_ADULTS_V1": 1,
            "AI4WORK_EMPLOYERS_V1": 1,
        },
        "collection_started_at": "2026-08-28T08:00:00+00:00",
        "collection_closed_at": "2026-08-28T18:00:00+00:00",
        "collection_channels": ["eucons.ro first-party research forms"],
        "source_system": "eucons.ro",
        "source_export_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "direct_identifiers_collected": False,
        "crm_linkage": "FORBIDDEN",
        "commercial_tracking": "FORBIDDEN",
        "storage_class": "RESEARCH_ONLY_SEPARATE_FROM_CRM",
    }
    if prod:
        frame.update(
            {
                "privacy_notice_version": "AI4WORK-PRIVACY-v1",
                "controller_determination_reference": "CTRL-DETERMINATION-001",
                "controller_approval_reference": "CTRL-APPROVAL-001",
                "processor_binding_reference": "PROCESSOR-BINDING-001",
                "server_log_profile_reference": "SERVER-LOG-REVIEW-001",
                "retention_schedule_reference": "RETENTION-APPROVAL-001",
                "production_store_binding_reference": "RESEARCH-STORE-BINDING-001",
            }
        )
    return frame, source_bytes


class NF06PreingestTests(unittest.TestCase):
    def test_valid_prod_two_form_batch_is_handoff_eligible_without_answer_leakage(self):
        records = normalized_records()
        frame, source_bytes = collection_frame(records, prod=True)
        manifest = NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=True)
        self.assertEqual(manifest["evidence_class"], "PROD_REAL_EVIDENCE")
        self.assertTrue(manifest["prod_promotion_eligible"])
        self.assertFalse(manifest["non_evidence"])
        self.assertEqual(manifest["record_count"], 2)
        self.assertEqual(manifest["form_counts"]["AI4WORK_ADULTS_V1"], 1)
        self.assertEqual(manifest["form_counts"]["AI4WORK_EMPLOYERS_V1"], 1)
        rendered = NF06.manifest_json_bytes(manifest).decode("utf-8")
        self.assertNotIn("redactare și documente", rendered)
        self.assertNotIn("compliance/verificare documente", rendered)

    def test_prod_rejects_synthetic_record(self):
        records = normalized_records()
        records[0]["synthetic"] = True
        frame, source_bytes = collection_frame(records, prod=True)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=True)

    def test_test_twin_requires_synthetic_and_is_permanently_non_evidence(self):
        records = normalized_records(synthetic=True)
        frame, source_bytes = collection_frame(records, prod=False)
        manifest = NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=False)
        self.assertEqual(manifest["evidence_class"], "TEST_TWIN_NON_EVIDENCE")
        self.assertTrue(manifest["non_evidence"])
        self.assertFalse(manifest["prod_promotion_eligible"])

        real_record_in_test_twin = normalized_records(synthetic=True)
        real_record_in_test_twin[1]["synthetic"] = False
        bad_frame, bad_bytes = collection_frame(real_record_in_test_twin, prod=False)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(real_record_in_test_twin, collection_frame=bad_frame, source_bytes=bad_bytes, prod=False)

    def test_source_bytes_or_sha_mismatch_fails_closed(self):
        records = normalized_records()
        frame, source_bytes = collection_frame(records, prod=True)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes + b" ", prod=True)

        frame2, source_bytes2 = collection_frame(records, prod=True)
        frame2["source_export_sha256"] = "0" * 64
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(records, collection_frame=frame2, source_bytes=source_bytes2, prod=True)

    def test_prod_requires_controller_determination_approval_provider_logging_retention_and_store_refs(self):
        records = normalized_records()
        required = [
            "privacy_notice_version",
            "controller_determination_reference",
            "controller_approval_reference",
            "processor_binding_reference",
            "server_log_profile_reference",
            "retention_schedule_reference",
            "production_store_binding_reference",
        ]
        for field in required:
            with self.subTest(field=field):
                frame, source_bytes = collection_frame(records, prod=True)
                del frame[field]
                with self.assertRaises(NF06.NF06PreingestError):
                    NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=True)

    def test_duplicate_response_id_is_rejected(self):
        records = normalized_records()
        records[1]["response_id"] = records[0]["response_id"]
        frame, source_bytes = collection_frame(records, prod=True)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=True)

    def test_received_at_outside_collection_window_is_rejected(self):
        records = normalized_records()
        records[0]["received_at"] = "2026-08-29T09:00:00+00:00"
        frame, source_bytes = collection_frame(records, prod=True)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=True)

    def test_noncanonical_identifier_like_value_in_controlled_field_is_rejected_again(self):
        records = normalized_records()
        records[0]["profile"]["occupational_family"] = "test@example.org"
        frame, source_bytes = collection_frame(records, prod=True)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=True)

    def test_tampered_frozen_form_value_is_rejected(self):
        records = normalized_records()
        records[1]["answers"]["E07"] = "foarte mult"
        frame, source_bytes = collection_frame(records, prod=True)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest(records, collection_frame=frame, source_bytes=source_bytes, prod=True)

    def test_empty_batch_is_rejected(self):
        frame, source_bytes = collection_frame([], prod=True)
        with self.assertRaises(NF06.NF06PreingestError):
            NF06.build_preingest_manifest([], collection_frame=frame, source_bytes=source_bytes, prod=True)


if __name__ == "__main__":
    unittest.main()
