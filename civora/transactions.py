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

    Recovery is bounded. After ``max_recovery_attempts`` failed replays a
    transaction is moved durably to ``dead_letter`` and is no longer retried
    automatically. Dead letters can leave that state only through an explicit,
    audited resolution: ``requeue`` or ``abort``.
    """

    SCHEMA_VERSION = 1
    VALID_STATES = {"prepared", "committed", "aborted", "dead_letter"}
    VALID_RESOLUTION_ACTIONS = {"requeue", "abort"}
    DEFAULT_MAX_RECOVERY_ATTEMPTS = 3

    def __init__(self, path: Path, *, max_recovery_attempts: int = DEFAULT_MAX_RECOVERY_ATTEMPTS):
        if not isinstance(max_recovery_attempts, int) or max_recovery_attempts < 1:
            raise TransactionJournalError("max_recovery_attempts must be a positive integer")
        self.path = path
        self.max_recovery_attempts = max_recovery_attempts
        self.records: Dict[str, dict] = {}
        self.store = AtomicJsonStore(path, schema_version=self.SCHEMA_VERSION, validator=self._validate_payload)
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
            if not isinstance(record, dict) or record.get("id") != tx_id:
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
            history = record.get("resolution_history", [])
            if not isinstance(history, list):
                raise AtomicJsonStoreError("transaction resolution_history must be a list")
            for entry in history:
                if not isinstance(entry, dict):
                    raise AtomicJsonStoreError("transaction resolution history entry must be an object")
                if entry.get("action") not in cls.VALID_RESOLUTION_ACTIONS:
                    raise AtomicJsonStoreError("transaction resolution history has invalid action")
                for field in ("timestamp", "actor", "reason"):
                    if not isinstance(entry.get(field), str) or not entry[field]:
                        raise AtomicJsonStoreError(f"transaction resolution history requires {field}")

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
                "resolution_history": [],
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

    def resolve_dead_letter(self, tx_id: str, action: str, *, actor: str, reason: str) -> dict:
        """Explicitly resolve one dead letter and persist an immutable audit entry.

        ``requeue`` returns the record to ``prepared`` and resets the automatic
        recovery budget. ``abort`` terminates it. The operation is rejected for
        non-dead-letter transactions and requires non-empty actor/reason values.
        """
        if action not in self.VALID_RESOLUTION_ACTIONS:
            raise TransactionJournalError(f"invalid dead-letter resolution action: {action}")
        if not isinstance(actor, str) or not actor.strip():
            raise TransactionJournalError("dead-letter resolution actor is required")
        if not isinstance(reason, str) or not reason.strip():
            raise TransactionJournalError("dead-letter resolution reason is required")
        timestamp = _utc_now()

        def mutate(state: dict) -> None:
            records = state.setdefault("records", {})
            if tx_id not in records:
                raise TransactionJournalError(f"unknown transaction: {tx_id}")
            record = records[tx_id]
            if record.get("status") != "dead_letter":
                raise TransactionJournalError("only dead-letter transactions can be explicitly resolved")
            record.setdefault("resolution_history", []).append({
                "timestamp": timestamp,
                "action": action,
                "actor": actor.strip(),
                "reason": reason.strip(),
            })
            record["updated_at"] = timestamp
            if action == "requeue":
                record["status"] = "prepared"
                record["recovery_attempts"] = 0
                record["last_error"] = None
            else:
                record["status"] = "aborted"
                record["last_error"] = reason.strip()

        self._atomic_mutate(mutate)
        return dict(self.records[tx_id])

    def prepared(self) -> List[dict]:
        self.load()
        return [dict(record) for record in self.records.values() if record.get("status") == "prepared"]

    def dead_letters(self) -> List[dict]:
        self.load()
        return [dict(record) for record in self.records.values() if record.get("status") == "dead_letter"]

    def _record_recovery_failure(self, tx_id: str, error: str) -> bool:
        dead_lettered = False

        def mutate(state: dict) -> None:
            nonlocal dead_lettered
            records = state.setdefault("records", {})
            if tx_id not in records:
                raise TransactionJournalError(f"unknown transaction: {tx_id}")
            record = records[tx_id]
            if record.get("status") != "prepared":
                return
            attempts = int(record.get("recovery_attempts", 0)) + 1
            record["recovery_attempts"] = attempts
            record["updated_at"] = _utc_now()
            record["last_error"] = error
            if attempts >= self.max_recovery_attempts:
                record["status"] = "dead_letter"
                dead_lettered = True

        self._atomic_mutate(mutate)
        return dead_lettered

    def recover(self, handler: Callable[[dict], None]) -> List[str]:
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
