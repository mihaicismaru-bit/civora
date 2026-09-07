#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_cerv_ft_exact import collect_exact
from eu_direct_cerv_ft_reconcile import reconcile, validate_receipt

REF = "CERV-2026-CHAR-LITI-CHARTER"
CALL = "CERV-2026-CHAR-LITI"
PROGRAMME_CODE = "43251589"
STATUS_CODE = "31094502"


def facets():
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{
                "rawValue": PROGRAMME_CODE,
                "value": "Citizens, Equality, Rights and Values Programme (CERV)",
            }]},
            {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": "Open"}]},
        ]
    }


def rows():
    return [{
        "identifier": REF,
        "topicAbbreviation": REF,
        "callIdentifier": CALL,
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Synthetic CERV topic",
        "deadlineDate": "2026-10-01T17:00:00Z",
    }]


def pack(endpoint, payload):
    raw = json.dumps(payload, sort_keys=True).encode()
    return payload, raw, {
        "url": endpoint,
        "final_url": endpoint,
        "http_status": 200,
        "content_type": "application/json",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def post(endpoint, **kwargs):
    if endpoint == ft.SEARCH_ENDPOINT:
        return pack(endpoint, rows())
    if endpoint == ft.FACET_ENDPOINT:
        return pack(endpoint, facets())
    raise AssertionError(endpoint)


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


def evidence(at: str):
    return collect_exact(
        REF,
        run_id="reconcile-test",
        fetched_at=at,
        post_func=post,
        topic_func=topic,
    )


def main() -> int:
    current = evidence("2026-09-02T01:10:00+00:00")
    baseline = reconcile(current)
    validate_receipt(baseline, current=current)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_change_count"] == 0
    assert baseline["material_admission_ready_for_downstream_review"] is True
    assert baseline["open_call_authorized"] is False

    previous = evidence("2026-09-02T01:00:00+00:00")
    no_change = reconcile(current, previous)
    validate_receipt(no_change, current=current, previous=previous)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0
    assert no_change["open_call_authorized"] is False

    bad_previous = copy.deepcopy(previous)
    bad_previous["reference"] = "CERV-2026-DAPHNE-CHILDREN"
    try:
        reconcile(current, bad_previous)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV reconciliation accepted identity drift")

    tampered = copy.deepcopy(baseline)
    tampered["open_call_authorized"] = True
    try:
        validate_receipt(tampered, current=current)
    except ValueError:
        pass
    else:
        raise AssertionError("CERV reconciliation self-authorized OPEN")

    print("eu_direct_cerv_ft_reconcile regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
