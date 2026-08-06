from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
import uuid

from .persistence import AtomicJsonStore, AtomicJsonStoreError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TransactionJournalError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransactionRecord:
    id: str
    operation: str
    payload: dict
    status: str
    created_at: str
    updated_at: str
    recovery_attempts: int = 0
    last_error: Optional[str] = None


class TransactionJournal:
    """Durable write-ahead journal for recoverable multi-store operations.

    The journal provides at-least-once replay semantics. Recovery handlers MUST
    therefore be idempotent. Every state transition is performed through one
    lock-scoped read-modify-write operation so concurrent journal instances do
    not overwrite one another's records.
    """

    SCHEMA_VERSION = 1
    VALID_STATES = {"prepared", "committed", "aborted"}

    def __init__(self, path: Path):
        self.path = path
        self.records: Dict[str, dict] = {}
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )
        self.recovered_from_backup = False
        self.load()

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        records = payload.get("records")
        if not isinstance(records, dict):
            raise AtomicJsonStoreError("transaction journal must contain a records object")
        for tx_id, record in records.items():
            if not isinstance(tx_id, str) or not tx_id:
                raise AtomicJsonStoreError("transaction journal has invalid transaction id")
            if not isinstance(record, dict):
                raise AtomicJsonStoreError("transaction record must be an object")
            if record.get("id") != tx_id:
                raise AtomicJsonStoreError("transaction record id mismatch")
            if not isinstance(record.get("operation"), str) or not record["operation"]:
                raise AtomicJsonStoreError("transaction record is missing operation")
            if not isinstance(record.get("payload"), dict):
                raise AtomicJsonStoreError("transaction record payload must be an object")
            if record.get("status") not in cls.VALID_STATES:
                raise AtomicJsonStoreError("transaction record has invalid status")
            if not isinstance(record.get("created_at"), str) or not record["created_at"]:
                raise AtomicJsonStoreError("transaction record is missing created_at")
            if not isinstance(record.get("updated_at"), str) or not record["updated_at"]:
                raise AtomicJsonStoreError("transaction record is missing updated_at")
            attempts = record.get("recovery_attempts", 0)
            if not isinstance(attempts, int) or attempts < 0:
                raise AtomicJsonStoreError("transaction recovery_attempts must be non-negative")
            last_error = record.get("last_error")
            if last_error is not None and not isinstance(last_error, str):
                raise AtomicJsonStoreError("transaction last_error must be a string or null")

    def load(self) -> None:
        try:
            payload = self.store.load({"records": {}})
        except AtomicJsonStoreError as exc:
            raise TransactionJournalError(str(exc)) from exc
        self.records = payload.get("records", {})
        self.recovered_from_backup = self.store.recovered_from_backup

    def _atomic_mutate(self, mutator: Callable[[dict], None]) -> None:
        try:
            committed = self.store.update({"records": {}}, mutator)
        except AtomicJsonStoreError as exc:
            raise TransactionJournalError(str(exc)) from exc
        self.records = committed.get("records", {})
        self.recovered_from_backup = self.store.recovered_from_backup

    def prepare(self, operation: str, payload: dict, *, tx_id: Optional[str] = None) -> str:
        if not isinstance(operation, str) or not operation.strip():
            raise TransactionJournalError("operation must be a non-empty string")
        if not isinstance(payload, dict):
            raise TransactionJournalError("payload must be an object")
        tx_id = tx_id or str(uuid.uuid4())
        now = _utc_now()

        def mutate(state: dict) -> None:
            records = state.setdefault("records", {})
            if tx_id in records:
                raise TransactionJournalError(f"transaction already exists: {tx_id}")
            records[tx_id] = {
                "id": tx_id,
                "operation": operation,
                "payload": payload,
                "status": "prepared",
                "created_at": now,
                "updated_at": now,
                "recovery_attempts": 0,
                "last_error": None,
            }

        self._atomic_mutate(mutate)
        return tx_id

    def _transition(self, tx_id: str, status: str, *, last_error: Optional[str] = None) -> None:
        if status not in self.VALID_STATES:
            raise TransactionJournalError(f"invalid transaction state: {status}")

        def mutate(state: dict) -> None:
            records = state.setdefault("records", {})
            if tx_id not in records:
                raise TransactionJournalError(f"unknown transaction: {tx_id}")
            records[tx_id]["status"] = status
            records[tx_id]["updated_at"] = _utc_now()
            records[tx_id]["last_error"] = last_error

        self._atomic_mutate(mutate)

    def commit(self, tx_id: str) -> None:
        self._transition(tx_id, "committed")

    def abort(self, tx_id: str, reason: Optional[str] = None) -> None:
        self._transition(tx_id, "aborted", last_error=reason)

    def prepared(self) -> List[dict]:
        self.load()
        return [dict(record) for record in self.records.values() if record.get("status") == "prepared"]

    def _record_recovery_failure(self, tx_id: str, error: str) -> None:
        def mutate(state: dict) -> None:
            records = state.setdefault("records", {})
            if tx_id not in records:
                raise TransactionJournalError(f"unknown transaction: {tx_id}")
            record = records[tx_id]
            if record.get("status") != "prepared":
                return
            record["recovery_attempts"] = int(record.get("recovery_attempts", 0)) + 1
            record["updated_at"] = _utc_now()
            record["last_error"] = error

        self._atomic_mutate(mutate)

    def recover(self, handler: Callable[[dict], None]) -> List[str]:
        """Replay prepared records and commit successful recoveries.

        Failed recoveries remain prepared and persist their attempt count/error.
        A competing process may commit a transaction first; commit remains safe
        because state transitions are serialized by the store lock.
        """
        recovered: List[str] = []
        for record in list(self.prepared()):
            tx_id = record["id"]
            try:
                handler(dict(record))
            except Exception as exc:
                self._record_recovery_failure(tx_id, str(exc))
                continue
            self.commit(tx_id)
            recovered.append(tx_id)
        return recovered
