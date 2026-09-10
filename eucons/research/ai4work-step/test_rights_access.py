from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research_storage import SQLiteResearchStorage, canonical_json_bytes
from rights_access import (
    ACCESS_COPY_SCOPE,
    RightsAccessError,
    build_receipt_keyed_access_copy,
)


FUTURE_REPLAY_BOUNDARY = "2099-01-01T00:00:00+00:00"


def test_record(response_id: str = "receipt-access-001") -> dict:
    # Synthetic engineering fixture only. It is never respondent evidence.
    return {
        "schema_version": 1,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "form_id": "AI4WORK_ADULTS_V1",
        "form_version": 1,
        "response_id": hashlib.sha256(response_id.encode("utf-8")).hexdigest(),
        "received_at": "2026-08-27T20:00:00+00:00",
        "recruitment_channel_id": "CH-ACCESS001",
        "profile": {
            "region": "Centru",
            "status": "persoană ocupată potențial eligibilă",
            "age_band": "40-49",
            "occupational_family": "administrativ/back-office",
        },
        "answers": {"Q01": 3, "Q07": False},
        "synthetic": False,
    }


def append_test_record(store: SQLiteResearchStorage, item: dict) -> None:
    body = canonical_json_bytes({"fixture": "TEST_TWIN_NON_EVIDENCE", "record": item})
    store.append_idempotent(
        item,
        raw_bytes=body,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )


