#!/usr/bin/env python3
"""THCS 2027 national *index* planning signal: official raw discovery only.

The UEFISCDI multi-year THCS detail page may fail strict visible-HTML proof.
This separate source does not repair or override its quarantine. The UEFISCDI
competition index is evidence of a PLANNED listing, never Romanian national
funding rules, an open application window, or a live submission endpoint.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import ssl
from urllib.request import Request, build_opener, HTTPSHandler

import thcs_2027_preannouncement_pair as core

SOURCE_ID = "SRC-RO-UEFISCDI-TRANSNATIONAL-CALL-INDEX"
URL = "https://uefiscdi.gov.ro/apeluri-transnationale"
SCHEMA = "PARTENER_THCS_2027_NATIONAL_INDEX_PLANNING_RAW_V1"
PARSER_VERSION = "THCS_2027_NATIONAL_INDEX_PLANNING_V1"
PROGRAMME_FAMILY = "Horizon Europe / THCS Joint Transnational Call 2027"
SOURCE_FAMILY = "ROMANIA/UEFISCDI/PROGRAMMING_PIPELINE"
AUTHORITY_CLASS = "T1B_ROMANIAN_NATIONAL_CALL_INDEX_DISCOVERY"
SCOPE = "NATIONAL_TRANSNATIONAL_CALL_INDEX_DISCOVERY"
STATE = "PROGRAMMING_PIPELINE"
MAX_BYTES = 4_000_000
RAW_NAME = "raw-uefiscdi-transnational-call-index.html"
OFF = ("material_fact_use", "open_call_authorized", "publish_authorized",
       "distribution_authorized", "deadline_authorized", "budget_authorized",
       "eligibility_authorized")
FIELDS = {"schema", "run_id", "source_id", "requested_url", "final_url",
          "fetched_at", "raw_file", "raw_sha256", "raw_bytes",
          "parser_version", "programme_family", "source_family",
          "authority_class", "authority_scope", "observation_state",
          "publication_effect", "http_status", "content_type",
          "handoff_sha256"} | set(OFF)


def validate_registry(path=core.REGISTRY):
    registry = core.strict(Path(path).read_bytes())
    rows = registry.get("sources")
    if not isinstance(rows, list):
        raise ValueError("index source registry absent")
    matching = [r for r in rows if isinstance(r, dict) and r.get("id") == SOURCE_ID]
    if len(matching) != 1:
        raise ValueError("national source id not unique")
    row = matching[0]
    if (row.get("url") != URL or
        row.get("authority_scope") != SCOPE or
        row.get("material_fact_use") is not False or
        row.get("open_call_authorized") is not False or
        row.get("material_fact_publication_authorized") is not False or
        row.get("adapter_required") != "UEFISCDI_EXACT_CALL_NATIONAL_RULES_RECONCILE_V1"):
        raise ValueError("UEFISCDI index authority drift")


def validate_html(raw: bytes, mime: str):
    if not isinstance(raw, bytes) or not 250 <= len(raw) <= MAX_BYTES:
        raise ValueError("implausible official index original size")
    if (not isinstance(mime, str) or
        mime.split(";", 1)[0].strip().lower() not in
            {"text/html", "application/xhtml+xml"}):
        raise ValueError("official HTML MIME mismatch")
    if b"<html" not in raw[:8192].lower():
        raise ValueError("official HTML envelope missing")
    parser = core.Visible()
    parser.feed(raw.decode("utf-8", "replace"))
    text = core.fold(" ".join(parser.parts))
    # Require all three official headings, in their documented visible order.
    opened = text.find("competitii deschise")
    planned = text.find("competitii in pregatire")
    closed = text.find("competitii inchise")
    if min(opened, planned, closed) < 0 or not opened < planned < closed:
        raise ValueError("UEFISCDI three visible lifecycle headings missing")
    segment = text[planned:closed]
    if "transforming health and care systems (thcs)" in text[opened:planned]:
        raise ValueError("THCS also occurs outside planned lifecycle")
    # Same official planned entry must include the precise expected launch date.
    pattern = (r"transforming health and care systems\s*\(thcs\)"
               r"\s*lansare\s*:?\s*16 noiembrie 2026")
    if len(re.findall(pattern, segment)) != 1:
        raise ValueError("exact THCS-2027 planned entry/date absent or ambiguous")


def fetch():
    validate_registry()
    req = Request(URL, headers={
        "User-Agent": "PARTENER.EU-THCS-index-evidence/1.0",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity", "Cache-Control": "no-cache"})
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()),
                          core.NoRedirect())
    with opener.open(req, timeout=25) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError("index HTTP endpoint drift")
        if (response.headers.get("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("encoded official index rejected")
        mime = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdecimal() or int(declared) != len(raw)):
            raise ValueError("official index content length mismatch")
    validate_html(raw, mime)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return raw, mime, stamp


def build(raw: bytes, mime: str, fetched_at: str, run_id: str):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("run_id invalid")
    core.timestamp(fetched_at)
    validate_html(raw, mime)
    manifest = {
        "schema": SCHEMA, "run_id": run_id, "source_id": SOURCE_ID,
        "requested_url": URL, "final_url": URL, "fetched_at": fetched_at,
        "raw_file": RAW_NAME, "raw_sha256": core.sha(raw),
        "raw_bytes": len(raw), "parser_version": PARSER_VERSION,
        "programme_family": PROGRAMME_FAMILY, "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS, "authority_scope": SCOPE,
        "observation_state": STATE, "publication_effect": "NONE",
        "content_type": mime, "http_status": 200,
    }
    manifest.update({field: False for field in OFF})
    manifest["handoff_sha256"] = core.sha(core.canonical(manifest))
    return manifest


def seal(folder: Path, raw: bytes, mime: str, fetched_at: str, run_id: str):
    manifest = build(raw, mime, fetched_at, run_id)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    with (folder / RAW_NAME).open("xb") as f:
        f.write(raw)
    with (folder / "manifest.json").open("xb") as f:
        f.write(core.canonical(manifest))
    replay(folder)
    return manifest


def replay(folder: Path):
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("missing or symlinked handoff directory")
    if any(f.is_symlink() or not f.is_file() for f in folder.iterdir()):
        raise ValueError("untrusted handoff file")
    if {f.name for f in folder.iterdir()} != {"manifest.json", RAW_NAME}:
        raise ValueError("extra or missing original handoff file")
    manifest = core.strict((folder / "manifest.json").read_bytes())
    if set(manifest) != FIELDS or manifest["schema"] != SCHEMA:
        raise ValueError("national index manifest schema drift")
    proof = manifest["handoff_sha256"]
    if (not isinstance(proof, str) or
        proof != core.sha(core.canonical({k:v for k,v in manifest.items()
                                         if k != "handoff_sha256"}))):
        raise ValueError("national index manifest SHA mismatch")
    if (manifest["source_id"] != SOURCE_ID or manifest["requested_url"] != URL or
        manifest["final_url"] != URL or manifest["raw_file"] != RAW_NAME or
        manifest["parser_version"] != PARSER_VERSION or
        manifest["programme_family"] != PROGRAMME_FAMILY or
        manifest["source_family"] != SOURCE_FAMILY or
        manifest["authority_class"] != AUTHORITY_CLASS or
        manifest["authority_scope"] != SCOPE or
        manifest["observation_state"] != STATE or
        manifest["publication_effect"] != "NONE" or
        manifest["http_status"] != 200 or
        any(manifest[k] is not False for k in OFF)):
        raise ValueError("index provenance/authority gate mismatch")
    raw = (folder / RAW_NAME).read_bytes()
    if len(raw) != manifest["raw_bytes"] or core.sha(raw) != manifest["raw_sha256"]:
        raise ValueError("original index SHA/size mismatch")
    if core.canonical(build(raw, manifest["content_type"], manifest["fetched_at"],
                            manifest["run_id"])) != core.canonical(manifest):
        raise ValueError("national index semantic replay drift")
    return {"status": "THCS_INDEX_PLANNED_RAW_REPLAY_VERIFIED_DISCOVERY_ONLY",
            "source_id": SOURCE_ID, "raw_sha256": core.sha(raw),
            "observation_state": STATE, "open_call_authorized": False,
            "publish_authorized": False, "national_detail_verified": False}


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
    else:
        if not args.run_id:
            raise SystemExit("--run-id required")
        raw, mime, stamp = fetch()
        manifest = seal(args.out, raw, mime, stamp, args.run_id)
        print(json.dumps({"status": "NATIONAL_INDEX_PLANNED_DISCOVERY_ONLY",
                          "source_id": SOURCE_ID, "raw_sha256": manifest["raw_sha256"],
                          "handoff_sha256": manifest["handoff_sha256"],
                          "open_call_authorized": False,
                          "national_detail_verified": False}, sort_keys=True))


if __name__ == "__main__":
    main()
