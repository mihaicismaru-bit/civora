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

    The journal intentionally provides at-least-once replay semantics. Recovery
    handlers therefore MUST be idempotent. A transaction is persisted as
    ``prepared`` before external state is changed and is moved to ``committed``
    only after the coordinated operation succeeds.
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

    def save(self) -> None:
        try:
            self.store.save({"records": self.records})
        except AtomicJsonStoreError as exc:
            raise TransactionJournalError(str(exc)) from exc

    def prepare(self, operation: str, payload: dict, *, tx_id: Optional[str] = None) -> str:
        if not isinstance(operation, str) or not operation.strip():
            raise TransactionJournalError("operation must be a non-empty string")
        if not isinstance(payload, dict):
            raise TransactionJournalError("payload must be an object")
        tx_id = tx_id or str(uuid.uuid4())
        if tx_id in self.records:
            raise TransactionJournalError(f"transaction already exists: {tx_id}")
        now = _utc_now()
        self.records[tx_id] = {
            "id": tx_id,
            "operation": operation,
            "payload": payload,
            "status": "prepared",
            "created_at": now,
            "updated_at": now,
            "recovery_attempts": 0,
            "last_error": None,
        }
        try:
            self.save()
        except Exception:
            self.records.pop(tx_id, None)
            raise
        return tx_id

    def _transition(self, tx_id: str, status: str, *, last_error: Optional[str] = None) -> None:
        if status not in self.VALID_STATES:
            raise TransactionJournalError(f"invalid transaction state: {status}")
        if tx_id not in self.records:
            raise TransactionJournalError(f"unknown transaction: {tx_id}")
        previous = dict(self.records[tx_id])
        self.records[tx_id]["status"] = status
        self.records[tx_id]["updated_at"] = _utc_now()
        self.records[tx_id]["last_error"] = last_error
        try:
            self.save()
        except Exception:
            self.records[tx_id] = previous
            raise

    def commit(self, tx_id: str) -> None:
        self._transition(tx_id, "committed")

    def abort(self, tx_id: str, reason: Optional[str] = None) -> None:
        self._transition(tx_id, "aborted", last_error=reason)

    def prepared(self) -> List[dict]:
        return [dict(record) for record in self.records.values() if record.get("status") == "prepared"]

    def recover(self, handler: Callable[[dict], None]) -> List[str]:
        """Replay prepared records and commit successful recoveries.

        Failed recoveries remain prepared and persist their attempt count/error,
        making subsequent recovery deterministic and observable.
        """
        recovered: List[str] = []
        for record in list(self.prepared()):
            tx_id = record["id"]
            try:
                handler(dict(record))
            except Exception as exc:
                previous = dict(self.records[tx_id])
                self.records[tx_id]["recovery_attempts"] = previous.get("recovery_attempts", 0) + 1
                self.records[tx_id]["updated_at"] = _utc_now()
                self.records[tx_id]["last_error"] = str(exc)
                try:
                    self.save()
                except Exception:
                    self.records[tx_id] = previous
                    raise
                continue
            self.commit(tx_id)
            recovered.append(tx_id)
        return recovered
