import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import dape_release


class DapeReleaseTests(unittest.TestCase):
    def inputs(self):
        run_manifest = {
            "run_id": "NF-SYNTH-RELEASE",
            "project_id": "SYNTH-001",
            "closed_checkpoints": ["NF05_GAP_DETECTION", "NF06_PRIMARY_RESEARCH", "NF07_NEED_DISCOVERY", "NF08_NEED_RANKING", "NF09_CAUSAL_MODEL", "NF10_INTERVENTION_TRACEABILITY", "NF11_ADVERSARIAL_QA", "NF12_PACKAGE"],
            "source_snapshot_ids": ["SRC-A@1"],
            "artifact_hashes": {},
            "events": [],
        }
        narrative_pack = {
            "pack_sha256": "p" * 64,
            "release_gate": {"ready_for_narrative": True},
            "claim_ledger": [
                {
                    "need_id": "N1", "rank": 1, "score": 70, "scope": "school",
                    "prohibited_overclaim": "limit",
                    "evidence_refs": [
                        {
                            "evidence_id": "E1", "source": "source", "source_type": "primary_research",
                            "source_url": None, "source_document_id": "DOC1", "territory": "School",
                            "scope": "school", "period": "2023-2024", "tier": "A",
                            "constructs": ["practice_quality"], "direct_measurement": True,
                            "population_snapshot_id": "POP1", "measures": []
                        }
                    ]
                }
            ]
        }
        compiled_analysis = {
            "source_pack_sha256": narrative_pack["pack_sha256"],
            "markdown_sha256": "m" * 64,
            "source_register_sha256": "s" * 64,
            "validation": {"valid": True},
        }
        export_manifest = {
            "source_pack_sha256": narrative_pack["pack_sha256"],
            "source_markdown_sha256": compiled_analysis["markdown_sha256"],
            "source_register_sha256": compiled_analysis["source_register_sha256"],
            "files": {
                "ANALIZA_NEVOI.docx": {"role": "compiled_analysis_docx", "sha256": "a" * 64},
                "SOURCE_REGISTER.docx": {"role": "source_register_docx", "sha256": "b" * 64},
            },
            "docx_validation": {
                "ANALIZA_NEVOI.docx": {"valid": True},
                "SOURCE_REGISTER.docx": {"valid": True},
            },
            "package_zip": {"path": "ANALIZA_NEVOI_PACKAGE.zip", "sha256": "z" * 64},
        }
        return run_manifest, narrative_pack, compiled_analysis, export_manifest

    def test_export_writes_exact_seven_artifacts(self):
        run_manifest, narrative_pack, compiled_analysis, export_manifest = self.inputs()
        with tempfile.TemporaryDirectory() as directory:
            result = dape_release.export_dape_checkpoint(
                run_manifest, narrative_pack, compiled_analysis, export_manifest, Path(directory),
                checkpoint_id="NF-CP12-HANDOFF", project_id="NEEDS-FACTORY", canonical_base_checkpoint="NF-CP11",
            )
            self.assertEqual(result["artifact_count"], 7)
            self.assertEqual(set(result["artifacts"]), set(dape_release.SEVEN_ARTIFACTS))
            self.assertFalse(result["canonical"])
            self.assertEqual(result["state"], "HANDOFF_READY_NOT_CANONICAL")
            for name in dape_release.SEVEN_ARTIFACTS:
                self.assertTrue((Path(directory) / name).exists())
                self.assertEqual(len(result["file_hashes"][name]), 64)

    def test_export_is_deterministic(self):
        inputs = self.inputs()
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = dape_release.export_dape_checkpoint(*inputs, Path(a), checkpoint_id="NF-CP12-HANDOFF", project_id="NEEDS-FACTORY", canonical_base_checkpoint="NF-CP11")
            second = dape_release.export_dape_checkpoint(*inputs, Path(b), checkpoint_id="NF-CP12-HANDOFF", project_id="NEEDS-FACTORY", canonical_base_checkpoint="NF-CP11")
            self.assertEqual(first["file_hashes"], second["file_hashes"])

    def test_release_gate_must_be_ready(self):
        run_manifest, narrative_pack, compiled_analysis, export_manifest = self.inputs()
        narrative_pack["release_gate"]["ready_for_narrative"] = False
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(dape_release.DapeReleaseError):
                dape_release.export_dape_checkpoint(run_manifest, narrative_pack, compiled_analysis, export_manifest, Path(directory), checkpoint_id="NF-X", project_id="NEEDS", canonical_base_checkpoint="NF-CP11")

    def test_nf12_must_be_closed(self):
        run_manifest, narrative_pack, compiled_analysis, export_manifest = self.inputs()
        run_manifest["closed_checkpoints"] = ["NF11_ADVERSARIAL_QA"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(dape_release.DapeReleaseError):
                dape_release.export_dape_checkpoint(run_manifest, narrative_pack, compiled_analysis, export_manifest, Path(directory), checkpoint_id="NF-X", project_id="NEEDS", canonical_base_checkpoint="NF-CP11")

    def test_hash_lineage_mismatch_blocks_handoff(self):
        run_manifest, narrative_pack, compiled_analysis, export_manifest = self.inputs()
        export_manifest["source_markdown_sha256"] = "wrong"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(dape_release.DapeReleaseError):
                dape_release.export_dape_checkpoint(run_manifest, narrative_pack, compiled_analysis, export_manifest, Path(directory), checkpoint_id="NF-X", project_id="NEEDS", canonical_base_checkpoint="NF-CP11")


if __name__ == "__main__":
    unittest.main()
