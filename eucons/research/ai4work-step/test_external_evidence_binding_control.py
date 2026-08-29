from __future__ import annotations

import copy
import json
import unittest

from external_evidence_binding_control import (
    MANIFEST_PATH,
    _load,
    evidence_binding_errors,
    evaluate_repository_binding,
)


class ExternalEvidenceBindingControlTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
