import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import dape, partener


class PartenerAdapterTests(unittest.TestCase):
    def _checkpoint(self):
        return {
            "schema_version": 3,
            "sources": {
                "SRC-GOOD": {
                    "raw_sha256": "raw-good",
                    "semantic_sha256": "abcdef0123456789abcdef0123456789",
                    "pending_semantic_sha256": None,
                    "last_success": "2026-08-19T12:05:23Z",
                    "last_observed": "2026-08-19T12:05:23Z",
                    "health": "PASS",
                    "quarantined": False,
                    "final_url": "https://example.test/good",
                },
                "SRC-PENDING": {
                    "raw_sha256": "raw-pending",
                    "semantic_sha256": "11111111111111111111111111111111",
                    "pending_semantic_sha256": "22222222222222222222222222222222",
                    "last_success": "2026-08-19T11:00:00Z",
                    "last_observed": "2026-08-19T12:00:00Z",
                    "health": "PASS",
                    "quarantined": False,
                    "final_url": "https://example.test/pending",
                },
                "SRC-BAD": {
                    "raw_sha256": None,
                    "semantic_sha256": None,
                    "pending_semantic_sha256": None,
                    "last_success": None,
                    "last_observed": "2026-08-19T12:00:00Z",
                    "health": "FAIL",
                    "quarantined": True,
                    "final_url": None,
                },
            },
        }

    def test_pass_source_returns_stable_receipt(self):
        receipt = partener.material_fact_receipt(self._checkpoint(), "SRC-GOOD")
        self.assertEqual(receipt["material_fact_state"], "STABLE_LAST_KNOWN_GOOD")
        self.assertTrue(receipt["source_snapshot_id"].startswith("SRC-GOOD@"))
        self.assertFalse(receipt["pending_change"])

    def test_pending_semantic_change_does_not_replace_last_known_good(self):
        receipt = partener.material_fact_receipt(self._checkpoint(), "SRC-PENDING")
        self.assertEqual(receipt["semantic_sha256"], "11111111111111111111111111111111")
        self.assertEqual(receipt["pending_semantic_sha256"], "22222222222222222222222222222222")
        self.assertEqual(receipt["material_fact_state"], "LAST_KNOWN_GOOD_PENDING_RECONCILIATION")

    def test_quarantined_failed_source_is_rejected(self):
        with self.assertRaises(partener.PartenerSourceError):
            partener.material_fact_receipt(self._checkpoint(), "SRC-BAD")

    def test_provenance_is_attached_without_overwriting_explicit_evidence_url(self):
        evidence = {"id": "E1", "source_url": "https://evidence.test/original"}
        enriched = partener.attach_partener_provenance(evidence, self._checkpoint(), "SRC-GOOD")
        self.assertEqual(enriched["source_url"], "https://evidence.test/original")
        self.assertEqual(enriched["partener_source"]["health"], "PASS")


class DapeAdapterTests(unittest.TestCase):
    def _run_manifest(self):
        return {
            "run_id": "NF-abc123",
            "project_id": "310224",
            "source_snapshot_ids": ["SRC-A@1", "SRC-B@2"],
            "closed_checkpoints": ["NF07_NEED_DISCOVERY", "NF11_ADVERSARIAL_QA", "NF12_PACKAGE"],
            "artifact_hashes": {
                "NARRATIVE_READY_PACK.json": "packhash",
                "RELEASE_GATE.json": "gatehash",
            },
        }

    def test_handoff_preserves_single_control_plane_and_seven_artifact_contract(self):
        handoff = dape.build_handoff_package(
            self._run_manifest(),
            checkpoint_id="NF-CP07-DAPE-HANDOFF",
            project_id="NEEDS-FACTORY",
            scope="Integrate Needs Factory as a domain-specific consumer of the canonical DAPE control plane.",
            artifact_roles={
                "NARRATIVE_READY_PACK.json": "narrative_ready_pack",
                "RELEASE_GATE.json": "qa_release_gate",
            },
            canonical_base_checkpoint="NF-CP06",
            checkpoint_root="checkpoints/NF-CP07-dape-handoff",
        )
        self.assertEqual(len(handoff["required_checkpoint_artifacts"]), 7)
        self.assertEqual(handoff["checkpoint_manifest"]["classification"], "DOMAIN_SPECIFIC")
        self.assertTrue(handoff["checkpoint_manifest"]["integration"]["single_control_plane_preserved"])
        self.assertFalse(handoff["checkpoint_manifest"]["separation_guards"]["generic_duplication_allowed"])
        self.assertFalse(handoff["canonical"])
        bundle = {item["path"]: item for item in handoff["artifact_bundle"]["artifacts"]}
        self.assertEqual(bundle["NARRATIVE_READY_PACK.json"]["sha256"], "packhash")

    def test_dape_validation_is_pending_without_nf11(self):
        manifest = self._run_manifest()
        manifest["closed_checkpoints"] = ["NF07_NEED_DISCOVERY"]
        checkpoint = dape.build_checkpoint_manifest(
            manifest,
            checkpoint_id="NF-X",
            project_id="NEEDS-FACTORY",
            scope="test",
            required_artifact_paths={},
        )
        self.assertEqual(checkpoint["validation"]["result"], "PENDING")


if __name__ == "__main__":
    unittest.main()
