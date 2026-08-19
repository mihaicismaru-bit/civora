#!/usr/bin/env python3
"""Ingest direct official decision-maker signals for PARTENER.EU.

This lane discovers statements/signals only. It never promotes a call status,
deadline, budget, eligibility rule or other administrative fact. Person signals
are emitted only when the tracked role has a verified official snapshot.
Source failures preserve historical observations and remain visible in status.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import re
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_official_sources.json"
REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_registry.json"
SOURCE_REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_source_registry.json"
CANONICAL_CALLS = ROOT / "partener-eu" / "ingest" / "state" / "mipe_canonical_calls.json"
UA = "PARTENER.EU-DecisionMakerOfficialIngest/2.5 (+https://partener.eu)"
NOW = dt.datetime.now(dt.timezone.utc)
FETCH_TIMEOUT_SECONDS = 18
MAX_SOURCE_FETCH_WORKERS = 9

FUNDING_TERMS = (
    "fonduri europene", "finantare", "finanțare", "pnrr", "programul", "apel",
    "grant", "buget", "coeziune", "investitii", "investiții", "mysmis",
    "digital europe", "proiecte selectate", "contracte", "plati", "plăți",
    "ajutor de stat", "mecanism", "nextgenerationeu", "competitivitate",
)
SIGNAL_TERMS = (
    "ministr", "secretar de stat", "presed", "președ", "premier", "prim-ministr",
    "comisia european", "a declarat", "a anuntat", "a anunțat", "prioritate",
    "prelung", "acceler", "negocier", "decizie", "aprobat", "adoptat", "semnat",
    "lans", "rezultat", "contract", "plătește", "plateste", "propune", "alocă", "aloca",
)
STATEMENT_CUES = (
    "a declarat", "a anuntat", "a anunțat", "a precizat", "a spus", "a afirmat",
    "a explicat", "a subliniat", "a mentionat", "a menționat", "a transmis",
    "a aratat", "a arătat", "a adaugat", "a adăugat", "anunta", "anunță",
    "declara", "declară", "precizeaza", "precizează", "spune", "afirma", "afirmă",
    "explica", "explică", "subliniaza", "subliniază", "propune",
)
DIRECT_QUOTE_SIGNAL_CUE = "DIRECT_QUOTE_ATTRIBUTION"
DIRECT_QUOTE_ROLE_TERMS = (
    "ministr", "președ", "presed", "director", "secretar de stat",
    "comisar", "premier", "prim-ministr",
)
DIRECT_QUOTE_CLOSERS = {"„": "”", "“": "”", "«": "»", '"': '"'}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def fold(value: Any) -> str:
    return clean(value).lower().translate(str.maketrans("ăâîșşțţ", "aaisstt"))


def official_host(url: str, allowed_hosts: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and host in {str(x).lower() for x in allowed_hosts}


def verified_role(person: dict[str, Any]) -> dict[str, Any] | None:
    verification = person.get("roleVerification")
    if not isinstance(verification, dict) or verification.get("status") != "VERIFIED":
        return None
    url = str(verification.get("sourceUrl") or "")
    tier = str(verification.get("sourceTier") or "")
    verified_at = str(verification.get("verifiedAt") or "")
    if not url.startswith("https://") or not verified_at or not tier.startswith("T1"):
        return None
    return {
        "role": str(person.get("role") or ""),
        "institution": str(person.get("institution") or ""),
        "verifiedAt": verified_at,
        "sourceUrl": url,
        "sourceTier": tier,
    }


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, clean(" ".join(self._parts))))
            self._href = None
            self._parts = []


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in {"script", "style", "svg", "noscript"}:
            self._skip += 1
        if t == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "svg", "noscript"} and self._skip:
            self._skip -= 1
        if t == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        value = clean(data)
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        else:
            self.parts.append(value)


def fetch(url: str, limit: int = 900_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=.8"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS, context=ssl.create_default_context()) as response:
        return response.read(limit).decode("utf-8", "ignore")


def source_fetch_budget_seconds(sources: list[dict[str, Any]]) -> int:
    """Conservative network wait budget for the bounded source pool.

    Each source keeps its own sequential listing/article contract so source-health
    accounting is unchanged. Sources execute concurrently in bounded waves.
    The estimate intentionally assumes every configured candidate consumes the
    full socket timeout and therefore fails safe when registry growth would no
    longer fit the workflow envelope.
    """
    enabled = [s for s in sources if s.get("enabled", True)]
    if not enabled:
        return 0
    workers = min(MAX_SOURCE_FETCH_WORKERS, len(enabled))
    longest_source = max(
        FETCH_TIMEOUT_SECONDS * (1 + max(0, int(s.get("maxLinks") or 10)))
        for s in enabled
    )
    return math.ceil(len(enabled) / workers) * longest_source


def parse_date(text: str) -> str | None:
    months = {
        "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5,
        "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10,
        "noiembrie": 11, "decembrie": 12,
    }
    m = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})\b", fold(text))
    if m:
        try:
            return dt.date(int(m.group(3)), months[m.group(2)], int(m.group(1))).isoformat()
        except ValueError:
            pass
    return None


def relevant(text: str) -> bool:
    value = fold(text)
    return (
        any(fold(x) in value for x in FUNDING_TERMS)
        and any(fold(x) in value for x in (*SIGNAL_TERMS, *STATEMENT_CUES))
    )


def classify(text: str) -> str:
    value = fold(text)
    if any(x in value for x in ("termen", "prelung", "calendar", "ghid", "lans")):
        return "PROGRAMME_CHANGE_SIGNAL"
    if any(x in value for x in ("buget", "finant", "grant", "milioane", "miliarde", "plati", "aloc", "ajutor de stat")):
        return "FUNDING_COMMITMENT"
    return "POLICY_SIGNAL"


def first_relevant_sentence(text: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", clean(text)):
        if 45 <= len(sentence) <= 520 and any(fold(x) in fold(sentence) for x in FUNDING_TERMS):
            return sentence
    return clean(text)[:500]


def alias_present(text: Any, alias: Any) -> bool:
    """Match a person alias only as a complete folded token sequence.

    Romanian diacritics are folded before matching, while ASCII alphanumerics
    define the entity boundary. This preserves explicit surname mentions such as
    `Maxim a declarat` but rejects accidental substrings such as `maximizează`
    or `maximum`.
    """
    value = fold(text)
    needle = fold(alias)
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", value) is not None


def actor_alias(person: dict[str, Any], text: str) -> str | None:
    aliases = [clean(alias) for alias in person.get("aliases") or [] if clean(alias)]
    name = clean(person.get("name"))
    if name:
        aliases.append(name)
    for alias in sorted(set(aliases), key=len, reverse=True):
        if alias_present(text, alias):
            return alias
    return None


def direct_quote_window_for(person: dict[str, Any], text: str) -> dict[str, Any] | None:
    """Accept only explicit actor + role + colon + bounded direct-quote attribution.

    The role phrase must sit between the tracked actor and the colon, the quote
    must be explicitly delimited in article body text, and funding context must
    occur inside the quote itself. This is intentionally stricter than generic
    quotation detection and never infers the verified role from article wording.
    """
    value = clean(text)
    folded = fold(value)
    aliases = [clean(alias) for alias in person.get("aliases") or [] if clean(alias)]
    name = clean(person.get("name"))
    if name:
        aliases.append(name)
    for alias in sorted(set(aliases), key=len, reverse=True):
        needle = fold(alias)
        if not needle:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
        for match in re.finditer(pattern, folded):
            colon = folded.find(":", match.end(), min(len(folded), match.end() + 180))
            if colon < 0:
                continue
            attribution = folded[match.end():colon]
            if not any(fold(term) in attribution for term in DIRECT_QUOTE_ROLE_TERMS):
                continue
            tail = value[colon + 1:colon + 951]
            stripped = tail.lstrip()
            leading = len(tail) - len(stripped)
            if not stripped or stripped[0] not in DIRECT_QUOTE_CLOSERS:
                continue
            opener = stripped[0]
            quote_start = leading + 1
            closer = DIRECT_QUOTE_CLOSERS[opener]
            quote_end = tail.find(closer, quote_start)
            if quote_end < 0:
                continue
            quote = clean(tail[quote_start:quote_end])
            if len(quote) < 45 or len(quote.split()) < 8:
                continue
            funding = next((term for term in FUNDING_TERMS if fold(term) in fold(quote)), None)
            if not funding:
                continue
            statement_end = colon + 1 + quote_end + 1
            statement = clean(value[match.start():statement_end])
            if len(statement) > 900:
                continue
            return {
                "statement": statement,
                "actorAlias": alias,
                "signalCue": DIRECT_QUOTE_SIGNAL_CUE,
                "fundingCue": funding,
                "scope": "ACTOR_ROLE_COLON_QUOTE",
                "sentenceIndex": len(sentence_units(value[:match.start()])),
            }
    return None


def sentence_units(text: str) -> list[str]:
    return [
        sentence for sentence in re.split(r"(?<=[.!?])\s+", clean(text))
        if 25 <= len(sentence) <= 700
    ]


def statement_window_for(person: dict[str, Any], text: str) -> dict[str, Any] | None:
    """Bind actor + speech cue + funding context to one compact article window.

    The actor and speech/announcement cue must occur in the same sentence. Funding
    context may be in that sentence or one immediately adjacent sentence. This
    rejects articles where a tracked person is merely mentioned somewhere while a
    separate generic funding paragraph happens to exist elsewhere on the page.
    """
    sentences = sentence_units(text)
    actor_speech: list[tuple[int, str, str, str]] = []
    for index, sentence in enumerate(sentences):
        alias = actor_alias(person, sentence)
        if not alias:
            continue
        cue = next((term for term in STATEMENT_CUES if fold(term) in fold(sentence)), None)
        if cue:
            actor_speech.append((index, sentence, alias, cue))

    for index, sentence, alias, cue in actor_speech:
        funding = next((term for term in FUNDING_TERMS if fold(term) in fold(sentence)), None)
        if funding:
            return {
                "statement": sentence,
                "actorAlias": alias,
                "signalCue": cue,
                "fundingCue": funding,
                "scope": "SENTENCE",
                "sentenceIndex": index,
            }

    for index, sentence, alias, cue in actor_speech:
        for neighbor_index in (index - 1, index + 1):
            if neighbor_index < 0 or neighbor_index >= len(sentences):
                continue
            neighbor = sentences[neighbor_index]
            funding = next((term for term in FUNDING_TERMS if fold(term) in fold(neighbor)), None)
            if not funding:
                continue
            ordered = [neighbor, sentence] if neighbor_index < index else [sentence, neighbor]
            window = clean(" ".join(ordered))
            if len(window) > 1100:
                continue
            return {
                "statement": window,
                "actorAlias": alias,
                "signalCue": cue,
                "fundingCue": funding,
                "scope": "ADJACENT_SENTENCES",
                "sentenceIndex": min(index, neighbor_index),
            }
    direct_quote = direct_quote_window_for(person, text)
    if direct_quote:
        return direct_quote
    return None


def actor_for(text: str, registry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for person in registry.get("people") or []:
        if not person.get("active"):
            continue
        if not actor_alias(person, text):
            continue
        snapshot = verified_role(person)
        if snapshot:
            return person, snapshot
        return None
    return None


def actor_statement_for(text: str, registry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    candidates: list[tuple[int, int, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for person in registry.get("people") or []:
        if not person.get("active"):
            continue
        snapshot = verified_role(person)
        if not snapshot:
            continue
        evidence = statement_window_for(person, text)
        if not evidence:
            continue
        candidates.append((
            int(evidence.get("sentenceIndex") or 0),
            -int(person.get("priority") or 50),
            person,
            snapshot,
            evidence,
        ))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    _, _, person, snapshot, evidence = candidates[0]
    return person, snapshot, evidence


def candidate_links(source: dict[str, Any], body: str) -> list[str]:
    parser = LinkParser()
    parser.feed(body)
    out: list[str] = []
    seen: set[str] = set()
    allowed = source.get("allowedHosts") or []
    for href, label in parser.links:
        url = urljoin(source["url"], href)
        p = urlparse(url)
        if p.scheme not in {"http", "https"} or not official_host(url, allowed):
            continue
        if url.rstrip("/") == source["url"].rstrip("/"):
            continue
        hay = fold(f"{label} {url}")
        path_ok = any(str(hint) in url for hint in source.get("pathHints") or ())
        funding_hint = any(fold(term) in hay for term in FUNDING_TERMS)
        if not (path_ok or funding_hint):
            continue
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= int(source.get("maxLinks") or 10):
            break
    return out


def canonical_link_for(text: str, canonical: dict[str, Any]) -> dict[str, Any]:
    calls = canonical.get("calls") or canonical.get("items") or []
    hay = fold(text)
    matches: list[dict[str, Any]] = []
    for call in calls:
        code = clean(call.get("code") or call.get("callCode") or call.get("id"))
        if not code or len(code) < 5:
            continue
        if fold(code) in hay:
            matches.append(call)
    if len(matches) != 1:
        return {"status": "UNRESOLVED"}
    call = matches[0]
    return {
        "status": "MATCHED_EXPLICIT_CODE",
        "callId": call.get("id"),
        "code": call.get("code") or call.get("callCode"),
        "programme": call.get("programme") or call.get("program"),
    }


def canonical_article_url(value: Any) -> str:
    """Normalize only transport-irrelevant URL variance for stable signal identity."""
    return clean(value).split("#", 1)[0].rstrip("/")


def normalized_statement_identity(value: Any) -> str:
    """Normalize punctuation/diacritics without changing statement semantics."""
    return re.sub(r"[^a-z0-9]+", " ", fold(value)).strip()


def logical_signal_key(item: dict[str, Any]) -> str:
    """Return a stable identity for the same attributed statement across re-fetches.

    Page bytes, observation timestamps and content hashes are deliberately absent
    from the identity. They are observation-version provenance, not signal identity.
    """
    snapshot = item.get("sourceSnapshot") if isinstance(item.get("sourceSnapshot"), dict) else {}
    sources = item.get("sources") or []
    first_source = sources[0] if sources and isinstance(sources[0], dict) else {}
    parts = (
        clean(item.get("sourceId") or snapshot.get("sourceId")),
        canonical_article_url(snapshot.get("url") or first_source.get("url")),
        clean(item.get("personId")),
        clean(item.get("date"))[:10],
        normalized_statement_identity(item.get("statement")),
    )
    if not all(parts):
        return ""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def observation_records(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Return versioned observations, collapsing repeated identical page bytes."""
    existing = item.get("observations")
    if isinstance(existing, list) and existing:
        records: list[dict[str, Any]] = []
        for row in existing:
            if not isinstance(row, dict):
                continue
            fingerprint = clean(row.get("fingerprint"))
            content_hash = clean(row.get("contentHash"))
            first_seen = clean(row.get("firstObservedAt") or row.get("observedAt"))
            last_seen = clean(row.get("lastObservedAt") or row.get("observedAt") or first_seen)
            if not fingerprint or not content_hash or not first_seen:
                continue
            records.append({
                "fingerprint": fingerprint,
                "contentHash": content_hash,
                "firstObservedAt": first_seen,
                "lastObservedAt": last_seen,
                "observationCount": max(1, int(row.get("observationCount") or 1)),
            })
        if records:
            return records
    snapshot = item.get("sourceSnapshot") if isinstance(item.get("sourceSnapshot"), dict) else {}
    fingerprint = clean(item.get("fingerprint"))
    content_hash = clean(snapshot.get("contentHash"))
    observed = clean(item.get("observedAt") or snapshot.get("observedAt"))
    if not fingerprint or not content_hash or not observed:
        return []
    return [{
        "fingerprint": fingerprint,
        "contentHash": content_hash,
        "firstObservedAt": observed,
        "lastObservedAt": observed,
        "observationCount": 1,
    }]


