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
title = "Educație incluzivă de calitate pentru copiii din învățământul primar"
priority = "Educație"
objective = "6.f.1 Intervenții integrate"
region = "LDR+MDR"
sheet = "Apeluri PC 2025"

# Schema v3 distinguishes applicant variants of the same call concept.
a_isj = module.stable_id(program, title, priority, objective, region, sheet, "ISJ/ISMB")
a_min = module.stable_id(program, title, priority, objective, region, sheet, "Ministerul Educației")
assert a_isj != a_min
assert module.IDENTITY_SCHEMA_VERSION == 3

isj = {
    "id": a_isj,
    "programme": "PEO",
    "programmeRaw": program,
    "title": title,
    "priority": priority,
    "objective": objective,
    "region": region,
    "budget": "235349042.47",
    "fund": "FSE+",
    "plannedLaunch": "2025-10-01",
    "plannedClose": "2025-12-31",
    "callType": "competitiv",
    "applicants": "ISJ/ISMB",
    "notes": "",
    "sourceSheet": sheet,
    "sourceRow": 254,
}
ministry = {
    **isj,
    "id": a_min,
    "budget": "13395588",
    "applicants": "Ministerul Educației",
    "sourceRow": 255,
}
assert module.base_identity_tuple(isj) == module.base_identity_tuple(ministry)
assert module.identity_tuple(isj) != module.identity_tuple(ministry)

# Exact duplicate rows for the same applicant variant collapse deterministically.
duplicate = {**isj, "sourceRow": 256}
deduped, dropped = module.dedupe_exact_identities([isj, duplicate])
assert len(deduped) == 1
assert len(dropped) == 1
assert deduped[0]["sourceRow"] == 254

# A conflicting twin for the same applicant variant still fails closed.
conflict = {**duplicate, "budget": "999"}
try:
    module.dedupe_exact_identities([isj, conflict])
except RuntimeError as exc:
    assert "conflicting duplicate PEO stable identity" in str(exc)
else:
    raise AssertionError("conflicting duplicate identity did not fail closed")

# Legacy base identity can still be used only when unique; variant ambiguity is explicit.
base_map, ambiguous = module.build_unique_map([isj, ministry], module.base_identity_tuple)
assert module.base_identity_tuple(isj) not in base_map
assert len(ambiguous) == 1
variant_map, variant_ambiguous = module.build_unique_map([isj, ministry], module.identity_tuple)
assert len(variant_map) == 2
assert not variant_ambiguous

assert all(v == 1 for v in Counter([a_isj, a_min]).values())
source = MODULE_PATH.read_text(encoding="utf-8")
assert "same_source_bytes" in source
assert "if not same_source_bytes:" in source
assert "UNCHANGED_WORKBOOK_SHA_IMPLIES_ZERO_MATERIAL_CHANGES" in source
assert "return 2" in source
print("PASS PEO calendar identity v3 regression")
