#!/usr/bin/env python3
"""Regression guard for stale source-resolution tasks that revert to baseline."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "source_registry_probe.py"
spec = importlib.util.spec_from_file_location("source_registry_probe", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

SOURCE = {"id": "SRC-TEST", "tier": "T1", "url": "https://example.invalid/"}
BASELINE = "a" * 64
CANDIDATE = "b" * 64
OBSERVED_AT = "2026-09-22T10:30:00Z"

original_task_dir = module.TASK_DIR
try:
    with tempfile.TemporaryDirectory() as td:
        module.TASK_DIR = Path(td)
        path = module.TASK_DIR / "SRC-TEST.json"
        path.write_text(json.dumps({
            "schema_version": "1.2",
            "source_id": "SRC-TEST",
            "status": "OPEN",
            "previous_semantic_sha256": BASELINE,
            "current_semantic_sha256": CANDIDATE,
            "material_fact_autoupdate_allowed": False,
        }), encoding="utf-8")

        assert module.close_reverted_resolution_task(
            SOURCE, BASELINE, BASELINE, OBSERVED_AT
        ) is True
        closed = json.loads(path.read_text(encoding="utf-8"))
        assert closed["status"] == "RESOLVED_REVERTED_TO_BASELINE"
        assert closed["previous_semantic_sha256"] == BASELINE
        assert closed["current_semantic_sha256"] == CANDIDATE
        assert closed["resolved_at"] == OBSERVED_AT
        assert closed["material_fact_autoupdate_allowed"] is False
        assert closed["automatic_material_fact_update_allowed"] is False
        assert closed["material_fact_action"] == "NONE"
        assert closed["publish_authorized"] is False

        path.write_text(json.dumps({
            "status": "OPEN",
            "previous_semantic_sha256": BASELINE,
            "current_semantic_sha256": CANDIDATE,
        }), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        assert module.close_reverted_resolution_task(
            SOURCE, BASELINE, CANDIDATE, OBSERVED_AT
        ) is False
        assert path.read_text(encoding="utf-8") == before

        path.write_text(json.dumps({
            "status": "RESOLVED_REVERTED_TO_BASELINE",
            "previous_semantic_sha256": BASELINE,
            "current_semantic_sha256": CANDIDATE,
        }), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        assert module.close_reverted_resolution_task(
            SOURCE, BASELINE, BASELINE, OBSERVED_AT
        ) is False
        assert path.read_text(encoding="utf-8") == before
finally:
    module.TASK_DIR = original_task_dir

print("PASS source registry reverted-task regression")
