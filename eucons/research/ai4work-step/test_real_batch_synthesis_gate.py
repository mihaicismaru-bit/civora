from __future__ import annotations

import copy
import hashlib
import unittest

import nf06_preingest as NF06
import real_batch_synthesis_gate as GATE
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


def bound_manifest(register: dict, records: list[dict]) -> dict:
    manifest = valid_manifest(register)
    manifest["source_export_sha256"] = hashlib.sha256(NF06.canonical_export_bytes(records)).hexdigest()
    return manifest


class RealBatchSynthesisGateTests(unittest.TestCase):
    def test_valid_real_batch_must_pass_temporal_and_method_gates_together(self):
        register = channel_register()
        records = real_records()
        result = GATE.assert_real_batch_ready_for_synthesis(
            records,
            manifest=bound_manifest(register, records),
            method_frame=approved_method_frame(),
            channel_register=register,
        )
        self.assertTrue(result["ready_for_primary_synthesis"])
        self.assertTrue(result["channel_temporal_windows_validated"])
        self.assertFalse(result["representativeness_claim_allowed"])
        self.assertEqual(result["evidence_class"], "CONTROL_ARTIFACT_NOT_EVIDENCE")

    def test_response_before_attributed_channel_open_is_rejected_even_if_other_controls_pass(self):
        register = channel_register()
        records = real_records()
        target = next(row for row in records if row["recruitment_channel_id"] == CHANNELS["Sud-Vest Oltenia"][0])
        target["received_at"] = "2026-08-21T12:00:00+00:00"
        manifest = bound_manifest(register, records)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            GATE.assert_real_batch_ready_for_synthesis(
                records,
                manifest=manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_response_after_attributed_channel_close_is_rejected(self):
        register = channel_register()
        records = real_records()
        target = next(row for row in records if row["recruitment_channel_id"] == CHANNELS["Centru"][0])
        target["received_at"] = "2026-08-26T12:00:00+00:00"
        manifest = bound_manifest(register, records)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            GATE.assert_real_batch_ready_for_synthesis(
                records,
                manifest=manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_record_batch_is_cryptographically_bound_to_manifest_source_export(self):
        register = channel_register()
        records = real_records()
        manifest = bound_manifest(register, records)
        tampered = copy.deepcopy(records)
        tampered[0]["received_at"] = "2026-08-24T12:00:00+00:00"
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            GATE.assert_real_batch_ready_for_synthesis(
                tampered,
                manifest=manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_manifest_method_aggregates_must_reconcile_to_bound_records(self):
        register = channel_register()
        records = real_records()
        manifest = bound_manifest(register, records)
        first = CHANNELS["Centru"][0]
        second = CHANNELS["Centru"][1]
        manifest["channel_counts"][first] -= 1
        manifest["channel_counts"][second] += 1
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            GATE.assert_real_batch_ready_for_synthesis(
                records,
                manifest=manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )

    def test_synthetic_record_is_never_eligible_for_real_synthesis_gate(self):
        register = channel_register()
        records = real_records()
        records[0]["synthetic"] = True
        manifest = bound_manifest(register, records)
        with self.assertRaises(GATE.RealBatchSynthesisGateError):
            GATE.assert_real_batch_ready_for_synthesis(
                records,
                manifest=manifest,
                method_frame=approved_method_frame(),
                channel_register=register,
            )


if __name__ == "__main__":
    unittest.main()
