#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

from eu_direct_digital_ft_handoff import CURRENT_MODE, OMITTED_SKIP_MODE, resolve_handoff, validate_state


def taxonomy(records):
    return {
        "schema": "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "records": records,
    }


def digital_row(reference="DIGITAL-2026-AI-DATA-10-COMPLIANCE"):
    return {
        "programme_family_normalized": "DIGITAL_EUROPE",
        "identifier": reference,
        "status_label_candidate": "Open",
        "taxonomy_fingerprint": "a" * 64,
        "source_semantic_fingerprint": "b" * 64,
        "authority_url_candidate": f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{reference}",
    }


def expect_fail(fn):
    try:
        fn()
    except Exception:
        return
    raise AssertionError("expected fail-closed rejection")


def main() -> int:
    current = resolve_handoff(taxonomy([digital_row()]), run_id="current")
    assert current["observation_state"] == CURRENT_MODE
    assert current["target_reference"] == "DIGITAL-2026-AI-DATA-10-COMPLIANCE"
    assert current["exact_recheck_required"] is True
    assert current["current_taxonomy_candidate"] is True
    assert current["closure_inference_authorized"] is False
    assert current["open_call_authorized"] is False

    omitted = resolve_handoff(taxonomy([]), run_id="omitted")
    assert omitted["observation_state"] == OMITTED_SKIP_MODE
    assert omitted["target_reference"] is None
    assert omitted["exact_recheck_required"] is False
    assert omitted["bounded_sample_omission_is_material_fact"] is False
    assert omitted["closure_inference_authorized"] is False
    assert omitted["open_call_authorized"] is False

    tampered = copy.deepcopy(omitted)
    tampered["closure_inference_authorized"] = True
    expect_fail(lambda: validate_state(tampered))

    widened = copy.deepcopy(current)
    widened["open_call_authorized"] = True
    expect_fail(lambda: validate_state(widened))

    bad_skip = copy.deepcopy(omitted)
    bad_skip["target_reference"] = "DIGITAL-2026-AI-DATA-10-COMPLIANCE"
    expect_fail(lambda: validate_state(bad_skip))

    print(json.dumps({
        "current": current["observation_state"],
        "omitted": omitted["observation_state"],
        "material_authorization": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
