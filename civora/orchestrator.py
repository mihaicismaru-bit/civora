from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional
import json
from .models import Source, StoryObject
from .pipeline import verify_story, generate_article, generate_content_pack
from .review import ReviewQueue


class Orchestrator:
    def __init__(self, state_dir: Path, review_queue: Optional[ReviewQueue] = None):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.review_queue = review_queue

    def save_checkpoint(self, story: StoryObject, label: str) -> Path:
        payload = {"label": label, "story": story.to_dict()}
        path = self.state_dir / f"{story.id}_v{story.version}_{label}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def run(self, story: StoryObject, source_map: Dict[str, Source]) -> StoryObject:
        self.save_checkpoint(story, "signal")
        verify_story(story, source_map)
        self.save_checkpoint(story, "verified")
        if story.state.value == "blocked":
            if self.review_queue is not None:
                self.review_queue.enqueue(story, "trust_score_below_threshold")
            return story
        generate_article(story)
        self.save_checkpoint(story, "drafted")
        generate_content_pack(story)
        self.save_checkpoint(story, "packaged")
        return story
