#!/usr/bin/env python3
"""Resilient MIPE/MySMIS ingestion for PARTENER.EU.

Flow: index discovery (URLs only) -> verified official fetch -> strict parser and
change detector -> atomic News feed update.  Search snippets, mirrors, invalid
TLS responses and challenge pages can never become facts.  If all official
sources fail, the live feed is left byte-for-byte untouched.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import json
import os
import re
import socket
import subprocess
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

from mipe_core_v2 import (
    OFFICIAL_HOSTS,
    PRIORITY_PDDS_SEED,
    build_page_item,
    clean,
    date_label,
    extract_html_document,
    fold,
    health_fingerprint,
    in_pdds_scope,
    iso_z,
    merge_feed_items,
    normalize_url,
    now_utc,
    parse_datetime,
    parse_feed_js,
    relevance_score,
    render_feed_js,
    sha256_hex,
    source_scope,
    validate_item,
    verify_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST_DIR = REPO_ROOT / "partener-eu" / "ingest"
STATE_DIR = INGEST_DIR / "state"
WEB_DIR = REPO_ROOT / "partener-eu" / "web"
STATE_PATH = STATE_DIR / "mipe_state_v2.json"
HEALTH_PATH = STATE_DIR / "mipe_health.json"
DISCOVERY_PATH = STATE_DIR / "mipe_discovered_urls.json"
FEED_PATH = WEB_DIR / "mipe-news.js"
RELAY_INBOX = INGEST_DIR / "relay_inbox"

UA = "PARTENER.EU-CIVORA-MIPE-Ingest/2.0 (+https://partener.eu)"
MAX_BODY_BYTES = 14 * 1024 * 1024
MAX_PDDS_PAGES = int(os.environ.get("MIPE_MAX_PDDS_PAGES", "90"))
MAX_BROAD_PAGES = int(os.environ.get("MIPE_MAX_BROAD_PAGES", "45"))

MYSMIS_BASE = "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021"
MYSMIS_REGISTRY_URL = MYSMIS_BASE + "/finantari-programe-2021-2027"
MYSMIS_HOME_URL = MYSMIS_BASE + "/home"
MYSMIS_FALLBACK_REGISTRY = "https://resurse.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"

STRUCTURED_URLS = [
    MYSMIS_REGISTRY_URL,
    MYSMIS_HOME_URL,
    "https://mfe.gov.ro/wp-sitemap.xml",
    "https://mfe.gov.ro/sitemap.xml",
    "https://mfe.gov.ro/feed/",
    "https://mfe.gov.ro/wp-json/",
    "https://mfe.gov.ro/wp-json/wp/v2/posts?per_page=50&_fields=link,date,modified,title,excerpt",
    "https://mfe.gov.ro/wp-json/wp/v2/pages?per_page=50&_fields=link,date,modified,title,excerpt",
    "https://mfe.gov.ro/wp-json/wp/v2/media?per_page=50&orderby=modified&order=desc&_fields=link,date,modified,title,source_url",
    "https://www.fonduri-ue.ro/",
    "https://fonduri-ue.gov.ro/",
    "https://generatormachete.mfe.gov.ro/",
]

SEARCH_QUERIES = [
    'site:mfe.gov.ro/pdds/ (apel OR ghid OR consultare OR corrigendum OR termen OR buget)',
    'site:mfe.gov.ro/ghiduri_peos/ (apel OR ghid OR consultare OR termen)',
    'site:mfe.gov.ro/ghiduri_pids/ (apel OR ghid OR consultare OR termen)',
    'site:mfe.gov.ro/wp-content/uploads/ (ghid OR calendar OR corrigendum OR program)',
    'site:reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/ noutati',
]

OPEN_STATES = {"DESCHIS", "DESCHISA", "ACTIV", "ACTIVA", "IN DERULARE"}
CLOSED_STATES = {"FINALIZAT", "FINALIZATA", "INCHIS", "INCHISA"}


@dataclass(frozen=True)
class Candidate:
    url: str
    scope: str
    title_hint: str = ""
    discovered_via: str = "configured official seed"
    discovery_url: str = ""


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def parse_header_blocks(raw: str) -> dict[str, str]:
    selected: dict[str, str] = {}
    for block in re.split(r"\r?\n\r?\n", raw.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or not lines[0].startswith("HTTP/"):
            continue
        selected = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                selected[key.strip().lower()] = value.strip()
    return selected


def failure_class(error: str, status: int = 0, challenge: bool = False) -> str:
    value = fold(error)
    if challenge:
        return "CLOUDFLARE_CHALLENGE"
    if "certificate" in value or "ssl" in value or "tls" in value:
        return "TLS_ERROR"
    if "resolve" in value or "name or service" in value or "dns" in value:
        return "DNS_ERROR"
    if "timeout" in value or "timed out" in value or "rc=28" in value:
        return "CONNECT_TIMEOUT"
    if status:
        return f"HTTP_{status}"
    return "TRANSPORT_ERROR"


class CurlTransport:
    name = "curl-verified-tls"

    def fetch(self, url: str, timeout: int = 28) -> dict[str, Any]:
        normalized = normalize_url(url)
        if not normalized:
            return {"ok": False, "requestedUrl": url, "failureClass": "SCOPE_REJECTED", "error": "URL outside official registry"}
        with tempfile.TemporaryDirectory(prefix="mipe-fetch-") as directory:
            body_path = Path(directory) / "body.bin"
            headers_path = Path(directory) / "headers.txt"
            command = [
                "curl", "--silent", "--show-error", "--location", "--compressed", "--http1.1",
                "--connect-timeout", "7", "--max-time", str(timeout), "--max-redirs", "6",
                "--proto", "=https", "--proto-redir", "=https", "--user-agent", UA,
                "--header", "Accept: text/html,application/xhtml+xml,application/json,application/xml,text/xml;q=0.9,*/*;q=0.7",
                "--output", str(body_path), "--dump-header", str(headers_path),
                "--write-out", "%{http_code}\t%{url_effective}\t%{content_type}\t%{remote_ip}\t%{ssl_verify_result}\t%{size_download}",
                normalized,
            ]
            process = subprocess.run(command, capture_output=True)
            body = body_path.read_bytes() if body_path.exists() else b""
            raw_headers = headers_path.read_text(encoding="utf-8", errors="replace") if headers_path.exists() else ""
            fields = process.stdout.decode("utf-8", errors="replace").strip().split("\t")
            status = int(fields[0]) if fields and fields[0].isdigit() else 0
            final_raw = fields[1] if len(fields) > 1 else normalized
            content_type = fields[2] if len(fields) > 2 else ""
            remote_ip = fields[3] if len(fields) > 3 else ""
            ssl_result = fields[4] if len(fields) > 4 else ""
            final_url = normalize_url(final_raw)
            error = process.stderr.decode("utf-8", errors="replace").strip()
            challenge = status == 403 and any(marker in body.lower() for marker in (b"cf-chl-", b"just a moment", b"verify you are human"))
            if challenge:
                error = "Cloudflare challenge page; no source content accepted"
            elif len(body) > MAX_BODY_BYTES:
                error = f"response exceeds {MAX_BODY_BYTES} bytes"
            elif not final_url:
                error = error or "redirected outside official registry"
            ok = (
                process.returncode == 0 and 200 <= status < 400 and ssl_result in {"", "0"}
                and final_url is not None and 0 < len(body) <= MAX_BODY_BYTES and not challenge
            )
            return {
                "ok": ok,
                "requestedUrl": normalized,
                "finalUrl": final_url or final_raw,
                "status": status,
                "contentType": content_type,
                "remoteIp": remote_ip,
                "headers": parse_header_blocks(raw_headers),
                "body": body,
                "transport": self.name,
                "tlsVerified": bool(ok),
                "error": error or (None if ok else f"curl rc={process.returncode}, HTTP {status}"),
                "failureClass": None if ok else failure_class(error or f"rc={process.returncode}", status, challenge),
            }


class RegistryTableParser(HTMLParser):
    """Parse APEX report tables, retaining links in the Info cell."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._table: Optional[list[list[dict[str, Any]]]] = None
        self._row: Optional[list[dict[str, Any]]] = None
        self._cell: Optional[dict[str, Any]] = None
        self._href: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attrs_d = {key.lower(): (value or "") for key, value in attrs}
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = {"parts": [], "links": []}
        elif tag == "a" and self._cell is not None:
            self._href = attrs_d.get("href") or None
            # APEX often renders the Info link as an icon with no text node.
            # Capture href at tag-open time so the stable row identity is kept.
            if self._href:
                absolute = normalize_url(self._href, MYSMIS_REGISTRY_URL)
                if absolute and absolute not in self._cell["links"]:
                    self._cell["links"].append(absolute)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a":
            self._href = None
        elif tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append({"text": clean(" ".join(self._cell["parts"])), "links": self._cell["links"]})
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(cell["text"] or cell["links"] for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None and data.strip():
            self._cell["parts"].append(data)
        if self._cell is not None and self._href:
            absolute = normalize_url(self._href, MYSMIS_REGISTRY_URL)
            if absolute and absolute not in self._cell["links"]:
                self._cell["links"].append(absolute)


HEADER_ALIASES = {
    "program operational": "program",
    "tip apel": "callType",
    "apel": "callName",
    "stare apel": "state",
    "entitati participante": "participants",
    "nr. schite": "drafts",
    "nr. proiecte inregistrate (depuse)": "submittedProjects",
    "nr. contracte": "contracts",
    "nr. proiecte retrase": "withdrawnProjects",
    "buget nerambursabil apel": "grantBudget",
    "buget total proiecte (schite & depuse)": "totalProjectBudget",
    "buget nerambursabil proiecte depuse": "submittedGrantBudget",
    "info": "info",
}


def normalized_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9 ()&.-]+", "", fold(value)).strip()


