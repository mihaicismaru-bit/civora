from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .models import StoryObject
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class ReviewQueueError(RuntimeError):
    pass


class ReviewQueue:
    """Checksum-protected persistent queue for blocked or review stories."""

    SCHEMA_VERSION = 2

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

    @staticmethod
    def _validate_payload(payload: dict) -> None:
        items = payload.get("items")
        if not isinstance(items, dict):
            raise AtomicJsonStoreError("review queue must contain an items object")
        for story_id, item in items.items():
            if not isinstance(story_id, str) or not story_id:
                raise AtomicJsonStoreError("review queue has invalid story id")
            if not isinstance(item, dict):
                raise AtomicJsonStoreError("review queue item must be an object")
            if not isinstance(item.get("story"), dict):
                raise AtomicJsonStoreError("review queue item is missing story")
            if not isinstance(item.get("reason"), str) or not item["reason"]:
                raise AtomicJsonStoreError("review queue item is missing reason")
            if item.get("status") not in {"pending", "approved", "rejected"}:
                raise AtomicJsonStoreError("review queue item has invalid status")

    def load(self) -> None:
        try:
            payload = self.store.load({"items": {}})
        except AtomicJsonStoreError as exc:
            raise ReviewQueueError(str(exc)) from exc
        self.items = payload.get("items", {})
        self.recovered_from_backup = self.store.recovered_from_backup

    def save(self) -> None:
        try:
            self.store.save({"items": self.items})
        except AtomicJsonStoreError as exc:
            raise ReviewQueueError(str(exc)) from exc

    def enqueue(self, story: StoryObject, reason: str) -> None:
        previous = self.items.get(story.id)
        self.items[story.id] = {
            "story": story.to_dict(),
            "reason": reason,
            "status": "pending",
        }
        try:
            self.save()
        except Exception:
            if previous is None:
                self.items.pop(story.id, None)
            else:
                self.items[story.id] = previous
            raise

    def pending(self) -> List[dict]:
        return [item for item in self.items.values() if item.get("status") == "pending"]
