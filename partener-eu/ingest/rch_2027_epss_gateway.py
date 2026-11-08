#!/usr/bin/env python3
"""RCH 2027: acquire the EPSS public gateway linked by the exact official call.

Sixth optional original-byte receipt. This proves only a publicly accessible
Call 1 login gateway, never an authenticated submission window or OPEN_CALL.
The original five-source pairing remains separately immutable and unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import re
import ssl
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import rch_2027_raw_acquire as raw
import rch_2027_paired_handoff as pair

VERSION = "RCH_2027_EPSS_GATEWAY_ACQUIRE_V1"
SOURCE_ID = "SRC-EU-RCH-2027-EPSS-GATEWAY"
GATEWAY_URL = "https://epss.proposals.ee/rch/"
RAW_PATH = f"raw/{SOURCE_ID}.html"
MANIFEST_PATH = "handoff/rch_2027_epss_gateway.json"
MAX_BYTES = 2_000_000
FALSE_FLAGS = tuple(raw.LOCKED_FALSE) + ("submission_live_authorized", "distribution_authorized")
FIELDS = frozenset({
    "schema_version", "source_id", "requested_url", "final_url",
    "official_call_detail_url", "source_html_raw_sha256",
    "paired_handoff_sha256", "fetched_at_utc", "run_id", "parser_version",
    "programme_family", "source_family", "authority_class",
    "observation_state", "http_status", "content_type", "raw_path",
    "raw_sha256", "raw_length", "requires", "handoff_sha256",
}) | frozenset(FALSE_FLAGS)


class _LinkParser(raw._VisibleHTML):
    """A visible, labelled outbound link, rather than a JS or template string."""
    def __init__(self):
        super().__init__()
        self.active = None
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag.lower() == "a":
            if self.active is not None:
                raise ValueError("nested official submission link is ambiguous")
            properties = dict(attrs)
            self.active = (properties.get("href", ""), [], self.stack[-1][1])

    def handle_data(self, data):
        super().handle_data(data)
        if self.active is not None and not self.stack[-1][1]:
            self.active[1].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.active is not None:
            href, label, hidden = self.active
            if not hidden and " ".join("".join(label).casefold().split()).startswith("submission platform"):
                self.candidates.append(href)
            self.active = None
        super().handle_endtag(tag)


def validate_gateway_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or (parsed.hostname or "").lower() != "epss.proposals.ee"
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.path != "/rch/"
            or parsed.query or parsed.fragment):
        raise ValueError("RCH EPSS gateway URL/host/path drift")


def official_submission_link(call_html: bytes) -> str:
    raw.validate_source_identity("SRC-EU-RCH-2027-CALL1", call_html)
    collector = _LinkParser()
    collector.feed(call_html.decode("utf-8", errors="replace"))
    source = raw.SOURCE_SPECS["SRC-EU-RCH-2027-CALL1"]["url"]
    candidates = [urljoin(source, x) for x in collector.candidates]
    # The official call page renders the same EPSS link twice (facts + body).
    # Duplication is safe only when every matching visible anchor agrees exactly.
    if not candidates or len(set(candidates)) != 1:
        raise ValueError("RCH official call page has no unique EPSS submission target")
    validate_gateway_url(candidates[0])
    return candidates[0]


def validate_gateway_response(*, status: int, mime: str, encoding: str,
                              declared_length: str | None, body: bytes) -> None:
    if status != 200 or mime.split(";", 1)[0].strip().lower() not in raw.ALLOWED_MIME:
        raise ValueError("RCH EPSS status/MIME rejected")
    if encoding.strip().lower() not in ("", "identity") or not body or len(body) > MAX_BYTES:
        raise ValueError("RCH EPSS encoding/size rejected")
    if declared_length is not None and (
            not declared_length.isdecimal() or int(declared_length) != len(body)):
        raise ValueError("RCH EPSS transfer length mismatch")
    if not re.search(rb"<(?:!doctype\s+html\b|html\b)", body[:4096], re.I):
        raise ValueError("RCH EPSS has no HTML envelope")
    visible = raw._VisibleHTML()
    visible.feed(body.decode("utf-8", errors="replace"))
    text = " ".join(" ".join(visible.chunks).casefold().split())
    required = ("rch call 1", "resilient cultural heritage", "sign in")
    if any(token not in text for token in required):
        raise ValueError("RCH EPSS public login identity missing")


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        validate_gateway_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def fetch_gateway(url: str) -> tuple[bytes, str, str]:
    validate_gateway_url(url)
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()), _SafeRedirects())
    request = Request(url, headers={
        "User-Agent": "PARTENER.EU-official-evidence/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(request, timeout=30) as response:
        final = response.geturl()
        validate_gateway_url(final)
        status = int(getattr(response, "status", 200))
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        encoding = response.headers.get("Content-Encoding", "identity")
        if status != 200 or mime not in raw.ALLOWED_MIME or encoding.strip().lower() not in ("", "identity"):
            raise ValueError("RCH EPSS transport rejected before body read")
        body = response.read(MAX_BYTES + 1)
        validate_gateway_response(status=status, mime=mime, encoding=encoding,
                                  declared_length=response.headers.get("Content-Length"), body=body)
        return body, final, mime


def _origin(root: Path) -> tuple[dict, dict, str]:
    pair.replay(root)
    source_manifest = raw.read_evidence_json(root / "handoff/rch_2027_sources.json")
    paired = raw.read_evidence_json(root / "handoff/rch_2027_paired_handoff.json")
    call_row = next(r for r in source_manifest["receipts"]
                    if r["source_id"] == "SRC-EU-RCH-2027-CALL1")
    url = official_submission_link((root / call_row["raw_path"]).read_bytes())
    return source_manifest, paired, url


def _output(**kwargs) -> dict:
    manifest = {
        "schema_version": "1.0", "source_id": SOURCE_ID,
        "official_call_detail_url": raw.SOURCE_SPECS["SRC-EU-RCH-2027-CALL1"]["url"],
        "parser_version": VERSION, "programme_family": raw.FAMILY,
        "source_family": ["EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"],
        "authority_class": "T1B_PUBLIC_EPSS_GATEWAY_NOT_AUTHENTICATED_SUBMISSION",
        "observation_state": "PUBLIC_RCH_CALL1_LOGIN_GATEWAY_ONLY",
        "http_status": 200, "content_type": "text/html", "raw_path": RAW_PATH,
        "requires": ["authenticated_current_submission_stage",
                     "romania_annex_semantic_reconciliation",
                     "independent_reviewed_canonical_admission"],
        **{key: False for key in FALSE_FLAGS},
        **kwargs,
    }
    manifest["handoff_sha256"] = raw.sha256(raw.canonical_json(manifest))
    return manifest


def replay(root: Path) -> dict:
    source, paired, url = _origin(root)
    record = raw.read_evidence_json(root / MANIFEST_PATH)
    raw.require_fields(record, FIELDS, "EPSS gateway")
    stamped = record.pop("handoff_sha256")
    if raw.sha256(raw.canonical_json(record)) != stamped:
        raise ValueError("RCH EPSS handoff SHA mismatch")
    if any(record.get(key) is not False for key in FALSE_FLAGS):
        raise ValueError("RCH EPSS cannot authorize submission/publication")
    validate_gateway_url(record.get("final_url", ""))
    if record.get("requested_url") != url:
        raise ValueError("RCH EPSS URL not bound to official source anchor")
    if record.get("run_id") != source["run_id"] or record.get("run_id") != paired["run_id"]:
        raise ValueError("RCH EPSS mixed acquisition runs")
    stamp = record.get("fetched_at_utc")
    if not isinstance(stamp, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp):
        raise ValueError("RCH EPSS timestamp invalid")
    when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    previous = datetime.strptime(paired["fetched_at_latest_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if not previous - timedelta(minutes=5) <= when <= previous + timedelta(minutes=20):
        raise ValueError("RCH EPSS not captured in source run")
    if when > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("RCH EPSS evidence timestamp in future")
    source_row = next(r for r in source["receipts"] if r["source_id"] == "SRC-EU-RCH-2027-CALL1")
    body = (root / RAW_PATH).read_bytes()
    validate_gateway_response(status=200, mime="text/html", encoding="identity",
                              declared_length=str(record.get("raw_length")), body=body)
    if record.get("raw_sha256") != raw.sha256(body):
        raise ValueError("RCH EPSS raw integrity failure")
    expected = _output(
        requested_url=url, final_url=record["final_url"],
        source_html_raw_sha256=source_row["raw_sha256"],
        paired_handoff_sha256=paired["handoff_sha256"],
        fetched_at_utc=stamp, run_id=source["run_id"],
        raw_sha256=raw.sha256(body), raw_length=len(body),
    )
    if record != {k: v for k, v in expected.items() if k != "handoff_sha256"}:
        raise ValueError("RCH EPSS source/authority/observation drift")
    return {"status": "EPSS_PUBLIC_LOGIN_RAW_REPLAY_VERIFIED_NOT_PUBLISHED",
            "run_id": record["run_id"], "raw_sha256": record["raw_sha256"],
            "publish_authorized": False, "open_call_authorized": False,
            "submission_live_authorized": False}


def capture(root: Path, run_id: str) -> dict:
    source, paired, url = _origin(root)
    if run_id != source["run_id"] or run_id != paired["run_id"]:
        raise ValueError("RCH EPSS run ID differs from source pairing")
    body, final, mime = fetch_gateway(url)
    validate_gateway_response(status=200, mime=mime, encoding="identity",
                              declared_length=None, body=body)
    raw.write_immutable(root / RAW_PATH, body)
    receipt = _output(
        requested_url=url, final_url=final,
        source_html_raw_sha256=next(r["raw_sha256"] for r in source["receipts"]
                                    if r["source_id"] == "SRC-EU-RCH-2027-CALL1"),
        paired_handoff_sha256=paired["handoff_sha256"],
        fetched_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_id=run_id, raw_sha256=raw.sha256(body), raw_length=len(body),
    )
    raw.write_immutable(root / MANIFEST_PATH,
                        json.dumps(receipt, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return replay(root)


def main() -> None:
    parser = argparse.ArgumentParser(description="RCH public EPSS gateway evidence only, never submit/publish")
    parser.add_argument("--evidence-dir", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture-run-id")
    group.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    root = Path(args.evidence_dir)
    result = replay(root) if args.replay else capture(root, args.capture_run_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
