from __future__ import annotations

from pathlib import Path

from .editorial_approval import EditorialApprovalStore
from .editorial_resolution import EditorialResolutionCoordinator
from .review import ReviewQueue
from .transactions import TransactionJournal


class EditorialConsistencyError(RuntimeError):
    pass


class EditorialConsistencyInspector:
    """Read-only consistency inspection across editorial durable stores.

    Approval is the authoritative operator decision. When Review Queue is active,
    every editorial-gate approval case must have a queue item in the same state.
    A temporary mismatch is classified as recoverable only when a prepared
    ``editorial_review_resolution`` transaction exactly covers that case/story
    and targets the authoritative terminal state. Committed transactions must
    already agree with both durable stores.
    """

    def __init__(
        self,
        approval_path: Path,
        review_queue_path: Path,
        transaction_journal_path: Path,
    ) -> None:
        self.approval_path = approval_path
        self.review_queue_path = review_queue_path
        self.transaction_journal_path = transaction_journal_path

    @staticmethod
    def _resolution_transactions(journal: TransactionJournal) -> list[dict]:
        journal.load()
        return [
            dict(record)
            for record in journal.records.values()
            if record.get("operation") == EditorialResolutionCoordinator.OPERATION
        ]

    @staticmethod
    def _matching_prepared(
        records: list[dict], *, case_id: str, story_id: str, action: str
    ) -> list[dict]:
        result = []
        for record in records:
            payload = record.get("payload", {})
            if (
                record.get("status") == "prepared"
                and payload.get("case_id") == case_id
                and payload.get("story_id") == story_id
                and payload.get("action") == action
            ):
                result.append(record)
        return result

    def inspect(self) -> dict:
        approval_store = EditorialApprovalStore(self.approval_path)
        review_queue = ReviewQueue(self.review_queue_path)
        journal = TransactionJournal(self.transaction_journal_path)

        cases = approval_store.list_cases()
        transactions = self._resolution_transactions(journal)
        mismatches: list[dict] = []
        recoverable: list[dict] = []

        for case in cases:
            case_id = case["case_id"]
            story_id = case["story_id"]
            approval_state = case["state"]
            queue_item = review_queue.get(story_id)

            if queue_item is None:
                mismatch = {
                    "type": "missing_review_queue_item",
                    "case_id": case_id,
                    "story_id": story_id,
                    "approval_state": approval_state,
                }
                matching = (
                    self._matching_prepared(
                        transactions,
                        case_id=case_id,
                        story_id=story_id,
                        action=approval_state,
                    )
                    if approval_state in EditorialApprovalStore.FINAL_STATES
                    else []
                )
                if matching:
                    mismatch["transaction_ids"] = [item["id"] for item in matching]
                    recoverable.append(mismatch)
                else:
                    mismatches.append(mismatch)
                continue

            queue_state = queue_item.get("status")
            if queue_state != approval_state:
                mismatch = {
                    "type": "approval_queue_state_mismatch",
                    "case_id": case_id,
                    "story_id": story_id,
                    "approval_state": approval_state,
                    "review_queue_state": queue_state,
                }
                matching = (
                    self._matching_prepared(
                        transactions,
                        case_id=case_id,
                        story_id=story_id,
                        action=approval_state,
                    )
                    if approval_state in EditorialApprovalStore.FINAL_STATES
                    else []
                )
                if matching:
                    mismatch["transaction_ids"] = [item["id"] for item in matching]
                    recoverable.append(mismatch)
                else:
                    mismatches.append(mismatch)

        for record in transactions:
            if record.get("status") not in {"committed", "prepared"}:
                continue
            payload = record.get("payload", {})
            case = approval_store.load_case(payload.get("case_id", ""))
            if case is None:
                mismatches.append(
                    {
                        "type": "transaction_missing_approval_case",
                        "transaction_id": record["id"],
                        "status": record["status"],
                    }
                )
                continue
            if case.get("story_id") != payload.get("story_id"):
                mismatches.append(
                    {
                        "type": "transaction_story_mismatch",
                        "transaction_id": record["id"],
                        "case_id": case["case_id"],
                    }
                )
                continue
            if record.get("status") == "committed":
                expected = payload.get("action")
                queue_item = review_queue.get(case["story_id"])
                if case.get("state") != expected or queue_item is None or queue_item.get("status") != expected:
                    mismatches.append(
                        {
                            "type": "committed_resolution_not_reflected",
                            "transaction_id": record["id"],
                            "case_id": case["case_id"],
                            "expected_state": expected,
                            "approval_state": case.get("state"),
                            "review_queue_state": queue_item.get("status") if queue_item else None,
                        }
                    )

        if mismatches:
            status = "degraded"
        elif recoverable:
            status = "pending_transaction"
        else:
            status = "healthy"
        return {
            "status": status,
            "case_count": len(cases),
            "resolution_transaction_count": len(transactions),
            "mismatch_count": len(mismatches),
            "recoverable_mismatch_count": len(recoverable),
            "mismatches": mismatches,
            "recoverable_mismatches": recoverable,
        }
