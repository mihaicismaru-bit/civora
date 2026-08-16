#!/usr/bin/env python3
"""Râmnicu Vâlcea Council Watch — official adopted-decision reader.

The monitor reads the municipality's official 2026 DocManager HCL register and
keeps a durable review state. It never turns an agenda item into an adopted
result and never publishes directly.

Contract:
- the official `HOTARARI ADOPTATE` register proves what has been published;
- a target meeting date is confirmed only by HCL entries carrying that date;
- when target HCLs exist, their official HTML attachments are fetched to expose
  operative articles, vote language, money and procurement references;
- when the register still stops before the target date, the state says exactly
  that instead of inferring approval, rejection, postponement or even that the
  meeting took place.
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
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "editorial" / "council_watch_rm_valcea_state.json"
BASE = "https://dm.primariavl.ro/dm/2026/hotarari.nsf"
ADOPTED_VIEW = BASE + "/vwHotarariByAn?OpenView&Count=500"
OFFICIAL_HOST = "dm.primariavl.ro"
USER_AGENT = "VALCEA-CLAR-Council-Watch/1.1 (+https://valceaclar.ro/)"
TARGET_DATE_ISO = "2026-08-14"
MAX_BYTES = 3_000_000
MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}
MONTH_PATTERN = "|".join(MONTHS)
ENTRY_PATTERN = re.compile(
    rf"\b2026\s+(?P<number>\d{{1,4}})\s+hotarirea\s+(?P=number)\s*-\s*"
    rf"(?P<day>[0-3]?\d)\s+(?P<month>{MONTH_PATTERN})\s+2026\s*-\s*"
    rf"(?P<title>.*?)(?=\s+2026\s+\d{{1,4}}\s+hotarirea\s+\d{{1,4}}\s*-|\Z)",
    re.I,
)
ATTACHMENT_LABEL = re.compile(
    rf"hotarirea\s+(?P<number>\d{{1,4}})\s*-\s*(?P<day>[0-3]?\d)\s+"
    rf"(?P<month>{MONTH_PATTERN})\s+2026\s*-",
    re.I,
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "a" and data.get("href"):
            self._href = data["href"]
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            self.links.append({"href": self._href, "text": text})
            self._href = None
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)


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
        key = charset.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(charset)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch(url: str, timeout: int = 18) -> dict[str, Any]:
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
            return {
                "ok": True,
                "status": int(response.status),
                "url": str(response.geturl()),
                "body": decode_body(raw, response.headers.get("content-type") or ""),
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
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() != OFFICIAL_HOST:
        return None
    if not parsed.path.lower().startswith("/dm/2026/hotarari.nsf"):
        return None
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/$:@")
    query = urllib.parse.quote(urllib.parse.unquote(parsed.query), safe="=&:$,()/-")
    return urllib.parse.urlunparse(("https", parsed.netloc, path, parsed.params, query, ""))


def to_text(body: str) -> str:
    parser = TextParser()
    parser.feed(body)
    return parser.text()


def parse_links(page_url: str, body: str) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(body)
    rows: list[dict[str, str]] = []
    for link in parser.links:
        url = canonical_url(page_url, link.get("href") or "")
        if url:
            rows.append({"url": url, "text": link.get("text") or ""})
    return rows


def iso_date(day: int, month_name: str) -> str | None:
    try:
        return date(2026, MONTHS[month_name.casefold()], day).isoformat()
    except (KeyError, ValueError):
        return None


def parse_register(text: str) -> list[dict[str, Any]]:
    compact = re.sub(r"\s+", " ", text)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for match in ENTRY_PATTERN.finditer(compact):
        number = int(match.group("number"))
        if number in seen:
            continue
        seen.add(number)
        decision_date = iso_date(int(match.group("day")), match.group("month"))
        title = re.sub(r"\s+", " ", match.group("title")).strip(" -|\t\r\n")
        rows.append({
            "decision_number": number,
            "decision_date": decision_date,
            "title": title,
        })
    return rows


def attachment_index(page_url: str, body: str) -> dict[tuple[int, str], str]:
    result: dict[tuple[int, str], str] = {}
    for link in parse_links(page_url, body):
        low = urllib.parse.unquote(link["url"]).lower()
        if "$file" not in low or not low.endswith((".htm", ".html")):
            continue
        label = urllib.parse.unquote(link.get("text") or "") + " " + urllib.parse.unquote(link["url"])
        match = ATTACHMENT_LABEL.search(label)
        if not match:
            continue
        decision_date = iso_date(int(match.group("day")), match.group("month"))
        if not decision_date:
            continue
        result[(int(match.group("number")), decision_date)] = link["url"]
    return result


def snippets(pattern: str, text: str, limit: int = 10, radius: int = 300) -> list[str]:
    compact = re.sub(r"\s+", " ", text)
    rows: list[str] = []
    for match in re.finditer(pattern, compact, flags=re.I):
        start = max(0, match.start() - radius)
        end = min(len(compact), match.end() + radius)
        piece = compact[start:end].strip()
        if piece and piece not in rows:
            rows.append(piece)
        if len(rows) >= limit:
            break
    return rows


def operative_articles(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text)
    matches = list(re.finditer(r"\bArt\.\s*(\d+)\.?\s*", compact, flags=re.I))
    rows: list[str] = []
    for index, match in enumerate(matches[:16]):
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(compact), match.start() + 1400)
        piece = compact[match.start():end].strip()
        if len(piece) > 1050:
            piece = piece[:1050].rsplit(" ", 1)[0] + "…"
        rows.append(piece)
    return rows


def enrich_target(row: dict[str, Any], official_html_url: str | None) -> dict[str, Any]:
    enriched = dict(row)
    enriched["official_html_url"] = official_html_url
    if not official_html_url:
        enriched["document_health"] = "OFFICIAL_ATTACHMENT_NOT_RESOLVED"
        return enriched
    result = fetch(official_html_url)
    enriched["document_health"] = "OK" if result["ok"] else "UNREACHABLE"
    enriched["http_status"] = result["status"]
    enriched["source_sha256"] = result["sha256"]
    enriched["error"] = result["error"]
    if not result["ok"]:
        return enriched
    text = to_text(result["body"])
    enriched["operative_articles"] = operative_articles(text)
    enriched["vote_snippets"] = snippets(r"\bvot(?:uri|ul|at|uri)?\b|unanimit|abțin|abtin|împotriv|impotriv", text, limit=8)
    enriched["money_snippets"] = snippets(r"\b(?:lei|RON|euro|EUR)\b", text, limit=10)
    enriched["procurement_snippets"] = snippets(r"achizi|contract|atribu|concesi|închiri|inchiri|licita", text, limit=8)
    return enriched


def build_state() -> dict[str, Any]:
    result = fetch(ADOPTED_VIEW)
    if not result["ok"]:
        return {
            "schema_version": "1.1",
            "instance_id": "valcea",
            "monitor_id": "council-watch-rm-valcea",
            "generated_at": now_iso(),
            "source": {"publisher": "Primăria Municipiului Râmnicu Vâlcea", "url": ADOPTED_VIEW, "tier": "T1"},
            "target_meeting": {
                "date": TARGET_DATE_ISO,
                "status": "OFFICIAL_ADOPTED_HCL_REGISTER_UNREACHABLE",
                "publication_allowed_from_this_state": False,
            },
            "register_health": {"reachable": False, "http_status": result["status"], "error": result["error"]},
            "target_decisions": [],
            "policy": {
                "agenda_item_is_not_adopted_decision": True,
                "no_inference_from_missing_document": True,
                "normal_story_ready_gate_required": True,
            },
        }

    text = to_text(result["body"])
    register = parse_register(text)
    attachments = attachment_index(result["url"], result["body"])
    register.sort(key=lambda row: row["decision_number"], reverse=True)
    latest = register[0] if register else None
    target_rows = [row for row in register if row.get("decision_date") == TARGET_DATE_ISO]
    target = [
        enrich_target(row, attachments.get((row["decision_number"], TARGET_DATE_ISO)))
        for row in target_rows
    ]

    if target_rows:
        status = "OFFICIAL_ADOPTED_DECISIONS_PUBLISHED_FOR_TARGET_DATE"
    elif latest and latest.get("decision_date") and latest["decision_date"] < TARGET_DATE_ISO:
        status = "TARGET_DATE_NOT_YET_PUBLISHED_IN_OFFICIAL_ADOPTED_HCL_REGISTER"
    elif latest and latest.get("decision_date") and latest["decision_date"] >= TARGET_DATE_ISO:
        status = "NO_OFFICIAL_ADOPTED_DECISION_FOUND_FOR_TARGET_DATE"
    elif register:
        status = "OFFICIAL_REGISTER_DATE_NOT_RESOLVED"
    else:
        status = "OFFICIAL_REGISTER_EMPTY_OR_STRUCTURE_CHANGED"

    return {
        "schema_version": "1.1",
        "instance_id": "valcea",
        "monitor_id": "council-watch-rm-valcea",
        "generated_at": now_iso(),
        "source": {
            "publisher": "Primăria Municipiului Râmnicu Vâlcea",
            "url": ADOPTED_VIEW,
            "tier": "T1",
            "official_host_only": True,
            "register_label": "HOTARARI ADOPTATE",
        },
        "target_meeting": {
            "date": TARGET_DATE_ISO,
            "weekday": "vineri",
            "status": status,
            "publication_allowed_from_this_state": False,
        },
        "register_health": {
            "reachable": True,
            "http_status": result["status"],
            "source_sha256": result["sha256"],
            "entries_parsed": len(register),
            "official_html_attachments_indexed": len(attachments),
        },
        "latest_official_decision": latest,
        "target_decisions": target,
        "latest_decisions": register[:25],
        "policy": {
            "source_discovery_is_not_story": True,
            "official_decision_text_required_for_result_claim": True,
            "agenda_item_is_not_adopted_decision": True,
            "meeting_occurrence_not_inferred_from_missing_hcl": True,
            "missing_target_hcl_does_not_mean_rejected_or_postponed": True,
            "normal_story_ready_gate_required": True,
        },
    }


def self_test() -> int:
    sample = """
    HOTARARI ADOPTATE
    An Nr. hotarare Titlul hotararii
    2026 304 hotarirea 304 - 23 iulie 2026 - acordare autorizatie anuala
    2026 303 hotarirea 303 - 23 iulie 2026 - alta hotarare
    """
    rows = parse_register(sample)
    assert rows == [
        {"decision_number": 304, "decision_date": "2026-07-23", "title": "acordare autorizatie anuala"},
        {"decision_number": 303, "decision_date": "2026-07-23", "title": "alta hotarare"},
    ]
    assert canonical_url(BASE, "/dm/2026/hotarari.nsf/x/$FILE/a b.htm") == "https://dm.primariavl.ro/dm/2026/hotarari.nsf/x/$FILE/a%20b.htm"
    assert canonical_url(BASE, "https://evil.example/test") is None
    sample_hcl = "Consiliul Local, întrunind 20 de voturi pentru, HOTĂRĂȘTE: Art.1. Se aprobă suma de 100.000 lei. Art.2. Se încheie contractul."
    assert len(operative_articles(sample_hcl)) == 2
    assert snippets(r"\blei\b", sample_hcl)
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
        "latest_official_decision": state.get("latest_official_decision"),
        "target_decisions": len(state.get("target_decisions") or []),
        "entries_parsed": state.get("register_health", {}).get("entries_parsed"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
