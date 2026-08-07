from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .checkpoints import StoryCheckpointStore
from .models import Source, StoryObject
from .pipeline import generate_article, generate_content_pack, verify_story
from .review import ReviewQueue
from .transactions import TransactionJournal


class OrchestratorError(RuntimeError):
    pass


class Orchestrator:
    STORY_TO_REVIEW = "story_to_review"

    def __init__(
        self,
        state_dir: Path,
        review_queue: Optional[ReviewQueue] = None,
        transaction_journal: Optional[TransactionJournal] = None,
        checkpoint_store: Optional[StoryCheckpointStore] = None,
    ):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.review_queue = review_queue
        self.transaction_journal = transaction_journal
        self.checkpoint_store = checkpoint_store or StoryCheckpointStore(self.state_dir)
        if self.review_queue is not None and self.transaction_journal is None:
            self.transaction_journal = TransactionJournal(self.state_dir / "transactions.json")

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
        self.recover_pending_transactions()
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
