#!/usr/bin/env python3
"""Official EEA/Norway Grants Romania 2021-2028 programming intelligence.

This adapter reads the Financial Mechanism Office's current Romania programme map.
It is deliberately *not* a call adapter: programme grants, programme operators and
partner organisations are market/programming intelligence only. They can seed
operator watches and applicant-fit research, but can never authorize OPEN_CALL,
call deadlines, call budgets or applicant eligibility.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import ssl
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

SOURCE_URL = "https://eeagrants.org/en/fmo/news/renewed-cooperation-romania"
SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA and Norway Grants Romania 2021-2028"
AUTHORITY_CLASS = "EEA_FMO_ROMANIA_PROGRAMME_MAP"
PARSER_VERSION = "EEA_ROMANIA_PROGRAMMING_INTELLIGENCE_V1"
OFFICIAL_HOSTS = {"eeagrants.org", "www.eeagrants.org"}
EXPECTED_PATH = "/en/fmo/news/renewed-cooperation-romania"
MAX_BYTES = 4_000_000
USER_AGENT = "PARTENER.EU source-intelligence/1.0 (+https://partener.eu)"

EXPECTED_PROGRAMMES = (
    "Green Transition",
    "Clean Energy Transition",
    "Local Development",
    "Research and Innovation",
    "Green Business and Innovation",
    "Culture",
    "Justice",
    "Home Affairs",
    "Institutional Cooperation and Capacity Building",
)

MISSING_TO_CONFIRM_CALL = (
    "exact_call_identifier",
    "official_current_open_status",
    "exact_official_call_endpoint",
    "semantic_reconciliation",
)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _official_source_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        raise ValueError(f"non-official EEA/FMO URL: {value}")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError(f"unexpected authority components in URL: {value}")
    if parsed.path.rstrip("/") != EXPECTED_PATH:
        raise ValueError(f"unexpected Romania programme-map path: {value}")
    return urlunparse(("https", host, EXPECTED_PATH, "", "", ""))


class _BlockParser(HTMLParser):
    BLOCKS = {"h2", "h3", "h4", "p", "li"}
    IGNORED = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str]] = []
        self._active_tag: str | None = None
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in self.IGNORED:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in self.BLOCKS:
            self._active_tag = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth or not self._active_tag:
            return
        value = " ".join(data.split())
        if value:
            self._parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.IGNORED and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == self._active_tag:
            value = " ".join(self._parts).strip()
            if value:
                self.events.append((tag, value))
            self._active_tag = None
            self._parts = []


def fetch_url(url: str = SOURCE_URL, *, timeout: float = 20.0) -> dict[str, Any]:
    requested_url = _official_source_url(url)
    request = Request(
        requested_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        status = int(response.getcode() or 0)
        final_url = _official_source_url(response.geturl())
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {requested_url}")
    if len(raw) > MAX_BYTES:
        raise RuntimeError(f"response exceeds {MAX_BYTES} bytes for {requested_url}")
    if "text/html" not in content_type.lower() and "application/xhtml+xml" not in content_type.lower():
        raise RuntimeError(f"unexpected content type {content_type!r} for {requested_url}")
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "raw": raw,
    }


def _label_value(text: str, labels: tuple[str, ...]) -> str | None:
    lower = text.lower()
    for label in labels:
        marker = label.lower()
        if lower.startswith(marker):
            value = text[len(label):].lstrip(" :\u00a0").strip()
            return value or None
    return None


def parse_programme_map(raw: bytes) -> list[dict[str, Any]]:
    parser = _BlockParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()

    in_programmes = False
    current: dict[str, Any] | None = None
    sections: dict[str, dict[str, Any]] = {}

    for tag, text in parser.events:
        if tag == "h2":
            if "programmes 2021-2028" in text.lower():
                in_programmes = True
                current = None
                continue
            if in_programmes:
                break
        if not in_programmes:
            continue
        if tag == "h4":
            if text not in EXPECTED_PROGRAMMES:
                current = None
                continue
            if text in sections:
                raise RuntimeError(f"duplicate programme heading: {text}")
            current = {
                "programme_name": text,
                "programme_grant_evidence": None,
                "programme_operator": None,
                "donor_programme_partners": None,
                "international_partner_organisations": None,
            }
            sections[text] = current
            continue
        if not current or tag not in {"p", "li"}:
            continue

        value = _label_value(text, ("Programme grant",))
        if value is not None:
            current["programme_grant_evidence"] = value
            continue
        value = _label_value(text, ("Programme Operator",))
        if value is not None:
            current["programme_operator"] = value
            continue
        value = _label_value(text, ("Donor Programme Partner(s)", "Donor Programme Partners"))
        if value is not None:
            current["donor_programme_partners"] = value
            continue
        value = _label_value(text, ("International Partner Organisation(s)", "International Partner Organisations"))
        if value is not None:
            current["international_partner_organisations"] = value

    missing = [name for name in EXPECTED_PROGRAMMES if name not in sections]
    if missing:
        raise RuntimeError(f"official FMO programme map missing expected programmes: {missing}")
    extras = sorted(set(sections) - set(EXPECTED_PROGRAMMES))
    if extras:
        raise RuntimeError(f"unexpected programme headings: {extras}")

    rows: list[dict[str, Any]] = []
    for name in EXPECTED_PROGRAMMES:
        row = sections[name]
        if not row.get("programme_grant_evidence") or not row.get("programme_operator"):
            raise RuntimeError(f"incomplete FMO programme evidence for {name}: grant/operator required")
        rows.append(row)
    return rows


def normalize_programmes(
    programme_rows: list[dict[str, Any]],
    *,
    authority_url: str,
    fetched_at: str,
    raw_hash: str,
    run_id: str,
) -> list[dict[str, Any]]:
    authority_url = _official_source_url(authority_url)
    if len(programme_rows) != len(EXPECTED_PROGRAMMES):
        raise RuntimeError("programme batch is incomplete; fail closed")

    normalized: list[dict[str, Any]] = []
    for row in programme_rows:
        name = str(row.get("programme_name") or "").strip()
        if name not in EXPECTED_PROGRAMMES:
            raise RuntimeError(f"unknown programme in batch: {name!r}")
        semantic = {
            "programme_name": name,
            "programme_grant_evidence": row.get("programme_grant_evidence"),
            "programme_operator": row.get("programme_operator"),
            "donor_programme_partners": row.get("donor_programme_partners"),
            "international_partner_organisations": row.get("international_partner_organisations"),
        }
        normalized.append(
            {
                "schema": "PARTENER_EU_EEA_ROMANIA_PROGRAMMING_OBSERVATION_V1",
                "source_family": SOURCE_FAMILY,
                "programme_family": PROGRAMME_FAMILY,
                "authority_class": AUTHORITY_CLASS,
                "programme_name": name,
                "programme_operator": semantic["programme_operator"],
                "operator_watch_seed": semantic["programme_operator"],
                "programme_grant_evidence": semantic["programme_grant_evidence"],
                "programme_grant_scope": "PROGRAMME_ALLOCATION_NOT_CALL_BUDGET",
                "donor_programme_partners": semantic["donor_programme_partners"],
                "international_partner_organisations": semantic["international_partner_organisations"],
                "authority_url": authority_url,
                "fetched_at": fetched_at,
                "raw_hash": raw_hash,
                "semantic_fingerprint": _sha256(_canonical_json(semantic)),
                "parser_version": PARSER_VERSION,
                "run_id": run_id,
                "observation_state": "PROGRAMMING_PIPELINE",
                "not_a_call": True,
                "material_fact_use": False,
                "open_call_authorized": False,
                "publish_authorized": False,
                "canonical_corpus_mutation": False,
                "publication_effect": "NONE",
                "missing_to_confirm_call": list(MISSING_TO_CONFIRM_CALL),
            }
        )
    return normalized


def collect_live(*, run_id: str, fetched_at: str | None = None) -> dict[str, Any]:
    fetched_at = fetched_at or _utc_now()
    response = fetch_url(SOURCE_URL)
    raw = bytes(response["raw"])
    raw_hash = _sha256(raw)
    parsed = parse_programme_map(raw)
    records = normalize_programmes(
        parsed,
        authority_url=str(response["final_url"]),
        fetched_at=fetched_at,
        raw_hash=raw_hash,
        run_id=run_id,
    )
    return {
        "schema": "PARTENER_EU_EEA_ROMANIA_PROGRAMMING_EVIDENCE_V1",
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "source": {
            "url": str(response["final_url"]),
            "http_status": int(response["status"]),
            "content_type": str(response["content_type"]),
            "raw_hash": raw_hash,
            "bytes": len(raw),
        },
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "records": records,
        "stats": {
            "programme_records": len(records),
            "operator_watch_seeds": sum(1 for row in records if row.get("operator_watch_seed")),
            "open_calls_authorized": 0,
        },
        "observation_state": "PROGRAMMING_PIPELINE",
        "material_fact_use": False,
        "open_call_authorized": False,
        "publish_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    payload = collect_live(run_id=args.run_id)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
