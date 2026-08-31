from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from explicit_user_approval_control import (
    APPROVAL_ACTION,
    APPROVAL_SCHEMA,
    APPROVAL_SOURCE,
    HERE,
    REQUIRED_BOUND_ARTIFACTS,
    explicit_user_approval_errors,
)


class ExplicitUserApprovalControlTests(unittest.TestCase):
    """TEST TWIN control fixtures only; never evidence and never promotable."""

    research_id = "AI4WORK-STEP-NF-RUN-001"
    approved_at = "2026-08-31T18:00:00Z"

    def _payload(self) -> dict:
        return {
            "schema_version": APPROVAL_SCHEMA,
            "research_id": self.research_id,
            "status": "APPROVED",
            "artifact_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
            "test_fixture_class": "TEST_TWIN_NON_EVIDENCE",
            "synthetic": False,
            "approval_source": APPROVAL_SOURCE,
            "authorized_action": APPROVAL_ACTION,
            "approved": True,
            "approved_at": self.approved_at,
            "approved_by_user_reference": "TEST_TWIN_OPAQUE_APPROVAL_REFERENCE_NON_EVIDENCE",
            "real_collection_authorized": True,
            "merge_authorized": False,
            "deploy_authorized": False,
            "canonicalization_authorized": False,
            "bound_artifacts": {
                key: {
                    "reference": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for key, path in REQUIRED_BOUND_ARTIFACTS.items()
            },
        }

    def _write_receipt(self, payload: dict) -> tuple[Path, str]:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix=".tmp_explicit_user_approval_test_twin_non_evidence_",
            dir=HERE,
            delete=False,
        )
        try:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        finally:
            handle.close()
        path = Path(handle.name)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _manifest(self, path: Path, digest: str, timestamp: str | None = None) -> dict:
        return {
            "research_id": self.research_id,
            "explicit_user_approval_reference": path.name,
            "explicit_user_approval_sha256": digest,
            "approval_timestamp": timestamp if timestamp is not None else self.approved_at,
        }

    def test_valid_exact_bound_receipt_mechanics_pass(self):
        path, digest = self._write_receipt(self._payload())
        try:
            self.assertEqual(
                explicit_user_approval_errors(
                    manifest=self._manifest(path, digest),
                    research_id=self.research_id,
                ),
                [],
            )
        finally:
            path.unlink(missing_ok=True)

    def test_arbitrary_nonempty_approval_string_is_not_authority(self):
        manifest = {
            "research_id": self.research_id,
            "explicit_user_approval_reference": "ARBITRARY_TEXT_IS_NOT_APPROVAL.json",
            "explicit_user_approval_sha256": "0" * 64,
            "approval_timestamp": self.approved_at,
        }
        errors = explicit_user_approval_errors(manifest=manifest, research_id=self.research_id)
        self.assertIn("explicit_user_approval_receipt_reference_invalid", errors)

    def test_future_dated_approval_is_rejected(self):
        payload = self._payload()
        payload["approved_at"] = "2999-01-01T00:00:00Z"
        path, digest = self._write_receipt(payload)
        try:
            errors = explicit_user_approval_errors(
                manifest=self._manifest(path, digest, payload["approved_at"]),
                research_id=self.research_id,
            )
            self.assertIn("explicit_user_approval_timestamp_future", errors)
        finally:
            path.unlink(missing_ok=True)

    def test_method_binding_drift_is_rejected(self):
        payload = self._payload()
        payload["bound_artifacts"]["need_analysis_plan"]["sha256"] = "0" * 64
        path, digest = self._write_receipt(payload)
        try:
            errors = explicit_user_approval_errors(
                manifest=self._manifest(path, digest),
                research_id=self.research_id,
            )
            self.assertIn("explicit_user_approval_binding_invalid:need_analysis_plan", errors)
        finally:
            path.unlink(missing_ok=True)

    def test_collection_approval_cannot_escalate_to_merge_or_deploy(self):
        payload = self._payload()
        payload["merge_authorized"] = True
        payload["deploy_authorized"] = True
        payload["canonicalization_authorized"] = True
        path, digest = self._write_receipt(payload)
        try:
            errors = explicit_user_approval_errors(
                manifest=self._manifest(path, digest),
                research_id=self.research_id,
            )
            self.assertIn("explicit_user_approval_merge_scope_escalated", errors)
            self.assertIn("explicit_user_approval_deploy_scope_escalated", errors)
            self.assertIn("explicit_user_approval_canonicalization_scope_escalated", errors)
        finally:
            path.unlink(missing_ok=True)

    def test_synthetic_approval_receipt_is_rejected(self):
        payload = self._payload()
        payload["synthetic"] = True
        path, digest = self._write_receipt(payload)
        try:
            errors = explicit_user_approval_errors(
                manifest=self._manifest(path, digest),
                research_id=self.research_id,
            )
            self.assertIn("explicit_user_approval_synthetic_or_unresolved", errors)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
