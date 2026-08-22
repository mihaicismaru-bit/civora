#!/usr/bin/env python3
"""Prove whether active MIPE source fixers are no-ops on checked-in source.

The fixers are executed in the same order as the dual-relay recovery workflow.
The target source is always restored byte-for-byte before exit. PASS requires
all fixers to exit successfully and the final SHA-256 to equal the initial one.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
OUT = ROOT / "partener-eu" / "ops" / "mipe_fixer_idempotence.json"
FIXERS = (
    "partener-eu/ops/fix_mipe_resilient_classifier.py",
    "partener-eu/ops/fix_mipe_resilient_runtime.py",
    "partener-eu/ops/fix_mipe_content_quality.py",
    "partener-eu/ops/fix_mipe_first_party_relay.py",
    "partener-eu/ops/fix_mipe_dual_relay.py",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run() -> tuple[dict, int]:
    original = TARGET.read_bytes()
    before = sha256(original)
    results: list[dict] = []
    final_bytes = original
    restoration_verified = False
    unexpected_error: str | None = None

    try:
        for rel in FIXERS:
            fixer = ROOT / rel
            if not fixer.exists():
                results.append({
                    "fixer": rel,
                    "returnCode": 127,
                    "stdout": "",
                    "stderr": "fixer file missing",
                })
                break
            completed = subprocess.run(
                [sys.executable, str(fixer)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            results.append({
                "fixer": rel,
                "returnCode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            })
            if completed.returncode != 0:
                break
        final_bytes = TARGET.read_bytes()
    except Exception as exc:  # proof must still restore the target
        unexpected_error = f"{type(exc).__name__}: {exc}"
        try:
            final_bytes = TARGET.read_bytes()
        except Exception:
            final_bytes = b""
    finally:
        TARGET.write_bytes(original)
        restoration_verified = TARGET.read_bytes() == original

    after = sha256(final_bytes)
    all_fixers_ran = len(results) == len(FIXERS)
    all_ok = all_fixers_ran and all(row.get("returnCode") == 0 for row in results)
    mutated = before != after
    status = "PASS" if all_ok and not mutated and restoration_verified and not unexpected_error else "FAIL"

    payload = {
        "schema": "PARTENER_MIPE_FIXER_IDEMPOTENCE_V1",
        "generatedAt": utc_now(),
        "target": TARGET.relative_to(ROOT).as_posix(),
        "beforeSha256": before,
        "afterSha256": after,
        "mutated": mutated,
        "restorationVerified": restoration_verified,
        "allFixersRan": all_fixers_ran,
        "fixerCount": len(FIXERS),
        "results": results,
        "unexpectedError": unexpected_error,
        "status": status,
        "policy": (
            "Runtime fixer removal is permitted only when status=PASS, "
            "beforeSha256=afterSha256, and restorationVerified=true."
        ),
    }
    return payload, 0 if status == "PASS" else 1


def main() -> int:
    payload, code = run()
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
