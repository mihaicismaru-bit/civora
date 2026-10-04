#!/usr/bin/env python3
"""Regression: the direct-only MIPE collector must preserve MySMIS pending reconciliation state."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))
SPEC = importlib.util.spec_from_file_location("mipe_direct_only_ingest", INGEST / "mipe_direct_only_ingest.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_pending_checkpoint_is_preserved() -> None:
    pending = {"signature": "a" * 64, "confirmations": 1, "validatedCallCount": 977}
    previous = {"mysmisPendingChange": pending}
    output = {"status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED", "items": [], "runs": []}
    result = module.preserve_mysmis_pending_checkpoint(previous, output)
    assert result["mysmisPendingChange"] == pending
    assert result is output


def test_absent_checkpoint_is_not_invented() -> None:
    output = {}
    result = module.preserve_mysmis_pending_checkpoint({}, output)
    assert "mysmisPendingChange" not in result


def main() -> int:
    test_pending_checkpoint_is_preserved()
    test_absent_checkpoint_is_not_invented()
    print("MIPE MySMIS pending checkpoint regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