def rows_from_matrix(matrix: list[list[Any]], links_by_row: Optional[list[list[list[str]]]] = None) -> list[dict[str, str]]:
    header_index: Optional[int] = None
    columns: dict[int, str] = {}
    for index, raw_row in enumerate(matrix[:20]):
        headers = [normalized_header(cell) for cell in raw_row]
        if {"program operational", "apel", "stare apel"}.issubset(set(headers)):
            header_index = index
            columns = {position: HEADER_ALIASES[name] for position, name in enumerate(headers) if name in HEADER_ALIASES}
            break
    if header_index is None:
        return []
    rows: list[dict[str, str]] = []
    for source_index, raw_row in enumerate(matrix[header_index + 1 :], start=header_index + 1):
        row = {key: clean(raw_row[position]) for position, key in columns.items() if position < len(raw_row)}
        if not (row.get("program") and row.get("callName") and row.get("state")):
            continue
        if links_by_row and source_index < len(links_by_row):
            flattened = [url for cell_links in links_by_row[source_index] for url in cell_links]
            if flattened:
                row["infoUrl"] = flattened[-1]
        stable = row.get("infoUrl") or "\n".join((row["program"], row.get("callType", ""), row["callName"]))
        row["id"] = sha256_hex(stable)[:24]
        rows.append(row)
    return rows


