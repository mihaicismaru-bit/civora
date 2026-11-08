#!/usr/bin/env python3
"""RCH 2027 secondary UEFISCDI news: immutable official discovery only.

The article is NOT MC-UMP's Romania Annex I and never expands eligibility,
proves authenticated EPSS submission, or authorizes an OPEN_CALL. Attach raw
bytes to the existing five-original paired handoff without changing that
canonical handoff or any downstream material facts.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import rch_2027_raw_acquire as raw
import rch_2027_paired_handoff as pair

PARSER_VERSION = "RCH_2027_UEFISCDI_NEWS_RAW_V1"
SOURCE_ID = "SRC-RO-UEFISCDI-RCH-2027-NEWS"
URL = "https://uefiscdi.gov.ro/news-primul-apel-transnational-al-parteneriatului-european-resilient-cultural-heritage-rch"
RAW_PATH = "raw/SRC-RO-UEFISCDI-RCH-2027-NEWS.html"
MANIFEST_PATH = "handoff/rch_2027_uefiscdi_news.json"
HOSTS = frozenset({"uefiscdi.gov.ro", "www.uefiscdi.gov.ro"})
SOURCE_FAMILY = ["ROMANIA", "EU_DIRECT", "OFFICIAL_DISCOVERY"]
AUTHORITY = "T1B_OFFICIAL_NATIONAL_INFORMATIONAL_NOTICE_NOT_FUNDING_AUTHORITY"
OBSERVATION = "SECONDARY_OFFICIAL_INFORMATION_RAW_UNRECONCILED"
FALSE_FLAGS = tuple(raw.LOCKED_FALSE) + ("distribution_authorized",)
MAX_BYTES = 5_000_000
# Article identity only, NOT a parser for its eligibility/deadline wording.
VISIBLE_TERMS = (
    "primul apel transnațional",
    "resilient cultural heritage",
    "ministerul culturii",
    "unitatea de management",
)
RECEIPT_KEYS = frozenset({
    "source_id", "requested_url", "final_url", "fetched_at_utc",
    "run_id", "parser_version", "programme_family", "source_family",
    "authority_class", "observation_state", "raw_path", "raw_sha256",
    "raw_length", "http_status", "content_type", "content_encoding",
}) | frozenset(FALSE_FLAGS)
MANIFEST_KEYS = frozenset({
    "schema_version", "parser_version", "run_id", "programme_family",
    "observation_state", "paired_handoff_sha256", "receipt",
    "requires", "handoff_sha256",
}) | frozenset(FALSE_FLAGS)
REQUIRES = [
    "review_secondary_news_against_romania_annex_i",
    "independent_current_mc_ump_national_clarification_check",
    "authenticated_epss_submission_stage_confirmation",
    "reviewed_canonical_admission",
]


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    expected = urlsplit(URL)
    if (parsed.scheme != "https" or (parsed.hostname or "").lower() not in HOSTS
            or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.path != expected.path
            or parsed.query or parsed.fragment):
        raise ValueError("UEFISCDI news authority/path drift")


class StrictRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        validate_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def validate_response(*, status: int, mime: str, encoding: str,
                      declared_length: str | None, body: bytes) -> None:
    if status != 200 or mime.split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("UEFISCDI news status/MIME rejected")
    if encoding.strip().lower() not in ("", "identity"):
        raise ValueError("UEFISCDI news compressed transport rejected")
    if not body or len(body) > MAX_BYTES:
        raise ValueError("UEFISCDI news empty/oversize original")
    if declared_length is not None and (
            not declared_length.isdecimal() or int(declared_length) != len(body)):
        raise ValueError("UEFISCDI news truncated/invalid content length")
    if not re.search(rb"<(?:!doctype\s+html\b|html\b)", body[:4096], re.I):
        raise ValueError("UEFISCDI news HTML envelope missing")
    visible = raw._VisibleHTML()
    visible.feed(body.decode("utf-8", errors="replace"))
    text = " ".join(" ".join(visible.chunks).casefold().split())
    if any(term not in text for term in VISIBLE_TERMS):
        raise ValueError("UEFISCDI news source-specific visible identity missing")


def fetch_news() -> tuple[bytes, str, str]:
    validate_url(URL)
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), StrictRedirects())
    req = Request(URL, headers={
        "User-Agent": "PARTENER.EU-official-evidence/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=30) as response:
        final_url = response.geturl()
        validate_url(final_url)
        status = int(getattr(response, "status", 200))
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        encoding = response.headers.get("Content-Encoding", "identity")
        declared = response.headers.get("Content-Length")
        if status != 200 or mime not in {"text/html", "application/xhtml+xml"} or encoding.strip().lower() not in ("", "identity"):
            raise ValueError("UEFISCDI news invalid HTTP transport before body")
        body = response.read(MAX_BYTES + 1)
        validate_response(status=status, mime=mime, encoding=encoding,
                          declared_length=declared, body=body)
        return body, final_url, mime


def _paired(root: Path) -> dict:
    # Establish immutable five-document provenance before admitting a news sidecar.
    return pair.replay(root)


def _receipt(body: bytes, final_url: str, mime: str, run_id: str, stamp: str) -> dict:
    validate_url(final_url)
    validate_response(status=200, mime=mime, encoding="identity",
                      declared_length=None, body=body)
    return {
        "source_id": SOURCE_ID, "requested_url": URL, "final_url": final_url,
        "fetched_at_utc": stamp, "run_id": run_id, "parser_version": PARSER_VERSION,
        "programme_family": raw.FAMILY, "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY, "observation_state": OBSERVATION,
        "raw_path": RAW_PATH, "raw_sha256": raw.sha256(body),
        "raw_length": len(body), "http_status": 200,
        "content_type": mime, "content_encoding": "identity",
        **{key: False for key in FALSE_FLAGS},
    }


def _manifest(receipt: dict, paired_sha: str, run_id: str) -> dict:
    manifest = {
        "schema_version": "1.0", "parser_version": PARSER_VERSION,
        "run_id": run_id, "programme_family": raw.FAMILY,
        "observation_state": OBSERVATION,
        "paired_handoff_sha256": paired_sha,
        "receipt": receipt, "requires": REQUIRES,
        **{key: False for key in FALSE_FLAGS},
    }
    manifest["handoff_sha256"] = raw.sha256(raw.canonical_json(manifest))
    return manifest


def replay(root: Path) -> dict:
    paired = _paired(root)
    manifest = raw.read_evidence_json(root / MANIFEST_PATH)
    raw.require_fields(manifest, MANIFEST_KEYS, "UEFISCDI news handoff")
    checksum = manifest.pop("handoff_sha256")
    if checksum != raw.sha256(raw.canonical_json(manifest)):
        raise ValueError("UEFISCDI news handoff SHA mismatch")
    if (manifest.get("schema_version") != "1.0" or manifest.get("parser_version") != PARSER_VERSION
            or manifest.get("programme_family") != raw.FAMILY
            or manifest.get("observation_state") != OBSERVATION
            or manifest.get("paired_handoff_sha256") != paired["paired_handoff_sha256"]
            or manifest.get("run_id") != paired["run_id"]
            or manifest.get("requires") != REQUIRES
            or any(manifest.get(key) is not False for key in FALSE_FLAGS)):
        raise ValueError("UEFISCDI news handoff identity/authorization drift")
    receipt = manifest.get("receipt")
    if not isinstance(receipt, dict):
        raise ValueError("UEFISCDI news receipt missing")
    raw.require_fields(receipt, RECEIPT_KEYS, "UEFISCDI news receipt")
    if (receipt.get("source_id") != SOURCE_ID or receipt.get("requested_url") != URL
            or receipt.get("run_id") != paired["run_id"]
            or receipt.get("parser_version") != PARSER_VERSION
            or receipt.get("programme_family") != raw.FAMILY
            or receipt.get("source_family") != SOURCE_FAMILY
            or receipt.get("authority_class") != AUTHORITY
            or receipt.get("observation_state") != OBSERVATION
            or receipt.get("raw_path") != RAW_PATH
            or receipt.get("http_status") != 200
            or receipt.get("content_encoding") != "identity"
            or any(receipt.get(key) is not False for key in FALSE_FLAGS)):
        raise ValueError("UEFISCDI news provenance/authorization drift")
    validate_url(receipt.get("final_url", ""))
    stamp = receipt.get("fetched_at_utc")
    if not isinstance(stamp, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp):
        raise ValueError("UEFISCDI news fetched_at missing")
    body = (root / RAW_PATH).read_bytes()
    validate_response(status=200, mime=receipt.get("content_type", ""),
                      encoding=receipt.get("content_encoding", ""),
                      declared_length=str(receipt.get("raw_length")), body=body)
    if raw.sha256(body) != receipt.get("raw_sha256"):
        raise ValueError("UEFISCDI news raw SHA-256 mismatch")
    return {
        "status": "SECONDARY_OFFICIAL_NEWS_RAW_REPLAY_VERIFIED_NOT_PUBLISHED",
        "source_id": SOURCE_ID, "run_id": paired["run_id"],
        "raw_sha256": receipt["raw_sha256"],
        "paired_handoff_sha256": paired["paired_handoff_sha256"],
        "open_call_authorized": False, "eligibility_authorized": False,
        "publish_authorized": False, "distribution_authorized": False,
    }


def capture(root: Path, run_id: str) -> dict:
    paired = _paired(root)
    if not isinstance(run_id, str) or run_id != paired["run_id"]:
        raise ValueError("UEFISCDI news capture run must match the five originals")
    body, final_url, mime = fetch_news()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt = _receipt(body, final_url, mime, run_id, stamp)
    manifest = _manifest(receipt, paired["paired_handoff_sha256"], run_id)
    raw.write_immutable(root / RAW_PATH, body)
    raw.write_immutable(root / MANIFEST_PATH,
                        json.dumps(manifest, indent=2, sort_keys=True,
                                   ensure_ascii=False).encode("utf-8") + b"\n")
    return replay(root)


def main() -> int:
    ap = argparse.ArgumentParser(description="UEFISCDI RCH secondary news raw evidence, no publication")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture-run-id")
    mode.add_argument("--replay", action="store_true")
    ap.add_argument("--evidence-dir", required=True)
    args = ap.parse_args()
    root = Path(args.evidence_dir)
    result = replay(root) if args.replay else capture(root, args.capture_run_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
