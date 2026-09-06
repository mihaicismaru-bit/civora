from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from .research import EvidenceRef, ResearchPacket

SCORE_MODEL_VERSION = "PPOS_EVIDENCE_READINESS_SCORE_V1"
SCORE_TYPE = "EVIDENCE_READINESS_ONLY"
MAX_SCORE = 100
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_SOURCE_CLASSES = {"PRIMARY_PUBLIC", "SECONDARY_DISCOVERY"}
ALLOWED_KINDS = {"ANNOUNCEMENT", "ARTICLE", "PUBLIC_POST", "DOCUMENT", "OTHER"}
ALLOWED_EVIDENCE_AUTHORITIES = {"PRIMARY_SOURCE", "SECONDARY_CONTEXT"}
ALLOWED_EVIDENCE_KINDS = {"DETAIL_PAGE", "DOCUMENT", "PUBLIC_POST", "OTHER"}


@dataclass(frozen=True)
class ScoreDimension:
    name: str
    score: int
    maximum: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceScorecard:
    scorecard_id: str
    scorecard_hash: str
    packet_id: str
    research_packet_hash: str
    signal_id: str
    radar_observation_hash: str
    score_model_version: str
    score_type: str
    evidence_readiness_score: int
    readiness_band: str
    dimensions: tuple[ScoreDimension, ...]
    reasons: tuple[str, ...]
    editorial_impact_score: None = None
    virality_score: None = None
    audience_fit_score: None = None
    state: str = "SCORING_ONLY"
    scoring_authority: bool = True
    fact_authority: bool = False
    draft_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    synthetic: bool = False

    def to_dict(self) -> dict:
        value = asdict(self)
        value["dimensions"] = [asdict(d) for d in self.dimensions]
        return value


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must use Z UTC")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("timestamp is invalid") from exc
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError("timestamp must be UTC")
    return dt.astimezone(timezone.utc)


def _research_packet_body(packet: ResearchPacket) -> dict:
    return {
        "schema_version": "PPOS_RESEARCH_PACKET_V1",
        "signal_id": packet.signal_id,
        "radar_observation_hash": packet.radar_observation_hash,
        "source_url": packet.source_url,
        "source_class": packet.source_class,
        "kind": packet.kind,
        "observed_at_utc": packet.observed_at_utc,
        "title": packet.title,
        "excerpt": packet.excerpt,
        "topic": packet.topic,
        "locality": packet.locality,
        "evidence_refs": [asdict(e) for e in packet.evidence_refs],
        "evidence_requirements": packet.evidence_requirements,
        "unresolved_questions": packet.unresolved_questions,
        "research_status": packet.research_status,
        "evidence_bound": packet.evidence_bound,
        "scoring_input_ready": packet.scoring_input_ready,
        "synthetic": packet.synthetic,
        "state": packet.state,
        "fact_authority": packet.fact_authority,
        "scoring_authority": packet.scoring_authority,
        "draft_authority": packet.draft_authority,
        "publish_authority": packet.publish_authority,
        "network_fetch_performed": packet.network_fetch_performed,
    }


