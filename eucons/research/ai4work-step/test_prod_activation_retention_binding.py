from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prod_activation_gate import (
    COLLECTION_FRAME_PATH,
    CONTRACT_PATH,
    CONTROLLER_PATH,
    DPIA_SCREENING_PATH,
    HERE,
    MANIFEST_PATH,
    _load,
    activation_errors,
)


class ProdActivationRetentionBindingTests(unittest.TestCase):
    def load_artifacts(self):
        return (
            _load(CONTRACT_PATH),
            _load(MANIFEST_PATH),
            _load(CONTROLLER_PATH),
            _load(COLLECTION_FRAME_PATH),
            _load(DPIA_SCREENING_PATH),
        )

    def _temporary_attestation(self, payload: dict) -> tuple[Path, str]:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix=".tmp_prod_retention_evidence_",
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

    def test_promoted_retention_artifact_is_semantically_checked_by_activation(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        manifest = copy.deepcopy(manifest)
        key = "retention_and_deletion"
        path, digest = self._temporary_attestation(
            {
                "research_id": manifest["research_id"],
                "evidence_binding_key": key,
                "evidence_class": "OPERATIONAL_EVIDENCE",
                "synthetic": False,
            }
        )
        try:
            manifest["required_external_or_operational_evidence"][key] = {
                "status": "PASS",
                "reference": path.name,
                "sha256": digest,
            }
            with patch(
                "prod_activation_gate.retention_attestation_errors",
                return_value=["TEST_SENTINEL_RETENTION_SEMANTIC_FAILURE"],
            ) as validator:
                errors = activation_errors(
                    contract=contract,
                    manifest=manifest,
                    controller=controller,
                    collection_frame=frame,
                    dpia_screening=dpia,
                )
            validator.assert_called_once()
            self.assertIn(
                "retention_semantics:TEST_SENTINEL_RETENTION_SEMANTIC_FAILURE",
                errors,
            )
        finally:
            path.unlink(missing_ok=True)

    def test_generic_sha_binding_cannot_bypass_bad_retention_semantics(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        manifest = copy.deepcopy(manifest)
        key = "retention_and_deletion"
        path, digest = self._temporary_attestation(
            {
                "research_id": manifest["research_id"],
                "evidence_binding_key": key,
                "evidence_class": "OPERATIONAL_EVIDENCE",
                "synthetic": False,
            }
        )
        try:
            manifest["required_external_or_operational_evidence"][key] = {
                "status": "APPROVED",
                "reference": path.name,
                "sha256": digest,
            }
            errors = activation_errors(
                contract=contract,
                manifest=manifest,
                controller=controller,
                collection_frame=frame,
                dpia_screening=dpia,
            )
            self.assertTrue(any(item.startswith("retention_semantics:") for item in errors), errors)
            self.assertFalse(
                "external_evidence_binding_invalid:retention_and_deletion" in errors,
                errors,
            )
        finally:
            path.unlink(missing_ok=True)

    def test_current_open_retention_gate_does_not_emit_false_operational_semantic_failure(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertFalse(any(item.startswith("retention_semantics:") for item in errors), errors)
        self.assertIn("external_evidence_status_or_binding_invalid:retention_and_deletion", errors)


if __name__ == "__main__":
    unittest.main()
