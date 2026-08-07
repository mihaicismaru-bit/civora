from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import StoryObject
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class StoryCheckpointError(RuntimeError):
    pass


class StoryCheckpointStore:
    """Durable, checksum-protected storage for editorial story checkpoints."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        state_dir: Path,
        *,
        lock_timeout: float = 10.0,
        stale_lock_after: float = 300.0,
    ):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.lock_timeout = lock_timeout
        self.stale_lock_after = stale_lock_after

    @staticmethod
    def _validate(payload: dict) -> None:
        label = payload.get("label")
        story = payload.get("story")
        if not isinstance(label, str) or not label.strip():
            raise AtomicJsonStoreError("checkpoint label must be a non-empty string")
        if not isinstance(story, dict):
            raise AtomicJsonStoreError("checkpoint story must be an object")
        if not isinstance(story.get("id"), str) or not story.get("id"):
            raise AtomicJsonStoreError("checkpoint story id is required")
        if not isinstance(story.get("version"), int):
            raise AtomicJsonStoreError("checkpoint story version must be an integer")

    def path_for(self, story_id: str, version: int, label: str) -> Path:
        return self.state_dir / f"{story_id}_v{version}_{label}.json"

    def _store(self, path: Path) -> AtomicJsonStore:
        return AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate,
            lock_timeout=self.lock_timeout,
            stale_lock_after=self.stale_lock_after,
        )

    def save(self, story: StoryObject, label: str) -> Path:
        path = self.path_for(story.id, story.version, label)
        payload = {"label": label, "story": story.to_dict()}
        try:
            self._store(path).save(payload)
        except AtomicJsonStoreError as exc:
            raise StoryCheckpointError(f"cannot persist checkpoint {path.name}") from exc
        return path

    def load(self, story_id: str, version: int, label: str) -> dict:
        path = self.path_for(story_id, version, label)
        store = self._store(path)
        try:
            return store.load({})
        except AtomicJsonStoreError as exc:
            raise StoryCheckpointError(f"cannot load checkpoint {path.name}") from exc

    def recovered_from_backup(self, story_id: str, version: int, label: str) -> bool:
        path = self.path_for(story_id, version, label)
        store = self._store(path)
        try:
            store.load({})
        except AtomicJsonStoreError as exc:
            raise StoryCheckpointError(f"cannot inspect checkpoint {path.name}") from exc
        return store.recovered_from_backup
