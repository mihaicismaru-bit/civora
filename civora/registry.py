from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from .models import Source
from .persistence import AtomicJsonStore, AtomicJsonStoreError


class SourceRegistryError(RuntimeError):
    pass


class SourceRegistry:
    """Checksum-protected, recoverable JSON-backed source registry."""

    SCHEMA_VERSION = 2

    def __init__(self, path: Path):
        self.path = path
        self._sources: Dict[str, Source] = {}
        self.store = AtomicJsonStore(
            path,
            schema_version=self.SCHEMA_VERSION,
            validator=self._validate_payload,
        )
        self.recovered_from_backup = False
        self.load()

    @staticmethod
    def _validate_payload(payload: dict) -> None:
        sources = payload.get("sources")
        if not isinstance(sources, list):
            raise AtomicJsonStoreError("source registry must contain a sources list")
        seen = set()
        for item in sources:
            if not isinstance(item, dict):
                raise AtomicJsonStoreError("source registry entry must be an object")
            source_id = item.get("id")
            if not isinstance(source_id, str) or not source_id:
                raise AtomicJsonStoreError("source registry entry has invalid id")
            if source_id in seen:
                raise AtomicJsonStoreError("source registry contains duplicate ids")
            seen.add(source_id)
            try:
                Source(**item)
            except Exception as exc:
                raise AtomicJsonStoreError("source registry entry is invalid") from exc

    def load(self) -> None:
        self._sources = {}
        default = {"sources": []}
        try:
            payload = self.store.load(default)
        except AtomicJsonStoreError as exc:
            raise SourceRegistryError(str(exc)) from exc
        self.recovered_from_backup = self.store.recovered_from_backup
        for item in payload.get("sources", []):
            source = Source(**item)
            self._sources[source.id] = source

    def save(self) -> None:
        payload = {
            "sources": [
                asdict(source)
                for source in sorted(self._sources.values(), key=lambda item: item.id)
            ]
        }
        try:
            self.store.save(payload)
        except AtomicJsonStoreError as exc:
            raise SourceRegistryError(str(exc)) from exc

    def upsert(self, source: Source) -> Source:
        previous = self._sources.get(source.id)
        self._sources[source.id] = source
        try:
            self.save()
        except Exception:
            if previous is None:
                self._sources.pop(source.id, None)
            else:
                self._sources[source.id] = previous
            raise
        return source

    def get(self, source_id: str) -> Optional[Source]:
        return self._sources.get(source_id)

    def all(self) -> List[Source]:
        return list(self._sources.values())

    def as_map(self) -> Dict[str, Source]:
        return dict(self._sources)
