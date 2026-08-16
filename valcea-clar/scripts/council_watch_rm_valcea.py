#!/usr/bin/env python3
"""Râmnicu Vâlcea Council Watch — official decision extractor.

Reads only the official DocManager domain and turns the municipal Lotus Notes
register into a durable review ledger. It never publishes a story itself.

The collector deliberately separates:
- source discovery / register navigation;
- decisions actually carrying the target meeting date;
- extracted operative articles, money mentions and vote language;
- editorial interpretation, which remains downstream and human/newsroom gated.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "editorial" / "council_watch_rm_valcea_state.json"
BASE = "https://dm.primariavl.ro/dm/2026/hotarari.nsf"
OFFICIAL_HOST = "dm.primariavl.ro"
USER_AGENT = "VALCEA-CLAR-Council-Watch/1.0 (+https://valceaclar.ro/)"
TARGET_DATE_ISO = "2026-08-14"
TARGET_DATE_RO = "14 august 2026"
MAX_BYTES = 3_000_000
MAX_DISCOVERY_PAGES = 40
MAX_DOCUMENT_FETCHES = 180
MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5,
    "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10,
    "noiembrie": 11, "decembrie": 12,
}


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.frames: list[str] = []
        self._href: str | None = None
        self._parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "a" and data.get("href"):
            self._href = data["href"]
            self._parts = []
        elif tag.lower() in {"frame", "iframe"} and data.get("src"):
            self.frames.append(data["src"])
        elif tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            self.links.append({"href": self._href, "text": text})
            self._href = None
            self._parts = []
        elif tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)
        if self._in_title:
            self.title_parts.append(data)


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip += 1
        if tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "tr", "td"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = html.unescape(" ".join(self.parts)).replace("\u00a0", " ")
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def decode_body(raw: bytes, content_type: str) -> str:
    candidates: list[str] = []
    match = re.search(r"charset=([\w.-]+)", content_type or "", re.I)
    if match:
        candidates.append(match.group(1))
    candidates.extend(["utf-8", "windows-1250", "iso-8859-2", "windows-1252"])
    seen: set[str] = set()
    for charset in candidates:
        if charset.lower() in seen:
            continue
        seen.add(charset.lower())
        try:
            return raw.decode(charset)
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", errors="replace")


def fetch(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
            raw = response.read(MAX_BYTES)
            body = decode_body(raw, response.headers.get("content-type") or "")
            return {
                "ok": True,
                "status": int(response.status),
                "url": str(response.geturl()),
                "body": body,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": int(exc.code), "url": url, "body": "", "sha256": None, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "status": None, "url": url, "body": "", "sha256": None, "error": f"{type(exc).__name__}: {exc}"}


def canonical_url(base: str, candidate: str) -> str | None:
    candidate = html.unescape(str(candidate or "").strip())
    if not candidate or candidate.startswith(("javascript:", "mailto:", "#")):
        return None
    url = urllib.parse.urljoin(base, candidate)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != OFFICIAL_HOST:
        return None
    if not parsed.path.lower().startswith("/dm/2026/hotarari.nsf"):
        return None
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def parse_links(page_url: str, body: str) -> tuple[list[dict[str, str]], list[str], str]:
    parser = LinkParser()
    parser.feed(body)
    links: list[dict[str, str]] = []
    for row in parser.links:
        url = canonical_url(page_url, row["href"])
        if url:
            links.append({"url": url, "text": row["text"][:500]})
    frames: list[str] = []
    for raw in parser.frames:
        url = canonical_url(page_url, raw)
        if url:
            frames.append(url)
    # Lotus views sometimes hide URLs in JavaScript instead of anchors.
    for raw in re.findall(r"(?i)(?:href|location(?:\.href)?|window\.open)\s*[=(]\s*['\"]([^'\"]+)", body):
        url = canonical_url(page_url, raw)
        if url:
            links.append({"url": url, "text": "javascript-discovered"})
    title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
    return links, frames, title


def to_text(body: str) -> str:
    parser = TextParser()
    parser.feed(body)
    return parser.text()


def looks_document(url: str) -> bool:
    low = urllib.parse.unquote(url).lower()
    return "$file" in low or bool(re.search(r"/vw[^/]+/[0-9a-f]{24,}/", low))


def looks_navigation(url: str) -> bool:
    low = url.lower()
    return any(token in low for token in ("openview", "vw", "?start=", "?open")) and not looks_document(url)


def discover() -> tuple[list[dict[str, Any]], dict[str, str]]:
    seeds = [
        BASE,
        BASE + "/vwHotarariByAn?OpenView&Count=500",
        BASE + "/vwHotarariByAn?OpenView&Start=1&Count=500",
        BASE + "/vwHotarariByAn",
    ]
    queue: deque[tuple[str, int]] = deque((url, 0) for url in seeds)
    visited: set[str] = set()
    docs: dict[str, dict[str, Any]] = {}
    page_health: dict[str, str] = {}

    while queue and len(visited) < MAX_DISCOVERY_PAGES:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        result = fetch(url)
        page_health[url] = "OK" if result["ok"] else str(result["error"])
        if not result["ok"]:
            continue
        links, frames, title = parse_links(result["url"], result["body"])
        for row in links:
            target = row["url"]
            if looks_document(target):
                docs.setdefault(target, {"url": target, "link_text": row.get("text") or "", "discovered_from": result["url"]})
            elif depth < 2 and looks_navigation(target) and target not in visited:
                queue.append((target, depth + 1))
        for frame in frames:
            if depth < 2 and frame not in visited:
                queue.append((frame, depth + 1))
        # Keep discovery diagnostics useful without persisting raw HTML.
        if title and result["url"] in page_health:
            page_health[result["url"]] = "OK: " + title[:160]
    return list(docs.values()), page_health


def parse_ro_date(text: str) -> str | None:
    folded = text.casefold()
    pattern = r"\b([0-3]?\d)\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(2026)\b"
    match = re.search(pattern, folded)
    if not match:
        return None
    day = int(match.group(1))
    month = MONTHS[match.group(2)]
    try:
        return datetime(2026, month, day).date().isoformat()
    except ValueError:
        return None


def snippets(pattern: str, text: str, limit: int = 12, radius: int = 260) -> list[str]:
    rows: list[str] = []
    for match in re.finditer(pattern, text, flags=re.I):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        piece = re.sub(r"\s+", " ", text[start:end]).strip()
        if piece and piece not in rows:
            rows.append(piece)
        if len(rows) >= limit:
            break
    return rows


def operative_articles(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text)
    matches = list(re.finditer(r"\bArt\.\s*(\d+)\.?\s*", compact, flags=re.I))
    rows: list[str] = []
    for index, match in enumerate(matches[:12]):
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(compact), match.start() + 1200)
        piece = compact[match.start():end].strip()
        if len(piece) > 900:
            piece = piece[:900].rsplit(" ", 1)[0] + "…"
        rows.append(piece)
    return rows


def parse_document(meta: dict[str, Any]) -> dict[str, Any]:
    result = fetch(meta["url"])
    row: dict[str, Any] = {
        "url": meta["url"],
        "link_text": meta.get("link_text") or "",
        "discovered_from": meta.get("discovered_from"),
        "reachable": bool(result["ok"]),
        "http_status": result["status"],
        "source_sha256": result["sha256"],
        "error": result["error"],
    }
    if not result["ok"]:
        return row
    text = to_text(result["body"])
    compact = re.sub(r"\s+", " ", text)
    number_match = re.search(r"HOT[ĂA]R[ÂA]REA\s+NR\.?\s*([0-9]+)", compact, flags=re.I)
    row["decision_number"] = int(number_match.group(1)) if number_match else None
    row["decision_date"] = parse_ro_date(compact) or parse_ro_date(urllib.parse.unquote(meta["url"]))
    row["target_date_match"] = row["decision_date"] == TARGET_DATE_ISO
    row["text_head"] = compact[:1200]
    row["operative_articles"] = operative_articles(text)
    row["vote_snippets"] = snippets(r"\bvot(?:ul|uri|at|uri)?\b|unanimit|abțin|abtin|împotriv|impotriv", compact, limit=8)
    row["money_snippets"] = snippets(r"\b(?:lei|RON|euro|EUR)\b", compact, limit=10)
    row["procurement_snippets"] = snippets(r"achizi|contract|atribu|concesi|închiri|inchiri|licita", compact, limit=8)
    return row


def candidate_priority(meta: dict[str, Any]) -> tuple[int, str]:
    text = (meta.get("link_text") or "") + " " + urllib.parse.unquote(meta.get("url") or "")
    folded = text.casefold()
    if TARGET_DATE_RO in folded:
        return (0, meta["url"])
    if "august" in folded or "08.2026" in folded or "2026" in folded:
        return (1, meta["url"])
    return (2, meta["url"])


def build_state() -> dict[str, Any]:
    discovered, health = discover()
    ordered = sorted(discovered, key=candidate_priority)
    documents: list[dict[str, Any]] = []
    for meta in ordered[:MAX_DOCUMENT_FETCHES]:
        documents.append(parse_document(meta))

    # Keep all exact target-date decisions plus enough latest-number context to
    # explain numbering gaps and to distinguish "not found" from crawl failure.
    target = [row for row in documents if row.get("target_date_match")]
    numbered = [row for row in documents if isinstance(row.get("decision_number"), int)]
    latest = sorted(numbered, key=lambda row: row["decision_number"], reverse=True)[:25]
    recent_august = [row for row in documents if str(row.get("decision_date") or "").startswith("2026-08-")]

    if target:
        target_status = "OFFICIAL_DECISIONS_FOUND_FOR_TARGET_DATE"
    elif any(str(row.get("decision_date") or "").startswith("2026-08-") for row in documents):
        target_status = "NO_TARGET_DATE_DECISION_FOUND_IN_ACCESSIBLE_OFFICIAL_REGISTER"
    elif discovered:
        target_status = "OFFICIAL_REGISTER_DISCOVERED_BUT_TARGET_DATE_NOT_RESOLVED"
    else:
        target_status = "OFFICIAL_REGISTER_STRUCTURE_NOT_RESOLVED"

    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "monitor_id": "council-watch-rm-valcea",
        "generated_at": now_iso(),
        "source": {
            "publisher": "Primăria Municipiului Râmnicu Vâlcea",
            "url": BASE,
            "tier": "T1",
            "official_host_only": True,
        },
        "target_meeting": {
            "date": TARGET_DATE_ISO,
            "weekday": "vineri",
            "status": target_status,
            "publication_allowed_from_this_state": False,
        },
        "discovery": {
            "document_links_found": len(discovered),
            "documents_fetched": len(documents),
            "reachable_documents": sum(1 for row in documents if row.get("reachable")),
            "page_health": health,
        },
        "target_decisions": target,
        "august_decisions": sorted(recent_august, key=lambda row: (row.get("decision_date") or "", row.get("decision_number") or -1), reverse=True)[:80],
        "latest_numbered_decisions": latest,
        "policy": {
            "source_discovery_is_not_story": True,
            "official_decision_text_required_for_result_claim": True,
            "agenda_item_is_not_adopted_decision": True,
            "no_inference_from_missing_document": True,
            "normal_story_ready_gate_required": True,
        },
    }


def self_test() -> int:
    sample = """
    ROMÂNIA CONSILIUL LOCAL HOTĂRÂREA NR. 250
    Consiliul Local întrunit în ședință la data de 14 august 2026.
    Întrunind votul unanim al membrilor prezenți, HOTĂRĂȘTE:
    Art.1. Se aprobă investiția la valoarea de 1.250.000 lei, inclusiv TVA.
    Art.2. Se mandatează direcția de specialitate să încheie contractul.
    """
    assert parse_ro_date(sample) == TARGET_DATE_ISO
    assert len(operative_articles(sample)) == 2
    assert snippets(r"\blei\b", sample)
    assert snippets(r"\bvot", sample)
    assert canonical_url(BASE, "/dm/2026/hotarari.nsf/vwHotarariByAn/ABC/$FILE/test.htm") is not None
    assert canonical_url(BASE, "https://evil.example/test") is None
    print("Râmnicu Vâlcea Council Watch self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    state = build_state()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": state["target_meeting"]["status"],
        "target_decisions": len(state["target_decisions"]),
        "august_decisions": len(state["august_decisions"]),
        "document_links_found": state["discovery"]["document_links_found"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
