#!/usr/bin/env python3
"""Regression guard for collision-safe PEO calendar identity migration."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "peo_calendar_ingest.py"
spec = importlib.util.spec_from_file_location("peo_calendar_ingest", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

program = "Program Educație și Ocupare"
title = "Competențe pentru piața muncii"
priority = "P9"

# Identity v1 used only programme+title+priority and could collide. V2 must
# distinguish objective/region/sheet while remaining deterministic.
a = module.stable_id(program, title, priority, "Obiectiv A", "Național", "Calendar PEO")
b = module.stable_id(program, title, priority, "Obiectiv B", "Național", "Calendar PEO")
c = module.stable_id(program, title, priority, "Obiectiv A", "Sud-Vest", "Calendar PEO")
d = module.stable_id(program, title, priority, "Obiectiv A", "Național", "Altă foaie")
assert len({a, b, c, d}) == 4
assert a == module.stable_id(program, title, priority, "Obiectiv A", "Național", "Calendar PEO")
assert module.IDENTITY_SCHEMA_VERSION == 2

# Semantic identity lets a legacy row migrate without manufacturing an addition.
legacy = {
    "id": "legacy-colliding-id",
    "programme": "PEO",
    "programmeRaw": program,
    "title": title,
    "priority": priority,
    "objective": "Obiectiv A",
    "region": "Național",
    "sourceSheet": "Calendar PEO",
}
current = {
    **legacy,
    "id": a,
    "identitySchemaVersion": 2,
}
assert module.identity_tuple(legacy) == module.identity_tuple(current)

# A V2 result set must never retain duplicate stable identities.
assert all(v == 1 for v in Counter([a, b, c, d]).values())
print("PASS PEO calendar identity regression")
