from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json

from .research import EvidenceRef, ResearchPacket
from .scoring import EvidenceScorecard, score_research_packet

MASTER_DRAFT_MODEL_VERSION = "PPOS_MASTER_DRAFT_BRIEF_V1"


class DraftBriefStatus(str, Enum):
    DIRECT_PRIMARY_CONTEXT_BOUND = "DIRECT_PRIMARY_CONTEXT_BOUND"
    HOLD_DIRECT_PRIMARY_CONTEXT = "HOLD_DIRECT_PRIMARY_CONTEXT"


class DraftSupportKind(str, Enum):
    SOURCE_TITLE = "SOURCE_TITLE"
    SOURCE_EXCERPT = "SOURCE_EXCERPT"


@dataclass(frozen=True)
class DraftSupportItem:
    kind: str
    text: str
    evidence_ids: tuple[str, ...]
    support_class: str = "DIRECT_PRIMARY_CONTEXT"
    attribution_required: bool = True


@dataclass(frozen=True)
class AttributionRequirement:
    evidence_id: str
    source_url: str
    requirement: str = "ATTRIBUTE_SOURCE_FOR_ANY_USE_OF_BOUND_CONTEXT"


@dataclass(frozen=True)
class MasterDraftBrief:
    brief_id: str
    brief_hash: str
    model_version: str
    scorecard_id: str
    scorecard_hash: str
    packet_id: str
    research_packet_hash: str
    signal_id: str
    radar_observation_hash: str
    source_url: str
    source_class: str
    topic: str
    locality: str
    evidence_readiness_score: int
    readiness_band: str
    working_headline: str
    support_items: tuple[DraftSupportItem, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    attribution_requirements: tuple[AttributionRequirement, ...]
    unknowns: tuple[str, ...]
    drafting_constraints: tuple[str, ...]
    draft_status: str
    native_adaptation_input_ready: bool
    state: str = "MASTER_DRAFT_BRIEF_ONLY"
    internal_draft_brief_authority: bool = True
    fact_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    synthetic: bool = False

    def to_dict(self) -> dict:
        value = asdict(self)
        value["support_items"] = [asdict(v) for v in self.support_items]
        value["evidence_refs"] = [asdict(v) for v in self.evidence_refs]
        value["attribution_requirements"] = [asdict(v) for v in self.attribution_requirements]
        return value


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validate_exact_binding(packet: ResearchPacket, scorecard: EvidenceScorecard) -> None:
    if not isinstance(packet, ResearchPacket):
        raise ValueError("master draft input must include ResearchPacket")
    if not isinstance(scorecard, EvidenceScorecard):
        raise ValueError("master draft input must include EvidenceScorecard")
    expected = score_research_packet(packet)
    if expected != scorecard:
        raise ValueError("scorecard is not exactly bound to the supplied research packet")
    if scorecard.state != "SCORING_ONLY" or not scorecard.scoring_authority:
        raise ValueError("master draft accepts canonical M03 scorecards only")
    if scorecard.fact_authority or scorecard.draft_authority or scorecard.queue_authority or scorecard.publish_authority:
        raise ValueError("scorecard carries forbidden downstream authority")
    if scorecard.network_fetch_performed or scorecard.synthetic:
        raise ValueError("master draft accepts local non-synthetic scorecards only")


def _exact_primary_refs(packet: ResearchPacket) -> tuple[EvidenceRef, ...]:
    if packet.source_class != "PRIMARY_PUBLIC":
        return ()
    return tuple(
        ref for ref in packet.evidence_refs
        if ref.authority == "PRIMARY_SOURCE" and ref.source_url == packet.source_url
    )


def build_master_draft_brief(packet: ResearchPacket, scorecard: EvidenceScorecard) -> MasterDraftBrief:
    _validate_exact_binding(packet, scorecard)

    exact_primary = _exact_primary_refs(packet)
    evidence_ids = tuple(sorted(ref.evidence_id for ref in exact_primary))
    direct_ready = bool(exact_primary and packet.excerpt.strip())

    support_items: tuple[DraftSupportItem, ...]
    if direct_ready:
        support_items = (
            DraftSupportItem(
                kind=DraftSupportKind.SOURCE_TITLE.value,
                text=packet.title,
                evidence_ids=evidence_ids,
            ),
            DraftSupportItem(
                kind=DraftSupportKind.SOURCE_EXCERPT.value,
                text=packet.excerpt,
                evidence_ids=evidence_ids,
            ),
        )
        draft_status = DraftBriefStatus.DIRECT_PRIMARY_CONTEXT_BOUND
    else:
        support_items = ()
        draft_status = DraftBriefStatus.HOLD_DIRECT_PRIMARY_CONTEXT

    attributions = tuple(
        AttributionRequirement(ref.evidence_id, ref.source_url)
        for ref in sorted(exact_primary, key=lambda e: (e.evidence_id, e.source_url))
    )

    unknowns = tuple(dict.fromkeys(
        tuple(packet.unresolved_questions) + (
            "NO_SEMANTIC_CLAIM_EXTRACTION_BEYOND_DIRECT_BOUND_SOURCE_CONTEXT",
        )
    ))
    constraints = (
        "USE_ONLY_SUPPORT_ITEMS_AS_DRAFTABLE_CONTEXT",
        "ATTRIBUTE_EVERY_SUPPORTED_ITEM_TO_ITS_BOUND_PRIMARY_SOURCE",
        "DO_NOT_PROMOTE_SOURCE_CONTEXT_TO_UNATTRIBUTED_FACT",
        "DO_NOT_INFER_MISSING_NAMES_DATES_NUMBERS_CAUSES_OR_OUTCOMES",
        "PRESERVE_UNKNOWNS_EXPLICITLY",
        "NO_EDITORIAL_IMPACT_VIRALITY_OR_AUDIENCE_FIT_INFERENCE",
        "NO_NETWORK_FETCH",
        "NO_QUEUE_OR_PUBLISH_AUTHORITY",
    )

    body = {
        "schema_version": MASTER_DRAFT_MODEL_VERSION,
        "scorecard_id": scorecard.scorecard_id,
        "scorecard_hash": scorecard.scorecard_hash,
        "packet_id": packet.packet_id,
        "research_packet_hash": packet.research_packet_hash,
        "signal_id": packet.signal_id,
        "radar_observation_hash": packet.radar_observation_hash,
        "source_url": packet.source_url,
        "source_class": packet.source_class,
        "topic": packet.topic,
        "locality": packet.locality,
        "evidence_readiness_score": scorecard.evidence_readiness_score,
        "readiness_band": scorecard.readiness_band,
        "working_headline": packet.title,
        "support_items": [asdict(v) for v in support_items],
        "evidence_refs": [asdict(v) for v in packet.evidence_refs],
        "attribution_requirements": [asdict(v) for v in attributions],
        "unknowns": unknowns,
        "drafting_constraints": constraints,
        "draft_status": draft_status.value,
        "native_adaptation_input_ready": direct_ready,
        "state": "MASTER_DRAFT_BRIEF_ONLY",
        "internal_draft_brief_authority": True,
        "fact_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "synthetic": False,
    }
    brief_id = _hash({
        "scorecard_id": scorecard.scorecard_id,
        "scorecard_hash": scorecard.scorecard_hash,
        "stage": MASTER_DRAFT_MODEL_VERSION,
    })
    return MasterDraftBrief(
        brief_id=brief_id,
        brief_hash=_hash(body),
        model_version=MASTER_DRAFT_MODEL_VERSION,
        scorecard_id=scorecard.scorecard_id,
        scorecard_hash=scorecard.scorecard_hash,
        packet_id=packet.packet_id,
        research_packet_hash=packet.research_packet_hash,
        signal_id=packet.signal_id,
        radar_observation_hash=packet.radar_observation_hash,
        source_url=packet.source_url,
        source_class=packet.source_class,
        topic=packet.topic,
        locality=packet.locality,
        evidence_readiness_score=scorecard.evidence_readiness_score,
        readiness_band=scorecard.readiness_band,
        working_headline=packet.title,
        support_items=support_items,
        evidence_refs=packet.evidence_refs,
        attribution_requirements=attributions,
        unknowns=unknowns,
        drafting_constraints=constraints,
        draft_status=draft_status.value,
        native_adaptation_input_ready=direct_ready,
    )


def master_draft_briefs_json(briefs) -> str:
    by_hash: dict[str, MasterDraftBrief] = {}
    for packet, scorecard in tuple(briefs):
        brief = build_master_draft_brief(packet, scorecard)
        by_hash.setdefault(brief.brief_hash, brief)
    ordered = tuple(sorted(
        by_hash.values(),
        key=lambda b: (
            not b.native_adaptation_input_ready,
            -b.evidence_readiness_score,
            b.brief_id,
            b.brief_hash,
        ),
    ))
    return json.dumps([b.to_dict() for b in ordered], indent=2, ensure_ascii=False, sort_keys=True)
