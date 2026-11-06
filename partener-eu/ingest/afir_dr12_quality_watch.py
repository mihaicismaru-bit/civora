#!/usr/bin/env python3
"""AFIR DR-12 quality-threshold raw evidence, never a call-status writer.

Runs inside the existing AFIR workflow. Original official bytes are preserved
in a per-run artifact; the two preannounced monthly quality thresholds are
*observations*, not eligibility, funding status, or permission to publish.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import afir_ingest as transport

NOTICE_URL = "https://www.afir.ro/comunicate/170-de-milioane-euro-pentru-exploatatiile-tinerilor-fermieri/"
PARSER_VERSION = "afir-dr12-monthly-quality-watch-v2"
# An official notice must contain one coherent monthly-stage statement.
# A second (even malformed) announcement must not be silently discarded.
STAGE_INTRO = re.compile(r"\bpragul\s+de\s+calitate\s+lunar\b", re.IGNORECASE)
MAX_STAGE_SPAN = 480
STAGE_PATTERN = re.compile(
    r"pragul\s+de\s+calitate\s+lunar.*?"
    r"\b80\s+de\s+puncte\b.*?"
    r"\b6\s+octombrie\s*[–—-]\s*5\s+noiembrie\s+2026\b.*?"
    r"\b45\s+de\s+puncte\b.*?"
    r"\b6\s+noiembrie\s*[–—-]\s*2\s+decembrie\s+2026\b.*?"
    r"\bpentru\s+ambele\s+componente\b",
    flags=re.IGNORECASE | re.DOTALL,
)
STAGES = (
    {"from_date": "2026-10-06", "through_date": "2026-11-05", "minimum_quality_points": 80},
    {"from_date": "2026-11-06", "through_date": "2026-12-02", "minimum_quality_points": 45},
)


def parse_notice(raw: bytes) -> list[dict]:
    """Admit exact stage evidence only if both ranges and both components occur."""
    if not isinstance(raw, bytes) or not raw or len(raw) > 12_000_000:
        raise ValueError("empty or oversized AFIR DR-12 raw source")
    parser = transport.Parser()
    parser.feed(raw.decode("utf-8", "replace"))
    text = transport.clean(" ".join(parser.text))
    if not re.search(r"\bDR\s*[-–]\s*12\b", text, re.IGNORECASE):
        raise ValueError("official DR-12 intervention identity missing")
    intros = list(STAGE_INTRO.finditer(text))
    match = STAGE_PATTERN.search(text)
    # Never stitch 80 points from one announcement to 45 points in another,
    # or accept a second conflicting/duplicate monthly-stage announcement.
    if (len(intros) != 1 or match is None or match.start() != intros[0].start()
            or match.end() - match.start() > MAX_STAGE_SPAN):
        raise ValueError("AFIR DR-12 monthly stages missing, duplicated or contradictory")
    return [dict(stage, components=["ZOOTEHNIC", "VEGETAL"]) for stage in STAGES]


def capture(
    fetched: dict,
    destination: Path,
    *,
    run_id: str,
    fetched_at_utc: str,
    run_attempt: str = "1",
) -> dict:
    """Write once to a new run-scoped directory; never overwrite prior proof."""
    raw = fetched.get("data")
    if (
        not run_id or not run_id.strip()
        or fetched.get("ok") is not True
        or fetched.get("url") != NOTICE_URL
        or fetched.get("status") != 200
        or "html" not in str(fetched.get("content_type") or "").lower()
        or not isinstance(raw, bytes)
    ):
        raise ValueError("DR-12 raw receipt lacks exact official HTTPS identity, status, run or HTML bytes")
    observed = dt.datetime.fromisoformat(fetched_at_utc.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("DR-12 receipt timestamp must be timezone-aware")
    stages = parse_notice(raw)
    if destination.exists():
        raise ValueError("DR-12 immutable receipt destination already exists")
    manifest = {
        "schema_version": "1.0",
        "requested_url": NOTICE_URL,
        "final_url": fetched["url"],
        "fetched_at_utc": observed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "raw_evidence_file": "notice.raw.html",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "http_status": fetched["status"],
        "content_type": fetched.get("content_type"),
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "programme": "PS_PAC_2023_2027/DR12",
        "source_family": "AFIR",
        "authority_class": "T1_OFFICIAL_AGENCY",
        "source_publication_date": "2026-10-01",
        "observation_state": "RAW_MONTHLY_QUALITY_STAGE_OBSERVED_PENDING_GUIDE_COUNTER_RECONCILIATION",
        "stage_kind": "PREANNOUNCED_MONTHLY_QUALITY_THRESHOLD",
        "stages": stages,
        "exact_current_call_identifier_verified": False,
        "open_call_authorized": False,
        "eligibility_change_authorized": False,
        "material_fact_action": "NONE",
        "publish_authorized": False,
        "distribution_authorized": False,
    }
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "notice.raw.html").write_bytes(raw)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest



def replay_receipt(destination: Path) -> dict:
    """Independently replay immutable original bytes; never authorize public facts."""
    raw = (destination / "notice.raw.html").read_bytes()
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "requested_url": NOTICE_URL,
        "final_url": NOTICE_URL,
        "raw_evidence_file": "notice.raw.html",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "parser_version": PARSER_VERSION,
        "http_status": 200,
        "programme": "PS_PAC_2023_2027/DR12",
        "source_family": "AFIR",
        "authority_class": "T1_OFFICIAL_AGENCY",
        "stage_kind": "PREANNOUNCED_MONTHLY_QUALITY_THRESHOLD",
        "observation_state": "RAW_MONTHLY_QUALITY_STAGE_OBSERVED_PENDING_GUIDE_COUNTER_RECONCILIATION",
        "source_publication_date": "2026-10-01",
        "stages": parse_notice(raw),
        "exact_current_call_identifier_verified": False,
        "open_call_authorized": False,
        "eligibility_change_authorized": False,
        "material_fact_action": "NONE",
        "publish_authorized": False,
        "distribution_authorized": False,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ValueError(f"DR-12 immutable replay disagreement: {field}")
    if "html" not in str(manifest.get("content_type") or "").lower():
        raise ValueError("DR-12 replay content-type mismatch")
    if not str(manifest.get("run_id") or "").strip():
        raise ValueError("DR-12 replay run_id missing")
    if not str(manifest.get("run_attempt") or "").isdigit():
        raise ValueError("DR-12 replay run_attempt invalid")
    try:
        timestamp = dt.datetime.fromisoformat(
            str(manifest["fetched_at_utc"]).replace("Z", "+00:00")
        )
    except (ValueError, KeyError) as exc:
        raise ValueError("DR-12 replay fetched_at_utc invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != dt.timedelta():
        raise ValueError("DR-12 replay fetched_at_utc must be UTC")
    return manifest


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--replay-dir":
        proof = replay_receipt(Path(sys.argv[2]))
        print(json.dumps({
            "verified": True, "raw_sha256": proof["raw_sha256"],
            "run_id": proof["run_id"], "publish_authorized": False,
        }, sort_keys=True))
        return 0
    if len(sys.argv) != 1:
        print("usage: afir_dr12_quality_watch.py [--replay-dir PATH]", file=sys.stderr)
        return 2
    root = os.environ.get("PARTENER_AFIR_DR12_EVIDENCE_DIR")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not root or not run_id:
        print("DR-12 capture requires a run-scoped evidence destination and GITHUB_RUN_ID", file=sys.stderr)
        return 2
    fetched = transport.fetch(NOTICE_URL, timeout=20)
    if not fetched.get("ok"):
        print("AFIR DR-12 official notice unavailable; preserve LKG, no material admission: "
              + str(fetched.get("error")), file=sys.stderr)
        return 2
    try:
        result = capture(
            fetched, Path(root), run_id=run_id,
            fetched_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        )
    except ValueError as exc:
        print(f"AFIR DR-12 receipt rejected; source-bound review only: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "observation_state": result["observation_state"],
        "raw_sha256": result["raw_sha256"],
        "run_id": result["run_id"],
        "publish_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
