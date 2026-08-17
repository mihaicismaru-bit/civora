#!/usr/bin/env python3
"""Ingest direct official public-policy / funding signals for PARTENER.EU.

This is discovery for the homepage editorial module "Ce spun decidenții".
It does NOT change a call, deadline, budget or eligibility rule. Those effects
remain governed by canonical call evidence. Only direct official institutional
sources are accepted here; failed sources preserve their last known good items.
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
STATE = ROOT / "partener-eu/ingest/state/people_policy_official_sources.json"
REGISTRY = ROOT / "partener-eu/ingest/state/people_policy_registry.json"
UA = "PARTENER.EU-DecisionMakerOfficialIngest/1.0 (+https://partener.eu)"
NOW = dt.datetime.now(dt.timezone.utc)

SOURCES = [
    {
        "id": "MS_PRESS",
        "publisher": "Ministerul Sănătății",
        "institution": "MS",
        "url": "https://www.ms.gov.ro/ro/centrul-de-presa/",
        "tier": "T1_DIRECT_OFFICIAL",
        "pathHints": ("/centrul-de-presa/",),
        "maxLinks": 14,
    },
    {
        "id": "ANC_COMMUNICATES",
        "publisher": "Autoritatea Națională pentru Cercetare",
        "institution": "ANC",
        "url": "https://www.research.gov.ro/category/comunicare/comunicate/",
        "tier": "T1_DIRECT_OFFICIAL",
        "pathHints": ("research.gov.ro/",),
        "maxLinks": 14,
    },
    {
        "id": "ADR_ARTICLES",
        "publisher": "Autoritatea pentru Digitalizarea României",
        "institution": "ADR",
        "url": "https://www.adr.gov.ro/articole",
        "tier": "T1_DIRECT_OFFICIAL",
        "pathHints": ("/articole/",),
        "maxLinks": 14,
    },
    {
        "id": "FED_MAI",
        "publisher": "Ministerul Afacerilor Interne — Direcția Fonduri Externe Nerambursabile",
        "institution": "FED MAI",
        "url": "https://fed.mai.gov.ro/in/apeluri/",
        "tier": "T1_DIRECT_OFFICIAL",
        "pathHints": ("fed.mai.gov.ro/",),
        "maxLinks": 10,
    },
]

FUNDING_TERMS = (
    "fonduri europene", "finantare", "finanțare", "pnrr", "programul", "apel",
    "grant", "buget", "coeziune", "investitii", "investiții", "mysmis",
    "digital europe", "proiecte selectate", "contracte", "plati", "plăți",
)
SIGNAL_TERMS = (
    "ministr", "secretar de stat", "presed", "președ", "a declarat", "a anuntat",
    "a anunțat", "prioritate", "prelung", "acceler", "negocier", "decizie",
    "aprobat", "adoptat", "semnat", "lans", "rezultat", "contract",
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
    with urllib.request.urlopen(req, timeout=18, context=ssl.create_default_context()) as r:
        return r.read(limit).decode("utf-8", "ignore")


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
    f = fold(text)
    return any(fold(x) in f for x in FUNDING_TERMS) and any(fold(x) in f for x in SIGNAL_TERMS)


def classify(text: str) -> str:
    f = fold(text)
    if any(x in f for x in ("termen", "prelung", "calendar", "ghid", "lans")):
        return "PROGRAMME_CHANGE_SIGNAL"
    if any(x in f for x in ("buget", "finant", "grant", "milioane", "miliarde", "plati", "plăți")):
        return "FUNDING_COMMITMENT"
    return "POLICY_SIGNAL"


def first_relevant_sentence(text: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", clean(text)):
        if 45 <= len(sentence) <= 520 and any(fold(x) in fold(sentence) for x in FUNDING_TERMS):
            return sentence
    return clean(text)[:500]


def actor_for(text: str, publisher: str, institution: str, registry: dict[str, Any]) -> tuple[str, str, str]:
    f = fold(text)
    for person in registry.get("people") or []:
        if not person.get("active"):
            continue
        if any(fold(alias) in f for alias in person.get("aliases") or []):
            # Avoid a stale office title from the registry: the direct official publisher is the safe context.
            return str(person.get("id")), str(person.get("name")), f"Decident public · {publisher}"
    pid = "institution-" + re.sub(r"[^a-z0-9]+", "-", institution.lower()).strip("-")
    return pid, publisher, "Instituție publică · sursă oficială"


def candidate_links(source: dict[str, Any], body: str) -> list[str]:
    parser = LinkParser(); parser.feed(body)
    base_host = urlparse(source["url"]).hostname
    out: list[str] = []
    seen: set[str] = set()
    for href, label in parser.links:
        url = urljoin(source["url"], href)
        p = urlparse(url)
        if p.scheme not in {"http", "https"} or p.hostname != base_host:
            continue
        if url.rstrip("/") == source["url"].rstrip("/"):
            continue
        hay = fold(f"{label} {url}")
        path_ok = any(h in url for h in source.get("pathHints") or ())
        funding_hint = any(fold(term) in hay for term in FUNDING_TERMS)
        if not (path_ok or funding_hint):
            continue
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key); out.append(key)
        if len(out) >= int(source.get("maxLinks") or 10):
            break
    return out


def ingest_source(source: dict[str, Any], registry: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    observed = NOW.isoformat()
    listing = fetch(source["url"])
    urls = candidate_links(source, listing)
    items: list[dict[str, Any]] = []
    for url in urls:
        try:
            body = fetch(url)
        except Exception:
            continue
        parser = TextParser(); parser.feed(body)
        text = clean(" ".join(parser.parts))[:45_000]
        title = clean(" ".join(parser.title_parts))
        if not relevant(f"{title} {text}"):
            continue
        person_id, person, role = actor_for(f"{title} {text[:8000]}", source["publisher"], source["institution"], registry)
        date = parse_date(text[:8000]) or NOW.date().isoformat()
        headline = re.sub(r"\s*[-|–—]\s*[^-|–—]{2,80}$", "", title).strip() or first_relevant_sentence(text)[:220]
        statement = first_relevant_sentence(text)
        fingerprint = hashlib.sha256(f"{source['id']}|{url}|{headline}|{statement}".encode()).hexdigest()
        items.append({
            "id": "official-" + fingerprint[:18],
            "personId": person_id,
            "person": person,
            "role": role,
            "institution": source["institution"],
            "date": date,
            "type": classify(f"{headline} {statement}"),
            "topic": "Fonduri europene / decizie publică",
            "headline": headline[:220],
            "statement": statement[:600],
            "officialFact": "Semnal observat direct pe o sursă oficială. Efectul asupra unui apel, termen, buget sau criteriu se validează separat în dosarul canonic.",
            "analysis": "Contează dacă schimbă priorități, calendar, finanțare sau ritmul de implementare. PARTENER.EU nu transformă declarația în regulă de apel fără evidență administrativă explicită.",
            "watch": "Ghidul, ordinul, corrigendumul, lista de rezultate sau actul administrativ care materializează semnalul.",
            "audiences": ["Beneficiari", "Consultanți"],
            "sources": [{"label": source["publisher"], "url": url, "tier": source["tier"]}],
            "priority": 100 if not person_id.startswith("institution-") else 70,
            "initials": "".join(x[0] for x in person.split()[:2]).upper(),
            "whyItMatters": "Semnal public recent dintr-o sursă oficială; impactul operațional este separat de declarație.",
            "autoGenerated": True,
            "officialIngested": True,
            "observedAt": observed,
            "sourceId": source["id"],
            "fingerprint": fingerprint,
        })
    status = {
        "id": source["id"], "publisher": source["publisher"], "url": source["url"],
        "tier": source["tier"], "status": "OK", "observedAt": observed,
        "candidateLinks": len(urls), "acceptedItems": len(items), "failClosed": True,
    }
    return status, items


def main() -> int:
    previous = load(STATE, {"sources": [], "items": []})
    registry = load(REGISTRY, {"people": []})
    previous_by_source: dict[str, list[dict[str, Any]]] = {}
    for item in previous.get("items") or []:
        previous_by_source.setdefault(str(item.get("sourceId") or ""), []).append(item)

    statuses: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for source in SOURCES:
        try:
            status, fresh = ingest_source(source, registry)
            statuses.append(status); items.extend(fresh)
        except Exception as exc:
            statuses.append({
                "id": source["id"], "publisher": source["publisher"], "url": source["url"],
                "tier": source["tier"], "status": "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED",
                "observedAt": NOW.isoformat(), "error": clean(exc)[:260], "failClosed": True,
            })
            items.extend(previous_by_source.get(source["id"], []))

    dedup: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("fingerprint") or item.get("id"))
        dedup[key] = item
    items = sorted(dedup.values(), key=lambda x: (str(x.get("date") or ""), int(x.get("priority") or 0)), reverse=True)[:120]
    payload = {
        "schemaVersion": 1,
        "generatedAt": NOW.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy": {
            "directOfficialOnly": True,
            "signalsDoNotChangeCalls": True,
            "lastKnownGoodOnSourceFailure": True,
            "fundingRelevanceRequired": True,
            "failClosed": True,
        },
        "sources": statuses,
        "items": items,
    }
    STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sources": len(statuses), "items": len(items), "ok": sum(1 for x in statuses if x["status"] == "OK")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
