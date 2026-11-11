#!/usr/bin/env python3
"""Water4All 2026 official pair: acquisition-only, immutable, non-authorizing.

The 10-Nov-2026 preproposal window has passed. A later invited full-proposal
deadline must NEVER become a fresh Romanian OPEN_CALL. Raw HTML evidence
alone does not verify national regulations, the EPSS endpoint or eligibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import tempfile
import unicodedata
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, Request

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
PARSER = "WATER4ALL_2026_OFFICIAL_PAIR_RAW_V1"
SCHEMA = "PARTENER_WATER4ALL_2026_PAIR_HANDOFF_V1"
FAMILY = "HORIZON_EUROPE/WATER4ALL/JTC_2026"
MAX_BYTES = 5_000_000
LOCKED = ("material_fact_use", "open_call_authorized", "publish_authorized",
          "distribution_authorized", "deadline_authorized", "budget_authorized",
          "eligibility_authorized")
SOURCES = {
    "SRC-EU-WATER4ALL-2026-JTC": {
        "url": "https://www.water4all-partnership.eu/joint-activities/water4all-2026-joint-transnational-call",
        "host": "www.water4all-partnership.eu",
        "family": "EU_DIRECT/BRUSSELS/JOINT_TRANSNATIONAL_CALL",
        "authority": "T1_OFFICIAL_JOINT_CALL_OPERATOR",
        "state": "STAGE1_EXPIRED_PRIMARY_HTML_RAW_PENDING_SEMANTIC_REVIEW",
        "markers": ("water4all 2026", "10 november 2026", "6 april 2027", "epss"),
    },
    "SRC-RO-UEFISCDI-WATER4ALL-2026": {
        "url": "https://uefiscdi.gov.ro/water4all",
        "host": "uefiscdi.gov.ro",
        "family": "ROMANIA/UEFISCDI/RESEARCH",
        "authority": "T1B_ROMANIAN_NATIONAL_FUNDING_AGENCY",
        "state": "STAGE1_EXPIRED_NATIONAL_LANDING_RAW_PENDING_SEMANTIC_REVIEW",
        "markers": ("water4all 2026", "10 noiembrie 2026", "aprilie 2027",
                    "water4all-2026-joint-transnational-call"),
    },
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def strict_json(raw):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate JSON key")
            out[k] = v
        return out
    def invalid(value):
        raise ValueError("nonfinite JSON value")
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(result, dict):
        raise ValueError("handoff not object")
    return result


class VisibleText(HTMLParser):
    SKIP = {"head", "script", "style", "noscript", "svg", "iframe", "nav", "footer"}
    VOID = {"br", "hr", "img", "link", "meta", "input", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        attrs = dict(attrs)
        parent_hidden = self.stack[-1][1] if self.stack else False
        hidden = (parent_hidden or tag in self.SKIP or "hidden" in attrs or
                  attrs.get("aria-hidden") == "true" or
                  "display:none" in (attrs.get("style") or "").replace(" ", "").lower())
        self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        if tag not in self.VOID:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data.strip() and not (self.stack and self.stack[-1][1]):
            self.parts.append(data.strip())


def fold(value):
    return re.sub(r"\s+", " ", "".join(
        ch for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch))).casefold()


def exact_url(source_id, url):
    spec = SOURCES[source_id]
    parts = urlsplit(url)
    if (url != spec["url"] or parts.scheme != "https" or
            parts.hostname != spec["host"] or parts.port not in (None, 443) or
            parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("official exact URL/host drift")


def validate_html(source_id, raw, mime):
    if not isinstance(raw, bytes) or len(raw) < 250 or len(raw) > MAX_BYTES:
        raise ValueError("empty, implausible or oversized official HTML original")
    if mime.split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("official HTML MIME mismatch")
    if b"<html" not in raw[:8192].lower():
        raise ValueError("missing HTML envelope")
    parser = VisibleText()
    parser.feed(raw.decode("utf-8", "replace"))
    visible = fold(" ".join(parser.parts))
    missing = [token for token in SOURCES[source_id]["markers"] if token not in visible]
    if missing:
        raise ValueError("exact 2026 call/stage marker missing: " + ", ".join(missing))


def validate_registry(path=REGISTRY):
    rows = strict_json(path.read_bytes()).get("sources")
    if not isinstance(rows, list) or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("source registry duplicate/invalid")
    by_id = {row["id"]: row for row in rows}
    for sid, spec in SOURCES.items():
        row = by_id.get(sid)
        peer = next(k for k in SOURCES if k != sid)
        if (not row or row.get("url") != spec["url"] or
            row.get("paired_official_source_id") != peer or
            row.get("adapter_required") != "WATER4ALL_2026_STAGE_SPECIFIC_PRIMARY_AND_ROMANIAN_RULES_RECONCILE_V1" or
            row.get("authority_class") != spec["authority"] or
            row.get("material_fact_use") is not False or
            row.get("open_call_authorized") is not False or
            row.get("material_fact_publication_authorized") is not False):
            raise ValueError("Water4All official-pair registry authority drift")
        exact_url(sid, row["url"])


def timestamp_ok(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("UTC fetched_at format")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not datetime(2026, 11, 10, tzinfo=timezone.utc) <= date <= datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("fetched_at clock invalid")


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("official redirect refused pending authority review")


def fetch(sid):
    spec = SOURCES[sid]
    exact_url(sid, spec["url"])
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), RejectRedirect())
    req = Request(spec["url"], headers={
        "User-Agent": "PARTENER.EU-water4all-official-evidence/1.0",
        "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=25) as response:
        exact_url(sid, response.geturl())
        if response.status != 200:
            raise ValueError("official HTTP status not 200")
        if (response.headers.get("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("unapproved official content encoding")
        mime = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdecimal() or int(declared) != len(raw)):
            raise ValueError("official HTML declared length drift")
        validate_html(sid, raw, mime)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        return raw, mime, stamp


def build(originals, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("run_id invalid")
    if set(originals) != set(SOURCES):
        raise ValueError("both official paired originals required")
    receipts = []
    for sid in sorted(SOURCES):
        raw, mime, stamp = originals[sid]
        validate_html(sid, raw, mime)
        timestamp_ok(stamp)
        spec = SOURCES[sid]
        receipts.append({
            "source_id": sid, "url": spec["url"], "final_url": spec["url"],
            "raw_path": f"raw/{sid}.html", "raw_sha256": sha(raw),
            "raw_bytes": len(raw), "content_type": mime, "http_status": 200,
            "fetched_at": stamp, "parser_version": PARSER, "run_id": run_id,
            "programme_family": FAMILY, "source_family": spec["family"],
            "authority_class": spec["authority"], "observation_state": spec["state"],
            "publication_effect": "NONE",
            **{key: False for key in LOCKED},
        })
    payload = {
        "schema": SCHEMA, "parser_version": PARSER, "run_id": run_id,
        "programme_family": FAMILY, "source_pair": sorted(SOURCES),
        "call_identity_discovery_hint": "Water4All JTC 2026",
        "stage1": "2026-11-10T15:00:00+01:00_PREPROPOSALS_PASSED",
        "stage2": "2027-04-06T15:00:00+02:00_INVITED_FULL_PROPOSALS_ONLY",
        "observation_state": "PAIRED_HTML_ACQUIRED_ONLY_SEMANTIC_REVIEW_REQUIRED",
        "requires": ["primary_call_announcement_pdf", "national_regulations_v8_romania",
                     "national_information_package", "current_exact_epss_endpoint",
                     "stage_specific_semantic_reconciliation", "reviewed_publication_gate"],
        "receipts": receipts, "publication_effect": "NONE",
        **{key: False for key in LOCKED},
    }
    payload["handoff_sha256"] = sha(canonical(payload))
    return payload


def replay(out):
    if not out.is_dir() or out.is_symlink() or {p.name for p in out.iterdir()} != {"raw", "handoff.json"}:
        raise ValueError("immutable handoff directory/file-set invalid")
    if any(p.is_symlink() for p in (out / "raw", out / "handoff.json")):
        raise ValueError("symlinked handoff item")
    payload = strict_json((out / "handoff.json").read_bytes())
    expected = build({sid: (
        (out / "raw" / f"{sid}.html").read_bytes(),
        next((r["content_type"] for r in payload.get("receipts", []) if r.get("source_id") == sid), ""),
        next((r["fetched_at"] for r in payload.get("receipts", []) if r.get("source_id") == sid), "")
    ) for sid in SOURCES}, payload.get("run_id"))
    if payload != expected:
        raise ValueError("handoff provenance, flags or size/hash mismatch")
    if {p.name for p in (out / "raw").iterdir()} != {f"{sid}.html" for sid in SOURCES}:
        raise ValueError("raw file-set drift")
    if any(p.is_symlink() for p in (out / "raw").iterdir()):
        raise ValueError("symlinked raw original")
    return {"status": "PAIRED_RAW_REPLAY_VERIFIED_NON_AUTHORIZING", "run_id": payload["run_id"],
            "source_count": 2, "publication_effect": "NONE", "open_call_authorized": False}


def seal(out, originals, run_id):
    validate_registry()
    payload = build(originals, run_id)
    if out.exists() or out.is_symlink() or out.parent.is_symlink():
        raise ValueError("immutable handoff output must not exist")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="partener-water4all-", dir=out.parent) as temp:
        stage = Path(temp)
        (stage / "raw").mkdir()
        for row in payload["receipts"]:
            (stage / row["raw_path"]).write_bytes(originals[row["source_id"]][0])
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
            parser.error("--out and --run-id required for acquisition")
        validate_registry()
        originals = {sid: fetch(sid) for sid in sorted(SOURCES)}
        result = seal(args.out, originals, args.run_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
