from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BINDING_PATH = HERE / "CLAUS_WEB_DOCUMENTARY_BINDING.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
HOSTING_PLAN_PATH = HERE / "HOSTING_BINDING_PLAN.json"
STORAGE_CONTRACT_PATH = HERE / "PROVIDER_STORAGE_CONTRACT.json"
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

    def test_hosting_plan_matches_frozen_provider_baseline_and_keeps_live_facts_open(self) -> None:
        plan = json.loads(HOSTING_PLAN_PATH.read_text(encoding="utf-8"))
        binding_bytes = BINDING_PATH.read_bytes()
        baseline = plan.get("provider_documentary_baseline") or {}

        self.assertEqual(plan.get("schema_version"), "eucons.ai4work_research_hosting_plan.v0.6")
        self.assertEqual(
            baseline.get("status"),
            "FROZEN_FIRST_PARTY_SHARED_HOSTING_PACKAGE",
        )
        self.assertEqual(baseline.get("binding_reference"), BINDING_PATH.name)
        self.assertEqual(baseline.get("binding_sha256"), hashlib.sha256(binding_bytes).hexdigest())

        self.assertEqual(
            (baseline.get("dpa") or {}).get("sha256"),
            "40391f30b73a2a20182bc2c1e38b65d515c4d4d65dd2c412b76c0592767d024f",
        )
        self.assertEqual(
            (baseline.get("annex_4") or {}).get("sha256"),
            "69b5491a9fc4842af858b7e58dec88599025229014346eb466ff762912b32108",
        )
        self.assertEqual(
            (baseline.get("annex_5") or {}).get("sha256"),
            "09d8c6a95427d4716ffa6dccc0ae5e054a074b3a8a861085c6ad89984d9c485d",
        )

        raw_access = baseline.get("raw_access_logging") or {}
        self.assertTrue(raw_access.get("provider_field_set_confirmed"))
        self.assertIn("full URL including query string", raw_access.get("may_include") or [])
        self.assertEqual(
            raw_access.get("current_eucons_cpanel_archive_retention"),
            "OPEN_ACCOUNT_INSPECTION_REQUIRED",
        )
        self.assertEqual(
            raw_access.get("current_eucons_log_access_controls"),
            "OPEN_ACCOUNT_INSPECTION_REQUIRED",
        )

        role = plan.get("role_determination_before_activation") or {}
        self.assertEqual(
            role.get("status"),
            "CONTROLLER_UNRESOLVED_EXTERNAL_ROLE_REQUESTS_WITHDRAWN_FAIL_CLOSED",
        )

        open_gates = plan.get("current_open_operational_gates") or {}
        for key in (
            "controller_and_privacy_contact",
            "lawful_basis_article13_dpia_retention_rights_approval",
            "controller_processor_subprocessor_chain",
            "current_cpanel_raw_access_retention_and_access",
            "account_specific_annex_5_override",
            "research_only_store_isolation_encryption_access",
            "provider_bound_deletion_backup_execution",
            "provider_bound_test_twin_smoke",
            "real_primary_response_batch",
        ):
            self.assertEqual(open_gates.get(key), "OPEN")

        serialized = HOSTING_PLAN_PATH.read_text(encoding="utf-8")
        self.assertNotIn("ANNEX_4_AVAILABLE_ON_REQUEST", serialized)
        self.assertNotIn("EXACT_ANNEX_5_VALUES_OPEN", serialized)
        self.assertFalse((plan.get("authorization") or {}).get("merge"))
        self.assertFalse((plan.get("authorization") or {}).get("deploy"))
        self.assertFalse((plan.get("authorization") or {}).get("real_collection"))

    def test_storage_contract_matches_frozen_provider_baseline_and_does_not_reopen_closed_documentary_gaps(self) -> None:
        contract_text = STORAGE_CONTRACT_PATH.read_text(encoding="utf-8")
        contract = json.loads(contract_text)
        framework = contract.get("candidate_hosting_processor_framework") or {}
        go_no_go = contract.get("go_no_go") or {}

        self.assertEqual(contract.get("schema_version"), "eucons.research_storage_contract.v0.7")
        self.assertFalse(contract.get("production_enabled"))
        self.assertEqual((contract.get("controller") or {}).get("status"), "UNRESOLVED_BEFORE_COLLECTION")
        self.assertEqual(framework.get("documentary_binding_reference"), BINDING_PATH.name)
        self.assertEqual(
            framework.get("dpa_sha256"),
            "40391f30b73a2a20182bc2c1e38b65d515c4d4d65dd2c412b76c0592767d024f",
        )
        self.assertEqual(
            framework.get("annex_4_sha256"),
            "69b5491a9fc4842af858b7e58dec88599025229014346eb466ff762912b32108",
        )
        self.assertEqual(
            framework.get("annex_5_sha256"),
            "09d8c6a95427d4716ffa6dccc0ae5e054a074b3a8a861085c6ad89984d9c485d",
        )
        self.assertIn("full URL including query string", framework.get("raw_access_logging") or "")
        self.assertEqual(
            framework.get("raw_access_current_account_retention"),
            "OPEN_ACCOUNT_INSPECTION_REQUIRED",
        )
        self.assertEqual(
            framework.get("raw_access_current_account_access_controls"),
            "OPEN_ACCOUNT_INSPECTION_REQUIRED",
        )
        self.assertEqual(
            go_no_go.get("hosting_account_contract_and_annexes"),
            "FIRST_PARTY_DPA_ANNEX4_ANNEX5_FROZEN_ACCOUNT_CONFIGURATION_AND_OVERRIDE_OPEN",
        )
        self.assertEqual(
            go_no_go.get("provider_raw_access_field_profile"),
            "CLOSED_FIRST_PARTY_PROVIDER_CONFIRMED",
        )
        self.assertEqual(go_no_go.get("actual_server_log_retention"), "OPEN_ACCOUNT_INSPECTION_REQUIRED")
        self.assertEqual(go_no_go.get("status"), "NO_GO_FOR_REAL_COLLECTION")

        self.assertNotIn("nominal Annex 4 list is available on request", contract_text)
        self.assertNotIn("Annex 5 values are available on request", contract_text)
        self.assertNotIn("OPEN_EXTERNAL_PROVIDER_CONFIRMATION\",\n    \"actual_server_log_retention", contract_text)


if __name__ == "__main__":
    unittest.main()
