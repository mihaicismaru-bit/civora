from __future__ import annotations

from pathlib import Path

from .checkpoints import StoryCheckpointStore
from .orchestrator import Orchestrator
from .review import ReviewQueue
from .story_codec import story_from_dict
from .transactions import TransactionJournal


def resume_approved_story(state_dir: Path, story_id: str, version: int = 1):
    """Resume an approved editorial story after a real process restart.

    The story is reconstructed from the durable ``editorial_review`` checkpoint.
    A fresh Orchestrator then runs startup recovery, including prepared editorial
    transaction replay and cross-store consistency validation, before invoking
    the existing approval re-entry gate.
    """
    state_dir = Path(state_dir)
    checkpoints = StoryCheckpointStore(state_dir)
    payload = checkpoints.load(story_id, version, "editorial_review")
    story = story_from_dict(payload["story"])

    queue = ReviewQueue(state_dir / "review_queue.json")
    journal = TransactionJournal(state_dir / "transactions.json")
    orchestrator = Orchestrator(
        state_dir,
        review_queue=queue,
        transaction_journal=journal,
        checkpoint_store=checkpoints,
    )
    return orchestrator.resume_after_approval(story)
