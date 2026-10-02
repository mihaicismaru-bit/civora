#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "partener-eu" / "ingest" / "build_afir_live_funds.py"
sys.path.insert(0, str(BUILDER.parent))
spec = importlib.util.spec_from_file_location("afir_live_funds", BUILDER)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

for token in ("-", "–", "—", "N/A", "N/D"):
    assert module.parse_eur(token) is None
assert module.decimal_total([{"v": "1.00"}, {"v": None}], "v") is None
assert module.decimal_total([{"v": "1.00"}, {"v": "2.00"}], "v") == "3.00"
print("AFIR unknown-value regression PASS")
