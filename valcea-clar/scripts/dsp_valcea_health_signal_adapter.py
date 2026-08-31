#!/usr/bin/env python3
"""Evidence-first DSP Vâlcea public-health signal adapter.

The adapter reads only the official "Promovarea sănătății" HTML surface.
It extracts section-level public-health signals and provenance metadata.
It deliberately does not parse linked document bodies, infer live health
conditions, extract person-level data, or grant publication/media rights.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SOURCE_ID = "signal-dsp-valcea-promovarea-sanatatii"
SOURCE_NAME = "Direcția de Sănătate Publică Vâlcea — Promovarea sănătății"
SOURCE_URL = "https://www.aspjvalcea.ro/documente-utile/promovarea-sanatatii.php"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_HEALTH_CAMPAIGNS"
CANONICAL_HOST = "www.aspjvalcea.ro"
ALLOWED_HOSTS = {"aspjvalcea.ro", "www.aspjvalcea.ro"}
CANONICAL_PATH = "/documente-utile/promovarea-sanatatii.php"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-DSP-Health-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 3_000_000

DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
PLACEHOLDER_TERMS = (
    "enable javascript", "access denied", "captcha", "robot",
    "temporarily unavailable", "service unavailable", "cloudflare",
)
HEALTH_HINTS = (
    "sanat", "sănăt", "canicul", "tutun", "nicotin", "alcool", "maternitat",
    "gravid", "anafil", "medicin", "preven", "campani", "respir", "aliment",
    "activitat fizic", "raport", "populatie", "populație",
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def official_surface_url(url: str) -> bool:
    parsed = urlsplit(clean_text(url))
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        return False
    if parsed.hostname.casefold() not in ALLOWED_HOSTS or parsed.username or parsed.password:
        return False
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    return path.rstrip("/") == CANONICAL_PATH and not parsed.query and not parsed.fragment


def normalize_official_url(value: str, *, base_url: str = SOURCE_URL) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    parsed = urlsplit(urljoin(base_url, text))
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        return None
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    return urlunsplit(("https", CANONICAL_HOST, path, parsed.query, ""))


class PromotionParser(html.parser.HTMLParser):
    """Capture h2/h3 sections plus official links/images attached to each section."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.heading_tag: str | None = None
        self.heading_parts: list[str] = []
        self.current: dict[str, Any] | None = None
        self.sections: list[dict[str, Any]] = []
        self.current_link: str | None = None
        self.link_parts: list[str] = []

    def _flush(self) -> None:
        if self.current is None:
            return
        self.current["text"] = clean_text(" ".join(self.current.pop("parts", [])))
        self.sections.append(self.current)
        self.current = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        attrs_d = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in {"h2", "h3"}:
            self._flush()
            self.heading_tag = tag
            self.heading_parts = []
            return
        if tag == "a" and self.current is not None:
            self.current_link = attrs_d.get("href") or ""
            self.link_parts = []
            return
        if tag == "img" and self.current is not None:
            src = normalize_official_url(attrs_d.get("src") or "")
            if src:
                self.current["media"].append({
                    "url": src,
                    "alt_text": clean_text(attrs_d.get("alt") or ""),
                    "rights_status": "UNVERIFIED",
                    "public_reuse_allowed": False,
                    "basis": "OFFICIAL_DSP_PAGE_IMAGE_REFERENCE",
                })

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in {"h2", "h3"} and self.heading_tag == tag:
            title = clean_text(" ".join(self.heading_parts))
            self.heading_tag = None
            self.heading_parts = []
            if title:
                self.current = {"title": title, "parts": [title], "links": [], "media": []}
            return
        if tag == "a" and self.current is not None and self.current_link is not None:
            url = normalize_official_url(self.current_link)
            text = clean_text(" ".join(self.link_parts))
            if url:
                self.current["links"].append({"url": url, "text": text})
            self.current_link = None
            self.link_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        if self.heading_tag is not None:
            self.heading_parts.append(text)
            return
        if self.current is not None:
            self.current["parts"].append(text)
            if self.current_link is not None:
                self.link_parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush()


def placeholder_response(html_text: str) -> bool:
    visible = fold(re.sub(r"<[^>]+>", " ", html_text))[:5000]
    return any(fold(term) in visible for term in PLACEHOLDER_TERMS)