def parse_registry_html(data: bytes) -> dict[str, Any]:
    raw = data.decode("utf-8", errors="replace")
    parser = RegistryTableParser()
    parser.feed(raw)
    rows: list[dict[str, str]] = []
    for table in parser.tables:
        matrix = [[cell["text"] for cell in raw_row] for raw_row in table]
        links = [[cell["links"] for cell in raw_row] for raw_row in table]
        candidate = rows_from_matrix(matrix, links)
        if len(candidate) > len(rows):
            rows = candidate
    visible = clean(re.sub(r"<[^>]+>", " ", raw))
    range_match = re.search(r"\b(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\b", visible, flags=re.I)
    page_range = tuple(int(value) for value in range_match.groups()) if range_match else None
    total = page_range[2] if page_range else len(rows)
    complete = bool(rows) and (page_range is None or (page_range[0] == 1 and len(rows) >= total))
    return {"rows": rows, "range": page_range, "total": total, "complete": complete, "rawSha256": sha256_hex(data)}


def _xlsx_cell_value(cell: ET.Element, shared: list[str], ns: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t", "")
    value = cell.findtext("x:v", default="", namespaces=ns)
    if cell_type == "s" and value.isdigit():
        index = int(value)
        return shared[index] if index < len(shared) else value
    if cell_type == "inlineStr":
        return "".join(cell.itertext())
    return value


def parse_registry_xlsx(data: bytes) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as temporary:
        temporary.write(data)
        temporary.flush()
        with zipfile.ZipFile(temporary.name) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [clean("".join(node.itertext())) for node in root]
            sheet_names = sorted(name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
            if not sheet_names:
                return {"rows": [], "complete": False, "total": 0, "rawSha256": sha256_hex(data)}
            root = ET.fromstring(archive.read(sheet_names[0]))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            matrix: list[list[str]] = []
            for row in root.findall(".//x:sheetData/x:row", ns):
                values: dict[int, str] = {}
                max_index = -1
                for cell in row.findall("x:c", ns):
                    reference = cell.attrib.get("r", "A1")
                    letters = re.match(r"[A-Z]+", reference)
                    if not letters:
                        continue
                    column = 0
                    for character in letters.group(0):
                        column = column * 26 + ord(character) - 64
                    column -= 1
                    values[column] = _xlsx_cell_value(cell, shared, ns)
                    max_index = max(max_index, column)
                matrix.append([values.get(index, "") for index in range(max_index + 1)])
    rows = rows_from_matrix(matrix)
    return {"rows": rows, "complete": bool(rows), "total": len(rows), "rawSha256": sha256_hex(data)}


def dedupe_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    output: dict[str, Candidate] = {}
    for candidate in candidates:
        url = normalize_url(candidate.url)
        if not url:
            continue
        fixed = Candidate(url, candidate.scope or source_scope(url), candidate.title_hint, candidate.discovered_via, candidate.discovery_url)
        existing = output.get(url)
        if not existing or candidate.discovered_via == "explicit priority seed" or len(candidate.title_hint) > len(existing.title_hint):
            output[url] = fixed
    return list(output.values())


def load_candidates() -> list[Candidate]:
    candidates = [Candidate(PRIORITY_PDDS_SEED, "PDDS", "Programare PDDS", "explicit priority seed")]
    for url in STRUCTURED_URLS:
        normalized = normalize_url(url)
        if normalized:
            candidates.append(Candidate(normalized, source_scope(normalized), "", "configured official surface"))
    for filename in ("pdds_webindex_seeds.json", "mipe_known_canonical_seeds.json", "mipe_discovered_urls.json", "mipe_discovery_sources.json"):
        payload = load_json(STATE_DIR / filename, {})
        rows: list[Any] = []
        if isinstance(payload, Mapping):
            for key in ("items", "seeds", "sources", "urls"):
                if isinstance(payload.get(key), list):
                    rows.extend(payload[key])
        elif isinstance(payload, list):
            rows = payload
        for raw in rows:
            if isinstance(raw, str):
                value, data = raw, {}
            elif isinstance(raw, Mapping):
                value, data = str(raw.get("url") or raw.get("canonicalUrl") or ""), raw
            else:
                continue
            if str(data.get("role") or "").startswith("T2_"):
                continue
            url = normalize_url(value)
            if url:
                candidates.append(Candidate(
                    url,
                    str(data.get("programme") or data.get("scope") or source_scope(url)),
                    clean(data.get("titleHint") or data.get("title")),
                    clean(data.get("discoveredVia") or data.get("role") or f"configured {filename}"),
                    clean(data.get("discoveryUrl")),
                ))
    return dedupe_candidates(candidates)


def search_discover() -> tuple[list[Candidate], list[dict[str, Any]]]:
    found: list[Candidate] = []
    health: list[dict[str, Any]] = []
    for query in SEARCH_QUERIES:
        endpoint = "https://www.bing.com/search?" + urllib.parse.urlencode({"format": "rss", "q": query})
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": UA, "Accept": "application/rss+xml,application/xml"})
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(2 * 1024 * 1024)
            root = ET.fromstring(raw)
            count = 0
            for item in root.findall(".//item"):
                url = normalize_url(clean(item.findtext("link")))
                if not url:
                    continue
                if "mfe.gov.ro/pdds" in query and urllib.parse.urlsplit(url).hostname == "mfe.gov.ro" and not in_pdds_scope(url):
                    continue
                found.append(Candidate(url, source_scope(url), clean(item.findtext("title")), "web-index discovery only", endpoint))
                count += 1
            health.append({"query": query, "ok": True, "officialUrlCount": count})
        except Exception as exc:
            health.append({"query": query, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return dedupe_candidates(found), health


def persist_discoveries(candidates: Iterable[Candidate], observed_at: str) -> bool:
    previous = load_json(DISCOVERY_PATH, {})
    rows = previous.get("items", []) if isinstance(previous, Mapping) else []
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, Mapping):
            url = normalize_url(str(row.get("url") or ""))
            if url:
                merged[url] = dict(row)
    changed = False
    for candidate in candidates:
        if candidate.discovered_via != "web-index discovery only" or candidate.url in merged:
            continue
        merged[candidate.url] = {
            "url": candidate.url,
            "scope": candidate.scope,
            "titleHint": candidate.title_hint,
            "discoveredVia": candidate.discovered_via,
            "discoveryUrl": candidate.discovery_url,
            "firstDiscoveredAt": observed_at,
        }
        changed = True
    if changed:
        payload = {
            "version": 2,
            "policy": "Search/index output locates official canonical URLs only. No snippet, title, date or fact is published until verified directly on the official URL.",
            "items": sorted(merged.values(), key=lambda row: row["url"]),
        }
        atomic_write(DISCOVERY_PATH, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return changed


def sitemap_candidates(data: bytes, base_url: str) -> list[Candidate]:
    try:
        root = ET.fromstring(data)
    except Exception:
        return []
    output: list[Candidate] = []
    for node in root.iter():
        local = node.tag.rsplit("}", 1)[-1].lower()
        if local not in {"loc", "link"}:
            continue
        value = clean(node.text) or clean(node.attrib.get("href"))
        url = normalize_url(value, base_url)
        if url:
            output.append(Candidate(url, source_scope(url), "", "verified official sitemap/feed", base_url))
    return dedupe_candidates(output)


def wp_json_candidates(data: bytes, discovery_url: str) -> list[Candidate]:
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        return []
    output: list[Candidate] = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, Mapping):
            continue
        url = normalize_url(str(row.get("link") or row.get("source_url") or ""))
        if not url:
            continue
        title = row.get("title")
        if isinstance(title, Mapping):
            title = title.get("rendered")
        output.append(Candidate(url, source_scope(url), clean(title), "verified official WordPress REST", discovery_url))
    return dedupe_candidates(output)


def make_page_observation(result: Mapping[str, Any], candidate: Candidate, fetched_at: str) -> Optional[dict[str, Any]]:
    if not result.get("ok") or not isinstance(result.get("body"), (bytes, bytearray)):
        return None
    content_type = fold(result.get("contentType") or result.get("headers", {}).get("content-type"))
    body = bytes(result["body"])
    if "html" not in content_type and not body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return None
    document = extract_html_document(body, str(result.get("finalUrl")), result.get("headers") or {})
    canonical = document.get("canonicalUrl")
    if not canonical or (candidate.scope == "PDDS" and not in_pdds_scope(str(canonical))):
        return None
    return {
        "candidate": asdict(candidate),
        "document": document,
        "fetchedAt": fetched_at,
        "transport": result.get("transport"),
        "httpStatus": result.get("status"),
    }


def linked_candidates(observation: Mapping[str, Any], pdds_only: bool) -> list[Candidate]:
    document = observation.get("document") or {}
    parent = str(document.get("canonicalUrl") or "")
    output: list[Candidate] = []
    for raw in document.get("links") or []:
        if not isinstance(raw, Mapping):
            continue
        url = normalize_url(str(raw.get("url") or ""))
        if not url or (pdds_only and not in_pdds_scope(url)):
            continue
        text = clean(raw.get("text"))
        if pdds_only or relevance_score(text, "", "", url) >= 1:
            output.append(Candidate(url, source_scope(url), text, "verified official page link", parent))
    return dedupe_candidates(output)


def source_state(result: Mapping[str, Any], candidate: Candidate) -> dict[str, Any]:
    return {
        "url": candidate.url,
        "scope": candidate.scope,
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "transport": result.get("transport"),
        "remoteIp": result.get("remoteIp"),
        "failureClass": result.get("failureClass"),
        "error": clean(result.get("error"))[:500] or None,
    }


def direct_collect(candidates: list[Candidate], observed_at: str) -> dict[str, Any]:
    transport = CurlTransport()
    observations: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    registry: Optional[dict[str, Any]] = None
    seen: set[str] = set()
    blocked_hosts: set[str] = set()
    queue: deque[Candidate] = deque()

    def priority(candidate: Candidate) -> tuple[int, int, str]:
        if candidate.url == PRIORITY_PDDS_SEED:
            tier = 0
        elif candidate.url == MYSMIS_REGISTRY_URL:
            tier = 1
        elif candidate.scope == "PDDS":
            tier = 2
        elif candidate.scope == "MYSMIS":
            tier = 3
        elif any(marker in candidate.url for marker in ("wp-json", "sitemap", "/feed/")):
            tier = 4
        else:
            tier = 5
        return tier, -relevance_score(candidate.title_hint, "", "", candidate.url), candidate.url

    queue.extend(sorted(candidates, key=priority))
    pdds_count = broad_count = 0
    while queue and len(seen) < MAX_PDDS_PAGES + MAX_BROAD_PAGES:
        candidate = queue.popleft()
        if candidate.url in seen:
            continue
        host = urllib.parse.urlsplit(candidate.url).hostname or ""
        if host in blocked_hosts:
            continue
        if candidate.scope == "PDDS":
            if pdds_count >= MAX_PDDS_PAGES:
                continue
            pdds_count += 1
        else:
            if broad_count >= MAX_BROAD_PAGES:
                continue
            broad_count += 1
        seen.add(candidate.url)
        timeout = 40 if candidate.url == MYSMIS_REGISTRY_URL else 24
        result = transport.fetch(candidate.url, timeout=timeout)
        states.append(source_state(result, candidate))
        if not result.get("ok"):
            if result.get("failureClass") in {"CONNECT_TIMEOUT", "DNS_ERROR"}:
                blocked_hosts.add(host)
            continue

        body = result.get("body") or b""
        content_type = fold(result.get("contentType"))
        if candidate.url == MYSMIS_REGISTRY_URL:
            registry = parse_registry_html(body)
            registry.update({
                "url": MYSMIS_REGISTRY_URL,
                "transport": result.get("transport"),
                "httpStatus": result.get("status"),
                "fetchedAt": observed_at,
                "tlsVerified": True,
            })
        if "xml" in content_type or candidate.url.endswith(("sitemap.xml", "/feed/")):
            queue.extend(item for item in sitemap_candidates(body, candidate.url) if item.url not in seen)
            continue
        if "json" in content_type or "/wp-json/" in candidate.url:
            queue.extend(item for item in wp_json_candidates(body, candidate.url) if item.url not in seen)
            continue
        observation = make_page_observation(result, candidate, observed_at)
        if observation:
            observations.append(observation)
            pdds_only = candidate.url == PRIORITY_PDDS_SEED or candidate.scope == "PDDS"
            queue.extend(item for item in linked_candidates(observation, pdds_only) if item.url not in seen)

    if registry is None:
        fallback = Candidate(MYSMIS_FALLBACK_REGISTRY, "MYSMIS", "", "configured official fallback")
        result = transport.fetch(fallback.url, timeout=40)
        states.append(source_state(result, fallback))
        if result.get("ok"):
            registry = parse_registry_html(result.get("body") or b"")
            registry.update({"url": fallback.url, "transport": result.get("transport"), "httpStatus": result.get("status"), "fetchedAt": observed_at, "tlsVerified": True})
    return {"observations": observations, "sourceStates": states, "registry": registry, "attemptedCount": len(seen)}


async def browser_collect_async(candidates: list[Candidate], observed_at: str) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        return {"observations": [], "sourceStates": [{"url": "browser", "ok": False, "failureClass": "BROWSER_UNAVAILABLE", "error": str(exc)}], "registry": None}

    observations: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    registry: Optional[dict[str, Any]] = None
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="ro-RO", timezone_id="Europe/Bucharest", viewport={"width": 1400, "height": 950}, ignore_https_errors=False, accept_downloads=True)
        page = await context.new_page()

        # Priority seed gets one real-browser attempt.  No challenge bypass or TLS relaxation.
        candidate = next((item for item in candidates if item.url == PRIORITY_PDDS_SEED), Candidate(PRIORITY_PDDS_SEED, "PDDS"))
        row: dict[str, Any] = {"url": candidate.url, "scope": "PDDS", "transport": "playwright-verified-tls"}
        try:
            response = await page.goto(candidate.url, wait_until="domcontentloaded", timeout=35000)
            await page.wait_for_timeout(2500)
            content = await page.content()
            challenge = any(marker in content.lower() for marker in ("cf-chl-", "just a moment", "verify you are human"))
            final_url = normalize_url(page.url)
            status = response.status if response else 0
            ok = bool(response and 200 <= status < 400 and final_url and not challenge)
            row.update({"ok": ok, "status": status, "finalUrl": final_url or page.url})
            if ok:
                result = {"ok": True, "body": content.encode(), "finalUrl": final_url, "status": status, "contentType": "text/html", "headers": await response.all_headers(), "transport": "playwright-verified-tls"}
                observation = make_page_observation(result, candidate, observed_at)
                if observation:
                    observations.append(observation)
            else:
                row.update({"failureClass": "CLOUDFLARE_CHALLENGE" if challenge else f"HTTP_{status}", "error": "challenge page" if challenge else f"HTTP {status}"})
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            row.update({"ok": False, "failureClass": failure_class(message), "error": message[:500]})
        states.append(row)

        # APEX row selector can expose the complete official registry without a mirror.
        registry_row: dict[str, Any] = {"url": MYSMIS_REGISTRY_URL, "scope": "MYSMIS", "transport": "playwright-verified-tls"}
        try:
            response = await page.goto(MYSMIS_REGISTRY_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector("#APELURI_row_select", timeout=20000)
            initial = parse_registry_html((await page.content()).encode())
            options = await page.locator("#APELURI_row_select option").evaluate_all("els=>els.map(e=>e.value)")
            numeric = sorted(int(value) for value in options if str(value).isdigit())
            if numeric:
                await page.select_option("#APELURI_row_select", str(numeric[-1]))
                await page.wait_for_timeout(7000)
            rendered = (await page.content()).encode()
            parsed = parse_registry_html(rendered)
            complete = bool(parsed.get("rows")) and parsed.get("total") and len(parsed["rows"]) >= int(parsed["total"])
            if not complete and initial.get("total") and len(parsed.get("rows") or []) >= int(initial["total"]):
                complete = True
                parsed["total"] = int(initial["total"])
            parsed["complete"] = bool(complete)
            status = response.status if response else 0
            ok = bool(response and 200 <= status < 400 and parsed.get("rows"))
            registry_row.update({"ok": ok, "status": status, "visibleRows": len(parsed.get("rows") or []), "totalRows": parsed.get("total"), "complete": parsed.get("complete"), "rowOptions": numeric})
            if ok:
                parsed.update({"url": MYSMIS_REGISTRY_URL, "transport": "playwright-verified-tls", "httpStatus": status, "fetchedAt": observed_at, "tlsVerified": True})
                registry = parsed
            else:
                registry_row.update({"failureClass": "PARSER_ERROR", "error": "registry rows not found"})
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            registry_row.update({"ok": False, "failureClass": failure_class(message), "error": message[:500]})
        states.append(registry_row)
        await browser.close()
    return {"observations": observations, "sourceStates": states, "registry": registry}


def browser_collect(candidates: list[Candidate], observed_at: str) -> dict[str, Any]:
    return asyncio.run(browser_collect_async(candidates, observed_at))


def relay_collect(observed_at: str) -> dict[str, Any]:
    secret = os.environ.get("MIPE_RELAY_HMAC_KEY", "")
    observations: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    registry: Optional[dict[str, Any]] = None
    if not RELAY_INBOX.exists():
        return {"observations": observations, "sourceStates": states, "registry": registry}
    for path in sorted(RELAY_INBOX.glob("*.json")):
        snapshot = load_json(path, {})
        ok, reason, body = verify_snapshot(snapshot, secret)
        row = {"url": snapshot.get("url"), "transport": "signed-relay-hmac-sha256", "ok": ok, "error": None if ok else reason}
        if not ok or body is None:
            row["failureClass"] = "RELAY_REJECTED"
            states.append(row)
            continue
        url = normalize_url(str(snapshot.get("url") or ""))
        final_url = normalize_url(str(snapshot.get("finalUrl") or ""))
        if not url or not final_url:
            continue
        if url in {MYSMIS_REGISTRY_URL, MYSMIS_FALLBACK_REGISTRY}:
            content_type = fold(snapshot.get("contentType"))
            parsed = parse_registry_xlsx(body) if "spreadsheet" in content_type or body.startswith(b"PK") else parse_registry_html(body)
            parsed.update({"url": url, "transport": "signed-relay-hmac-sha256", "httpStatus": int(snapshot.get("httpStatus") or 0), "fetchedAt": snapshot.get("fetchedAt") or observed_at, "tlsVerified": True})
            registry = parsed
        else:
            candidate = Candidate(url, source_scope(url), "", "signed independent collector")
            result = {"ok": True, "body": body, "finalUrl": final_url, "status": int(snapshot.get("httpStatus") or 0), "contentType": snapshot.get("contentType") or "text/html", "headers": snapshot.get("headers") or {}, "transport": "signed-relay-hmac-sha256"}
            observation = make_page_observation(result, candidate, str(snapshot.get("fetchedAt") or observed_at))
            if observation:
                observations.append(observation)
        states.append(row)
    return {"observations": observations, "sourceStates": states, "registry": registry}


def load_state() -> dict[str, Any]:
    state = load_json(STATE_PATH, {})
    if not isinstance(state, dict) or state.get("version") != 2:
        state = {"version": 2, "pageInventory": {}, "registryRows": {}, "items": [], "lastGoodAt": None, "lastMaterialRun": None}
    state.setdefault("pageInventory", {})
    state.setdefault("registryRows", {})
    state.setdefault("items", [])
    return state


def recent_document(document: Mapping[str, Any], observed_at: str, days: int = 400) -> bool:
    now_value = parse_datetime(observed_at) or now_utc()
    for key in ("publishedAt", "modifiedAt"):
        parsed = parse_datetime(document.get(key))
        if parsed:
            return now_value - dt.timedelta(days=days) <= parsed <= now_value + dt.timedelta(days=2)
    return False


def process_pages(observations: Iterable[Mapping[str, Any]], state: dict[str, Any], observed_at: str) -> tuple[list[dict[str, Any]], int, int]:
    inventory: dict[str, Any] = state["pageInventory"]
    fresh: list[dict[str, Any]] = []
    verified = changed = 0
    excluded = {normalize_url(MYSMIS_REGISTRY_URL), normalize_url(MYSMIS_HOME_URL), normalize_url("https://mfe.gov.ro/")}
    for observation in observations:
        document = observation.get("document") or {}
        canonical = normalize_url(str(document.get("canonicalUrl") or ""))
        if not canonical:
            continue
        verified += 1
        if canonical in excluded or any(marker in canonical for marker in ("/wp-json/", "sitemap.xml", "/feed/")):
            continue
        digest = str(document.get("contentSha256") or "")
        previous = inventory.get(canonical)
        change_type = "NEW" if not previous else ("CHANGED" if previous.get("contentSha256") != digest else "UNCHANGED")
        if change_type == "UNCHANGED":
            continue
        inventory[canonical] = {
            "contentSha256": digest,
            "rawSha256": document.get("rawSha256"),
            "title": document.get("title"),
            "publishedAt": document.get("publishedAt"),
            "modifiedAt": document.get("modifiedAt"),
            "lastChangedOrFirstSeenAt": observed_at,
            "lastTransport": observation.get("transport"),
        }
        changed += 1
        if change_type == "NEW" and not recent_document(document, observed_at):
            continue
        item = build_page_item(
            document,
            fetched_at=str(observation.get("fetchedAt") or observed_at),
            transport=str(observation.get("transport") or "unknown"),
            http_status=int(observation.get("httpStatus") or 0),
            change_type=change_type,
            discovery=observation.get("candidate") or {},
        )
        if item:
            fresh.append(item)
    return fresh, verified, changed


def stable_registry_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {key: clean(row.get(key)) for key in ("id", "program", "callType", "callName", "state", "grantBudget", "infoUrl") if clean(row.get(key))}


def registry_state(value: Any) -> str:
    return fold(value).upper()


def registry_item(current: Mapping[str, str], previous: Optional[Mapping[str, str]], observed_at: str, registry: Mapping[str, Any], change_type: str) -> Optional[dict[str, Any]]:
    old_state = registry_state(previous.get("state")) if previous else ""
    new_state = registry_state(current.get("state"))
    old_budget = clean(previous.get("grantBudget")) if previous else ""
    new_budget = clean(current.get("grantBudget"))
    evidence = ["structured official MySMIS row", "complete official registry snapshot"]
    kind = "OFFICIAL_UPDATE"
    status = "NEWS"
    if new_state in OPEN_STATES and (not previous or old_state not in OPEN_STATES):
        kind, status = "CALL_OPENED", "OPEN"
        evidence.append(f"structured official state={clean(current.get('state'))}")
    elif previous and new_state in CLOSED_STATES and old_state not in CLOSED_STATES:
        kind = "CALL_CLOSED"
        evidence.append(f"structured official state={clean(current.get('state'))}")
    elif previous and old_budget != new_budget and new_budget:
        kind = "BUDGET_UPDATED"
        evidence.append("structured official grant budget changed")
    else:
        return None
    canonical = normalize_url(current.get("infoUrl") or str(registry.get("url") or MYSMIS_REGISTRY_URL))
    if not canonical:
        return None
    programme = clean(current.get("program"))
    summary = f"{programme}. Stare oficială MySMIS: {clean(current.get('state'))}."
    if new_budget:
        summary += f" Buget nerambursabil apel: {new_budget}."
    item = {
        "id": sha256_hex(str(current.get("id")) + "\n" + str(registry.get("rawSha256")) + "\n" + kind)[:24],
        "title": clean(current.get("callName"))[:360],
        "url": canonical,
        "canonicalUrl": canonical,
        "date": observed_at[:10],
        "dateLabel": date_label(observed_at),
        "dateBasis": "observedAt",
        "publishedAt": None,
        "modifiedAt": None,
        "summary": summary[:900],
        "tag": "MYSMIS",
        "kind": kind,
        "status": status,
        "tier": "T1",
        "source": "MIPE",
        "sourceAdapter": "MYSMIS_REGISTRY",
        "changeType": change_type,
        "observedAt": observed_at,
        "evidence": evidence,
        "provenance": {
            "fetchedUrl": normalize_url(str(registry.get("url") or MYSMIS_REGISTRY_URL)),
            "canonicalUrl": canonical,
            "fetchedAt": str(registry.get("fetchedAt") or observed_at),
            "transport": registry.get("transport"),
            "httpStatus": int(registry.get("httpStatus") or 200),
            "tlsVerified": registry.get("tlsVerified") is True,
            "contentSha256": sha256_hex(json.dumps(dict(current), ensure_ascii=False, sort_keys=True)),
            "rawSha256": registry.get("rawSha256"),
            "canonicalEvidence": "official MySMIS registry row",
            "discovery": {"scope": "MYSMIS", "discoveredVia": "configured official structured source"},
            "structuredRow": dict(current),
            "previousStructuredRow": dict(previous or {}),
            "registryComplete": True,
        },
    }
    return item if validate_item(item) else None


def process_registry(registry: Optional[Mapping[str, Any]], state: dict[str, Any], observed_at: str) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    summary = {"available": False, "complete": False, "visibleRows": 0, "totalRows": 0, "baselineCreated": False, "changedRows": 0}
    if not registry or registry.get("tlsVerified") is not True:
        return [], summary, False
    rows = [stable_registry_row(row) for row in registry.get("rows") or [] if isinstance(row, Mapping)]
    rows = [row for row in rows if row.get("id") and row.get("program") and row.get("callName") and row.get("state")]
    summary.update({"available": bool(rows), "complete": bool(registry.get("complete")), "visibleRows": len(rows), "totalRows": int(registry.get("total") or len(rows)), "transport": registry.get("transport"), "url": registry.get("url")})
    if not rows or not registry.get("complete"):
        return [], summary, False
    identifiers = [row["id"] for row in rows]
    if len(identifiers) != len(set(identifiers)):
        summary.update({"complete": False, "rejected": "duplicate stable row identifiers"})
        return [], summary, False
    previous_map: dict[str, Any] = state["registryRows"]
    if len(previous_map) >= 50 and len(rows) < int(len(previous_map) * 0.85):
        summary.update({"complete": False, "rejected": "suspicious registry shrinkage"})
        return [], summary, False
    current_map = {row["id"]: row for row in rows}
    if not previous_map:
        state["registryRows"] = current_map
        summary["baselineCreated"] = True
        return [], summary, True
    fresh: list[dict[str, Any]] = []
    changed = 0
    for identifier, current in current_map.items():
        previous = previous_map.get(identifier)
        if previous is None:
            item = registry_item(current, None, observed_at, registry, "NEW")
            if item:
                fresh.append(item)
            changed += 1
            continue
        tracked_changed = any(clean(previous.get(key)) != clean(current.get(key)) for key in ("state", "grantBudget"))
        if tracked_changed:
            changed += 1
            item = registry_item(current, previous, observed_at, registry, "CHANGED")
            if item:
                fresh.append(item)
    summary["changedRows"] = changed
    material = current_map != previous_map
    if material:
        state["registryRows"] = current_map
    return fresh, summary, material


def persist_health(health: dict[str, Any]) -> bool:
    previous = load_json(HEALTH_PATH, {})
    fingerprint = health_fingerprint(health)
    if isinstance(previous, Mapping) and previous.get("fingerprint") == fingerprint:
        return False
    payload = dict(health)
    payload["fingerprint"] = fingerprint
    atomic_write(HEALTH_PATH, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return True


def validate_feed(items: Iterable[Mapping[str, Any]]) -> None:
    seen: set[str] = set()
    for item in items:
        if not validate_item(item):
            raise ValueError(f"invalid feed item: {item.get('url')} / {item.get('title')}")
        key = str(item.get("sourceAdapter")) + ":" + str(item.get("id"))
        if key in seen:
            raise ValueError(f"duplicate feed item: {key}")
        seen.add(key)


def feed_meta_signature(meta: Mapping[str, Any]) -> str:
    stable = {
        "pipelineVersion": meta.get("pipelineVersion"),
        "status": meta.get("status"),
        "prioritySeedAvailable": meta.get("prioritySeedAvailable"),
        "mysmisRegistryAvailable": meta.get("mysmisRegistryAvailable"),
        "mysmisRegistryComplete": meta.get("mysmisRegistryComplete"),
        "itemCount": meta.get("itemCount"),
        "provenancePolicy": meta.get("provenancePolicy"),
    }
    return sha256_hex(json.dumps(stable, ensure_ascii=False, sort_keys=True))


def run(enable_browser: bool = False) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    observed_at = iso_z(now_utc())
    configured = load_candidates()
    indexed, search_health = search_discover()
    discoveries_changed = persist_discoveries(indexed, observed_at)
    candidates = dedupe_candidates(configured + indexed)

    direct = direct_collect(candidates, observed_at)
    observations = list(direct.get("observations") or [])
    source_states = list(direct.get("sourceStates") or [])
    registry = direct.get("registry")
    attempted = int(direct.get("attemptedCount") or 0)

    if enable_browser:
        browser = browser_collect(candidates, observed_at)
        observations.extend(browser.get("observations") or [])
        source_states.extend(browser.get("sourceStates") or [])
        if browser.get("registry") and browser["registry"].get("complete"):
            registry = browser["registry"]

    relay = relay_collect(observed_at)
    observations.extend(relay.get("observations") or [])
    source_states.extend(relay.get("sourceStates") or [])
    if relay.get("registry") and relay["registry"].get("complete"):
        registry = relay["registry"]

    state = load_state()
    before_material = sha256_hex(json.dumps({"pageInventory": state["pageInventory"], "registryRows": state["registryRows"]}, ensure_ascii=False, sort_keys=True))
    page_items, verified_pages, changed_pages = process_pages(observations, state, observed_at)
    registry_items, registry_summary, registry_material = process_registry(registry, state, observed_at)
    fresh_items = page_items + registry_items
    after_material = sha256_hex(json.dumps({"pageInventory": state["pageInventory"], "registryRows": state["registryRows"]}, ensure_ascii=False, sort_keys=True))
    inventory_changed = before_material != after_material or registry_material

    old_feed_text = FEED_PATH.read_text(encoding="utf-8") if FEED_PATH.exists() else ""
    old_meta, old_items = parse_feed_js(old_feed_text)
    if not old_items and isinstance(state.get("items"), list):
        old_items = [item for item in state["items"] if isinstance(item, dict)]
    merged_items = merge_feed_items(old_items, fresh_items, limit=100)
    validate_feed(merged_items)
    items_changed = merged_items != old_items

    pdds_available = any(row.get("url") == PRIORITY_PDDS_SEED and row.get("ok") for row in source_states)
    registry_available = bool(registry_summary.get("available"))
    other_official_available = bool(verified_pages)
    source_available = registry_available or other_official_available or pdds_available
    failures = sorted({str(row.get("failureClass")) for row in source_states if row.get("failureClass")})
    if fresh_items:
        status = "OK_NEW_VERIFIED_ITEMS" if pdds_available else "PARTIAL_SOURCE_FAILURE_NEW_VERIFIED_ITEMS"
    elif source_available:
        status = "OK_NO_NEW_RELEVANT_ITEMS" if pdds_available else "PARTIAL_SOURCE_FAILURE_LAST_KNOWN_GOOD_PRESERVED"
    else:
        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"

    new_meta = {
        "pipelineVersion": 2,
        "status": status,
        "asOf": observed_at,
        "source": "MIPE official web properties",
        "prioritySeed": PRIORITY_PDDS_SEED,
        "prioritySeedAvailable": pdds_available,
        "mysmisRegistryAvailable": registry_available,
        "mysmisRegistryComplete": bool(registry_summary.get("complete")),
        "itemCount": len(merged_items),
        "provenancePolicy": "verified official canonical URL only; search index is discovery-only; invalid TLS and challenge pages are rejected",
    }
    meta_changed = feed_meta_signature(new_meta) != feed_meta_signature(old_meta)
    # Fail-closed: never rewrite live News during a total official-source failure.
    feed_changed = source_available and (items_changed or meta_changed)
    if feed_changed:
        atomic_write(FEED_PATH, render_feed_js(new_meta, merged_items))
        state["lastGoodAt"] = observed_at

    state["items"] = merged_items
    if inventory_changed or items_changed:
        state["lastMaterialRun"] = {
            "observedAt": observed_at,
            "status": status,
            "verifiedPageCount": verified_pages,
            "changedPageCount": changed_pages,
            "registry": registry_summary,
            "newItemCount": len(fresh_items),
        }
        atomic_write(STATE_PATH, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    health = {
        "version": 2,
        "observedAt": observed_at,
        "status": status,
        "prioritySeed": PRIORITY_PDDS_SEED,
        "prioritySeedAvailable": pdds_available,
        "sourceAvailable": source_available,
        "sourceAvailability": {
            "priorityPDDS": pdds_available,
            "mysmisRegistry": registry_available,
            "otherVerifiedPages": other_official_available,
        },
        "candidateCount": len(candidates),
        "attemptedCount": attempted,
        "verifiedPageCount": verified_pages,
        "verifiedCount": verified_pages + int(registry_summary.get("visibleRows") or 0),
        "changedPageCount": changed_pages,
        "newItemCount": len(fresh_items),
        "feedItemCount": len(merged_items),
        "feedChanged": feed_changed,
        "inventoryChanged": inventory_changed,
        "discoveriesChanged": discoveries_changed,
        "browserEnabled": enable_browser,
        "failureClasses": failures,
        "registry": registry_summary,
        "searchDiscovery": search_health,
        "sourceStates": source_states[:180],
    }
    health_changed = persist_health(health)
    health["healthChanged"] = health_changed
    health["statePersisted"] = inventory_changed or items_changed
    print(json.dumps(health, ensure_ascii=False, indent=2, sort_keys=True))
    return health


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="Enable strict Playwright fallback and full MySMIS registry rendering")
    args = parser.parse_args()
    run(enable_browser=args.browser)


if __name__ == "__main__":
    main()
