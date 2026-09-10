from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prod_activation_gate as gate


class ProdActivationTestTwinSmokeBindingTests(unittest.TestCase):
    def _binding(self, artifact: dict[str, object], *, key: str) -> tuple[dict[str, str], Path, tempfile.TemporaryDirectory[str]]:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        path = root / "attestation.json"
        path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        binding = {
            "status": "PASS",
            "reference": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        return binding, root, tempdir

    def test_dedicated_smoke_requires_and_accepts_synthetic_non_evidence(self) -> None:
        key = "provider_bound_test_twin_smoke"
        artifact = {
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "evidence_binding_key": key,
            "synthetic": True,
            "evidence_class": "TEST_TWIN_NON_EVIDENCE",
        }
        binding, root, tempdir = self._binding(artifact, key=key)
        self.addCleanup(tempdir.cleanup)
        with patch.object(gate, "HERE", root):
            self.assertTrue(
                gate._valid_promoted_local_binding(
                    key=key,
                    value=binding,
                    research_id="AI4WORK-STEP-NF-RUN-001",
                )
            )

    def test_dedicated_smoke_rejects_evidence_like_or_nonsynthetic_artifact(self) -> None:
        key = "provider_bound_test_twin_smoke"
        artifact = {
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "evidence_binding_key": key,
            "synthetic": False,
            "evidence_class": "PROD_REAL_EVIDENCE",
        }
        binding, root, tempdir = self._binding(artifact, key=key)
        self.addCleanup(tempdir.cleanup)
        with patch.object(gate, "HERE", root):
            self.assertFalse(
                gate._valid_promoted_local_binding(
                    key=key,
                    value=binding,
                    research_id="AI4WORK-STEP-NF-RUN-001",
                )
            )

    def test_ordinary_operational_evidence_still_rejects_test_twin(self) -> None:
        key = "privacy_notice"
        artifact = {
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "evidence_binding_key": key,
            "synthetic": True,
            "artifact_class": "TEST_TWIN_NON_EVIDENCE",
        }
        binding, root, tempdir = self._binding(artifact, key=key)
        self.addCleanup(tempdir.cleanup)
        with patch.object(gate, "HERE", root):
            self.assertFalse(
                gate._valid_promoted_local_binding(
                    key=key,
                    value=binding,
                    research_id="AI4WORK-STEP-NF-RUN-001",
                )
            )


if __name__ == "__main__":
    unittest.main()
