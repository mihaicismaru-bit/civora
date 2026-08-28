#!/usr/bin/env python3
"""Bounded live acquisition for exact official Interreg call pages.

This module deliberately probes a small set of exact, official call-detail resources
as negative controls. It captures current bytes, verifies call-specific markers,
hashes the response, and delegates semantic classification to INTERREG_CALL_V1.

The live acquisition is evidence-only. It cannot publish, mutate the opportunity
corpus, or authorize material facts. A stale page that still says OPEN after its
deadline is surfaced as REVIEW_REQUIRED rather than OPEN_CALL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import urllib.request
from typing import Any

from interreg_call import normalize_call_observation

SCHEMA = "PARTENER_EU_INTERREG_CALL_LIVE_EVIDENCE_V1"
USER_AGENT = "PARTENER.EU-Interreg-Call/1.0"
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 25

# Bounded exact-call controls. These are intentionally historical/expired calls.
# They prove that current readback plus deadline reconciliation cannot generate a
# false OPEN_CALL from stale official page copy.
CALL_PROBES: tuple[dict[str, Any], ...] = (
    {
        "probe_id": "DRP-THIRD-CALL-2025",
        "call_identifier": "Third call for proposals",
        "programme": "Danube Region Programme 2021-2027",
        "url": "https://interreg-danube.eu/calls-for-proposals/third-call-for-proposals",
        "title": "Third call for proposals",
        "deadline": "2025-12-15T14:00:00+01:00",
        "markers": ("Third call for proposals", "15 December 2025"),
    },
    {
        "probe_id": "ROBG-CALL-6-2025",
        "call_identifier": "Call 6",
        "programme": "Interreg VI-A Romania-Bulgaria 2021-2027",
        "url": "https://interregviarobg.eu/en/open-calls-for-proposals-call-6",
        "title": "Call 6",
        "deadline": "2025-12-22T13:00:00+02:00",
        "markers": ("Call 6", "22"),
    },
    {
        "probe_id": "ROUA-SECOND-SMALL-SCALE-2025",
        "call_identifier": "2nd call for small-scale projects",
        "programme": "Interreg NEXT Romania-Ukraine 2021-2027",
        "url": "https://ro-ua.net/en/comunication-2021-2027/noutati-2021-2027/1662-launching-of-the-second-call-for-small-scale-projects-within-the-interreg-next-vi-a-romania-ukraine-programme-2021-2027",
        "title": "Second call for small-scale projects",
        "deadline": "2025-07-28T14:00:00+03:00",
        "markers": ("second call", "28 July 2025"),
    },
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0:
            clean = re.sub(r"\s+", " ", data).strip()
            if clean:
                self.parts.append(clean)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _visible_text(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    decoded = raw.decode(charset, errors="replace")
    parser = _VisibleText()
    parser.feed(decoded)
    return html.unescape(" ".join(parser.parts))


def _fetch(url: str) -> tuple[bytes, str, int, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=context) as response:
        final_url = response.geturl()
        status = int(response.getcode() or 0)
        content_type = str(response.headers.get("Content-Type") or "")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"response exceeds {MAX_BYTES} bytes")
    if status != 200:
        raise ValueError(f"unexpected HTTP status {status}")
    if "html" not in content_type.lower():
        raise ValueError(f"unexpected content type {content_type!r}")
    return raw, final_url, status, content_type


def _declared_status(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(call|applications?|submission)[^.]{0,100}\bclosed\b", lowered) or "closed calls" in lowered:
        return "CLOSED"
    if re.search(r"\bopen\s+until\b", lowered) or re.search(r"\bcall\s+(?:is|was)\s+open\b", lowered):
        return "OPEN"
    if re.search(r"\blaunch(?:ing|ed)?\b[^.]{0,100}\bcall\b", lowered):
        return "OPEN"
    if "pre-announcement" in lowered or "preannouncement" in lowered:
        return "FORTHCOMING"
    return "UNRESOLVED"


def _markers_verified(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return all(str(marker).casefold() in lowered for marker in markers)


def build_live_evidence(*, run_id: str | None = None) -> dict[str, Any]:
    observed_at = _utc_now()
    run = run_id or f"INTERREG-CALL-{observed_at.replace(':', '').replace('-', '')}"
    rows: list[dict[str, Any]] = []

    for probe in CALL_PROBES:
        row: dict[str, Any] = {
            "probe_id": probe["probe_id"],
            "call_identifier": probe["call_identifier"],
            "programme": probe["programme"],
            "registered_url": probe["url"],
            "fetched_at": observed_at,
            "run_id": run,
            "publication_effect": "NONE",
            "publish_authorized": False,
            "material_fact_use": False,
            "canonical_corpus_mutation": False,
        }
        try:
            raw, final_url, status, content_type = _fetch(str(probe["url"]))
            text = _visible_text(raw, content_type)
            if len(text) < 120:
                raise ValueError("low-information HTML body")
            readback_verified = _markers_verified(text, tuple(probe["markers"]))
            raw_hash = _sha256(raw)
            normalized = normalize_call_observation(
                {
                    "call_identifier": probe["call_identifier"],
                    "programme": probe["programme"],
                    "authority_url": final_url,
                    "title": probe["title"],
                    "official_status": _declared_status(text),
                    "deadline": probe["deadline"],
                    "readback_verified": readback_verified,
                },
                fetched_at=observed_at,
                raw_hash=raw_hash,
                run_id=run,
            )
            row.update(
                {
                    "fetch_status": "PASS",
                    "http_status": status,
                    "content_type": content_type,
                    "final_url": final_url,
                    "bytes": len(raw),
                    "raw_hash": raw_hash,
                    "readback_verified": readback_verified,
                    "declared_status_from_visible_text": _declared_status(text),
                    "normalized": normalized,
                }
            )
        except Exception as exc:
            row.update(
                {
                    "fetch_status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        rows.append(row)

    states: dict[str, int] = {}
    for row in rows:
        normalized = row.get("normalized") or {}
        state = str(normalized.get("observation_state") or "FETCH_FAILED")
        states[state] = states.get(state, 0) + 1

    return {
        "schema": SCHEMA,
        "created_at": observed_at,
        "run_id": run,
        "probe_count": len(rows),
        "fetch_pass": sum(1 for row in rows if row.get("fetch_status") == "PASS"),
        "fetch_fail": sum(1 for row in rows if row.get("fetch_status") == "FAIL"),
        "observation_states": states,
        "source_family": "INTERREG",
        "authority_class": "OFFICIAL_INTERREG_PROGRAMME_AUTHORITY",
        "parser_version": "INTERREG_CALL_LIVE_FETCH_V1",
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "rows": rows,
    }


def validate_envelope(data: dict[str, Any]) -> None:
    if data.get("schema") != SCHEMA:
        raise ValueError("unexpected exact-call live-evidence schema")
    if data.get("publication_effect") != "NONE":
        raise ValueError("exact-call live evidence must have publication_effect=NONE")
    if data.get("canonical_corpus_mutation") is not False or data.get("publish_authorized") is not False:
        raise ValueError("exact-call live evidence cannot authorize corpus/publication mutation")
    for row in data.get("rows", []):
        if row.get("publish_authorized") is not False or row.get("material_fact_use") is not False:
            raise ValueError(f"unsafe exact-call row {row.get('probe_id')}")
        normalized = row.get("normalized")
        if not normalized:
            continue
        if normalized.get("publish_authorized") is not False or normalized.get("material_fact_use") is not False:
            raise ValueError(f"normalizer became authorizing for {row.get('probe_id')}")
        if normalized.get("observation_state") == "OPEN_CALL":
            raise ValueError(f"historical control unexpectedly classified OPEN_CALL: {row.get('probe_id')}")
        if normalized.get("raw_hash") != row.get("raw_hash"):
            raise ValueError(f"raw hash detached from normalized receipt: {row.get('probe_id')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()

    evidence = build_live_evidence(run_id=args.run_id)
    validate_envelope(evidence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "probe_count": evidence["probe_count"],
                "fetch_pass": evidence["fetch_pass"],
                "fetch_fail": evidence["fetch_fail"],
                "observation_states": evidence["observation_states"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
