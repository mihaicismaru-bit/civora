#!/usr/bin/env python3
"""Resilient, fail-closed MIPE ingestion for PARTENER.EU.

The direct MIPE host is intermittently unreachable from GitHub-hosted runners.
This adapter therefore tries several transports while keeping the canonical
source URL on an official MIPE-managed host:

1. direct HTTPS / WordPress REST / RSS / sitemap;
2. the official MIPE Oportunitati-UE platform;
3. search/index transports for discovery of official canonical URLs only.

Only a successful direct fetch from the official canonical host may create or
refresh a published MIPE fact. Search/proxy copies are never factual sources.
Historical DIRECTLY verified feed items are preserved on outage.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
WEB_PATH = ROOT / "partener-eu" / "web" / "mipe-news.js"
REGISTRY_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_source_registry.json"
INDEX_PATH = ROOT / "partener-eu" / "web" / "index.html"
MIPE_RELAY_URL = os.getenv("MIPE_RELAY_URL", "https://partener-mipe-relay-mihaicismaru-6634s-projects.vercel.app/api/mipe").strip()

OFFICIAL_HOSTS = {
    "mfe.gov.ro",
    "www.mfe.gov.ro",
    "fonduri-ue.gov.ro",
    "www.fonduri-ue.gov.ro",
    "fonduri-ue.ro",
    "www.fonduri-ue.ro",
    "oportunitati-ue.gov.ro",
    "www.oportunitati-ue.gov.ro",
    "reporting.mysmis2021.gov.ro",
}

SEEDS = [
    "https://mfe.gov.ro/",
    "https://mfe.gov.ro/ghiduri_peos/",
    "https://mfe.gov.ro/ghiduri_pids/",
    "https://mfe.gov.ro/pdds/despre-program-programare/",
    "https://mfe.gov.ro/pnrr/",
    "https://oportunitati-ue.gov.ro/",
]

DISCOVERY_QUERIES = [
    "site:mfe.gov.ro apel ghid consultare corrigendum 2026",
    "site:mfe.gov.ro PEO PoIDS PDDS 2026",
    "site:oportunitati-ue.gov.ro finantare 2026",
]

USER_AGENT = "PARTENER.EU-CIVORA-MIPE-Resilient/2.0 (+https://partener.eu)"
MAX_BYTES = 5_000_000
MAX_CANDIDATES = 32
MAX_ITEMS = 60
MAX_SEARCH_RESULTS = 24

FUNDING_KEYWORDS = [
    "fonduri", "finanț", "finant", "apel", "ghid", "program", "proiect",
    "investi", "beneficiar", "grant", "alocare", "buget", "poids", "pids",
    "peo", "pdds", "pnrr", "coeziune", "consultare", "corrigendum", "termen",
    "eligibil", "mysmis", "fse+", "feder", "ftj", "tranziție justă",
    "step", "ajutor de stat", "ajutor de minimis",
]
EXCLUDE_HINTS = [
    "post vacant", "concurs recrutare", "declarație de avere", "declaratie de avere",
    "achiziție publică", "achizitie publica", "anunț de angajare", "anunt de angajare",
]
INDEX_PATHS = {
    "/", "/ghiduri_peos/", "/ghiduri_pids/", "/pdds/despre-program-programare/",
    "/pnrr/",
}
MONTHS_RO = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sept", "oct", "nov", "dec"]


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize(url: str, base: str | None = None) -> str | None:
    try:
        if base:
            url = urllib.parse.urljoin(base, url)
        p = urllib.parse.urlparse(url.strip())
        host = (p.hostname or "").lower()
        if p.scheme not in {"http", "https"} or host not in OFFICIAL_HOSTS:
            return None
        path = re.sub(r"/{2,}", "/", p.path or "/")
        # Tracking parameters are not part of canonical identity.
        query = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
        return urllib.parse.urlunparse(("https", host, path, "", urllib.parse.urlencode(query), ""))
    except Exception:
        return None


def is_official(url: str) -> bool:
    return canonicalize(url) is not None


def fetch(url: str, timeout: int = 24, attempts: int = 2, accept: str | None = None) -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept or "text/html,application/xhtml+xml,application/xml,application/json,text/plain;q=0.9,*/*;q=0.7",
        "Accept-Language": "ro,en;q=0.7",
        "Cache-Control": "no-cache",
    }
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    last = "unknown"
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
                data = response.read(MAX_BYTES)
                return {
                    "ok": True,
                    "status": getattr(response, "status", 200),
                    "url": response.geturl(),
                    "content_type": response.headers.get("Content-Type", ""),
                    "data": data,
                }
        except Exception as exc:  # noqa: BLE001 - persisted as source health evidence
            last = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
    return {"ok": False, "url": url, "error": last}


def fetch_first_party_relay(canonical: str) -> dict[str, Any]:
    """Fetch raw official bytes through a controlled PARTENER.EU relay.

    The relay cannot turn a third-party page into an official source. Both the
    requested canonical URL and the relay-reported final URL must remain on the
    official allowlist, and the body hash is recomputed locally.
    """
    if not MIPE_RELAY_URL:
        return {"ok": False, "error": "relay_disabled"}
    relay_target = MIPE_RELAY_URL + ("&" if "?" in MIPE_RELAY_URL else "?") + urllib.parse.urlencode({"url": canonical})
    response = fetch(relay_target, timeout=30, attempts=1, accept="application/json")
    if not response.get("ok"):
        return {"ok": False, "error": response.get("error", "relay_unavailable"), "relay": MIPE_RELAY_URL}
    try:
        payload = json.loads(response["data"].decode("utf-8", errors="strict"))
        requested = canonicalize(str(payload.get("canonicalUrl") or ""))
        final_url = canonicalize(str(payload.get("finalUrl") or payload.get("canonicalUrl") or ""))
        upstream_status = int(payload.get("upstreamStatus") or payload.get("status") or 0)
        encoded = str(payload.get("bodyBase64") or "")
        body = base64.b64decode(encoded, validate=True)
        claimed_hash = str(payload.get("sha256") or "").lower()
        local_hash = hashlib.sha256(body).hexdigest()
        if requested != canonical:
            raise ValueError("relay_canonical_mismatch")
        if not final_url or not is_official(final_url):
            raise ValueError("relay_final_url_not_official")
        if not 200 <= upstream_status < 400:
            raise ValueError(f"relay_upstream_status_{upstream_status}")
        if not body or len(body) > MAX_BYTES:
            raise ValueError("relay_body_size_invalid")
        if not claimed_hash or claimed_hash != local_hash:
            raise ValueError("relay_sha256_mismatch")
        return {
            "ok": True,
            "status": upstream_status,
            "url": final_url,
            "content_type": str(payload.get("contentType") or "application/octet-stream"),
            "data": body,
            "relay": MIPE_RELAY_URL,
            "relay_region": payload.get("relayRegion"),
            "relay_fetched_at": payload.get("fetchedAt"),
            "relay_sha256": local_hash,
        }
    except Exception as exc:  # noqa: BLE001 - persisted as transport evidence
        return {"ok": False, "error": f"relay_validation:{type(exc).__name__}:{exc}", "relay": MIPE_RELAY_URL}


def translate_original_url(url: str, base_canonical: str) -> str | None:
    """Map a Google Translate wrapper URL back to the official MIPE URL."""
    try:
        absolute = urllib.parse.urljoin(base_canonical, url)
        parsed = urllib.parse.urlparse(absolute)
        host = (parsed.hostname or "").lower()
        if host == "mfe-gov-ro.translate.goog":
            query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if not k.startswith("_x_tr_")]
            candidate = urllib.parse.urlunparse(("https", "mfe.gov.ro", parsed.path or "/", "", urllib.parse.urlencode(query), ""))
            return canonicalize(candidate)
        return canonicalize(absolute)
    except Exception:
        return None


def google_translate_url(canonical: str) -> str | None:
    parsed = urllib.parse.urlparse(canonical)
    if (parsed.hostname or "").lower() not in {"mfe.gov.ro", "www.mfe.gov.ro"}:
        return None
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query += [("_x_tr_sl", "ro"), ("_x_tr_tl", "en"), ("_x_tr_hl", "en")]
    return urllib.parse.urlunparse(("https", "mfe-gov-ro.translate.goog", parsed.path or "/", "", urllib.parse.urlencode(query), ""))


def meaningful_official_paths(links: Iterable[tuple[str, str]], base: str, translated: bool = False) -> set[str]:
    paths: set[str] = set()
    for href, _label in links:
        official = translate_original_url(href, base) if translated else canonicalize(href, base)
        if not official:
            continue
        path = urllib.parse.urlparse(official).path.rstrip("/") or "/"
        if path in {"/", "/contact", "/despre-noi"}:
            continue
        if any(path.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".css", ".js")):
            continue
        paths.add(path)
    return paths


def fetch_dual_relay(canonical: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Retrieve a canonical MIPE page through two independent live relays.

    Jina supplies structured text and original official links. Google Translate
    supplies an independent live HTML fetch. Publication is allowed only when
    the Reader source URL is exact, the translated page has MIPE signatures,
    and the two views share meaningful official link paths.
    """
    translate_url = google_translate_url(canonical)
    if not translate_url:
        return None, {"target": canonical, "ok": False, "transport": "dual-relay", "error": "translate_mapping_unavailable"}

    reader_endpoint = "https://r.jina.ai/" + canonical
    reader = fetch(reader_endpoint, timeout=22, attempts=1, accept="text/plain,text/markdown,*/*")
    translated = fetch(translate_url, timeout=22, attempts=1, accept="text/html,application/xhtml+xml,*/*;q=0.7")
    evidence: dict[str, Any] = {
        "target": canonical,
        "ok": False,
        "transport": "canonical-dual-relay",
        "readerUrl": reader_endpoint,
        "translateUrl": translate_url,
        "readerError": reader.get("error"),
        "translateError": translated.get("error"),
    }
    if not reader.get("ok") or not translated.get("ok"):
        return None, evidence

    parsed_reader = parse_reader(reader["data"], canonical)
    parsed_translate = parse_html(translated["data"])
    if not parsed_reader or canonicalize(parsed_reader.get("canonical") or "") != canonical:
        evidence["error"] = "reader_source_mismatch"
        return None, evidence

    raw_translate = translated["data"].decode("utf-8", errors="ignore").lower()
    signatures = {
        "mipeHost": "mfe.gov.ro" in raw_translate,
        "ministry": ("ministerul investi" in raw_translate or "ministry of investment" in raw_translate),
        "wordpress": "wp-content" in raw_translate,
    }
    if sum(bool(value) for value in signatures.values()) < 2:
        evidence.update({"error": "translate_official_signature_insufficient", "signatures": signatures})
        return None, evidence

    reader_paths = meaningful_official_paths(parsed_reader.get("links", []), canonical)
    translate_paths = meaningful_official_paths(parsed_translate.get("links", []), canonical, translated=True)
    shared = sorted(reader_paths & translate_paths)
    target_path = urllib.parse.urlparse(canonical).path.rstrip("/") or "/"
    target_specific = [path for path in shared if path == target_path or path.startswith(target_path + "/") or path.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".7z"))]

    # Template-heavy pages still share many official links. Require either one
    # target/document path or at least five independent shared official paths.
    if not target_specific and len(shared) < 5:
        evidence.update({
            "error": "dual_relay_link_consensus_insufficient",
            "sharedOfficialPathCount": len(shared),
            "sharedOfficialPaths": shared[:20],
            "signatures": signatures,
        })
        return None, evidence

    evidence.update({
        "ok": True,
        "transport": "canonical-dual-relay-corroborated",
        "verification": "CANONICAL_DUAL_RELAY_CORROBORATED",
        "readerSha256": hashlib.sha256(reader["data"]).hexdigest(),
        "translateSha256": hashlib.sha256(translated["data"]).hexdigest(),
        "readerBytes": len(reader["data"]),
        "translateBytes": len(translated["data"]),
        "sharedOfficialPathCount": len(shared),
        "sharedOfficialPaths": shared[:30],
        "targetSpecificPaths": target_specific[:20],
        "signatures": signatures,
    })
    parsed_reader["canonical"] = canonical
    return parsed_reader, evidence


