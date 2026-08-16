#!/usr/bin/env python3
"""Material discovery-health fingerprinting for LOCAL NEWS OS.

Newsrooms poll sources frequently, but a new observation timestamp is not itself a
material state change. This module provides an instance-neutral comparison for
persisting source-health ledgers independently from story publication without
creating a commit on every poll.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def error_category(value: Any) -> str | None:
    """Normalize volatile transport messages into stable, useful categories."""
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if "certificate_verify_failed" in lowered or "certificate verify failed" in lowered:
        return "SSL_CERTIFICATE"
    if any(token in lowered for token in (
        "name or service not known",
        "temporary failure in name resolution",
        "nodename nor servname",
        "no address associated with hostname",
    )):
        return "DNS"
    if "network is unreachable" in lowered:
        return "NETWORK_UNREACHABLE"
    if "connection refused" in lowered:
        return "CONNECTION_REFUSED"
    if "timed out" in lowered or "timeout" in lowered:
        return "TIMEOUT"
    http = re.search(r"http(?:error| error)?\s*[: ]?\s*(\d{3})", lowered)
    if http:
        return f"HTTP_{http.group(1)}"
    prefix = text.split(":", 1)[0].strip()
    return prefix or "UNKNOWN_ERROR"


def material_signature(doc: dict[str, Any]) -> dict[str, Any]:
    """Return health fields that should create durable state when they change.

    Deliberately excludes observation timestamps and volatile error-message text.
    Source rows are sorted by id so harmless execution-order differences do not
    create churn.
    """
    rows: list[dict[str, Any]] = []
    for row in doc.get("sources", []):
        if not isinstance(row, dict):
            continue
        rows.append({
            "source_id": row.get("source_id"),
            "listing_ok": bool(row.get("listing_ok")),
            "links_examined": row.get("links_examined"),
            "article_failures": row.get("article_failures"),
            "facts": row.get("facts"),
            "error_category": error_category(row.get("error")),
        })
    rows.sort(key=lambda row: str(row.get("source_id") or ""))
    return {
        "schema_version": doc.get("schema_version"),
        "execution_mode": doc.get("execution_mode"),
        "instance_id": doc.get("instance_id"),
        "source_contract": doc.get("source_contract"),
        "publication_date_guard": doc.get("publication_date_guard"),
        "sources_total": doc.get("sources_total"),
        "sources_ok": doc.get("sources_ok"),
        "facts_admitted": doc.get("facts_admitted"),
        "sources": rows,
    }


def materially_changed(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    return material_signature(current) != material_signature(previous)


def self_test() -> int:
    baseline = {
        "schema_version": "1.2",
        "observed_at": "2026-08-16T10:00:00+03:00",
        "execution_mode": "bounded_parallel",
        "instance_id": "fixture",
        "source_contract": "SOURCE_PACK_V1",
        "publication_date_guard": "STRICT",
        "sources_total": 2,
        "sources_ok": 1,
        "facts_admitted": 0,
        "sources": [
            {"source_id": "b", "listing_ok": False, "facts": 0,
             "error": "URLError: <urlopen error [Errno -2] Name or service not known>"},
            {"source_id": "a", "listing_ok": True, "links_examined": 4,
             "article_failures": 0, "facts": 0},
        ],
    }
    timestamp_only = json.loads(json.dumps(baseline))
    timestamp_only["observed_at"] = "2026-08-16T10:05:00+03:00"
    timestamp_only["sources"].reverse()
    timestamp_only["sources"][0 if timestamp_only["sources"][0]["source_id"] == "b" else 1]["error"] = (
        "URLError: <urlopen error [Errno -3] Temporary failure in name resolution>"
    )
    assert not materially_changed(timestamp_only, baseline)

    recovered = json.loads(json.dumps(baseline))
    recovered["sources_ok"] = 2
    recovered["sources"][0]["listing_ok"] = True
    recovered["sources"][0].pop("error", None)
    assert materially_changed(recovered, baseline)

    different_failure = json.loads(json.dumps(baseline))
    different_failure["sources"][0]["error"] = (
        "URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"
    )
    assert materially_changed(different_failure, baseline)

    schema_upgrade = json.loads(json.dumps(baseline))
    schema_upgrade["schema_version"] = "1.3"
    assert materially_changed(schema_upgrade, baseline)
    assert error_category("HTTP Error 503: unavailable") == "HTTP_503"
    assert error_category("socket timeout") == "TIMEOUT"
    print("LOCAL NEWS OS material discovery-health fingerprint self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current")
    parser.add_argument("--previous")
    parser.add_argument("--changed-exit-code", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.current or not args.previous:
        parser.error("--current and --previous are required")

    current = load_json(Path(args.current))
    previous = load_json(Path(args.previous))
    changed = materially_changed(current, previous)
    print(json.dumps({
        "changed": changed,
        "current": material_signature(current),
        "previous": material_signature(previous),
    }, ensure_ascii=False))
    return args.changed_exit_code if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
