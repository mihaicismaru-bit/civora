#!/usr/bin/env python3
"""Official CERV programme-fit and programming watch for PARTENER.EU.

This adapter is deliberately non-authorizing. It verifies official European
Commission programme and Romanian NCP pages, records immutable provenance, and
exposes programme-fit / programming intelligence only. It cannot create an
OPEN_CALL observation or authorize deadline, budget, eligibility, publication,
distribution, or alerts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable, Mapping

SCHEMA = "PARTENER_EU_CERV_PROGRAMME_WATCH_V1"
PARSER_VERSION = "EU_DIRECT_CERV_PROGRAMME_WATCH_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "CERV"
AUTHORITY_CLASS = "EU_COMMISSION_PROGRAMME_AUTHORITY"
OBSERVATION_STATE = "PROGRAMME_FIT_AND_PROGRAMMING_WATCH_NON_AUTHORIZING"

PROGRAMME_OVERVIEW_URL = (
    "https://commission.europa.eu/funding-and-tenders/find-funding/eu-funding-programmes/"
    "citizens-equality-rights-and-values-programme/"
    "citizens-equality-rights-and-values-programme-overview_en"
)
NCP_URL = (
    "https://commission.europa.eu/funding-and-tenders/find-funding/eu-funding-programmes/"
    "citizens-equality-rights-and-values-programme/"
    "citizens-equality-rights-and-values-programme-overview/"
    "cerv-national-contact-points_en"
)

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
)
ALLOWED_PROGRAMMING_STATES = {"PROGRAMMING", "PLANNED", "CONSULTATION", "PROPOSAL"}
REQUIRED_OVERVIEW_ANCHORS = (
    "citizens, equality, rights and values",
    "civil society organisations",
    "funding and tenders portal",
    "cerv indicative planning 2026",
    "cerv work programme 2026-2027",
)
REQUIRED_NCP_ANCHORS = (
    "romania",
    "ministry of culture of romania",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


class _HTMLProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self._anchor_label_hint: str | None = None
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.casefold()
        if low in {"script", "style", "noscript"}:
            self._suppressed += 1
            return
        if low == "a" and not self._suppressed:
            attr_map = dict(attrs)
            self._href = attr_map.get("href")
            self._anchor_label_hint = (
                attr_map.get("data-untranslated-label")
                or attr_map.get("aria-label")
                or attr_map.get("title")
            )
            self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        low = tag.casefold()
        if low in {"script", "style", "noscript"}:
            self._suppressed = max(0, self._suppressed - 1)
            return
        if low == "a" and not self._suppressed:
            label = (self._anchor_label_hint or " ".join(self._anchor_parts)).strip()
            if self._href and label:
                self.links.append({"text": label, "href": self._href})
            self._href = None
            self._anchor_parts = []
            self._anchor_label_hint = None

    def handle_data(self, data: str) -> None:
        if self._suppressed:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.text_parts.append(cleaned)
        if self._href is not None:
            self._anchor_parts.append(cleaned)


def parse_html(raw: bytes, *, base_url: str) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    parser = _HTMLProbe()
    parser.feed(text)
    visible = " ".join(parser.text_parts)
    normalized = re.sub(r"\s+", " ", html.unescape(visible)).strip()
    links = [
        {
            "text": re.sub(r"\s+", " ", item["text"]).strip(),
            "url": urllib.parse.urljoin(base_url, item["href"]),
        }
        for item in parser.links
    ]
    return {"text": normalized, "links": links}


def default_fetch(url: str, *, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError(f"official CERV response exceeds bounded 4 MB limit: {url}")
        status = int(getattr(response, "status", 200) or 200)
        final_url = str(response.geturl())
        content_type = str(response.headers.get("Content-Type") or "")
    if status != 200:
        raise ValueError(f"official CERV source returned HTTP {status}: {url}")
    return raw, {
        "requested_url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
    }


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _require_anchors(text: str, anchors: tuple[str, ...], *, source: str) -> None:
    normalized = _normal(text)
    missing = [anchor for anchor in anchors if _normal(anchor) not in normalized]
    if missing:
        raise ValueError(f"{source} missing required official semantic anchors: {missing}")


def _find_document_link(links: list[dict[str, str]], needle: str) -> str | None:
    token = _normal(needle)
    candidates = [
        item["url"]
        for item in links
        if token in _normal(item.get("text") or "")
        and str(item.get("url") or "").startswith(
            ("https://commission.europa.eu/", "https://ec.europa.eu/")
        )
    ]
    return sorted(set(candidates))[0] if candidates else None


def build_receipt(
    *,
    overview_raw: bytes,
    overview_meta: Mapping[str, Any],
    ncp_raw: bytes,
    ncp_meta: Mapping[str, Any],
    fetched_at: str,
    run_id: str,
) -> dict[str, Any]:
    overview = parse_html(overview_raw, base_url=PROGRAMME_OVERVIEW_URL)
    ncp = parse_html(ncp_raw, base_url=NCP_URL)
    _require_anchors(overview["text"], REQUIRED_OVERVIEW_ANCHORS, source="CERV overview")
    _require_anchors(ncp["text"], REQUIRED_NCP_ANCHORS, source="CERV NCP page")

    indicative_url = _find_document_link(overview["links"], "CERV Indicative Planning 2026")
    work_programme_url = _find_document_link(overview["links"], "CERV Work Programme 2026-2027")

    fit_facts = {
        "fit_state": "ROMANIA_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING",
        "programme_scope_evidence": (
            "Official Commission overview states that CERV supports civil society organisations "
            "active at local, regional, national and transnational level."
        ),
        "romania_presence_evidence": (
            "Official Commission CERV National Contact Points page lists Romania and the "
            "Ministry of Culture of Romania."
        ),
        "programme_period": "2021-2027",
    }
    programming = [
        {
            "title": "CERV Indicative Planning 2026",
            "document_kind": "INDICATIVE_PLANNING",
            "observation_state": "PLANNED",
            "source_url": indicative_url or PROGRAMME_OVERVIEW_URL,
            "authority_class": AUTHORITY_CLASS,
            "observed_at": fetched_at,
            "open_call_authorized": False,
            "material_fact_use": False,
        },
        {
            "title": "CERV Work Programme 2026-2027",
            "document_kind": "WORK_PROGRAMME",
            "observation_state": "PROGRAMMING",
            "source_url": work_programme_url or PROGRAMME_OVERVIEW_URL,
            "authority_class": AUTHORITY_CLASS,
            "observed_at": fetched_at,
            "open_call_authorized": False,
            "material_fact_use": False,
        },
    ]
    fit_evidence = {
        "observation_state": "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING",
        "authority_class": AUTHORITY_CLASS,
        "overview_url": PROGRAMME_OVERVIEW_URL,
        "romania_ncp_url": NCP_URL,
        "facts": fit_facts,
        "semantic_fingerprint": sha256_json(fit_facts),
        "eligibility_fact_authorized": False,
        "call_fact_authorized": False,
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "sources": [
            {
                **dict(overview_meta),
                "role": "PROGRAMME_OVERVIEW_AND_PROGRAMMING",
                "sha256": sha256_bytes(overview_raw),
            },
            {
                **dict(ncp_meta),
                "role": "ROMANIA_NATIONAL_CONTACT_POINT",
                "sha256": sha256_bytes(ncp_raw),
            },
        ],
        "programme_fit_evidence": fit_evidence,
        "programming_observations": programming,
        "source_health": "HEALTHY",
        "market_intelligence_only": True,
        "missing_for_open_call_confirmation": [
            "current call/topic identifier",
            "current official Funding & Tenders topic endpoint",
            "exact current semantic reconciliation",
            "field-scoped material admission",
        ],
        "publication_effect": "NONE",
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False
    receipt["semantic_fingerprint"] = sha256_json(
        {
            "programme_fit_evidence": fit_evidence,
            "programming_observations": programming,
            "source_hashes": [row["sha256"] for row in receipt["sources"]],
        }
    )
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("CERV programme watch schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("CERV programme watch family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("CERV programme watch authority drift")
    if receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("CERV programme watch observation state drift")
    if receipt.get("source_health") != "HEALTHY" or receipt.get("market_intelligence_only") is not True:
        raise ValueError("CERV programme watch is not healthy market intelligence")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("CERV programme watch attempted publication effect")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"CERV programme watch attempted authorization: {key}")

    sources = receipt.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("CERV programme watch requires exactly two official sources")
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError("CERV source receipt malformed")
        final_url = str(source.get("final_url") or source.get("requested_url") or "")
        if not final_url.startswith("https://commission.europa.eu/"):
            raise ValueError(f"CERV source left Commission authority: {final_url}")
        digest = str(source.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("CERV source receipt lacks sha256")
        if int(source.get("status") or 0) != 200:
            raise ValueError("CERV source receipt is not HTTP 200")

    fit = receipt.get("programme_fit_evidence")
    if not isinstance(fit, Mapping):
        raise ValueError("CERV programme fit evidence missing")
    if fit.get("observation_state") != "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING":
        raise ValueError("CERV programme fit state drift")
    if fit.get("eligibility_fact_authorized") is not False or fit.get("call_fact_authorized") is not False:
        raise ValueError("CERV programme fit attempted call/eligibility authorization")
    if fit.get("semantic_fingerprint") != sha256_json(fit.get("facts") or {}):
        raise ValueError("CERV programme fit semantic fingerprint mismatch")

    programming = receipt.get("programming_observations")
    if not isinstance(programming, list) or len(programming) < 2:
        raise ValueError("CERV programming observations missing")
    for item in programming:
        if not isinstance(item, Mapping):
            raise ValueError("CERV programming observation malformed")
        state = str(item.get("observation_state") or "")
        if state not in ALLOWED_PROGRAMMING_STATES:
            raise ValueError(f"CERV programming state may not authorize calls: {state}")
        if item.get("open_call_authorized") is not False or item.get("material_fact_use") is not False:
            raise ValueError("CERV programming observation crossed non-authorizing boundary")
        source_url = str(item.get("source_url") or "")
        if not source_url.startswith(("https://commission.europa.eu/", "https://ec.europa.eu/")):
            raise ValueError("CERV programming observation lacks official source URL")

    expected = sha256_json(
        {
            "programme_fit_evidence": fit,
            "programming_observations": programming,
            "source_hashes": [row["sha256"] for row in sources],
        }
    )
    if receipt.get("semantic_fingerprint") != expected:
        raise ValueError("CERV programme watch semantic fingerprint mismatch")


def collect(
    *,
    run_id: str,
    fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, Mapping[str, Any]]] | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    fetched_at = fetched_at or utc_now()
    fetcher = fetcher or default_fetch
    overview_raw, overview_meta = fetcher(PROGRAMME_OVERVIEW_URL)
    ncp_raw, ncp_meta = fetcher(NCP_URL)
    receipt = build_receipt(
        overview_raw=overview_raw,
        overview_meta=overview_meta,
        ncp_raw=ncp_raw,
        ncp_meta=ncp_meta,
        fetched_at=fetched_at,
        run_id=run_id,
    )
    return receipt, {
        "cerv-programme-overview.html": overview_raw,
        "cerv-national-contact-points.html": ncp_raw,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    receipt, raw_files = collect(run_id=args.run_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, raw in raw_files.items():
        (args.output_dir / name).write_bytes(raw)
    output = args.output_dir / "cerv-programme-watch.json"
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": receipt["schema"],
                "programme_family": receipt["programme_family"],
                "source_health": receipt["source_health"],
                "programme_fit_state": receipt["programme_fit_evidence"]["facts"]["fit_state"],
                "programming_states": [
                    row["observation_state"] for row in receipt["programming_observations"]
                ],
                "open_call_authorized": receipt["open_call_authorized"],
                "publication_effect": receipt["publication_effect"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
