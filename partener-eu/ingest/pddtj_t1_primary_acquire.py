#!/usr/bin/env python3
"""Acquire the exact MIPE PDDTJ Order 1794 page as a non-admitting T1 candidate.

This extends the existing Verified Source Registry workflow. A captured page
does not establish the order attachment, entry-into-force date, an open call,
or permission to publish. Original bytes exist only in per-run CI artifacts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.error import HTTPError

import pddtj_oi_discovery_acquire as oi

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu/ingest/source_registry.json"
VERSION = "PDDTJ_T1_PRIMARY_CANDIDATE_V1"
SCHEMA = "PARTENER_EU_PDDTJ_T1_PRIMARY_NONADMITTING_V1"
SOURCE_ID = "SRC-ADRVEST-PDDTJ-PARKS-1794-2026"
RAW_NAME = "mipe-pddtj-order-1794-candidate.original.html"
OFF = {
    "material_fact_use": False,
    "t1_primary_reconciled": False,
    "order_attachment_verified": False,
    "effective_date_verified": False,
    "open_call_authorized": False,
    "publish_authorized": False,
    "distribution_authorized": False,
    "canonical_corpus_mutation": False,
    "publication_effect": "NONE",
}


def identity(registry):
    rows = oi.source_rows(registry)
    source = rows[SOURCE_ID]
    url = source.get("primary_t1_link_candidate")
    witness = source.get("primary_t1_link_witness")
    if (url !=
        "https://mfe.gov.ro/dgpddtj-actualizarea-ghidului-solicitantului-pentru-actiunea-dezvoltarea-intreprinderilor-si-a-antreprenoriatului-componenta-sprijin-pentru-infrastructura-de-afaceri/"
        or witness !=
        "https://www.cjgorj.ro/actualizarea-ghidului-solicitantului-pentru-actiunea-dezvoltarea-intreprinderilor-si-a-antreprenoriatului-componenta-sprijin-pentru-infrastructura-de-afaceri-parc/"
        or source.get("primary_t1_raw_receipt_state") != "PENDING_TRANSPORT_AND_CONTENT_VERIFICATION"):
        raise ValueError("MIPE primary candidate must be pinned and unverified")
    return url, witness


def expected(url, witness, run_id):
    return {
        "source_id": SOURCE_ID,
        "requested_url": url,
        "witness_url": witness,
        "programme": "PDDTJ",
        "source_family": ["ROMANIA", "MIPE_PRIMARY", "GUIDE_AMENDMENT"],
        "authority_class": "T1_PRIMARY_CANDIDATE_UNRECONCILED",
        "observation_state": "GUIDE_AMENDMENT_DISCOVERED_RAW_PENDING",
        "parser_version": VERSION,
        "run_id": run_id,
        **OFF,
    }


def acquire(registry, raw_dir, run_id, fetcher=oi.network_fetch, observed_at=None):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("invalid run_id")
    url, witness = identity(registry)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    if list(raw_dir.iterdir()):
        raise ValueError("new acquisition needs an empty raw directory")
    timestamp = observed_at or oi.utc()
    oi.require_utc_stamp(timestamp)
    row = {**expected(url, witness, run_id), "attempted_at": timestamp}
    try:
        raw, media, final, code = fetcher(url)
        if final != url or code != 200 or media not in oi.HTML_TYPES:
            raise ValueError("original MIPE origin, media or status mismatch")
        sem = oi.validate_visible(raw, {"words": ("1794", "parcuri industriale")})
        (raw_dir / RAW_NAME).write_bytes(raw)
        row.update({
            "fetch_status": "PASS",
            "source_health": "RAW_CAPTURED",
            "final_url": final,
            "http_status": 200,
            "content_type": media,
            "fetched_at": observed_at or oi.utc(),
            "raw_file": RAW_NAME,
            "raw_bytes": len(raw),
            "raw_sha256": oi.digest(raw),
            "semantic_sha256": sem,
        })
    except (OSError, ValueError, RuntimeError) as error:
        code = error.code if isinstance(error, HTTPError) else None
        health = ("HTTP_FAILURE" if isinstance(error, HTTPError) else
                  "IDENTITY_OR_CONTENT_REVIEW" if isinstance(error, ValueError) else
                  "TRANSPORT_FAILURE")
        row.update({
            "fetch_status": "FAIL_REVIEW",
            "source_health": health,
            "error_type": type(error).__name__,
            "http_status": code,
            "fetched_at": None,
            "raw_file": None,
            "raw_sha256": None,
        })
    manifest = {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": observed_at or oi.utc(),
        "rows": [row],
        "fetch_pass": int(row["fetch_status"] == "PASS"),
        "fetch_fail": int(row["fetch_status"] == "FAIL_REVIEW"),
        **OFF,
    }
    manifest["handoff_sha256"] = oi.digest(oi.canonical(manifest))
    validate_replay(manifest, raw_dir, registry)
    return manifest


def validate_replay(manifest, raw_dir, registry):
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("T1 candidate handoff schema mismatch")
    proof = manifest.get("handoff_sha256")
    base = {k: v for k, v in manifest.items() if k != "handoff_sha256"}
    if not isinstance(proof, str) or proof != oi.digest(oi.canonical(base)):
        raise ValueError("T1 candidate handoff fingerprint mismatch")
    if any(manifest.get(k) != v for k, v in OFF.items()):
        raise ValueError("T1 candidate crossed publication boundary")
    if (not isinstance(manifest.get("run_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", manifest["run_id"])):
        raise ValueError("T1 replay run identity invalid")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("T1 candidate row cardinality mismatch")
    row = rows[0]
    url, witness = identity(registry)
    fixed = expected(url, witness, manifest["run_id"])
    if any(row.get(k) != v for k, v in fixed.items()):
        raise ValueError("T1 original identity or non-admission drift")
    if not isinstance(row.get("attempted_at"), str):
        raise ValueError("missing source health timestamp")
    attempt = oi.require_utc_stamp(row["attempted_at"])
    if attempt > oi.require_utc_stamp(manifest["created_at"]):
        raise ValueError("attempt later than manifest")
    if row.get("fetch_status") == "PASS":
        allowed = set(fixed) | {"attempted_at", "fetch_status", "source_health",
                   "final_url", "http_status", "content_type", "fetched_at",
                   "raw_file", "raw_bytes", "raw_sha256", "semantic_sha256"}
        raw = (Path(raw_dir) / RAW_NAME).read_bytes()
        if (set(row) != allowed or row.get("raw_file") != RAW_NAME
            or row.get("final_url") != url or row.get("http_status") != 200
            or row.get("content_type") not in oi.HTML_TYPES
            or row.get("source_health") != "RAW_CAPTURED"
            or row.get("raw_bytes") != len(raw)
            or row.get("raw_sha256") != oi.digest(raw)
            or row.get("semantic_sha256") != oi.validate_visible(
                raw, {"words": ("1794", "parcuri industriale")})
            or oi.require_utc_stamp(row.get("fetched_at")) < attempt
            or manifest.get("fetch_pass") != 1 or manifest.get("fetch_fail") != 0):
            raise ValueError("T1 primary raw provenance invalid")
        expected_files = {RAW_NAME}
    elif row.get("fetch_status") == "FAIL_REVIEW":
        allowed = set(fixed) | {"attempted_at", "fetch_status", "source_health",
                               "error_type", "http_status", "fetched_at",
                               "raw_file", "raw_sha256"}
        category = row.get("error_type")
        if (set(row) != allowed or row.get("fetched_at") is not None
            or row.get("raw_file") is not None or row.get("raw_sha256") is not None
            or manifest.get("fetch_pass") != 0 or manifest.get("fetch_fail") != 1):
            raise ValueError("T1 fetch failure invented provenance")
        if category == "HTTPError":
            if (row.get("source_health") != "HTTP_FAILURE"
                or type(row.get("http_status")) is not int
                or not 400 <= row["http_status"] <= 599):
                raise ValueError("T1 HTTP failure mismatch")
        elif category == "ValueError":
            if row.get("source_health") != "IDENTITY_OR_CONTENT_REVIEW" or row.get("http_status") is not None:
                raise ValueError("T1 content failure mismatch")
        elif category in {"OSError", "URLError", "TimeoutError", "SSLError", "RuntimeError", "ConnectionError"}:
            if row.get("source_health") != "TRANSPORT_FAILURE" or row.get("http_status") is not None:
                raise ValueError("T1 transport failure mismatch")
        else:
            raise ValueError("unrecognized T1 source failure type")
        expected_files = set()
    else:
        raise ValueError("unknown T1 candidate status")
    if {p.name for p in Path(raw_dir).iterdir()} != expected_files:
        raise ValueError("T1 raw file manifest mismatch")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--replay-manifest", type=Path)
    args = parser.parse_args()
    registry = oi.strict_load(REGISTRY.read_text(encoding="utf-8"))
    if args.replay_manifest:
        manifest = oi.strict_load(args.replay_manifest.read_text(encoding="utf-8"))
        validate_replay(manifest, args.raw_dir, registry)
    else:
        manifest = acquire(registry, args.raw_dir, args.run_id)
        args.out.write_bytes(oi.canonical(manifest))
    print(json.dumps({
        "t1_primary_candidate": True,
        "fetch_pass": manifest["fetch_pass"],
        "fetch_fail": manifest["fetch_fail"],
        "t1_primary_reconciled": False,
        "publication_effect": "NONE",
    }))


if __name__ == "__main__":
    main()
