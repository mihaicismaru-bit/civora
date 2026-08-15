#!/usr/bin/env python3
"""Discover fresh VÂLCEA CLAR facts from primary local sources, zero LLM.

Automatic admission is intentionally narrow: only the existence of a newly
published item, its source-provided title and publication date may become a
fact. Numbers, claims, people, quotations and article-body details remain out
of the automatic fact registry until a stronger verification layer exists.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import time
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "news_sources.json"
OUT = ROOT / "editorial" / "auto_facts.json"
STATE = ROOT / "editorial" / "news_discovery_state.json"
TZ = ZoneInfo("Europe/Bucharest")
UA = "Mozilla/5.0 VÂLCEA-CLAR-Autonomous-News/1.0 (+https://valceaclar.ro/)"
RO_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5,
    "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10,
    "noiembrie": 11, "decembrie": 12,
}
GENERIC_NAV = {
    "acasa", "acasă", "contact", "despre noi", "citește", "citeste", "mai mult",
    "vezi detalii", "detalii", "articole", "noutăți", "noutati", "știri", "stiri",
    "comunicate", "comunicate de presă", "comunicate de presa", "anunțuri", "anunturi",
    "pagina următoare", "pagina urmatoare", "rss", "hartă site", "harta site",
}


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text)))
            self._href = None
            self._text = []


def clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", value).strip(" \t\r\n-|•")


def fetch(url: str, max_bytes: int = 4_000_000) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.4",
        "Connection": "close",
    })
    with urllib.request.urlopen(req, timeout=22, context=ssl.create_default_context()) as response:
        raw = response.read(max_bytes)
        ctype = (response.headers.get("content-type") or "").lower()
        if "html" not in ctype and not raw.lstrip().startswith(b"<"):
            raise RuntimeError(f"not HTML: {ctype}")
        charset = "utf-8"
        match = re.search(r"charset=([\w-]+)", ctype)
        if match:
            charset = match.group(1)
        return raw.decode(charset, errors="replace"), response.geturl()


def same_host(a: str, b: str) -> bool:
    ha = (urlparse(a).hostname or "").lower().removeprefix("www.")
    hb = (urlparse(b).hostname or "").lower().removeprefix("www.")
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def title_ok(title: str, source: dict, min_chars: int) -> bool:
    compact = clean_text(title)
    low = compact.casefold()
    generic = GENERIC_NAV | {clean_text(v).casefold() for v in source.get("generic_titles", [])}
    if len(compact) < min_chars or len(compact) > 260:
        return False
    if low in generic:
        return False
    if re.fullmatch(r"[\W_\d]+", compact):
        return False
    return True


def hint_match(url: str, source: dict) -> bool:
    searchable = url.lower()
    hints = [str(x).lower() for x in source.get("path_hints", [])]
    return not hints or any(hint in searchable for hint in hints)


def extract_listing_links(text: str, final_url: str, source: dict, limit: int, min_chars: int) -> list[tuple[str, str]]:
    parser = AnchorParser()
    parser.feed(text)
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, anchor_text in parser.links:
        absolute = urljoin(final_url, html.unescape(href).strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not same_host(absolute, final_url):
            continue
        absolute = absolute.split("#", 1)[0]
        title = clean_text(anchor_text)
        if absolute in seen or absolute.rstrip("/") == final_url.rstrip("/"):
            continue
        if not hint_match(absolute, source) or not title_ok(title, source, min_chars):
            continue
        seen.add(absolute)
        result.append((absolute, title))
        if len(result) >= limit:
            break
    return result


def first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return clean_text(m.group(1)) if m else None


def extract_article_title(text: str, fallback: str, source: dict, min_chars: int) -> str | None:
    candidates = [
        first(r"<h1\b[^>]*>(.*?)</h1>", text),
        first(r"<meta\b(?=[^>]*property=['\"]og:title['\"])(?=[^>]*content=['\"]([^'\"]+)['\"])[^>]*>", text),
        first(r"<title\b[^>]*>(.*?)</title>", text),
        fallback,
    ]
    for candidate in candidates:
        if candidate and title_ok(candidate, source, min_chars):
            # Remove common publisher suffixes from HTML titles, never rewrite substance.
            candidate = re.sub(r"\s+[|–—-]\s+(?:Primaria|Primăria|Consiliul|Instituția|IPJ|IGSU|ISU|SCM).*$", "", candidate, flags=re.I).strip()
            if title_ok(candidate, source, min_chars):
                return candidate
    return None


def parse_iso(value: str) -> datetime | None:
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except ValueError:
        return None


def extract_date(text: str) -> datetime | None:
    iso_patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<time\b[^>]*datetime=["\']([^"\']+)["\']',
        r'<meta\b(?=[^>]*(?:property|name)=["\'](?:article:published_time|date|datePublished)["\'])(?=[^>]*content=["\']([^"\']+)["\'])[^>]*>',
    ]
    for pattern in iso_patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            parsed = parse_iso(html.unescape(m.group(1)))
            if parsed:
                return parsed

    plain = clean_text(text[:500_000]).casefold()
    m = re.search(r"\b([0-3]?\d)[\s.\-/]+([01]?\d)[\s.\-/]+(20\d{2})\b", plain)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), 12, 0, tzinfo=TZ)
        except ValueError:
            pass
    month_names = "|".join(RO_MONTHS)
    m = re.search(rf"\b([0-3]?\d)\s+({month_names})\s+(20\d{{2}})\b", plain)
    if m:
        try:
            return datetime(int(m.group(3)), RO_MONTHS[m.group(2)], int(m.group(1)), 12, 0, tzinfo=TZ)
        except ValueError:
            pass
    return None


def fact_id(source_id: str, url: str) -> str:
    return f"auto-{source_id}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]}"


def discover_source(source: dict, now: datetime, policy: dict) -> tuple[list[dict], dict]:
    listing, final_url = fetch(source["url"])
    limit = int(policy.get("max_candidates_per_source", 12))
    min_chars = int(policy.get("min_title_chars", 24))
    age_limit = timedelta(hours=int(policy.get("candidate_max_age_hours", 72)))
    links = extract_listing_links(listing, final_url, source, limit, min_chars)
    facts: list[dict] = []
    examined = 0
    failures = 0
    for url, listing_title in links:
        examined += 1
        try:
            article, article_url = fetch(url, max_bytes=3_000_000)
            title = extract_article_title(article, listing_title, source, min_chars)
            published = extract_date(article)
            if not title or not published:
                continue
            age = now - published
            if age < timedelta(hours=-8) or age > age_limit:
                continue
            confidence = 94 if source.get("tier") == "T1" else 91
            valid_until = published + age_limit
            facts.append({
                "id": fact_id(source["id"], article_url),
                "status": "verified",
                "auto_generated": True,
                "auto_scope": "source_title_and_publication_date_only",
                "section": source["section"],
                "priority": int(source.get("priority", 75)),
                "confidence": confidence,
                "valid_from": published.isoformat(timespec="seconds"),
                "valid_until": valid_until.isoformat(timespec="seconds"),
                "slots": ["morning", "evening"],
                "headline": title,
                "dek": f"Publicat de {source['publisher']} la {published.strftime('%d.%m.%Y')}. VÂLCEA CLAR preia automat doar titlul, data și sursa primară; detaliile materiale rămân în verificare.",
                "paragraphs": [],
                "material_fact_gate": "PASS_TITLE_DATE_ONLY",
                "sources": [{
                    "name": source["publisher"],
                    "url": article_url,
                    "tier": source.get("tier", "T1"),
                }],
                "discovered_at": now.isoformat(timespec="seconds"),
            })
        except Exception:
            failures += 1
        time.sleep(0.12)
    # Stable order and URL/id dedupe.
    unique = {item["id"]: item for item in facts}
    result = sorted(unique.values(), key=lambda item: (-item["priority"], item["valid_from"], item["id"]), reverse=False)
    return result, {"source_id": source["id"], "listing_ok": True, "links_examined": examined, "article_failures": failures, "facts": len(result)}


def self_test() -> int:
    sample = '<html><head><meta property="article:published_time" content="2026-08-15T07:30:00+03:00"><title>Un anunț oficial suficient de descriptiv — Instituția</title></head><body><h1>Un anunț oficial suficient de descriptiv</h1></body></html>'
    assert extract_date(sample) == datetime(2026, 8, 15, 7, 30, tzinfo=TZ)
    source = {"generic_titles": [], "publisher": "X"}
    assert extract_article_title(sample, "x", source, 24) == "Un anunț oficial suficient de descriptiv"
    print("Autonomous news discovery self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    policy = registry.get("policy", {})
    now = datetime.now(TZ)
    all_facts: list[dict] = []
    health: list[dict] = []
    for source in registry.get("sources", []):
        try:
            facts, row = discover_source(source, now, policy)
            all_facts.extend(facts)
            health.append(row)
        except Exception as exc:
            health.append({"source_id": source["id"], "listing_ok": False, "error": f"{type(exc).__name__}: {exc}", "facts": 0})
        time.sleep(0.25)

    deduped = {item["id"]: item for item in all_facts}
    facts = sorted(deduped.values(), key=lambda item: (-item["priority"], item["id"]))
    output = {
        "schema_version": "1.0",
        "generated_at": now.isoformat(timespec="seconds"),
        "generator": "primary_source_title_date_zero_llm_v1",
        "facts": facts,
        "policy": {
            "llm_required": False,
            "external_paid_api_required": False,
            "autopublished_fields": ["source_title", "publication_date", "source_url"],
            "article_body_material_facts_autopublish": False,
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = {
        "schema_version": "1.0",
        "observed_at": now.isoformat(timespec="seconds"),
        "sources_total": len(health),
        "sources_ok": sum(1 for row in health if row.get("listing_ok")),
        "facts_admitted": len(facts),
        "sources": health,
    }
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "sources_ok": state["sources_ok"], "sources_total": state["sources_total"], "facts_admitted": len(facts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
