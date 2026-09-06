from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json

from .master_draft import (
    DraftBriefStatus,
    DraftSupportKind,
    MasterDraftBrief,
    MASTER_DRAFT_MODEL_VERSION,
)

NATIVE_ADAPT_MODEL_VERSION = "PPOS_NATIVE_ADAPTATION_BUNDLE_V1"


class NativePlatform(str, Enum):
    FACEBOOK_PAGE = "FACEBOOK_PAGE"
    INSTAGRAM_PROFESSIONAL = "INSTAGRAM_PROFESSIONAL"
    THREADS = "THREADS"


ACTIVE_NATIVE_PLATFORMS = (
    NativePlatform.FACEBOOK_PAGE.value,
    NativePlatform.INSTAGRAM_PROFESSIONAL.value,
    NativePlatform.THREADS.value,
)


class NativeAdaptationStatus(str, Enum):
    READY = "READY_NATIVE_TEXT"
    HOLD_INPUT_NOT_READY = "HOLD_INPUT_NOT_READY"
    HOLD_LENGTH_BUDGET = "HOLD_LENGTH_BUDGET"


class NativeBundleStatus(str, Enum):
    READY_ALL_ACTIVE_LANES = "READY_ALL_ACTIVE_LANES"
    HOLD_INPUT_NOT_READY = "HOLD_INPUT_NOT_READY"
    HOLD_ONE_OR_MORE_LANES = "HOLD_ONE_OR_MORE_LANES"


HOUSE_MAX_CHARS = {
    NativePlatform.FACEBOOK_PAGE.value: 1800,
    NativePlatform.INSTAGRAM_PROFESSIONAL.value: 1800,
    NativePlatform.THREADS.value: 500,
}

VISUAL_REQUIREMENT = {
    NativePlatform.FACEBOOK_PAGE.value: "PREFERRED_DOWNSTREAM_M06",
    NativePlatform.INSTAGRAM_PROFESSIONAL.value: "REQUIRED_DOWNSTREAM_M06",
    NativePlatform.THREADS.value: "OPTIONAL_DOWNSTREAM_M06",
}

CONTENT_SURFACE = {
    NativePlatform.FACEBOOK_PAGE.value: "PAGE_POST_TEXT",
    NativePlatform.INSTAGRAM_PROFESSIONAL.value: "MEDIA_CAPTION",
    NativePlatform.THREADS.value: "THREADS_TEXT_POST",
}


@dataclass(frozen=True)
class NativeAdaptation:
    adaptation_id: str
    adaptation_hash: str
    platform: str
    status: str
    text: str
    char_count: int
    house_max_chars: int
    content_surface: str
    visual_requirement: str
    source_url: str
    evidence_ids: tuple[str, ...]
    support_kinds: tuple[str, ...]
    unknowns: tuple[str, ...]
    constraints: tuple[str, ...]
    adaptation_ready: bool
    api_write_allowed: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NativeAdaptationBundle:
    bundle_id: str
    bundle_hash: str
    model_version: str
    brief_id: str
    brief_hash: str
    source_url: str
    source_class: str
    topic: str
    locality: str
    adaptations: tuple[NativeAdaptation, ...]
    unknowns: tuple[str, ...]
    status: str
    rights_input_ready: bool
    active_platforms: tuple[str, ...] = ACTIVE_NATIVE_PLATFORMS
    state: str = "NATIVE_ADAPTATION_ONLY"
    native_adaptation_authority: bool = True
    fact_authority: bool = False
    visual_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        value = asdict(self)
        value["adaptations"] = [item.to_dict() for item in self.adaptations]
        return value


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _brief_body(brief: MasterDraftBrief) -> dict:
    return {
        "schema_version": brief.model_version,
        "scorecard_id": brief.scorecard_id,
        "scorecard_hash": brief.scorecard_hash,
        "packet_id": brief.packet_id,
        "research_packet_hash": brief.research_packet_hash,
        "signal_id": brief.signal_id,
        "radar_observation_hash": brief.radar_observation_hash,
        "source_url": brief.source_url,
        "source_class": brief.source_class,
        "topic": brief.topic,
        "locality": brief.locality,
        "evidence_readiness_score": brief.evidence_readiness_score,
        "readiness_band": brief.readiness_band,
        "working_headline": brief.working_headline,
        "support_items": [asdict(v) for v in brief.support_items],
        "evidence_refs": [asdict(v) for v in brief.evidence_refs],
        "attribution_requirements": [asdict(v) for v in brief.attribution_requirements],
        "unknowns": brief.unknowns,
        "drafting_constraints": brief.drafting_constraints,
        "draft_status": brief.draft_status,
        "native_adaptation_input_ready": brief.native_adaptation_input_ready,
        "state": brief.state,
        "internal_draft_brief_authority": brief.internal_draft_brief_authority,
        "fact_authority": brief.fact_authority,
        "queue_authority": brief.queue_authority,
        "publish_authority": brief.publish_authority,
        "network_fetch_performed": brief.network_fetch_performed,
        "synthetic": brief.synthetic,
    }


