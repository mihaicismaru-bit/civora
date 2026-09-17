from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping, Any

from .contracts import Story


_SPECIFICITY_RANK = {
    "EVENT_DIRECT": 50,
    "SUBJECT_DIRECT": 40,
    "PLACE_DIRECT": 30,
    "CONTEXT_CURRENT": 20,
    "CONTEXT_ARCHIVE": 10,
}


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


class MediaPackResolver:
    """Select one rights-cleared real-media asset for a Story.

    The resolver is locality-agnostic. Instance configuration supplies the
    actual assets and the context terms that define the publication's area.
    Assets without VERIFIED_REUSABLE rights are never emitted.
    """

    def __init__(
        self,
        assets: Iterable[Mapping[str, Any]],
        *,
        context_terms: Iterable[str] = (),
    ) -> None:
        self.assets = tuple(dict(asset) for asset in assets)
        self.context_terms = tuple(_norm(term) for term in context_terms if _norm(term))

    def __call__(self, story: Story) -> Story:
        haystack = _norm(" ".join((story.headline, story.dek, story.media_query or "")))
        candidates: list[tuple[int, str, Mapping[str, Any]]] = []

        for asset in self.assets:
            if asset.get("rights_status") != "VERIFIED_REUSABLE":
                continue
            if not asset.get("image_url") or not asset.get("source_page"):
                continue
            usage = set(asset.get("usage_scope") or ())
            if usage and "site_article" not in usage:
                continue

            specificity = str(asset.get("specificity") or "CONTEXT_ARCHIVE")
            rank = _SPECIFICITY_RANK.get(specificity, 0)
            match_terms = tuple(_norm(x) for x in asset.get("match_terms") or () if _norm(x))
            locality_tags = tuple(_norm(x) for x in asset.get("locality_tags") or () if _norm(x))

            exact_hits = sum(1 for term in match_terms if term and term in haystack)
            context_hits = sum(1 for tag in locality_tags if tag in self.context_terms)
            if exact_hits:
                score = rank * 100 + exact_hits * 10 + context_hits
            elif specificity in {"CONTEXT_CURRENT", "CONTEXT_ARCHIVE"} and context_hits:
                score = rank * 100 + context_hits
            else:
                continue
            candidates.append((score, str(asset.get("asset_id") or ""), asset))

        if not candidates:
            metadata = dict(story.metadata)
            metadata["media_status"] = "NO_SAFE_MEDIA"
            return replace(story, metadata=metadata)

        _score, _asset_id, selected = max(candidates, key=lambda row: (row[0], row[1]))
        media = {
            "asset_id": selected.get("asset_id"),
            "image_url": selected.get("image_url"),
            "source_page": selected.get("source_page"),
            "creator": selected.get("creator"),
            "license": selected.get("license"),
            "license_url": selected.get("license_url"),
            "alt": selected.get("alt") or story.media_query or story.headline,
            "caption": selected.get("caption"),
            "specificity": selected.get("specificity"),
            "rights_status": selected.get("rights_status"),
        }
        metadata = dict(story.metadata)
        metadata["media_status"] = "SELECTED_REAL_REUSABLE"
        metadata["media"] = media
        return replace(story, metadata=metadata)
