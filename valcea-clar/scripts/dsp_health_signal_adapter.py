#!/usr/bin/env python3
"""Extract dated DSP Vâlcea public-health campaign signals without publication authority.

The adapter is deliberately evidence-first: it accepts only dates or month periods
that are explicit in visible source text. Campaign/event periods are preserved as
period semantics and are never relabelled as publication timestamps. Output is
signal-only and cannot authorize a public story.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SOURCE_ID = "signal-dsp-valcea-promovarea-sanatatii"
SOURCE_NAME = "Direcția de Sănătate Publică Vâlcea — Promovarea sănătății"
SOURCE_URL = "https://www.aspjvalcea.ro/documente-utile/promovarea-sanatatii.php"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_HEALTH_CAMPAIGNS"
CURRENT_HOSTS = {"aspjvalcea.ro", "www.aspjvalcea.ro"}
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-DSP-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
MIN_SECTION_TEXT = 8
SIGNAL_TERMS = (
    "campan", "sanat", "sănăt", "preven", "recomand", "canicul",
    "tutun", "nicotin", "alcool", "activitate fizica", "activității fizice",
)
RO_MONTHS = {
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


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


class SectionParser(html.parser.HTMLParser):
    """Collect heading-led visible sections while ignoring script/style payloads."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.heading_depth = 0
        self.heading_parts: list[str] = []
        self.current_title = ""
        self.current_parts: list[str] = []
        self.sections: list[dict[str, str]] = []

    def _flush(self) -> None:
        title = clean_text(self.current_title)
        body = clean_text(" ".join(self.current_parts))
        if title and len(body) >= MIN_SECTION_TEXT:
            self.sections.append({"title": title, "text": body})
        self.current_parts = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self._flush()
            self.heading_depth += 1
            self.heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4"} and self.heading_depth:
            self.heading_depth -= 1
            self.current_title = clean_text(" ".join(self.heading_parts))
            self.heading_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        if self.heading_depth:
            self.heading_parts.append(text)
        elif self.current_title:
            self.current_parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush()


def month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last_day).isoformat()


def extract_period(text: str) -> dict[str, str] | None:
    """Return only explicit temporal evidence; never infer a date from retrieval time."""
    value = clean_text(text)
    exact = re.search(r"(?<!\d)([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})(?!\d)", value)
    if exact:
        try:
            d = date(int(exact.group(3)), int(exact.group(2)), int(exact.group(1)))
        except ValueError:
            return None
        return {
            "period_start": d.isoformat(),
            "period_end": d.isoformat(),
            "temporal_precision": "EXACT_DATE",
            "temporal_evidence": exact.group(0),
        }

    folded = fold(value)
    month_alt = "|".join(RO_MONTHS)
    ranged = re.search(
        rf"\b({month_alt})\s*(?:-|–|—|pana\s+la|până\s+la)\s*({month_alt})\s+((?:20)\d{{2}})\b",
        folded,
    )
    if ranged:
        start_month = RO_MONTHS[ranged.group(1)]
        end_month = RO_MONTHS[ranged.group(2)]
        year = int(ranged.group(3))
        if end_month < start_month:
            return None
        start, _ = month_bounds(year, start_month)
        _, end = month_bounds(year, end_month)
        return {
            "period_start": start,
            "period_end": end,
            "temporal_precision": "MONTH_RANGE",
            "temporal_evidence": ranged.group(0),
        }

    single = re.search(rf"\b({month_alt})\s+((?:20)\d{{2}})\b", folded)
    if single:
        month = RO_MONTHS[single.group(1)]
        year = int(single.group(2))
        start, end = month_bounds(year, month)
        return {
            "period_start": start,
            "period_end": end,
            "temporal_precision": "MONTH",
            "temporal_evidence": single.group(0),
        }
    return None


def relevant_section(title: str, text: str) -> bool:
    hay = fold(f"{title} {text}")
    return any(fold(term) in hay for term in SIGNAL_TERMS)


