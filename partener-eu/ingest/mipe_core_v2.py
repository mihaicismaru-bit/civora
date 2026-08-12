#!/usr/bin/env python3
"""Pure, deterministic primitives for PARTENER.EU MIPE ingestion v2.

No network access lives here.  Publication is intentionally fail-closed:
content becomes a MIPE fact only after a verified-TLS fetch from an explicit
official host (or a fresh, signed collector snapshot attesting the same).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import re
import unicodedata
import urllib.parse
from collections.abc import Iterable, Mapping
from html.parser import HTMLParser
from typing import Any, Optional

UTC = dt.timezone.utc
PRIORITY_PDDS_SEED = "https://mfe.gov.ro/pdds/despre-program-programare/"
PDDS_PREFIX = "/pdds/"

# Exact, reviewed MIPE/MySMIS web properties.  Never broaden to arbitrary gov.ro.
OFFICIAL_HOSTS = {
    "mfe.gov.ro",
    "generatormachete.mfe.gov.ro",
    "fonduri-ue.gov.ro",
    "www.fonduri-ue.gov.ro",
    "fonduri-ue.ro",
    "www.fonduri-ue.ro",
    "beneficiar.fonduri-ue.ro",
    "pncr.fonduri-ue.ro",
    "transfer.fonduri-ue.ro",
    "ticketing.smis.fonduri-ue.ro",
    "dwh4smis.fonduri-ue.ro",
    "reporting.mysmis2021.gov.ro",
    "resurse.mysmis2021.gov.ro",
    "mysmis2021.gov.ro",
    "www.mysmis2021.gov.ro",
}

TRACKING_KEYS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref", "source"}
ROMANIAN_MONTHS = {
    "ianuarie": 1, "ian": 1, "februarie": 2, "feb": 2,
    "martie": 3, "mar": 3, "aprilie": 4, "apr": 4, "mai": 5,
    "iunie": 6, "iun": 6, "iulie": 7, "iul": 7, "august": 8, "aug": 8,
    "septembrie": 9, "sept": 9, "sep": 9, "octombrie": 10, "oct": 10,
    "noiembrie": 11, "nov": 11, "decembrie": 12, "dec": 12,
}
MONTH_LABELS = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sept", "oct", "nov", "dec"]
RELEVANCE_TERMS = {
    "apel", "finantare", "finantari", "fonduri", "ghid", "solicitant",
    "corrigendum", "erata", "consultare", "termen", "depunere", "buget",
    "alocare", "program", "prioritate", "beneficiar", "eligibil", "mysmis",
    "pdds", "peo", "poids", "pids", "pnrr", "fse", "feder", "tranzitie justa",
}
EXCLUDED_TITLE_TERMS = {
    "post vacant", "concurs recrutare", "declaratie de avere",
    "achizitie publica", "anunt de angajare", "rezultate concurs",
}


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def iso_z(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def sha256_hex(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def normalize_url(value: str, base: Optional[str] = None) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(base or "", value.strip()))
    except (TypeError, ValueError):
        return None
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() not in {"http", "https"} or host not in OFFICIAL_HOSTS:
        return None
    if parsed.port not in (None, 443):
        return None
    try:
        path = urllib.parse.quote(
            urllib.parse.unquote(parsed.path or "/"),
            safe="/:@-._~!$&'()*+,;=",
        )
    except Exception:
        path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    if not path.startswith("/"):
        path = "/" + path
    leaf = path.rsplit("/", 1)[-1]
    if path != "/" and "." not in leaf and not path.endswith("/"):
        path += "/"
    kept: list[tuple[str, str]] = []
    for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in TRACKING_KEYS:
            continue
        kept.append((key, val))
    query = urllib.parse.urlencode(sorted(kept), doseq=True)
    return urllib.parse.urlunsplit(("https", host, path, query, ""))


def in_pdds_scope(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.hostname == "mfe.gov.ro" and parsed.path.startswith(PDDS_PREFIX)


def source_scope(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.lower()
    if parsed.hostname == "mfe.gov.ro" and path.startswith(PDDS_PREFIX):
        return "PDDS"
    if "ghiduri_peos" in path or re.search(r"/(?:peo)(?:/|$)", path):
        return "PEO"
    if "ghiduri_pids" in path or "poids" in path or re.search(r"/(?:pids)(?:/|$)", path):
        return "PoIDS"
    if parsed.hostname in {"reporting.mysmis2021.gov.ro", "resurse.mysmis2021.gov.ro"}:
        return "MYSMIS"
    return "MIPE"


class OfficialHTMLParser(HTMLParser):
    """Extract only stable semantic facts, canonical URL, dates and official links."""

    TEXT_TAGS = {"h1", "h2", "h3", "p", "li", "td", "th", "caption", "blockquote"}
    IGNORED = {"style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ignored_depth = 0
        self.title: list[str] = []
        self.h1: list[str] = []
        self.body: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: Optional[str] = None
        self.links: list[dict[str, str]] = []
        self.times: list[dict[str, str]] = []
        self._href: Optional[str] = None
        self._anchor_text: list[str] = []
        self._time_value: Optional[str] = None
        self._time_text: list[str] = []
        self._jsonld = False
        self._jsonld_text: list[str] = []
        self.jsonld: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        self.stack.append(tag)
        if tag in self.IGNORED:
            self.ignored_depth += 1
        if tag == "meta":
            key = (attrs_d.get("property") or attrs_d.get("name") or attrs_d.get("itemprop") or "").lower()
            if key and attrs_d.get("content"):
                self.meta[key] = attrs_d["content"]
        elif tag == "link":
            rel = {part.lower() for part in attrs_d.get("rel", "").split()}
            if "canonical" in rel and attrs_d.get("href"):
                self.canonical = attrs_d["href"]
        elif tag == "a":
            self._href = attrs_d.get("href") or None
            self._anchor_text = []
        elif tag == "time":
            self._time_value = attrs_d.get("datetime") or ""
            self._time_text = []
        elif tag == "script" and "ld+json" in attrs_d.get("type", "").lower():
            self._jsonld = True
            self._jsonld_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._href is not None:
            self.links.append({"href": self._href, "text": clean(" ".join(self._anchor_text))})
            self._href = None
            self._anchor_text = []
        elif tag == "time" and self._time_value is not None:
            self.times.append({"datetime": self._time_value, "text": clean(" ".join(self._time_text))})
            self._time_value = None
            self._time_text = []
        elif tag == "script" and self._jsonld:
            try:
                self.jsonld.append(json.loads("".join(self._jsonld_text)))
            except Exception:
                pass
            self._jsonld = False
            self._jsonld_text = []
        if tag in self.IGNORED and self.ignored_depth:
            self.ignored_depth -= 1
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._jsonld:
            self._jsonld_text.append(data)
        if self.ignored_depth or not data.strip():
            return
        current = self.stack[-1] if self.stack else ""
        if current == "title":
            self.title.append(data)
        if current == "h1":
            self.h1.append(data)
        if current in self.TEXT_TAGS:
            self.body.append(data)
        if self._href is not None:
            self._anchor_text.append(data)
        if self._time_value is not None:
            self._time_text.append(data)


def _walk_json(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def parse_datetime(value: Any) -> Optional[dt.datetime]:
    raw = clean(value)
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(raw[:10], fmt).replace(tzinfo=UTC)
        except Exception:
            continue
    match = re.search(
        r"\b([0-3]?\d)\s+(ianuarie|ian|februarie|feb|martie|mar|aprilie|apr|mai|iunie|iun|iulie|iul|august|aug|septembrie|sept|sep|octombrie|oct|noiembrie|nov|decembrie|dec)\s+(20\d{2})(?:\s*,?\s*(?:ora\s*)?([0-2]?\d)[:.]([0-5]\d))?\b",
        fold(raw),
    )
    if not match:
        return None
    day, month, year, hour, minute = match.groups()
    try:
        return dt.datetime(int(year), ROMANIAN_MONTHS[month], int(day), int(hour or 0), int(minute or 0), tzinfo=UTC)
    except ValueError:
        return None


def find_explicit_dates(text: str) -> list[dt.datetime]:
    patterns = (
        r"\b20\d{2}[-/.][01]?\d[-/.][0-3]?\d(?:[T\s][0-2]?\d:[0-5]\d(?::[0-5]\d)?)?\b",
        r"\b[0-3]?\d[./-][01]?\d[./-]20\d{2}(?:\s+(?:ora\s*)?[0-2]?\d[:.][0-5]\d)?\b",
        r"\b[0-3]?\d\s+(?:ianuarie|ian|februarie|feb|martie|mar|aprilie|apr|mai|iunie|iun|iulie|iul|august|aug|septembrie|sept|sep|octombrie|oct|noiembrie|nov|decembrie|dec)\s+20\d{2}(?:\s*,?\s*(?:ora\s*)?[0-2]?\d[:.][0-5]\d)?\b",
    )
    found: dict[str, dt.datetime] = {}
    for pattern in patterns:
        for match in re.finditer(pattern, clean(text), flags=re.I):
            parsed = parse_datetime(match.group(0))
            if parsed:
                found[iso_z(parsed)] = parsed
    return list(found.values())


def _jsonld_dates(items: list[Any]) -> tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    published = modified = None
    for root in items:
        for node in _walk_json(root):
            if not published:
                for key in ("datePublished", "dateCreated", "uploadDate"):
                    published = parse_datetime(node.get(key))
                    if published:
                        break
            if not modified:
                modified = parse_datetime(node.get("dateModified"))
            if published and modified:
                return published, modified
    return published, modified


def extract_html_document(data: bytes, final_url: str, headers: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    parser = OfficialHTMLParser()
    parser.feed(data.decode("utf-8", errors="replace"))
    meta = {key.lower(): clean(value) for key, value in parser.meta.items()}
    title = clean(meta.get("og:title") or meta.get("twitter:title") or " ".join(parser.h1) or " ".join(parser.title))
    description = clean(meta.get("description") or meta.get("og:description") or meta.get("twitter:description"))
    body = clean(" ".join(parser.body))
    normalized_final = normalize_url(final_url)
    canonical = normalize_url(parser.canonical or final_url, final_url)

    published = modified = None
    for key in ("article:published_time", "datepublished", "dc.date", "dcterms.created", "date"):
        published = parse_datetime(meta.get(key))
        if published:
            break
    for key in ("article:modified_time", "datemodified", "dcterms.modified"):
        modified = parse_datetime(meta.get(key))
        if modified:
            break
    json_published, json_modified = _jsonld_dates(parser.jsonld)
    published = published or json_published
    modified = modified or json_modified
    if not published:
        for item in parser.times:
            published = parse_datetime(item.get("datetime")) or parse_datetime(item.get("text"))
            if published:
                break
    if not modified and headers:
        modified = parse_datetime(headers.get("last-modified") or headers.get("Last-Modified"))

    links: list[dict[str, str]] = []
    for link in parser.links:
        url = normalize_url(link.get("href", ""), final_url)
        if url:
            links.append({"url": url, "text": clean(link.get("text"))})
    fingerprint = "\n".join((title, description, body))
    return {
        "title": title,
        "description": description,
        "body": body,
        "canonicalUrl": canonical,
        "finalUrl": normalized_final,
        "publishedAt": iso_z(published) if published else None,
        "modifiedAt": iso_z(modified) if modified else None,
        "contentDates": [iso_z(item) for item in find_explicit_dates(body[:30000])],
        "links": links,
        "contentSha256": sha256_hex(fingerprint),
        "rawSha256": sha256_hex(data),
    }


def relevance_score(title: str, description: str, body: str, url: str) -> int:
    title_f = fold(title)
    all_f = fold(" ".join((title, description, body[:7000], url)))
    score = 0
    for term in RELEVANCE_TERMS:
        if term in title_f:
            score += 3
        elif term in all_f:
            score += 1
    if any(term in title_f for term in EXCLUDED_TITLE_TERMS):
        score -= 15
    if source_scope(url) in {"PDDS", "PEO", "PoIDS", "MYSMIS"}:
        score += 2
    return score


def detect_program(text: str, url: str = "") -> str:
    value = fold(text + " " + url)
    if "pdds" in value or "dezvoltare durabila" in value:
        return "PDDS"
    if re.search(r"\bpeo\b", value) or "educatie si ocupare" in value:
        return "PEO"
    if "poids" in value or "pids" in value or "incluziune si demnitate sociala" in value:
        return "PoIDS"
    if "pnrr" in value:
        return "PNRR"
    if "tranzitie justa" in value or re.search(r"\bptj\b", value):
        return "PTJ"
    if "program regional" in value:
        return "REGIONAL"
    if "mysmis" in value:
        return "MYSMIS"
    return "MIPE"


def classify_event(title: str, description: str, body: str) -> tuple[str, list[str]]:
    raw = " ".join((title, description, body[:18000]))
    text = fold(raw)
    has_date = bool(find_explicit_dates(raw))
    evidence: list[str] = []

    if "corrigendum" in text or re.search(r"\berata\b", text):
        return "GUIDE_MODIFIED", ["explicit corrigendum/erata wording"]
    if re.search(r"\b(prelung(?:ire|este|it|ita)|s-a prelungit)\b", text) and "termen" in text and has_date:
        return "DEADLINE_EXTENDED", ["explicit extension wording", "explicit deadline date"]
    if "consultare publica" in text:
        if has_date and any(term in text for term in ("termen", "pana la", "observatii", "propuneri")):
            return "CONSULTATION_OPENED", ["explicit public-consultation wording", "explicit consultation date"]
        return "OFFICIAL_UPDATE", ["public-consultation wording without verified closing date"]

    guide = "ghidul solicitantului" in text or "ghid solicitant" in text
    guide_final = any(phrase in text for phrase in (
        "ghidul a fost aprobat", "ghidul solicitantului aprobat", "publica ghidul solicitantului",
        "ghid final", "versiunea finala a ghidului", "ordin privind aprobarea ghidului",
    ))
    if guide and guide_final:
        return "GUIDE_PUBLISHED", ["guide wording", "explicit publication/approval wording"]

    open_signal = any(phrase in text for phrase in (
        "apelul este deschis", "apel deschis", "deschiderea apelului", "lanseaza apelul",
        "a fost lansat apelul", "lansarea apelului", "se deschide apelul",
        "depunerea cererilor de finantare incepe", "se pot depune cereri de finantare",
    ))
    submission = any(phrase in text for phrase in (
        "depunerea cererilor", "depunerea proiectelor", "perioada de depunere",
        "termen limita de depunere", "pana la data de", "incepand cu data de",
    ))
    if open_signal and submission and has_date:
        return "CALL_OPENED", ["explicit launch/open wording", "explicit submission wording", "explicit date"]
    if "buget" in text and any(word in text for word in ("majorat", "suplimentat", "realocat", "alocare actualizata")):
        return "BUDGET_UPDATED", ["explicit budget-change wording"]
    if any(phrase in text for phrase in ("programul a fost modificat", "modificarea programului", "decizia comisiei")):
        return "POLICY_UPDATED", ["explicit programme/policy modification wording"]
    if guide:
        evidence.append("guide mentioned without explicit publication/approval wording")
    elif "apel de proiecte" in text or "apeluri de proiecte" in text:
        evidence.append("generic call wording; OPEN intentionally not inferred")
    return "OFFICIAL_UPDATE", evidence


def date_label(value: Any) -> str:
    parsed = parse_datetime(value)
    if not parsed:
        return "dată neprecizată"
    return f"{parsed.day} {MONTH_LABELS[parsed.month - 1]} {parsed.year}"


def summarize(description: str, body: str, limit: int = 700) -> str:
    text = clean(description)
    if len(text) < 60:
        text = clean(body)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def build_page_item(
    document: Mapping[str, Any], *, fetched_at: str, transport: str,
    http_status: int, change_type: str, discovery: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    canonical = normalize_url(str(document.get("canonicalUrl") or ""))
    final_url = normalize_url(str(document.get("finalUrl") or ""))
    if not canonical or not final_url:
        return None
    title = clean(document.get("title"))
    description = clean(document.get("description"))
    body = clean(document.get("body"))
    if len(title) < 8 or relevance_score(title, description, body, canonical) < 3:
        return None
    kind, evidence = classify_event(title, description, body)
    event_at = document.get("publishedAt") or document.get("modifiedAt") or fetched_at
    basis = "publishedAt" if document.get("publishedAt") else ("modifiedAt" if document.get("modifiedAt") else "observedAt")
    programme = detect_program(" ".join((title, description, body[:2500])), canonical)
    item = {
        "id": sha256_hex(canonical + "\n" + str(document.get("contentSha256") or ""))[:24],
        "title": title[:360],
        "url": canonical,
        "canonicalUrl": canonical,
        "date": str(event_at)[:10],
        "dateLabel": date_label(event_at),
        "dateBasis": basis,
        "publishedAt": document.get("publishedAt"),
        "modifiedAt": document.get("modifiedAt"),
        "summary": summarize(description, body),
        "tag": programme,
        "kind": kind,
        "status": "OPEN" if kind == "CALL_OPENED" else "NEWS",
        "tier": "T1",
        "source": "MIPE",
        "sourceAdapter": "OFFICIAL_WEB_PAGE",
        "changeType": change_type,
        "observedAt": fetched_at,
        "evidence": evidence,
        "provenance": {
            "fetchedUrl": final_url,
            "canonicalUrl": canonical,
            "fetchedAt": fetched_at,
            "transport": transport,
            "httpStatus": int(http_status),
            "tlsVerified": True,
            "contentSha256": str(document.get("contentSha256") or ""),
            "rawSha256": str(document.get("rawSha256") or ""),
            "canonicalEvidence": "rel=canonical" if canonical != final_url else "verified final URL",
            "discovery": dict(discovery or {}),
        },
    }
    return item if validate_item(item) else None


def validate_item(item: Mapping[str, Any]) -> bool:
    url = normalize_url(str(item.get("url") or ""))
    if not url or url != item.get("url"):
        return False
    provenance = item.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("tlsVerified") is not True:
        return False
    try:
        status_code = int(provenance.get("httpStatus") or 0)
    except (TypeError, ValueError):
        return False
    if not 200 <= status_code < 400:
        return False
    if normalize_url(str(provenance.get("canonicalUrl") or "")) != url:
        return False
    if item.get("kind") == "CALL_OPENED":
        evidence = {str(value) for value in item.get("evidence") or []}
        textual = {"explicit launch/open wording", "explicit submission wording", "explicit date"}
        structured = (
            "structured official MySMIS row" in evidence
            and any(value.startswith("structured official state=") for value in evidence)
            and item.get("sourceAdapter") == "MYSMIS_REGISTRY"
        )
        if not textual.issubset(evidence) and not structured:
            return False
        if item.get("status") != "OPEN":
            return False
    elif item.get("status") == "OPEN":
        return False
    return len(clean(item.get("title"))) >= 8


def canonical_snapshot_payload(snapshot: Mapping[str, Any]) -> bytes:
    body = {key: value for key, value in snapshot.items() if key != "signature"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_snapshot(snapshot: Mapping[str, Any], secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), canonical_snapshot_payload(snapshot), hashlib.sha256).hexdigest()


def verify_snapshot(snapshot: Mapping[str, Any], secret: str, max_age_hours: int = 48) -> tuple[bool, str, Optional[bytes]]:
    if not secret:
        return False, "relay HMAC secret is not configured", None
    supplied = str(snapshot.get("signature") or "")
    expected = sign_snapshot(snapshot, secret)
    if not supplied or not hmac.compare_digest(supplied, expected):
        return False, "invalid relay signature", None
    if snapshot.get("signatureAlgorithm") != "HMAC-SHA256":
        return False, "unsupported relay signature algorithm", None
    fetched = parse_datetime(snapshot.get("fetchedAt"))
    if not fetched:
        return False, "invalid fetchedAt", None
    age = now_utc() - fetched
    if age < dt.timedelta(minutes=-5) or age > dt.timedelta(hours=max_age_hours):
        return False, "snapshot outside freshness window", None
    if not normalize_url(str(snapshot.get("url") or "")) or not normalize_url(str(snapshot.get("finalUrl") or "")):
        return False, "snapshot URL outside official registry", None
    if snapshot.get("tlsVerified") is not True:
        return False, "collector did not attest verified TLS", None
    try:
        status = int(snapshot.get("httpStatus") or 0)
    except (TypeError, ValueError):
        return False, "invalid HTTP status", None
    if not 200 <= status < 400:
        return False, "unsuccessful HTTP status", None
    try:
        body = base64.b64decode(str(snapshot.get("bodyBase64") or ""), validate=True)
    except Exception:
        return False, "invalid body encoding", None
    if not body or sha256_hex(body) != snapshot.get("bodySha256"):
        return False, "body hash mismatch", None
    return True, "ok", body


def parse_feed_js(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta_match = re.search(r"window\.PARTENER_DATA\.mipeIngestion\s*=\s*(\{.*?\});", text, flags=re.S)
    item_match = re.search(r"window\.PARTENER_DATA\.mipeNews\s*=\s*(\[.*\]);", text, flags=re.S)
    meta: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    try:
        if meta_match:
            value = json.loads(meta_match.group(1))
            if isinstance(value, dict):
                meta = value
    except Exception:
        pass
    try:
        if item_match:
            value = json.loads(item_match.group(1))
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, dict)]
    except Exception:
        pass
    return meta, items


def render_feed_js(meta: Mapping[str, Any], items: Iterable[Mapping[str, Any]]) -> str:
    return (
        "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        "window.PARTENER_DATA.mipeIngestion="
        + json.dumps(dict(meta), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA.mipeNews="
        + json.dumps([dict(item) for item in items], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + ";\n"
    )


def _entity_key(item: Mapping[str, Any]) -> str:
    provenance = item.get("provenance")
    if item.get("sourceAdapter") == "MYSMIS_REGISTRY" and isinstance(provenance, Mapping):
        row = provenance.get("structuredRow")
        if isinstance(row, Mapping) and row.get("id"):
            return "MYSMIS:" + str(row["id"])
    return "URL:" + str(item.get("url"))


def merge_feed_items(previous: Iterable[Mapping[str, Any]], fresh: Iterable[Mapping[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in previous:
        if validate_item(item):
            merged[_entity_key(item)] = dict(item)
    for item in fresh:
        if validate_item(item):
            merged[_entity_key(item)] = dict(item)
    values = list(merged.values())
    values.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("observedAt") or ""), str(item.get("title") or "")), reverse=True)
    return values[:limit]


def health_fingerprint(health: Mapping[str, Any]) -> str:
    stable = {
        "status": health.get("status"),
        "prioritySeedAvailable": health.get("prioritySeedAvailable"),
        "sourceAvailability": health.get("sourceAvailability"),
        "failureClasses": health.get("failureClasses"),
        "verifiedCount": health.get("verifiedCount"),
        "newItemCount": health.get("newItemCount"),
        "registry": health.get("registry"),
    }
    return sha256_hex(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
