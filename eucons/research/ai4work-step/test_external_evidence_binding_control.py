from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from external_evidence_binding_control import (
    MANIFEST_PATH,
    _load,
    evidence_binding_errors,
    evaluate_repository_binding,
)


class ExternalEvidenceBindingControlTests(unittest.TestCase):
    def _temporary_attestation(self, payload: dict) -> tuple[Path, str]:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix=".tmp_external_evidence_",
            dir=MANIFEST_PATH.parent,
            delete=False,
        )
        try:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        finally:
            handle.close()
        path = Path(handle.name)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _set_promoted_temp_evidence(
        self, manifest: dict, *, key: str, payload: dict, status: str = "PASS"
    ) -> Path:
        path, digest = self._temporary_attestation(payload)
        manifest["required_external_or_operational_evidence"][key] = {
            "status": status,
            "reference": path.name,
            "sha256": digest,
        }
        return path

    def test_current_repository_bindings_are_truthful_while_open_gates_remain_open(self):
        ready, errors = evaluate_repository_binding()
        self.assertTrue(ready, errors)

    def test_arbitrary_pass_label_cannot_be_promoted(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        manifest["required_external_or_operational_evidence"]["privacy_notice"] = {
            "status": "PASS",
            "reference": "TEST_ONLY_NON_EVIDENCE:privacy_notice",
            "sha256": "0" * 64,
        }
        errors = evidence_binding_errors(manifest)
        self.assertIn("evidence_reference_not_local_immutable:privacy_notice", errors)

    def test_promoted_reference_with_wrong_digest_fails(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        manifest["required_external_or_operational_evidence"]["provider_annex_4_5"]["sha256"] = "0" * 64
        errors = evidence_binding_errors(manifest)
        self.assertIn("evidence_sha256_mismatch:provider_annex_4_5", errors)

    def test_path_traversal_cannot_satisfy_promoted_gate(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        manifest["required_external_or_operational_evidence"]["privacy_notice"] = {
            "status": "APPROVED",
            "reference": "../../README.md",
            "sha256": "0" * 64,
        }
        errors = evidence_binding_errors(manifest)
        self.assertIn("evidence_reference_not_local_immutable:privacy_notice", errors)

    def test_open_gate_may_be_empty_but_partial_binding_is_rejected(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        manifest["required_external_or_operational_evidence"]["privacy_notice"] = {
            "status": "OPEN",
            "reference": "RESEARCH_PRIVACY_NOTICE_DRAFT.md",
            "sha256": None,
        }
        errors = evidence_binding_errors(manifest)
        self.assertIn("open_evidence_partial_binding:privacy_notice", errors)

    def test_existing_frozen_provider_binding_is_hash_verified(self):
        manifest = _load(MANIFEST_PATH)
        item = manifest["required_external_or_operational_evidence"]["provider_annex_4_5"]
        self.assertEqual(item["status"], "FROZEN")
        errors = evidence_binding_errors(manifest)
        self.assertFalse(any(error.endswith(":provider_annex_4_5") for error in errors), errors)

    def test_pass_requires_exact_semantic_evidence_key_binding(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        path = self._set_promoted_temp_evidence(
            manifest,
            key="privacy_notice",
            payload={
                "research_id": manifest["research_id"],
                "evidence_binding_key": "lawful_basis_or_lia",
                "evidence_class": "OPERATIONAL_EVIDENCE",
            },
        )
        try:
            errors = evidence_binding_errors(manifest)
            self.assertIn("promoted_evidence_key_missing_or_mismatch:privacy_notice", errors)
        finally:
            path.unlink(missing_ok=True)

    def test_pass_requires_explicit_research_id_binding(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        path = self._set_promoted_temp_evidence(
            manifest,
            key="privacy_notice",
            payload={
                "evidence_binding_key": "privacy_notice",
                "evidence_class": "OPERATIONAL_EVIDENCE",
            },
        )
        try:
            errors = evidence_binding_errors(manifest)
            self.assertIn(
                "promoted_evidence_research_id_missing_or_mismatch:privacy_notice",
                errors,
            )
        finally:
            path.unlink(missing_ok=True)

    def test_test_twin_cannot_semantically_satisfy_pass_gate(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        path = self._set_promoted_temp_evidence(
            manifest,
            key="privacy_notice",
            payload={
                "research_id": manifest["research_id"],
                "evidence_binding_key": "privacy_notice",
                "evidence_class": "TEST_TWIN_NON_EVIDENCE",
                "synthetic": True,
            },
        )
        try:
            errors = evidence_binding_errors(manifest)
            self.assertIn("promoted_evidence_is_synthetic:privacy_notice", errors)
            self.assertIn(
                "promoted_evidence_non_evidence_marker:privacy_notice:evidence_class",
                errors,
            )
        finally:
            path.unlink(missing_ok=True)

    def test_exact_real_semantic_attestation_can_satisfy_pass_binding(self):
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        path = self._set_promoted_temp_evidence(
            manifest,
            key="privacy_notice",
            payload={
                "research_id": manifest["research_id"],
                "evidence_binding_key": "privacy_notice",
                "evidence_class": "OPERATIONAL_EVIDENCE",
                "synthetic": False,
            },
        )
        try:
            errors = evidence_binding_errors(manifest)
            self.assertFalse(any(error.endswith(":privacy_notice") for error in errors), errors)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()