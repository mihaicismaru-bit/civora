#!/usr/bin/env python3
"""Deterministic recovery and atomic-state regression for P10."""
import json
import pathlib
import tempfile

import p10_validate as validation

with tempfile.TemporaryDirectory() as d:
    root = pathlib.Path(d)
    state_path = root / "source_state.json"
    checkpoint_path = root / "source_state.checkpoint.json"
    expected = {
        "schema_version": 3,
        "sources": {"A": {"semantic_sha256": "abc", "health": "PASS"}},
        "last_run": "2026-08-12T00:00:00Z",
    }

    # Verify durable atomic write/read first.
    validation.atomic_json(checkpoint_path, expected)
    assert json.loads(checkpoint_path.read_text(encoding="utf-8")) == expected

    # Simulate an interrupted/corrupted primary state and prove deterministic
    # recovery from the durable checkpoint without touching production files.
    state_path.write_text("{corrupted", encoding="utf-8")
    original_state = validation.STATE
    original_checkpoint = validation.CHECKPOINT
    try:
        validation.STATE = state_path
        validation.CHECKPOINT = checkpoint_path
        recovered, used_checkpoint = validation.recover_state()
    finally:
        validation.STATE = original_state
        validation.CHECKPOINT = original_checkpoint

    assert used_checkpoint is True
    assert recovered == expected
    assert json.loads(state_path.read_text(encoding="utf-8")) == expected

checks = validation.static_frontend_checks()
assert all(x["pass"] for x in checks), checks
print(json.dumps({
    "atomic_state_write": "PASS",
    "corrupt_state_checkpoint_recovery": "PASS",
    "frontend_static_checks": f"{sum(x['pass'] for x in checks)}/{len(checks)} PASS",
}, indent=2))