def _validate_packet_integrity(packet: ResearchPacket) -> None:
    if not isinstance(packet, ResearchPacket):
        raise ValueError("scoring input must be a ResearchPacket")
    if packet.synthetic:
        raise ValueError("synthetic research packets are not scoring inputs")
    if packet.state != "RESEARCH_PACKET_ONLY":
        raise ValueError("scoring accepts RESEARCH_PACKET_ONLY packets")
    if packet.research_status != "EVIDENCE_BOUND" or not packet.evidence_bound or not packet.scoring_input_ready:
        raise ValueError("research packet is not evidence-bound scoring input")
    if packet.fact_authority or packet.scoring_authority or packet.draft_authority or packet.publish_authority:
        raise ValueError("research packet carries forbidden authority")
    if packet.network_fetch_performed:
        raise ValueError("scoring accepts local no-network research packets only")
    if not packet.evidence_refs:
        raise ValueError("scoring requires evidence references")
    if packet.source_class not in ALLOWED_SOURCE_CLASSES:
        raise ValueError("research packet source_class is not scoring-supported")
    if packet.kind not in ALLOWED_KINDS:
        raise ValueError("research packet kind is invalid")
    observed = _parse_utc(packet.observed_at_utc)
    evidence_ids = set()
    for ref in packet.evidence_refs:
        if not isinstance(ref, EvidenceRef):
            raise ValueError("research packet evidence_refs are invalid")
        if ref.synthetic:
            raise ValueError("scoring does not accept synthetic evidence")
        if ref.authority not in ALLOWED_EVIDENCE_AUTHORITIES:
            raise ValueError("evidence authority is invalid")
        if ref.kind not in ALLOWED_EVIDENCE_KINDS:
            raise ValueError("evidence kind is invalid")
        if not HEX64.fullmatch(ref.content_sha256 or ""):
            raise ValueError("evidence content_sha256 is invalid")
        parsed = urlsplit(ref.source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("scoring evidence must use https URL")
        if ref.evidence_id in evidence_ids:
            raise ValueError("scoring evidence IDs must be unique")
        evidence_ids.add(ref.evidence_id)
        if _parse_utc(ref.captured_at_utc) < observed:
            raise ValueError("evidence capture cannot predate radar observation")
    expected_packet_id = _hash({
        "signal_id": packet.signal_id,
        "radar_observation_hash": packet.radar_observation_hash,
        "stage": "M02_RESEARCH_V1",
    })
    if packet.packet_id != expected_packet_id:
        raise ValueError("research packet_id integrity mismatch")
    expected_hash = _hash(_research_packet_body(packet))
    if packet.research_packet_hash != expected_hash:
        raise ValueError("research_packet_hash integrity mismatch")


def _primary_refs(refs: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    return tuple(e for e in refs if e.authority == "PRIMARY_SOURCE")


def _evidence_quality(refs: tuple[EvidenceRef, ...]) -> ScoreDimension:
    primary = _primary_refs(refs)
    score = 0
    reasons = []
    if primary:
        score += 20
        reasons.append("PRIMARY_EVIDENCE_PRESENT")
    if len(primary) >= 2:
        score += 5
        reasons.append("MULTIPLE_PRIMARY_EVIDENCE_ITEMS")
    if len({e.kind for e in refs}) >= 2:
        score += 5
        reasons.append("MULTIPLE_EVIDENCE_KINDS")
    return ScoreDimension("evidence_quality", score, 30, tuple(reasons))


def _source_directness(packet: ResearchPacket) -> ScoreDimension:
    primary = _primary_refs(packet.evidence_refs)
    signal_host = urlsplit(packet.source_url).netloc.lower()
    primary_hosts = {urlsplit(e.source_url).netloc.lower() for e in primary}
    if packet.source_class == "PRIMARY_PUBLIC" and signal_host in primary_hosts:
        return ScoreDimension("source_directness", 15, 15, ("PRIMARY_DISCOVERY_BOUND_TO_SAME_HOST_PRIMARY_EVIDENCE",))
    if packet.source_class == "SECONDARY_DISCOVERY" and any(h != signal_host for h in primary_hosts):
        return ScoreDimension("source_directness", 12, 15, ("SECONDARY_DISCOVERY_CONFIRMED_BY_INDEPENDENT_PRIMARY_HOST",))
    return ScoreDimension("source_directness", 0, 15, ("NO_DIRECT_PRIMARY_BINDING",))


def _corroboration(refs: tuple[EvidenceRef, ...]) -> ScoreDimension:
    primary = _primary_refs(refs)
    hosts = {urlsplit(e.source_url).netloc.lower() for e in primary}
    if len(hosts) >= 2:
        return ScoreDimension("corroboration", 15, 15, ("MULTI_HOST_PRIMARY_CORROBORATION",))
    if len(primary) >= 2:
        return ScoreDimension("corroboration", 10, 15, ("MULTIPLE_PRIMARY_ITEMS_SINGLE_HOST",))
    if len(primary) == 1:
        return ScoreDimension("corroboration", 5, 15, ("ONE_PRIMARY_ITEM",))
    return ScoreDimension("corroboration", 0, 15, ("NO_PRIMARY_ITEM",))


def _timeliness(packet: ResearchPacket) -> ScoreDimension:
    observed = _parse_utc(packet.observed_at_utc)
    captures = [_parse_utc(e.captured_at_utc) for e in packet.evidence_refs]
    latest = max(captures)
    lag_seconds = max(0.0, (latest - observed).total_seconds())
    if lag_seconds <= 3600:
        return ScoreDimension("research_timeliness", 20, 20, ("EVIDENCE_CAPTURE_WITHIN_1H",))
    if lag_seconds <= 86400:
        return ScoreDimension("research_timeliness", 15, 20, ("EVIDENCE_CAPTURE_WITHIN_24H",))
    if lag_seconds <= 259200:
        return ScoreDimension("research_timeliness", 10, 20, ("EVIDENCE_CAPTURE_WITHIN_72H",))
    if lag_seconds <= 604800:
        return ScoreDimension("research_timeliness", 5, 20, ("EVIDENCE_CAPTURE_WITHIN_7D",))
    return ScoreDimension("research_timeliness", 0, 20, ("EVIDENCE_CAPTURE_AFTER_7D",))


def _provenance(refs: tuple[EvidenceRef, ...]) -> ScoreDimension:
    reasons = []
    score = 0
    if all(HEX64.fullmatch(e.content_sha256 or "") for e in refs):
        score += 5
        reasons.append("CONTENT_HASHES_VALID")
    if len({e.evidence_id for e in refs}) == len(refs):
        score += 5
        reasons.append("EVIDENCE_IDS_UNIQUE")
    if all(urlsplit(e.source_url).scheme == "https" for e in refs):
        score += 5
        reasons.append("HTTPS_EVIDENCE_ONLY")
    if all(e.captured_at_utc.endswith("Z") for e in refs):
        score += 5
        reasons.append("UTC_CAPTURE_TIMES_PRESENT")
    return ScoreDimension("provenance_completeness", score, 20, tuple(reasons))


def _band(score: int) -> str:
    if score >= 85:
        return "EVIDENCE_READY_STRONG"
    if score >= 70:
        return "EVIDENCE_READY_STANDARD"
    return "EVIDENCE_READY_LIMITED"


def score_research_packet(packet: ResearchPacket) -> EvidenceScorecard:
    _validate_packet_integrity(packet)
    dimensions = (
        _evidence_quality(packet.evidence_refs),
        _source_directness(packet),
        _corroboration(packet.evidence_refs),
        _timeliness(packet),
        _provenance(packet.evidence_refs),
    )
    score = sum(d.score for d in dimensions)
    if score < 0 or score > MAX_SCORE:
        raise ValueError("score out of range")
    reasons = tuple(reason for d in dimensions for reason in d.reasons)
    body = {
        "schema_version": "PPOS_EVIDENCE_SCORECARD_V1",
        "packet_id": packet.packet_id,
        "research_packet_hash": packet.research_packet_hash,
        "signal_id": packet.signal_id,
        "radar_observation_hash": packet.radar_observation_hash,
        "score_model_version": SCORE_MODEL_VERSION,
        "score_type": SCORE_TYPE,
        "evidence_readiness_score": score,
        "readiness_band": _band(score),
        "dimensions": [asdict(d) for d in dimensions],
        "reasons": reasons,
        "editorial_impact_score": None,
        "virality_score": None,
        "audience_fit_score": None,
        "state": "SCORING_ONLY",
        "scoring_authority": True,
        "fact_authority": False,
        "draft_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "synthetic": False,
    }
    scorecard_id = _hash({
        "packet_id": packet.packet_id,
        "research_packet_hash": packet.research_packet_hash,
        "model": SCORE_MODEL_VERSION,
    })
    return EvidenceScorecard(
        scorecard_id=scorecard_id,
        scorecard_hash=_hash(body),
        packet_id=packet.packet_id,
        research_packet_hash=packet.research_packet_hash,
        signal_id=packet.signal_id,
        radar_observation_hash=packet.radar_observation_hash,
        score_model_version=SCORE_MODEL_VERSION,
        score_type=SCORE_TYPE,
        evidence_readiness_score=score,
        readiness_band=_band(score),
        dimensions=dimensions,
        reasons=reasons,
    )


def score_packets(packets) -> tuple[EvidenceScorecard, ...]:
    by_hash: dict[str, EvidenceScorecard] = {}
    for packet in tuple(packets):
        scorecard = score_research_packet(packet)
        by_hash.setdefault(scorecard.scorecard_hash, scorecard)
    return tuple(sorted(
        by_hash.values(),
        key=lambda s: (-s.evidence_readiness_score, s.scorecard_id, s.scorecard_hash),
    ))


def scorecards_json(scorecards: tuple[EvidenceScorecard, ...]) -> str:
    return json.dumps([s.to_dict() for s in scorecards], indent=2, ensure_ascii=False, sort_keys=True)
