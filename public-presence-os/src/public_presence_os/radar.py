from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit, urlunsplit

MAX_BATCH = 100
MAX_TITLE = 280
MAX_EXCERPT = 2000
MAX_LABEL = 80
REF_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
WS_RE = re.compile(r"\s+")


class RadarSourceClass(str, Enum):
    PRIMARY_PUBLIC = "PRIMARY_PUBLIC"
    SECONDARY_DISCOVERY = "SECONDARY_DISCOVERY"
    MANUAL_SYNTHETIC = "MANUAL_SYNTHETIC"


class RadarKind(str, Enum):
    ANNOUNCEMENT = "ANNOUNCEMENT"
    ARTICLE = "ARTICLE"
    PUBLIC_POST = "PUBLIC_POST"
    DOCUMENT = "DOCUMENT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class RadarObservation:
    external_ref: str
    source_url: str
    source_class: RadarSourceClass
    kind: RadarKind
    observed_at_utc: str
    title: str
    excerpt: str
    topic: str
    locality: str
    synthetic: bool = False


@dataclass(frozen=True)
class RadarSignal:
    signal_id: str
    observation_hash: str
    external_ref: str
    source_url: str
    source_class: str
    kind: str
    observed_at_utc: str
    title: str
    excerpt: str
    topic: str
    locality: str
    state: str = "DISCOVERY_ONLY"
    fact_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    synthetic: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _norm_text(value: str, *, name: str, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = WS_RE.sub(" ", value).strip()
    if not value and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    if len(value) > max_len:
        raise ValueError(f"{name} exceeds {max_len} characters")
    return value


def _norm_utc(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("observed_at_utc must use Z UTC")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("observed_at_utc is invalid") from exc
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError("observed_at_utc must be UTC")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _norm_url(url: str, source_class: RadarSourceClass, synthetic: bool) -> str:
    if not isinstance(url, str):
        raise ValueError("source_url must be a string")
    p = urlsplit(url.strip())
    if source_class == RadarSourceClass.MANUAL_SYNTHETIC:
        if not synthetic or p.scheme != "synthetic" or not p.netloc:
            raise ValueError("MANUAL_SYNTHETIC requires synthetic:// URL and synthetic=true")
        return urlunsplit(("synthetic", p.netloc.lower(), p.path or "/", p.query, ""))
    if synthetic:
        raise ValueError("public source classes cannot be marked synthetic")
    if p.scheme != "https" or not p.netloc:
        raise ValueError("public radar sources require https URL")
    host = p.netloc.lower()
    if "@" in host:
        raise ValueError("source_url userinfo is not allowed")
    path = p.path or "/"
    return urlunsplit(("https", host, path, p.query, ""))


def normalize_observation(obs: RadarObservation) -> dict:
    external_ref = _norm_text(obs.external_ref, name="external_ref", max_len=160)
    if not REF_RE.fullmatch(external_ref):
        raise ValueError("external_ref contains unsupported characters")
    source_url = _norm_url(obs.source_url, obs.source_class, obs.synthetic)
    title = _norm_text(obs.title, name="title", max_len=MAX_TITLE)
    excerpt = _norm_text(obs.excerpt, name="excerpt", max_len=MAX_EXCERPT, allow_empty=True)
    topic = _norm_text(obs.topic, name="topic", max_len=MAX_LABEL)
    locality = _norm_text(obs.locality, name="locality", max_len=MAX_LABEL)
    observed_at = _norm_utc(obs.observed_at_utc)
    return {
        "external_ref": external_ref,
        "source_url": source_url,
        "source_class": obs.source_class.value,
        "kind": obs.kind.value,
        "observed_at_utc": observed_at,
        "title": title,
        "excerpt": excerpt,
        "topic": topic,
        "locality": locality,
        "synthetic": obs.synthetic,
    }


def materialize_signal(obs: RadarObservation) -> RadarSignal:
    normalized = normalize_observation(obs)
    signal_id = _hash({
        "source_url": normalized["source_url"],
        "external_ref": normalized["external_ref"],
    })
    observation_hash = _hash(normalized)
    return RadarSignal(
        signal_id=signal_id,
        observation_hash=observation_hash,
        **normalized,
    )


def ingest_observations(observations) -> tuple[RadarSignal, ...]:
    observations = tuple(observations)
    if len(observations) > MAX_BATCH:
        raise ValueError(f"radar batch exceeds {MAX_BATCH}")
    by_hash: dict[str, RadarSignal] = {}
    for obs in observations:
        if not isinstance(obs, RadarObservation):
            raise ValueError("radar input must contain RadarObservation values")
        signal = materialize_signal(obs)
        by_hash.setdefault(signal.observation_hash, signal)
    return tuple(sorted(by_hash.values(), key=lambda s: (s.observed_at_utc, s.signal_id, s.observation_hash)))


def signals_json(signals: tuple[RadarSignal, ...]) -> str:
    return json.dumps([s.to_dict() for s in signals], indent=2, ensure_ascii=False, sort_keys=True)
