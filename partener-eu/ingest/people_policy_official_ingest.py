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
import re
import ssl
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_official_sources.json"
REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_registry.json"
SOURCE_REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_source_registry.json"
CANONICAL_CALLS = ROOT / "partener-eu" / "ingest" / "state" / "mipe_canonical_calls.json"
UA = "PARTENER.EU-DecisionMakerOfficialIngest/2.1 (+https://partener.eu)"
NOW = dt.datetime.now(dt.timezone.utc)

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
        self.parts.append(value)
        if self._in_title:
            self.title_parts.append(value)


def fetch(url: str, limit: int = 900_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=.8"})
    with urllib.request.urlopen(req, timeout=18, context=ssl.create_default_context()) as response:
        return response.read(limit).decode("utf-8", "ignore")


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
    return any(fold(x) in value for x in FUNDING_TERMS) and any(fold(x) in value for x in SIGNAL_TERMS)


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


def actor_for(text: str, registry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    value = fold(text)
    for person in registry.get("people") or []:
        if not person.get("active"):
            continue
        if not any(fold(alias) in value for alias in person.get("aliases") or []):
            continue
        snapshot = verified_role(person)
        if snapshot:
            return person, snapshot
        return None
    return None


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
        actor = actor_for(f"{title} {text[:10000]}", registry)
        if not actor:
            if any(fold(alias) in fold(combined) for person in registry.get("people") or [] for alias in person.get("aliases") or []):
                unverified_roles += 1
            continue
        person, role_snapshot = actor
        date = parse_date(text[:10000]) or NOW.date().isoformat()
        headline = re.sub(r"\s*[-|–—]\s*[^-|–—]{2,80}$", "", title).strip() or first_relevant_sentence(text)[:220]
        statement = first_relevant_sentence(text)
        content_hash = hashlib.sha256(clean(text[:30000]).encode("utf-8")).hexdigest()
        fingerprint = hashlib.sha256(f"{person['id']}|{url}|{content_hash}".encode("utf-8")).hexdigest()
        canonical_link = canonical_link_for(f"{headline} {statement} {text[:12000]}", canonical)
        items.append({
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
        })
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
        "unverifiedRoleMentionsRejected": unverified_roles, "failClosed": True,
    }
    return status, items


def main() -> int:
    previous = load(STATE, {"sources": [], "items": []})
    registry = load(REGISTRY, {"people": []})
    source_registry = load(SOURCE_REGISTRY, {"sources": [], "policy": {}})
    canonical = load(CANONICAL_CALLS, {"calls": []})

    statuses: list[dict[str, Any]] = []
    fresh_items: list[dict[str, Any]] = []
    for source in source_registry.get("sources") or []:
        try:
            status, fresh = ingest_source(source, registry, canonical)
            statuses.append(status)
            fresh_items.extend(fresh)
        except Exception as exc:
            statuses.append({
                "id": source.get("id"), "publisher": source.get("publisher"), "url": source.get("url"),
                "tier": source.get("tier"), "status": "SOURCE_UNAVAILABLE_HISTORY_PRESERVED",
                "observedAt": NOW.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "error": clean(exc)[:260], "failClosed": True,
            })

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

    dedup: dict[str, dict[str, Any]] = {}
    for item in [*trusted_history, *fresh_items]:
        key = str(item.get("fingerprint") or item.get("id"))
        if key:
            dedup[key] = item
    items = sorted(
        dedup.values(),
        key=lambda x: (str(x.get("date") or ""), str(x.get("observedAt") or ""), int(x.get("priority") or 0)),
        reverse=True,
    )[:320]
    quarantine_dedup = {
        str(x.get("fingerprint") or x.get("id") or f"legacy-{i}"): x
        for i, x in enumerate(quarantine)
    }
    quarantine = list(quarantine_dedup.values())[-320:]
    payload = {
        "schemaVersion": 2,
        "generatedAt": NOW.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy": {
            **(source_registry.get("policy") or {}),
            "personSignalsRequireVerifiedRoleSnapshot": True,
            "administrativeFactsNeverPromotedFromSignals": True,
            "historyDeduplicatedByFingerprint": True,
            "legacyUnverifiedSignalsQuarantined": True,
            "canonicalLinkRequiresExplicitCodeMatch": True,
            "sourceHealthRequiresArticleFetchProofWhenCandidatesExist": True,
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
        "quarantinedLegacy": len(quarantine),
        "ok": sum(1 for x in statuses if x.get("status") == "OK"),
        "reachableNoCandidates": sum(1 for x in statuses if x.get("status") == "OK_NO_CANDIDATES"),
        "degraded": sum(1 for x in statuses if str(x.get("status", "")).startswith("DEGRADED_")),
        "failed": sum(1 for x in statuses if str(x.get("status", "")).startswith("SOURCE_UNAVAILABLE")),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