def merge_observation_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    versions: dict[str, dict[str, Any]] = {}
    for item in items:
        for row in observation_records(item):
            fingerprint = row["fingerprint"]
            current = versions.get(fingerprint)
            if current is None:
                versions[fingerprint] = dict(row)
                continue
            current["firstObservedAt"] = min(current["firstObservedAt"], row["firstObservedAt"])
            current["lastObservedAt"] = max(current["lastObservedAt"], row["lastObservedAt"])
            current["observationCount"] += int(row.get("observationCount") or 1)
    return sorted(versions.values(), key=lambda row: (row["firstObservedAt"], row["fingerprint"]))


def deduplicate_signal_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge logical duplicates while retaining every distinct source observation version."""
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for index, item in enumerate(history):
        logical = logical_signal_key(item)
        fallback = clean(item.get("fingerprint") or item.get("id") or f"legacy-{index}")
        key = f"logical:{logical}" if logical else f"fallback:{fallback}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    merged: list[dict[str, Any]] = []
    for key in order:
        rows = groups[key]
        base = dict(rows[0])
        logical = logical_signal_key(base)
        if logical:
            stable_id = "official-signal-" + logical[:18]
            legacy_ids = {
                clean(value)
                for row in rows
                for value in [row.get("id"), *((row.get("legacyIds") or []) if isinstance(row.get("legacyIds"), list) else [])]
                if clean(value) and clean(value) != stable_id
            }
            base["id"] = stable_id
            base["logicalSignalKey"] = logical
            if legacy_ids:
                base["legacyIds"] = sorted(legacy_ids)
        observations = merge_observation_records(rows)
        if observations:
            base["observations"] = observations
            base["firstObservedAt"] = min(row["firstObservedAt"] for row in observations)
            base["lastObservedAt"] = max(row["lastObservedAt"] for row in observations)
            base["observationCount"] = sum(int(row["observationCount"]) for row in observations)
        # Preserve the earliest trusted role/source snapshot represented by the
        # first historical row; only explicit canonical evidence may improve.
        if str((base.get("canonicalLink") or {}).get("status")) != "MATCHED_EXPLICIT_CODE":
            matched = next(
                (row.get("canonicalLink") for row in rows if str((row.get("canonicalLink") or {}).get("status")) == "MATCHED_EXPLICIT_CODE"),
                None,
            )
            if matched:
                base["canonicalLink"] = matched
        merged.append(base)
    return merged


def ingest_source(source: dict[str, Any], registry: dict[str, Any], canonical: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    observed = NOW.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    allowed = source.get("allowedHosts") or []
    if not source.get("enabled", True):
        return ({
            "id": source["id"], "publisher": source["publisher"], "url": source["url"],
            "tier": source["tier"], "status": "DISABLED", "observedAt": observed, "failClosed": True,
        }, [])
    if not source["url"].startswith("https://") or not official_host(source["url"], allowed):
        raise ValueError(f"source registry host mismatch for {source['id']}")
    listing = fetch(source["url"])
    urls = candidate_links(source, listing)
    items: list[dict[str, Any]] = []
    unverified_roles = 0
    statement_evidence_rejections = 0
    article_fetch_attempts = 0
    article_fetch_successes = 0
    article_fetch_failures = 0
    for url in urls:
        article_fetch_attempts += 1
        try:
            body = fetch(url)
            article_fetch_successes += 1
        except Exception:
            article_fetch_failures += 1
            continue
        parser = TextParser()
        parser.feed(body)
        text = clean(" ".join(parser.parts))[:45_000]
        title = clean(" ".join(parser.title_parts))
        combined = f"{title} {text}"
        if not relevant(combined):
            continue
        actor = actor_statement_for(text[:30_000], registry)
        if not actor:
            mentioned_people = [
                person for person in registry.get("people") or []
                if person.get("active") and actor_alias(person, combined)
            ]
            if any(verified_role(person) for person in mentioned_people):
                statement_evidence_rejections += 1
            elif mentioned_people:
                unverified_roles += 1
            continue
        person, role_snapshot, statement_evidence = actor
        date = parse_date(text[:10000]) or NOW.date().isoformat()
        statement = clean(statement_evidence["statement"])
        headline = re.sub(r"\s*[-|–—]\s*[^-|–—]{2,80}$", "", title).strip() or statement[:220]
        content_hash = hashlib.sha256(clean(text[:30000]).encode("utf-8")).hexdigest()
        fingerprint = hashlib.sha256(f"{person['id']}|{url}|{content_hash}".encode("utf-8")).hexdigest()
        canonical_link = canonical_link_for(f"{headline} {statement} {text[:12000]}", canonical)
        item = {
            "id": "official-" + fingerprint[:18],
            "personId": person["id"],
            "person": person["name"],
            "role": role_snapshot["role"],
            "institution": role_snapshot["institution"],
            "roleVerification": role_snapshot,
            "date": date,
            "type": classify(f"{headline} {statement}"),
            "signalKind": "STATEMENT_SIGNAL",
            "topic": source.get("institution") or "Fonduri europene",
            "headline": headline[:220],
            "statement": statement[:600],
            "statementExtraction": {
                "status": "ACTOR_SPEECH_FUNDING_BOUND",
                "scope": statement_evidence["scope"],
                "actorAlias": statement_evidence["actorAlias"],
                "signalCue": statement_evidence["signalCue"],
                "fundingCue": statement_evidence["fundingCue"],
            },
            "officialFact": "Niciun efect administrativ nu este promovat din această declarație. Orice termen, buget, eligibilitate, deschidere sau modificare de apel cere dovadă T1/T1B separată în dosarul canonic.",
            "administrativeFact": {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True},
            "analysis": "Semnalul este relevant pentru monitorizare; impactul operațional se stabilește numai după legarea de documentul oficial aplicabil.",
            "watch": "Ghidul, ordinul, corrigendumul, lista de rezultate sau actul administrativ care poate materializa semnalul.",
            "audiences": ["Beneficiari", "Consultanți"],
            "canonicalLink": canonical_link,
            "sources": [{"label": source["publisher"], "url": url, "tier": source["tier"]}],
            "sourceSnapshot": {
                "sourceId": source["id"], "publisher": source["publisher"], "tier": source["tier"],
                "url": url, "observedAt": observed, "contentHash": content_hash,
            },
            "priority": int(person.get("priority") or 50),
            "initials": "".join(x[0] for x in person["name"].split()[:2]).upper(),
            "whyItMatters": "Semnal public observat direct pe o sursă oficială; efectul administrativ rămâne separat și fail-closed.",
            "autoGenerated": True,
            "officialIngested": True,
            "observedAt": observed,
            "sourceId": source["id"],
            "fingerprint": fingerprint,
        }
        logical = logical_signal_key(item)
        if logical:
            item["logicalSignalKey"] = logical
            item["id"] = "official-signal-" + logical[:18]
        item["observations"] = observation_records(item)
        item["firstObservedAt"] = observed
        item["lastObservedAt"] = observed
        item["observationCount"] = 1
        items.append(item)
    if not urls:
        source_status = "OK_NO_CANDIDATES"
    elif article_fetch_successes == 0:
        source_status = "DEGRADED_ARTICLE_FETCH_FAILED"
    elif article_fetch_failures:
        source_status = "DEGRADED_PARTIAL_ARTICLE_FETCH"
    else:
        source_status = "OK"
    status = {
        "id": source["id"], "publisher": source["publisher"], "url": source["url"],
        "tier": source["tier"], "status": source_status, "observedAt": observed,
        "listingFetched": True,
        "candidateLinks": len(urls),
        "articleFetchAttempts": article_fetch_attempts,
        "articleFetchSuccesses": article_fetch_successes,
        "articleFetchFailures": article_fetch_failures,
        "acceptedItems": len(items),
        "statementEvidenceRejected": statement_evidence_rejections,
        "unverifiedRoleMentionsRejected": unverified_roles, "failClosed": True,
    }
    return status, items


def main() -> int:
    previous = load(STATE, {"sources": [], "items": []})
    registry = load(REGISTRY, {"people": []})
    source_registry = load(SOURCE_REGISTRY, {"sources": [], "policy": {}})
    canonical = load(CANONICAL_CALLS, {"calls": []})

    configured_sources = list(source_registry.get("sources") or [])
    results: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    workers = min(MAX_SOURCE_FETCH_WORKERS, max(1, len(configured_sources)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="partener-source") as pool:
        futures = {
            pool.submit(ingest_source, source, registry, canonical): source
            for source in configured_sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                results[str(source.get("id"))] = future.result()
            except Exception as exc:
                results[str(source.get("id"))] = ({
                    "id": source.get("id"), "publisher": source.get("publisher"), "url": source.get("url"),
                    "tier": source.get("tier"), "status": "SOURCE_UNAVAILABLE_HISTORY_PRESERVED",
                    "observedAt": NOW.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "error": clean(exc)[:260], "failClosed": True,
                }, [])

    statuses: list[dict[str, Any]] = []
    fresh_items: list[dict[str, Any]] = []
    for source in configured_sources:
        status, fresh = results[str(source.get("id"))]
        statuses.append(status)
        fresh_items.extend(fresh)

    trusted_history: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = list(previous.get("quarantine") or [])
    for item in previous.get("items") or []:
        role = item.get("roleVerification")
        if isinstance(role, dict) and str(role.get("sourceTier") or "").startswith("T1") and role.get("sourceUrl"):
            trusted_history.append(item)
            continue
        sources = item.get("sources") or []
        first = sources[0] if sources and isinstance(sources[0], dict) else {}
        quarantine.append({
            "id": item.get("id"),
            "sourceId": item.get("sourceId"),
            "observedAt": item.get("observedAt"),
            "url": first.get("url"),
            "fingerprint": item.get("fingerprint"),
            "reason": "PRE_V2_ROLE_NOT_VERIFIED",
        })

    items = sorted(
        deduplicate_signal_history([*trusted_history, *fresh_items]),
        key=lambda x: (
            str(x.get("date") or ""),
            str(x.get("lastObservedAt") or x.get("observedAt") or ""),
            int(x.get("priority") or 0),
        ),
        reverse=True,
    )[:320]
    quarantine_dedup = {
        str(x.get("fingerprint") or x.get("id") or f"legacy-{i}"): x
        for i, x in enumerate(quarantine)
    }
    quarantine = list(quarantine_dedup.values())[-320:]
    network_budget_seconds = source_fetch_budget_seconds(configured_sources)
    payload = {
        "schemaVersion": 2,
        "generatedAt": NOW.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy": {
            **(source_registry.get("policy") or {}),
            "personSignalsRequireVerifiedRoleSnapshot": True,
            "administrativeFactsNeverPromotedFromSignals": True,
            "historyDeduplicatedByFingerprint": False,
            "historyDeduplicatedByLogicalSignalIdentity": True,
            "sourceObservationVersionsPreserved": True,
            "legacyUnverifiedSignalsQuarantined": True,
            "canonicalLinkRequiresExplicitCodeMatch": True,
            "sourceHealthRequiresArticleFetchProofWhenCandidatesExist": True,
            "actorSpeechFundingEvidenceRequired": True,
            "attributedDirectQuoteEvidenceSupported": True,
            "directQuoteRequiresActorRoleColonAndFundingInQuote": True,
            "actorAliasesRequireTokenBoundaries": True,
            "boundedConcurrentSourceIngest": True,
            "maxSourceFetchWorkers": MAX_SOURCE_FETCH_WORKERS,
            "fetchTimeoutSeconds": FETCH_TIMEOUT_SECONDS,
            "worstCaseNetworkBudgetSeconds": network_budget_seconds,
            "failClosed": True,
        },
        "sources": statuses,
        "items": items,
        "quarantine": quarantine,
    }
    STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "sources": len(statuses),
        "freshItems": len(fresh_items),
        "historyItems": len(items),
        "logicalSignalItems": sum(1 for x in items if x.get("logicalSignalKey")),
        "observationVersions": sum(len(x.get("observations") or []) for x in items),
        "quarantinedLegacy": len(quarantine),
        "sourceFetchWorkers": workers,
        "worstCaseNetworkBudgetSeconds": network_budget_seconds,
        "ok": sum(1 for x in statuses if x.get("status") == "OK"),
        "reachableNoCandidates": sum(1 for x in statuses if x.get("status") == "OK_NO_CANDIDATES"),
        "degraded": sum(1 for x in statuses if str(x.get("status", "")).startswith("DEGRADED_")),
        "failed": sum(1 for x in statuses if str(x.get("status", "")).startswith("SOURCE_UNAVAILABLE")),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())