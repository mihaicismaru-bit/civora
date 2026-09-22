#!/usr/bin/env python3
"""Regression guard for preserving reviewed resolution metadata across P10 refreshes."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ops" / "p10_resolution_tasks.py"
spec = importlib.util.spec_from_file_location("p10_resolution_tasks", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

SOURCE_ID = "SRC-TEST"
BASELINE = "a" * 64
REVIEWED = "b" * 64
FUTURE = "c" * 64

original_tasks = module.TASKS
try:
    with tempfile.TemporaryDirectory() as td:
        module.TASKS = Path(td)
        path = module.TASKS / f"{SOURCE_ID}.json"
        path.write_text(json.dumps({
            "schema_version": "1.3",
            "source_id": SOURCE_ID,
            "status": "RESOLVED_NON_MATERIAL_CHANGE",
            "previous_semantic_sha256": BASELINE,
            "candidate_semantic_sha256": REVIEWED,
            "current_semantic_sha256": REVIEWED,
            "resolved_semantic_sha256": REVIEWED,
            "resolved_at": "2026-09-22T17:25:00Z",
            "resolution_reason": "Reviewed as non-material.",
            "material_fact_autoupdate_allowed": False,
            "automatic_material_fact_update_allowed": False,
            "material_fact_action": "NONE",
            "publish_authorized": False,
            "evidence_urls": ["https://example.invalid/"],
        }), encoding="utf-8")

        # Re-materializing the exact reviewed candidate must not erase the audit
        # fields or reopen the task.
        module.write_task(SOURCE_ID, {
            "source_url": "https://example.invalid/",
            "candidate_semantic_sha256": REVIEWED,
            "current_semantic_sha256": REVIEWED,
        })
        same = json.loads(path.read_text(encoding="utf-8"))
        assert same["status"] == "RESOLVED_NON_MATERIAL_CHANGE"
        assert same["resolved_semantic_sha256"] == REVIEWED
        assert same["resolution_reason"] == "Reviewed as non-material."
        assert same["material_fact_action"] == "NONE"
        assert same["publish_authorized"] is False
        assert same["material_fact_autoupdate_allowed"] is False
        assert same["automatic_material_fact_update_allowed"] is False

        # A genuinely new candidate must reopen fail-closed and remove the prior
        # resolution metadata so it cannot be mistaken for a reviewed state.
        module.write_task(SOURCE_ID, {
            "source_url": "https://example.invalid/",
            "candidate_semantic_sha256": FUTURE,
            "current_semantic_sha256": FUTURE,
        })
        future = json.loads(path.read_text(encoding="utf-8"))
        assert future["status"] == "OPEN_MANUAL_EVIDENCE_RESOLUTION"
        assert future["candidate_semantic_sha256"] == FUTURE
        assert future["current_semantic_sha256"] == FUTURE
        assert "resolved_semantic_sha256" not in future
        assert "resolved_at" not in future
        assert "resolution_reason" not in future
        assert "material_fact_action" not in future
        assert "publish_authorized" not in future
        assert future["material_fact_autoupdate_allowed"] is False
        assert future["automatic_material_fact_update_allowed"] is False
finally:
    module.TASKS = original_tasks

print("PASS P10 reviewed resolution metadata regression")
