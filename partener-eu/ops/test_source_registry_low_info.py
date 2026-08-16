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

# A pre-fix polluted row must recover the authoritative baseline from the
# resolution task rather than treating the shell hash as canonical forever.
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
