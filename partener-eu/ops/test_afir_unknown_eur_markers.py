#!/usr/bin/env python3
"""Regression reproducer for AFIR counter unknown EUR markers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "partener-eu" / "ingest" / "build_afir_live_funds.py"


def load_builder():
    sys.path.insert(0, str(BUILDER.parent))
    spec = importlib.util.spec_from_file_location("partener_afir_live_funds_unknown_markers", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    builder = load_builder()
    for marker in ("-", "–", "—", "N/A", "N/D"):
        assert builder.parse_eur(marker) is None, f"{marker!r} must remain UNKNOWN/null"

    rows = [
        {"sessionAllocationEur": "84794823.50", "submissionCeilingEur": None},
        {"sessionAllocationEur": "84794823.50", "submissionCeilingEur": None},
    ]
    assert builder.decimal_total(rows, "sessionAllocationEur") == "169589647.00"
    assert builder.decimal_total(rows, "submissionCeilingEur") is None

    print("AFIR unknown EUR marker regression PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
