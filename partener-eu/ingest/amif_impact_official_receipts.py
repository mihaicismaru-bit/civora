#!/usr/bin/env python3
"""Acquisition-only paired original receipts for AMIF/2026/SA/IMPACT Lot 3.

Never authorizes OPEN_CALL, a national re-opening, eligibility, distribution
or material fact publication. Both official originals remain raw-pending until
full semantic reconciliation and review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import unicodedata
from urllib.parse import urlsplit
import urllib.error
import urllib.request

VERSION = "AMIF_IMPACT_LOT3_OFFICIAL_ORIGINALS_V1"
SCHEMA = "PARTENER_AMIF_IMPACT_LOT3_RAW_HANDOFF_V1"
FAMILY = "FAMI_2021_2027/AMIF_2026_SA_IMPACT"
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
MAX_BYTES = 4_000_000
LOCKED = ("material_fact_use", "open_call_authorized", "publish_authorized",
          "distribution_authorized", "deadline_authorized", "eligibility_authorized")
SOURCES = {
    "SRC-MAI-AMIF-IMPACT-LOT3-20261110": {
        "url": "https://fed.mai.gov.ro/11719/clarificari-com-actiunea-specifica-impact-extindere-termen-limita-pentru-lotul-3-si-informatii-suplimentare-privind-modalitatea-de-distribuire-pentru-loturile-1-si-2/",
        "kind": "html", "family": "ROMANIA/MAI/FAMI",
        "authority": "T1_MANAGING_AUTHORITY_MIRROR",
        "state": "MAI_NOTICE_RAW_ACQUIRED_SEMANTIC_REVIEW_PENDING",
    },
    "SRC-EC-AMIF-IMPACT-2026-51-PDF": {
        "url": "https://fed.mai.gov.ro/wp-content/uploads/2026/11/1.-IMPACT-extension-of-ddl-Lot-3-and-distrib-key-Note-to-the-Committee.pdf",
        "kind": "pdf", "family": "EU_DIRECT/BRUSSELS/MAI_MIRROR",
        "authority": "T1_EC_DG_HOME_DOCUMENT_NATIONAL_MIRROR",
        "state": "PRIMARY_PDF_RAW_ACQUIRED_SEMANTIC_REVIEW_PENDING",
    },
}


def digest(b):
    return hashlib.sha256(b).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate evidence JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite evidence field")
    obj = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(obj, dict):
        raise ValueError("evidence must be object")
    return obj


def assert_url(source_id, url):
    if source_id not in SOURCES or url != SOURCES[source_id]["url"]:
        raise ValueError("official exact URL drift")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "fed.mai.gov.ro" or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("untrusted official URL")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("official source redirect requires review")


def fold(text):
    normalized = unicodedata.normalize("NFKD", text)
    return re.sub(r"\s+", " ", "".join(c for c in normalized if not unicodedata.combining(c))).casefold().strip()


class Visible(HTMLParser):
    SKIP = {"script", "style", "head", "noscript", "nav", "footer", "svg", "iframe", "template"}
    VOID = {"br", "hr", "img", "input", "meta", "link", "source", "wbr"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts = [], []
    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            attrs = dict(attrs)
            hidden = (tag in self.SKIP or "hidden" in attrs or "inert" in attrs
                      or attrs.get("aria-hidden") == "true"
                      or "display:none" in (attrs.get("style") or "").replace(" ", "").lower())
            self.stack.append((tag, hidden or (self.stack[-1][1] if self.stack else False)))
    def handle_startendtag(self, tag, attrs):
        if tag not in self.VOID | {"svg", "math"}:
            self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        for pos in range(len(self.stack) - 1, -1, -1):
            if self.stack[pos][0] == tag:
                del self.stack[pos:]
                break
    def handle_data(self, data):
        if data.strip() and not (self.stack and self.stack[-1][1]):
            self.parts.append(data.strip())


def validate_raw(source_id, raw, mime):
    spec = SOURCES[source_id]
    media = mime.split(";", 1)[0].strip().lower()
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("empty/oversized original")
    if spec["kind"] == "html":
        if media not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("unexpected MAI notice MIME")
        if b"<html" not in raw[:8192].lower():
            raise ValueError("HTML envelope missing")
        parser = Visible()
        parser.feed(raw.decode("utf-8", "replace"))
        content = fold(" ".join(parser.parts))
        if any(x not in content for x in ("clarificari", "impact", "lotul 3", "20 noiembrie 2026", "home-funds/2026/51")):
            raise ValueError("MAI amendment exact identity missing")
    elif media != "application/pdf" or not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
        raise ValueError("primary PDF envelope/MIME invalid")
    # An authentic-looking PDF shape is not semantic validation of its contents.


def validate_registry(path=REGISTRY):
    data = strict_json(path.read_bytes())
    records = data.get("sources", [])
    by_id = {row["id"]: row for row in records}
    if len(records) != len(by_id):
        raise ValueError("duplicate registry source")
    for source_id, spec in SOURCES.items():
        row = by_id.get(source_id)
        partner = next(key for key in SOURCES if key != source_id)
        if (not row or row.get("url") != spec["url"] or row.get("tier") != "T1"
                or row.get("paired_official_source_id") != partner
                or row.get("call_identifier_discovery_hint") != "AMIF/2026/SA/IMPACT"
                or row.get("commission_note_identifier") != "HOME-Funds/2026/51"
                or row.get("affected_lot") != "3"
                or row.get("adapter_required") != "AMIF_IMPACT_LOT_SPECIFIC_PRIMARY_AND_NATIONAL_RECONCILE"
                or row.get("material_fact_use") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False):
            raise ValueError("AMIF official pair or authority registry drift")
        assert_url(source_id, row["url"])


def valid_timestamp(stamp):
    if not isinstance(stamp, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp):
        raise ValueError("fetched_at UTC missing/invalid")
    date = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if date < datetime(2026, 11, 10, tzinfo=timezone.utc) or date > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("fetched_at outside source date")


def fetch(source_id):
    spec = SOURCES[source_id]
    url = spec["url"]
    assert_url(source_id, url)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        NoRedirect(),
    )
    request = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-official-evidence/1.0",
        "Accept": "text/html,application/xhtml+xml,application/pdf",
        "Accept-Encoding": "identity", "Cache-Control": "no-cache",
    })
    with opener.open(request, timeout=25) as response:
        assert_url(source_id, response.geturl())
        if response.status != 200:
            raise ValueError("official HTTP response is not 200")
        mime = response.headers.get("Content-Type", "")
        if (response.headers.get("Content-Encoding") or "identity").lower().strip() != "identity":
            raise ValueError("compressed official response refused")
        media = mime.split(";", 1)[0].strip().lower()
        if media not in {"text/html", "application/xhtml+xml", "application/pdf"}:
            raise ValueError("official response MIME unsupported")
        raw = response.read(MAX_BYTES + 1)
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) != len(raw)):
            raise ValueError("official source Content-Length mismatch")
        validate_raw(source_id, raw, mime)
        return raw, mime, datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_handoff(raw_by_id, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("invalid run_id")
    if set(raw_by_id) != set(SOURCES):
        raise ValueError("paired official originals required")
    rows = []
    for source_id in sorted(SOURCES):
        spec = SOURCES[source_id]
        raw, mime, stamp = raw_by_id[source_id]
        validate_raw(source_id, raw, mime)
        valid_timestamp(stamp)
        rows.append({
            "source_id": source_id, "requested_url": spec["url"], "final_url": spec["url"],
            "fetched_at": stamp, "raw_sha256": digest(raw), "raw_bytes": len(raw),
            "raw_path": f"raw/{source_id}.{'pdf' if spec['kind']=='pdf' else 'html'}",
            "content_type": mime, "parser_version": VERSION, "run_id": run_id,
            "programme_family": FAMILY, "source_family": spec["family"],
            "authority_class": spec["authority"], "observation_state": spec["state"],
            "http_status": 200, "publication_effect": "NONE",
            **{key: False for key in LOCKED},
        })
    payload = {
        "schema": SCHEMA, "parser_version": VERSION, "run_id": run_id,
        "programme_family": FAMILY, "call_identifier_hint": "AMIF/2026/SA/IMPACT",
        "commission_document": "HOME-Funds/2026/51", "lot": "3",
        "observation_state": "PAIRED_RAW_ACQUIRED_SEMANTIC_REVIEW_REQUIRED",
        "requires": ["full_primary_pdf_semantic_extraction", "original_national_call_reconciliation",
                     "current_submission_channel", "romanian_lot_specific_eligibility",
                     "reviewed_material_release_gate"],
        "receipts": rows, "publication_effect": "NONE",
        **{key: False for key in LOCKED},
    }
    payload["handoff_sha256"] = digest(canonical(payload))
    return payload


def seal(out, raw_by_id, run_id):
    payload = build_handoff(raw_by_id, run_id)
    if out.exists() or out.is_symlink() or out.parent.is_symlink():
        raise ValueError("immutable evidence output must not exist")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="amif-impact-", dir=out.parent) as temporary:
        staging = Path(temporary)
        (staging / "raw").mkdir()
        for receipt in payload["receipts"]:
            (staging / receipt["raw_path"]).write_bytes(raw_by_id[receipt["source_id"]][0])
        (staging / "handoff.json").write_bytes(canonical(payload) + b"\n")
        staging.rename(out)
    return replay(out)


def replay(out):
    if not out.is_dir() or out.is_symlink() or {x.name for x in out.iterdir()} != {"raw", "handoff.json"}:
        raise ValueError("AMIF evidence directory/file-set invalid")
    if (out / "raw").is_symlink() or (out / "handoff.json").is_symlink():
        raise ValueError("symlinked AMIF evidence")
    payload = strict_json((out / "handoff.json").read_bytes())
    fields = {"schema", "parser_version", "run_id", "programme_family", "call_identifier_hint",
              "commission_document", "lot", "observation_state", "requires", "receipts",
              "publication_effect", "handoff_sha256", *LOCKED}
    if set(payload) != fields:
        raise ValueError("AMIF handoff field-set drift")
    fingerprint = payload.pop("handoff_sha256")
    if fingerprint != digest(canonical(payload)):
        raise ValueError("immutable handoff SHA mismatch")
    if (payload["schema"] != SCHEMA or payload["parser_version"] != VERSION
            or payload["programme_family"] != FAMILY or payload["call_identifier_hint"] != "AMIF/2026/SA/IMPACT"
            or payload["commission_document"] != "HOME-Funds/2026/51" or payload["lot"] != "3"
            or payload["observation_state"] != "PAIRED_RAW_ACQUIRED_SEMANTIC_REVIEW_REQUIRED"
            or payload["publication_effect"] != "NONE" or any(payload[key] is not False for key in LOCKED)
            or payload["requires"] != ["full_primary_pdf_semantic_extraction",
                 "original_national_call_reconciliation", "current_submission_channel",
                 "romanian_lot_specific_eligibility", "reviewed_material_release_gate"]):
        raise ValueError("AMIF provenance/publication gate drift")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", str(payload["run_id"])):
        raise ValueError("AMIF run_id drift")
    rows = payload["receipts"]
    if not isinstance(rows, list) or len(rows) != 2 or [r.get("source_id") for r in rows] != sorted(SOURCES):
        raise ValueError("paired AMIF receipt missing/duplicated")
    if {x.name for x in (out / "raw").iterdir()} != {Path(r["raw_path"]).name for r in rows}:
        raise ValueError("AMIF original file-set drift")
    for row in rows:
        spec = SOURCES[row["source_id"]]
        row_fields = {"source_id", "requested_url", "final_url", "fetched_at", "raw_sha256",
                      "raw_bytes", "raw_path", "content_type", "parser_version", "run_id",
                      "programme_family", "source_family", "authority_class", "observation_state",
                      "http_status", "publication_effect", *LOCKED}
        if set(row) != row_fields or (row["requested_url"] != spec["url"]
                or row["final_url"] != spec["url"] or row["parser_version"] != VERSION
                or row["run_id"] != payload["run_id"] or row["programme_family"] != FAMILY
                or row["source_family"] != spec["family"] or row["authority_class"] != spec["authority"]
                or row["observation_state"] != spec["state"] or type(row["http_status"]) is not int
                or row["http_status"] != 200 or row["publication_effect"] != "NONE"
                or any(row[key] is not False for key in LOCKED)):
            raise ValueError("AMIF receipt authority/provenance drift")
        assert_url(row["source_id"], row["final_url"])
        valid_timestamp(row["fetched_at"])
        rawpath = out / row["raw_path"]
        if not rawpath.is_file() or rawpath.is_symlink():
            raise ValueError("original AMIF file missing/symlinked")
        raw = rawpath.read_bytes()
        if type(row["raw_bytes"]) is not int or row["raw_bytes"] != len(raw) or row["raw_sha256"] != digest(raw):
            raise ValueError("AMIF raw original size/hash mismatch")
        validate_raw(row["source_id"], raw, row["content_type"])
    return {"status": "PAIRED_IMMUTABLE_RAW_REPLAY_VERIFIED_NON_AUTHORIZING",
            "run_id": payload["run_id"], "source_count": 2,
            "publication_effect": "NONE", "open_call_authorized": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--replay-dir", type=Path)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    args = parser.parse_args()
    if bool(args.out) == bool(args.replay_dir):
        parser.error("specify exactly one of --out or --replay-dir")
    try:
        validate_registry()
        if args.replay_dir:
            result = replay(args.replay_dir)
        else:
            originals = {source_id: fetch(source_id) for source_id in sorted(SOURCES)}
            result = seal(args.out, originals, args.run_id)
    except (ValueError, OSError, KeyError, TypeError, urllib.error.URLError) as exc:
        print(f"AMIF_IMPACT_RAW_HELD: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
