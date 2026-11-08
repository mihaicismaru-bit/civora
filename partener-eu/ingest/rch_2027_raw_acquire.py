#!/usr/bin/env python3
"""RCH 2027: official-source acquisition only, immutable raw handoff, fail-closed replay.

This module never decides that a call is OPEN or that dates, budgets, or
national eligibility are publishable. Those require a separate reviewed
exact-call + Romanian national-annex semantic reconciliation.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
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

# This is a source-identity guard, not a call-status or eligibility parser.
# An HTTP 200 HTML envelope at an official URL can still be a maintenance page,
# login/denial page, or stale template; none should enter the paired handoff.
SOURCE_VISIBLE_TERMS = {
    "SRC-EU-RCH-2027-CALL1": (
        "first joint transnational call",
        "foundations for climate-resilient cultural heritage",
    ),
    "SRC-RO-MCUMP-RCH-2027": (
        "primul apel de proiecte",
        "resilient cultural heritage",
    ),
}
_HTML_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}
_HTML_NONVISIBLE = {"head", "script", "style", "template", "noscript", "svg"}


class _VisibleHTML(HTMLParser):
    """Collect actual on-page text, ignoring hidden descendants and script/template data."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        properties = dict(attrs)
        # Normalize *all* CSS whitespace, not only spaces: official-looking
        # text inside display:<TAB>none / visibility:<LF>hidden must not
        # satisfy an exact-call page identity check.
        css = re.sub(r"\\s+", "", properties.get("style") or "").lower()
        hidden_css = (
            "display:none" in css
            or "visibility:hidden" in css
            or "visibility:collapse" in css
            or "content-visibility:hidden" in css
            or re.search(r"(?:^|;)opacity:0(?:;|$|!important)", css) is not None
        )
        hidden = (
            (self.stack[-1][1] if self.stack else False)
            or tag in _HTML_NONVISIBLE or "hidden" in properties
            or (properties.get("aria-hidden") or "").lower() == "true"
            or hidden_css
        )
        if tag not in _HTML_VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _HTML_VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.chunks.append(data)


def validate_source_identity(source_id: str, raw: bytes) -> None:
    """Fail closed on a source-specific call page replaced by unrelated HTML."""
    visible = _VisibleHTML()
    visible.feed(raw.decode("utf-8", errors="replace"))
    text = " ".join(" ".join(visible.chunks).casefold().split())
    if any(term not in text for term in SOURCE_VISIBLE_TERMS[source_id]):
        raise ValueError("RCH official page lacks visible source-specific call identity")

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
    validate_source_identity(source_id, raw)


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



# Document evidence is a separate, bounded immutable handoff.  This deliberately
# does not parse document terms or authorize OPEN_CALL/publication.
DOCUMENT_PARSER_VERSION = "RCH_2027_OFFICIAL_PDF_ACQUISITION_V1"
MAX_DOCUMENT_BYTES = 30_000_000
DOCUMENT_SPECS = {
    "SRC-EU-RCH-2027-CALL-TEXT": "RCH-JTC-2027-Call-Text_final.pdf",
    "SRC-EU-RCH-2027-GUIDANCE": "RCH_JTC_2027_Guidance-for-Applicants.pdf",
    "SRC-EU-RCH-2027-PREPROPOSAL": "RCH_JTC_2027_PreProposal_Template_final.pdf",
}
DOCUMENT_BASE = "https://www.heritageresearch-hub.eu/app/uploads/2026/11/"


def document_url(source_id: str) -> str:
    return DOCUMENT_BASE + DOCUMENT_SPECS[source_id]


def validate_document_url(source_id: str, url: str) -> None:
    if source_id not in DOCUMENT_SPECS:
        raise ValueError("unknown RCH document identity")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or
            (parsed.hostname or "").lower() not in {"www.heritageresearch-hub.eu", "heritageresearch-hub.eu"} or
            parsed.port not in (None, 443) or parsed.username is not None or
            parsed.password is not None or parsed.query or parsed.fragment or
            parsed.path != urlsplit(document_url(source_id)).path):
        raise ValueError("RCH official PDF host/path/identity drift")