def signal_id(title: str, period: dict[str, str]) -> str:
    raw = "\0".join(
        [SOURCE_ID, clean_text(title), period["period_start"], period["period_end"]]
    )
    return "dsp-health-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def extract_signals(html_text: str, *, final_url: str = SOURCE_URL) -> list[dict[str, Any]]:
    parsed = urlsplit(final_url)
    host = parsed.netloc.casefold()
    if host not in CURRENT_HOSTS:
        raise ValueError(f"DSP adapter refused unexpected final host: {host or '<empty>'}")

    parser = SectionParser()
    parser.feed(html_text)
    parser.close()

    signals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in parser.sections:
        title = clean_text(section["title"])
        body = clean_text(section["text"])
        if not relevant_section(title, body):
            continue
        period = extract_period(f"{title} {body}")
        if period is None:
            continue
        sid = signal_id(title, period)
        if sid in seen:
            continue
        seen.add(sid)
        signals.append({
            "signal_id": sid,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "final_url": final_url,
            "source_tier": SOURCE_TIER,
            "source_kind": SOURCE_KIND,
            "title": title,
            **period,
            "date_semantics": "CAMPAIGN_OR_EVENT_PERIOD_NOT_PUBLICATION_TIMESTAMP",
            "excerpt": body[:1200],
            "lifecycle": "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "provenance": {
                "authority": "DSP_VALCEA_OFFICIAL",
                "retrieval_surface": SOURCE_URL,
                "temporal_basis": "EXPLICIT_VISIBLE_SOURCE_TEXT",
            },
        })
    return signals


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, str]:
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with urlopen(request, timeout=18, context=ssl.create_default_context()) as response:
        final_url = str(response.geturl())
        host = urlsplit(final_url).netloc.casefold()
        if host not in CURRENT_HOSTS:
            raise ValueError(f"DSP adapter refused redirect outside official host: {host or '<empty>'}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("DSP health source response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"DSP health source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(html_text: str, *, final_url: str, content_sha256: str) -> dict[str, Any]:
    signals = extract_signals(html_text, final_url=final_url)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR DSP Vâlcea health signals",
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "final_url": final_url,
        "source_content_sha256": content_sha256,
        "signal_count": len(signals),
        "signals": signals,
        "policy": {
            "publication_authority": "NONE",
            "signal_only": True,
            "public_projection": False,
            "auto_publication": False,
            "explicit_temporal_evidence_required": True,
            "event_period_is_not_publication_timestamp": True,
        },
    }


def self_test() -> int:
    sample = """
    <html><body>
      <h2>Campania națională „Respiră curat, alege sănătatea!”</h2>
      <p>Institutul derulează în perioada iulie – august 2026 campania națională.</p>
      <h2>Recomandări în caz de caniculă</h2>
      <p>Recomandări pentru prevenirea impactului temperaturilor crescute.</p>
      <h2>Ziua mondială fără tutun - 31.05.2026</h2>
      <p>Acțiuni pentru prevenirea consumului de tutun.</p>
      <h2>Campania de promovare a sănătății mintale</h2>
      <p>Comunicare pentru luna ianuarie 2026.</p>
      <h2>Raport administrativ 2026</h2>
      <p>Acesta nu este un semnal de campanie cu dată explicită suficientă.</p>
    </body></html>
    """
    signals = extract_signals(sample)
    assert len(signals) == 3
    by_precision = {row["temporal_precision"]: row for row in signals}
    assert by_precision["MONTH_RANGE"]["period_start"] == "2026-07-01"
    assert by_precision["MONTH_RANGE"]["period_end"] == "2026-08-31"
    assert by_precision["EXACT_DATE"]["period_start"] == "2026-05-31"
    assert by_precision["MONTH"]["period_start"] == "2026-01-01"
    assert all(row["publication_authority"] == "NONE" for row in signals)
    assert all(row["auto_publication"] is False for row in signals)
    assert extract_period("Recomandări pentru caniculă în anul 2026") is None
    assert html_response_ok("text/html; charset=utf-8", b"plain") is True
    assert html_response_ok("text/plain", b"<HTML><body>ok</body></HTML>") is True
    assert html_response_ok("text/plain", b"not html") is False
    assert len(extract_signals(sample, final_url="https://aspjvalcea.ro/documente-utile/promovarea-sanatatii.php")) == 3
    for rejected_url in (
        "https://example.com/health",
        "https://dspvalcea.ro/documente-utile/promovarea-sanatatii.php",
        "https://www.dspvalcea.ro/documente-utile/promovarea-sanatatii.php",
    ):
        try:
            extract_signals(sample, final_url=rejected_url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-domain or legacy final URL must fail closed: {rejected_url}")
    doc = build_document(sample, final_url=SOURCE_URL, content_sha256="abc")
    assert doc["policy"]["signal_only"] is True
    assert doc["policy"]["event_period_is_not_publication_timestamp"] is True
    print("VÂLCEA CLAR DSP health signal adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    html_text, final_url, body_sha = fetch_html()
    document = build_document(html_text, final_url=final_url, content_sha256=body_sha)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "source_id": SOURCE_ID,
        "signal_count": document["signal_count"],
        "publication_authority": "NONE",
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
