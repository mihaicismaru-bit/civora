from __future__ import annotations

import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class RetentionScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schedule = load_json("GDPR_RETENTION_SCHEDULE_DRAFT.json")
        self.contract = load_json("form_contract.json")
        self.activation = load_json("PROD_ACTIVATION_MANIFEST_DRAFT.json")
        self.rows = {
            row["data_class"]: row
            for row in self.schedule.get("schedules", [])
            if isinstance(row, dict) and row.get("data_class")
        }

    def test_schedule_policy_complete_but_prod_still_fail_closed(self) -> None:
        self.assertEqual(self.schedule.get("research_id"), self.contract.get("research_id"))
        self.assertEqual(self.schedule.get("research_id"), self.activation.get("research_id"))
        self.assertEqual(
            self.schedule.get("status"),
            "TECHNICAL_POLICY_COMPLETE_CONTROLLER_ACCEPTANCE_AND_PROVIDER_BINDING_REQUIRED_BEFORE_COLLECTION",
        )
        self.assertIs(self.schedule.get("controller_approval"), False)
        self.assertIs(self.schedule.get("collection_enabled"), False)
        self.assertIs(self.contract.get("production_enabled"), False)
        self.assertEqual(self.contract.get("crm_integration"), "FORBIDDEN")
        self.assertEqual(self.contract.get("commercial_analytics"), "FORBIDDEN")
        retention_gate = (
            self.activation.get("required_external_or_operational_evidence", {})
            .get("retention_and_deletion", {})
        )
        self.assertEqual(retention_gate.get("status"), "OPEN")
        self.assertIsNone(retention_gate.get("reference"))
        self.assertIsNone(retention_gate.get("sha256"))

    def test_logs_and_research_records_have_minimised_non_renewing_lifecycle(self) -> None:
        logs = self.rows["reverse-proxy/application access logs"]
        allowed = str(logs.get("allowed_content", "")).lower()
        self.assertIn("request bodies", allowed)
        self.assertIn("form answers", allowed)
        self.assertIn("raw idempotency-key", allowed)
        self.assertIn("must not be logged", allowed)
        self.assertIn("7 days maximum", str(logs.get("target_retention", "")).lower())
        self.assertIn("verified before collection", str(logs.get("gate", "")).lower())

        analytical = self.rows["raw and normalised analytical respondent records in live research storage"]
        self.assertEqual(analytical.get("store"), "RESEARCH_ANALYTICS_ONLY")
        self.assertEqual(analytical.get("live_store_hard_stop"), "2027-03-31 unless a documented legal claim/audit hold approved by the controller requires a narrower retained subset")
        self.assertIn("180 days", str(analytical.get("retention", "")))
        backup_rule = str(analytical.get("backup_residual_rule", "")).lower()
        self.assertIn("must not be restored into live processing", backup_rule)
        self.assertIn("must expire by provider rotation", backup_rule)
        self.assertIn("without creating a new retention cycle", backup_rule)

        evidence = set(self.schedule.get("deletion_evidence_required", []))
        self.assertTrue(any("counts before and after" in item.lower() for item in evidence))
        self.assertTrue(any("backup schedule" in item.lower() for item in evidence))
        self.assertTrue(any("retention clock" in item.lower() for item in evidence))
        self.assertTrue(any("stale idempotent retry" in item.lower() for item in evidence))

    def test_erasure_replay_marker_is_minimal_non_analytical_and_bounded_to_24h(self) -> None:
        marker = self.rows["erasure replay-suppression markers"]
        self.assertEqual(marker.get("store"), "RESEARCH_RIGHTS_CONTROL_ONLY_NOT_ANALYTICAL")
        content = str(marker.get("content", "")).lower()
        self.assertIn("opaque derived response_id", content)
        self.assertIn("expires_at_utc", content)
        for forbidden in (
            "no questionnaire answers",
            "canonical body digest",
            "raw idempotency-key",
            "identity/contact data",
            "ip",
            "user-agent",
            "device",
            "crm",
            "employer identifier",
        ):
            self.assertIn(forbidden, content)
        self.assertIn("maximum 24 hours", str(marker.get("retention", "")).lower())
        self.assertIn("same-tab/session", str(marker.get("retention_rationale", "")).lower())
        self.assertIn("per-marker", str(marker.get("production_binding_control", "")).lower())
        self.assertIn("FORBIDDEN", str(marker.get("export", "")))
        self.assertIn("collection remains NO_GO", str(marker.get("gate", "")))
        self.assertIn("automatically", str(marker.get("deletion", "")).lower())

    def test_contact_and_test_twin_remain_separate_from_prod_evidence(self) -> None:
        contact = self.rows["optional follow-up contact records"]
        self.assertEqual(contact.get("store"), "RESEARCH_CONTACT_SEPARATE_NO_RESPONSE_LINKAGE")
        self.assertIn("90 days", str(contact.get("retention", "")))
        self.assertIn("no contact identifier is copied to nf06", str(contact.get("post_deletion", "")).lower())

        twin = self.rows["TEST TWIN synthetic dataset"]
        classification = str(twin.get("classification", ""))
        self.assertIn("NON_EVIDENCE", classification)
        self.assertIn("synthetic=true", classification)
        self.assertIn("must never share PROD evidence namespace or promotion path", str(twin.get("separation", "")))

        provider_limit = str(
            self.schedule.get("exceptions", {}).get("processor_backup_limit", "")
        ).lower()
        self.assertIn("annex 5", provider_limit)
        self.assertIn("collection remains no_go", provider_limit)
        replay_extension = str(self.schedule.get("exceptions", {}).get("replay_marker_extension", "")).lower()
        self.assertIn("longer than 24 hours", replay_extension)
        self.assertIn("explicit controller approval", replay_extension)


if __name__ == "__main__":
    unittest.main()
