from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research_storage import ResearchStorageError, SQLiteResearchStorage, canonical_json_bytes


FUTURE_REPLAY_BOUNDARY = "2099-01-01T00:00:00+00:00"


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


def append_test_record(store: SQLiteResearchStorage, item: dict) -> tuple[bytes, str]:
    body = canonical_json_bytes({"fixture": "TEST_TWIN_NON_EVIDENCE", "record": item})
    body_sha = hashlib.sha256(body).hexdigest()
    store.append_idempotent(item, raw_bytes=body, body_sha256=body_sha)
    return body, body_sha


class DataSubjectRightsTests(unittest.TestCase):
    def test_receipt_lookup_atomic_erasure_and_replay_block(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(
                Path(td) / "rights.sqlite",
                erasure_replay_not_after_utc=FUTURE_REPLAY_BOUNDARY,
            )
            item = test_record()
            body, body_sha = append_test_record(store, item)

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
            self.assertEqual(
                store.conn.execute(
                    "SELECT COUNT(*) FROM erasure_replay_blocks WHERE response_id = ?",
                    (item["response_id"],),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

            # A delayed transport retry must not recreate data before the approved boundary.
            with self.assertRaisesRegex(ResearchStorageError, "erased response replay blocked"):
                store.append_idempotent(item, raw_bytes=body, body_sha256=body_sha)
            self.assertIsNone(store.get_by_response_id(item["response_id"]))
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

    def test_erasure_fails_closed_without_finite_replay_retention_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            item = test_record("receipt-test-boundary-required")
            append_test_record(store, item)

            with self.assertRaisesRegex(ResearchStorageError, "retention boundary required"):
                store.delete_by_response_id(item["response_id"])

            self.assertEqual(store.get_by_response_id(item["response_id"]), item)
            self.assertEqual(
                store.conn.execute(
                    "SELECT COUNT(*) FROM erasure_replay_blocks WHERE response_id = ?",
                    (item["response_id"],),
                ).fetchone()[0],
                0,
            )

    def test_replay_marker_auto_expires_at_configured_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(
                Path(td) / "rights.sqlite",
                erasure_replay_not_after_utc=FUTURE_REPLAY_BOUNDARY,
            )
            item = test_record("receipt-test-expiry")
            body, body_sha = append_test_record(store, item)
            self.assertTrue(store.delete_by_response_id(item["response_id"]))

            deleted = store.expire_erasure_replay_blocks(
                now_utc=datetime(2100, 1, 1, tzinfo=timezone.utc)
            )
            self.assertEqual(deleted, 1)
            self.assertEqual(
                store.conn.execute("SELECT COUNT(*) FROM erasure_replay_blocks").fetchone()[0],
                0,
            )

            normalized_sha, inserted = store.append_idempotent(item, raw_bytes=body, body_sha256=body_sha)
            self.assertTrue(inserted)
            self.assertEqual(len(normalized_sha), 64)

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
        self.assertEqual(
            procedure["research_store_operations"]["erasure_replay_suppression"],
            "OPAQUE_RESPONSE_ID_ONLY_NO_ANSWERS_NO_BODY_DIGEST_NOT_ANALYTICAL",
        )
        self.assertEqual(
            procedure["research_store_operations"]["erasure_replay_marker_reference_adapter_boundary"],
            "REQUIRED_FINITE_UTC_NOT_AFTER_NO_DEFAULT",
        )
        self.assertTrue(procedure["research_store_operations"]["erased_records_replay_blocked"])
        self.assertEqual(procedure["test_twin"]["classification"], "TEST_TWIN_NON_EVIDENCE")
        self.assertFalse(procedure["test_twin"]["prod_promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
