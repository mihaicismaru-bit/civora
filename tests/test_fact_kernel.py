import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.fact_kernel import FactKernelStore, FactKernelStoreError
from civora.models import Evidence, FactKernel, Signal, StoryObject, VerificationStatus


class FactKernelStoreTests(unittest.TestCase):
    def make_story(self, *, grounded=True):
        statement = "Circulația este restricționată temporar în centru."
        evidence = [
            Evidence(
                "source-a",
                statement if grounded else "A fost publicat un anunț despre trafic.",
                confidence=0.95,
            ),
            Evidence(
                "source-b",
                statement if grounded else "Autoritățile monitorizează traficul.",
                confidence=0.90,
            ),
        ]
        signal = Signal(
            title="Trafic restricționat",
            summary="Restricție temporară de trafic.",
            geography=["Râmnicu Vâlcea"],
            source_ids=["source-a", "source-b"],
            public_interest=0.9,
            impact=0.8,
            novelty=0.5,
            utility=0.9,
            factual_risk=0.1,
        )
        kernel = FactKernel(
            confirmed_facts=[statement],
            uncertain_claims=[],
            affected_groups=["șoferi"],
            next_expected_event="Ridicarea restricției.",
            evidence=evidence,
            verification_status=VerificationStatus.VERIFIED,
        )
        return StoryObject(signal=signal, fact_kernel=kernel)

    def test_grounded_kernel_has_deterministic_provenance(self):
        with TemporaryDirectory() as td:
            store = FactKernelStore(Path(td) / "fact_kernels.json")
            story = self.make_story(grounded=True)
            record = store.persist_story(story)
            self.assertEqual(record["revision"], 1)
            self.assertEqual(record["gate"], "grounded")
            self.assertEqual(record["provenance_coverage"], 1.0)
            self.assertEqual(record["independent_source_count"], 2)
            self.assertEqual(
                record["confirmed_facts"][0]["provenance_status"],
                "grounded",
            )
            self.assertEqual(len(record["confirmed_facts"][0]["evidence_ids"]), 2)
            self.assertEqual(store.load_story(story.id)["semantic_hash"], record["semantic_hash"])

    def test_unlinked_confirmed_fact_requires_review(self):
        with TemporaryDirectory() as td:
            store = FactKernelStore(Path(td) / "fact_kernels.json")
            story = self.make_story(grounded=False)
            record = store.persist_story(story)
            self.assertEqual(record["gate"], "needs_review")
            self.assertEqual(record["provenance_coverage"], 0.0)
            self.assertEqual(
                record["confirmed_facts"][0]["provenance_status"],
                "unlinked",
            )
            self.assertEqual(len(store.needs_review()), 1)

    def test_identical_semantic_kernel_is_idempotent(self):
        with TemporaryDirectory() as td:
            store = FactKernelStore(Path(td) / "fact_kernels.json")
            story = self.make_story()
            first = store.persist_story(story)
            second = store.persist_story(story)
            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 1)
            self.assertEqual(store.history_for_story(story.id), [])

    def test_semantic_change_creates_revision_history(self):
        with TemporaryDirectory() as td:
            store = FactKernelStore(Path(td) / "fact_kernels.json")
            story = self.make_story()
            first = store.persist_story(story)
            story.fact_kernel.uncertain_claims.append("Ora exactă a ridicării restricției nu este cunoscută.")
            second = store.persist_story(story)
            history = store.history_for_story(story.id)
            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["revision"], 1)

    def test_backup_recovery_is_visible_in_health(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "fact_kernels.json"
            store = FactKernelStore(path)
            story = self.make_story()
            store.persist_story(story)
            story.fact_kernel.uncertain_claims.append("Detaliu nou.")
            store.persist_story(story)
            path.write_text("{broken", encoding="utf-8")
            recovered = FactKernelStore(path)
            health = recovered.health()
            self.assertEqual(health["status"], "recovered_from_backup")
            self.assertEqual(health["kernel_count"], 1)

    def test_dangling_evidence_reference_fails_closed(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "fact_kernels.json"
            store = FactKernelStore(path)
            story = self.make_story()
            store.persist_story(story)
            payload = json.loads(path.read_text(encoding="utf-8"))
            kernel = next(iter(payload["kernels"].values()))
            kernel["confirmed_facts"][0]["evidence_ids"] = ["missing"]
            payload["checksum"] = store.store.checksum(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")
            path.with_suffix(path.suffix + ".bak").unlink(missing_ok=True)
            with self.assertRaises(FactKernelStoreError):
                FactKernelStore(path).load_story(story.id)


if __name__ == "__main__":
    unittest.main()
