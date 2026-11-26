from __future__ import annotations

import copy
import hashlib
import unittest

import nf06_preingest as NF06
import real_batch_synthesis_gate as GATE
from research_storage import canonical_json_bytes
from test_primary_evidence_readiness import (
    ADULT_FORM,
    CHANNELS,
    EMPLOYER_FORM,
    REGIONS,
    approved_method_frame,
    channel_register,
    valid_manifest,
)


def real_records() -> list[dict]:
    records: list[dict] = []
    serial = 0
    for region in REGIONS:
        first, second = CHANNELS[region]
        for form_id, per_channel in (
            (ADULT_FORM, ((first, 20), (second, 20))),
            (EMPLOYER_FORM, ((first, 8), (second, 7))),
        ):
            for channel_id, count in per_channel:
                for _ in range(count):
                    serial += 1
                    records.append(
                        {
                            "research_id": "AI4WORK-STEP-NF-RUN-001",
                            "form_id": form_id,
                            "response_id": hashlib.sha256(f"real-{serial}".encode("utf-8")).hexdigest(),
                            "received_at": "2026-08-23T12:00:00+00:00",
                            "recruitment_channel_id": channel_id,
                            "profile": {"region": region},
                            "synthetic": False,
                        }
                    )
    return records


def bound_collection_frame(register: dict, records: list[dict]) -> dict:
    source_sha = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    register_sha = hashlib.sha256(canonical_json_bytes(register)).hexdigest()
    return {
        "research_id": "AI4WORK-STEP-NF-RUN-001",
        "collection_frame_id": "AI4WORK-CF-PROD-SYNTHESIS-TEST-001",
        "frame_status": "APPROVED_FOR_PROD",
        "evidence_class": "PROD_REAL_EVIDENCE",
        "instrument_versions": {
            ADULT_FORM: 1,
            EMPLOYER_FORM: 1,
        },
        **NF06.instrument_definition_hashes(),
        "collection_started_at": "2026-08-20T00:00:00+00:00",
        "collection_closed_at": "2026-08-27T23:59:59+00:00",
        "collection_channels": sorted(
            {channel_id for pair in CHANNELS.values() for channel_id in pair}
        ),
        "collection_channel_register_sha256": register_sha,
        "source_system": "eucons.ro",
        "source_export_sha256": source_sha,
        "direct_identifiers_collected": False,
        "crm_linkage": "FORBIDDEN",
        "commercial_tracking": "FORBIDDEN",
        "storage_class": "RESEARCH_ONLY_SEPARATE_FROM_CRM",
        "privacy_notice_version": "AI4WORK-PRIVACY-v1",
        "controller_determination_reference": "CTRL-DETERMINATION-001",
        "controller_approval_reference": "CTRL-APPROVAL-001",
        "processor_binding_reference": "PROCESSOR-BINDING-001",
        "server_log_profile_reference": "SERVER-LOG-REVIEW-001",
        "retention_schedule_reference": "RETENTION-APPROVAL-001",
        "production_store_binding_reference": "RESEARCH-STORE-BINDING-001",
    }


def bound_manifest(register: dict, records: list[dict], frame: dict) -> dict:
    manifest = valid_manifest(register)
    manifest["source_export_sha256"] = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    manifest["collection_frame_sha256"] = hashlib.sha256(canonical_json_bytes(frame)).hexdigest()
    manifest["form_contract_sha256"] = frame["form_contract_sha256"]
    manifest["forms_definition_sha256"] = frame["forms_definition_sha256"]
    return manifest


def assert_ready(register: dict, records: list[dict], frame: dict, manifest: dict) -> dict:
    return GATE.assert_real_batch_ready_for_synthesis(
        records,
        manifest=manifest,
        collection_frame=frame,
        method_frame=approved_method_frame(),
        channel_register=register,
    )


