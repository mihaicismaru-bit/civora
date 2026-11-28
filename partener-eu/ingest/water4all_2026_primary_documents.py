#!/usr/bin/env python3
"""Water4All JTC 2026 primary PDFs: acquisition-only, immutable and non-authorizing.

The operator's call page links these original documents. The page's displayed
version labels are discovery hints, NOT validated PDF contents. This module
deliberately never extracts OPEN_CALL, Romanian eligibility, dates or budgets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import ssl
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

PARSER = "WATER4ALL_2026_PRIMARY_DOCUMENTS_RAW_V1"
SCHEMA = "PARTENER_WATER4ALL_2026_PDF_HANDOFF_V1"
FAMILY = "HORIZON_EUROPE/WATER4ALL/JTC_2026"
HOST = "www.water4all-partnership.eu"
MAX_BYTES = 15_000_000
LOCKED = ("material_fact_use", "open_call_authorized", "publish_authorized",
          "distribution_authorized", "deadline_authorized", "budget_authorized",
          "eligibility_authorized", "national_regulations_reconciled")
DOCUMENTS = {
    "CALL_ANNOUNCEMENT": {
        "url": "https://www.water4all-partnership.eu/sites/default/files/2026-09/Call_Announcement_Water4All_JTC2026_20260908.pdf",
        "version_hint_unverified": "V3_2026-10-06",
    },
    "NATIONAL_REGULATIONS": {
        "url": "https://www.water4all-partnership.eu/sites/default/files/2026-06/National_Regulations-Water4All_JTC2026.pdf",
        "version_hint_unverified": "V8_2026-10-28",
    },
}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def no_nonfinite(value):
        raise ValueError("nonfinite JSON token")
    obj = json.loads(raw, object_pairs_hook=unique, parse_constant=no_nonfinite)
    if not isinstance(obj, dict):
        raise ValueError("handoff not object")
    return obj


def exact_url(doc_id, url):
    if doc_id not in DOCUMENTS or url != DOCUMENTS[doc_id]["url"]:
        raise ValueError("exact official document URL drift")
    part = urlsplit(url)
    if (part.scheme != "https" or part.hostname != HOST or
            part.port not in (None, 443) or part.username or part.password or
            part.query or part.fragment):
        raise ValueError("invalid official document host or URL")


def pdf_ok(raw, mime):
    if mime.split(";", 1)[0].strip().lower() != "application/pdf":
        raise ValueError("official PDF MIME mismatch")
    if not isinstance(raw, bytes) or len(raw) < 1024 or len(raw) > MAX_BYTES:
        raise ValueError("official PDF size invalid")
    if not re.match(rb"%PDF-[12]\.[0-9]", raw[:8]) or b"%%EOF" not in raw[-2048:]:
        raise ValueError("official PDF magic/trailer missing")


def stamp_ok(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("fetched_at not UTC seconds")
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not datetime(2026, 11, 10, tzinfo=timezone.utc) <= when <= datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("fetched_at outside acquisition period")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("official PDF redirect refused")


def fetch(doc_id):
    spec = DOCUMENTS[doc_id]
    exact_url(doc_id, spec["url"])
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(spec["url"], headers={
        "User-Agent": "PARTENER.EU-water4all-primary-docs/1.0",
        "Accept": "application/pdf", "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=30) as response:
        exact_url(doc_id, response.geturl())
        if response.status != 200:
            raise ValueError("official PDF HTTP status not 200")
        if (response.headers.get("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("official PDF compressed or transformed response")
        mime = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) != len(raw)):
            raise ValueError("official PDF Content-Length mismatch")
        pdf_ok(raw, mime)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        return raw, mime, stamp


def build(originals, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("run_id invalid")
    if not originals or not set(originals).issubset(DOCUMENTS):
        raise ValueError("at least one exact official PDF required")
    receipts = []
    for doc_id in sorted(originals):
        raw, mime, stamp = originals[doc_id]
        pdf_ok(raw, mime)
        stamp_ok(stamp)
        spec = DOCUMENTS[doc_id]
        exact_url(doc_id, spec["url"])
        receipts.append({
            "document_id": doc_id,
            "parent_source_id": "SRC-EU-WATER4ALL-2026-JTC",
            "requested_url": spec["url"], "final_url": spec["url"],
            "raw_path": f"raw/{doc_id}.pdf", "raw_sha256": sha256(raw),
            "raw_bytes": len(raw), "content_type": mime, "http_status": 200,
            "fetched_at": stamp, "run_id": run_id, "parser_version": PARSER,
            "programme_family": FAMILY, "source_family": "EU_DIRECT/BRUSSELS/JOINT_TRANSNATIONAL_CALL",
            "authority_class": "T1_OFFICIAL_JOINT_CALL_OPERATOR",
            "observation_state": "PDF_RAW_ACQUIRED_CONTENT_AND_VERSION_NOT_RECONCILED",
            "document_version_hint_unverified": spec["version_hint_unverified"],
            "publication_effect": "NONE", **{key: False for key in LOCKED},
        })
    payload = {
        "schema": SCHEMA, "run_id": run_id, "parser_version": PARSER,
        "programme_family": FAMILY, "document_ids": sorted(DOCUMENTS),
        "documents_missing": sorted(set(DOCUMENTS) - set(originals)),
        "documents_complete": len(originals) == len(DOCUMENTS),
        "observation_state": "RAW_DOCUMENTS_ONLY_SEMANTIC_REVIEW_REQUIRED",
        "requires": ["verify_pdf_actual_version_and_call_identity",
                     "cross_check_dates_against_current_operator_page",
                     "review_romania_section_of_national_regulations",
                     "obtain_romanian_national_information_package",
                     "confirm_current_epss_and_stage",
                     "reviewed_exact_call_semantic_reconciliation"],
        "receipts": receipts, "publication_effect": "NONE",
        **{key: False for key in LOCKED},
    }
    payload["handoff_sha256"] = sha256(canonical(payload))
    return payload


def replay(out):
    if not out.is_dir() or out.is_symlink() or {p.name for p in out.iterdir()} != {"raw", "handoff.json"}:
        raise ValueError("immutable PDF handoff file-set invalid")
    if (out / "raw").is_symlink() or (out / "handoff.json").is_symlink():
        raise ValueError("symlinked PDF handoff")
    payload = strict_json((out / "handoff.json").read_bytes())
    receipts = payload.get("receipts")
    if not isinstance(receipts, list):
        raise ValueError("PDF receipts not list")
    ids = [r.get("document_id") for r in receipts]
    if not ids or ids != sorted(set(ids)) or not set(ids).issubset(DOCUMENTS):
        raise ValueError("PDF receipt identity/order invalid")
    raw_dir = out / "raw"
    if not raw_dir.is_dir() or {p.name for p in raw_dir.iterdir()} != {f"{i}.pdf" for i in ids}:
        raise ValueError("PDF raw file-set drift")
    if any(p.is_symlink() for p in raw_dir.iterdir()):
        raise ValueError("symlinked original PDF")
    reconstructed = build({
        doc_id: (
            (raw_dir / f"{doc_id}.pdf").read_bytes(),
            next(row["content_type"] for row in receipts if row["document_id"] == doc_id),
            next(row["fetched_at"] for row in receipts if row["document_id"] == doc_id),
        ) for doc_id in ids
    }, payload.get("run_id"))
    if payload != reconstructed:
        raise ValueError("PDF immutable evidence hash/provenance/policy mismatch")
    return {
        "status": ("BOTH_PDFS_RAW_REPLAY_VERIFIED_NOT_RECONCILED"
                   if reconstructed["documents_complete"] else
                   "PARTIAL_PDFS_RAW_REPLAY_VERIFIED_NOT_RECONCILED"),
        "document_count": len(ids), "documents_missing": reconstructed["documents_missing"],
        "run_id": payload["run_id"], "open_call_authorized": False,
        "publication_effect": "NONE",
    }


def seal(out, originals, run_id):
    payload = build(originals, run_id)
    if out.exists() or out.is_symlink() or out.parent.is_symlink():
        raise ValueError("immutable PDF destination must not already exist")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="partener-water4all-pdfs-", dir=out.parent) as tmp:
        stage = Path(tmp)
        (stage / "raw").mkdir()
        for row in payload["receipts"]:
            (stage / row["raw_path"]).write_bytes(originals[row["document_id"]][0])
        (stage / "handoff.json").write_bytes(canonical(payload) + b"\n")
        stage.rename(out)
    return replay(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--replay-dir", type=Path)
    args = parser.parse_args()
    if args.replay_dir:
        result = replay(args.replay_dir)
    else:
        if not args.out or not args.run_id:
            parser.error("--out and --run-id required")
        originals = {}
        for doc_id in sorted(DOCUMENTS):
            try:
                originals[doc_id] = fetch(doc_id)
            except (ValueError, OSError) as exc:
                print(f"OFFICIAL_PDF_QUARANTINED {doc_id}: {type(exc).__name__}: {exc}")
        if not originals:
            raise ValueError("no official original PDF verified; no evidence handoff")
        result = seal(args.out, originals, args.run_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
