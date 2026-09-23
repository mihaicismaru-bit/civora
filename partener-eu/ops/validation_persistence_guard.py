#!/usr/bin/env python3
"""Classify main-branch drift before a PARTENER.EU validation run persists evidence.

The production validation job generates derived evidence from the checkout it started
with. If canonical PARTENER.EU inputs advance while that run is executing, rebasing a
now-stale generated commit on top of the newer main can re-introduce old readiness or
resolution-task counts. This guard distinguishes relevant PARTENER.EU drift from
unrelated repository activity so stale evidence is never pushed over newer canonical
state.

Exit codes:
  0  only unrelated/generated-evidence drift; rebasing the validation commit is safe
 10  canonical PARTENER.EU/workflow drift exists; do not push this validation commit
  2  invalid input
"""

from __future__ import annotations

import json
import sys
from pathlib import PurePosixPath


SAFE_GENERATED_PREFIXES = (
    "partener-eu/validation/",
    "partener-eu/deployment/",
)
SAFE_GENERATED_FILES = {
    "partener-eu/P10_ACCEPTANCE.json",
}


def normalize_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return str(PurePosixPath(value)) if value else ""


def is_relevant_partener_drift(path: str) -> bool:
    path = normalize_path(path)
    if not path or path == ".":
        return False

    if path in SAFE_GENERATED_FILES:
        return False
    if any(path.startswith(prefix) for prefix in SAFE_GENERATED_PREFIXES):
        return False

    if path.startswith("partener-eu/"):
        return True

    if path == ".github/workflows/partener-edge-local.yml":
        return True
    if path.startswith(".github/workflows/partener-eu-") and path.endswith((".yml", ".yaml")):
        return True

    return False


def classify(paths: list[str]) -> dict[str, object]:
    normalized = [normalize_path(path) for path in paths]
    normalized = [path for path in normalized if path and path != "."]
    relevant = [path for path in normalized if is_relevant_partener_drift(path)]
    return {
        "status": "RELEVANT_PARTENER_DRIFT" if relevant else "SAFE_TO_REBASE",
        "pathCount": len(normalized),
        "relevantCount": len(relevant),
        "relevantPaths": relevant,
    }


def main() -> int:
    paths = [line for line in sys.stdin.read().splitlines() if line.strip()]
    if not paths:
        print(json.dumps({"status": "SAFE_TO_REBASE", "pathCount": 0, "relevantCount": 0, "relevantPaths": []}, sort_keys=True))
        return 0

    result = classify(paths)
    print(json.dumps(result, sort_keys=True))
    return 10 if result["relevantCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