def _validate_brief(brief: MasterDraftBrief) -> None:
    if not isinstance(brief, MasterDraftBrief):
        raise ValueError("native adaptation input must be MasterDraftBrief")
    if brief.model_version != MASTER_DRAFT_MODEL_VERSION:
        raise ValueError("unsupported master draft model version")
    expected_id = _hash({
        "scorecard_id": brief.scorecard_id,
        "scorecard_hash": brief.scorecard_hash,
        "stage": brief.model_version,
    })
    if expected_id != brief.brief_id or _hash(_brief_body(brief)) != brief.brief_hash:
        raise ValueError("master draft brief integrity check failed")
    if brief.state != "MASTER_DRAFT_BRIEF_ONLY" or not brief.internal_draft_brief_authority:
        raise ValueError("native adaptation accepts canonical M04 briefs only")
    if brief.fact_authority or brief.queue_authority or brief.publish_authority:
        raise ValueError("master draft brief carries forbidden downstream authority")
    if brief.network_fetch_performed or brief.synthetic:
        raise ValueError("native adaptation accepts local non-synthetic briefs only")
    if brief.native_adaptation_input_ready:
        if brief.draft_status != DraftBriefStatus.DIRECT_PRIMARY_CONTEXT_BOUND.value:
            raise ValueError("adaptation-ready brief has invalid draft status")
        if brief.source_class != "PRIMARY_PUBLIC":
            raise ValueError("adaptation-ready brief must be primary-public")
        if not brief.attribution_requirements:
            raise ValueError("adaptation-ready brief must carry attribution requirements")
        attribution_ids = {item.evidence_id for item in brief.attribution_requirements}
        for item in brief.support_items:
            if not item.attribution_required or not item.evidence_ids:
                raise ValueError("all support items must remain evidence-bound and attributable")
            if not set(item.evidence_ids).issubset(attribution_ids):
                raise ValueError("support item references evidence without attribution requirement")


def _support_texts(brief: MasterDraftBrief) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    by_kind: dict[str, list] = {}
    for item in brief.support_items:
        by_kind.setdefault(item.kind, []).append(item)
    titles = by_kind.get(DraftSupportKind.SOURCE_TITLE.value, [])
    excerpts = by_kind.get(DraftSupportKind.SOURCE_EXCERPT.value, [])
    if len(titles) != 1 or len(excerpts) != 1:
        raise ValueError("adaptation-ready brief requires exactly one source title and excerpt")
    title = titles[0].text.strip()
    excerpt = excerpts[0].text.strip()
    if not title or not excerpt:
        raise ValueError("adaptation-ready support text must be non-empty")
    evidence_ids = tuple(sorted(set(titles[0].evidence_ids + excerpts[0].evidence_ids)))
    support_kinds = (
        DraftSupportKind.SOURCE_TITLE.value,
        DraftSupportKind.SOURCE_EXCERPT.value,
    )
    return title, excerpt, evidence_ids, support_kinds


def _render(platform: str, title: str, excerpt: str, source_url: str) -> str:
    if platform == NativePlatform.FACEBOOK_PAGE.value:
        return f"{title}\n\nDin sursa primară:\n{excerpt}\n\nSursa: {source_url}"
    if platform == NativePlatform.INSTAGRAM_PROFESSIONAL.value:
        return f"{title}\n\n{excerpt}\n\nSursă primară: {source_url}"
    if platform == NativePlatform.THREADS.value:
        return f"{title} — {excerpt}\n\nSursa: {source_url}"
    raise ValueError(f"unsupported native platform: {platform}")


