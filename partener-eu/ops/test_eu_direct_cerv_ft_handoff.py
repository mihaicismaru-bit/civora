#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json

import funding_tenders_fetch as ft
from eu_direct_cerv_ft_discovery import collect
from eu_direct_cerv_ft_exact import collect_exact
from eu_direct_cerv_ft_handoff import (
    CURRENT_MODE,
    OMITTED_RECHECK_MODE,
    OMITTED_SKIP_MODE,
    resolve,
    validate,
)

REFERENCE = "CERV-2026-CHAR-LITI-CHARTER"
PROGRAMME_CODE = "43251589"
STATUS_OPEN = "31094501"
PROGRAMME_LABEL = "Citizens, Equality, Rights and Values Programme (CERV)"


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
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
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


def topic(url):
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 10,
        "body_sha256": "b" * 64,
        "verified": True,
    }


def previous_exact():
    return collect_exact(
        REFERENCE,
        run_id="previous",
        fetched_at="2026-09-01T23:00:00+00:00",
        post_func=post_with([{
            "identifier": REFERENCE,
            "type": "1",
            "frameworkProgramme": PROGRAMME_CODE,
            "status": STATUS_OPEN,
            "callIdentifier": "CERV-2026-CHAR-LITI",
            "title": "Charter litigation",
        }]),
        topic_func=topic,
    )


def current_rows():
    return [{
        "identifier": REFERENCE,
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "status": STATUS_OPEN,
        "callIdentifier": "CERV-2026-CHAR-LITI",
        "title": "Charter litigation",
    }]


def main() -> int:
    previous = previous_exact()

    current = discovery(current_rows())
    handoff = resolve(current, previous=previous, run_id="test-current")
    validate(handoff)
    assert handoff["observation_state"] == CURRENT_MODE
    assert handoff["target_reference"] == REFERENCE
    assert handoff["exact_recheck_required"] is True
    assert handoff["previous_evidence_available"] is True
    assert handoff["previous_same_identity"] is True
    assert handoff["semantic_reconciliation_required_if_exact"] is True
    assert handoff["field_scoped_material_admission_required_if_exact"] is True
    assert handoff["open_call_authorized"] is False

    omitted_recheck = resolve(discovery([]), previous=previous, run_id="test-omitted-history")
    validate(omitted_recheck)
    assert omitted_recheck["observation_state"] == OMITTED_RECHECK_MODE
    assert omitted_recheck["target_reference"] == REFERENCE
    assert omitted_recheck["exact_recheck_required"] is True
    assert omitted_recheck["current_discovery_candidate"] is False
    assert omitted_recheck["previous_evidence_available"] is True
    assert omitted_recheck["previous_same_identity"] is True
    assert omitted_recheck["bounded_discovery_absence_is_material_fact"] is False
    assert omitted_recheck["closure_inference_authorized"] is False

    omitted = resolve(discovery([]), run_id="test-omitted")
    validate(omitted)
    assert omitted["observation_state"] == OMITTED_SKIP_MODE
    assert omitted["target_reference"] is None
    assert omitted["exact_recheck_required"] is False
    assert omitted["previous_evidence_available"] is False
    assert omitted["bounded_discovery_absence_is_material_fact"] is False
    assert omitted["closure_inference_authorized"] is False

    tampered = copy.deepcopy(omitted_recheck)
    tampered["closure_inference_authorized"] = True
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV handoff accepted closure inference from bounded omission")

    tampered = copy.deepcopy(handoff)
    tampered["open_call_authorized"] = True
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV handoff accepted OPEN authorization")

    tampered = copy.deepcopy(omitted_recheck)
    tampered["previous_evidence_sha256"] = "0" * 64
    tampered["previous_reference"] = "CERV-2026-DAPHNE-CHILDREN"
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV omission recheck accepted previous identity drift")

    tampered = copy.deepcopy(omitted)
    tampered["target_reference"] = REFERENCE
    tampered["exact_recheck_required"] = True
    try:
        validate(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV omission acquired an unsafe exact target without history")

    print("CERV structured handoff/history fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
