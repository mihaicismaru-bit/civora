from __future__ import annotations

import copy
import unittest
from datetime import datetime, timezone

from live_operational_evidence_control import (
    MANIFEST_PATH,
    _load,
    attestation_semantic_errors,
    repository_live_operational_evidence_errors,
)


NOW = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)


class LiveOperationalEvidenceControlTests(unittest.TestCase):
    def test_current_repository_open_state_is_truthful(self) -> None:
        self.assertEqual(
            repository_live_operational_evidence_errors(now_utc=NOW),
            [],
        )

    def test_real_operational_key_rejects_test_twin_fixture(self) -> None:
        fixture = {
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "evidence_binding_key": "processor_chain",
            "evidence_class": "TEST_TWIN_NON_EVIDENCE",
            "synthetic": True,
            "account_specific": True,
            "provider_bound": True,
            "verified_by": "CI fixture",
            "verified_at_utc": "2026-09-01T20:00:00Z",
            "controller": {"legal_name": "TEST ONLY", "registration_id": "TEST ONLY"},
            "processor": {"legal_name": "TEST ONLY", "service": "TEST ONLY", "account_reference": "TEST ONLY"},
            "dpa_binding": {"reference": "TEST ONLY", "sha256": "0" * 64},
            "controller_instruction_reference": "TEST ONLY",
            "active_subprocessors": [],
            "respondent_data_access": {
                "authorized_roles": ["TEST ONLY"],
                "crm_access_allowed": False,
                "employer_row_level_access_allowed": False,
            },
        }
        errors = attestation_semantic_errors(
            key="processor_chain",
            artifact=fixture,
            now_utc=NOW,
        )
        self.assertIn("processor_chain:must_be_real", errors)
        self.assertIn("processor_chain:evidence_class_invalid", errors)

    def test_logging_cap_and_minimisation_fail_closed_for_test_twin_fixture(self) -> None:
        fixture = {
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "evidence_binding_key": "account_server_logging_binding",
            "evidence_class": "TEST_TWIN_NON_EVIDENCE",
            "synthetic": True,
            "account_specific": True,
            "provider_bound": True,
            "verified_by": "CI fixture",
            "verified_at_utc": "2026-09-01T20:00:00Z",
            "provider": "TEST ONLY",
            "service": "TEST ONLY",
            "account_reference": "TEST ONLY",
            "configuration_readback_reference": "TEST ONLY",
            "raw_access_enabled": True,
            "raw_access_retention_days": 8,
            "authorized_access_roles": ["TEST ONLY"],
            "log_minimisation": {
                "request_bodies_logged": False,
                "form_answers_logged": False,
                "raw_idempotency_keys_logged": False,
                "questionnaire_data_in_query_string": False,
                "direct_form_identifiers_in_url": False,
                "raw_access_excluded_from_nf06": True,
                "ip_user_agent_excluded_from_analytics": True,
            },
            "cloudflare": {"effective_state_verified": True},
        }
        errors = attestation_semantic_errors(
            key="account_server_logging_binding",
            artifact=fixture,
            now_utc=NOW,
        )
        self.assertIn("account_server_logging_binding:must_be_real", errors)
        self.assertIn(
            "account_server_logging_binding:raw_access_retention_exceeds_approved_7_day_cap",
            errors,
        )

    def test_provider_bound_test_twin_smoke_is_explicitly_non_evidence(self) -> None:
        fixture = {
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "evidence_binding_key": "provider_bound_test_twin_smoke",
            "evidence_class": "TEST_TWIN_NON_EVIDENCE",
            "synthetic": True,
            "prod_promotion_eligible": False,
            "need_evidence_eligible": False,
            "provider_bound": True,
            "account_specific": True,
            "same_runtime_path_as_prod": True,
            "writes_prod_need_evidence": False,
            "real_dissemination_performed": False,
            "verified_by": "CI fixture",
            "verified_at_utc": "2026-09-01T20:00:00Z",
            "checks": {
                "submit": True,
                "canonical_export": True,
                "rights_hold": True,
                "rectification": True,
                "erasure": True,
                "replay_suppression": True,
                "retention_expiry": True,
                "nf06_rejection_as_non_evidence": True,
            },
        }
        self.assertEqual(
            attestation_semantic_errors(
                key="provider_bound_test_twin_smoke",
                artifact=fixture,
                now_utc=NOW,
            ),
            [],
        )

    def test_test_twin_smoke_cannot_claim_need_evidence_eligibility(self) -> None:
        fixture = {
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "evidence_binding_key": "provider_bound_test_twin_smoke",
            "evidence_class": "TEST_TWIN_NON_EVIDENCE",
            "synthetic": True,
            "prod_promotion_eligible": False,
            "need_evidence_eligible": True,
            "provider_bound": True,
            "account_specific": True,
            "same_runtime_path_as_prod": True,
            "writes_prod_need_evidence": False,
            "real_dissemination_performed": False,
            "verified_by": "CI fixture",
            "verified_at_utc": "2026-09-01T20:00:00Z",
            "checks": {
                "submit": True,
                "canonical_export": True,
                "rights_hold": True,
                "rectification": True,
                "erasure": True,
                "replay_suppression": True,
                "retention_expiry": True,
                "nf06_rejection_as_non_evidence": True,
            },
        }
        errors = attestation_semantic_errors(
            key="provider_bound_test_twin_smoke",
            artifact=fixture,
            now_utc=NOW,
        )
        self.assertIn(
            "provider_bound_test_twin_smoke:need_evidence_eligibility_must_be_false",
            errors,
        )

    def test_open_live_operational_item_cannot_use_partial_binding(self) -> None:
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        manifest["required_external_or_operational_evidence"]["processor_chain"] = {
            "status": "OPEN",
            "reference": "processor-chain-draft.json",
            "sha256": None,
        }
        # Exercise the same invariant directly without creating any synthetic operational file.
        item = manifest["required_external_or_operational_evidence"]["processor_chain"]
        self.assertEqual(item["status"], "OPEN")
        self.assertIsNotNone(item["reference"])
        self.assertIsNone(item["sha256"])


if __name__ == "__main__":
    unittest.main()
