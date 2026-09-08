#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_life_ft_exact import (
    ExactLifeConflict,
    PRIORITY_EXACT_WATCH_REFERENCES,
    collect_exact,
    select_life_candidate,
    select_life_execution_target,
    validate_evidence,
    validate_reference,
)

REF = "LIFE-2026-SAP-ENV-ENVIRONMENT"
PRIORITY_WATCH_REF = "LIFE-2026-CET-BUILDSKILLS"
PROGRAMME_CODE = "43252405"
STATUS_CODE = "31094501"
PROGRAMME_LABEL = "Programme for the Environment and Climate Action (LIFE)"


def facet_payload():
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
            {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": "Open"}]},
        ]
    }


def search_payload(deadline="2026-09-23T17:00:00Z", reference=REF, call_identifier="LIFE-2026-SAP-ENV"):
    return [{
        "identifier": reference,
        "topicAbbreviation": reference,
        "callIdentifier": call_identifier,
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Synthetic LIFE environment topic",
        "deadlineDate": deadline,
    }]


def receipt(url):
    return {"url": url, "final_url": url, "http_status": 200, "content_type": "application/json", "bytes": 2, "sha256": "a" * 64}


def make_post(search=None, facet=None):
    search = search if search is not None else search_payload()
    facet = facet if facet is not None else facet_payload()

    def post(endpoint, **kwargs):
        if endpoint == ft.SEARCH_ENDPOINT:
            return copy.deepcopy(search), b"{}", receipt(endpoint)
        if endpoint == ft.FACET_ENDPOINT:
            return copy.deepcopy(facet), b"{}", receipt(endpoint)
        raise AssertionError(endpoint)

    return post


def topic(url):
    return {"url": url, "final_url": url, "http_status": 200, "content_type": "text/html", "bytes": 10, "body_sha256": "b" * 64, "verified": True}


def main():
    taxonomy = {
        "schema": "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "records": [
            {"identifier": "LIFE-2026-TA-PP-NAT-SNAP", "programme_family_normalized": "LIFE", "status_label_candidate": "Forthcoming", "taxonomy_fingerprint": "1" * 64, "source_semantic_fingerprint": "2" * 64, "authority_url_candidate": ft.topic_url("LIFE-2026-TA-PP-NAT-SNAP")},
            {"identifier": REF, "programme_family_normalized": "LIFE", "status_label_candidate": "Open", "taxonomy_fingerprint": "3" * 64, "source_semantic_fingerprint": "4" * 64, "authority_url_candidate": ft.topic_url(REF)},
        ],
    }
    selected = select_life_candidate(taxonomy)
    assert selected["identifier"] == REF

    # The bounded programme sample deliberately omits the priority BUILDUP topic.
    # The canonical LIFE lane must still route it into an exact F&T re-check,
    # while preserving the sample candidate only as a non-authorizing fallback.
    execution = select_life_execution_target(taxonomy)
    assert PRIORITY_EXACT_WATCH_REFERENCES == (PRIORITY_WATCH_REF,)
    assert execution["identifier"] == PRIORITY_WATCH_REF
    assert execution["handoff_mode"] == "EXPLICIT_PRIORITY_EXACT_RECHECK"
    assert execution["priority_rank"] == 0
    assert execution["bounded_sample_contains_target"] is False
    assert execution["bounded_sample_fallback"]["identifier"] == REF
    assert execution["material_fact_use"] is False
    assert execution["exact_recheck_required"] is True
    assert execution["source_authority_url_candidate"] == ft.topic_url(PRIORITY_WATCH_REF)

    evidence = collect_exact(
        REF,
        run_id="synthetic",
        fetched_at="2026-09-01T15:00:00+00:00",
        source_candidate=selected,
        post_func=make_post(),
        topic_func=topic,
    )
    validate_evidence(evidence)
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["status_label"] == "Open"
    assert evidence["authority_url_verified"] is True
    assert evidence["programme_family"] == "LIFE"
    assert evidence["material_fact_use"] is False
    assert evidence["open_call_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["publish_authorized"] is False

    # Keep priority watch identities on the existing generic exact LIFE adapter.
    # This is deliberately synthetic/non-authorizing: live admission remains owned
    # by the canonical F&T acquisition/reconciliation lane.
    assert validate_reference(PRIORITY_WATCH_REF) == PRIORITY_WATCH_REF
    watch_evidence = collect_exact(
        PRIORITY_WATCH_REF,
        run_id="synthetic-priority-watch",
        fetched_at="2026-09-08T06:00:00+00:00",
        post_func=make_post(
            search=search_payload(
                deadline="2026-09-16T17:00:00+02:00",
                reference=PRIORITY_WATCH_REF,
                call_identifier="LIFE-2026-CET",
            )
        ),
        topic_func=topic,
    )
    validate_evidence(watch_evidence)
    assert watch_evidence["reference"] == PRIORITY_WATCH_REF
    assert watch_evidence["call_identifier"] == "LIFE-2026-CET"
    assert watch_evidence["candidate_state"] == "OPEN_CALL"
    assert watch_evidence["authority_url"] == ft.topic_url(PRIORITY_WATCH_REF)
    assert watch_evidence["authority_url_verified"] is True
    assert watch_evidence["semantic_reconciliation_required"] is True
    assert watch_evidence["field_scoped_material_admission_required"] is True
    assert watch_evidence["material_fact_use"] is False
    assert watch_evidence["open_call_authorized"] is False
    assert watch_evidence["deadline_authorized"] is False
    assert watch_evidence["publish_authorized"] is False
    assert watch_evidence["canonical_corpus_mutation"] is False
    assert watch_evidence["publication_effect"] == "NONE"

    bad_facet = facet_payload()
    bad_facet["facets"][0]["values"][0]["value"] = "Horizon Europe"
    try:
        collect_exact(REF, run_id="bad-programme", fetched_at="2026-09-01T15:00:00+00:00", post_func=make_post(facet=bad_facet), topic_func=topic)
        raise AssertionError("non-LIFE programme label was accepted")
    except ValueError as exc:
        assert "not proven to belong to LIFE" in str(exc)

    conflict_rows = search_payload("2026-09-23T17:00:00Z") + search_payload("2026-10-01T17:00:00Z")
    try:
        collect_exact(REF, run_id="conflict", fetched_at="2026-09-01T15:00:00+00:00", post_func=make_post(search=conflict_rows), topic_func=topic)
        raise AssertionError("materially conflicting exact LIFE rows were accepted")
    except ExactLifeConflict:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["open_call_authorized"] = True
    try:
        validate_evidence(tampered)
        raise AssertionError("self-authorization was accepted")
    except ValueError as exc:
        assert "attempted authorization" in str(exc)

    print("eu_direct_life_ft_exact regression: PASS")


if __name__ == "__main__":
    main()
