from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def _rows_by_story(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("story_id") or ""): row
        for row in document.get("rows") or document.get("results") or []
        if isinstance(row, dict) and str(row.get("story_id") or "").strip()
    }


def _expected_blocker(state: str) -> str | None:
    if state == "CONSISTENT":
        return None
    if not state:
        return "CROSS_SURFACE_VISUAL_BINDING_UNKNOWN"
    if state == "NOT_READY":
        return "CROSS_SURFACE_VISUAL_BINDING_NOT_READY"
    return "CROSS_SURFACE_VISUAL_BINDING_DIVERGENCE"


def validate_documents(
    candidates: dict[str, Any],
    visual_replay: dict[str, Any],
    gate_report: dict[str, Any],
) -> dict[str, int]:
    assert candidates.get("publication_authority") == "NONE"
    assert candidates.get("acceptance_ready") is False
    assert candidates.get("schema_version") == "1.2"
    assert visual_replay.get("publication_authority") == "NONE"
    assert visual_replay.get("schema_version") == "1.1"
    assert gate_report.get("publication_authority") == "NONE"
    assert gate_report.get("acceptance_ready") is False
    assert gate_report.get("schema_version") == "1.1"

    candidate_rows = _rows_by_story(candidates)
    visual_rows = _rows_by_story(visual_replay)
    gate_rows = _rows_by_story(gate_report)
    story_ids = [str(value) for value in candidates.get("first_ten_candidate_ids") or []]

    assert int(visual_replay.get("candidate_count") or 0) == len(story_ids)
    assert int(gate_report.get("candidate_count") or 0) == len(story_ids)

    consistent = 0
    divergent = 0
    for story_id in story_ids:
        candidate = candidate_rows.get(story_id)
        visual = visual_rows.get(story_id)
        gate = gate_rows.get(story_id)
        assert candidate is not None, f"{story_id}: candidate row missing"
        assert visual is not None, f"{story_id}: visual replay row missing"
        assert gate is not None, f"{story_id}: gate row missing"

        state = str(candidate.get("canonical_site_visual_binding_state") or "").strip()
        assert str(visual.get("canonical_site_visual_binding_state") or "").strip() == state, (
            f"{story_id}: visual replay lost canonical binding state"
        )
        assert str(gate.get("canonical_site_visual_binding_state") or "").strip() == state, (
            f"{story_id}: gate report lost canonical binding state"
        )

        expected_blocker = _expected_blocker(state)
        blockers = list(gate.get("blockers") or [])
        cross_blockers = [
            value for value in blockers if str(value).startswith("CROSS_SURFACE_VISUAL_BINDING_")
        ]
        if expected_blocker is None:
            consistent += 1
            assert not cross_blockers, f"{story_id}: consistent binding received cross-surface blocker"
        else:
            if state not in {"", "NOT_READY"}:
                divergent += 1
            assert expected_blocker in blockers, (
                f"{story_id}: missing fail-closed blocker {expected_blocker} for state {state!r}"
            )
            assert gate.get("truth_state") == "BLOCKED", (
                f"{story_id}: cross-surface mismatch cannot be truth-complete"
            )

        if gate.get("truth_state") == "REPLAY_TRUTH_COMPLETE":
            assert state == "CONSISTENT", (
                f"{story_id}: truth-complete replay requires CONSISTENT canonical visual binding"
            )

    assert int(visual_replay.get("canonical_consistent_count") or 0) == consistent
    assert int(visual_replay.get("cross_surface_divergent_count") or 0) == divergent
    assert int(gate_report.get("truth_complete_count") or 0) <= consistent

    return {
        "candidate_count": len(story_ids),
        "canonical_consistent_count": consistent,
        "cross_surface_divergent_count": divergent,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Core v2 cross-surface visual truth across runtime artifacts")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--visual-readback", required=True)
    parser.add_argument("--gate-report", required=True)
    args = parser.parse_args()
    result = validate_documents(
        _load(Path(args.candidates)),
        _load(Path(args.visual_readback)),
        _load(Path(args.gate_report)),
    )
    print(json.dumps({"status": "PASS_SHADOW", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
