import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.fact_kernel import FactKernelStore
from civora.fact_reconciliation import FactReconciliationStore
from civora.models import Evidence, FactKernel, Signal, StoryObject, VerificationStatus


class FactReconciliationStoreTests(unittest.TestCase):
    def make_story(self):
        statement = "Circulația este restricționată temporar în centru."
        story = StoryObject(
            signal=Signal(
                title="Trafic restricționat",
                summary="Restricție temporară de trafic.",
                geography=["Râmnicu Vâlcea"],
                source_ids=["source-a", "source-b"],
                public_interest=0.9,
                impact=0.8,
                novelty=0.5,
                utility=0.9,
                factual_risk=0.1,
            ),
            fact_kernel=FactKernel(
                confirmed_facts=[statement],
                uncertain_claims=[],
                affected_groups=["șoferi"],
                next_expected_event="Ridicarea restricției.",
                evidence=[
                    Evidence("source-a", statement, confidence=0.80),
                    Evidence("source-b", statement, confidence=0.75),
                ],
                verification_status=VerificationStatus.VERIFIED,
            ),
        )
        return story

    def test_reconciliation_report_is_durable_and_corroborated(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            kernel_store = FactKernelStore(root / "fact_kernels.json")
            reconciliation_store = FactReconciliationStore(
                root / "fact_reconciliation.json"
            )
            story = self.make_story()
            kernel = kernel_store.persist_story(story)
            report = reconciliation_store.persist_kernel(kernel)
            self.assertEqual(report["result"]["gate"], "corroborated")
            assessment = report["result"]["fact_assessments"][0]
            self.assertEqual(assessment["status"], "corroborated")
            self.assertEqual(assessment["independent_source_count"], 2)
            self.assertEqual(
                reconciliation_store.load_story(story.id)["report_id"],
                report["report_id"],
            )

    def test_same_kernel_and_policy_is_idempotent(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            kernel_store = FactKernelStore(root / "fact_kernels.json")
            reconciliation_store = FactReconciliationStore(
                root / "fact_reconciliation.json"
            )
            story = self.make_story()
            kernel = kernel_store.persist_story(story)
            first = reconciliation_store.persist_kernel(kernel)
            second = reconciliation_store.persist_kernel(kernel)
            self.assertEqual(first["report_id"], second["report_id"])
            health = reconciliation_store.health()
            self.assertEqual(health["report_count"], 1)

    def test_new_kernel_revision_creates_new_reconciliation_report(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            kernel_store = FactKernelStore(root / "fact_kernels.json")
            reconciliation_store = FactReconciliationStore(
                root / "fact_reconciliation.json"
            )
            story = self.make_story()
            first_kernel = kernel_store.persist_story(story)
            first_report = reconciliation_store.persist_kernel(first_kernel)
            story.fact_kernel.uncertain_claims.append(
                "Ora exactă de ridicare a restricției nu este confirmată."
            )
            second_kernel = kernel_store.persist_story(story)
            second_report = reconciliation_store.persist_kernel(second_kernel)
            self.assertNotEqual(first_report["report_id"], second_report["report_id"])
            self.assertEqual(second_report["kernel_revision"], 2)
            self.assertEqual(reconciliation_store.health()["report_count"], 2)
            self.assertEqual(
                reconciliation_store.load_story(story.id)["report_id"],
                second_report["report_id"],
            )

    def test_unlinked_fact_report_requires_review(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            kernel_store = FactKernelStore(root / "fact_kernels.json")
            reconciliation_store = FactReconciliationStore(
                root / "fact_reconciliation.json"
            )
            story = self.make_story()
            story.fact_kernel.evidence = [
                Evidence(
                    "source-a",
                    "A fost publicat un anunț despre trafic.",
                    confidence=0.95,
                )
            ]
            kernel = kernel_store.persist_story(story)
            report = reconciliation_store.persist_kernel(kernel)
            self.assertEqual(report["result"]["gate"], "needs_review")
            self.assertEqual(
                report["result"]["fact_assessments"][0]["status"],
                "unsupported",
            )


if __name__ == "__main__":
    unittest.main()
