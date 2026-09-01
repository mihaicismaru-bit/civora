#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def check_non_authorizing(obj: dict[str, Any]) -> None:
    for key in MATERIAL_FLAGS:
        assert obj[key] is False, (key, obj.get(key))
    assert obj["canonical_corpus_mutation"] is False
    assert obj["publication_effect"] == "NONE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root

    taxonomy = load(root / "programme-taxonomy.json")
    handoff = load(root / "digital-exact/ft-digital-handoff-state.json")
    assert taxonomy["schema"] == "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1"
    assert handoff["schema"] == "PARTENER_EU_DIGITAL_FT_HANDOFF_STATE_V1"
    check_non_authorizing(handoff)
    assert handoff["bounded_sample_omission_is_material_fact"] is False
    assert handoff["closure_inference_authorized"] is False

    digital_rows = [
        row for row in taxonomy.get("records") or []
        if row.get("programme_family_normalized") == "DIGITAL_EUROPE"
    ]
    exact_required = handoff["exact_recheck_required"] is True
    if exact_required:
        assert digital_rows
        assert handoff["observation_state"] == "CURRENT_BOUNDED_SAMPLE_CANDIDATE_EXACT_RECHECK"
        exact = load(root / "digital-exact/ft-digital-exact-evidence.json")
        rec = load(root / "digital-exact/ft-digital-reconciliation.json")
        assert exact["schema"] == "PARTENER_EU_DIGITAL_FT_EXACT_EVIDENCE_V1"
        assert rec["schema"] == "PARTENER_EU_DIGITAL_FT_RECONCILIATION_V1"
        assert exact["reference"] == handoff["target_reference"]
        assert exact["programme_family"] == "DIGITAL_EUROPE"
        assert exact["reference"].startswith("DIGITAL-")
        assert "digital europe programme" in exact["programme_label_official"].casefold()
        assert exact["authority_url_verified"] is True
        assert exact["authority_readback"]["verified"] is True
        assert exact["candidate_state"] in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}
        assert exact["status_label"]
        check_non_authorizing(exact)
        check_non_authorizing(rec)
        assert rec["reference"] == exact["reference"]
        assert rec["current_evidence_sha256"] == canonical_sha(exact)
        assert rec["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
        assert rec["previous_evidence_sha256"] is None
        assert rec["material_admission_ready_for_downstream_review"] is (exact["candidate_state"] == "OPEN_CALL")
        result = {
            "handoff_state": handoff["observation_state"],
            "reference": exact["reference"],
            "candidate_state": exact["candidate_state"],
            "status_label": exact["status_label"],
            "authority_url_verified": exact["authority_url_verified"],
            "reconciliation_state": rec["reconciliation_state"],
            "semantic_change_count": rec["semantic_change_count"],
            "material_admission_ready_for_downstream_review": rec["material_admission_ready_for_downstream_review"],
            "open_call_authorized": rec["open_call_authorized"],
        }
    else:
        assert not digital_rows
        assert handoff["observation_state"] == "BOUNDED_SAMPLE_FAMILY_OMITTED_NO_SAFE_IDENTITY_NON_AUTHORIZING"
        assert handoff["target_reference"] is None
        assert not (root / "digital-exact/ft-digital-exact-evidence.json").exists()
        assert not (root / "digital-exact/ft-digital-reconciliation.json").exists()
        result = {
            "handoff_state": handoff["observation_state"],
            "reference": None,
            "exact_recheck_required": False,
            "open_call_authorized": False,
        }

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
