from __future__ import annotations

# TEST TWIN ONLY — NON-EVIDENCE. Uses synthetic engineering fixtures only.

import copy
import hashlib
from datetime import datetime, timedelta, timezone
import json
import unittest

import canonical_export_integrity as EXPORT_INTEGRITY
import collection_close_export_freeze as FREEZE
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


def rights_snapshot(
    response_ids: list[str] | None = None,
    *,
    captured_at: str | None = None,
    **overrides,
) -> dict:
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snapshot = {
        "schema_version": HANDOFF.RIGHTS_HOLD_SNAPSHOT_SCHEMA,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "source_class": HANDOFF.RIGHTS_HOLD_SOURCE_CLASS,
        "artifact_class": HANDOFF.RIGHTS_HOLD_ARTIFACT_CLASS,
        "captured_at": captured_at,
        "complete_current_snapshot": True,
        "response_ids": [] if response_ids is None else list(response_ids),
    }
    snapshot.update(overrides)
    return snapshot


def _canonical_snapshot_sha(snapshot: dict) -> str:
    payload = (
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _unvalidated_source_bytes(bundles: list[dict]) -> bytes:
    records = [copy.deepcopy(bundle["wrapper"]["record"]) for bundle in bundles]
    records.sort(
        key=lambda row: (
            str(row.get("form_id", "")),
            str(row.get("received_at", "")),
            str(row.get("response_id", "")),
        )
    )
    return b"".join(canonical_json_bytes(record) for record in records)


def freeze_receipt(
    bundles: list[dict],
    frame: dict,
    snapshot: dict,
    **overrides,
) -> dict:
    source_bytes = _unvalidated_source_bytes(bundles)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipt = {
        "schema_version": FREEZE.SCHEMA_VERSION,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "artifact_class": FREEZE.ARTIFACT_CLASS,
        "evidence_class": FREEZE.PROD_EVIDENCE_CLASS,
        "freeze_status": FREEZE.FREEZE_STATUS,
        "collection_frame_id": frame["collection_frame_id"],
        "collection_frame_sha256": hashlib.sha256(canonical_json_bytes(frame)).hexdigest(),
        "collection_closed_at": frame["collection_closed_at"],
        "runtime_acceptance_disabled_at": now,
        "export_frozen_at": now,
        "source_export_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "accepted_record_count": len(bundles),
        "post_close_accepted_record_count": 0,
        "rights_hold_snapshot_sha256": _canonical_snapshot_sha(snapshot),
        "collection_channel_register_sha256": frame["collection_channel_register_sha256"],
        "retention_schedule_sha256": FREEZE.retention_schedule_sha256(),
        "retention_anchor_at": frame["collection_closed_at"],
        "live_respondent_delete_max_days_after_close": 180,
        "live_respondent_hard_stop": "2027-03-31",
        "synthetic_records_included": False,
        "direct_identifiers_in_receipt": False,
        "crm_linkage": "FORBIDDEN",
        "commercial_tracking": "FORBIDDEN",
        "control_artifact_not_need_evidence": True,
        "receipt_is_authorization": False,
        "nf06_freeze_prerequisite_satisfied": True,
    }
    receipt.update(overrides)
    return receipt


def call_handoff(
    bundles: list[dict],
    frame: dict,
    snapshot: dict | None,
    *,
    freeze: dict | None = None,
):
    if freeze is None and isinstance(snapshot, dict):
        freeze = freeze_receipt(bundles, frame, snapshot)
    return HANDOFF.build_prod_preingest_from_persisted_bundles(
        bundles,
        collection_frame=frame,
        rights_hold_snapshot=snapshot,
        collection_freeze_receipt=freeze,
    )


class NF06PersistedHandoffTests(unittest.TestCase):
    def test_valid_persisted_prod_bundles_build_exact_nf06_source_and_manifest(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in reversed(records)]
        frame, expected_source_bytes = collection_frame(records, prod=True)
        snapshot = rights_snapshot()

        source_bytes, manifest = call_handoff(bundles, frame, snapshot)

        self.assertEqual(source_bytes, expected_source_bytes)
        self.assertEqual(
            manifest["source_export_sha256"],
            hashlib.sha256(expected_source_bytes).hexdigest(),
        )
        self.assertEqual(manifest["evidence_class"], "PROD_REAL_EVIDENCE")
        self.assertEqual(manifest["record_count"], 2)
        self.assertTrue(manifest["prod_promotion_eligible"])
        self.assertTrue(manifest["rights_hold_snapshot_checked"])
        self.assertTrue(manifest["held_responses_excluded_from_export"])
        self.assertEqual(manifest["rights_hold_count_at_export"], 0)
        self.assertEqual(
            manifest["rights_hold_snapshot_schema"],
            "eucons.ai4work_rights_hold_snapshot.v0.1",
        )
        self.assertEqual(
            manifest["rights_hold_snapshot_source_class"],
            "EUCONS_RESEARCH_RIGHTS_STORE",
        )
        self.assertEqual(
            manifest["rights_hold_snapshot_captured_at"],
            snapshot["captured_at"],
        )
        canonical_snapshot = (
            json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        self.assertEqual(
            manifest["rights_hold_snapshot_sha256"],
            hashlib.sha256(canonical_snapshot).hexdigest(),
        )
        self.assertEqual(
            manifest["rights_hold_receipt_set_sha256"],
            hashlib.sha256(
                json.dumps([], ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
        )
        self.assertTrue(manifest["collection_close_export_freeze_checked"])
        self.assertEqual(
            manifest["collection_close_export_freeze_schema"],
            FREEZE.SCHEMA_VERSION,
        )
        self.assertEqual(
            manifest["collection_close_export_freeze_status"],
            "FROZEN_FOR_NF06_PROD",
        )
        self.assertEqual(
            manifest["collection_close_post_close_accepted_record_count"], 0
        )
        self.assertTrue(manifest["collection_close_control_not_need_evidence"])
        self.assertFalse(manifest["collection_close_receipt_is_authorization"])

    def test_prod_handoff_requires_structured_authoritative_rights_hold_snapshot(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "authoritative rights-hold snapshot object is required",
        ):
            call_handoff(bundles, frame, None, freeze=None)

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "rights-hold snapshot must be an object",
        ):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                bundles,
                collection_frame=frame,
                rights_hold_snapshot=set(),
                collection_freeze_receipt=None,
            )

    def test_prod_handoff_requires_collection_close_export_freeze_receipt(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        snapshot = rights_snapshot()

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "authoritative collection close/export freeze receipt is required",
        ):
            call_handoff(bundles, frame, snapshot, freeze=None)

    def test_collection_freeze_rejects_post_close_accepts_and_hash_drift(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        snapshot = rights_snapshot()

        bad_count = freeze_receipt(
            bundles,
            frame,
            snapshot,
            post_close_accepted_record_count=1,
        )
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "post-close accepted records must be zero",
        ):
            call_handoff(bundles, frame, snapshot, freeze=bad_count)

        bad_hash = freeze_receipt(
            bundles,
            frame,
            snapshot,
            source_export_sha256="0" * 64,
        )
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "source_export_sha256 mismatch",
        ):
            call_handoff(bundles, frame, snapshot, freeze=bad_hash)

    def test_collection_freeze_binds_retention_and_is_not_authorization(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        snapshot = rights_snapshot()

        bad_retention = freeze_receipt(
            bundles,
            frame,
            snapshot,
            retention_schedule_sha256="0" * 64,
        )
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "retention schedule SHA-256 mismatch",
        ):
            call_handoff(bundles, frame, snapshot, freeze=bad_retention)

        bad_authorization = freeze_receipt(
            bundles,
            frame,
            snapshot,
            receipt_is_authorization=True,
        )
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "must not act as controller/deploy authorization",
        ):
            call_handoff(bundles, frame, snapshot, freeze=bad_authorization)

    def test_record_under_rights_hold_fails_before_nf06_prod_export(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        snapshot = rights_snapshot([records[0]["response_id"]])

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "under rights analysis hold",
        ):
            call_handoff(bundles, frame, snapshot)

    def test_invalid_rights_hold_receipt_fails_closed(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        snapshot = rights_snapshot(["not-an-opaque-receipt"])

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "lowercase SHA-256 hex",
        ):
            call_handoff(bundles, frame, snapshot)

    def test_rights_snapshot_source_class_and_completeness_are_fail_closed(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "source_class mismatch",
        ):
            call_handoff(
                bundles,
                frame,
                rights_snapshot(source_class="ARBITRARY_CALLER_SET"),
            )

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "complete_current_snapshot=true",
        ):
            call_handoff(
                bundles,
                frame,
                rights_snapshot(complete_current_snapshot=False),
            )

    def test_rights_snapshot_must_not_predate_collection_close_or_candidate_records(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "predates collection close",
        ):
            call_handoff(
                bundles,
                frame,
                rights_snapshot(captured_at="2026-08-28T17:59:59Z"),
            )

        frame2 = copy.deepcopy(frame)
        frame2["collection_closed_at"] = "2026-08-28T09:30:00+00:00"
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "predates latest candidate record",
        ):
            call_handoff(
                bundles,
                frame2,
                rights_snapshot(captured_at="2026-08-28T09:45:00Z"),
            )

    def test_rights_snapshot_must_be_fresh_at_handoff_and_not_future_dated(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)

        stale = (
            datetime.now(timezone.utc) - HANDOFF.MAX_RIGHTS_HOLD_SNAPSHOT_AGE - timedelta(seconds=5)
        ).isoformat().replace("+00:00", "Z")
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "stale at NF06 persisted handoff",
        ):
            call_handoff(bundles, frame, rights_snapshot(captured_at=stale))

        future = (
            datetime.now(timezone.utc) + HANDOFF.MAX_RIGHTS_HOLD_CLOCK_SKEW + timedelta(seconds=5)
        ).isoformat().replace("+00:00", "Z")
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "future beyond allowed clock skew",
        ):
            call_handoff(bundles, frame, rights_snapshot(captured_at=future))

    def test_rights_snapshot_rejects_unreviewed_extra_fields(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "exact field allowlist mismatch",
        ):
            call_handoff(
                bundles,
                frame,
                rights_snapshot(
                    case_narrative="must never enter analytical control artifact"
                ),
            )

    def test_record_tamper_after_persistence_commit_fails_before_nf06(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        bundles[0]["wrapper"]["record"]["answers"]["A01"] = "tampered"
        snapshot = rights_snapshot()

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "integrity validation",
        ):
            call_handoff(bundles, frame, snapshot)

    def test_receipt_body_digest_tamper_fails_before_nf06(self):
        records = normalized_records()
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        bundles[1]["receipt"]["body_sha256"] = "0" * 64
        snapshot = rights_snapshot()

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "integrity validation",
        ):
            call_handoff(bundles, frame, snapshot)

    def test_duplicate_persisted_response_id_fails_closed(self):
        records = normalized_records()
        first = persisted_bundle(records[0])
        bundles = [first, copy.deepcopy(first)]
        frame, _ = collection_frame(records, prod=True)
        snapshot = rights_snapshot()

        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "duplicate response_id",
        ):
            call_handoff(bundles, frame, snapshot)

    def test_test_twin_record_is_not_accepted_by_prod_persisted_handoff(self):
        records = normalized_records(synthetic=True)
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        snapshot = rights_snapshot()

        with self.assertRaises(HANDOFF.NF06PersistedHandoffError):
            call_handoff(bundles, frame, snapshot)


if __name__ == "__main__":
    unittest.main()
