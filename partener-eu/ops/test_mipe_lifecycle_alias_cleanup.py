#!/usr/bin/env python3
"""Regression guard for retiring the applied lifecycle alias fixer."""
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXER = ROOT / "partener-eu" / "ops" / "fix_call_lifecycle_event_aliases.py"
LIFECYCLE = ROOT / "partener-eu" / "ingest" / "build_call_lifecycle.py"
FINAL_CLEANUP_WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-mipe-final-cleanup-qa.yml"

EXPECTED_EVENT_STAGE = {
    "DEADLINE_EXTENDED": "OPEN",
    "EVALUATION_UPDATE": "EVALUATION",
    "CONTRACTING_UPDATE": "CONTRACTING",
}


def main() -> int:
    assert not FIXER.exists(), f"retired one-shot fixer reappeared: {FIXER.relative_to(ROOT)}"

    namespace = runpy.run_path(str(LIFECYCLE))
    event_stage = namespace.get("EVENT_STAGE")
    assert isinstance(event_stage, dict), "build_call_lifecycle.py no longer exposes EVENT_STAGE"
    for event, expected_stage in EXPECTED_EVENT_STAGE.items():
        actual_stage = event_stage.get(event)
        assert actual_stage == expected_stage, (event, actual_stage, expected_stage)

    workflow = FINAL_CLEANUP_WORKFLOW.read_text(encoding="utf-8")
    assert "fix_call_lifecycle_event_aliases.py" not in workflow, (
        "final cleanup replay still invokes the retired lifecycle alias fixer"
    )
    assert "test_mipe_lifecycle_alias_cleanup.py" in workflow, (
        "lifecycle alias cleanup regression is not wired into the final cleanup gate"
    )

    print("PARTENER.EU lifecycle alias cleanup regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