def reader_url(target: str) -> str:
    # Reader accepts the original URL after the prefix. http is intentionally
    # tried because Reader handles the upstream redirect itself and some MIPE
    # routes are unreachable to GitHub runners only on direct TLS.
    p = urllib.parse.urlparse(target)
    source = urllib.parse.urlunparse(("http", p.netloc, p.path, "", p.query, ""))
    return "https://r.jina.ai/" + source


def search_url(query: str) -> str:
    return "https://s.jina.ai/" + urllib.parse.quote(query, safe="")


class HTMLDoc(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.title: list[str] = []
        self.h1: list[str] = []
        self.paragraphs: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.meta: dict[str, str] = {}
        self.times: list[str] = []
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self.stack.append(tag)
        if tag == "a":
            self._href = a.get("href")
            self._anchor = []
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta[key] = str(a["content"])
        elif tag == "time" and a.get("datetime"):
            self.times.append(str(a["datetime"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, clean_text(" ".join(self._anchor))))
            self._href = None
            self._anchor = []
        if tag in self.stack:
            idx = len(self.stack) - 1 - self.stack[::-1].index(tag)
            self.stack = self.stack[:idx]

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        current = self.stack[-1] if self.stack else ""
        if current == "title":
            self.title.append(data)
        elif current == "h1":
            self.h1.append(data)
        elif current in {"p", "li"}:
            self.paragraphs.append(data)
        if self._href is not None:
            self._anchor.append(data)


def parse_html(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    parser = HTMLDoc()
    parser.feed(text)
    title = clean_text(
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or " ".join(parser.h1)
        or " ".join(parser.title)
    )
    description = clean_text(
        parser.meta.get("description")
        or parser.meta.get("og:description")
        or parser.meta.get("twitter:description")
    )
    body = clean_text(" ".join(parser.paragraphs))
    return {
        "title": title,
        "description": description,
        "body": body,
        "links": parser.links,
        "meta": parser.meta,
        "times": parser.times,
        "raw": text,
    }


READER_BOILERPLATE = (
    "skip to main content", "adaugă ca sursă preferată", "adauga ca sursa preferata",
    "bine ați venit pe site", "bine ati venit pe site", "acest site folosește",
    "acest site foloseste", "politica de confidențialitate", "politica de confidentialitate",
    "urmărește-ne", "urmareste-ne", "toate drepturile rezervate", "copyright",
    "facebook", "linkedin", "youtube", "instagram", "sitemap", "meniu principal",
)
PUBLISHABLE_EVENT_KINDS = {
    "CALL_OPENED", "DEADLINE_EXTENDED", "GUIDE_PUBLISHED", "GUIDE_MODIFIED",
    "CONSULTATION_OPENED", "RESULTS_PUBLISHED",
}
STATIC_TITLE_HINTS = (
    "poveste de succes", "povești de succes", "povesti de succes",
    "politica de coeziune", "alte finanțări și instrumente financiare",
    "alte finantari si instrumente financiare", "hartă site", "harta site",
    "programul dezvoltare durabilă și tranziție justă – ministerul",
    "programul dezvoltare durabila si tranzitie justa – ministerul",
)
OFFICIAL_UPDATE_ACTIONS = (
    "anunț", "anunt", "finanț", "finant", "buget", "investi", "apel",
    "contract", "plată", "plata", "cerere", "negocier", "reform",
    "aprobat", "publicat", "lansat", "actualizat", "modificat",
)


def markdown_plain(value: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[`*_#>|]+", " ", value)
    return clean_text(value)


def is_boilerplate(value: str) -> bool:
    plain = markdown_plain(value)
    low = plain.lower()
    if len(plain) < 55:
        return True
    if any(marker in low for marker in READER_BOILERPLATE):
        return True
    alpha = sum(ch.isalpha() for ch in plain)
    return alpha < max(30, len(plain) // 3)


def best_reader_summary(body_md: str, title: str) -> str:
    title_terms = {w for w in re.findall(r"[a-zăâîșț0-9]+", title.lower()) if len(w) >= 5}
    ranked: list[tuple[int, int, str]] = []
    for index, paragraph in enumerate(re.split(r"\n\s*\n", body_md)):
        candidate = markdown_plain(paragraph)
        if is_boilerplate(candidate) or candidate.lower() == title.lower():
            continue
        low = candidate.lower()
        relevance = sum(3 for keyword in FUNDING_KEYWORDS if keyword in low)
        overlap = sum(1 for term in title_terms if term in low)
        # Prefer early, title-related explanatory paragraphs, not navigation or footer text.
        score = relevance + overlap + max(0, 8 - index // 4)
        ranked.append((score, -index, candidate[:900]))
    if not ranked:
        return ""
    ranked.sort(reverse=True)
    return ranked[0][2]


def parse_reader(raw: bytes, target: str) -> dict[str, Any] | None:
    text = raw.decode("utf-8", errors="replace")
    if len(text.strip()) < 180:
        return None
    title_match = re.search(r"(?mi)^Title:\s*(.+)$", text)
    source_match = re.search(r"(?mi)^URL Source:\s*(.+)$", text)
    date_match = re.search(r"(?mi)^(?:Published Time|Published Date|Date):\s*(.+)$", text)
    marker = re.search(r"(?mi)^Markdown Content:\s*$", text)
    body_md = text[marker.end():] if marker else text
    source = canonicalize(source_match.group(1).strip()) if source_match else canonicalize(target)
    target_canonical = canonicalize(target)
    if not source or not target_canonical:
        return None
    # Reader may normalize www and trailing slash; canonical path must still be
    # the requested official page or another official redirect target.
    if urllib.parse.urlparse(source).hostname not in OFFICIAL_HOSTS:
        return None
    title = clean_text(title_match.group(1)) if title_match else ""
    if not title:
        heading = re.search(r"(?m)^#\s+(.+)$", body_md)
        title = clean_text(heading.group(1)) if heading else ""
    links: list[tuple[str, str]] = []
    for anchor, href in re.findall(r"\[([^\]]{0,250})\]\((https?://[^)\s]+)\)", body_md):
        links.append((href, clean_text(anchor)))
    # Include raw official URLs that are not expressed as markdown links.
    for href in re.findall(r"https?://[^\s<>()\]]+", body_md):
        href = href.rstrip(".,;:\"'")
        if is_official(href):
            links.append((href, ""))
    body = clean_text(re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", body_md))
    body = clean_text(re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body))
    description = best_reader_summary(body_md, title)
    return {
        "title": title,
        "description": description,
        "body": body,
        "links": links,
        "meta": {},
        "times": [date_match.group(1).strip()] if date_match else [],
        "raw": text,
        "canonical": source,
    }


def parse_date(*values: str | None, body: str = "") -> dt.date | None:
    candidates = [v for v in values if v]
    candidates += re.findall(r"\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\b", body[:8000])
    candidates += re.findall(r"\b(\d{1,2}[./-]\d{1,2}[./-]20\d{2})\b", body[:8000])
    month_map = {
        "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5,
        "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10,
        "noiembrie": 11, "decembrie": 12,
    }
    for value in candidates:
        text = clean_text(value)
        try:
            return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return dt.datetime.strptime(text[:10], fmt).date()
            except Exception:
                pass
        m = re.search(r"\b(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})\b", text.lower())
        if m:
            return dt.date(int(m.group(3)), month_map[m.group(2)], int(m.group(1)))
    return None


def ro_date(value: dt.date | None) -> str:
    if not value:
        return "Data publicării neconfirmată"
    return f"{value.day} {MONTHS_RO[value.month - 1]} {value.year}"


def score_relevance(title: str, description: str, body: str, url: str) -> int:
    hay = " ".join([title, description, body[:5000], url]).lower()
    score = sum(3 if keyword in title.lower() else 1 for keyword in FUNDING_KEYWORDS if keyword in hay)
    if any(excluded in title.lower() for excluded in EXCLUDE_HINTS):
        score -= 12
    return score


def classify_tag(title: str, url: str = "", context: str = "") -> str:
    # URL and title outrank the page body because MIPE templates contain links
    # to every programme and can otherwise contaminate programme classification.
    primary = f"{title} {url}".lower()
    secondary = context[:800].lower()
    if "/ghiduri_peos/" in primary or re.search(r"\bpeo\b", primary) or "educație și ocupare" in primary or "educatie si ocupare" in primary:
        return "PEO"
    if "/ghiduri_pids/" in primary or "poids" in primary or re.search(r"\bpids\b", primary) or "incluziune și demnitate socială" in primary or "incluziune si demnitate sociala" in primary:
        return "PoIDS"
    if "/pdds/" in primary or "programul dezvoltare durabilă" in primary or "programul dezvoltare durabila" in primary:
        return "PDDS"
    if "tranziție justă" in primary or "tranzitie justa" in primary or re.search(r"\bptj\b", primary):
        return "PTJ"
    if "programul sănătate" in primary or "programul sanatate" in primary:
        return "SĂNĂTATE"
    if "pnrr" in primary or "redresare și reziliență" in primary or "redresare si rezilienta" in primary or "planul-national-de-redresare" in primary:
        return "PNRR"
    if re.search(r"\bpr[ -](?:nord|sud|vest|centru|bucure)", primary) or "program regional" in primary:
        return "REGIONAL"
    combined = f"{primary} {secondary}"
    if re.search(r"\bpeo\b", combined):
        return "PEO"
    if "poids" in combined or re.search(r"\bpids\b", combined):
        return "PoIDS"
    if "pdds" in combined:
        return "PDDS"
    if "programul sănătate" in combined or "programul sanatate" in combined:
        return "SĂNĂTATE"
    if "program regional" in combined or "programul regiunea" in combined or re.search(r"\badr\s+(?:centru|nord|sud|vest|bucure)", combined):
        return "REGIONAL"
    return "MIPE"


def classify_kind(title: str, body: str) -> str:
    text = f"{title} {body[:1800]}".lower()
    if ("prelung" in text or "extind" in text) and any(token in text for token in ("termen", "perioada", "depunere", "deadline")):
        return "DEADLINE_EXTENDED"
    if "corrigendum" in text or "corrigend" in text or "rectific" in title.lower():
        return "GUIDE_MODIFIED"
    if "consultare" in text and ("ghid" in text or "apel" in text):
        return "CONSULTATION_OPENED"
    # An explicit call launch outranks generic mentions of a guide. Launch
    # pages commonly link the guide and would otherwise be misclassified as a
    # guide publication merely because both words appear in the same page.
    if any(token in text for token in ("apelul este deschis", "apel deschis", "lansarea apelului", "s-a lansat apelul", "se lansează apelul", "se lanseaza apelul")):
        return "CALL_OPENED"
    if "ghid" in text and any(token in text for token in ("actualiz", "modific", "revizuit")):
        return "GUIDE_MODIFIED"
    if "ghidul solicitantului" in title.lower() or ("ghid" in text and any(token in text for token in ("publicat", "aprobat", "final", "lansat"))):
        return "GUIDE_PUBLISHED"
    if "rezultat" in text or "lista proiectelor" in text:
        return "RESULTS_PUBLISHED"
    return "OFFICIAL_UPDATE"


def decision_useful(title: str, kind: str, date: dt.date | None, path: str) -> bool:
    low = title.lower()
    normalized_path = path.rstrip("/") or "/"
    if any(hint in low for hint in STATIC_TITLE_HINTS):
        return False
    if path.lower().endswith(".xml") or "sitemap" in path.lower():
        return False
    if normalized_path in {"/programul-dezvoltare-durabila-si-tranzitie-justa"}:
        return False
    if kind in PUBLISHABLE_EVENT_KINDS:
        return True
    if kind != "OFFICIAL_UPDATE" or not date:
        return False
    if date < now_utc().date() - dt.timedelta(days=180):
        return False
    if path.rstrip("/") in {"", "/minister/perioade-de-programare", "/programe-de-finantare/planul-national-de-redresare-si-rezilienta", "/programe-de-finantare/alte-finantari-si-instrumente-financiare"}:
        return False
    return any(token in low for token in OFFICIAL_UPDATE_ACTIONS)


def previous_item_useful(item: dict[str, Any]) -> bool:
    verification = str(item.get("verification") or "")
    transport = str(item.get("retrievalTransport") or "")
    if verification == "CANONICAL_OFFICIAL_FETCH":
        return True
    return transport.startswith("direct") or "dual-relay-corroborated" in transport


def item_id(url: str, title: str) -> str:
    return hashlib.sha256(f"{url}\n{title}".encode()).hexdigest()[:20]


def document_links(links: Iterable[tuple[str, str]], base: str) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, label in links:
        url = canonicalize(href, base)
        if not url or url in seen:
            continue
        path = urllib.parse.urlparse(url).path.lower()
        if not re.search(r"\.(?:pdf|docx?|xlsx?|csv|zip|7z|rar)(?:$|/)", path):
            continue
        seen.add(url)
        clean_label = re.sub(r"[`*_#]+", "", clean_text(label)).strip()
        documents.append({"name": clean_label or Path(path).name or "Document oficial", "url": url})
    return documents[:25]


def candidate_links(links: Iterable[tuple[str, str]], base: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, label in links:
        url = canonicalize(href, base)
        if not url or url in seen:
            continue
        if re.search(r"\.(?:jpg|jpeg|png|gif|svg|webp|pdf|docx?|xlsx?|zip|7z|rar)(?:\?|$)", url, re.I):
            continue
        if score_relevance(label, "", "", url) <= 0:
            continue
        seen.add(url)
        out.append({"url": url, "title_hint": label, "discovery": "page-link"})
    return out


def fetch_document(target: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    canonical = canonicalize(target)
    if not canonical:
        return None, {"target": target, "ok": False, "error": "non_official_target"}

    direct = fetch(canonical, timeout=6, attempts=1)
    if direct.get("ok"):
        content_type = direct.get("content_type", "").lower()
        try:
            if "json" in content_type:
                return {"json": json.loads(direct["data"].decode("utf-8", errors="replace")), "canonical": canonical}, {"target": canonical, "ok": True, "transport": "direct-json"}
            if "xml" in content_type or direct["data"].lstrip().startswith(b"<?xml"):
                return {"xml": direct["data"], "canonical": canonical}, {"target": canonical, "ok": True, "transport": "direct-xml"}
            parsed = parse_html(direct["data"])
            parsed["canonical"] = canonicalize(direct.get("url") or canonical) or canonical
            return parsed, {"target": canonical, "ok": True, "transport": "direct-https"}
        except Exception as exc:  # noqa: BLE001
            direct = {"ok": False, "error": f"direct_parse:{type(exc).__name__}:{exc}"}

    dual_parsed, dual_evidence = fetch_dual_relay(canonical)
    if dual_parsed is not None:
        dual_evidence["directError"] = direct.get("error")
        return dual_parsed, dual_evidence

    relay = fetch_first_party_relay(canonical)
    if relay.get("ok"):
        content_type = str(relay.get("content_type", "")).lower()
        evidence = {
            "target": canonical,
            "ok": True,
            "transport": "direct-canonical-via-first-party-relay",
            "directError": direct.get("error"),
            "relay": relay.get("relay"),
            "relayRegion": relay.get("relay_region"),
            "relayFetchedAt": relay.get("relay_fetched_at"),
            "sha256": relay.get("relay_sha256"),
        }
        try:
            if "json" in content_type:
                return {"json": json.loads(relay["data"].decode("utf-8", errors="replace")), "canonical": canonical}, evidence
            if "xml" in content_type or relay["data"].lstrip().startswith(b"<?xml"):
                return {"xml": relay["data"], "canonical": canonical}, evidence
            parsed = parse_html(relay["data"])
            parsed["canonical"] = canonicalize(relay.get("url") or canonical) or canonical
            return parsed, evidence
        except Exception as exc:  # noqa: BLE001
            relay = {"ok": False, "error": f"relay_parse:{type(exc).__name__}:{exc}", "relay": relay.get("relay")}

    return None, {
        "target": canonical,
        "ok": False,
        "transport": "direct+first-party-relay",
        "directError": direct.get("error"),
        "relayError": relay.get("error"),
        "relay": relay.get("relay"),
        "policy": "search-discovery-only-when-official-byte-transports-unavailable",
    }


def candidates_from_json(payload: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("items") or payload.get("data") or payload.get("results") or []
    else:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        link = row.get("link") or row.get("url") or row.get("canonical_url")
        title = row.get("title") or row.get("name") or ""
        if isinstance(title, dict):
            title = title.get("rendered") or title.get("text") or ""
        excerpt = row.get("excerpt") or row.get("description") or ""
        if isinstance(excerpt, dict):
            excerpt = excerpt.get("rendered") or ""
        url = canonicalize(str(link or ""))
        if url:
            out.append({
                "url": url,
                "title_hint": clean_text(title),
                "excerpt_hint": clean_text(excerpt),
                "date_hint": str(row.get("date") or row.get("published_at") or ""),
                "discovery": "official-json",
            })
    return out


def candidates_from_xml(raw: bytes) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return out
    for element in root.iter():
        if not element.tag.endswith("loc") or not element.text:
            continue
        url = canonicalize(clean_text(element.text))
        if url:
            out.append({"url": url, "discovery": "official-xml"})
    for item in root.findall(".//item"):
        url = canonicalize(clean_text(item.findtext("link")))
        if url:
            out.append({
                "url": url,
                "title_hint": clean_text(item.findtext("title")),
                "date_hint": clean_text(item.findtext("pubDate")),
                "discovery": "official-feed",
            })
    return out


def search_discovery() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    candidates: list[dict[str, str]] = []
    health: list[dict[str, Any]] = []
    for query in DISCOVERY_QUERIES:
        result = fetch(search_url(query), timeout=18, attempts=1, accept="text/plain,text/markdown,*/*")
        health.append({
            "query": query,
            "ok": bool(result.get("ok")),
            "transport": "jina-search-discovery-only",
            "error": result.get("error"),
        })
        if not result.get("ok"):
            continue
        text = result["data"].decode("utf-8", errors="replace")
        for url in re.findall(r"https?://[^\s<>()\]\"']+", text):
            canonical = canonicalize(url.rstrip(".,;:"))
            if canonical:
                candidates.append({"url": canonical, "discovery": "jina-search-official-url"})
                if len(candidates) >= MAX_SEARCH_RESULTS:
                    break
    return candidates, health


def seed_candidates() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    candidates: list[dict[str, str]] = []
    health: list[dict[str, Any]] = []

    endpoint_seeds: list[str] = []
    for base in ("https://mfe.gov.ro", "https://oportunitati-ue.gov.ro"):
        endpoint_seeds.extend([
            base + "/wp-json/wp/v2/posts?per_page=50&orderby=modified&order=desc&_fields=link,date,modified,title,excerpt",
            base + "/feed/",
            base + "/wp-sitemap.xml",
            base + "/sitemap.xml",
        ])

    for target in [*SEEDS, *endpoint_seeds]:
        parsed, result = fetch_document(target)
        health.append(result)
        if not parsed:
            continue
        canonical = parsed.get("canonical") or canonicalize(target) or target
        if "json" in parsed:
            candidates.extend(candidates_from_json(parsed["json"]))
            continue
        if "xml" in parsed:
            candidates.extend(candidates_from_xml(parsed["xml"]))
            continue
        linked_candidates = candidate_links(parsed.get("links", []), canonical)
        if canonicalize(target) == "https://mfe.gov.ro/pdds/despre-program-programare/":
            linked_candidates = [
                candidate for candidate in linked_candidates
                if urllib.parse.urlparse(candidate["url"]).hostname == "mfe.gov.ro"
                and urllib.parse.urlparse(candidate["url"]).path.startswith("/pdds/")
            ]
        candidates.extend(linked_candidates)
        # Seed pages themselves are retained as discovery candidates only. A
        # specific page may still be published if it is not an index path.
        candidates.append({"url": canonical, "title_hint": parsed.get("title", ""), "discovery": result.get("transport", "seed")})
    return candidates, health


def make_item(candidate: dict[str, str], cache: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    url = candidate["url"]
    if url not in cache:
        cache[url] = fetch_document(url)
    parsed, health = cache[url]
    if not parsed or "json" in parsed or "xml" in parsed:
        return None, health

    canonical = parsed.get("canonical") or url
    path = urllib.parse.urlparse(canonical).path or "/"
    title = clean_text(parsed.get("title") or candidate.get("title_hint"))
    description = clean_text(parsed.get("description") or candidate.get("excerpt_hint"))
    body = clean_text(parsed.get("body"))
    if not title or len(title) < 8 or len(body) < 120:
        return None, health

    score = score_relevance(title, description, body, canonical)
    kind = classify_kind(title, body)
    if score < 3:
        return None, health
    if path in INDEX_PATHS and kind == "OFFICIAL_UPDATE":
        return None, health
    if kind == "OFFICIAL_UPDATE" and score < 7:
        return None, health

    meta = parsed.get("meta") or {}
    date = None
    for key in ("article:published_time", "date", "datepublished", "dc.date", "og:published_time"):
        if meta.get(key):
            date = parse_date(meta.get(key), body=body)
            if date:
                break
    if not date:
        date = parse_date(*(parsed.get("times") or []), candidate.get("date_hint"), body=body)

    if not decision_useful(title, kind, date, path):
        return None, health

    documents = document_links(parsed.get("links", []), canonical)
    summary = clean_text(description)
    if is_boilerplate(summary):
        summary = ""
    if not summary:
        summary = f"Actualizare oficială MIPE: {title}."
        if documents:
            summary += f" Pagina include {len(documents)} documente oficiale pentru verificare."
    if path.rstrip("/") in {"/peos/anunturi", "/pids/anunturi", "/poids/anunturi"} and documents:
        material = [d["name"] for d in documents if "lista plăților" not in d["name"].lower() and "lista platilor" not in d["name"].lower()]
        highlights = material[:3] or [d["name"] for d in documents[:3]]
        summary = f"Pagina oficială {classify_tag(title, canonical, description)} a fost actualizată și include {len(documents)} documente oficiale. Cele mai relevante elemente observate: " + "; ".join(highlights) + "."
    summary = summary[:900]
    transport = health.get("transport", "unknown")
    tier = "T1_DUAL_RELAY_CORROBORATED" if "dual-relay-corroborated" in transport else ("T1_RELAY_ATTESTED" if "first-party-relay" in transport else ("T1" if transport.startswith("direct") else "T1_PROXY_TRANSPORT"))
    observed = now_utc().isoformat()
    item = {
        "id": item_id(canonical, title),
        "title": title[:360],
        "url": canonical,
        "date": date.isoformat() if date else "",
        "dateLabel": ro_date(date),
        "dateConfidence": "OFFICIAL_PAGE" if date else "OBSERVED_ONLY",
        "summary": summary,
        "tag": classify_tag(title, canonical, description),
        "kind": kind,
        "tier": tier,
        "source": "MIPE",
        "observedAt": observed,
        "relevanceScore": score,
        "discovery": candidate.get("discovery", "crawl"),
        "retrievalTransport": transport,
        "decisionUseful": True,
        "documents": documents,
    }
    return item, health


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"items": [], "runs": []}
    except Exception:
        return {"items": [], "runs": []}


def write_outputs(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run = state["lastRun"]
    payload = {
        "status": state["status"],
        "asOf": run["observedAt"],
        "source": "MIPE official web properties",
        "roots": run.get("roots", []),
        "searchTransports": run.get("searchTransports", []),
        "itemCount": len(state.get("items", [])),
        "currentVerifiedCount": run.get("currentVerifiedCount", 0),
        "transportMode": run.get("transportMode", "unavailable"),
        "lastKnownGoodPreserved": run.get("lastKnownGoodPreserved", False),
    }
    js = "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
    js += "window.PARTENER_DATA.mipeIngestion=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    js += "window.PARTENER_DATA.mipeNews=" + json.dumps(state.get("items", []), ensure_ascii=False, separators=(",", ":")) + ";\n"
    WEB_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_PATH.write_text(js, encoding="utf-8")

    # GitHub Pages may cache static JavaScript by URL. Advance only the MIPE
    # feed and adapter query versions after a completed ingest so every browser
    # receives the newly persisted feed without invalidating unrelated assets.
    if INDEX_PATH.exists():
        index = INDEX_PATH.read_text(encoding="utf-8")
        version = re.sub(r"[^0-9]", "", run["observedAt"])[:14]
        updated = re.sub(r'(mipe-news\.js\?v=)[^"\']+', rf'\g<1>{version}', index)
        updated = re.sub(r'(mipe-news-adapter\.js\?v=)[^"\']+', rf'\g<1>{version}', updated)
        if updated != index:
            INDEX_PATH.write_text(updated, encoding="utf-8")


def write_registry(run: dict[str, Any]) -> None:
    records = []
    for result in run.get("roots", []):
        target = result.get("target")
        if not target:
            continue
        records.append({
            "sourceId": "mipe-" + hashlib.sha1(target.encode()).hexdigest()[:12],
            "institution": "Ministerul Investițiilor și Proiectelor Europene",
            "sourceType": "official_web",
            "canonicalUrl": target,
            "trustClass": "T1",
            "monitoringFrequency": "hourly",
            "extractionMethod": result.get("transport", "unavailable"),
            "lastSuccessfulRetrieval": run["observedAt"] if result.get("ok") else None,
            "lastChangeDetected": run["observedAt"] if run.get("currentVerifiedCount") else None,
            "healthStatus": "UP" if result.get("ok") else "DEGRADED",
            "lastError": result.get("error") or result.get("directError") or result.get("proxyError"),
        })
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps({"asOf": run["observedAt"], "sources": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    previous_state = load_state()
    previous_by_url: dict[str, dict[str, Any]] = {}
    for old_item in previous_state.get("items", []):
        old_url = old_item.get("url")
        if not old_url:
            continue
        normalized = dict(old_item)
        # Items created by pre-v2 ingestion are preserved, but they must still
        # satisfy the current provenance contract. The marker is explicit and
        # never pretends that an old item was fetched in the current run.
        normalized.setdefault("retrievalTransport", "legacy-preserved")
        if normalized.get("verification") == "CANONICAL_OFFICIAL_FETCH" and normalized.get("retrievalTransport") == "legacy-preserved":
            normalized["retrievalTransport"] = "direct-canonical-preserved"
        normalized.setdefault("tier", "T1_LEGACY_PRESERVED")
        normalized.setdefault("observedAt", previous_state.get("lastRun", {}).get("observedAt", ""))
        normalized.setdefault("documents", [])
        if previous_item_useful(normalized):
            previous_by_url[old_url] = normalized

    candidates, root_health = seed_candidates()
    search_candidates, search_health = search_discovery()
    candidates.extend(search_candidates)

    # Include previous canonical URLs so that material changes can be detected
    # even when discovery sources are temporarily sparse.
    candidates.extend({"url": url, "discovery": "previous-feed-refresh"} for url in previous_by_url)

    dedup: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        url = canonicalize(candidate.get("url", ""))
        if not url:
            continue
        candidate["url"] = url
        old = dedup.get(url)
        if not old or len(candidate.get("title_hint", "")) > len(old.get("title_hint", "")):
            dedup[url] = candidate

    priority = {
        "official-json": 0,
        "official-feed": 1,
        "page-link": 2,
        "jina-search-official-url": 3,
        "official-xml": 4,
        "previous-feed-refresh": 5,
    }
    queue = sorted(
        dedup.values(),
        key=lambda candidate: (
            priority.get(candidate.get("discovery", ""), 8),
            -score_relevance(candidate.get("title_hint", ""), candidate.get("excerpt_hint", ""), "", candidate["url"]),
        ),
    )[:MAX_CANDIDATES]

    current: list[dict[str, Any]] = []
    page_health: list[dict[str, Any]] = []

    def fetch_candidate(candidate: dict[str, str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        # Candidate URLs are deduplicated before this point; a private cache per
        # worker avoids shared mutable state while bounding wall-clock latency.
        return make_item(candidate, {})

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="mipe-fetch") as pool:
        for item, health in pool.map(fetch_candidate, queue):
            page_health.append(health)
            if item:
                current.append(item)

    merged = dict(previous_by_url)
    for item in current:
        merged[item["url"]] = item

    def sort_key(item: dict[str, Any]) -> tuple[str, str]:
        date = item.get("date") or "0000-00-00"
        return date, item.get("observedAt", "")

    items = sorted(merged.values(), key=sort_key, reverse=True)[:MAX_ITEMS]
    successful = [result for result in [*root_health, *page_health] if result.get("ok")]
    direct_success = any(str(result.get("transport", "")).startswith("direct") or "dual-relay-corroborated" in str(result.get("transport", "")) for result in successful)
    proxy_success = any("jina-reader" in str(result.get("transport", "")) for result in successful)

    if current and direct_success:
        status = "OK"
        transport_mode = "direct"
    elif items and direct_success:
        status = "OK_NO_NEW_RELEVANT_ITEMS"
        transport_mode = "direct"
    elif items:
        status = "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"
        transport_mode = "direct-unavailable"
    else:
        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"
        transport_mode = "direct-unavailable"

    observed = now_utc().isoformat()
    run = {
        "observedAt": observed,
        "status": status,
        "roots": root_health,
        "searchTransports": search_health,
        "candidateCount": len(dedup),
        "fetchedCandidateCount": len(queue),
        "currentVerifiedCount": len(current),
        "publishedItemCount": len(items),
        "transportMode": transport_mode,
        "lastKnownGoodPreserved": bool(previous_by_url and not current),
        "directSuccessCount": sum(1 for result in successful if str(result.get("transport", "")).startswith("direct")),
        "proxySuccessCount": sum(1 for result in successful if "jina-reader" in str(result.get("transport", ""))),
    }
    runs = (previous_state.get("runs") or [])[-59:] + [run]
    output = {"status": status, "lastRun": run, "items": items, "runs": runs}
    write_outputs(output)
    write_registry(run)
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