class RightsAccessTests(unittest.TestCase):
    def test_access_copy_contains_only_approved_record_fields(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights-access.sqlite")
            item = test_record()
            append_test_record(store, item)
            self.assertTrue(store.set_analysis_hold(item["response_id"], "RESTRICTED_PENDING_REVIEW"))

            copy = build_receipt_keyed_access_copy(store, item["response_id"])
            self.assertIsNotNone(copy)
            self.assertEqual(copy["scope"], ACCESS_COPY_SCOPE)
            self.assertTrue(copy["controller_article15_context_required"])
            # This narrow record-copy adapter still does not authenticate by itself;
            # the two-part proof is a separate operational precondition.
            self.assertTrue(copy["requester_authentication_not_implemented_here"])
            self.assertEqual(copy["record"], item)

            # Rights-review state and storage/transport internals must not leak.
            serialized_keys = set(copy) | set(copy["record"])
            for forbidden in (
                "raw_sha256",
                "normalized_sha256",
                "body_sha256",
                "idempotency_key",
                "analysis_hold",
                "hold_state",
                "erasure_replay_block",
            ):
                self.assertNotIn(forbidden, serialized_keys)
            self.assertEqual(
                store.get_analysis_hold(item["response_id"]),
                "RESTRICTED_PENDING_REVIEW",
            )
            self.assertEqual(store.export("AI4WORK_ADULTS_V1"), [])

    def test_access_copy_is_detached_from_stored_record(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights-access.sqlite")
            item = test_record("receipt-access-detached")
            append_test_record(store, item)

            copy = build_receipt_keyed_access_copy(store, item["response_id"])
            copy["record"]["profile"]["region"] = "Sud-Muntenia"
            self.assertEqual(
                store.get_by_response_id(item["response_id"])["profile"]["region"],
                "Centru",
            )

    def test_unknown_or_erased_receipt_has_no_live_copy(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(
                Path(td) / "rights-access.sqlite",
                erasure_replay_not_after_utc=FUTURE_REPLAY_BOUNDARY,
            )
            item = test_record("receipt-access-erased")
            append_test_record(store, item)

            self.assertIsNone(build_receipt_keyed_access_copy(store, "unknown-receipt"))
            self.assertTrue(store.delete_by_response_id(item["response_id"]))
            self.assertIsNone(build_receipt_keyed_access_copy(store, item["response_id"]))

    def test_new_stored_fields_fail_closed_pending_disclosure_review(self):
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteResearchStorage(Path(td) / "rights-access.sqlite")
            item = test_record("receipt-access-unreviewed")
            item["internal_debug_token"] = "must-never-be-disclosed"
            append_test_record(store, item)

            with self.assertRaisesRegex(RightsAccessError, "not approved"):
                build_receipt_keyed_access_copy(store, item["response_id"])

    def test_rights_procedure_binds_article15_copy_and_separate_two_part_auth_candidate(self):
        procedure = json.loads(
            (Path(__file__).with_name("GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json")).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(procedure["schema_version"], "eucons.ai4work_data_subject_rights.v0.8")
        self.assertIn("gdpr_article_15", procedure["legal_design_anchors"])
        operations = procedure["research_store_operations"]
        self.assertEqual(
            operations["access_reference_adapter"],
            "RECEIPT_KEYED_RESPONDENT_RECORD_COPY_ALLOWLIST_FAIL_CLOSED_ON_NEW_FIELDS_NO_STORAGE_INTERNALS",
        )
        self.assertTrue(operations["access_controller_context_required"])
        self.assertEqual(
            operations["access_controller_context_template"],
            "ARTICLE15_CONTEXT_RESPONSE_TEMPLATE_2026-09-03.json",
        )
        self.assertEqual(
            operations["access_requester_authentication_reference_adapter"],
            "TWO_PART_OPAQUE_PROOF_RESPONSE_ID_PLUS_PRIVATE_UUIDV4_NO_IDENTITY_REGISTRY",
        )
        self.assertEqual(
            operations["access_requester_authentication_php_verifier"],
            "eucons/runtime/php/src/ResearchRightsAuth.php",
        )
        self.assertEqual(procedure["test_twin"]["classification"], "TEST_TWIN_NON_EVIDENCE")
        self.assertFalse(procedure["collection_enabled"])

    def test_rights_applicability_is_reconciled_but_live_workflow_remains_fail_closed(self):
        procedure = json.loads(
            (Path(__file__).with_name("GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json")).read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("gdpr_article_20", procedure["legal_design_anchors"])
        applicability = procedure["rights_applicability"]
        self.assertEqual(
            applicability["lawful_basis_status"],
            "GDPR_ARTICLE_6_1_F_LEGITIMATE_INTERESTS",
        )
        self.assertIn("ARTICLE_6_1_F", applicability["proposed_basis"])
        self.assertEqual(
            applicability["portability"],
            "NOT_APPLICABLE_UNDER_FINAL_LEGITIMATE_INTEREST_BASIS; MUST_BE_IMPLEMENTED BEFORE PROD IF FINAL BASIS CHANGES TO CONSENT OR CONTRACT AND ARTICLE 20 CONDITIONS ARE MET",
        )
        self.assertEqual(
            applicability["consent_withdrawal"],
            "NOT_APPLICABLE_UNDER_FINAL_LEGITIMATE_INTEREST_BASIS; MUST_BE_IMPLEMENTED BEFORE PROD IF CONSENT BECOMES A LEGAL BASIS",
        )
        self.assertEqual(
            procedure["research_store_operations"]["portability_reference_adapter"],
            "NOT_ENABLED_FINAL_LEGITIMATE_INTEREST_BASIS",
        )
        self.assertTrue(procedure["controller_policy_acceptance"]["approved"])
        self.assertFalse(procedure["controller_approval"])
        self.assertEqual(
            procedure["research_store_operations"]["access_requester_authentication_reference_adapter"],
            "TWO_PART_OPAQUE_PROOF_RESPONSE_ID_PLUS_PRIVATE_UUIDV4_NO_IDENTITY_REGISTRY",
        )
        self.assertEqual(procedure["request_channel"]["privacy_contact"], "privacy@eucons.ro")
        self.assertEqual(procedure["request_channel"]["status"], "CONFIG_BOUND_LIVE_DELIVERY_UNVERIFIED")
        self.assertFalse(procedure["collection_enabled"])


if __name__ == "__main__":
    unittest.main()
