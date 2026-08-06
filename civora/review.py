from __future__ import annotations
from pathlib import Path
from typing import Dict, List
import json

from .models import StoryObject


class ReviewQueue:
    """Persistent queue for blocked or human-review stories."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.items: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        self.items = {}
        if self.path.exists():
            self.items = json.loads(self.path.read_text(encoding="utf-8")).get("items", {})

    def save(self) -> None:
        self.path.write_text(json.dumps({"schema_version": 1, "items": self.items}, ensure_ascii=False, indent=2), encoding="utf-8")

    def enqueue(self, story: StoryObject, reason: str) -> None:
        self.items[story.id] = {
            "story": story.to_dict(),
            "reason": reason,
            "status": "pending",
        }
        self.save()

    def pending(self) -> List[dict]:
        return [item for item in self.items.values() if item.get("status") == "pending"]