class RealBatchSynthesisGateTests(unittest.TestCase):
    def test_valid_real_batch_must_pass_frame_temporal_and_method_gates_together(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        result = assert_ready(register, records, frame, bound_manifest(register, records, frame))
        self.assertTrue(result["ready_for_primary_synthesis"])
        self.assertTrue(result["collection_frame_bound"])
        self.assertTrue(result["collection_frame_window_validated"])
        self.assertTrue(result["collection_frame_channel_membership_validated"])
        self.assertTrue(result["channel_register_bound"])
        self.assertEqual(
            result["channel_register_sha256"],
            frame["collection_channel_register_sha256"],
        )
        self.assertTrue(result["channel_temporal_windows_validated"])
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertEqual(result["evidence_class"], "CONTROL_ARTIFACT_NOT_EVIDENCE")
        self.assertEqual(result["schema_version"], "eucons.ai4work_real_batch_synthesis_gate.v0.2")

    def test_response_before_attributed_channel_open_is_rejected_even_if_frame_allows_it(self):
        register = channel_register()
        records = real_records()
        target = next(row for row in records if row["recruitment_channel_id"] == CHANNELS["Sud-Vest Oltenia"][0])
        target["received_at"] = "2026-08-21T12:00:00+00:00"
        frame = bound_collection_frame(register, records)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, bound_manifest(register, records, frame))

    def test_response_after_attributed_channel_close_is_rejected_even_if_frame_allows_it(self):
        register = channel_register()
        records = real_records()
        target = next(row for row in records if row["recruitment_channel_id"] == CHANNELS["Centru"][0])
        target["received_at"] = "2026-08-26T12:00:00+00:00"
        frame = bound_collection_frame(register, records)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, bound_manifest(register, records, frame))

    def test_record_batch_is_cryptographically_bound_to_manifest_source_export(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        tampered = copy.deepcopy(records)
        tampered[0]["received_at"] = "2026-08-24T12:00:00+00:00"
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, tampered, frame, manifest)

    def test_collection_frame_sha_must_bind_manifest(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        manifest["collection_frame_sha256"] = "0" * 64
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)

    def test_collection_frame_source_export_must_bind_exact_records(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        frame["source_export_sha256"] = "0" * 64
        manifest["collection_frame_sha256"] = hashlib.sha256(canonical_json_bytes(frame)).hexdigest()
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)

    def test_collection_frame_instrument_hashes_must_reconcile_with_manifest(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        manifest["form_contract_sha256"] = "0" * 64
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)

    def test_supplied_channel_register_snapshot_must_match_frozen_hash(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        tampered_register = copy.deepcopy(register)
        tampered_register["entries"][0]["distributor_role"] = "tampered_but_schema_valid_role"
        with self.assertRaisesRegex(
            GATE.RealBatchSynthesisGateError,
            "supplied channel register does not match",
        ):
            assert_ready(tampered_register, records, frame, manifest)

    def test_record_outside_global_collection_frame_is_rejected(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        frame["collection_closed_at"] = "2026-08-22T23:59:59+00:00"
        manifest = bound_manifest(register, records, frame)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)

    def test_used_channel_missing_from_collection_frame_is_rejected(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        frame["collection_channels"] = frame["collection_channels"][:-1]
        manifest = bound_manifest(register, records, frame)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)

    def test_manifest_method_aggregates_must_reconcile_to_bound_records(self):
        register = channel_register()
        records = real_records()
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        first = CHANNELS["Centru"][0]
        second = CHANNELS["Centru"][1]
        manifest["channel_counts"][first] -= 1
        manifest["channel_counts"][second] += 1
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)

    def test_duplicate_response_id_is_rejected_even_when_hashes_are_rebound(self):
        register = channel_register()
        records = real_records()
        records[1]["response_id"] = records[0]["response_id"]
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)

    def test_synthetic_record_is_never_eligible_for_real_synthesis_gate(self):
        register = channel_register()
        records = real_records()
        records[0]["synthetic"] = True
        frame = bound_collection_frame(register, records)
        manifest = bound_manifest(register, records, frame)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            assert_ready(register, records, frame, manifest)


if __name__ == "__main__":
    unittest.main()
