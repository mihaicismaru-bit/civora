#!/usr/bin/env python3
"""Fail-closed proof that the newly deployed PARTENER.EU projection is publicly readable.

The proof compares the public static manifest with the exact local manifest used for
this Pages deployment and verifies the three decision-critical listing routes expose
the expected number of dossier cards. It never alters canonical funding data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://partener.eu/"
DEFAULT_MANIFEST = "partener-eu/web/static-public-manifest.json"
DEFAULT_OUTPUT = "/tmp/partener-pages-readback.json"
CARD_RE = re.compile(r"\bdata-dossier-id\s*=\s*[\"']", re.IGNORECASE)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cache_busted(url: str, token: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("partener_readback", token))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def fetch_bytes(url: str, *, timeout: float, token: str) -> tuple[int, bytes, str]:
    target = cache_busted(url, token)
    req = urllib.request.Request(
        target,
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "User-Agent": "PARTENER.EU-Pages-Public-Readback/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return int(getattr(response, "status", 200)), response.read(), response.geturl()


def parse_json_bytes(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))


def count_cards(raw: bytes) -> int:
    return len(CARD_RE.findall(raw.decode("utf-8", "replace")))


def compare_manifest(expected: dict[str, Any], observed: dict[str, Any]) -> tuple[bool, list[str]]:
    if expected == observed:
        return True, []
    keys = sorted(set(expected) | set(observed))
    mismatches = [key for key in keys if expected.get(key) != observed.get(key)]
    return False, mismatches


def self_test() -> int:
    sample = {
        "schemaVersion": 1,
        "generatedAt": "2026-09-24T10:22:01Z",
        "currentOpen": 11,
        "prepare": 25,
        "consultations": 5,
        "policy": {"materialFactsInvented": False},
    }
    same = json.loads(json.dumps(sample))
    ok, mismatches = compare_manifest(sample, same)
    assert ok and not mismatches
    changed = json.loads(json.dumps(sample))
    changed["prepare"] = 24
    ok, mismatches = compare_manifest(sample, changed)
    assert not ok and mismatches == ["prepare"]
    assert count_cards(b'<article data-dossier-id="a"></article><div data-dossier-id=\'b\'></div>') == 2
    assert count_cards(b"<article></article>") == 0
    busted = cache_busted("https://partener.eu/consultari/?x=1", "abc")
    assert "x=1" in busted and "partener_readback=abc" in busted
    print("PASS public deploy readback proof self-test")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.attempts < 1:
        parser.error("--attempts must be >= 1")

    manifest_path = pathlib.Path(args.manifest)
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_counts = {
        "finantari/deschise/": int(expected.get("currentOpen", -1)),
        "finantari/in-pregatire/": int(expected.get("prepare", -1)),
        "consultari/": int(expected.get("consultations", -1)),
    }
    if any(value < 0 for value in required_counts.values()):
        raise SystemExit("Manifest missing one of currentOpen/prepare/consultations")

    base_url = args.base_url.rstrip("/") + "/"
    manifest_url = urllib.parse.urljoin(base_url, "static-public-manifest.json")
    expected_hash = sha256_bytes(canonical_bytes(expected))
    attempts_log: list[dict[str, Any]] = []
    final_observed: dict[str, Any] | None = None
    final_routes: dict[str, Any] = {}
    final_hash: str | None = None
    final_mismatches: list[str] = []
    passed = False

    for attempt in range(1, args.attempts + 1):
        token = f"{expected.get('generatedAt', 'unknown')}-{attempt}-{int(time.time())}"
        record: dict[str, Any] = {"attempt": attempt, "errors": []}
        try:
            code, raw, resolved = fetch_bytes(manifest_url, timeout=args.timeout_seconds, token=token)
            observed = parse_json_bytes(raw)
            if not isinstance(observed, dict):
                raise ValueError("public manifest is not a JSON object")
            same, mismatches = compare_manifest(expected, observed)
            observed_hash = sha256_bytes(canonical_bytes(observed))
            record["manifest"] = {
                "http_status": code,
                "resolved_url": resolved,
                "matches": same,
                "mismatch_keys": mismatches,
                "sha256": observed_hash,
            }
            final_observed = observed
            final_hash = observed_hash
            final_mismatches = mismatches

            route_results: dict[str, Any] = {}
            routes_ok = True
            for route, expected_count in required_counts.items():
                route_url = urllib.parse.urljoin(base_url, route)
                r_code, r_raw, r_resolved = fetch_bytes(route_url, timeout=args.timeout_seconds, token=token)
                observed_count = count_cards(r_raw)
                route_ok = r_code == 200 and observed_count == expected_count
                route_results[route] = {
                    "http_status": r_code,
                    "resolved_url": r_resolved,
                    "expected_cards": expected_count,
                    "observed_cards": observed_count,
                    "matches": route_ok,
                }
                routes_ok = routes_ok and route_ok
            record["routes"] = route_results
            final_routes = route_results
            passed = same and routes_ok
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
            record["errors"].append(f"{type(exc).__name__}: {exc}")
            passed = False
        attempts_log.append(record)
        if passed:
            break
        if attempt < args.attempts:
            time.sleep(args.delay_seconds)

    result = {
        "status": "PASS" if passed else "FAIL",
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": base_url,
        "expected_manifest_sha256": expected_hash,
        "observed_manifest_sha256": final_hash,
        "manifest_matches": bool(final_observed is not None and not final_mismatches and final_hash == expected_hash),
        "manifest_mismatch_keys": final_mismatches,
        "expected_counts": {
            "currentOpen": expected.get("currentOpen"),
            "prepare": expected.get("prepare"),
            "consultations": expected.get("consultations"),
        },
        "observed_counts": {
            route: details.get("observed_cards") for route, details in final_routes.items()
        },
        "routes": final_routes,
        "attempts_used": len(attempts_log),
        "attempts": attempts_log,
        "fail_closed": True,
    }
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "attempts"}, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
