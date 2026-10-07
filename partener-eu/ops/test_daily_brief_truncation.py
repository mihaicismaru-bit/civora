#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "partener-eu" / "ingest" / "build_daily_brief.py"
spec = importlib.util.spec_from_file_location("partener_daily_brief", MODULE)
assert spec and spec.loader
brief = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brief)

title = "Sprijinirea investițiilor în dezvoltarea instalațiilor autonome (stand-alone) de stocare în baterii"
out = brief.truncate_at_word(title, 65)
assert out.endswith("…")
assert len(out) <= 66
assert not out.endswith("(…")
assert out in {"Sprijinirea investițiilor în dezvoltarea instalațiilor autonome…", "Sprijinirea investițiilor în dezvoltarea instalațiilor…"}
print("PASS daily brief word-boundary truncation")
