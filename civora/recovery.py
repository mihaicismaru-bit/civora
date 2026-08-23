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
    not lose previously committed events. Callers may supply a stable ``event_id``
    to make cross-store reconciliation idempotent: replaying an identical event
    is a no-op, while reusing an id for different content fails closed.

    ``observe_health`` is the state-oriented companion to ``append``. It records
    only real component-health transitions: repeated observations with the same
    status and details are coalesced atomically, while recovery to healthy state
    is persisted so a later recurrence of the same fault remains visible.
    """

    SCHEMA_VERSION = 1
    EVENT_TYPES = {
        "recovery",
        "degradation",
        "corruption",
        "pending_transaction",
        "resolution",
        "health_transition",
    }
    _HEALTH_EVENT_TYPES = {
        "recovery",
        "degradation",
        "corruption",
        "pending_transaction",
        "health_transition",
    }

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
        event_id: Optional[str] = None,
    ) -> dict:
        if event_type not in self.EVENT_TYPES:
            raise RecoveryEventLedgerError(f"unsupported recovery event type: {event_type}")
        event = {
            "id": event_id or str(uuid4()),
            "timestamp": timestamp or _utc_now(),
            "component": component,
            "event_type": event_type,
            "status": status,
            "details": dict(details or {}),
        }
        if not isinstance(event["id"], str) or not event["id"].strip():
            raise RecoveryEventLedgerError("recovery event id must be a non-empty string")

        existing: Optional[dict] = None

        def mutate(payload: dict) -> None:
            nonlocal existing
            events = payload.setdefault("events", [])
            for current in events:
                if current.get("id") != event["id"]:
                    continue
                existing = dict(current)
                if current != event:
                    raise RecoveryEventLedgerError(
                        f"recovery event id already exists with different content: {event['id']}"
                    )
                return
            events.append(event)

        try:
            committed = self.store.update({"events": []}, mutate)
        except AtomicJsonStoreError as exc:
            raise RecoveryEventLedgerError("cannot append recovery event") from exc
        self.events = list(committed["events"])
        self.recovered_from_backup = self.store.recovered_from_backup
        return dict(existing or event)

    def observe_health(
        self,
        *,
        component: str,
        event_type: str,
        status: str,
        details: Optional[dict] = None,
        timestamp: Optional[str] = None,
    ) -> Optional[dict]:
        """Persist a health transition while coalescing repeated observations.

        Initial healthy state is intentionally silent. Once a component has a
        recorded non-healthy observation, a transition back to healthy is stored
        as ``health_transition``. This marker prevents a later recurrence of the
        same fault from being incorrectly suppressed as a duplicate.
        """
        if event_type not in self._HEALTH_EVENT_TYPES:
            raise RecoveryEventLedgerError(f"unsupported health event type: {event_type}")
        if not isinstance(component, str) or not component.strip():
            raise RecoveryEventLedgerError("health observation component is required")
        if not isinstance(status, str) or not status.strip():
            raise RecoveryEventLedgerError("health observation status is required")

        observation_details = dict(details or {})
        created: Optional[dict] = None
        existing: Optional[dict] = None
        observed_at = timestamp or _utc_now()

        def mutate(payload: dict) -> None:
            nonlocal created, existing
            events = payload.setdefault("events", [])
            previous = next(
                (
                    event
                    for event in reversed(events)
                    if event.get("component") == component
                    and event.get("event_type") in self._HEALTH_EVENT_TYPES
                ),
                None,
            )

            if previous is None and status == "healthy":
                return

            effective_type = "health_transition" if status == "healthy" else event_type
            if (
                previous is not None
                and previous.get("event_type") == effective_type
                and previous.get("status") == status
                and previous.get("details") == observation_details
            ):
                existing = dict(previous)
                return

            created = {
                "id": str(uuid4()),
                "timestamp": observed_at,
                "component": component,
                "event_type": effective_type,
                "status": status,
                "details": observation_details,
            }
            events.append(created)

        try:
            committed = self.store.update({"events": []}, mutate)
        except AtomicJsonStoreError as exc:
            raise RecoveryEventLedgerError("cannot record health observation") from exc
        self.events = list(committed["events"])
        self.recovered_from_backup = self.store.recovered_from_backup
        if created is not None:
            return dict(created)
        if existing is not None:
            return dict(existing)
        return None

    def all(self) -> list[dict]:
        try:
            state = self.store.load({"events": []})
        except AtomicJsonStoreError as exc:
            raise RecoveryEventLedgerError("cannot read recovery event ledger") from exc
        self.events = list(state.get("events", []))
        self.recovered_from_backup = self.store.recovered_from_backup
        return [dict(event) for event in self.events]
