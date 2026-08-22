#!/usr/bin/env python3
"""Materialize the currently active MIPE runtime fixer state into source.

This is a development migration helper, not a runtime ingestion component.
It runs the same active fixer chain used by recovery workflows and records the
source hash transition. The caller is responsible for tests before committing
the resulting source file.
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
OUT = ROOT / "partener-eu" / "ops" / "mipe_fixer_materialization.json"
FIXERS = (
    "partener-eu/ops/fix_mipe_resilient_classifier.py",
    "partener-eu/ops/fix_mipe_resilient_runtime.py",
    "partener-eu/ops/fix_mipe_content_quality.py",
    "partener-eu/ops/fix_mipe_first_party_relay.py",
    "partener-eu/ops/fix_mipe_dual_relay.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    before = digest(TARGET)
    results = []
    for rel in FIXERS:
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

    after = digest(TARGET)
    all_ok = len(results) == len(FIXERS) and all(r["returnCode"] == 0 for r in results)
    payload = {
        "schema": "PARTENER_MIPE_FIXER_MATERIALIZATION_V1",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "target": TARGET.relative_to(ROOT).as_posix(),
        "beforeSha256": before,
        "afterSha256": after,
        "changed": before != after,
        "allFixersRan": len(results) == len(FIXERS),
        "results": results,
        "status": "PASS" if all_ok else "FAIL",
        "policy": "Commit target only after syntax and MIPE regression tests pass.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
