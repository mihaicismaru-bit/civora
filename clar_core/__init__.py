"""CLAR Core — minimal reusable local-news runtime.

This package intentionally starts small. It is the replacement core for the
Craiova Clar greenfield build; legacy CIVORA/LOCAL NEWS OS code is reused only
when a component proves directly useful to the end-to-end publication path.
"""

from .contracts import FactPacket, PublicationReceipt, SourceItem, Story
from .pipeline import Pipeline

__all__ = ["SourceItem", "FactPacket", "Story", "PublicationReceipt", "Pipeline"]
