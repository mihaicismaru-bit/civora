from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class SourceItem:
    source_id: str
    canonical_url: str
    title: str
    discovered_at: datetime
    published_at: datetime | None = None
    body_text: str | None = None
    source_type: str = "official"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FactPacket:
    source_item: SourceItem
    kind: str
    facts: Mapping[str, Any]
    evidence_urls: Sequence[str]
    confidence: str
    risk: str = "low"
    material: bool = True


@dataclass(frozen=True)
class Story:
    story_id: str
    slug: str
    section: str
    headline: str
    dek: str
    paragraphs: Sequence[str]
    source_urls: Sequence[str]
    published_at: datetime
    updated_at: datetime | None = None
    media_query: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicationReceipt:
    story_id: str
    canonical_url: str
    published_at: datetime
    destination: str
    status: str
    external_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
