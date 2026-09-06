#!/usr/bin/env python3
"""Bounded live probe for the official Interreg NEXT Black Sea Basin call index.

This probe is acquisition-only and non-authorizing. It exists to prove runner
transport/marker health before the BSB call index is admitted to the canonical
Romania-relevant Interreg call-surface watch. Historic OPEN/CLOSED labels on the
index are intentionally not parsed into call facts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

SCHEMA = "PARTENER_EU_INTERREG_BSB_CALL_INDEX_PROBE_V1"
PARSER_VERSION = "INTERREG_BSB_CALL_INDEX_PROBE_V1"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_NEXT_BLACK_SEA_BASIN_2021_2027"
AUTHORITY_CLASS = "INTERREG_OFFICIAL_PROGRAMME_CALL_INDEX"
AUTHORITY_URL = "https://blacksea-cbc.net/interreg-next-bsb-2021-2027/calls-for-proposals"
ALLOWED_HOSTS = {"blacksea-cbc.net", "www.blacksea-cbc.net"}
ANCHORS = (
    "Calls for proposals",
    "Interreg NEXT Black Sea Basin Programme",
    "First Calls for Proposals",
    "Second Calls for Proposals",
)
OBSERVATION_STATE = "CALL_DISCOVERY_ONLY"

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normal(value: str) -> str:
    text = html.unescape(value).casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


class TextProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed = max(0, self.suppressed - 1)

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def html_text(raw: bytes) -> str:
    p = TextProbe()
    p.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(p.parts)


def classify_failure(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".casefold()
    if isinstance(exc, ssl.SSLCertVerificationError) or "certificate verify failed" in text:
        return "TLS_CERTIFICATE_VERIFY_FAILED"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP_{exc.code}"
    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"
    if "name or service not known" in text or "temporary failure in name resolution" in text or "getaddrinfo" in text:
        return "DNS_FAILURE"
    if isinstance(exc, ValueError):
        return "VALIDATION_ERROR"
    return "TRANSPORT_ERROR"


def fetch() -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(
        AUTHORITY_URL,
        headers={
            "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("official BSB call index exceeds 5 MB")
        meta = {
            "requested_url": AUTHORITY_URL,
            "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if meta["status"] != 200:
        raise ValueError(f"official BSB call index returned HTTP {meta['status']}")
    host = (urllib.parse.urlparse(meta["final_url"]).hostname or "").casefold()
    if host not in ALLOWED_HOSTS:
        raise ValueError("BSB call index escaped programme authority")
    text = html_text(raw)
    hay = normal(text)
    missing = [x for x in ANCHORS if normal(x) not in hay]
    if missing:
        raise ValueError(f"BSB call index missing required provenance anchors: {missing}")
    return raw, meta


def semantic_fingerprint(receipt: dict[str, Any]) -> str | None:
    if receipt["source_health"] != "HEALTHY":
        return None
    payload = {
        "programme_family": receipt["programme_family"],
        "authority_url": receipt["authority_url"],
        "authority_class": receipt["authority_class"],
        "observation_state": receipt["observation_state"],
        "final_url": receipt["final_url"],
        "source_sha256": receipt["source_sha256"],
        "normalized_visible_text_sha256": receipt["normalized_visible_text_sha256"],
        "market_intelligence_only": True,
        "discovered_call_facts": [],
    }
    return sha256_bytes(canonical_json(payload))


def validate(receipt: dict[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("BSB probe schema/parser drift")
    if receipt.get("authority_url") != AUTHORITY_URL or receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("BSB probe authority/observation drift")
    if receipt.get("market_intelligence_only") is not True or receipt.get("discovered_call_facts") != []:
        raise ValueError("BSB probe attempted to emit call facts")
    if any(receipt.get(flag) is not False for flag in MATERIAL_FLAGS):
        raise ValueError("BSB probe attempted material authorization")
    if receipt.get("source_health") == "HEALTHY":
        if receipt.get("status") != 200:
            raise ValueError("healthy BSB probe without HTTP 200")
        host = (urllib.parse.urlparse(str(receipt.get("final_url") or "")).hostname or "").casefold()
        if host not in ALLOWED_HOSTS:
            raise ValueError("healthy BSB probe escaped programme authority")
        if not receipt.get("source_sha256") or not receipt.get("normalized_visible_text_sha256"):
            raise ValueError("healthy BSB probe missing content hashes")
        expected = semantic_fingerprint(receipt)
        if receipt.get("semantic_fingerprint") != expected:
            raise ValueError("BSB semantic fingerprint mismatch")
    else:
        forbidden = ("source_sha256", "normalized_visible_text_sha256", "semantic_fingerprint")
        if any(receipt.get(x) is not None for x in forbidden):
            raise ValueError("degraded BSB probe retained partial semantic evidence")
        if receipt.get("current_material_truth_available") is not False or receipt.get("lkg_required") is not True:
            raise ValueError("degraded BSB probe did not fail closed")


def build(run_id: str) -> tuple[dict[str, Any], bytes | None]:
    observed = utc_now()
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "authority_url": AUTHORITY_URL,
        "observation_state": OBSERVATION_STATE,
        "run_id": run_id,
        "fetched_at": observed,
        "market_intelligence_only": True,
        "discovered_call_facts": [],
        "current_material_truth_available": False,
        "lkg_required": False,
        "publication_effect": "NONE",
        **{flag: False for flag in MATERIAL_FLAGS},
    }
    try:
        raw, meta = fetch()
        text = html_text(raw)
        receipt = {
            **base,
            "source_health": "HEALTHY",
            "requested_url": meta["requested_url"],
            "final_url": meta["final_url"],
            "status": meta["status"],
            "content_type": meta["content_type"],
            "source_sha256": sha256_bytes(raw),
            "normalized_visible_text_sha256": sha256_bytes(normal(text).encode()),
            "failure_class": None,
            "error_type": None,
            "error": None,
        }
        receipt["semantic_fingerprint"] = semantic_fingerprint(receipt)
        validate(receipt)
        return receipt, raw
    except Exception as exc:
        receipt = {
            **base,
            "source_health": "DEGRADED",
            "requested_url": AUTHORITY_URL,
            "final_url": None,
            "status": getattr(exc, "code", None),
            "content_type": None,
            "source_sha256": None,
            "normalized_visible_text_sha256": None,
            "semantic_fingerprint": None,
            "failure_class": classify_failure(exc),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "lkg_required": True,
        }
        validate(receipt)
        return receipt, None


def self_test() -> None:
    healthy = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "authority_url": AUTHORITY_URL,
        "observation_state": OBSERVATION_STATE,
        "run_id": "synthetic",
        "fetched_at": "2026-09-06T00:00:00+00:00",
        "market_intelligence_only": True,
        "discovered_call_facts": [],
        "current_material_truth_available": False,
        "lkg_required": False,
        "publication_effect": "NONE",
        "source_health": "HEALTHY",
        "requested_url": AUTHORITY_URL,
        "final_url": AUTHORITY_URL,
        "status": 200,
        "content_type": "text/html",
        "source_sha256": "1" * 64,
        "normalized_visible_text_sha256": "2" * 64,
        "failure_class": None,
        "error_type": None,
        "error": None,
        **{flag: False for flag in MATERIAL_FLAGS},
    }
    healthy["semantic_fingerprint"] = semantic_fingerprint(healthy)
    validate(healthy)
    tampered = dict(healthy)
    tampered["open_call_authorized"] = True
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("authorization widening was not rejected")
    degraded = dict(healthy)
    degraded.update(
        source_health="DEGRADED",
        final_url=None,
        status=None,
        content_type=None,
        source_sha256=None,
        normalized_visible_text_sha256=None,
        semantic_fingerprint=None,
        failure_class="TLS_CERTIFICATE_VERIFY_FAILED",
        error_type="OSError",
        error="synthetic certificate verify failed",
        lkg_required=True,
    )
    validate(degraded)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="artifacts/partener-eu/interreg-bsb-call-index-proof")
    ap.add_argument("--run-id", default="local")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        print("Interreg BSB call-index fail-closed regression: PASS")
        return 0
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    receipt, raw = build(args.run_id)
    (out / "bsb-call-index-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    if raw is not None:
        (out / "bsb-call-index.html").write_bytes(raw)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
