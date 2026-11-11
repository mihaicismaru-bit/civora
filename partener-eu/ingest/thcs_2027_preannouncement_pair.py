#!/usr/bin/env python3
"""THCS JTC 2027 paired official pre-announcement: immutable, acquisition-only.

A planned 16-Nov-2026 launch is NOT a live call. This evidence is historical
pre-launch intelligence, never a publication, eligibility or submission permit.
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
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

REGISTRY = Path(__file__).resolve().parent / "source_registry.json"
PARSER_VERSION = "THCS_2027_PREANNOUNCEMENT_PAIR_RAW_V1"
SCHEMA = "PARTENER_THCS_2027_PREANNOUNCEMENT_PAIR_V1"
FAMILY = "Horizon Europe / THCS Joint Transnational Call 2027"
MAX_BYTES = 5_000_000
SOURCE_SPECS = {
    "SRC-EU-THCS-2027-PREANNOUNCEMENT": {
        "url": "https://www.thcspartnership.eu/funding/jtc-2027-pre-announcement.kl",
        "authority": "T1_OFFICIAL_JOINT_CALL_OPERATOR",
        "family": "EU_DIRECT/BRUSSELS/PROGRAMMING_PIPELINE",
        "markers": ("jtc 2027", "pre-announcement", "16 november 2026",
                    "january 21, 2027", "june 24, 2027"),
    },
    "SRC-RO-UEFISCDI-THCS-2027": {
        "url": "https://uefiscdi.gov.ro/transforming-health-and-care-systems-thcs",
        "authority": "T1B_ROMANIAN_NATIONAL_FUNDING_AGENCY",
        "family": "ROMANIA/UEFISCDI/PROGRAMMING_PIPELINE",
        "markers": ("thcs-2027", "16 noiembrie 2026",
                    "21 ianuarie 2027", "24 iunie 2027"),
    },
}
PRIMARY = "SRC-EU-THCS-2027-PREANNOUNCEMENT"
OFF = ("material_fact_use", "open_call_authorized", "publish_authorized",
       "distribution_authorized", "deadline_authorized", "budget_authorized",
       "eligibility_authorized")
MANIFEST_KEYS = {"schema", "run_id", "programme_family", "observation_state",
                 "publication_effect", "receipts", "pending_source_ids", "handoff_sha256"} | set(OFF)
RECEIPT_KEYS = {"source_id", "requested_url", "final_url", "raw_file",
                "raw_sha256", "raw_bytes", "fetched_at", "run_id",
                "parser_version", "programme_family", "source_family",
                "authority_class", "observation_state", "content_type",
                "http_status"} | set(OFF)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def strict(raw: bytes) -> dict:
    def no_dupes(pairs):
        result = {}
        for key, val in pairs:
            if key in result:
                raise ValueError("duplicate evidence key")
            result[key] = val
        return result
    def no_nonfinite(value):
        raise ValueError("nonfinite evidence value")
    obj = json.loads(raw, object_pairs_hook=no_dupes, parse_constant=no_nonfinite)
    if not isinstance(obj, dict):
        raise ValueError("evidence not object")
    return obj

def fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(x for x in value if not unicodedata.combining(x))
    value = value.casefold().translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
    return re.sub(r"\s+", " ", value).strip()

class Visible(HTMLParser):
    SKIP = {"head", "script", "style", "noscript", "svg", "template", "iframe",
            "nav", "footer", "dialog", "textarea", "select"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs_seen = {}
        ambiguous = False
        for key, value in attrs:
            if key in attrs_seen and key in {"style", "hidden", "aria-hidden", "inert"}:
                ambiguous = True
            attrs_seen.setdefault(key, value or "")
        css = re.sub(r"\s+", "", attrs_seen.get("style", "").casefold())
        hidden = (ambiguous or tag in self.SKIP or
                  (tag == "details" and "open" not in attrs_seen) or
                  "popover" in attrs_seen or "hidden" in attrs_seen or
                  "inert" in attrs_seen or
                  attrs_seen.get("aria-hidden", "").casefold() == "true" or
                  "display:none" in css or "visibility:hidden" in css or
                  "visibility:collapse" in css or "content-visibility:hidden" in css or
                  re.search(r"(?:^|;)opacity:0(?:\.0+)?(?:!important)?(?:;|$)", css) is not None)
        if tag not in self.VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        if tag not in self.VOID | {"svg", "math"}:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        if not any(hidden for _, hidden in self.stack) and value.strip():
            self.parts.append(value.strip())

def exact_url(source_id: str, url: str):
    expected = SOURCE_SPECS[source_id]["url"]
    parsed = urlsplit(url)
    if (url != expected or parsed.scheme != "https" or
            parsed.hostname != urlsplit(expected).hostname or
            parsed.port not in (None, 443) or parsed.username or parsed.password or
            parsed.query or parsed.fragment):
        raise ValueError("official source URL/host drift")

def validate_html(source_id: str, raw: bytes, mime: str):
    if not isinstance(raw, bytes) or not 250 <= len(raw) <= MAX_BYTES:
        raise ValueError("implausible official original size")
    if not isinstance(mime, str) or mime.split(";", 1)[0].strip().lower() not in (
            "text/html", "application/xhtml+xml"):
        raise ValueError("official HTML MIME mismatch")
    if b"<html" not in raw[:8192].lower():
        raise ValueError("official HTML envelope missing")
    parser = Visible()
    parser.feed(raw.decode("utf-8", "replace"))
    text = fold(" ".join(parser.parts))
    missing = [s for s in SOURCE_SPECS[source_id]["markers"] if s not in text]
    if missing:
        raise ValueError("THCS exact preannouncement/date markers missing: " + ", ".join(missing))

def validate_registry(path=REGISTRY):
    data = strict(Path(path).read_bytes())
    rows = data.get("sources")
    if not isinstance(rows, list) or len({x["id"] for x in rows}) != len(rows):
        raise ValueError("source registry invalid or duplicate")
    by_id = {x["id"]: x for x in rows}
    for sid, spec in SOURCE_SPECS.items():
        row = by_id.get(sid)
        peer = next(x for x in SOURCE_SPECS if x != sid)
        if (not row or row.get("url") != spec["url"] or
            row.get("paired_official_source_id") != peer or
            row.get("authority_class") != spec["authority"] or
            row.get("programme_family") != FAMILY or
            row.get("authority_scope") != "PROGRAMMING_FRAMEWORK" or
            row.get("observation_state") != "PROGRAMMING_PIPELINE" or
            row.get("material_fact_use") is not False or
            row.get("open_call_authorized") is not False or
            row.get("material_fact_publication_authorized") is not False):
            raise ValueError("THCS source registry authority drift")
        exact_url(sid, row["url"])

def timestamp(value: str):
    if not isinstance(value, str) or not re.fullmatch(r"2026-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("fetched_at must be canonical UTC")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not datetime(2026, 11, 11, tzinfo=timezone.utc) <= moment <= datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("THCS receipt timestamp out of bounds")

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("unreviewed official redirect")

def fetch(source_id: str):
    spec = SOURCE_SPECS[source_id]
    exact_url(source_id, spec["url"])
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(spec["url"], headers={
        "User-Agent": "PARTENER.EU-THCS-evidence/1.0",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity", "Cache-Control": "no-cache"})
    with opener.open(req, timeout=25) as res:
        exact_url(source_id, res.geturl())
        if res.status != 200:
            raise ValueError("official HTTP status not 200")
        if (res.headers.get("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("encoded official original rejected")
        mime = res.headers.get("Content-Type", "")
        raw = res.read(MAX_BYTES + 1)
        declared = res.headers.get("Content-Length")
        if declared is not None and (not declared.isdecimal() or int(declared) != len(raw)):
            raise ValueError("declared content length mismatch")
    validate_html(source_id, raw, mime)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return raw, mime, stamp

def build(originals: dict, run_id: str) -> tuple[dict, dict]:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("run_id invalid")
    if PRIMARY not in originals or not set(originals).issubset(SOURCE_SPECS):
        raise ValueError("verified European original required; unverified national source must stay pending")
    receipts, files = [], {}
    for sid in sorted(SOURCE_SPECS):
        raw, mime, stamp = originals[sid]
        validate_html(sid, raw, mime)
        timestamp(stamp)
        spec = SOURCE_SPECS[sid]
        filename = "raw-" + sid + ".html"
        files[filename] = raw
        row = {
            "source_id": sid, "requested_url": spec["url"],
            "final_url": spec["url"], "raw_file": filename,
            "raw_sha256": sha(raw), "raw_bytes": len(raw), "fetched_at": stamp,
            "run_id": run_id, "parser_version": PARSER_VERSION,
            "programme_family": FAMILY, "source_family": spec["family"],
            "authority_class": spec["authority"], "observation_state": "PROGRAMMING_PIPELINE",
            "content_type": mime, "http_status": 200,
        }
        row.update({key: False for key in OFF})
        receipts.append(row)
    manifest = {
        "schema": SCHEMA, "run_id": run_id, "programme_family": FAMILY,
        "observation_state": "PROGRAMMING_PIPELINE", "publication_effect": "NONE",
        "receipts": receipts,
        "pending_source_ids": sorted(set(SOURCE_SPECS) - set(originals)),
    }
    manifest.update({key: False for key in OFF})
    manifest["handoff_sha256"] = sha(canonical(manifest))
    return manifest, files

def seal(out: Path, originals: dict, run_id: str):
    manifest, files = build(originals, run_id)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    for name, original in files.items():
        with (out / name).open("xb") as target:
            target.write(original)
    with (out / "manifest.json").open("xb") as target:
        target.write(canonical(manifest))
    replay(out)
    return manifest

def replay(out: Path):
    out = Path(out)
    if not out.is_dir() or out.is_symlink():
        raise ValueError("missing or symlinked original evidence directory")
    for p in out.iterdir():
        if p.is_symlink() or not p.is_file():
            raise ValueError("untrusted evidence file")
    manifest = strict((out / "manifest.json").read_bytes())
    if set(manifest) != MANIFEST_KEYS or manifest.get("schema") != SCHEMA:
        raise ValueError("THCS handoff schema mismatch")
    proof = manifest["handoff_sha256"]
    if not isinstance(proof, str) or sha(canonical({k: v for k, v in manifest.items() if k != "handoff_sha256"})) != proof:
        raise ValueError("THCS handoff SHA mismatch")
    if (manifest["programme_family"] != FAMILY or
        manifest["observation_state"] != "PROGRAMMING_PIPELINE" or
        manifest["publication_effect"] != "NONE" or
        any(manifest[x] is not False for x in OFF)):
        raise ValueError("THCS publication/authority gate mismatch")
    rows = manifest["receipts"]
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 2 or
        any(not isinstance(row, dict) for row in rows) or
        len({row.get("source_id") for row in rows}) != len(rows) or
        PRIMARY not in {row.get("source_id") for row in rows} or
        not {row.get("source_id") for row in rows}.issubset(SOURCE_SPECS) or
        manifest.get("pending_source_ids") != sorted(set(SOURCE_SPECS) - {row.get("source_id") for row in rows})):
        raise ValueError("THCS primary/pending source receipts mismatch")
    expected = {"manifest.json"}
    originals = {}
    for row in rows:
        if set(row) != RECEIPT_KEYS:
            raise ValueError("THCS receipt schema mismatch")
        sid = row["source_id"]
        spec = SOURCE_SPECS[sid]
        name = "raw-" + sid + ".html"
        if (row["raw_file"] != name or
            row["requested_url"] != spec["url"] or row["final_url"] != spec["url"] or
            row["run_id"] != manifest["run_id"] or
            row["parser_version"] != PARSER_VERSION or
            row["programme_family"] != FAMILY or
            row["source_family"] != spec["family"] or
            row["authority_class"] != spec["authority"] or
            row["observation_state"] != "PROGRAMMING_PIPELINE" or
            row["http_status"] != 200 or
            any(row[key] is not False for key in OFF)):
            raise ValueError("THCS receipt authority/provenance mismatch")
        timestamp(row["fetched_at"])
        raw = (out / name).read_bytes()
        if len(raw) != row["raw_bytes"] or sha(raw) != row["raw_sha256"]:
            raise ValueError("THCS immutable original SHA/size mismatch")
        validate_html(sid, raw, row["content_type"])
        originals[sid] = (raw, row["content_type"], row["fetched_at"])
        expected.add(name)
    if set(x.name for x in out.iterdir()) != expected:
        raise ValueError("extra/missing THCS original evidence file")
    if canonical(build(originals, manifest["run_id"])[0]) != canonical(manifest):
        raise ValueError("THCS replay divergent")
    return {"status": ("THCS_PREANNOUNCEMENT_PAIR_RAW_REPLAY_VERIFIED" if len(rows) == 2
                       else "THCS_EU_PRIMARY_RAW_REPLAY_VERIFIED_NATIONAL_QUARANTINED"),
            "observation_state": "PROGRAMMING_PIPELINE",
            "open_call_authorized": False, "publish_authorized": False,
            "raw_hashes": {r["source_id"]: r["raw_sha256"] for r in rows},
            "pending_source_ids": manifest["pending_source_ids"]}

def main():
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--out", type=Path)
    mode.add_argument("--replay-dir", type=Path)
    p.add_argument("--run-id")
    args = p.parse_args()
    validate_registry()
    if args.replay_dir:
        print(json.dumps(replay(args.replay_dir), sort_keys=True))
        return
    if not args.run_id:
        raise SystemExit("--run-id required")
    originals = {}
    for sid in SOURCE_SPECS:
        try:
            originals[sid] = fetch(sid)
        except (ValueError, OSError) as exc:
            if sid == PRIMARY:
                raise  # no safe primary acquisition means no handoff
            print(json.dumps({"source_id": sid, "observation_state": "NATIONAL_RAW_QUARANTINED",
                              "error_type": type(exc).__name__, "publication_effect": "NONE"}))
    receipt = seal(args.out, originals, args.run_id)
    print(json.dumps({"status": "THCS_PREANNOUNCEMENT_RAW_ACQUIRED_NOT_PUBLISHED",
                      "run_id": receipt["run_id"], "handoff_sha256": receipt["handoff_sha256"],
                      "sources": {r["source_id"]: r["raw_sha256"] for r in receipt["receipts"]},
                      "pending_source_ids": receipt["pending_source_ids"]},
                     sort_keys=True))

if __name__ == "__main__":
    main()
