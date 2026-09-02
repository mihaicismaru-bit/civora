#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json

import funding_tenders_fetch as ft
from eu_direct_cerv_ft_discovery import collect
from eu_direct_cerv_ft_handoff import CURRENT_MODE, OMITTED_SKIP_MODE, resolve, validate

REFERENCE = "CERV-2026-CITIZENS-CIV-ENGAGEMENT-ELECTIONS"
PROGRAMME_CODE = "43251589"
STATUS_OPEN = "31094501"


def raw_and_receipt(endpoint: str, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return payload, raw, {
        "url": endpoint + "?apiKey=SEDIA&text=CERV-2026&pageSize=25&pageNumber=1",
        "final_url": endpoint + "?apiKey=SEDIA&text=CERV-2026&pageSize=25&pageNumber=1",
        "http_status": 200,
        "content_type": "application/json",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def facets():
    return {
        "facets": [
            {
                "name": "frameworkProgramme",
                "values": [{
                    "rawValue": PROGRAMME_CODE,
                    "value": "Citizens, Equality, Rights and Values Programme (CERV)",
                }],
            },
            {"name": "status", "values": [{"rawValue": STATUS_OPEN, "value": "Open"}]},
        ]
    }


def post_with(rows):
    def post(endpoint: str, **kwargs):
        if endpoint == ft.SEARCH_ENDPOINT:
            return raw_and_receipt(endpoint, rows)
        if endpoint == ft.FACET_ENDPOINT:
            return raw_and_receipt(endpoint, facets())
        raise AssertionError(endpoint)
    return post


def discovery(rows):
    return collect(
        run_id="test-discovery",
        fetched_at="2026-09-02T00:00:00+00:00",
        post_func=post_with(rows),
    )


def main() -> int:
    current = discovery([{
        "identifier": REFERENCE,
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "status": STATUS_OPEN,
        "callIdentifier": "CERV-2026-CITIZENS-CIV",
        "title": "Citizens engagement",
    }])
    handoff = resolve(current, run_id="test-current")
    validate(handoff)
    assert handoff["observation_state"] == CURRENT_MODE
    assert handoff["target_reference"] == REFERENCE
    assert handoff["exact_recheck_required"] is True
    assert handoff["semantic_reconciliation_required_if_exact"] is True
    assert handoff["field_scoped_material_admission_required_if_exact"] is True
    assert handoff["open_call_authorized"] is False

    omitted = resolve(discovery([]), run_id="test-omitted")
    validate(omitted)
    assert omitted["observation_state"] == OMITTED_SKIP_MODE
    assert omitted["target_reference"] is None
    assert omitted["exact_recheck_required"] is False
    assert omitted["bounded_discovery_absence_is_material_fact"] is False
    assert omitted["closure_inference_authorized"] is False

    tampered = copy.deepcopy(omitted)
    tampered["closure_inference_authorized"] = True
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV handoff accepted closure inference")

    tampered = copy.deepcopy(handoff)
    tampered["open_call_authorized"] = True
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV handoff accepted OPEN authorization")

    tampered = copy.deepcopy(omitted)
    tampered["target_reference"] = REFERENCE
    tampered["exact_recheck_required"] = True
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV omission acquired an unsafe exact target")

    print("CERV structured handoff fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
