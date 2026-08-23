from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Callable, List, Optional

from .checkpoints import StoryCheckpointError, StoryCheckpointStore
from .editorial_approval import EditorialApprovalError, EditorialApprovalStore
from .editorial_consistency import EditorialConsistencyInspector
from .editorial_gate_store import EditorialGateStore, EditorialGateStoreError
from .fact_contradictions import FactContradictionStore, FactContradictionStoreError
from .fact_kernel import FactKernelStore, FactKernelStoreError
from .fact_reconciliation import FactReconciliationStore, FactReconciliationStoreError
from .ingestion import SignalStore, SignalStoreError
from .recovery import RecoveryEventLedger, RecoveryEventLedgerError
from .registry import SourceRegistry, SourceRegistryError
from .review import ReviewQueue, ReviewQueueError
from .transactions import TransactionJournal, TransactionJournalError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    status: str
    details: dict


@dataclass(frozen=True)
class RuntimeHealthReport:
    status: str
    generated_at: str
    components: List[ComponentHealth]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "generated_at": self.generated_at,
            "components": [asdict(component) for component in self.components],
        }


class UnifiedHealthInspector:
    """Build one recovery-aware health view over CIVORA durable state.

    Probes intentionally instantiate production stores. Health inspection can
    therefore repair a corrupt primary generation from a valid backup and report
    that recovery explicitly. Unrecoverable corruption is surfaced fail-closed.

    Editorial stores are part of the same startup integrity boundary as the core
    runtime stores. Pending review/approval work is normal editorial state and
    does not by itself degrade runtime health; malformed or unrecoverable durable
    editorial state does. Cross-store approval/review/transaction consistency is
    also exposed as an explicit component whenever all three paths are configured.
    """

    _SEVERITY = {
        "healthy": 0,
        "recovered_from_backup": 1,
        "pending_transaction": 2,
        "degraded": 2,
        "corrupt": 3,
    }
    _CHECKPOINT_RE = re.compile(
        r"^(?P<story_id>.+)_v(?P<version>\d+)_(?P<label>signal|verified|editorial_review|editorial_approved|drafted|packaged)\.json$"
    )

    def __init__(
        self,
        *,
        source_registry_path: Optional[Path] = None,
        signal_store_path: Optional[Path] = None,
        review_queue_path: Optional[Path] = None,
        transaction_journal_path: Optional[Path] = None,
        checkpoint_dir: Optional[Path] = None,
        recovery_event_ledger_path: Optional[Path] = None,
        fact_kernel_path: Optional[Path] = None,
        fact_reconciliation_path: Optional[Path] = None,
        fact_contradiction_path: Optional[Path] = None,
        editorial_gate_path: Optional[Path] = None,
        editorial_approval_path: Optional[Path] = None,
    ):
        self.source_registry_path = source_registry_path
        self.signal_store_path = signal_store_path
        self.review_queue_path = review_queue_path
        self.transaction_journal_path = transaction_journal_path
        self.checkpoint_dir = checkpoint_dir
        self.recovery_event_ledger_path = recovery_event_ledger_path
        self.fact_kernel_path = fact_kernel_path
        self.fact_reconciliation_path = fact_reconciliation_path
        self.fact_contradiction_path = fact_contradiction_path
        self.editorial_gate_path = editorial_gate_path
        self.editorial_approval_path = editorial_approval_path

    @classmethod
    def _overall_status(cls, components: List[ComponentHealth]) -> str:
        if not components:
            return "healthy"
        worst = max(components, key=lambda item: cls._SEVERITY.get(item.status, 3))
        if cls._SEVERITY.get(worst.status, 3) >= 3:
            return "corrupt"
        if cls._SEVERITY.get(worst.status, 3) >= 2:
            return "degraded"
        if any(item.status == "recovered_from_backup" for item in components):
            return "recovered_from_backup"
        return "healthy"

    @staticmethod
    def _probe_store(
        name: str,
        path: Path,
        factory: Callable[[Path], object],
        expected_errors: tuple[type[Exception], ...],
        details: Callable[[object], dict],
    ) -> ComponentHealth:
        try:
            instance = factory(path)
        except expected_errors as exc:
            return ComponentHealth(
                name=name,
                status="corrupt",
                details={"path": str(path), "error": str(exc)},
            )
        except Exception as exc:
            return ComponentHealth(
                name=name,
                status="degraded",
                details={"path": str(path), "error": str(exc)},
            )
        recovered = bool(getattr(instance, "recovered_from_backup", False))
        payload = {
            "path": str(path),
            "recovered_from_backup": recovered,
            **details(instance),
        }
        return ComponentHealth(
            name=name,
            status="recovered_from_backup" if recovered else "healthy",
            details=payload,
        )

    @staticmethod
    def _probe_domain_store(
        name: str,
        path: Path,
        factory: Callable[[Path], object],
        expected_errors: tuple[type[Exception], ...],
    ) -> ComponentHealth:
        """Probe a durable domain store through its public health contract."""
        try:
            instance = factory(path)
            health = instance.health()
        except expected_errors as exc:
            return ComponentHealth(
                name=name,
                status="corrupt",
                details={"path": str(path), "error": str(exc)},
            )
        except Exception as exc:
            return ComponentHealth(
                name=name,
                status="degraded",
                details={"path": str(path), "error": str(exc)},
            )

        status = health.get("status", "corrupt")
        if status not in {"healthy", "recovered_from_backup", "corrupt"}:
            status = "corrupt"
        details = {"path": str(path), **{key: value for key, value in health.items() if key != "status"}}
        if status == "corrupt" and "error" not in details:
            messages = details.get("details") or []
            if messages:
                details["error"] = messages[0]
        return ComponentHealth(name=name, status=status, details=details)

    def _probe_transactions(self, path: Path) -> ComponentHealth:
        component = self._probe_store(
            "transaction_journal",
            path,
            TransactionJournal,
            (TransactionJournalError,),
            lambda journal: {
                "record_count": len(journal.records),
                "prepared_count": len(
                    [record for record in journal.records.values() if record.get("status") == "prepared"]
                ),
                "dead_letter_count": len(
                    [record for record in journal.records.values() if record.get("status") == "dead_letter"]
                ),
            },
        )
        if component.status in {"corrupt", "degraded"}:
            return component
        if component.details.get("dead_letter_count", 0) > 0:
            return ComponentHealth(component.name, "degraded", component.details)
        if component.details.get("prepared_count", 0) > 0:
            return ComponentHealth(component.name, "pending_transaction", component.details)
        return component

    def _probe_editorial_consistency(self) -> ComponentHealth:
        assert self.editorial_approval_path is not None
        assert self.review_queue_path is not None
        assert self.transaction_journal_path is not None
        try:
            status = EditorialConsistencyInspector(
                self.editorial_approval_path,
                self.review_queue_path,
                self.transaction_journal_path,
            ).inspect()
        except (EditorialApprovalError, ReviewQueueError, TransactionJournalError) as exc:
            return ComponentHealth(
                name="editorial_consistency",
                status="corrupt",
                details={"error": str(exc)},
            )
        except Exception as exc:
            return ComponentHealth(
                name="editorial_consistency",
                status="degraded",
                details={"error": str(exc)},
            )

        component_status = status.get("status", "degraded")
        if component_status not in {"healthy", "pending_transaction", "degraded"}:
            component_status = "degraded"
        details = {key: value for key, value in status.items() if key != "status"}
        details.update(
            {
                "approval_path": str(self.editorial_approval_path),
                "review_queue_path": str(self.review_queue_path),
                "transaction_journal_path": str(self.transaction_journal_path),
            }
        )
        return ComponentHealth("editorial_consistency", component_status, details)

    def _probe_checkpoints(self, directory: Path) -> ComponentHealth:
        directory.mkdir(parents=True, exist_ok=True)
        store = StoryCheckpointStore(directory)
        checked = 0
        recovered = 0
        errors: List[dict] = []

        for path in sorted(directory.glob("*.json")):
            match = self._CHECKPOINT_RE.match(path.name)
            if match is None:
                continue
            checked += 1
            story_id = match.group("story_id")
            version = int(match.group("version"))
            label = match.group("label")
            try:
                if store.recovered_from_backup(story_id, version, label):
                    recovered += 1
            except StoryCheckpointError as exc:
                errors.append({"file": path.name, "error": str(exc)})
            except Exception as exc:
                errors.append({"file": path.name, "error": str(exc)})

        details = {
            "path": str(directory),
            "checkpoint_count": checked,
            "recovered_count": recovered,
        }
        if errors:
            details["errors"] = errors
            return ComponentHealth("story_checkpoints", "corrupt", details)
        if recovered:
            return ComponentHealth("story_checkpoints", "recovered_from_backup", details)
        return ComponentHealth("story_checkpoints", "healthy", details)

    @staticmethod
    def _event_type_for(status: str) -> str:
        return {
            "recovered_from_backup": "recovery",
            "pending_transaction": "pending_transaction",
            "corrupt": "corruption",
            "degraded": "degradation",
            "healthy": "health_transition",
        }.get(status, "degradation")

    def _record_events(self, report: RuntimeHealthReport) -> None:
        if self.recovery_event_ledger_path is None:
            return
        try:
            ledger = RecoveryEventLedger(self.recovery_event_ledger_path)
        except RecoveryEventLedgerError:
            return
        for component in report.components:
            if component.name == "recovery_event_ledger":
                continue
            ledger.observe_health(
                component=component.name,
                event_type=self._event_type_for(component.status),
                status=component.status,
                details=component.details,
                timestamp=report.generated_at,
            )

    def inspect(self) -> RuntimeHealthReport:
        components: List[ComponentHealth] = []

        if self.source_registry_path is not None:
            components.append(
                self._probe_store(
                    "source_registry",
                    self.source_registry_path,
                    SourceRegistry,
                    (SourceRegistryError,),
                    lambda registry: {"source_count": len(registry.all())},
                )
            )
        if self.signal_store_path is not None:
            components.append(
                self._probe_store(
                    "signal_store",
                    self.signal_store_path,
                    SignalStore,
                    (SignalStoreError,),
                    lambda store: {
                        "signal_count": len(store.records),
                        "fingerprint_count": len(store.fingerprints),
                    },
                )
            )
        if self.review_queue_path is not None:
            components.append(
                self._probe_store(
                    "review_queue",
                    self.review_queue_path,
                    ReviewQueue,
                    (ReviewQueueError,),
                    lambda queue: {
                        "item_count": len(queue.items),
                        "pending_count": len(queue.pending()),
                    },
                )
            )
        if self.transaction_journal_path is not None:
            components.append(self._probe_transactions(self.transaction_journal_path))
        if self.checkpoint_dir is not None:
            components.append(self._probe_checkpoints(self.checkpoint_dir))
        if self.fact_kernel_path is not None:
            components.append(
                self._probe_domain_store(
                    "fact_kernel",
                    self.fact_kernel_path,
                    FactKernelStore,
                    (FactKernelStoreError,),
                )
            )
        if self.fact_reconciliation_path is not None:
            components.append(
                self._probe_domain_store(
                    "fact_reconciliation",
                    self.fact_reconciliation_path,
                    FactReconciliationStore,
                    (FactReconciliationStoreError,),
                )
            )
        if self.fact_contradiction_path is not None:
            components.append(
                self._probe_domain_store(
                    "fact_contradictions",
                    self.fact_contradiction_path,
                    FactContradictionStore,
                    (FactContradictionStoreError,),
                )
            )
        if self.editorial_gate_path is not None:
            components.append(
                self._probe_domain_store(
                    "editorial_gate",
                    self.editorial_gate_path,
                    EditorialGateStore,
                    (EditorialGateStoreError,),
                )
            )
        if self.editorial_approval_path is not None:
            components.append(
                self._probe_domain_store(
                    "editorial_approval",
                    self.editorial_approval_path,
                    EditorialApprovalStore,
                    (EditorialApprovalError,),
                )
            )
        if (
            self.editorial_approval_path is not None
            and self.review_queue_path is not None
            and self.transaction_journal_path is not None
        ):
            components.append(self._probe_editorial_consistency())
        if self.recovery_event_ledger_path is not None:
            components.append(
                self._probe_store(
                    "recovery_event_ledger",
                    self.recovery_event_ledger_path,
                    RecoveryEventLedger,
                    (RecoveryEventLedgerError,),
                    lambda ledger: {"event_count": len(ledger.events)},
                )
            )

        report = RuntimeHealthReport(
            status=self._overall_status(components),
            generated_at=_utc_now(),
            components=components,
        )
        self._record_events(report)
        return report
