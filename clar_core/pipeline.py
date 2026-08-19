from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from .contracts import FactPacket, PublicationReceipt, SourceItem, Story


class Discoverer(Protocol):
    def __call__(self) -> Iterable[SourceItem]: ...


class Extractor(Protocol):
    def __call__(self, item: SourceItem) -> FactPacket | None: ...


class Composer(Protocol):
    def __call__(self, packet: FactPacket) -> Story | None: ...


class Publisher(Protocol):
    def __call__(self, story: Story) -> PublicationReceipt: ...


@dataclass
class PipelineResult:
    discovered: int = 0
    fact_packets: int = 0
    stories: int = 0
    publications: int = 0


class Pipeline:
    """One small end-to-end newsroom lane.

    No orchestration state machine lives here. A source adapter discovers
    SourceItems, a vertical extractor emits FactPackets, a composer emits
    Stories, and the canonical publisher returns PublicationReceipts.
    """

    def __init__(
        self,
        discover: Discoverer,
        extract: Extractor,
        compose: Composer,
        publish: Publisher,
        *,
        seen: Callable[[SourceItem], bool] | None = None,
        mark_seen: Callable[[SourceItem], None] | None = None,
    ) -> None:
        self.discover = discover
        self.extract = extract
        self.compose = compose
        self.publish = publish
        self.seen = seen or (lambda _item: False)
        self.mark_seen = mark_seen or (lambda _item: None)

    def run_once(self) -> PipelineResult:
        result = PipelineResult()
        for item in self.discover():
            result.discovered += 1
            if self.seen(item):
                continue
            packet = self.extract(item)
            if packet is None or not packet.material:
                self.mark_seen(item)
                continue
            result.fact_packets += 1
            story = self.compose(packet)
            if story is None:
                continue
            result.stories += 1
            receipt = self.publish(story)
            if receipt.status == "published":
                result.publications += 1
                self.mark_seen(item)
        return result
