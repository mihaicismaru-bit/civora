from __future__ import annotations

from pathlib import Path

from .editorial_approval import EditorialApprovalError, EditorialApprovalStore
from .review import ReviewQueue, ReviewQueueError
from .transactions import TransactionJournal, TransactionJournalError


class EditorialResolutionError(RuntimeError):
    pass


class EditorialResolutionCoordinator:
    """Crash-recoverable coordinator for approval-store and Review Queue resolution.

    The transaction journal is written first. Approval is the authoritative
    operator decision; Review Queue state is then reconciled idempotently. A
    crash after approval but before queue resolution leaves a prepared journal
    record that can safely be replayed at startup.
    """

    OPERATION = "editorial_review_resolution"

    def __init__(
        self,
        approval_store: EditorialApprovalStore,
        review_queue: ReviewQueue,
        transaction_journal: TransactionJournal,
    ) -> None:
        self.approval_store = approval_store
        self.review_queue = review_queue
        self.transaction_journal = transaction_journal

    @classmethod
    def from_state_dir(cls, state_dir: Path) -> "EditorialResolutionCoordinator":
        return cls(
            EditorialApprovalStore(state_dir / "editorial_approval.json"),
            ReviewQueue(state_dir / "review_queue.json"),
            TransactionJournal(state_dir / "transactions.json"),
        )

    @staticmethod
    def _validate_payload(payload: dict) -> None:
        for key in ("case_id", "story_id", "action", "actor", "reason"):
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise EditorialResolutionError(f"resolution payload {key} is invalid")
        if payload["action"] not in EditorialApprovalStore.FINAL_STATES:
            raise EditorialResolutionError("resolution payload action is invalid")

    def replay_payload(self, payload: dict) -> dict:
        """Idempotently finish one prepared editorial resolution transaction."""
        self._validate_payload(payload)
        case = self.approval_store.load_case(payload["case_id"])
        if case is None:
            raise EditorialResolutionError("unknown approval case")
        if case.get("story_id") != payload["story_id"]:
            raise EditorialResolutionError("approval case/story mismatch")

        if case.get("state") == "pending":
            case = self.approval_store.decide(
                payload["case_id"],
                action=payload["action"],
                actor=payload["actor"],
                reason=payload["reason"],
            )
        elif case.get("state") != payload["action"]:
            raise EditorialResolutionError("approval case resolved differently")

        queue_item = self.review_queue.resolve(
            payload["story_id"],
            action=payload["action"],
            actor=payload["actor"],
            reason=payload["reason"],
        )
        return {"case": case, "review_queue_item": queue_item}

    def decide(self, case_id: str, *, action: str, actor: str, reason: str) -> dict:
        case = self.approval_store.load_case(case_id)
        if case is None:
            raise EditorialResolutionError("unknown approval case")
        if case.get("state") != "pending":
            raise EditorialResolutionError("approval case is already resolved")
        payload = {
            "case_id": case_id,
            "story_id": case["story_id"],
            "action": action,
            "actor": actor.strip(),
            "reason": reason.strip(),
        }
        self._validate_payload(payload)
        tx_id = self.transaction_journal.prepare(self.OPERATION, payload)
        try:
            result = self.replay_payload(payload)
        except (EditorialApprovalError, ReviewQueueError, EditorialResolutionError) as exc:
            # Leave prepared for bounded startup recovery. The durable approval
            # decision may already exist and must not be rolled back silently.
            raise EditorialResolutionError(str(exc)) from exc
        self.transaction_journal.commit(tx_id)
        return {"transaction_id": tx_id, **result}

    def replay_transaction(self, record: dict) -> None:
        if record.get("operation") != self.OPERATION:
            raise EditorialResolutionError("unsupported editorial resolution transaction")
        self.replay_payload(record.get("payload", {}))
