#!/usr/bin/env python3
"""Audit fixer-chain identity for each workflow that mutates MIPE source.

Each chain starts from the same checked-in source bytes. The target is restored
before and after every chain. The receipt records whether Validation, Access
Bridge and Dual Relay are each byte-identical to immutable checked-in source.
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
OUT = ROOT / "partener-eu" / "ops" / "mipe_workflow_chain_equivalence.json"

CLASSIFIER = "partener-eu/ops/fix_mipe_resilient_classifier.py"
RUNTIME = "partener-eu/ops/fix_mipe_resilient_runtime.py"
QUALITY = "partener-eu/ops/fix_mipe_content_quality.py"
FIRST_PARTY = "partener-eu/ops/fix_mipe_first_party_relay.py"
DUAL_RELAY = "partener-eu/ops/fix_mipe_dual_relay.py"

CHAINS = {
    "production_validation": (CLASSIFIER,),
    "access_bridge": (CLASSIFIER, RUNTIME, QUALITY, FIRST_PARTY),
    "dual_relay": (CLASSIFIER, RUNTIME, QUALITY, FIRST_PARTY, DUAL_RELAY),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_chain(name: str, fixers: tuple[str, ...], original: bytes) -> dict:
    TARGET.write_bytes(original)
    before = sha(original)
    results = []
    error = None
    try:
        for rel in fixers:
            completed = subprocess.run(
                [sys.executable, str(ROOT / rel)],
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
        after_bytes = TARGET.read_bytes()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        after_bytes = TARGET.read_bytes()
    finally:
        TARGET.write_bytes(original)

    after = sha(after_bytes)
    all_ran = len(results) == len(fixers)
    all_ok = all_ran and all(r["returnCode"] == 0 for r in results)
    return {
        "chain": name,
        "fixers": list(fixers),
        "beforeSha256": before,
        "afterSha256": after,
        "mutated": before != after,
        "allFixersRan": all_ran,
        "allFixersOk": all_ok,
        "results": results,
        "error": error,
        "status": "PASS" if all_ok and before == after and not error else "FAIL",
    }


def main() -> int:
    original = TARGET.read_bytes()
    before = sha(original)
    chains = [run_chain(name, fixers, original) for name, fixers in CHAINS.items()]
    restored = TARGET.read_bytes() == original
    overall = "PASS" if restored and all(row["status"] == "PASS" for row in chains) else "FAIL"
    payload = {
        "schema": "PARTENER_MIPE_WORKFLOW_CHAIN_EQUIVALENCE_V1",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "target": TARGET.relative_to(ROOT).as_posix(),
        "sourceSha256": before,
        "restorationVerified": restored,
        "chains": chains,
        "status": overall,
        "policy": (
            "Runtime patcher removal is allowed only for a workflow chain whose status is PASS. "
            "A full-chain PASS does not imply subset-chain equivalence."
        ),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Receipt generation itself succeeds; CI enforces payload.status after persisting proof.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
