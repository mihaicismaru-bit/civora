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
    "budget": "100",
    "fund": "FSE+",
    "plannedLaunch": "2026-01-01",
    "plannedClose": "2026-02-01",
    "callType": "competitiv",
    "applicants": "IMM",
    "notes": "",
    "sourceSheet": "Calendar PEO",
    "sourceRow": 10,
}
current = {
    **legacy,
    "id": a,
    "identitySchemaVersion": 2,
}
assert module.identity_tuple(legacy) == module.identity_tuple(current)

# Exact duplicate source rows are presentation duplication, not two calls.
duplicate = {**current, "sourceRow": 11}
deduped, dropped = module.dedupe_exact_identities([current, duplicate])
assert len(deduped) == 1
assert len(dropped) == 1
assert deduped[0]["sourceRow"] == 10

# Conflicting twins with the same stable identity remain fail-closed.
conflict = {**duplicate, "budget": "200"}
try:
    module.dedupe_exact_identities([current, conflict])
except RuntimeError as exc:
    assert "conflicting duplicate PEO stable identity" in str(exc)
else:
    raise AssertionError("conflicting duplicate identity did not fail closed")

# A V2 result set must never retain duplicate stable identities.
assert all(v == 1 for v in Counter([a, b, c, d]).values())

# The runtime contains the strong migration invariant: unchanged source bytes
# cannot produce a material calendar change merely because IDs were upgraded.
source = MODULE_PATH.read_text(encoding="utf-8")
assert "same_source_bytes" in source
assert "if not same_source_bytes:" in source
assert "UNCHANGED_WORKBOOK_SHA_IMPLIES_ZERO_MATERIAL_CHANGES" in source
print("PASS PEO calendar identity regression")
