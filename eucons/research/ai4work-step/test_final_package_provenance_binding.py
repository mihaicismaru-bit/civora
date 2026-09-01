from __future__ import annotations

import copy
import hashlib
import io
import json
import unittest
import zipfile

import final_package_provenance_binding as BINDING
import source_register_provenance_control as PROVENANCE
import test_final_needs_package_gate as FIX
from research_storage import RESEARCH_ID, canonical_json_bytes

TEST_TWIN_FIXTURES_NON_EVIDENCE = True


def source_snapshot() -> bytes:
    return b"AI4WORK TEST TWIN SOURCE SNAPSHOT NON-EVIDENCE v1\n"


def provenance_manifest(register: dict) -> dict:
    payload = source_snapshot()
    return {
        "schema_version": PROVENANCE.SCHEMA,
        "research_id": RESEARCH_ID,
        "source_register_sha256": hashlib.sha256(canonical_json_bytes(register)).hexdigest(),
        "test_twin_evidence_eligible": False,
        "entries": [
            {
                "source_id": "S99",
                "source_type": "INSTITUTIONAL_RESEARCH_OR_EVALUATION",
                "source_reference": "https://example.invalid/test-twin-non-evidence",
                "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
                "verified_at": "2026-08-31T00:00:00+00:00",
                "status": PROVENANCE.TEST_PROVENANCE_STATUS,
                "synthetic": True,
                "evidence_eligible": False,
            }
        ],
    }


def snapshots() -> dict[str, bytes]:
    return {"S99": source_snapshot()}


def prod_shaped_records() -> list[dict]:
    result = copy.deepcopy(FIX.records())
    for record in result:
        record["synthetic"] = False
    return result


def prod_shaped_source_register() -> dict:
    register = copy.deepcopy(FIX.source_register())
    register["status"] = "VERIFIED_FOR_FINAL_PACKAGE"
    return register


class FinalPackageProvenanceBindingTests(unittest.TestCase):
    def test_test_twin_builds_deterministic_outer_package_and_remains_non_evidence(self):
        self.assertTrue(TEST_TWIN_FIXTURES_NON_EVIDENCE)
        register = FIX.source_register()
        manifest = provenance_manifest(register)
        first = BINDING.build_provenance_bound_final_package(
            FIX.records(),
            ranking_result=FIX.ranking(),
            adversarial_qa_result=FIX.qa(),
            source_register=register,
            source_provenance_manifest=manifest,
            source_snapshot_bytes_by_source_id=snapshots(),
            evidence_mode=BINDING.TEST_MODE,
        )
        second = BINDING.build_provenance_bound_final_package(
            FIX.records(),
            ranking_result=FIX.ranking(),
            adversarial_qa_result=FIX.qa(),
            source_register=register,
            source_provenance_manifest=manifest,
            source_snapshot_bytes_by_source_id=snapshots(),
            evidence_mode=BINDING.TEST_MODE,
        )
        binding, package_bytes = first
        self.assertEqual(package_bytes, second[1])
        self.assertEqual(binding["evidence_class"], BINDING.TEST_MODE)
        self.assertFalse(binding["prod_promotion_allowed"])
        self.assertFalse(binding["public_release_authorized"])
        self.assertFalse(binding["test_twin_evidence_eligible"])
        self.assertTrue(binding["direct_base_package_release_without_this_binding_forbidden"])
        self.assertEqual(binding["verified_source_count"], 1)

        with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "BASE_FINAL_NEEDS_PACKAGE.zip",
                    "SOURCE_REGISTER_PROVENANCE.json",
                    "SOURCE_REGISTER_PROVENANCE_VERIFICATION.json",
                    "FINAL_PACKAGE_PROVENANCE_BINDING.json",
                },
            )
            embedded = json.loads(archive.read("FINAL_PACKAGE_PROVENANCE_BINDING.json"))
            self.assertFalse(embedded["public_release_authorized"])
            self.assertFalse(embedded["prod_promotion_allowed"])
            self.assertNotIn("response_id", archive.read("FINAL_PACKAGE_PROVENANCE_BINDING.json").decode("utf-8"))

    def test_tampered_captured_source_bytes_fail_closed_before_packaging(self):
        register = FIX.source_register()
        with self.assertRaisesRegex(BINDING.FinalPackageProvenanceBindingError, "snapshot SHA-256 mismatch"):
            BINDING.build_provenance_bound_final_package(
                FIX.records(),
                ranking_result=FIX.ranking(),
                adversarial_qa_result=FIX.qa(),
                source_register=register,
                source_provenance_manifest=provenance_manifest(register),
                source_snapshot_bytes_by_source_id={"S99": b"tampered TEST TWIN bytes"},
                evidence_mode=BINDING.TEST_MODE,
            )

    def test_missing_captured_source_bytes_fail_closed(self):
        register = FIX.source_register()
        with self.assertRaisesRegex(BINDING.FinalPackageProvenanceBindingError, "captured source snapshot bytes are required"):
            BINDING.build_provenance_bound_final_package(
                FIX.records(),
                ranking_result=FIX.ranking(),
                adversarial_qa_result=FIX.qa(),
                source_register=register,
                source_provenance_manifest=provenance_manifest(register),
                source_snapshot_bytes_by_source_id={},
                evidence_mode=BINDING.TEST_MODE,
            )

    def test_prod_shaped_base_inputs_cannot_reach_release_boundary_without_real_provenance(self):
        register = prod_shaped_source_register()
        test_manifest = provenance_manifest(FIX.source_register())
        with self.assertRaises(BINDING.FinalPackageProvenanceBindingError):
            BINDING.build_provenance_bound_final_package(
                prod_shaped_records(),
                ranking_result=FIX.ranking(),
                adversarial_qa_result=FIX.qa(),
                source_register=register,
                source_provenance_manifest=test_manifest,
                source_snapshot_bytes_by_source_id=snapshots(),
                evidence_mode=BINDING.PROD_MODE,
            )

    def test_source_register_hash_drift_fails_closed(self):
        register = FIX.source_register()
        manifest = provenance_manifest(register)
        drifted = copy.deepcopy(register)
        drifted["entries"][0]["title"] = "drifted TEST TWIN title"
        with self.assertRaisesRegex(BINDING.FinalPackageProvenanceBindingError, "source provenance verification failed"):
            BINDING.build_provenance_bound_final_package(
                FIX.records(),
                ranking_result=FIX.ranking(),
                adversarial_qa_result=FIX.qa(),
                source_register=drifted,
                source_provenance_manifest=manifest,
                source_snapshot_bytes_by_source_id=snapshots(),
                evidence_mode=BINDING.TEST_MODE,
            )


if __name__ == "__main__":
    unittest.main()
