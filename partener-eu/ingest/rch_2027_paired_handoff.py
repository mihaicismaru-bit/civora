#!/usr/bin/env python3
"""RCH 2027 immutable cross-handoff integrity gate; never semantic admission.

The HTML and PDF collectors deliberately produce independent original-byte
manifests. This gate proves that all five receipts belong to one bounded
acquisition run and seals their exact manifests into a third immutable receipt.
It is not a call-status or national-eligibility decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import rch_2027_raw_acquire as raw

PAIR_VERSION = "RCH_2027_PAIRED_HANDOFF_V1"
MAX_CAPTURE_SPAN_SECONDS = 1200
# Legitimate clock skew is tolerated; an acquisition receipt cannot be from the future.
MAX_FUTURE_SKEW_SECONDS = 300
PAIR_NAME = "rch_2027_paired_handoff.json"


def read_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("RCH handoff must be a JSON object")
    return value


def expected_pair(root: Path) -> dict:
    """Recompute the expected sealed receipt from validated original bytes."""
    raw.validate_handoff(root)
    raw.validate_document_handoff(root)
    html_path = root / "handoff" / "rch_2027_sources.json"
    pdf_path = root / "handoff" / "rch_2027_documents.json"
    html_bytes = html_path.read_bytes()
    pdf_bytes = pdf_path.read_bytes()
    html = read_manifest(html_path)
    pdf = read_manifest(pdf_path)

    run_id = html["run_id"]
    if not isinstance(run_id, str) or run_id != pdf["run_id"]:
        raise ValueError("RCH HTML and PDF evidence came from different runs")
    receipts = html["receipts"] + pdf["receipts"]
    if len(receipts) != 5 or any(row["run_id"] != run_id for row in receipts):
        raise ValueError("RCH original evidence run identities are inconsistent")

    stamps = []
    for row in receipts:
        stamp = datetime.strptime(row["fetched_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
        stamps.append(stamp.replace(tzinfo=timezone.utc))
    oldest, newest = min(stamps), max(stamps)
    if (newest - oldest).total_seconds() > MAX_CAPTURE_SPAN_SECONDS:
        raise ValueError("RCH HTML/PDF capture spans exceeded the bounded run window")
    if newest > datetime.now(timezone.utc) + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        raise ValueError("RCH original acquisition receipts cannot claim future fetch timestamps")

    result = {
        "schema_version": "1.0",
        "parser_version": PAIR_VERSION,
        "run_id": run_id,
        "programme_family": raw.FAMILY,
        "source_family": ["EU_DIRECT", "BRUSSELS", "ROMANIA", "CALL_REGISTRY"],
        "authority_class": "T1B_PAIRED_OFFICIAL_ORIGINALS_NOT_SEMANTIC_AUTHORITY",
        "observation_state": "OFFICIAL_ORIGINALS_PAIRED_SEMANTIC_RECONCILIATION_REQUIRED",
        "source_ids": sorted(raw.SOURCE_SPECS),
        "document_ids": sorted(raw.DOCUMENT_SPECS),
        "source_handoff_sha256": html["handoff_sha256"],
        "document_handoff_sha256": pdf["handoff_sha256"],
        "source_manifest_raw_sha256": raw.sha256(html_bytes),
        "document_manifest_raw_sha256": raw.sha256(pdf_bytes),
        "fetched_at_earliest_utc": oldest.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_latest_utc": newest.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requires": [
            "independent_exact_call_identifier_review",
            "current_official_submission_endpoint_confirmation",
            "romania_annex_cost_and_eligibility_semantic_reconciliation",
            "reviewed_canonical_admission",
        ],
        **{key: False for key in raw.LOCKED_FALSE},
    }
    result["handoff_sha256"] = raw.sha256(raw.canonical_json(result))
    return result


def replay(root: Path) -> dict:
    expected = expected_pair(root)
    actual = read_manifest(root / "handoff" / PAIR_NAME)
    if actual != expected:
        raise ValueError("RCH paired handoff does not match the five verified originals")
    return {
        "status": "RAW_ORIGINALS_PAIRED_NOT_PUBLISHED",
        "run_id": expected["run_id"],
        "original_count": len(expected["source_ids"]) + len(expected["document_ids"]),
        "paired_handoff_sha256": expected["handoff_sha256"],
        "open_call_authorized": False,
        "publish_authorized": False,
        "semantic_reconciliation_required": True,
    }


def seal(root: Path) -> dict:
    expected = expected_pair(root)
    payload = json.dumps(expected, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    raw.write_immutable(root / "handoff" / PAIR_NAME, payload)
    return replay(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="RCH 2027 five-source immutable pairing; no publication")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seal", action="store_true")
    group.add_argument("--replay", action="store_true")
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    result = seal(Path(args.evidence_dir)) if args.seal else replay(Path(args.evidence_dir))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
