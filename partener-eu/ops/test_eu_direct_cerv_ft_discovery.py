#!/usr/bin/env python3
from __future__ import annotations

import copy
import json

import funding_tenders_fetch as ft
from eu_direct_cerv_ft_discovery import (
    DISCOVERED_STATE,
    OMITTED_STATE,
    collect,
    validate_receipt,
)

REFERENCE = "CERV-2026-CITIZENS-CIV-ENGAGEMENT-ELECTIONS"
PROGRAMME_CODE = "43251589"
STATUS_OPEN = "31094501"


def raw_and_receipt(endpoint: str, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    import hashlib
    return payload, raw, {
        "url": endpoint + "?apiKey=SEDIA&text=CERV-2026&pageSize=25&pageNumber=1",
        "final_url": endpoint + "?apiKey=SEDIA&text=CERV-2026&pageSize=25&pageNumber=1",
        "http_status": 200,
        "content_type": "application/json",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def facet_payload():
    return {
        "facets": [
            {
                "name": "frameworkProgramme",
                "values": [
                    {
                        "rawValue": PROGRAMME_CODE,
                        "value": "Citizens, Equality, Rights and Values Programme (CERV)",
                    }
                ],
            },
            {
                "name": "status",
                "values": [{"rawValue": STATUS_OPEN, "value": "Open"}],
            },
        ]
    }


def row(*, title: str = "Citizens engagement", record_type: str = "1"):
    return {
        "identifier": REFERENCE,
        "type": record_type,
        "frameworkProgramme": PROGRAMME_CODE,
        "status": STATUS_OPEN,
        "callIdentifier": "CERV-2026-CITIZENS-CIV",
        "title": title,
    }


def make_post(search_rows):
    def post(endpoint: str, **kwargs):
        if endpoint == ft.SEARCH_ENDPOINT:
            return raw_and_receipt(endpoint, search_rows)
        if endpoint == ft.FACET_ENDPOINT:
            return raw_and_receipt(endpoint, facet_payload())
        raise AssertionError(endpoint)
    return post


def main() -> int:
    receipt = collect(
        run_id="test-current",
        fetched_at="2026-09-02T00:00:00+00:00",
        post_func=make_post([row(), row(record_type="8")]),
    )
    validate_receipt(receipt)
    assert receipt["observation_state"] == DISCOVERED_STATE
    assert receipt["selected_reference"] == REFERENCE
    assert receipt["exact_current_recheck_required"] is True
    assert receipt["linked_type8_count"] == 1
    assert receipt["candidates"][0]["status_label_candidate"] == "Open"
    assert receipt["candidates"][0]["authority_url_verified"] is False
    assert receipt["open_call_authorized"] is False
    assert receipt["material_fact_use"] is False

    duplicate = collect(
        run_id="test-duplicate",
        fetched_at="2026-09-02T00:00:00+00:00",
        post_func=make_post([row(), row()]),
    )
    assert duplicate["duplicate_rows_removed"] == 1
    assert duplicate["selected_reference"] == REFERENCE

    conflict = collect(
        run_id="test-conflict",
        fetched_at="2026-09-02T00:00:00+00:00",
        post_func=make_post([row(title="A"), row(title="B")]),
    )
    assert conflict["observation_state"] == OMITTED_STATE
    assert conflict["selected_reference"] is None
    assert conflict["conflict_identifiers"] == [REFERENCE]
    assert conflict["closure_inference_authorized"] is False

    omitted = collect(
        run_id="test-omitted",
        fetched_at="2026-09-02T00:00:00+00:00",
        post_func=make_post([]),
    )
    assert omitted["observation_state"] == OMITTED_STATE
    assert omitted["selected_reference"] is None
    assert omitted["exact_current_recheck_required"] is False
    assert omitted["bounded_discovery_absence_is_material_fact"] is False

    tampered = copy.deepcopy(receipt)
    tampered["open_call_authorized"] = True
    try:
        validate_receipt(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV discovery accepted OPEN authorization")

    tampered = copy.deepcopy(receipt)
    tampered["candidates"][0]["authority_url_verified"] = True
    tampered["selected_candidate"] = tampered["candidates"][0]
    try:
        validate_receipt(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV discovery self-verified exact authority")

    tampered = copy.deepcopy(omitted)
    tampered["closure_inference_authorized"] = True
    try:
        validate_receipt(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV discovery inferred closure from omission")

    print("CERV structured discovery fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
