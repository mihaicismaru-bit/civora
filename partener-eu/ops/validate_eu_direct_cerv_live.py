#!/usr/bin/env python3
"""Validate live CERV evidence remains bounded, exact-current, and non-authorizing.

This validator is intentionally read-only. It validates the programme/programming watch,
structured discovery, omission-safe handoff, exact F&T evidence and reconciliation
produced by the canonical PARTENER.EU F&T workflow. Previous exact evidence may be
used only when it was already restored and the handoff proves same identity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eu_direct_cerv_programme_watch import validate_receipt as validate_programme
from eu_direct_cerv_ft_discovery import validate_receipt as validate_discovery
from eu_direct_cerv_ft_handoff import validate as validate_handoff
from eu_direct_cerv_ft_exact import validate_evidence
from eu_direct_cerv_ft_reconcile import validate_receipt as validate_reconciliation


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path, *, previous_available: bool, previous_run_id: str | None) -> dict[str, Any]:
    cerv_root = root / "cerv"
    programme = load_json(cerv_root / "cerv-programme-watch.json")
    discovery = load_json(cerv_root / "ft-discovery" / "ft-cerv-discovery.json")
    handoff = load_json(cerv_root / "ft-discovery" / "ft-cerv-handoff.json")

    validate_programme(programme)
    validate_discovery(discovery)
    validate_handoff(handoff)

    assert programme["source_health"] == "HEALTHY"
    assert programme["market_intelligence_only"] is True
    assert programme["open_call_authorized"] is False
    assert programme["deadline_authorized"] is False
    assert programme["budget_authorized"] is False
    assert programme["eligibility_authorized"] is False
    assert programme["publish_authorized"] is False
    assert programme["distribution_authorized"] is False
    assert programme["call_alert_authorized"] is False
    assert programme["publication_effect"] == "NONE"
    assert set(x["observation_state"] for x in programme["programming_observations"]) <= {
        "PROGRAMMING",
        "PLANNED",
        "CONSULTATION",
        "PROPOSAL",
    }

    assert discovery["market_intelligence_only"] is True
    assert discovery["bounded_discovery_absence_is_material_fact"] is False
    assert discovery["closure_inference_authorized"] is False
    assert discovery["open_call_authorized"] is False

    assert handoff["closure_inference_authorized"] is False
    assert handoff["open_call_authorized"] is False
    assert handoff["publish_authorized"] is False
    assert handoff["distribution_authorized"] is False
    assert handoff["call_alert_authorized"] is False

    exact_summary: dict[str, Any] | None = None
    previous_same_identity = bool(handoff.get("previous_same_identity"))
    if handoff["exact_recheck_required"]:
        exact = load_json(cerv_root / "ft-exact" / "ft-cerv-exact-evidence.json")
        reconciliation = load_json(cerv_root / "ft-exact" / "ft-cerv-reconciliation.json")
        previous = None
        if previous_available and previous_same_identity:
            previous = load_json(root / "history" / "previous" / "cerv-exact" / "ft-cerv-exact-evidence.json")
            validate_evidence(previous)

        validate_evidence(exact)
        validate_reconciliation(reconciliation, current=exact, previous=previous)
        assert exact["reference"] == handoff["target_reference"]
        assert exact["authority_url_verified"] is True
        assert exact["open_call_authorized"] is False
        assert exact["deadline_authorized"] is False
        assert exact["budget_authorized"] is False
        assert exact["eligibility_authorized"] is False

        if previous is None:
            assert reconciliation["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
        else:
            assert reconciliation["reconciliation_state"] in {
                "NO_CHANGE",
                "CERV_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            }

        exact_summary = {
            "reference": exact["reference"],
            "candidate_state": exact["candidate_state"],
            "status_label": exact["status_label"],
            "authority_url_verified": exact["authority_url_verified"],
            "reconciliation_state": reconciliation["reconciliation_state"],
            "semantic_change_count": reconciliation["semantic_change_count"],
            "previous_same_identity": previous_same_identity,
            "material_admission_ready_for_downstream_review": reconciliation[
                "material_admission_ready_for_downstream_review"
            ],
        }
    else:
        assert handoff["target_reference"] is None
        assert previous_same_identity is False

    return {
        "programme_fit": programme["programme_fit_evidence"]["facts"]["fit_state"],
        "programming_states": [x["observation_state"] for x in programme["programming_observations"]],
        "structured_candidate_count": len(discovery["candidates"]),
        "selected_reference": discovery["selected_reference"],
        "handoff_state": handoff["observation_state"],
        "previous_cerv_available": previous_available,
        "previous_cerv_run_id": previous_run_id,
        "exact": exact_summary,
        "open_call_authorized": handoff["open_call_authorized"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--previous-cerv-available", action="store_true")
    parser.add_argument("--previous-cerv-run-id")
    args = parser.parse_args()

    summary = validate(
        args.root,
        previous_available=args.previous_cerv_available,
        previous_run_id=args.previous_cerv_run_id,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
