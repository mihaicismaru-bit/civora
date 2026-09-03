#!/usr/bin/env python3
"""Strict-TLS curl transport wrapper for the RO-BG Call 6 exact adapter.

The official programme currently presents an incomplete TLS chain to Python's
urllib/OpenSSL path on GitHub-hosted runners. This wrapper does not disable TLS
verification: it uses the runner's curl trust stack with HTTPS-only redirects
and feeds the resulting bytes into the same exact semantic parser/reconciler.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import tempfile
from typing import Any

from interreg_ro_bg_call6_exact import collect, load_registry, reconcile, write_outputs


def curl_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="partener-robg-call6-") as tmp:
        body = pathlib.Path(tmp) / "body.bin"
        command = [
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--max-time", str(int(timeout)), "--proto", "=https", "--tlsv1.2",
            "--user-agent", "Mozilla/5.0 (compatible; PARTENER.EU/1.0; +https://partener.eu)",
            "--header", "Accept: text/html,application/xhtml+xml",
            "--header", "Accept-Language: en",
            "--output", str(body),
            "--write-out", "%{http_code}\n%{content_type}\n%{url_effective}",
            url,
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout + 10)
        if result.returncode != 0:
            raise RuntimeError(f"curl strict-TLS transport failed ({result.returncode}): {result.stderr.strip()}")
        lines = result.stdout.splitlines()
        if len(lines) < 3:
            raise RuntimeError("curl strict-TLS transport returned incomplete metadata")
        raw = body.read_bytes()
        if len(raw) > 5_000_000:
            raise ValueError("RO-BG exact source exceeds 5 MB")
        return raw, {
            "requested_url": url,
            "final_url": lines[-1].strip(),
            "http_status": int(lines[-3].strip()),
            "content_type": lines[-2].strip(),
            "transport": "CURL_STRICT_TLS",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--previous")
    args = parser.parse_args()
    registry = load_registry(args.registry)
    evidence, raws = collect(registry=registry, run_id=args.run_id, fetcher=curl_fetch)
    for row in evidence.get("sources") or []:
        row["transport"] = "CURL_STRICT_TLS"
    previous = json.loads(pathlib.Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    reconciliation = reconcile(evidence, previous)
    write_outputs(pathlib.Path(args.output_dir), evidence, reconciliation, raws)
    print(json.dumps({
        "transport": "CURL_STRICT_TLS",
        "source_health_state": evidence["source_health_state"],
        "official_call_identifier": evidence["official_call_identifier"],
        "candidate_state": evidence["candidate_state"],
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "closed_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
