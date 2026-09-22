#!/usr/bin/env python3
"""Regression guards for source-resolution task lifecycle and reviewed baselines."""
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
FUTURE = "c" * 64
OBSERVED_AT = "2026-09-22T10:30:00Z"

original_task_dir = module.TASK_DIR
original_reviewed_baselines = module.REVIEWED_BASELINES
try:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        module.TASK_DIR = root / "tasks"
        module.TASK_DIR.mkdir(parents=True)
        module.REVIEWED_BASELINES = root / "accepted-source-baselines.json"
        path = module.TASK_DIR / "SRC-TEST.json"

        # Existing behavior: a stale OPEN candidate can close only when the
        # source returns exactly to its previous canonical baseline.
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

        # New behavior: a persistent semantic change can become the comparison
        # baseline only after an explicit non-material review. The ledger and
        # task must agree, and neither may authorize material fact publication.
        path.write_text(json.dumps({
            "schema_version": "1.3",
            "source_id": "SRC-TEST",
            "status": "RESOLVED_NON_MATERIAL_CHANGE",
            "previous_semantic_sha256": BASELINE,
            "current_semantic_sha256": CANDIDATE,
            "resolved_semantic_sha256": CANDIDATE,
            "material_fact_autoupdate_allowed": False,
            "automatic_material_fact_update_allowed": False,
            "material_fact_action": "NONE",
            "publish_authorized": False,
        }), encoding="utf-8")
        module.REVIEWED_BASELINES.write_text(json.dumps({
            "schema_version": "1.0",
            "baselines": {
                "SRC-TEST": {
                    "accepted_semantic_sha256": CANDIDATE,
                    "previous_semantic_sha256": BASELINE,
                    "decision": "RESOLVED_NON_MATERIAL_CHANGE",
                    "material_fact_action": "NONE",
                    "publish_authorized": False,
                }
            },
        }), encoding="utf-8")

        old = {
            "semantic_sha256": BASELINE,
            "semantic_chars": 1000,
            "bytes": 10000,
        }
        assert module.reviewed_baseline_hash("SRC-TEST") == CANDIDATE
        assert module.task_baseline_hash("SRC-TEST", old) == CANDIDATE

        # A later new semantic change must still reopen fail-closed against the
        # reviewed candidate, rather than being hidden by the accepted baseline.
        assert module.task_baseline_hash("SRC-TEST", old) != FUTURE
        module.write_resolution_task(SOURCE, CANDIDATE, FUTURE, OBSERVED_AT)
        reopened = json.loads(path.read_text(encoding="utf-8"))
        assert reopened["status"] == "OPEN"
        assert reopened["previous_semantic_sha256"] == CANDIDATE
        assert reopened["current_semantic_sha256"] == FUTURE
        assert reopened["material_fact_autoupdate_allowed"] is False

        # Any authorization mismatch invalidates the reviewed baseline.
        path.write_text(json.dumps({
            "status": "RESOLVED_NON_MATERIAL_CHANGE",
            "resolved_semantic_sha256": CANDIDATE,
            "material_fact_autoupdate_allowed": False,
            "material_fact_action": "NONE",
            "publish_authorized": True,
        }), encoding="utf-8")
        assert module.reviewed_baseline_hash("SRC-TEST") is None
        assert module.task_baseline_hash("SRC-TEST", old) == BASELINE
finally:
    module.TASK_DIR = original_task_dir
    module.REVIEWED_BASELINES = original_reviewed_baselines

print("PASS source registry task lifecycle regression")
