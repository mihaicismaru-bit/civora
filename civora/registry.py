from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional
import json

from .models import Source


class SourceRegistry:
    """JSON-backed source registry with deterministic persistence."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sources: Dict[str, Source] = {}
        self.load()

    def load(self) -> None:
        self._sources = {}
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for item in payload.get("sources", []):
            source = Source(**item)
            self._sources[source.id] = source

    def save(self) -> None:
        payload = {
            "schema_version": 1,
            "sources": [asdict(s) for s in sorted(self._sources.values(), key=lambda x: x.id)],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, source: Source) -> Source:
        self._sources[source.id] = source
        self.save()
        return source

    def get(self, source_id: str) -> Optional[Source]:
        return self._sources.get(source_id)

    def all(self) -> List[Source]:
        return list(self._sources.values())

    def as_map(self) -> Dict[str, Source]:
        return dict(self._sources)
