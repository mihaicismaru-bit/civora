from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .checkpoints import StoryCheckpointStore
from .health import RuntimeHealthReport, UnifiedHealthInspector
from .models import Source, StoryObject
from .pipeline import generate_article, generate_content_pack, verify_story
from .recovery import RecoveryEventLedger
from .review import ReviewQueue
from .transactions import TransactionJournal, TransactionJournalError


class OrchestratorError(RuntimeError):
    pass


class Orchestrator:
    STORY_TO_REVIEW = "story_to_review"
    STARTUP_ALLOWED = {"healthy", "recovered_from_backup"}

    def __init__(
        self,
        state_dir: Path,
        review_queue: Optional[ReviewQueue] = None,
        transaction_journal: Optional[TransactionJournal] = None,
        checkpoint_store: Optional[StoryCheckpointStore] = None,
        health_inspector: Optional[UnifiedHealthInspector] = None,
        recovery_ledger: Optional[RecoveryEventLedger] = None,
        source_registry_path: Optional[Path] = None,
        signal_store_path: Optional[Path] = None,
    ):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.review_queue = review_queue
        self.transaction_journal = transaction_journal
        self.checkpoint_store = checkpoint_store or StoryCheckpointStore(self.state_dir)
        if self.review_queue is not None and self.transaction_journal is None:
            self.transaction_journal = TransactionJournal(self.state_dir / "transactions.json")

        self.source_registry_path = source_registry_path or self.state_dir / "sources.json"
        self.signal_store_path = signal_store_path or self.state_dir / "signals.json"
        self.recovery_ledger = recovery_ledger or RecoveryEventLedger(
            self.state_dir / "recovery_events.json"
        )
        if health_inspector is None:
            health_inspector = UnifiedHealthInspector(
                source_registry_path=self.source_registry_path,
                signal_store_path=self.signal_store_path,
                review_queue_path=getattr(self.review_queue, "path", None),
                transaction_journal_path=getattr(self.transaction_journal, "path", None),
                checkpoint_dir=self.checkpoint_store.state_dir,
                recovery_event_ledger_path=self.recovery_ledger.path,
            )
        self.health_inspector = health_inspector

    def save_checkpoint(self, story: StoryObject, label: str) -> Path:
        return self.checkpoint_store.save(story, label)

    def _replay_transaction(self, record: dict) -> None:
        if record.get("operation") != self.STORY_TO_REVIEW:
            raise OrchestratorError(f"unsupported transaction operation: {record.get('operation')}")
        if self.review_queue is None:
            raise OrchestratorError("review queue is unavailable for transaction replay")

        payload = record.get("payload", {})
        story_id = payload.get("story_id")
        story_payload = payload.get("story")
        reason = payload.get("reason")
        self.review_queue.enqueue_payload(story_id, story_payload, reason)

    def recover_pending_transactions(self) -> list[str]:
        if self.transaction_journal is None:
            return []
        return self.transaction_journal.recover(self._replay_transaction)

    def reconcile_resolution_audit(self) -> list[str]:
        """Repair missing global audit events from durable transaction history.

        Resolution history in the transaction journal is the source of truth for
        operator dead-letter decisions. Mirroring is idempotent, so this method
        is safe on every startup and repairs a crash between the journal write
        and the independent recovery-event-ledger append.
        """
        if self.transaction_journal is None:
            return []
        try:
            return self.transaction_journal.mirror_resolution_events(self.recovery_ledger)
        except TransactionJournalError as exc:
            raise OrchestratorError("startup blocked: resolution audit reconciliation failed") from exc

    def startup_health_gate(self) -> RuntimeHealthReport:
        """Validate and reconcile durable runtime state before accepting new work.

        Startup is fail-closed on corruption. Missing global dead-letter
        resolution audit is reconciled from durable transaction history before
        pending transactions are replayed. The runtime is then inspected again
        and new work is allowed only when the final state is healthy or was
        recovered from a valid backup.
        """
        initial = self.health_inspector.inspect()
        if initial.status == "corrupt":
            raise OrchestratorError("startup blocked: durable runtime state is corrupt")

        self.reconcile_resolution_audit()
        self.recover_pending_transactions()

        final = self.health_inspector.inspect()
        if final.status not in self.STARTUP_ALLOWED:
            raise OrchestratorError(
                f"startup blocked: runtime health remains {final.status} after recovery"
            )
        return final

    def _enqueue_blocked_story(self, story: StoryObject, reason: str) -> None:
        if self.review_queue is None:
            return
        if self.transaction_journal is None:
            raise OrchestratorError("transaction journal is required when review queue is configured")

        payload = {
            "story_id": story.id,
            "story": story.to_dict(),
            "reason": reason,
        }
        tx_id = self.transaction_journal.prepare(self.STORY_TO_REVIEW, payload)
        self.review_queue.enqueue_payload(story.id, payload["story"], reason)
        self.transaction_journal.commit(tx_id)

    def run(self, story: StoryObject, source_map: Dict[str, Source]) -> StoryObject:
        self.startup_health_gate()
        self.save_checkpoint(story, "signal")
        verify_story(story, source_map)
        self.save_checkpoint(story, "verified")
        if story.state.value == "blocked":
            self._enqueue_blocked_story(story, "trust_score_below_threshold")
            return story
        generate_article(story)
        self.save_checkpoint(story, "drafted")
        generate_content_pack(story)
        self.save_checkpoint(story, "packaged")
        return story
