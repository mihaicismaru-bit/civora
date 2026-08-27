from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research_storage import ResearchStorageError, SQLiteResearchStorage, canonical_json_bytes


def test_record(response_id: str = "receipt-test-001") -> dict:
    # Synthetic engineering fixture only. It is deliberately not respondent evidence.
    return {
        "schema_version": 1,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "form_id": "AI4WORK_ADULTS_V1",
        "form_version": 1,
        "response_id": response_id,
        "received_at": "2026-08-27T12:00:00+00:00",
        "recruitment_channel_id": "CH-RIGHTS001",
        "profile": {"region": "Centru"},
        "answers": {"Q01": 2},
        "synthetic": False,
    }


def append_test_record(store: SQLiteResearchStorage, item: dict) -> None:
    body = canonical_json_bytes({"fixture": "TEST_TWIN_NON_EVIDENCE", "record": item})
    body_sha = hashlib.sha256(body).hexdigest()
    store.append_idempotent(item, raw_bytes=body, body_sha256=body_sha)


class DataSubjectRightsTests(unittest.TestCase):
    def test_receipt_lookup_and_atomic_erasure_remove_live_record_receipt_and_hold(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            item = test_record()
            append_test_record(store, item)

            self.assertEqual(store.get_by_response_id(item["response_id"]), item)
            self.assertEqual(
                store.conn.execute(
                    "SELECT COUNT(*) FROM idempotency_receipts WHERE response_id = ?",
                    (item["response_id"],),
                ).fetchone()[0],
                1,
            )
            self.assertTrue(store.set_analysis_hold(item["response_id"], "RESTRICTED_PENDING_REVIEW"))
            self.assertEqual(store.get_analysis_hold(item["response_id"]), "RESTRICTED_PENDING_REVIEW")
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

            self.assertTrue(store.delete_by_response_id(item["response_id"]))
            self.assertIsNone(store.get_by_response_id(item["response_id"]))
            self.assertIsNone(store.get_analysis_hold(item["response_id"]))
            self.assertEqual(
                store.conn.execute(
                    "SELECT COUNT(*) FROM idempotency_receipts WHERE response_id = ?",
                    (item["response_id"],),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

    def test_restriction_and_objection_holds_exclude_records_until_cleared(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            restricted = test_record("receipt-test-002")
            objected = test_record("receipt-test-003")
            append_test_record(store, restricted)
            append_test_record(store, objected)

            self.assertTrue(store.set_analysis_hold(restricted["response_id"], "RESTRICTED_PENDING_REVIEW"))
            self.assertTrue(store.set_analysis_hold(objected["response_id"], "OBJECTED_PENDING_REVIEW"))
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])
            self.assertEqual(store.get_by_response_id(restricted["response_id"]), restricted)
            self.assertEqual(store.get_by_response_id(objected["response_id"]), objected)

            self.assertTrue(store.clear_analysis_hold(restricted["response_id"]))
            self.assertEqual(store.get_analysis_hold(restricted["response_id"]), None)
            self.assertEqual(store.get_analysis_hold(objected["response_id"]), "OBJECTED_PENDING_REVIEW")
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [restricted])

            self.assertTrue(store.clear_analysis_hold(objected["response_id"]))
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [restricted, objected])

    def test_unknown_receipt_does_not_mutate_other_records(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            item = test_record("receipt-test-004")
            append_test_record(store, item)

            self.assertFalse(store.set_analysis_hold("unknown-receipt", "RESTRICTED_PENDING_REVIEW"))
            self.assertFalse(store.delete_by_response_id("unknown-receipt"))
            self.assertEqual(store.get_by_response_id(item["response_id"]), item)
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [item])

    def test_invalid_receipt_and_hold_state_are_rejected_without_identity_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            with self.assertRaises(ResearchStorageError):
                store.get_by_response_id("")
            with self.assertRaises(ResearchStorageError):
                store.delete_by_response_id("x" * 257)
            with self.assertRaises(ResearchStorageError):
                store.set_analysis_hold("receipt-test-005", "FREE_TEXT_REASON")

    def test_rights_procedure_remains_draft_non_evidence(self):
        procedure = json.loads(
            (Path(__file__).with_name("GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json")).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(procedure["status"], "DRAFT_BINDING_REQUIRED_BEFORE_COLLECTION")
        self.assertEqual(procedure["evidence_class"], "CONTROL_ARTIFACT_NOT_EVIDENCE")
        self.assertFalse(procedure["controller_approval"])
        self.assertFalse(procedure["collection_enabled"])
        self.assertEqual(procedure["identification_policy"]["direct_identity_registry"], "FORBIDDEN")
        self.assertEqual(procedure["identification_policy"]["crm_or_contact_cross_reference"], "FORBIDDEN")
        self.assertEqual(
            procedure["research_store_operations"]["restriction_or_objection_state_store"],
            "BOUNDED_ENUM_ONLY_NO_CASE_NARRATIVE",
        )
        self.assertTrue(procedure["research_store_operations"]["held_records_excluded_from_export"])
        self.assertEqual(procedure["test_twin"]["classification"], "TEST_TWIN_NON_EVIDENCE")
        self.assertFalse(procedure["test_twin"]["prod_promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
