from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict, List, Optional

from .models import StoryObject, utc_now
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class ReviewQueueError(RuntimeError):
    pass


class ReviewQueue:
    """Checksum-protected persistent queue for blocked or review stories.

    Queue lifecycle mirrors the editorial approval terminal states. Resolution is
    audited and idempotent for the same terminal action so transaction replay can
    safely repair a crash between approval-store and queue-store writes.
    """

    # Keep schema 2 for backward compatibility with existing durable queues.
    # The added history field is optional on read and terminal status vocabulary
    # is a backward-compatible extension interpreted only by the new runtime.
    SCHEMA_VERSION = 2
    FINAL_STATUSES = {"approved", "rejected", "revision_required"}
    ALLOWED_STATUSES = {"pending", *FINAL_STATUSES}

    def __init__(self, path: Path):
        self.path = path
        self.items: Dict[str, dict] = {}
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )
        self.recovered_from_backup = False
        self.load()

    @classmethod
    def _validate_payload(cls, payload: dict) -> None:
        items = payload.get("items")
        if not isinstance(items, dict):
            raise AtomicJsonStoreError("review queue must contain an items object")
        for story_id, item in items.items():
            if not isinstance(story_id, str) or not story_id:
                raise AtomicJsonStoreError("review queue has invalid story id")
            if not isinstance(item, dict):
                raise AtomicJsonStoreError("review queue item must be an object")
            story = item.get("story")
            if not isinstance(story, dict):
                raise AtomicJsonStoreError("review queue item is missing story")
            if story.get("id") != story_id:
                raise AtomicJsonStoreError("review queue story id mismatch")
            if not isinstance(item.get("reason"), str) or not item["reason"]:
                raise AtomicJsonStoreError("review queue item is missing reason")
            if item.get("status") not in cls.ALLOWED_STATUSES:
                raise AtomicJsonStoreError("review queue item has invalid status")
            history = item.get("history", [])
            if not isinstance(history, list):
                raise AtomicJsonStoreError("review queue history must be a list")
            for event in history:
                if not isinstance(event, dict):
                    raise AtomicJsonStoreError("review queue history event must be an object")
                if event.get("to") not in cls.ALLOWED_STATUSES:
                    raise AtomicJsonStoreError("review queue history target is invalid")
                for key in ("at", "actor", "reason"):
                    if not isinstance(event.get(key), str) or not event[key]:
                        raise AtomicJsonStoreError("review queue history audit is invalid")
            if history and history[-1].get("to") != item.get("status"):
                raise AtomicJsonStoreError("review queue history/status mismatch")

    def _sync_from_payload(self, payload: dict) -> None:
        self.items = payload.get("items", {})

    def load(self) -> None:
        try:
            payload = self.store.load({"items": {}})
        except AtomicJsonStoreError as exc:
            raise ReviewQueueError(str(exc)) from exc
        self._sync_from_payload(payload)
        self.recovered_from_backup = self.store.recovered_from_backup

    def save(self) -> None:
        try:
            committed = self.store.save({"items": self.items})
        except AtomicJsonStoreError as exc:
            raise ReviewQueueError(str(exc)) from exc
        self._sync_from_payload(committed)

    def enqueue_payload(self, story_id: str, story_payload: dict, reason: str) -> None:
        """Idempotently persist a serialized story for review."""
        if not isinstance(story_id, str) or not story_id:
            raise ReviewQueueError("story_id must be non-empty")
        if not isinstance(story_payload, dict) or story_payload.get("id") != story_id:
            raise ReviewQueueError("story payload id must match story_id")
        if not isinstance(reason, str) or not reason:
            raise ReviewQueueError("review reason must be non-empty")

        def mutate(payload: dict) -> None:
            items = payload.setdefault("items", {})
            existing = items.get(story_id)
            if existing is not None:
                # Transaction replay must never reset a resolved item to pending.
                return
            now = utc_now()
            items[story_id] = {
                "story": copy.deepcopy(story_payload),
                "reason": reason,
                "status": "pending",
                "history": [
                    {"from": None, "to": "pending", "at": now, "actor": "system", "reason": reason}
                ],
            }

        try:
            committed = self.store.update({"items": {}}, mutate)
        except AtomicJsonStoreError as exc:
            raise ReviewQueueError(str(exc)) from exc
        self.recovered_from_backup = self.store.recovered_from_backup
        self._sync_from_payload(committed)

    def enqueue(self, story: StoryObject, reason: str) -> None:
        self.enqueue_payload(story.id, story.to_dict(), reason)

    def resolve(self, story_id: str, *, action: str, actor: str, reason: str) -> dict:
        if action not in self.FINAL_STATUSES:
            raise ReviewQueueError("invalid review queue resolution action")
        actor = actor.strip()
        reason = reason.strip()
        if not actor or not reason:
            raise ReviewQueueError("review queue resolution requires actor and reason")
        captured: dict[str, dict] = {}

        def mutate(payload: dict) -> None:
            item = payload.setdefault("items", {}).get(story_id)
            if item is None:
                raise ReviewQueueError("unknown review queue story")
            current = item.get("status")
            if current == action:
                captured["item"] = copy.deepcopy(item)
                return
            if current != "pending":
                raise ReviewQueueError("review queue item is already resolved differently")
            now = utc_now()
            item["status"] = action
            item.setdefault("history", []).append(
                {"from": "pending", "to": action, "at": now, "actor": actor, "reason": reason}
            )
            captured["item"] = copy.deepcopy(item)

        try:
            committed = self.store.update({"items": {}}, mutate)
        except AtomicJsonStoreError as exc:
            raise ReviewQueueError(str(exc)) from exc
        self.recovered_from_backup = self.store.recovered_from_backup
        self._sync_from_payload(committed)
        return captured["item"]

    def get(self, story_id: str) -> Optional[dict]:
        self.load()
        item = self.items.get(story_id)
        return copy.deepcopy(item) if item is not None else None

    def pending(self) -> List[dict]:
        self.load()
        return [copy.deepcopy(item) for item in self.items.values() if item.get("status") == "pending"]
