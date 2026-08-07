import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.fact_kernel import FactKernelStore
from civora.health import UnifiedHealthInspector
from civora.orchestrator import Orchestrator, OrchestratorError
from civora.recovery import RecoveryEventLedger


class EditorialHealthTests(unittest.TestCase):
    EDITORIAL_COMPONENTS = {
        "fact_kernel",
        "fact_reconciliation",
        "fact_contradictions",
        "editorial_gate",
        "editorial_approval",
    }

    def test_orchestrator_default_health_includes_all_editorial_stores(self):
        with TemporaryDirectory() as td:
            report = Orchestrator(Path(td)).startup_health_gate()
            names = {component.name for component in report.components}

            self.assertEqual(report.status, "healthy")
            self.assertTrue(self.EDITORIAL_COMPONENTS.issubset(names))

    def test_empty_editorial_stores_are_healthy(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            report = UnifiedHealthInspector(
                fact_kernel_path=root / "fact_kernels.json",
                fact_reconciliation_path=root / "fact_reconciliation.json",
                fact_contradiction_path=root / "fact_contradictions.json",
                editorial_gate_path=root / "editorial_gate.json",
                editorial_approval_path=root / "editorial_approval.json",
            ).inspect()

            self.assertEqual(report.status, "healthy")
            self.assertEqual(
                {component.name for component in report.components},
                self.EDITORIAL_COMPONENTS,
            )
            self.assertTrue(all(component.status == "healthy" for component in report.components))

    def test_unrecoverable_fact_kernel_corruption_blocks_startup(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "fact_kernels.json"
            backup = path.with_suffix(path.suffix + ".bak")
            path.write_text("{corrupt-primary", encoding="utf-8")
            backup.write_text("{corrupt-backup", encoding="utf-8")

            with self.assertRaisesRegex(OrchestratorError, "durable runtime state is corrupt"):
                Orchestrator(root).startup_health_gate()

    def test_fact_kernel_backup_recovery_is_visible_and_audited(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "fact_kernels.json"
            store = FactKernelStore(path)
            store.store.save(store.default_payload())
            store.store.save(store.default_payload())
            path.write_text("{corrupt-primary", encoding="utf-8")

            report = Orchestrator(root).startup_health_gate()
            component = next(item for item in report.components if item.name == "fact_kernel")

            self.assertIn(report.status, {"healthy", "recovered_from_backup"})
            self.assertIn(component.status, {"healthy", "recovered_from_backup"})
            events = RecoveryEventLedger(root / "recovery_events.json").all()
            self.assertTrue(
                any(
                    event["component"] == "fact_kernel"
                    and event["event_type"] == "recovery"
                    for event in events
                )
            )

    def test_pending_editorial_approval_is_not_runtime_degradation(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            # A pending approval is editorial work, not durable-state corruption.
            from civora.editorial_approval import EditorialApprovalStore

            store = EditorialApprovalStore(root / "editorial_approval.json")
            decision = {
                "decision_id": "decision-1",
                "story_id": "story-1",
                "kernel_semantic_hash": "a" * 64,
                "decision": "review",
            }
            store.ensure_pending(decision)

            report = UnifiedHealthInspector(
                editorial_approval_path=root / "editorial_approval.json"
            ).inspect()

            self.assertEqual(report.status, "healthy")
            self.assertEqual(report.components[0].status, "healthy")
            self.assertEqual(report.components[0].details["pending_count"], 1)


if __name__ == "__main__":
    unittest.main()
