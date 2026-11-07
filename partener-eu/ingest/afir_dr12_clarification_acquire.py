#!/usr/bin/env python3
"""AFIR DR-12 06.11.2026 clarification: acquire original PDF, never publish it.

The official DR-12 annex page is the ONLY delegation authority. The PDF is
raw discovery evidence; its content/eligibility implications are unverified.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

INDEX_URL = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-12/"
BLOB_HOST = "stportalafirprod.blob.core.windows.net"
DOC_NAME = "nota-clarificare-dr12_06112026.pdf"
LINK_LABEL = "Clarificare istoric șef exploatație DR-12 (06.11.2026)"
VERSION = "afir-dr12-clarification-original-v1"
MAX_HTML, MAX_PDF = 5_000_000, 10_000_000
NON_AUTHORITATIVE = {
    "observation_state": "NEW_DR12_CLARIFICATION_RAW_PENDING_SEMANTIC_RECONCILIATION",
    "call_status_authorized": False,
    "eligibility_authorized": False,
    "publish_authorized": False,
    "distribution_authorized": False,
    "material_fact_action": "NONE",
}


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []
        self.href = None
        self.words = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.words = []

    def handle_data(self, data):
        if self.href is not None:
            self.words.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.found.append((self.href, re.sub(r"\s+", " ", " ".join(self.words)).strip()))
            self.href = None
            self.words = []


def delegated_url(raw_html: bytes) -> str:
    if not raw_html or len(raw_html) > MAX_HTML:
        raise ValueError("DR-12 official index empty or oversized")
    p = Links()
    p.feed(raw_html.decode("utf-8-sig", "replace"))
    # Exact label AND date. Never use an arbitrary blob URL from search results.
    matches = [href for href, label in p.found if label == LINK_LABEL]
    if len(matches) != 1:
        raise ValueError("DR-12 clarification official link missing or ambiguous")
    origin = urllib.parse.urlsplit(urllib.parse.urljoin(INDEX_URL, matches[0]))
    if (origin.scheme != "https" or origin.hostname != "www.afir.ro"
            or origin.path != "/api/file/document" or origin.port not in (None, 443)
            or origin.username or origin.password or origin.fragment):
        raise ValueError("DR-12 document proxy authority mismatch")
    qs = urllib.parse.parse_qs(origin.query, keep_blank_values=True)
    if set(qs) != {"filename", "filetype", "url"} or any(len(x) != 1 for x in qs.values()):
        raise ValueError("DR-12 document proxy query ambiguous")
    if qs["filetype"][0].lower() != "pdf" or qs["filename"][0] != LINK_LABEL:
        raise ValueError("DR-12 document proxy identity mismatch")
    path = qs["url"][0]
    if not re.fullmatch(r"/media/[a-z0-9_-]+/" + DOC_NAME.replace(".", r"\."), path):
        raise ValueError("DR-12 document path not the dated official clarification")
    return "https://" + BLOB_HOST + "/media" + path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Official evidence redirect forbidden")


def acquire_exact(url: str, kind: str, *, authorized_pdf: str | None = None):
    if (kind == "index" and url != INDEX_URL) or (kind == "pdf" and url != authorized_pdf):
        raise ValueError("Source URL not delegated by current AFIR index")
    parts = urllib.parse.urlsplit(url)
    allowed = "www.afir.ro" if kind == "index" else BLOB_HOST
    if (parts.scheme != "https" or parts.hostname != allowed or parts.port not in (None, 443)
            or parts.username or parts.password or parts.fragment):
        raise ValueError("Unsafe official source URL")
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-AFIR-DR12-Clarification/1.0",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=25) as response:
        if response.geturl() != url or getattr(response, "status", 200) != 200:
            raise ValueError("AFIR document status/authority mismatch")
        ctype = (response.headers.get("Content-Type") or "").lower()
        if kind == "index" and "html" not in ctype:
            raise ValueError("Official DR-12 landing is not HTML")
        if kind == "pdf" and ("html" in ctype or "json" in ctype):
            raise ValueError("Delegated DR-12 PDF is a fallback page")
        if (response.headers.get("Content-Encoding") or "identity").strip().lower() != "identity":
            raise ValueError("Encoded official source is not raw original")
        limit = MAX_HTML if kind == "index" else MAX_PDF
        raw = response.read(limit + 1)
        length = response.headers.get("Content-Length")
        if (not raw or len(raw) > limit or
                (length is not None and (not length.strip().isdigit()
                                         or int(length) != len(raw)))):
            raise ValueError("Incomplete or oversized official document")
        if kind == "pdf":
            validate_pdf(raw)
        return raw, ctype


def validate_pdf(raw: bytes) -> None:
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-1024:]:
        raise ValueError("Not a complete original PDF container")


def strict_pairs(pairs):
    value = {}
    for k, v in pairs:
        if k in value:
            raise ValueError("Duplicate evidence manifest key")
        value[k] = v
    return value


def reject_nan(value):
    raise ValueError("Non-finite evidence manifest value")


def run(destination: Path, run_id: str, observed_at: str, attempt: str = "1") -> int:
    if not str(run_id).strip() or not str(attempt).isdigit():
        raise ValueError("Missing AFIR provenance run identity")
    parsed = dt.datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp lacks timezone")
    if destination.exists():
        raise ValueError("DR-12 immutable evidence destination already exists")
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": "AFIR_DR12_CLARIFICATION_ORIGINAL_V1",
        "status": "RAW_FETCH_FAILED",
        "source_url": INDEX_URL,
        "fetched_at": parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "parser_version": VERSION,
        "run_id": str(run_id),
        "run_attempt": str(attempt),
        "programme": "PS_PAC_2023_2027/DR12",
        "source_family": "AFIR",
        "authority_class": "T1_OFFICIAL_AFIR_INDEX_DELEGATED_DOCUMENT",
        "document_title": LINK_LABEL,
        **NON_AUTHORITATIVE,
    }
    try:
        index, index_type = acquire_exact(INDEX_URL, "index")
        (destination / "index.raw.html").write_bytes(index)
        manifest["index"] = {
            "file": "index.raw.html", "sha256": hashlib.sha256(index).hexdigest(),
            "byte_count": len(index), "content_type": index_type, "url": INDEX_URL,
        }
        pdf_url = delegated_url(index)
        pdf, pdf_type = acquire_exact(pdf_url, "pdf", authorized_pdf=pdf_url)
        (destination / "clarification.raw.pdf").write_bytes(pdf)
        manifest["document"] = {
            "file": "clarification.raw.pdf", "sha256": hashlib.sha256(pdf).hexdigest(),
            "byte_count": len(pdf), "content_type": pdf_type, "url": pdf_url,
        }
        manifest["status"] = "RAW_CAPTURED_PENDING_SEMANTIC_RECONCILIATION"
    except Exception as exc:
        (destination / "clarification.raw.pdf").unlink(missing_ok=True)
        manifest.pop("document", None)
        manifest["error"] = f"{type(exc).__name__}: {exc}"[:300]
    (destination / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if manifest["status"] == "RAW_CAPTURED_PENDING_SEMANTIC_RECONCILIATION" else 2


def replay(destination: Path) -> dict:
    if (destination.is_symlink() or not destination.is_dir()
            or {x.name for x in destination.iterdir()}
            != {"index.raw.html", "clarification.raw.pdf", "manifest.json"}
            or any(x.is_symlink() or not x.is_file() for x in destination.iterdir())):
        raise ValueError("DR-12 proof files incomplete or contaminated")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"),
                          object_pairs_hook=strict_pairs, parse_constant=reject_nan)
    expected_fields = {
        "schema", "status", "source_url", "fetched_at", "parser_version", "run_id",
        "run_attempt", "programme", "source_family", "authority_class",
        "document_title", "observation_state", "call_status_authorized",
        "eligibility_authorized", "publish_authorized", "distribution_authorized",
        "material_fact_action", "index", "document",
    }
    if set(manifest) != expected_fields:
        raise ValueError("Unregistered evidence field")
    index, pdf = (destination / "index.raw.html").read_bytes(), (destination / "clarification.raw.pdf").read_bytes()
    validate_pdf(pdf)
    pdf_url = delegated_url(index)
    expected = {
        "schema": "AFIR_DR12_CLARIFICATION_ORIGINAL_V1",
        "status": "RAW_CAPTURED_PENDING_SEMANTIC_RECONCILIATION",
        "source_url": INDEX_URL, "parser_version": VERSION,
        "programme": "PS_PAC_2023_2027/DR12", "source_family": "AFIR",
        "authority_class": "T1_OFFICIAL_AFIR_INDEX_DELEGATED_DOCUMENT",
        "document_title": LINK_LABEL, **NON_AUTHORITATIVE,
        "index": {
            "file": "index.raw.html", "sha256": hashlib.sha256(index).hexdigest(),
            "byte_count": len(index), "content_type": manifest["index"].get("content_type"),
            "url": INDEX_URL,
        },
        "document": {
            "file": "clarification.raw.pdf", "sha256": hashlib.sha256(pdf).hexdigest(),
            "byte_count": len(pdf), "content_type": manifest["document"].get("content_type"),
            "url": pdf_url,
        },
    }
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ValueError("DR-12 source identity or raw evidence integrity mismatch")
    if "html" not in manifest["index"]["content_type"] or any(
            x in manifest["document"]["content_type"] for x in ("html", "json")):
        raise ValueError("DR-12 evidence MIME mismatch")
    if not str(manifest.get("run_id") or "").strip() or not str(manifest.get("run_attempt") or "").isdigit():
        raise ValueError("DR-12 evidence run identity missing")
    stamp = dt.datetime.fromisoformat(str(manifest.get("fetched_at") or "").replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() != dt.timedelta():
        raise ValueError("DR-12 evidence timestamp not UTC")
    return manifest


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--replay-dir":
        m = replay(Path(sys.argv[2]))
        print(json.dumps({"verified": True, "document_sha256": m["document"]["sha256"],
                          "publish_authorized": False, "run_id": m["run_id"]}))
        return 0
    if len(sys.argv) != 1 or not os.environ.get("PARTENER_AFIR_DR12_NOTE_EVIDENCE_DIR"):
        print("PARTENER_AFIR_DR12_NOTE_EVIDENCE_DIR required", file=sys.stderr)
        return 2
    try:
        code = run(
            Path(os.environ["PARTENER_AFIR_DR12_NOTE_EVIDENCE_DIR"]),
            os.environ.get("GITHUB_RUN_ID", ""),
            dt.datetime.now(dt.timezone.utc).isoformat(),
            os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"raw_evidence_state": "CAPTURED" if code == 0 else "HOLD",
                      "publish_authorized": False}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
