from __future__ import annotations

import re
from typing import Any

CHANNEL_ID_RE = re.compile(r"^CH-[A-Z0-9]{8,32}$")


class ChannelProvenanceError(ValueError):
    pass


def validate_recruitment_channel_id(value: Any) -> str:
    """Validate an opaque, non-personal recruitment-batch identifier.

    Channel ids are provenance metadata only. They identify a documented
    dissemination batch, never a respondent, device, CRM contact, referrer or
    tracking audience. Human-readable organisation/person names are forbidden
    by construction through the bounded token format.
    """
    if not isinstance(value, str) or not CHANNEL_ID_RE.fullmatch(value):
        raise ChannelProvenanceError(
            "recruitment_channel_id must match CH-[A-Z0-9]{8,32}"
        )
    return value


def validate_channel_set(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ChannelProvenanceError("collection_channels must be a non-empty list")
    channels = tuple(validate_recruitment_channel_id(item) for item in value)
    if len(channels) != len(set(channels)):
        raise ChannelProvenanceError("collection_channels contains duplicates")
    return channels
