from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = "ValceaClar-InvestigationMonitor/1.0 (+https://valceaclar.ro)"
MAX_BYTES = 1_500_000


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._suppressed += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "template"} and self._suppressed:
            self._suppressed -= 1

    def handle_data(self, data: str) -> None:
        if self._suppressed:
            return
        value = normalize_space(data)
        if value:
            self.parts.append(value)


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_for_match(value: str) -> str:
    table = str.maketrans("ĂÂÎȘŞȚŢăâîșşțţ", "AAISSTTaaisstt")
    return normalize_space(html.unescape(value)).translate(table).casefold()


def semantic_clean(value: str) -> str:
    value = re.sub(r"\b\d+\s*(?:vizualizari|vizualizări|views)\b", "", value, flags=re.I)
    value = re.sub(r"Ultima modificare[^\n]{0,120}", "", value, flags=re.I)
    return normalize_space(value)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(url: str, timeout: float) -> tuple[bytes, dict[str, str], str, int]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,application/rss+xml,application/atom+xml;q=0.9,*/*;q=0.3",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_BYTES)
        headers = {key.lower(): value for key, value in response.headers.items()}
        return body, headers, response.geturl(), int(getattr(response, "status", 200))


def focused_text_from_html(body: bytes, terms: list[str]) -> dict[str, Any]:
    parser = VisibleTextParser()
    parser.feed(body.decode("utf-8", "replace"))
    chunks = [normalize_space(part) for part in parser.parts if normalize_space(part)]
    normalized_terms = [normalize_for_match(term) for term in terms]
    selected: list[str] = []
    for index, chunk in enumerate(chunks):
        normalized = normalize_for_match(chunk)
        if any(term in normalized for term in normalized_terms):
            selected.extend(chunks[max(0, index - 1):min(len(chunks), index + 2)])
    selected = list(dict.fromkeys(selected))
    link_hits = []
    for link in parser.links:
        normalized = normalize_for_match(link).replace(" ", "")
        if any(term.replace(" ", "") in normalized for term in normalized_terms):
            link_hits.append(link)
    focused = "\n".join(semantic_clean(item) for item in selected if semantic_clean(item))
    focused += "\n" + "\n".join(sorted(set(link_hits)))
    return {
        "focused_text": focused.strip(),
        "focused_excerpt": selected[:12],
        "match_count": len(selected),
        "link_hits": sorted(set(link_hits))[:20],
        "document_text_length": sum(len(part) for part in chunks),
    }


def rss_entries(body: bytes, terms: list[str]) -> dict[str, Any]:
    root = ET.fromstring(body)
    normalized_terms = [normalize_for_match(term) for term in terms]
    candidates = list(root.findall(".//item"))
    if not candidates:
        candidates = list(root.findall(".//{http://www.w3.org/2005/Atom}entry"))
    entries: list[dict[str, str]] = []
    for node in candidates[:100]:
        title = normalize_space(node.findtext("title", default=""))
        description = normalize_space(node.findtext("description", default=""))
        link = node.findtext("link", default="")
        if not link:
            atom_link = node.find("{http://www.w3.org/2005/Atom}link")
            link = atom_link.attrib.get("href", "") if atom_link is not None else ""
        published = (
            node.findtext("pubDate", default="")
            or node.findtext("{http://www.w3.org/2005/Atom}published", default="")
            or node.findtext("{http://www.w3.org/2005/Atom}updated", default="")
        )
        combined = normalize_for_match(f"{title} {description} {link}")
        if normalized_terms and not any(term in combined for term in normalized_terms):
            continue
        entries.append({
            "fingerprint": sha256_text(f"{title}\n{link}\n{published}"),
            "title": title,
            "link": link,
            "published": normalize_space(published),
        })
    entries = entries[:30]
    focused = "\n".join(f"{item['title']}|{item['link']}|{item['published']}" for item in entries)
    return {
        "focused_text": focused,
        "focused_excerpt": [item["title"] for item in entries[:12]],
        "entries": entries,
        "match_count": len(entries),
        "link_hits": [item["link"] for item in entries[:20]],
        "document_text_length": len(body),
    }
