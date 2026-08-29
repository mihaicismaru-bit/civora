from __future__ import annotations

import copy
import hashlib
import unittest

import canonical_export_integrity as EXPORT_INTEGRITY
import nf06_persisted_handoff as HANDOFF
from research_storage import canonical_json_bytes
from test_nf06_preingest import collection_frame, normalized_records


def persisted_bundle(record: dict) -> dict:
    raw_sha = hashlib.sha256(("raw:" + record["response_id"]).encode("utf-8")).hexdigest()
    normalized_sha = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
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


class NF06PersistedHandoffTests(unittest.TestCase):
    def test_valid_persisted_prod_bundles_build_exact_nf06_source_and_manifest(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in reversed(records)]
        frame, expected_source_bytes = collection_frame(records, prod=True)

        source_bytes, manifest = HANDOFF.build_prod_preingest_from_persisted_bundles(
            bundles,
            collection_frame=frame,
        )

        self.assertEqual(source_bytes, expected_source_bytes)
        self.assertEqual(
            manifest["source_export_sha256"],
            hashlib.sha256(expected_source_bytes).hexdigest(),
        )
        self.assertEqual(manifest["evidence_class"], "PROD_REAL_EVIDENCE")
        self.assertEqual(manifest["record_count"], 2)
        self.assertTrue(manifest["prod_promotion_eligible"])

    def test_record_tamper_after_persistence_commit_fails_before_nf06(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        bundles[0]["wrapper"]["record"]["answers"]["A01"] = "tampered"

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "integrity validation",
        ):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                bundles,
                collection_frame=frame,
            )

    def test_receipt_body_digest_tamper_fails_before_nf06(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        bundles[1]["receipt"]["body_sha256"] = "0" * 64

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "integrity validation",
        ):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                bundles,
                collection_frame=frame,
            )

    def test_duplicate_persisted_response_id_fails_closed(self):
        records = normalized_records()
        first = persisted_bundle(records[0])
        bundles = [first, copy.deepcopy(first)]
        frame, _ = collection_frame(records, prod=True)

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "duplicate response_id",
        ):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                bundles,
                collection_frame=frame,
            )

    def test_test_twin_record_is_not_accepted_by_prod_persisted_handoff(self):
        records = normalized_records(synthetic=True)
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)

        with self.assertRaises(HANDOFF.NF06PersistedHandoffError):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                bundles,
                collection_frame=frame,
            )


if __name__ == "__main__":
    unittest.main()
