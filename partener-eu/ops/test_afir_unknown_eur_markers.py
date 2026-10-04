#!/usr/bin/env python3
"""Regression: AFIR live counter unknown monetary markers remain UNKNOWN/null."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "partener-eu" / "ingest" / "build_afir_live_funds.py"


def load_builder():
    sys.path.insert(0, str(BUILDER.parent))
    spec = importlib.util.spec_from_file_location("partener_afir_live_funds_builder_unknown", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    builder = load_builder()
    for marker in ("-", "–", "—", "N/A", "N/D"):
        assert builder.parse_eur(marker) is None, marker
    assert builder.parse_eur("84.794.823,50 EUR") == "84794823.50"

    rows = builder.parse_rows([[
        "DR-12", "Componenta ZOOTEHNIC", "84.794.823,50 EUR",
        "06.10.2026 09:00:00", "02.12.2026 15:59:59",
        "-", "0", "0", "-"
    ]])
    assert rows[0]["submissionCeilingEur"] is None
    assert rows[0]["availableFundsEur"] is None
    assert rows[0]["submittedPublicValueEur"] == "0.00"
    assert rows[0]["submittedProjectCount"] == 0
    assert builder.decimal_total(rows, "submissionCeilingEur") is None
    assert builder.decimal_total(rows, "availableFundsEur") is None
    assert builder.decimal_total(rows, "sessionAllocationEur") == "84794823.50"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
