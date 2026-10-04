#!/usr/bin/env python3
"""Regression for the MySMIS two-observation checkpoint carried by direct MIPE ingest."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))
SPEC = importlib.util.spec_from_file_location(
    "mipe_direct_only_ingest",
    INGEST / "mipe_direct_only_ingest.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_candidate_is_carried() -> None:
    candidate = {
        "signature": "a" * 64,
        "confirmations": 1,
        "validatedCallCount": 977,
    }
    previous = {"mysmisPendingChange": candidate}
    output = {"status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED", "items": [], "runs": []}
    result = module.carry_mysmis_candidate(previous, output)
    assert result is output
    assert result["mysmisPendingChange"] == candidate


def test_absent_candidate_is_not_created() -> None:
    output = {}
    result = module.carry_mysmis_candidate({}, output)
    assert result is output
    assert "mysmisPendingChange" not in result


def main() -> int:
    test_candidate_is_carried()
    test_absent_candidate_is_not_created()
    print("MIPE MySMIS candidate carry regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
