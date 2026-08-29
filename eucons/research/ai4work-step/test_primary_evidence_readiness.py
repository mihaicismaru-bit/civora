from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import primary_evidence_readiness as READY
from research_storage import canonical_json_bytes

ROOT = Path(__file__).resolve().parent
REGIONS = ("Centru", "Sud-Muntenia", "Sud-Vest Oltenia")
CHANNELS = {
    "Centru": ("CH-CENTRU001", "CH-CENTRU002"),
    "Sud-Muntenia": ("CH-MUNTEN01", "CH-MUNTEN02"),
    "Sud-Vest Oltenia": ("CH-OLTENIA1", "CH-OLTENIA2"),
}


def approved_method_frame() -> dict:
    frame = json.loads((ROOT / "COLLECTION_FRAME_DRAFT.json").read_text(encoding="utf-8"))
    frame = copy.deepcopy(frame)
    frame["frame_status"] = "APPROVED_FOR_PROD"
    frame["approval"]["approved"] = True
    frame["approval"]["approved_for_prod"] = True
    frame["nf06_handoff"]["eligible_now"] = True
    return frame


def channel_register() -> dict:
    entries = []
    for region_index, region in enumerate(REGIONS):
        for channel_index, channel_id in enumerate(CHANNELS[region]):
            entries.append(
                {
                    "channel_id": channel_id,
                    "channel_type": "employment_service" if channel_index == 0 else "business_network",
                    "region_scope": [region],
                    "audience_scope": ["adults", "employers"],
                    "invitation_version": "AI4WORK-INVITE-v1",
                    "opened_at": f"2026-08-{20 + region_index:02d}T08:00:00+00:00",
                    "closed_at": f"2026-08-{25 + region_index:02d}T18:00:00+00:00",
                    "distributor_role": "documented_research_disseminator",
                    "non_coercion_confirmed": True,
                }
            )
    return {
        "schema_version": "eucons.ai4work_collection_channel_register.v0.1",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "entries": entries,
    }


def valid_manifest(register: dict) -> dict:
    channel_counts = {channel_id: 27 for pair in CHANNELS.values() for channel_id in pair}
    channel_counts[CHANNELS["Centru"][0]] = 30
    return {
        "schema_version": "eucons.ai4work_nf06_preingest_manifest.v0.5",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "evidence_class": "PROD_REAL_EVIDENCE",
        "non_evidence": False,
        "prod_promotion_eligible": True,
        "record_count": 165,
        "form_counts": {
            "AI4WORK_ADULTS_V1": 120,
            "AI4WORK_EMPLOYERS_V1": 45,
        },
        "form_region_counts": {
            "AI4WORK_ADULTS_V1": {region: 40 for region in REGIONS},
            "AI4WORK_EMPLOYERS_V1": {region: 15 for region in REGIONS},
        },
        "region_channel_ids": {region: list(CHANNELS[region]) for region in REGIONS},
        "form_region_channel_ids": {
            "AI4WORK_ADULTS_V1": {region: [CHANNELS[region][0]] for region in REGIONS},
            "AI4WORK_EMPLOYERS_V1": {region: [CHANNELS[region][1]] for region in REGIONS},
        },
        "channel_counts": channel_counts,
        "dominant_channel_share": 30 / 165,
        "collection_channel_register_sha256": hashlib.sha256(canonical_json_bytes(register)).hexdigest(),
    }


class PrimaryEvidenceReadinessTests(unittest.TestCase):
    def test_real_prod_batch_meeting_frozen_method_thresholds_can_enter_synthesis(self):
        register = channel_register()
        result = READY.assert_primary_evidence_ready_for_synthesis(
            valid_manifest(register),
            method_frame=approved_method_frame(),
            channel_register=register,
        )
        self.assertTrue(result["ready_for_primary_synthesis"])
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertTrue(result["thresholds_are_method_rules_not_evidence"])
        self.assertTrue(result["independent_channel_types_per_region_validated"])
        self.assertTrue(result["form_audience_channel_scope_validated"])

    def test_test_twin_is_rejected_even_with_large_counts(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["evidence_class"] = "TEST_TWIN_NON_EVIDENCE"
        manifest["non_evidence"] = True
        manifest["prod_promotion_eligible"] = False
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_unapproved_method_frame_is_rejected(self):
        register = channel_register()
        draft = json.loads((ROOT / "COLLECTION_FRAME_DRAFT.json").read_text(encoding="utf-8"))
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                valid_manifest(register),
                method_frame=draft,
                channel_register=register,
            )

    def test_population_or_region_below_frozen_threshold_is_rejected(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["form_region_counts"]["AI4WORK_ADULTS_V1"]["Sud-Vest Oltenia"] = 29
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_two_channel_ids_do_not_count_as_independent_when_channel_type_is_same(self):
        register = channel_register()
        for entry in register["entries"]:
            if entry["region_scope"] == ["Centru"]:
                entry["channel_type"] = "employment_service"
        manifest = valid_manifest(register)
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_channel_register_hash_mismatch_is_rejected(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["collection_channel_register_sha256"] = "0" * 64
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_form_channel_must_be_authorised_for_its_actual_audience(self):
        register = channel_register()
        for entry in register["entries"]:
            if entry["channel_id"] == CHANNELS["Centru"][1]:
                entry["audience_scope"] = ["adults"]
        manifest = valid_manifest(register)
        manifest["collection_channel_register_sha256"] = hashlib.sha256(canonical_json_bytes(register)).hexdigest()
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_region_channel_union_must_reconcile_with_form_specific_provenance(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["region_channel_ids"]["Centru"] = [CHANNELS["Centru"][0]]
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_dominant_channel_over_70_percent_requires_documented_sensitivity_pass(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["dominant_channel_share"] = 0.71
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )
        result = READY.assert_primary_evidence_ready_for_synthesis(
            manifest,
            method_frame=approved_method_frame(),
            channel_register=register,
            dominant_channel_sensitivity={
                "status": "PASS",
                "reference": "AI4WORK-CHANNEL-SENSITIVITY-001",
                "sha256": "a" * 64,
            },
        )
        self.assertTrue(result["dominant_channel_sensitivity_used"])


if __name__ == "__main__":
    unittest.main()