def iso_date(day: str, month: str, year: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def extract_dates(text: str) -> tuple[list[str], str]:
    out: list[str] = []
    anomalous = False
    for match in DATE_RE.finditer(text):
        value = iso_date(match.group(1), match.group(2), match.group(3))
        if value is None:
            anomalous = True
        elif value not in out:
            out.append(value)
    if anomalous:
        return out[:4], "PARTIAL_ANOMALY" if out else "ANOMALOUS"
    return out[:4], "EXPLICIT_VISIBLE_TEXT" if out else "MISSING"


def explicit_years(text: str) -> list[int]:
    years: list[int] = []
    for match in YEAR_RE.finditer(text):
        value = int(match.group(1))
        if value not in years:
            years.append(value)
    return years[:4]


def classify(title: str, text: str, *, date_status: str) -> str:
    value = fold(f"{title} {text}")
    if date_status in {"ANOMALOUS", "PARTIAL_ANOMALY"}:
        return "HOLD"
    if "canicul" in value or "temperatur" in value:
        return "PUBLIC_HEALTH_ADVISORY"
    if "maternitat" in value:
        return "HEALTH_SERVICE_REFERENCE"
    if "raport privind starea de sanatate" in value:
        return "PUBLIC_HEALTH_REPORT"
    if "anafil" in value or "medicina scolara" in value:
        return "SCHOOL_HEALTH_GUIDANCE"
    if any(token in value for token in ("campani", "preven", "tutun", "nicotin", "alcool", "alimentatie", "activitate fizica")):
        return "PUBLIC_HEALTH_CAMPAIGN"
    return "HOLD"


def evidence_id(*, title: str, links: list[dict[str, str]]) -> str:
    urls = sorted(link["url"] for link in links)
    basis = "\0".join([SOURCE_ID, fold(title), *urls])
    return "dsp-health-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def extract_signals(html_text: str, *, final_url: str = SOURCE_URL) -> list[dict[str, Any]]:
    if not official_surface_url(final_url):
        raise ValueError(f"DSP adapter refused unexpected source URL: {final_url}")
    if placeholder_response(html_text):
        raise ValueError("DSP source returned a placeholder/challenge response")

    parser = PromotionParser()
    parser.feed(html_text)
    parser.close()

    rows: dict[str, dict[str, Any]] = {}
    folded_hints = tuple(fold(item) for item in HEALTH_HINTS)
    for section in parser.sections:
        title = clean_text(section["title"])
        text = clean_text(section["text"])
        if len(title) < 5:
            continue
        folded_text = fold(f"{title} {text}")
        if not any(hint in folded_text for hint in folded_hints):
            continue
        dates, date_status = extract_dates(f"{title} {text}")
        signal_class = classify(title, text, date_status=date_status)
        sid = evidence_id(title=title, links=section["links"])
        rows[sid] = {
            "signal_id": sid,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "final_url": final_url,
            "source_tier": SOURCE_TIER,
            "source_kind": SOURCE_KIND,
            "title": title,
            "signal_class": signal_class,
            "effective_dates": dates,
            "effective_date_status": date_status,
            "explicit_years": explicit_years(f"{title} {text}"),
            "summary_excerpt": text[:800],
            "official_links": section["links"][:12],
            "media_candidates": section["media"][:8],
            "linked_document_body_ingest_allowed": False,
            "person_level_data_extraction_allowed": False,
            "medical_diagnosis_or_treatment_inference_allowed": False,
            "current_health_status_claim_allowed": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "media_public_reuse_allowed": False,
            "lifecycle": (
                "SIGNAL_ONLY_SOURCE_RECHECK_REQUIRED"
                if signal_class != "HOLD"
                else "HOLD_CLASSIFICATION_OR_DATE_ANOMALY"
            ),
            "provenance": {
                "authority": "DSP_VALCEA_OFFICIAL_PUBLIC_HEALTH_SURFACE",
                "retrieval_surface": SOURCE_URL,
                "metadata_basis": "VISIBLE_OFFICIAL_HTML_SECTION",
                "linked_document_basis": "OFFICIAL_LINK_DISCOVERED_BODY_NOT_FETCHED",
                "media_basis": "OFFICIAL_PAGE_REFERENCE_RIGHTS_UNVERIFIED",
            },
        }

    return sorted(rows.values(), key=lambda row: (row["signal_class"] == "HOLD", row["title"].casefold()))


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, str]:
    if not official_surface_url(url):
        raise ValueError("DSP fetch is restricted to the canonical health-promotion surface")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
        final_url = str(response.geturl())
        if not official_surface_url(final_url):
            raise ValueError(f"DSP adapter refused redirect outside canonical source surface: {final_url}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("DSP source response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"DSP source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(html_text: str, *, final_url: str, content_sha256: str) -> dict[str, Any]:
    signals = extract_signals(html_text, final_url=final_url)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR DSP public-health signals",
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
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "current_health_status_claim_allowed": False,
            "medical_diagnosis_or_treatment_inference_allowed": False,
            "person_level_data_extraction_allowed": False,
            "linked_document_body_ingest_allowed": False,
            "media_public_reuse_allowed": False,
            "source_recheck_required": True,
        },
    }


