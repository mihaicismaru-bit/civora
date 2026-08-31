from __future__ import annotations

# TEST TWIN ONLY — NON-EVIDENCE. Uses synthetic engineering fixtures only.

import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

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


def rights_snapshot(response_ids: list[str] | None = None, *, captured_at: str | None = None, **overrides) -> dict:
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    value = {
        "schema_version": HANDOFF.RIGHTS_HOLD_SNAPSHOT_SCHEMA,
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "source_class": HANDOFF.RIGHTS_HOLD_SOURCE_CLASS,
        "artifact_class": HANDOFF.RIGHTS_HOLD_ARTIFACT_CLASS,
        "captured_at": captured_at,
        "complete_current_snapshot": True,
        "response_ids": [] if response_ids is None else list(response_ids),
    }
    value.update(overrides)
    return value


def canonical_snapshot_sha(snapshot: dict) -> str:
    payload = (
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def unvalidated_source_bytes(bundles: list[dict]) -> bytes:
    records = [copy.deepcopy(bundle["wrapper"]["record"]) for bundle in bundles]
    records.sort(
        key=lambda row: (
            str(row.get("form_id", "")),
            str(row.get("received_at", "")),
            str(row.get("response_id", "")),
        )
    )
    return b"".join(canonical_json_bytes(record) for record in records)


def freeze_receipt(bundles: list[dict], frame: dict, snapshot: dict, **overrides) -> dict:
    source_bytes = unvalidated_source_bytes(bundles)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    value = {
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
        "rights_hold_snapshot_sha256": canonical_snapshot_sha(snapshot),
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
    value.update(overrides)
    return value


def handoff(bundles: list[dict], frame: dict, snapshot: dict, freeze: dict | None = None):
    if freeze is None:
        freeze = freeze_receipt(bundles, frame, snapshot)
    return HANDOFF.build_prod_preingest_from_persisted_bundles(
        bundles,
        collection_frame=frame,
        rights_hold_snapshot=snapshot,
        collection_freeze_receipt=freeze,
    )


class NF06PersistedHandoffTests(unittest.TestCase):
    def setUp(self):
        self.records = normalized_records()
        self.bundles = [persisted_bundle(record) for record in self.records]
        self.frame, self.expected_source = collection_frame(self.records, prod=True)

    def test_valid_persisted_prod_handoff_binds_rights_and_collection_freeze(self):
        snapshot = rights_snapshot()
        source_bytes, manifest = handoff(list(reversed(self.bundles)), self.frame, snapshot)
        self.assertEqual(source_bytes, self.expected_source)
        self.assertEqual(manifest["evidence_class"], "PROD_REAL_EVIDENCE")
        self.assertEqual(manifest["record_count"], 2)
        self.assertTrue(manifest["prod_promotion_eligible"])
        self.assertTrue(manifest["rights_hold_snapshot_checked"])
        self.assertTrue(manifest["held_responses_excluded_from_export"])
        self.assertEqual(manifest["rights_hold_count_at_export"], 0)
        self.assertEqual(manifest["rights_hold_snapshot_sha256"], canonical_snapshot_sha(snapshot))
        self.assertTrue(manifest["collection_close_export_freeze_checked"])
        self.assertEqual(manifest["collection_close_export_freeze_schema"], FREEZE.SCHEMA_VERSION)
        self.assertEqual(manifest["collection_close_export_freeze_status"], FREEZE.FREEZE_STATUS)
        self.assertEqual(manifest["collection_close_post_close_accepted_record_count"], 0)
        self.assertTrue(manifest["collection_close_control_not_need_evidence"])
        self.assertFalse(manifest["collection_close_receipt_is_authorization"])

    def test_missing_authoritative_rights_snapshot_fails_closed(self):
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "authoritative rights-hold snapshot"):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                self.bundles,
                collection_frame=self.frame,
                rights_hold_snapshot=None,
                collection_freeze_receipt=None,
            )

    def test_non_object_rights_snapshot_fails_closed(self):
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "rights-hold snapshot must be an object"):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                self.bundles,
                collection_frame=self.frame,
                rights_hold_snapshot=set(),
                collection_freeze_receipt=None,
            )

    def test_missing_collection_freeze_receipt_fails_closed(self):
        snapshot = rights_snapshot()
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "authoritative collection close/export freeze receipt"):
            HANDOFF.build_prod_preingest_from_persisted_bundles(
                self.bundles,
                collection_frame=self.frame,
                rights_hold_snapshot=snapshot,
                collection_freeze_receipt=None,
            )

    def test_held_response_fails_before_export(self):
        snapshot = rights_snapshot([self.records[0]["response_id"]])
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "under rights analysis hold"):
            handoff(self.bundles, self.frame, snapshot)

    def test_rights_snapshot_structure_source_and_completeness_fail_closed(self):
        for snapshot, pattern in [
            (rights_snapshot(["not-an-opaque-receipt"]), "lowercase SHA-256 hex"),
            (rights_snapshot(source_class="ARBITRARY_CALLER_SET"), "source_class mismatch"),
            (rights_snapshot(complete_current_snapshot=False), "complete_current_snapshot=true"),
            (rights_snapshot(case_narrative="forbidden"), "exact field allowlist mismatch"),
        ]:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, pattern):
                    handoff(self.bundles, self.frame, snapshot)

    def test_rights_snapshot_temporal_controls_fail_closed(self):
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "predates collection close"):
            handoff(self.bundles, self.frame, rights_snapshot(captured_at="2026-08-28T17:59:59Z"))

        stale = (datetime.now(timezone.utc) - HANDOFF.MAX_RIGHTS_HOLD_SNAPSHOT_AGE - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "stale at NF06 persisted handoff"):
            handoff(self.bundles, self.frame, rights_snapshot(captured_at=stale))

        future = (datetime.now(timezone.utc) + HANDOFF.MAX_RIGHTS_HOLD_CLOCK_SKEW + timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "future beyond allowed clock skew"):
            handoff(self.bundles, self.frame, rights_snapshot(captured_at=future))

    def test_collection_freeze_rejects_post_close_accepts_and_source_hash_drift(self):
        snapshot = rights_snapshot()
        for freeze, pattern in [
            (freeze_receipt(self.bundles, self.frame, snapshot, post_close_accepted_record_count=1), "post-close accepted records must be zero"),
            (freeze_receipt(self.bundles, self.frame, snapshot, source_export_sha256="0" * 64), "source_export_sha256 mismatch"),
        ]:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, pattern):
                    handoff(self.bundles, self.frame, snapshot, freeze)

    def test_collection_freeze_binds_retention_and_cannot_authorize(self):
        snapshot = rights_snapshot()
        for freeze, pattern in [
            (freeze_receipt(self.bundles, self.frame, snapshot, retention_schedule_sha256="0" * 64), "retention schedule SHA-256 mismatch"),
            (freeze_receipt(self.bundles, self.frame, snapshot, receipt_is_authorization=True), "must not act as controller/deploy authorization"),
            (freeze_receipt(self.bundles, self.frame, snapshot, synthetic_records_included=True), "synthetic records are forbidden"),
        ]:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, pattern):
                    handoff(self.bundles, self.frame, snapshot, freeze)

    def test_collection_freeze_temporal_chain_is_fail_closed(self):
        snapshot = rights_snapshot()
        close = self.frame["collection_closed_at"]
        before_close = "2026-08-28T17:59:59Z"
        freeze = freeze_receipt(
            self.bundles,
            self.frame,
            snapshot,
            runtime_acceptance_disabled_at=before_close,
            export_frozen_at=before_close,
        )
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "runtime acceptance was disabled before declared collection close"):
            handoff(self.bundles, self.frame, snapshot, freeze)

        freeze = freeze_receipt(
            self.bundles,
            self.frame,
            snapshot,
            retention_anchor_at="2026-08-28T18:00:01Z" if close != "2026-08-28T18:00:01Z" else "2026-08-28T18:00:02Z",
        )
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "retention anchor must equal collection_closed_at"):
            handoff(self.bundles, self.frame, snapshot, freeze)

    def test_persisted_record_or_receipt_tamper_fails_before_nf06(self):
        tampered = copy.deepcopy(self.bundles)
        tampered[0]["wrapper"]["record"]["answers"]["A01"] = "tampered"
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "integrity validation"):
            handoff(tampered, self.frame, rights_snapshot())

        tampered = copy.deepcopy(self.bundles)
        tampered[1]["receipt"]["body_sha256"] = "0" * 64
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "integrity validation"):
            handoff(tampered, self.frame, rights_snapshot())

    def test_duplicate_response_id_fails_closed(self):
        bundles = [self.bundles[0], copy.deepcopy(self.bundles[0])]
        with self.assertRaisesRegex(HANDOFF.NF06PersistedHandoffError, "duplicate response_id"):
            handoff(bundles, self.frame, rights_snapshot())

    def test_test_twin_record_is_not_accepted_by_prod_handoff(self):
        records = normalized_records(synthetic=True)
        bundles = [persisted_bundle(record) for record in records]
        frame, _ = collection_frame(records, prod=True)
        with self.assertRaises(HANDOFF.NF06PersistedHandoffError):
            handoff(bundles, frame, rights_snapshot())


if __name__ == "__main__":
    unittest.main()
