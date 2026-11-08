#!/usr/bin/env python3
"""RCH 2027: official-source acquisition only, immutable raw handoff, fail-closed replay.

This module never decides that a call is OPEN or that dates, budgets, or
national eligibility are publishable. Those require a separate reviewed
exact-call + Romanian national-annex semantic reconciliation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

PARSER_VERSION = "RCH_2027_RAW_ACQUISITION_V1"
MAX_BYTES = 5_000_000
SOURCE_SPECS = {
    "SRC-EU-RCH-2027-CALL1": {
        "url": "https://www.heritageresearch-hub.eu/call/rch-2027-call/",
        "hosts": {"www.heritageresearch-hub.eu", "heritageresearch-hub.eu"},
        "path": "/call/rch-2027-call",
        "source_family": ["EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"],
        "authority_class": "T1B_OFFICIAL_PARTNERSHIP_OPERATOR",
        "observation_state": "OFFICIAL_CALL_DETAIL_RAW_UNRECONCILED",
    },
    "SRC-RO-MCUMP-RCH-2027": {
        "url": "https://www.umpcultura.ro/ctg_62_rch-resilient-cultural-heritage_pg_0.htm",
        "hosts": {"www.umpcultura.ro", "umpcultura.ro"},
        "path": "/ctg_62_rch-resilient-cultural-heritage_pg_0.htm",
        "source_family": ["ROMANIA", "EU_DIRECT", "CALL_REGISTRY"],
        "authority_class": "T1B_NATIONAL_PARTNERSHIP_PARTICIPANT",
        "observation_state": "OFFICIAL_NATIONAL_RAW_UNRECONCILED",
    },
}
ALLOWED_MIME = {"text/html", "application/xhtml+xml"}
LOCKED_FALSE = (
    "material_fact_use", "open_call_authorized", "publish_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "national_annex_reconciled", "exact_call_identifier_reconciled",
)
FAMILY = "HORIZON_EUROPE_RESILIENT_CULTURAL_HERITAGE"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def validate_url(source_id: str, url: str) -> None:
    spec = SOURCE_SPECS[source_id]
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or (parsed.hostname or "").lower() not in spec["hosts"]
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)
            or parsed.path.rstrip("/") != spec["path"]):
        raise ValueError(f"RCH official source authority/path drift: {source_id}")


class StrictRedirects(HTTPRedirectHandler):
    def __init__(self, source_id: str):
        self.source_id = source_id
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        validate_url(self.source_id, target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def validate_response(source_id: str, *, status: int, mime: str,
                      encoding: str, declared_length: str | None, raw: bytes) -> None:
    if status != 200:
        raise ValueError("non-200 RCH acquisition cannot be admitted")
    if mime.lower().split(";", 1)[0].strip() not in ALLOWED_MIME:
        raise ValueError("unsupported RCH media type")
    if encoding.strip().lower() not in ("", "identity"):
        raise ValueError("compressed RCH response is not original interpreted HTML")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("empty or oversized RCH response")
    if declared_length is not None:
        if not declared_length.isdecimal() or int(declared_length) != len(raw):
            raise ValueError("RCH transfer truncation/length mismatch")
    if not re.search(rb"<(?:!doctype\s+html\b|html\b)", raw[:4096], re.I):
        raise ValueError("RCH response lacks an HTML document envelope")


def fetch_raw(source_id: str) -> tuple[bytes, str, str]:
    spec = SOURCE_SPECS[source_id]
    requested = spec["url"]
    validate_url(source_id, requested)
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        StrictRedirects(source_id),
    )
    req = Request(requested, headers={
        "User-Agent": "PARTENER.EU-official-evidence/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=30) as resp:
        final_url = resp.geturl()
        validate_url(source_id, final_url)
        status = int(getattr(resp, "status", 200))
        mime = resp.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        encoding = resp.headers.get("Content-Encoding", "identity")
        declared = resp.headers.get("Content-Length")
        if status != 200 or mime not in ALLOWED_MIME or encoding.strip().lower() not in ("", "identity"):
            raise ValueError("RCH transport status/MIME/encoding rejected before body read")
        raw = resp.read(MAX_BYTES + 1)
        validate_response(source_id, status=status, mime=mime, encoding=encoding,
                          declared_length=declared, raw=raw)
        return raw, final_url, mime


def make_receipt(source_id: str, raw: bytes, final_url: str, mime: str,
                 fetched_at: str, run_id: str) -> dict:
    spec = SOURCE_SPECS[source_id]
    validate_url(source_id, final_url)
    validate_response(source_id, status=200, mime=mime, encoding="identity",
                      declared_length=None, raw=raw)
    return {
        "source_id": source_id,
        "requested_url": spec["url"],
        "final_url": final_url,
        "fetched_at_utc": fetched_at,
        "run_id": run_id,
        "parser_version": PARSER_VERSION,
        "source_family": spec["source_family"],
        "programme_family": FAMILY,
        "authority_class": spec["authority_class"],
        "observation_state": spec["observation_state"],
        "http_status": 200,
        "content_type": mime,
        "content_encoding": "identity",
        "raw_sha256": sha256(raw),
        "raw_length": len(raw),
        "raw_path": f"raw/{source_id}.html",
        **{key: False for key in LOCKED_FALSE},
    }


def make_handoff(receipts: list[dict], run_id: str) -> dict:
    handoff = {
        "schema_version": "1.0",
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "programme_family": FAMILY,
        "observation_state": "RAW_ACQUIRED_RECONCILIATION_REQUIRED",
        "receipts": receipts,
        "source_ids": sorted(SOURCE_SPECS),
        "requires": [
            "exact_call_identifier", "current_submission_endpoint",
            "call_text_and_applicant_guidance", "romanian_national_annex",
            "semantic_reconciliation", "reviewed_release_gate",
        ],
        **{key: False for key in LOCKED_FALSE},
    }
    handoff["handoff_sha256"] = sha256(canonical_json(handoff))
    return handoff


def write_immutable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(f"immutable RCH receipt collision: {path}")


def validate_handoff(root: Path) -> dict:
    handoff = json.loads((root / "handoff" / "rch_2027_sources.json").read_text(encoding="utf-8"))
    recorded_hash = handoff.pop("handoff_sha256", None)
    if recorded_hash != sha256(canonical_json(handoff)):
        raise ValueError("RCH immutable handoff SHA-256 mismatch")
    if (handoff.get("schema_version") != "1.0" or handoff.get("parser_version") != PARSER_VERSION
            or handoff.get("programme_family") != FAMILY
            or handoff.get("observation_state") != "RAW_ACQUIRED_RECONCILIATION_REQUIRED"
            or handoff.get("source_ids") != sorted(SOURCE_SPECS)):
        raise ValueError("RCH handoff schema/programme/source drift")
    if any(handoff.get(key) is not False for key in LOCKED_FALSE):
        raise ValueError("RCH handoff illegally authorized publication/call")
    receipts = handoff.get("receipts")
    if not isinstance(receipts, list) or len(receipts) != len(SOURCE_SPECS):
        raise ValueError("RCH paired source receipts missing/duplicated")
    if sorted(row.get("source_id") for row in receipts) != sorted(SOURCE_SPECS):
        raise ValueError("RCH wrong source identities")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", str(handoff.get("run_id") or "")):
        raise ValueError("RCH run ID invalid")
    for row in receipts:
        source_id = row["source_id"]
        spec = SOURCE_SPECS[source_id]
        if (row.get("run_id") != handoff["run_id"]
                or row.get("parser_version") != PARSER_VERSION
                or row.get("programme_family") != FAMILY
                or row.get("source_family") != spec["source_family"]
                or row.get("authority_class") != spec["authority_class"]
                or row.get("observation_state") != spec["observation_state"]
                or row.get("requested_url") != spec["url"]
                or row.get("raw_path") != f"raw/{source_id}.html"):
            raise ValueError("RCH receipt provenance/identity drift")
        if any(row.get(key) is not False for key in LOCKED_FALSE):
            raise ValueError("RCH receipt attempted publication/OPEN authorization")
        validate_url(source_id, row.get("final_url", ""))
        stamp = row.get("fetched_at_utc", "")
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp):
            raise ValueError("RCH fetched_at UTC missing/invalid")
        raw = (root / row["raw_path"]).read_bytes()
        validate_response(source_id, status=row.get("http_status"),
                          mime=row.get("content_type", ""),
                          encoding=row.get("content_encoding", ""),
                          declared_length=str(row.get("raw_length")),
                          raw=raw)
        if sha256(raw) != row.get("raw_sha256"):
            raise ValueError("RCH original raw SHA-256 mismatch")
    return {"status": "RAW_REPLAY_VERIFIED_NOT_PUBLISHED", "run_id": handoff["run_id"],
            "sources": sorted(SOURCE_SPECS), "publish_authorized": False}


def capture(root: Path, run_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("run ID must be a safe immutable evidence key")
    receipts = []
    for source_id in sorted(SOURCE_SPECS):
        raw, final_url, mime = fetch_raw(source_id)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        receipt = make_receipt(source_id, raw, final_url, mime, stamp, run_id)
        write_immutable(root / receipt["raw_path"], raw)
        receipts.append(receipt)
    handoff = make_handoff(receipts, run_id)
    write_immutable(root / "handoff" / "rch_2027_sources.json",
                    json.dumps(handoff, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    return validate_handoff(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="RCH 2027 original source capture/replay; never publish")
    parser.add_argument("--output-dir", default="/tmp/rch-2027-call1-evidence")
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--replay-dir")
    args = parser.parse_args()
    result = validate_handoff(Path(args.replay_dir)) if args.replay_dir else capture(Path(args.output_dir), args.run_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