def self_test() -> int:
    sample = """
    <html><body>
      <h2>Recomandări în caz de caniculă</h2>
      <img src="/media/canicula.jpg" alt="recomandari canicula">
      <p>Recomandări pentru prevenirea impactului negativ al temperaturilor crescute asupra stării de sănătate.</p>
      <a href="/documente-utile/canicula.php">Citește mai mult</a>

      <h2>Campania națională „Respiră curat, alege sănătatea!”</h2>
      <p>Institutul Național de Sănătate Publică derulează în perioada iulie – august 2026 campania de prevenire.</p>
      <a href="https://www.aspjvalcea.ro/documente-utile/tutun.php">Citește mai mult</a>
      <img src="https://evil.example/generic.jpg" alt="generic">

      <h3>Ziua mondială fără tutun - 31.05.2026</h3>
      <p>Campanie de prevenție.</p>

      <h3>Raport privind starea de sănătate a populației județului Vâlcea pe anul 2025</h3>
      <a href="/documente/raport-2025.pdf">Raport 2025</a>

      <h3>Material invalid - 31.02.2026</h3>
      <p>Campanie de sănătate.</p>
    </body></html>
    """
    signals = extract_signals(sample)
    by_title = {row["title"]: row for row in signals}
    heat = by_title["Recomandări în caz de caniculă"]
    assert heat["signal_class"] == "PUBLIC_HEALTH_ADVISORY"
    assert heat["effective_date_status"] == "MISSING"
    assert heat["current_health_status_claim_allowed"] is False
    assert heat["media_candidates"][0]["public_reuse_allowed"] is False

    campaign = by_title["Campania națională „Respiră curat, alege sănătatea!”"]
    assert campaign["signal_class"] == "PUBLIC_HEALTH_CAMPAIGN"
    assert campaign["explicit_years"] == [2026]
    assert all("evil.example" not in item["url"] for item in campaign["media_candidates"])
    assert campaign["official_links"][0]["url"].startswith("https://www.aspjvalcea.ro/")

    tobacco = by_title["Ziua mondială fără tutun - 31.05.2026"]
    assert tobacco["effective_dates"] == ["2026-05-31"]

    report = by_title["Raport privind starea de sănătate a populației județului Vâlcea pe anul 2025"]
    assert report["signal_class"] == "PUBLIC_HEALTH_REPORT"
    assert report["linked_document_body_ingest_allowed"] is False

    invalid = by_title["Material invalid - 31.02.2026"]
    assert invalid["signal_class"] == "HOLD"
    assert invalid["effective_date_status"] == "ANOMALOUS"

    assert normalize_official_url("https://evil.example/file.pdf") is None
    assert official_surface_url("https://www.aspjvalcea.ro/documente-utile/promovarea-sanatatii.php")
    assert official_surface_url("https://aspjvalcea.ro/documente-utile/promovarea-sanatatii.php")
    assert not official_surface_url("https://dspvalcea.ro/documente-utile/promovarea-sanatatii.php")
    assert not official_surface_url("https://www.aspjvalcea.ro/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.live:
        parser.error("choose --self-test or --live")

    html_text, final_url, digest = fetch_html()
    print(json.dumps(build_document(html_text, final_url=final_url, content_sha256=digest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())