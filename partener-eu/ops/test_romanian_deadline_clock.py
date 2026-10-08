#!/usr/bin/env python3
"""Regression checks for Romanian funding deadline timezone and hour."""
from __future__ import annotations
import importlib.util
from pathlib import Path

module_path = Path(__file__).with_name("build_public_static_pages.py")
spec = importlib.util.spec_from_file_location("partener_deadlines", module_path)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

cases = (
    ("28 martie 2026, 16:00", "2026-03-28T14:00:00+00:00"),
    ("29 martie 2026, 16:00", "2026-03-29T13:00:00+00:00"),
    ("24 octombrie 2026, 16:00", "2026-10-24T13:00:00+00:00"),
    ("25 octombrie 2026, 16:00", "2026-10-25T14:00:00+00:00"),
    ("31 octombrie 2026, 16:00", "2026-10-31T14:00:00+00:00"),
    ("2 decembrie 2026, 16:00", "2026-12-02T14:00:00+00:00"),
)
for value, expected in cases:
    actual = module.parse_date(value)
    assert actual and actual.isoformat() == expected, (value, actual, expected)
print("PASS: Europe/Bucharest deadline clock and hour")
