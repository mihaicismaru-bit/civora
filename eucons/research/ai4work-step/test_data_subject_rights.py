from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research_storage import ResearchStorageError, SQLiteResearchStorage, canonical_json_bytes
from rights_rectification import rectify_by_response_id
from runtime import ResearchValidationError


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
        "profile": {
            "region": "Centru",
            "status": "persoană ocupată potențial eligibilă",
            "age_band": "40-49",
            "occupational_family": "administrativ/back-office",
        },
        "answers": {
            "Q01": 3,
            "Q02": 2,
            "Q03": 2,
            "Q04": 2,
            "Q05": 3,
            "Q06": 2,
            "Q07": False,
            "Q08": ["lipsa timpului"],
            "Q09": ["nu am folosit AI"],
            "Q10": {
                "utilizare_digitala_functionala": 3,
                "utilizarea_instrumentelor_AI": 5,
                "verificarea_rezultatelor_AI": 5,
                "protectia_datelor_confidentialitate": 4,
                "integrarea_AI_in_flux_de_lucru": 5,
            },
            "Q11": "adaptare mai bună la postul actual",
            "Q12": ["redactare și documente", "căutare și verificare informații"],
        },
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

    def test_rectification_revalidates_preset_values_and_preserves_transport_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            item = test_record("receipt-test-rectify")
            body, body_sha = append_test_record(store, item)
            before = store.conn.execute(
                "SELECT raw_sha256, normalized_sha256 FROM research_responses WHERE response_id = ?",
                (item["response_id"],),
            ).fetchone()

            corrected_profile = dict(item["profile"])
            corrected_profile["region"] = "Sud-Muntenia"
            corrected_answers = dict(item["answers"])
            corrected_answers["Q01"] = 4
            correction_bytes = canonical_json_bytes(
                {"rights_operation": "rectification", "receipt": item["response_id"]}
            )
            corrected_sha = rectify_by_response_id(
                store,
                item["response_id"],
                profile=corrected_profile,
                answers=corrected_answers,
                raw_bytes=correction_bytes,
            )

            corrected = store.get_by_response_id(item["response_id"])
            self.assertIsNotNone(corrected_sha)
            self.assertEqual(len(str(corrected_sha)), 64)
            self.assertEqual(corrected["profile"], corrected_profile)
            self.assertEqual(corrected["answers"], corrected_answers)
            for field in (
                "schema_version",
                "research_id",
                "form_id",
                "form_version",
                "response_id",
                "received_at",
                "recruitment_channel_id",
                "synthetic",
            ):
                self.assertEqual(corrected[field], item[field])

            after = store.conn.execute(
                "SELECT raw_sha256, normalized_sha256 FROM research_responses WHERE response_id = ?",
                (item["response_id"],),
            ).fetchone()
            self.assertNotEqual(before, after)
            self.assertEqual(after[1], corrected_sha)
            self.assertEqual(
                store.conn.execute(
                    "SELECT body_sha256, normalized_sha256 FROM idempotency_receipts WHERE response_id = ?",
                    (item["response_id"],),
                ).fetchone(),
                (body_sha, corrected_sha),
            )

            # A delayed retry of the original submission cannot overwrite the correction.
            replay_sha, inserted = store.append_idempotent(item, raw_bytes=body, body_sha256=body_sha)
            self.assertFalse(inserted)
            self.assertEqual(replay_sha, corrected_sha)
            self.assertEqual(store.get_by_response_id(item["response_id"]), corrected)

    def test_rectification_preserves_active_rights_hold(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            item = test_record("receipt-test-rectify-held")
            append_test_record(store, item)
            self.assertTrue(store.set_analysis_hold(item["response_id"], "RESTRICTED_PENDING_REVIEW"))

            corrected_profile = dict(item["profile"])
            corrected_profile["region"] = "Sud-Vest Oltenia"
            corrected_answers = dict(item["answers"])
            corrected_answers["Q01"] = 4
            corrected_sha = rectify_by_response_id(
                store,
                item["response_id"],
                profile=corrected_profile,
                answers=corrected_answers,
                raw_bytes=b"TEST_TWIN_NON_EVIDENCE rectification\n",
            )
            self.assertIsNotNone(corrected_sha)
            self.assertEqual(store.get_analysis_hold(item["response_id"]), "RESTRICTED_PENDING_REVIEW")
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])
            self.assertTrue(store.clear_analysis_hold(item["response_id"]))
            self.assertEqual(store.export("AI4WORK_ADULTS_V1")[0]["answers"]["Q01"], 4)

    def test_rectification_rejects_invalid_or_identifier_like_values_and_unknown_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights.sqlite")
            item = test_record("receipt-test-rectify-invalid")
            append_test_record(store, item)

            invalid_profile = dict(item["profile"])
            invalid_profile["region"] = "Unsupported Region"
            with self.assertRaises(ResearchValidationError):
                rectify_by_response_id(
                    store,
                    item["response_id"],
                    profile=invalid_profile,
                    answers=dict(item["answers"]),
                    raw_bytes=b"invalid\n",
                )

            identifier_profile = dict(item["profile"])
            identifier_profile["email"] = "person@example.org"
            with self.assertRaises(ResearchValidationError):
                rectify_by_response_id(
                    store,
                    item["response_id"],
                    profile=identifier_profile,
                    answers=dict(item["answers"]),
                    raw_bytes=b"invalid identifier\n",
                )
            self.assertIsNone(
                rectify_by_response_id(
                    store,
                    "unknown-receipt",
                    profile=dict(item["profile"]),
                    answers=dict(item["answers"]),
                    raw_bytes=b"unknown\n",
                )
            )
            self.assertEqual(store.get_by_response_id(item["response_id"]), item)

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
        self.assertEqual(
            procedure["research_store_operations"]["rectification_reference_adapter"],
            "RECEIPT_KEYED_PRESET_VALUES_ONLY_REVALIDATE_FROZEN_FORM_PRESERVE_TECHNICAL_PROVENANCE",
        )
        self.assertTrue(procedure["research_store_operations"]["rectification_preserves_active_hold"])
        self.assertTrue(procedure["research_store_operations"]["rectification_stale_retry_safe"])
        self.assertEqual(procedure["test_twin"]["classification"], "TEST_TWIN_NON_EVIDENCE")
        self.assertFalse(procedure["test_twin"]["prod_promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
