from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .persistence import AtomicJsonStore, AtomicJsonStoreError


class RecoveryEventLedgerError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecoveryEventLedger:
    """Durable append-only audit ledger for recovery and health events.

    Existing events are never edited or removed through this API. Appends use the
    common AtomicJsonStore read-modify-write primitive so concurrent writers do
    not lose previously committed events.
    """

    SCHEMA_VERSION = 1
    EVENT_TYPES = {"recovery", "degradation", "corruption", "pending_transaction"}

    def __init__(
        self,
        path: Path,
        *,
        lock_timeout: float = 10.0,
        stale_lock_after: float = 300.0,
    ):
        self.path = path
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate,
            lock_timeout=lock_timeout,
            stale_lock_after=stale_lock_after,
        )
        try:
            state = self.store.load({"events": []})
        except AtomicJsonStoreError as exc:
            raise RecoveryEventLedgerError(f"cannot load recovery event ledger: {path.name}") from exc
        self.events = list(state.get("events", []))
        self.recovered_from_backup = self.store.recovered_from_backup

    @classmethod
    def _validate(cls, payload: dict) -> None:
        events = payload.get("events")
        if not isinstance(events, list):
            raise AtomicJsonStoreError("recovery ledger events must be a list")
        seen: set[str] = set()
        for event in events:
            if not isinstance(event, dict):
                raise AtomicJsonStoreError("recovery ledger event must be an object")
            event_id = event.get("id")
            if not isinstance(event_id, str) or not event_id:
                raise AtomicJsonStoreError("recovery ledger event id is required")
            if event_id in seen:
                raise AtomicJsonStoreError("recovery ledger event ids must be unique")
            seen.add(event_id)
            if not isinstance(event.get("timestamp"), str) or not event.get("timestamp"):
                raise AtomicJsonStoreError("recovery ledger event timestamp is required")
            if not isinstance(event.get("component"), str) or not event.get("component"):
                raise AtomicJsonStoreError("recovery ledger event component is required")
            if event.get("event_type") not in cls.EVENT_TYPES:
                raise AtomicJsonStoreError("unsupported recovery ledger event type")
            if not isinstance(event.get("status"), str) or not event.get("status"):
                raise AtomicJsonStoreError("recovery ledger event status is required")
            if not isinstance(event.get("details"), dict):
                raise AtomicJsonStoreError("recovery ledger event details must be an object")

    def append(
        self,
        *,
        component: str,
        event_type: str,
        status: str,
        details: Optional[dict] = None,
        timestamp: Optional[str] = None,
    ) -> dict:
        if event_type not in self.EVENT_TYPES:
            raise RecoveryEventLedgerError(f"unsupported recovery event type: {event_type}")
        event = {
            "id": str(uuid4()),
            "timestamp": timestamp or _utc_now(),
            "component": component,
            "event_type": event_type,
            "status": status,
            "details": dict(details or {}),
        }

        def mutate(payload: dict) -> None:
            events = payload.setdefault("events", [])
            events.append(event)

        try:
            committed = self.store.update({"events": []}, mutate)
        except AtomicJsonStoreError as exc:
            raise RecoveryEventLedgerError("cannot append recovery event") from exc
        self.events = list(committed["events"])
        self.recovered_from_backup = self.store.recovered_from_backup
        return dict(event)

    def all(self) -> list[dict]:
        try:
            state = self.store.load({"events": []})
        except AtomicJsonStoreError as exc:
            raise RecoveryEventLedgerError("cannot read recovery event ledger") from exc
        self.events = list(state.get("events", []))
        self.recovered_from_backup = self.store.recovered_from_backup
        return [dict(event) for event in self.events]
