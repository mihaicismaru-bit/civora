from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Callable, List, Optional

from .checkpoints import StoryCheckpointError, StoryCheckpointStore
from .ingestion import SignalStore, SignalStoreError
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

    Probes intentionally instantiate the production stores. This means a health
    inspection may repair a corrupt primary generation from a valid backup, and
    that recovery is surfaced as ``recovered_from_backup`` rather than hidden.
    Corrupt state is never rewritten when no valid backup exists.
    """

    _SEVERITY = {
        "healthy": 0,
        "recovered_from_backup": 1,
        "pending_transaction": 2,
        "degraded": 2,
        "corrupt": 3,
    }
    _CHECKPOINT_RE = re.compile(
        r"^(?P<story_id>.+)_v(?P<version>\d+)_(?P<label>signal|verified|drafted|packaged)\.json$"
    )

    def __init__(
        self,
        *,
        source_registry_path: Optional[Path] = None,
        signal_store_path: Optional[Path] = None,
        review_queue_path: Optional[Path] = None,
        transaction_journal_path: Optional[Path] = None,
        checkpoint_dir: Optional[Path] = None,
    ):
        self.source_registry_path = source_registry_path
        self.signal_store_path = signal_store_path
        self.review_queue_path = review_queue_path
        self.transaction_journal_path = transaction_journal_path
        self.checkpoint_dir = checkpoint_dir

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
            },
        )
        if component.status in {"corrupt", "degraded"}:
            return component
        if component.details.get("prepared_count", 0) > 0:
            return ComponentHealth(
                name=component.name,
                status="pending_transaction",
                details=component.details,
            )
        return component

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

        return RuntimeHealthReport(
            status=self._overall_status(components),
            generated_at=_utc_now(),
            components=components,
        )
