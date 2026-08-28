from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BINDING_PATH = HERE / "CLAUS_WEB_DOCUMENTARY_BINDING.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProviderDocumentaryBindingTests(unittest.TestCase):
    def test_first_party_provider_package_is_frozen_without_closing_account_binding(self) -> None:
        binding_bytes = BINDING_PATH.read_bytes()
        binding = json.loads(binding_bytes.decode("utf-8"))
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            binding.get("status"),
            "DOCUMENTARY_PROVIDER_BASELINE_FROZEN_ACCOUNT_OVERRIDES_PENDING",
        )
        self.assertEqual(binding.get("evidence_class"), "CONTROL_ARTIFACT_NOT_NEED_EVIDENCE")
        self.assertEqual(
            binding.get("test_twin_policy"),
            "TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE",
        )

        documents = binding.get("documents") or {}
        expected = {
            "dpa_v1_0": (
                253895,
                "40391f30b73a2a20182bc2c1e38b65d515c4d4d65dd2c412b76c0592767d024f",
            ),
            "annex_4": (
                124650,
                "69b5491a9fc4842af858b7e58dec88599025229014346eb466ff762912b32108",
            ),
            "annex_5": (
                112754,
                "09d8c6a95427d4716ffa6dccc0ae5e054a074b3a8a861085c6ad89984d9c485d",
            ),
        }
        self.assertEqual(set(documents), set(expected))
        for key, (size_bytes, digest) in expected.items():
            self.assertEqual(documents[key].get("size_bytes"), size_bytes)
            self.assertEqual(documents[key].get("sha256"), digest)
            self.assertRegex(digest, SHA256_RE)

        gate = (manifest.get("required_external_or_operational_evidence") or {}).get(
            "provider_annex_4_5"
        ) or {}
        self.assertEqual(gate.get("status"), "FROZEN")
        self.assertEqual(gate.get("reference"), "CLAUS_WEB_DOCUMENTARY_BINDING.json")
        self.assertEqual(gate.get("sha256"), hashlib.sha256(binding_bytes).hexdigest())

        effect = binding.get("prod_gate_effect") or {}
        self.assertEqual(effect.get("provider_annex_4_5"), "FROZEN_DOCUMENTARY_BASELINE")
        for key in (
            "processor_chain",
            "server_logging_profile",
            "retention_and_deletion",
            "research_only_store_binding",
            "provider_bound_test_twin_smoke",
        ):
            self.assertTrue(str(effect.get(key) or "").startswith("OPEN"))

        pending = set(binding.get("not_closed_by_this_binding") or [])
        self.assertIn("current_cpanel_raw_access_archive_retention_and_access", pending)
        self.assertIn("any_account_specific_annex_5_override", pending)
        self.assertIn("research_only_store_isolation_encryption_and_access", pending)
        self.assertIn("provider_bound_deletion_and_backup_execution", pending)
        self.assertIn("controller_processor_role_chain", pending)

        self.assertFalse(manifest.get("approved_for_prod"))
        self.assertFalse(manifest.get("collection_enabled"))
        self.assertFalse(manifest.get("real_collection_authorized"))
        self.assertFalse(manifest.get("deploy_authorized"))


if __name__ == "__main__":
    unittest.main()
