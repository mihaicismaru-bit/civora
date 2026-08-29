from __future__ import annotations

import copy
import hashlib
import unittest

import canonical_export_integrity as EXPORT_INTEGRITY
import nf06_preingest as NF06
import response_integrity_control as INTEGRITY
from test_profile_coverage_control import full_profile_records

UNIT_TEST_FIXTURE_NON_EVIDENCE = True


def source_sha(records: list[dict]) -> str:
    return hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()


def persisted_bundle(record: dict) -> dict:
    normalized_sha = hashlib.sha256(NF06.canonical_export_bytes([record])).hexdigest()
    raw_sha = hashlib.sha256(b"TEST_TWIN_RAW_REQUEST_NON_EVIDENCE").hexdigest()
    return {
        "filename_response_id": record["response_id"],
        "wrapper": {
            "schema_version": 1,
            "received_at": record["received_at"],
            "raw_sha256": raw_sha,
            "normalized_sha256": normalized_sha,
            "record": copy.deepcopy(record),
        },
        "receipt": {
            "schema_version": 1,
            "response_id": record["response_id"],
            "form_id": record["form_id"],
            "accepted_at": record["received_at"],
            "body_sha256": EXPORT_INTEGRITY.analytical_body_sha256(record),
            "normalized_sha256": normalized_sha,
            "raw_sha256": raw_sha,
            "pii_in_receipt": False,
        },
    }


class ResponseIntegrityControlTests(unittest.TestCase):
    def test_exact_repeated_analytical_signatures_are_surfaced_without_exclusion_or_identity_inference(self):
        records = full_profile_records()
        result = INTEGRITY.assert_response_integrity_control(
            records,
            source_export_sha256=source_sha(records),
        )
        self.assertEqual(result["schema_version"], "eucons.ai4work_response_integrity_control.v0.1")
        self.assertTrue(result["response_integrity_qa_required"])
        self.assertGreater(result["repeated_signature_cluster_count"], 0)
        self.assertGreater(result["repeated_signature_record_count"], 0)
        self.assertFalse(result["same_person_multiple_submission_determined"])
        self.assertFalse(result["automatic_exclusion_authorized"])
        self.assertFalse(result["identity_or_device_linkage_used"])
        self.assertFalse(result["representativeness_claim_allowed"])

    def test_unique_analytical_signatures_do_not_create_duplicate_qa_signal(self):
        records = copy.deepcopy(full_profile_records())
        for index, record in enumerate(records):
            record["answers"] = {"UNIT_TEST_NON_EVIDENCE_SEQUENCE": index}
        result = INTEGRITY.assert_response_integrity_control(
            records,
            source_export_sha256=source_sha(records),
        )
        self.assertFalse(result["response_integrity_qa_required"])
        self.assertEqual(result["repeated_signature_cluster_count"], 0)
        self.assertEqual(result["repeated_signature_record_count"], 0)
        self.assertEqual(result["unique_analytical_signature_count"], len(records))

    def test_integrity_diagnostics_are_bound_to_exact_source_export(self):
        records = full_profile_records()
        with self.assertRaisesRegex(
            INTEGRITY.ResponseIntegrityControlError,
            "source export SHA-256 mismatch",
        ):
            INTEGRITY.assert_response_integrity_control(
                records,
                source_export_sha256="0" * 64,
            )

    def test_test_twin_record_is_rejected_by_prod_integrity_control(self):
        records = full_profile_records()
        records[0]["synthetic"] = True
        with self.assertRaisesRegex(
            INTEGRITY.ResponseIntegrityControlError,
            "only synthetic=false PROD records",
        ):
            INTEGRITY.assert_response_integrity_control(
                records,
                source_export_sha256=source_sha(records),
            )

    def test_canonical_export_revalidates_persisted_wrappers_and_receipts_before_nf06(self):
        records = full_profile_records()
        bundles = [persisted_bundle(record) for record in records]
        exported = EXPORT_INTEGRITY.canonical_export_bytes_from_persisted_bundles(bundles)
        self.assertEqual(exported, NF06.canonical_export_bytes(records))

    def test_canonical_export_rejects_record_tampering_after_persistence_hashes_were_committed(self):
        record = full_profile_records()[0]
        bundle = persisted_bundle(record)
        bundle["wrapper"]["record"]["answers"] = {"UNIT_TEST_NON_EVIDENCE_TAMPER": True}
        with self.assertRaisesRegex(
            EXPORT_INTEGRITY.CanonicalExportIntegrityError,
            "stored record normalized SHA-256 mismatch",
        ):
            EXPORT_INTEGRITY.validate_persisted_bundle(bundle)

    def test_canonical_export_rejects_receipt_or_filename_binding_drift(self):
        record = full_profile_records()[0]
        receipt_drift = persisted_bundle(record)
        receipt_drift["receipt"]["body_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            EXPORT_INTEGRITY.CanonicalExportIntegrityError,
            "receipt analytical body SHA-256 mismatch",
        ):
            EXPORT_INTEGRITY.validate_persisted_bundle(receipt_drift)

        filename_drift = persisted_bundle(record)
        filename_drift["filename_response_id"] = "3" * 64
        with self.assertRaisesRegex(
            EXPORT_INTEGRITY.CanonicalExportIntegrityError,
            "response filename does not match record response_id",
        ):
            EXPORT_INTEGRITY.validate_persisted_bundle(filename_drift)

    def test_canonical_export_gate_rejects_synthetic_record_from_prod_persisted_path(self):
        record = full_profile_records()[0]
        record["synthetic"] = True
        bundle = persisted_bundle(record)
        with self.assertRaisesRegex(
            EXPORT_INTEGRITY.CanonicalExportIntegrityError,
            "PROD storage rejects synthetic records",
        ):
            EXPORT_INTEGRITY.validate_persisted_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
