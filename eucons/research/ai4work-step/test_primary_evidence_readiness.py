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
ADULT_FORM = "AI4WORK_ADULTS_V1"
EMPLOYER_FORM = "AI4WORK_EMPLOYERS_V1"
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
        "schema_version": "eucons.ai4work_collection_channel_register.v0.2",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "invitation_catalog": {
            "reference": "RESEARCH_INVITATION_CATALOG_DRAFT.json",
            "sha256": "a" * 64,
        },
        "entries": entries,
    }


def valid_manifest(register: dict) -> dict:
    channel_counts = {}
    region_channel_counts = {}
    form_region_channel_counts = {
        ADULT_FORM: {},
        EMPLOYER_FORM: {},
    }
    for region in REGIONS:
        first, second = CHANNELS[region]
        region_channel_counts[region] = {first: 28, second: 27}
        form_region_channel_counts[ADULT_FORM][region] = {first: 20, second: 20}
        form_region_channel_counts[EMPLOYER_FORM][region] = {first: 8, second: 7}
        channel_counts[first] = 28
        channel_counts[second] = 27

    return {
        "schema_version": "eucons.ai4work_nf06_preingest_manifest.v0.6",
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "evidence_class": "PROD_REAL_EVIDENCE",
        "non_evidence": False,
        "prod_promotion_eligible": True,
        "channel_concentration_aggregates_emitted": True,
        "record_count": 165,
        "form_counts": {
            ADULT_FORM: 120,
            EMPLOYER_FORM: 45,
        },
        "region_counts": {region: 55 for region in REGIONS},
        "form_region_counts": {
            ADULT_FORM: {region: 40 for region in REGIONS},
            EMPLOYER_FORM: {region: 15 for region in REGIONS},
        },
        "region_channel_ids": {region: list(CHANNELS[region]) for region in REGIONS},
        "form_region_channel_ids": {
            ADULT_FORM: {region: list(CHANNELS[region]) for region in REGIONS},
            EMPLOYER_FORM: {region: list(CHANNELS[region]) for region in REGIONS},
        },
        "channel_counts": channel_counts,
        "region_channel_counts": region_channel_counts,
        "form_region_channel_counts": form_region_channel_counts,
        "dominant_channel_share": 28 / 165,
        "region_dominant_channel_share": {region: 28 / 55 for region in REGIONS},
        "form_region_dominant_channel_share": {
            ADULT_FORM: {region: 0.5 for region in REGIONS},
            EMPLOYER_FORM: {region: 8 / 15 for region in REGIONS},
        },
        "collection_channel_register_sha256": hashlib.sha256(canonical_json_bytes(register)).hexdigest(),
    }


def concentrate_centru(manifest: dict) -> set[str]:
    first, second = CHANNELS["Centru"]
    manifest["region_channel_counts"]["Centru"] = {first: 50, second: 5}
    manifest["form_region_channel_counts"][ADULT_FORM]["Centru"] = {first: 36, second: 4}
    manifest["form_region_channel_counts"][EMPLOYER_FORM]["Centru"] = {first: 14, second: 1}
    manifest["channel_counts"][first] = 50
    manifest["channel_counts"][second] = 5
    manifest["region_dominant_channel_share"]["Centru"] = 50 / 55
    manifest["form_region_dominant_channel_share"][ADULT_FORM]["Centru"] = 36 / 40
    manifest["form_region_dominant_channel_share"][EMPLOYER_FORM]["Centru"] = 14 / 15
    manifest["dominant_channel_share"] = 50 / 165
    return {
        "region:Centru",
        f"form_region:{ADULT_FORM}:Centru",
        f"form_region:{EMPLOYER_FORM}:Centru",
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
        self.assertTrue(result["invitation_catalog_binding_shape_validated"])
        self.assertTrue(result["form_audience_channel_scope_validated"])
        self.assertTrue(result["channel_concentration_scopes_validated"])
        self.assertFalse(result["dominant_channel_sensitivity_used"])

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
        manifest["form_region_counts"][ADULT_FORM]["Sud-Vest Oltenia"] = 29
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
        manifest["collection_channel_register_sha256"] = hashlib.sha256(canonical_json_bytes(register)).hexdigest()
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

    def test_legacy_channel_register_v01_is_rejected(self):
        register = channel_register()
        register["schema_version"] = "eucons.ai4work_collection_channel_register.v0.1"
        manifest = valid_manifest(register)
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_invalid_invitation_catalog_binding_shape_is_rejected(self):
        register = channel_register()
        register["invitation_catalog"] = {
            "reference": "../catalog.json",
            "sha256": "a" * 64,
        }
        manifest = valid_manifest(register)
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_invalid_invitation_catalog_digest_is_rejected(self):
        register = channel_register()
        register["invitation_catalog"]["sha256"] = "not-a-sha"
        manifest = valid_manifest(register)
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

    def test_hidden_regional_and_form_region_channel_dominance_requires_exact_scope_sensitivity(self):
        register = channel_register()
        manifest = valid_manifest(register)
        exceeded_scopes = concentrate_centru(manifest)
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )
        incomplete = {
            "status": "PASS",
            "reference": "AI4WORK-CHANNEL-SENSITIVITY-001",
            "sha256": "a" * 64,
            "covered_scopes": ["region:Centru"],
        }
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
                dominant_channel_sensitivity=incomplete,
            )
        result = READY.assert_primary_evidence_ready_for_synthesis(
            manifest,
            method_frame=approved_method_frame(),
            channel_register=register,
            dominant_channel_sensitivity={
                "status": "PASS",
                "reference": "AI4WORK-CHANNEL-SENSITIVITY-001",
                "sha256": "a" * 64,
                "covered_scopes": sorted(exceeded_scopes),
            },
        )
        self.assertTrue(result["dominant_channel_sensitivity_used"])
        self.assertEqual(set(result["dominant_channel_sensitivity_scopes"]), exceeded_scopes)

    def test_channel_count_aggregates_must_reconcile_across_global_region_and_form_region_views(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["region_channel_counts"]["Centru"][CHANNELS["Centru"][0]] += 1
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_declared_dominant_share_must_match_recomputed_counts(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["region_dominant_channel_share"]["Centru"] = 0.9
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_old_manifest_schema_fails_closed(self):
        register = channel_register()
        manifest = valid_manifest(register)
        manifest["schema_version"] = "eucons.ai4work_nf06_preingest_manifest.v0.5"
        with self.assertRaises(READY.PrimaryEvidenceReadinessError):
            READY.assert_primary_evidence_ready_for_synthesis(
                manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )


if __name__ == "__main__":
    unittest.main()
