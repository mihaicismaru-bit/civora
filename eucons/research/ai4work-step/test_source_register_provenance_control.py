from __future__ import annotations

import copy
import hashlib
import unittest
from datetime import datetime, timezone

import source_register_provenance_control as CONTROL
from research_storage import RESEARCH_ID, canonical_json_bytes

TEST_TWIN_FIXTURES_NON_EVIDENCE = True
SNAPSHOT = b"TEST TWIN NON-EVIDENCE source snapshot mechanics only"


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def source_register() -> dict:
    return {
        "schema_version": CONTROL.SOURCE_REGISTER_SCHEMA,
        "research_id": RESEARCH_ID,
        "status": CONTROL.TEST_STATUS,
        "test_twin_evidence_eligible": False,
        "entries": [
            {
                "source_id": "S99",
                "publisher": "TEST TWIN",
                "title": "Synthetic provenance mechanics fixture",
                "publication_date": "2026-09-01",
                "url": "https://example.invalid/test-twin-non-evidence",
                "evidence_role": "TEST_TWIN_NON_EVIDENCE",
                "h1_h5_numeric_points": 0,
                "project_activity_as_need_evidence": False,
                "numeric_rank_eligible": False,
            }
        ],
    }


def provenance(register: dict) -> dict:
    return {
        "schema_version": CONTROL.SCHEMA,
        "research_id": RESEARCH_ID,
        "source_register_sha256": _sha(register),
        "test_twin_evidence_eligible": False,
        "entries": [
            {
                "source_id": "S99",
                "source_type": "OFFICIAL_PUBLIC_AUTHORITY",
                "source_reference": "TEST-TWIN-NON-EVIDENCE://S99",
                "snapshot_sha256": hashlib.sha256(SNAPSHOT).hexdigest(),
                "verified_at": "2026-09-01T00:00:00+00:00",
                "status": CONTROL.TEST_PROVENANCE_STATUS,
                "synthetic": True,
                "evidence_eligible": False,
            }
        ],
    }


class SourceRegisterProvenanceTests(unittest.TestCase):
    def test_test_twin_verifies_mechanics_but_remains_non_evidence(self) -> None:
        self.assertTrue(TEST_TWIN_FIXTURES_NON_EVIDENCE)
        register = source_register()
        result = CONTROL.verify_source_register_provenance(
            register,
            provenance(register),
            snapshot_bytes_by_source_id={"S99": SNAPSHOT},
            evidence_mode=CONTROL.TEST_MODE,
            now_utc=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(result["verification_status"], CONTROL.TEST_MODE)
        self.assertFalse(result["test_twin_evidence_eligible"])
        self.assertEqual(result["secondary_evidence_numeric_points"], 0)
        self.assertEqual(result["project_activity_numeric_points"], 0)

    def test_declared_snapshot_hash_is_recomputed_and_mismatch_fails_closed(self) -> None:
        register = source_register()
        manifest = provenance(register)
        manifest["entries"][0]["snapshot_sha256"] = "0" * 64
        with self.assertRaisesRegex(CONTROL.SourceRegisterProvenanceError, "SHA-256 mismatch"):
            CONTROL.verify_source_register_provenance(
                register,
                manifest,
                snapshot_bytes_by_source_id={"S99": SNAPSHOT},
                evidence_mode=CONTROL.TEST_MODE,
                now_utc=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
            )

    def test_missing_snapshot_bytes_fail_closed(self) -> None:
        register = source_register()
        with self.assertRaisesRegex(CONTROL.SourceRegisterProvenanceError, "source/snapshot census mismatch"):
            CONTROL.verify_source_register_provenance(
                register,
                provenance(register),
                snapshot_bytes_by_source_id={},
                evidence_mode=CONTROL.TEST_MODE,
                now_utc=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
            )

    def test_orphan_provenance_entry_fails_closed(self) -> None:
        register = source_register()
        manifest = provenance(register)
        orphan = copy.deepcopy(manifest["entries"][0])
        orphan["source_id"] = "S98"
        manifest["entries"].append(orphan)
        with self.assertRaisesRegex(CONTROL.SourceRegisterProvenanceError, "source/provenance census mismatch"):
            CONTROL.verify_source_register_provenance(
                register,
                manifest,
                snapshot_bytes_by_source_id={"S99": SNAPSHOT},
                evidence_mode=CONTROL.TEST_MODE,
                now_utc=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
            )

    def test_test_twin_cannot_be_promoted_by_requesting_prod_mode(self) -> None:
        register = source_register()
        with self.assertRaisesRegex(CONTROL.SourceRegisterProvenanceError, "status does not match evidence mode"):
            CONTROL.verify_source_register_provenance(
                register,
                provenance(register),
                snapshot_bytes_by_source_id={"S99": SNAPSHOT},
                evidence_mode=CONTROL.PROD_MODE,
                now_utc=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
            )

    def test_project_activity_can_never_be_promoted_as_need_evidence(self) -> None:
        register = source_register()
        register["entries"][0]["project_activity_as_need_evidence"] = True
        manifest = provenance(register)
        with self.assertRaisesRegex(CONTROL.SourceRegisterProvenanceError, "project activity"):
            CONTROL.verify_source_register_provenance(
                register,
                manifest,
                snapshot_bytes_by_source_id={"S99": SNAPSHOT},
                evidence_mode=CONTROL.TEST_MODE,
                now_utc=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
            )

    def test_future_verification_timestamp_fails_closed(self) -> None:
        register = source_register()
        manifest = provenance(register)
        manifest["entries"][0]["verified_at"] = "2026-09-01T02:00:00+00:00"
        with self.assertRaisesRegex(CONTROL.SourceRegisterProvenanceError, "cannot be in the future"):
            CONTROL.verify_source_register_provenance(
                register,
                manifest,
                snapshot_bytes_by_source_id={"S99": SNAPSHOT},
                evidence_mode=CONTROL.TEST_MODE,
                now_utc=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