class StrictDocumentRedirects(HTTPRedirectHandler):
    def __init__(self, source_id: str):
        super().__init__()
        self.source_id = source_id

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        validate_document_url(self.source_id, target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def validate_document_response(*, status: int, mime: str, encoding: str,
                               declared_length: str | None, raw: bytes) -> None:
    if status != 200 or mime.split(";", 1)[0].strip().lower() != "application/pdf":
        raise ValueError("RCH PDF status/media type rejected")
    if encoding.strip().lower() not in ("", "identity"):
        raise ValueError("RCH PDF opaque compressed transport rejected")
    if len(raw) < 40 or len(raw) > MAX_DOCUMENT_BYTES or not raw.startswith(b"%PDF-"):
        raise ValueError("RCH original PDF envelope/size invalid")
    if b"%%EOF" not in raw[-4096:]:
        raise ValueError("RCH truncated PDF missing EOF marker")
    if declared_length is not None and (
            not declared_length.isdecimal() or int(declared_length) != len(raw)):
        raise ValueError("RCH PDF declared length mismatch")


def fetch_document_raw(source_id: str) -> tuple[bytes, str, str]:
    requested = document_url(source_id)
    validate_document_url(source_id, requested)
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        StrictDocumentRedirects(source_id),
    )
    req = Request(requested, headers={
        "User-Agent": "PARTENER.EU-official-evidence/1.0 (+https://partener.eu)",
        "Accept": "application/pdf",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=40) as resp:
        final_url = resp.geturl()
        validate_document_url(source_id, final_url)
        status = int(getattr(resp, "status", 200))
        mime = resp.headers.get("Content-Type", "")
        encoding = resp.headers.get("Content-Encoding", "identity")
        declared_length = resp.headers.get("Content-Length")
        if (status != 200 or mime.split(";", 1)[0].strip().lower() != "application/pdf"
                or encoding.strip().lower() not in ("", "identity")):
            raise ValueError("RCH PDF transport rejected before reading response body")
        raw = resp.read(MAX_DOCUMENT_BYTES + 1)
        validate_document_response(status=status, mime=mime, encoding=encoding,
                                   declared_length=declared_length, raw=raw)
        return raw, final_url, "application/pdf"


def capture_documents(root: Path, run_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("unsafe RCH PDF evidence run ID")
    rows = []
    for source_id in sorted(DOCUMENT_SPECS):
        raw, final_url, mime = fetch_document_raw(source_id)
        validate_document_url(source_id, final_url)
        validate_document_response(status=200, mime=mime, encoding="identity",
                                   declared_length=None, raw=raw)
        raw_path = f"raw/{source_id}.pdf"
        write_immutable(root / raw_path, raw)
        rows.append({
            "source_id": source_id,
            "requested_url": document_url(source_id),
            "final_url": final_url,
            "raw_path": raw_path,
            "raw_sha256": sha256(raw),
            "raw_length": len(raw),
            "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "parser_version": DOCUMENT_PARSER_VERSION,
            "run_id": run_id,
            "programme_family": FAMILY,
            "source_family": ["EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"],
            "authority_class": "T1B_OFFICIAL_PARTNERSHIP_OPERATOR_DOCUMENT",
            "observation_state": "OFFICIAL_PDF_RAW_UNRECONCILED",
            "content_type": "application/pdf",
            "http_status": 200,
            **{key: False for key in LOCKED_FALSE},
        })
    manifest = {
        "schema_version": "1.0",
        "parser_version": DOCUMENT_PARSER_VERSION,
        "run_id": run_id,
        "programme_family": FAMILY,
        "observation_state": "DOCUMENT_RAW_ACQUIRED_SEMANTIC_RECONCILIATION_REQUIRED",
        "source_ids": sorted(DOCUMENT_SPECS),
        "receipts": rows,
        "national_annex_locator": {
            "source_id": "SRC-EU-RCH-2027-CALL-TEXT",
            "section": "Annex I / Romania",
            "page_index_start": 127,
            "page_index_end": 129,
            "location_is_publication_authority": False,
        },
        **{key: False for key in LOCKED_FALSE},
    }
    manifest["handoff_sha256"] = sha256(canonical_json(manifest))
    write_immutable(root / "handoff" / "rch_2027_documents.json",
                    json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return validate_document_handoff(root)


def validate_document_handoff(root: Path) -> dict:
    manifest = json.loads((root / "handoff" / "rch_2027_documents.json").read_text(encoding="utf-8"))
    got = manifest.pop("handoff_sha256", None)
    if got != sha256(canonical_json(manifest)):
        raise ValueError("RCH document handoff SHA mismatch")
    if (manifest.get("schema_version") != "1.0" or
            manifest.get("parser_version") != DOCUMENT_PARSER_VERSION or
            manifest.get("programme_family") != FAMILY or
            manifest.get("observation_state") != "DOCUMENT_RAW_ACQUIRED_SEMANTIC_RECONCILIATION_REQUIRED" or
            manifest.get("source_ids") != sorted(DOCUMENT_SPECS) or
            manifest.get("national_annex_locator") != {
                "source_id": "SRC-EU-RCH-2027-CALL-TEXT",
                "section": "Annex I / Romania",
                "page_index_start": 127,
                "page_index_end": 129,
                "location_is_publication_authority": False,
            } or
            not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", str(manifest.get("run_id") or ""))):
        raise ValueError("RCH document identity/locator drift")
    if any(manifest.get(key) is not False for key in LOCKED_FALSE):
        raise ValueError("RCH document manifest attempted material authorization")
    rows = manifest.get("receipts")
    if not isinstance(rows, list) or len(rows) != len(DOCUMENT_SPECS) or (
            sorted(str(r.get("source_id")) for r in rows) != sorted(DOCUMENT_SPECS)):
        raise ValueError("RCH required official documents missing/duplicated")
    for row in rows:
        source_id = row["source_id"]
        if (row.get("requested_url") != document_url(source_id) or
                row.get("parser_version") != DOCUMENT_PARSER_VERSION or
                row.get("run_id") != manifest["run_id"] or
                row.get("programme_family") != FAMILY or
                row.get("source_family") != ["EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"] or
                row.get("authority_class") != "T1B_OFFICIAL_PARTNERSHIP_OPERATOR_DOCUMENT" or
                row.get("observation_state") != "OFFICIAL_PDF_RAW_UNRECONCILED" or
                row.get("raw_path") != f"raw/{source_id}.pdf" or
                row.get("content_type") != "application/pdf" or
                row.get("http_status") != 200 or
                not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(row.get("fetched_at_utc") or ""))):
            raise ValueError("RCH document provenance drift")
        if any(row.get(key) is not False for key in LOCKED_FALSE):
            raise ValueError("RCH document receipt attempted material authorization")
        validate_document_url(source_id, row.get("final_url", ""))
        raw = (root / row["raw_path"]).read_bytes()
        validate_document_response(status=row["http_status"], mime=row["content_type"],
                                   encoding="identity", declared_length=str(row.get("raw_length")), raw=raw)
        if row.get("raw_sha256") != sha256(raw):
            raise ValueError("RCH document raw SHA mismatch")
    return {"status": "PDF_RAW_REPLAY_VERIFIED_NOT_PUBLISHED",
            "run_id": manifest["run_id"],
            "source_ids": sorted(DOCUMENT_SPECS),
            "publish_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="RCH 2027 original source capture/replay; never publish")
    parser.add_argument("--output-dir", default="/tmp/rch-2027-call1-evidence")
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--replay-dir")
    parser.add_argument("--documents", action="store_true", help="PDF original-byte evidence only; no publication")
    args = parser.parse_args()
    if args.documents:
        result = (validate_document_handoff(Path(args.replay_dir)) if args.replay_dir
                  else capture_documents(Path(args.output_dir), args.run_id))
    else:
        result = validate_handoff(Path(args.replay_dir)) if args.replay_dir else capture(Path(args.output_dir), args.run_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