def _adaptation(
    brief: MasterDraftBrief,
    platform: str,
    *,
    title: str | None = None,
    excerpt: str | None = None,
    evidence_ids: tuple[str, ...] = (),
    support_kinds: tuple[str, ...] = (),
) -> NativeAdaptation:
    max_chars = HOUSE_MAX_CHARS[platform]
    if not brief.native_adaptation_input_ready:
        status = NativeAdaptationStatus.HOLD_INPUT_NOT_READY.value
        text = ""
        ready = False
    else:
        assert title is not None and excerpt is not None
        candidate = _render(platform, title, excerpt, brief.source_url)
        if len(candidate) > max_chars:
            status = NativeAdaptationStatus.HOLD_LENGTH_BUDGET.value
            text = ""
            ready = False
        else:
            status = NativeAdaptationStatus.READY.value
            text = candidate
            ready = True

    constraints = (
        "HOUSE_LENGTH_BUDGET_NOT_PLATFORM_API_LIMIT",
        "USE_ONLY_M04_SUPPORT_TEXT_PLUS_ATTRIBUTION_LABELS",
        "NO_TRUNCATION_OR_PARAPHRASE_TO_FIT",
        "PRESERVE_M04_UNKNOWNS",
        "NO_HASHTAG_ENTITY_OR_CTA_INFERENCE",
        "NO_NETWORK_FETCH",
        "NO_ACCOUNT_CONNECTION",
        "NO_QUEUE_OR_PUBLISH_AUTHORITY",
    )
    body = {
        "schema_version": NATIVE_ADAPT_MODEL_VERSION,
        "brief_id": brief.brief_id,
        "brief_hash": brief.brief_hash,
        "platform": platform,
        "status": status,
        "text": text,
        "char_count": len(text),
        "house_max_chars": max_chars,
        "content_surface": CONTENT_SURFACE[platform],
        "visual_requirement": VISUAL_REQUIREMENT[platform],
        "source_url": brief.source_url,
        "evidence_ids": evidence_ids,
        "support_kinds": support_kinds,
        "unknowns": brief.unknowns,
        "constraints": constraints,
        "adaptation_ready": ready,
        "api_write_allowed": False,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    adaptation_id = _hash({
        "brief_id": brief.brief_id,
        "brief_hash": brief.brief_hash,
        "platform": platform,
        "stage": NATIVE_ADAPT_MODEL_VERSION,
    })
    return NativeAdaptation(
        adaptation_id=adaptation_id,
        adaptation_hash=_hash(body),
        platform=platform,
        status=status,
        text=text,
        char_count=len(text),
        house_max_chars=max_chars,
        content_surface=CONTENT_SURFACE[platform],
        visual_requirement=VISUAL_REQUIREMENT[platform],
        source_url=brief.source_url,
        evidence_ids=evidence_ids,
        support_kinds=support_kinds,
        unknowns=brief.unknowns,
        constraints=constraints,
        adaptation_ready=ready,
    )


def build_native_adaptation_bundle(brief: MasterDraftBrief) -> NativeAdaptationBundle:
    _validate_brief(brief)

    title = excerpt = None
    evidence_ids: tuple[str, ...] = ()
    support_kinds: tuple[str, ...] = ()
    if brief.native_adaptation_input_ready:
        title, excerpt, evidence_ids, support_kinds = _support_texts(brief)

    adaptations = tuple(
        _adaptation(
            brief,
            platform,
            title=title,
            excerpt=excerpt,
            evidence_ids=evidence_ids,
            support_kinds=support_kinds,
        )
        for platform in ACTIVE_NATIVE_PLATFORMS
    )
    all_ready = all(item.adaptation_ready for item in adaptations)
    if all_ready:
        status = NativeBundleStatus.READY_ALL_ACTIVE_LANES.value
    elif not brief.native_adaptation_input_ready:
        status = NativeBundleStatus.HOLD_INPUT_NOT_READY.value
    else:
        status = NativeBundleStatus.HOLD_ONE_OR_MORE_LANES.value

    body = {
        "schema_version": NATIVE_ADAPT_MODEL_VERSION,
        "brief_id": brief.brief_id,
        "brief_hash": brief.brief_hash,
        "source_url": brief.source_url,
        "source_class": brief.source_class,
        "topic": brief.topic,
        "locality": brief.locality,
        "adaptations": [item.to_dict() for item in adaptations],
        "unknowns": brief.unknowns,
        "status": status,
        "rights_input_ready": all_ready,
        "active_platforms": ACTIVE_NATIVE_PLATFORMS,
        "state": "NATIVE_ADAPTATION_ONLY",
        "native_adaptation_authority": True,
        "fact_authority": False,
        "visual_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    bundle_id = _hash({
        "brief_id": brief.brief_id,
        "brief_hash": brief.brief_hash,
        "stage": NATIVE_ADAPT_MODEL_VERSION,
    })
    return NativeAdaptationBundle(
        bundle_id=bundle_id,
        bundle_hash=_hash(body),
        model_version=NATIVE_ADAPT_MODEL_VERSION,
        brief_id=brief.brief_id,
        brief_hash=brief.brief_hash,
        source_url=brief.source_url,
        source_class=brief.source_class,
        topic=brief.topic,
        locality=brief.locality,
        adaptations=adaptations,
        unknowns=brief.unknowns,
        status=status,
        rights_input_ready=all_ready,
    )


def native_adaptation_bundles_json(briefs) -> str:
    by_hash: dict[str, NativeAdaptationBundle] = {}
    for brief in tuple(briefs):
        bundle = build_native_adaptation_bundle(brief)
        by_hash.setdefault(bundle.bundle_hash, bundle)
    ordered = tuple(sorted(
        by_hash.values(),
        key=lambda b: (
            not b.rights_input_ready,
            b.brief_id,
            b.bundle_hash,
        ),
    ))
    return json.dumps([item.to_dict() for item in ordered], indent=2, ensure_ascii=False, sort_keys=True)
