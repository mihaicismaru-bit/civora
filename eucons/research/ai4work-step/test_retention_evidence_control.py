from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from retention_evidence_control import (
    EVIDENCE_KEY,
    MANIFEST_PATH,
    RESEARCH_ID,
    SCHEDULE_PATH,
    _load,
    repository_retention_evidence_errors,
    retention_attestation_errors,
)

# All temporary control fixtures in this module are TEST TWIN engineering inputs only.
# They are NON-EVIDENCE and are never respondent data or promotion artifacts.
TEST_TWIN_CLASSIFICATION = "TEST_TWIN_NON_EVIDENCE"


class RetentionEvidenceControlTests(unittest.TestCase):
    def test_current_repository_state_is_truthfully_open(self) -> None:
        manifest = _load(MANIFEST_PATH)
        item = manifest["required_external_or_operational_evidence"][EVIDENCE_KEY]
        self.assertEqual(item["status"], "OPEN")
        self.assertIsNone(item["reference"])
        self.assertIsNone(item["sha256"])
        self.assertEqual(repository_retention_evidence_errors(), [])

    def test_minimal_generic_operational_attestation_cannot_satisfy_retention(self) -> None:
        payload = {
            "research_id": RESEARCH_ID,
            "evidence_binding_key": EVIDENCE_KEY,
            "evidence_class": "OPERATIONAL_EVIDENCE",
            "synthetic": False,
        }
        errors = retention_attestation_errors(
            payload,
            now_utc=datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc),
        )
        self.assertIn("retention_attestation_schema_invalid", errors)
        self.assertIn("retention_attestation_not_account_specific", errors)
        self.assertIn("retention_attestation_not_provider_bound", errors)
        self.assertIn("retention_schedule_sha256_mismatch", errors)
        self.assertIn("retention_verified_facts_missing", errors)

    def test_test_twin_marker_is_never_promotable(self) -> None:
        payload = {
            "schema_version": "eucons.ai4work_retention_deletion_attestation.v0.1",
            "research_id": RESEARCH_ID,
            "evidence_binding_key": EVIDENCE_KEY,
            "evidence_class": "OPERATIONAL_EVIDENCE",
            "synthetic": False,
            "artifact_class": TEST_TWIN_CLASSIFICATION,
            "account_specific": True,
            "provider_bound": True,
            "verified_at": "2026-09-01T03:00:00Z",
            "retention_schedule_reference": SCHEDULE_PATH.name,
            "retention_schedule_sha256": hashlib.sha256(SCHEDULE_PATH.read_bytes()).hexdigest(),
            "verified_facts": {},
            "provider_account_service_reference": "TEST_TWIN_NON_EVIDENCE",
            "deletion_control_reference": "TEST_TWIN_NON_EVIDENCE",
        }
        errors = retention_attestation_errors(
            payload,
            now_utc=datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc),
        )
        self.assertIn("retention_attestation_contains_non_evidence_marker", errors)

    def test_promoted_manifest_with_only_generic_semantics_is_rejected(self) -> None:
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        temp_attestation = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix=".tmp_retention_test_twin_non_evidence_",
            dir=MANIFEST_PATH.parent,
            delete=False,
        )
        path = Path(temp_attestation.name)
        try:
            json.dump(
                {
                    "research_id": RESEARCH_ID,
                    "evidence_binding_key": EVIDENCE_KEY,
                    "evidence_class": "OPERATIONAL_EVIDENCE",
                    "synthetic": False,
                },
                temp_attestation,
                sort_keys=True,
                separators=(",", ":"),
            )
            temp_attestation.write("\n")
            temp_attestation.close()
            manifest["required_external_or_operational_evidence"][EVIDENCE_KEY] = {
                "status": "PASS",
                "reference": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                dir=MANIFEST_PATH.parent,
                delete=False,
            ) as manifest_file:
                json.dump(manifest, manifest_file, sort_keys=True, separators=(",", ":"))
                manifest_file.write("\n")
                manifest_path = Path(manifest_file.name)
            try:
                errors = repository_retention_evidence_errors(manifest_path=manifest_path)
                self.assertIn("retention_attestation_schema_invalid", errors)
                self.assertIn("retention_verified_facts_missing", errors)
            finally:
                manifest_path.unlink(missing_ok=True)
        finally:
            if not temp_attestation.closed:
                temp_attestation.close()
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
