from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit, urlunsplit

from .radar import (
    RadarKind,
    RadarObservation,
    RadarSignal,
    RadarSourceClass,
    materialize_signal,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
MAX_EVIDENCE = 20


class EvidenceAuthority(str, Enum):
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    SECONDARY_CONTEXT = "SECONDARY_CONTEXT"


class EvidenceKind(str, Enum):
    DETAIL_PAGE = "DETAIL_PAGE"
    DOCUMENT = "DOCUMENT"
    PUBLIC_POST = "PUBLIC_POST"
    OTHER = "OTHER"


class ResearchStatus(str, Enum):
    HOLD_PRIMARY_EVIDENCE = "HOLD_PRIMARY_EVIDENCE"
    HOLD_PRIMARY_CONFIRMATION = "HOLD_PRIMARY_CONFIRMATION"
    SYNTHETIC_NON_EVIDENCE = "SYNTHETIC_NON_EVIDENCE"
    EVIDENCE_BOUND = "EVIDENCE_BOUND"


@dataclass(frozen=True)
class ResearchEvidence:
    evidence_id: str
    source_url: str
    authority: EvidenceAuthority
    kind: EvidenceKind
    captured_at_utc: str
    content_sha256: str
    synthetic: bool = False


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    source_url: str
    authority: str
    kind: str
    captured_at_utc: str
    content_sha256: str
    synthetic: bool


@dataclass(frozen=True)
class ResearchPacket:
    packet_id: str
    research_packet_hash: str
    signal_id: str
    radar_observation_hash: str
    source_url: str
    source_class: str
    kind: str
    observed_at_utc: str
    title: str
    excerpt: str
    topic: str
    locality: str
    evidence_refs: tuple[EvidenceRef, ...]
    evidence_requirements: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    research_status: str
    evidence_bound: bool
    scoring_input_ready: bool
    state: str = "RESEARCH_PACKET_ONLY"
    fact_authority: bool = False
    scoring_authority: bool = False
    draft_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    synthetic: bool = False

    def to_dict(self) -> dict:
        value = asdict(self)
        value["evidence_refs"] = [asdict(e) for e in self.evidence_refs]
        return value


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _norm_utc(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must use Z UTC")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError(f"{field} must be UTC")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _norm_evidence_url(url: str, *, synthetic: bool) -> str:
    if not isinstance(url, str):
        raise ValueError("evidence source_url must be a string")
    p = urlsplit(url.strip())
    if synthetic:
        if p.scheme != "synthetic" or not p.netloc:
            raise ValueError("synthetic evidence requires synthetic:// URL")
        return urlunsplit(("synthetic", p.netloc.lower(), p.path or "/", p.query, ""))
    if p.scheme != "https" or not p.netloc:
        raise ValueError("production evidence requires https URL")
    host = p.netloc.lower()
    if "@" in host:
        raise ValueError("evidence source_url userinfo is not allowed")
    return urlunsplit(("https", host, p.path or "/", p.query, ""))


def _normalize_evidence(e: ResearchEvidence, *, observed_at_utc: str) -> EvidenceRef:
    if not isinstance(e, ResearchEvidence):
        raise ValueError("evidence must contain ResearchEvidence values")
    if not EVIDENCE_ID_RE.fullmatch(e.evidence_id or ""):
        raise ValueError("evidence_id contains unsupported characters")
    if not HEX64.fullmatch(e.content_sha256 or ""):
        raise ValueError("content_sha256 must be lowercase sha256")
    captured = _norm_utc(e.captured_at_utc, field="captured_at_utc")
    observed = _norm_utc(observed_at_utc, field="observed_at_utc")
    if captured < observed:
        raise ValueError("evidence capture cannot predate radar observation")
    source_url = _norm_evidence_url(e.source_url, synthetic=e.synthetic)
    if e.synthetic and e.authority == EvidenceAuthority.PRIMARY_SOURCE:
        raise ValueError("synthetic evidence cannot claim PRIMARY_SOURCE authority")
    return EvidenceRef(
        evidence_id=e.evidence_id,
        source_url=source_url,
        authority=e.authority.value,
        kind=e.kind.value,
        captured_at_utc=captured,
        content_sha256=e.content_sha256,
        synthetic=e.synthetic,
    )


def _validate_radar_integrity(signal: RadarSignal) -> None:
    if not isinstance(signal, RadarSignal):
        raise ValueError("research input must be a RadarSignal")
    if signal.state != "DISCOVERY_ONLY" or signal.fact_authority or signal.publish_authority or signal.network_fetch_performed:
        raise ValueError("research accepts fail-closed DISCOVERY_ONLY radar signals only")
    try:
        source_class = RadarSourceClass(signal.source_class)
        kind = RadarKind(signal.kind)
    except ValueError as exc:
        raise ValueError("radar signal enum value is invalid") from exc
    expected = materialize_signal(RadarObservation(
        external_ref=signal.external_ref,
        source_url=signal.source_url,
        source_class=source_class,
        kind=kind,
        observed_at_utc=signal.observed_at_utc,
        title=signal.title,
        excerpt=signal.excerpt,
        topic=signal.topic,
        locality=signal.locality,
        synthetic=signal.synthetic,
    ))
    if expected != signal:
        raise ValueError("radar signal integrity mismatch")


def _evidence_requirements(signal: RadarSignal) -> tuple[str, ...]:
    if signal.synthetic:
        return ("REPLACE_SYNTHETIC_WITH_REAL_PRIMARY_EVIDENCE", "NO_PRODUCTION_USE")
    if signal.source_class == RadarSourceClass.PRIMARY_PUBLIC.value:
        return ("PRIMARY_DETAIL_BODY_OR_DOCUMENT", "CONTENT_HASH_BOUND", "CAPTURE_TIME_BOUND")
    return ("INDEPENDENT_PRIMARY_SOURCE_CONFIRMATION", "CONTENT_HASH_BOUND", "CAPTURE_TIME_BOUND")


def _unresolved_questions(signal: RadarSignal, status: ResearchStatus) -> tuple[str, ...]:
    base = [
        "WHAT_MATERIAL_FACTS_ARE_DIRECTLY_SUPPORTED_BY_PRIMARY_EVIDENCE?",
        "WHAT_IS_THE_RELEVANT_DATE_TIME_OR_CURRENT_STATUS?",
        "WHAT_REMAINS_UNCONFIRMED_OR_ATTRIBUTION_ONLY?",
    ]
    if status == ResearchStatus.HOLD_PRIMARY_CONFIRMATION:
        base.insert(0, "WHICH_PRIMARY_SOURCE_CONFIRMS_THIS_DISCOVERY_SIGNAL?")
    elif status == ResearchStatus.SYNTHETIC_NON_EVIDENCE:
        base = ["WHICH_REAL_PRIMARY_SOURCE_REPLACES_THIS_SYNTHETIC_FIXTURE?"]
    return tuple(base)


def _same_host(url_a: str, url_b: str) -> bool:
    return urlsplit(url_a).netloc.lower() == urlsplit(url_b).netloc.lower()


def build_research_packet(signal: RadarSignal, evidence=()) -> ResearchPacket:
    _validate_radar_integrity(signal)

    evidence = tuple(evidence)
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError(f"research evidence exceeds {MAX_EVIDENCE}")

    by_id: dict[str, EvidenceRef] = {}
    for item in evidence:
        ref = _normalize_evidence(item, observed_at_utc=signal.observed_at_utc)
        previous = by_id.get(ref.evidence_id)
        if previous and previous != ref:
            raise ValueError("conflicting evidence_id")
        by_id.setdefault(ref.evidence_id, ref)
    refs = tuple(sorted(by_id.values(), key=lambda e: (e.captured_at_utc, e.evidence_id, e.content_sha256)))

    if signal.synthetic:
        if any(not e.synthetic for e in refs):
            raise ValueError("synthetic radar fixture cannot bind real production evidence")
        status = ResearchStatus.SYNTHETIC_NON_EVIDENCE
    else:
        if any(e.synthetic for e in refs):
            raise ValueError("production radar signal cannot bind synthetic evidence")
        primary = tuple(e for e in refs if e.authority == EvidenceAuthority.PRIMARY_SOURCE.value)
        if signal.source_class == RadarSourceClass.PRIMARY_PUBLIC.value:
            matching = tuple(e for e in primary if _same_host(signal.source_url, e.source_url))
            status = ResearchStatus.EVIDENCE_BOUND if matching else ResearchStatus.HOLD_PRIMARY_EVIDENCE
        elif signal.source_class == RadarSourceClass.SECONDARY_DISCOVERY.value:
            independent = tuple(e for e in primary if not _same_host(signal.source_url, e.source_url))
            status = ResearchStatus.EVIDENCE_BOUND if independent else ResearchStatus.HOLD_PRIMARY_CONFIRMATION
        else:
            raise ValueError("unsupported radar source_class")

    requirements = _evidence_requirements(signal)
    unresolved = _unresolved_questions(signal, status)
    evidence_bound = status == ResearchStatus.EVIDENCE_BOUND
    packet_body = {
        "schema_version": "PPOS_RESEARCH_PACKET_V1",
        "signal_id": signal.signal_id,
        "radar_observation_hash": signal.observation_hash,
        "source_url": signal.source_url,
        "source_class": signal.source_class,
        "kind": signal.kind,
        "observed_at_utc": signal.observed_at_utc,
        "title": signal.title,
        "excerpt": signal.excerpt,
        "topic": signal.topic,
        "locality": signal.locality,
        "evidence_refs": [asdict(e) for e in refs],
        "evidence_requirements": requirements,
        "unresolved_questions": unresolved,
        "research_status": status.value,
        "evidence_bound": evidence_bound,
        "scoring_input_ready": evidence_bound,
        "synthetic": signal.synthetic,
        "state": "RESEARCH_PACKET_ONLY",
        "fact_authority": False,
        "scoring_authority": False,
        "draft_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
    }
    packet_id = _hash({"signal_id": signal.signal_id, "radar_observation_hash": signal.observation_hash, "stage": "M02_RESEARCH_V1"})
    research_packet_hash = _hash(packet_body)
    return ResearchPacket(
        packet_id=packet_id,
        research_packet_hash=research_packet_hash,
        signal_id=signal.signal_id,
        radar_observation_hash=signal.observation_hash,
        source_url=signal.source_url,
        source_class=signal.source_class,
        kind=signal.kind,
        observed_at_utc=signal.observed_at_utc,
        title=signal.title,
        excerpt=signal.excerpt,
        topic=signal.topic,
        locality=signal.locality,
        evidence_refs=refs,
        evidence_requirements=requirements,
        unresolved_questions=unresolved,
        research_status=status.value,
        evidence_bound=evidence_bound,
        scoring_input_ready=evidence_bound,
        synthetic=signal.synthetic,
    )


def research_packets_json(packets: tuple[ResearchPacket, ...]) -> str:
    return json.dumps([p.to_dict() for p in packets], indent=2, ensure_ascii=False, sort_keys=True)
