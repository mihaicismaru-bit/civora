#!/usr/bin/env python3
"""Regression guard for low-information HTML in the verified source registry."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "source_registry_probe.py"
spec = importlib.util.spec_from_file_location("source_registry_probe", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def check(raw_size: int, content_type: str, semantic_text: str, expected_ok: bool, expected_issue):
    ok, issue, chars = module.classify_content_quality(raw_size, content_type, semantic_text.encode("utf-8"))
    assert ok is expected_ok, (raw_size, content_type, chars, ok, expected_ok)
    assert issue == expected_issue, (issue, expected_issue)


check(12_000, "text/html", "x" * 101, False, "LOW_INFORMATION_HTML_SHELL")
check(120_000, "text/html; charset=UTF-8", "conținut oficial " * 700, True, None)
check(2_000, "text/html", "pagină scurtă legitimă", True, None)
check(12_000, "application/pdf", "x" * 50, True, None)

old = {
    "semantic_sha256": "shell-hash",
    "semantic_bytes": 101,
    "bytes": 12_000,
}
original_task_dir = module.TASK_DIR
try:
    import tempfile
    import json
    with tempfile.TemporaryDirectory() as td:
        module.TASK_DIR = Path(td)
        (module.TASK_DIR / "SRC-TEST.json").write_text(json.dumps({
            "current_semantic_sha256": "shell-hash",
            "previous_semantic_sha256": "good-hash",
        }), encoding="utf-8")
        assert module.task_baseline_hash("SRC-TEST", old) == "good-hash"
finally:
    module.TASK_DIR = original_task_dir

print("PASS source registry low-information regression")


# Durable reconciliation ledger: a repeated candidate is not a reviewed baseline.
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    original = (module.REGISTRY, module.STATE, module.TASK_DIR,
                module.REVIEWED_BASELINES, module.fetch_source)
    try:
        module.REGISTRY = root / "registry.json"
        module.STATE = root / "state.json"
        module.TASK_DIR = root / "tasks"
        module.REVIEWED_BASELINES = root / "reviewed.json"
        module.TASK_DIR.mkdir()
        source = {"id": "SRC-TEST", "tier": "T1", "class": "official", "url": "https://example.invalid/", "material_fact_use": True}
        module.REGISTRY.write_text(json.dumps({"sources": [source]}), encoding="utf-8")
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        task_path = module.TASK_DIR / "SRC-TEST.json"
        module.STATE.write_text(json.dumps({"sources": [{"id": source["id"], "semantic_sha256": a, "semantic_chars": 500, "bytes": 8000}]}), encoding="utf-8")

        def observe(digest, quality=True, error=False):
            def fetch(_):
                if error:
                    raise OSError("synthetic failed transport")
                return {"ok": True, "semantic_sha256": digest, "semantic_chars": 500,
                        "bytes": 8000, "content_quality_ok": quality}
            module.fetch_source = fetch
            module.main()
            state = json.loads(module.STATE.read_text(encoding="utf-8"))
            row = state["sources"][0]
            assert state["summary"]["resolution_tasks_required"] == int(row["resolution_task_required"])
            return row

        row = observe(b)
        assert row["semantic_hash_changed"] and row["resolution_task_required"]
        task = json.loads(task_path.read_text(encoding="utf-8"))
        first = task["first_observed_at"]
        task["candidate_semantic_sha256"] = b
        task["audit_fixture"] = "preserve"
        task_path.write_text(json.dumps(task), encoding="utf-8")

        row = observe(b)
        assert not row["semantic_hash_changed"] and row["resolution_task_required"]
        assert row["publish_material_fact_update"] is False
        assert row["last_known_semantic_sha256"] == a
        row = observe(c)
        assert row["semantic_hash_changed"] and row["resolution_task_required"]
        task = json.loads(task_path.read_text(encoding="utf-8"))
        assert task["previous_semantic_sha256"] == a
        assert task["current_semantic_sha256"] == task["candidate_semantic_sha256"] == c
        assert task["first_observed_at"] == first and task["audit_fixture"] == "preserve"
        snapshot = task_path.read_bytes()
        for row in (observe(None, error=True), observe(b, quality=False)):
            assert row["resolution_task_required"] and row["publish_material_fact_update"] is False
            assert row["health"] != "PASS" and row["last_known_semantic_sha256"] == a
        assert task_path.read_bytes() == snapshot
        row = observe(a)
        assert row["resolution_task_state"] == "REVERSION_REVIEW_REQUIRED"
        assert row["resolution_task_required"] and task_path.read_bytes() == snapshot

        # Missing durable ledger after a previously pending observation fails closed.
        task_path.unlink()
        row = observe(c)
        assert row["resolution_task_required"] and row["publish_material_fact_update"] is False
        assert row["resolution_task_state"] == "INVALID" and not task_path.exists()
        task_path.write_bytes(snapshot)

        # An inconsistent or malformed task remains visible and is never overwritten.
        task_path.write_text("{", encoding="utf-8")
        row = observe(c)
        assert row["resolution_task_required"] and row["publish_material_fact_update"] is False
        assert row["resolution_task_state"] == "INVALID" and task_path.read_text() == "{"
        for patch in ({"source_id": "wrong"}, {"candidate_semantic_sha256": b},
                      {"previous_semantic_sha256": None}, {"publish_authorized": True}):
            task_path.write_text(json.dumps({**task, **patch}), encoding="utf-8")
            assert module.pending_resolution_task(source["id"]) == ("INVALID", None)

        # Explicitly reviewed exact non-material acceptance is the existing release gate.
        task.update(status="RESOLVED_NON_MATERIAL_CHANGE", resolved_semantic_sha256=c,
                    material_fact_action="NONE", publish_authorized=False)
        task_path.write_text(json.dumps(task), encoding="utf-8")
        assert module.pending_resolution_task(source["id"]) == ("INVALID", None)
        module.REVIEWED_BASELINES.write_text(json.dumps({"baselines": {source["id"]: {
            "accepted_semantic_sha256": c, "decision": "RESOLVED_NON_MATERIAL_CHANGE",
            "material_fact_action": "NONE", "publish_authorized": False}}}), encoding="utf-8")
        row = observe(c)
        assert not row["resolution_task_required"] and not row["semantic_hash_changed"]
        assert row.get("publish_material_fact_update") is not True
        task_path.unlink()
        assert module.pending_resolution_task(source["id"]) == ("NONE", None)
    finally:
        (module.REGISTRY, module.STATE, module.TASK_DIR,
         module.REVIEWED_BASELINES, module.fetch_source) = original

print("PASS durable source-resolution ledger regression")
