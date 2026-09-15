#!/usr/bin/env python3
from __future__ import annotations

import copy

from interreg_romania_programme_matrix import PROGRAMMES, collect, validate_receipt


def route_anchors(spec: dict, url: str) -> tuple[str, ...]:
    if url == spec["url"]:
        return tuple(spec["anchors"])
    if url in tuple(spec.get("fallback_urls") or ()):
        return tuple(spec.get("fallback_anchors") or spec["anchors"])
    raise AssertionError(f"undeclared synthetic route: {url}")


def spec_for_url(url: str) -> dict:
    for spec in PROGRAMMES:
        if url == spec["url"] or url in tuple(spec.get("fallback_urls") or ()):
            return spec
    raise AssertionError(url)


def synthetic_body(spec: dict, url: str) -> bytes:
    return ("<html><body>" + " | ".join(str(x) for x in route_anchors(spec, url)) + "</body></html>").encode()


def healthy_meta(url: str) -> dict:
    return {
        "requested_url": url, "final_url": url, "status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def fake_fetch(url: str):
    spec = spec_for_url(url)
    return synthetic_body(spec, url), healthy_meta(url)


def huskroua_primary_marker_drift_fetch(url: str):
    spec = spec_for_url(url)
    if spec["id"] == "HUSKROUA" and url == spec["url"]:
        return b"<html><body>Please wait while your request is being verified...</body></html>", healthy_meta(url)
    return synthetic_body(spec, url), healthy_meta(url)


def fail(fn, needle: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert needle.casefold() in str(exc).casefold(), (needle, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {needle!r}")


def main() -> int:
    receipt, raw = collect(run_id="synthetic-interreg-1", fetched_at="2026-09-04T00:00:00+00:00", fetcher=fake_fetch)
    assert receipt["schema"] == "PARTENER_EU_INTERREG_ROMANIA_PROGRAMME_MATRIX_V1"
    assert receipt["source_family"] == "INTERREG"
    assert receipt["programme_count"] == len(PROGRAMMES) == 9 and len(raw) == 9
    expected = {"RO_BG","RO_HU","RO_RS","RO_UA","RO_MD","DANUBE","INTERREG_EUROPE","HUSKROUA","BSB"}
    assert {x["programme_id"] for x in receipt["programmes"]} == expected
    assert all(x["territorial_fit_state"] == "ROMANIA_PROGRAMME_TERRITORY_VERIFIED_NON_AUTHORIZING" for x in receipt["programmes"])
    assert all(x["call_fact_authorized"] is False and x["applicant_eligibility_authorized"] is False for x in receipt["programmes"])

    huskroua = next(x for x in receipt["programmes"] if x["programme_id"] == "HUSKROUA")
    huskroua_source = next(x for x in receipt["sources"] if x["programme_id"] == "HUSKROUA")
    assert huskroua["cooperation_mode"] == "CBC_NEXT_MULTILATERAL"
    assert huskroua["romania_scope"] == ["Maramures", "Satu Mare", "Suceava"]
    assert huskroua["acquisition_route_kind"] == "PRIMARY"
    assert huskroua_source["acquisition_attempts"][-1]["outcome"] == "ACCEPTED"

    fallback_receipt, _ = collect(
        run_id="synthetic-interreg-huskroua-fallback",
        fetched_at="2026-09-07T14:15:00+00:00",
        fetcher=huskroua_primary_marker_drift_fetch,
    )
    fallback_huskroua = next(x for x in fallback_receipt["programmes"] if x["programme_id"] == "HUSKROUA")
    fallback_source = next(x for x in fallback_receipt["sources"] if x["programme_id"] == "HUSKROUA")
    husk_spec = next(x for x in PROGRAMMES if x["id"] == "HUSKROUA")
    assert fallback_huskroua["authority_url"] == husk_spec["canonical_authority_url"] == husk_spec["url"]
    assert fallback_huskroua["acquisition_url"] == husk_spec["fallback_urls"][0]
    assert fallback_huskroua["acquisition_route_kind"] == "OFFICIAL_FALLBACK"
    assert fallback_huskroua["romania_scope"] == ["Maramures", "Satu Mare", "Suceava"]
    assert fallback_huskroua["call_fact_authorized"] is False
    assert fallback_huskroua["applicant_eligibility_authorized"] is False
    assert len(fallback_source["acquisition_attempts"]) == 2
    assert fallback_source["acquisition_attempts"][0]["route_kind"] == "PRIMARY"
    assert fallback_source["acquisition_attempts"][0]["outcome"] == "REJECTED_FAIL_CLOSED"
    assert "missing required official territorial anchors" in fallback_source["acquisition_attempts"][0]["error"]
    assert fallback_source["acquisition_attempts"][1]["route_kind"] == "OFFICIAL_FALLBACK"
    assert fallback_source["acquisition_attempts"][1]["outcome"] == "ACCEPTED"
    validate_receipt(fallback_receipt)

    bsb = next(x for x in receipt["programmes"] if x["programme_id"] == "BSB")
    bsb_source = next(x for x in receipt["sources"] if x["programme_id"] == "BSB")
    assert bsb["cooperation_mode"] == "TRANSNATIONAL_NEXT"
    assert bsb["romania_scope"] == ["Braila", "Buzau", "Constanta", "Galati", "Tulcea", "Vrancea"]
    assert bsb["authority_url"].startswith("https://projects.research-and-innovation.ec.europa.eu/")
    assert bsb["acquisition_url"] == "https://keep.eu/programmes/387/2021-2027-Black-Sea-Basin/"
    assert bsb_source["authority_url"] == bsb["authority_url"]
    assert bsb_source["acquisition_url"] == bsb["acquisition_url"]
    assert "programme-validated" in bsb["evidence_note"]
    assert bsb["call_fact_authorized"] is False
    assert bsb["applicant_eligibility_authorized"] is False
    validate_receipt(receipt)

    t = copy.deepcopy(receipt); t["open_call_authorized"] = True
    fail(lambda: validate_receipt(t), "attempted authorization")
    t = copy.deepcopy(receipt); t["programmes"][0]["observation_state"] = "OPEN_CALL"
    fail(lambda: validate_receipt(t), "escaped programme-level geography research")
    t = copy.deepcopy(receipt); t["programmes"][0]["applicant_eligibility_authorized"] = True
    fail(lambda: validate_receipt(t), "attempted call/applicant eligibility authorization")
    t = copy.deepcopy(receipt); t["programmes"][0]["romania_scope"] = ["ALL_ROMANIA"]
    fail(lambda: validate_receipt(t), "territory/authority drift")
    t = copy.deepcopy(receipt)
    next(x for x in t["programmes"] if x["programme_id"] == "HUSKROUA")["romania_scope"] = ["ALL_ROMANIA"]
    fail(lambda: validate_receipt(t), "territory/authority drift")
    t = copy.deepcopy(receipt)
    next(x for x in t["programmes"] if x["programme_id"] == "BSB")["romania_scope"] = ["ALL_ROMANIA"]
    fail(lambda: validate_receipt(t), "territory/authority drift")
    t = copy.deepcopy(receipt)
    next(x for x in t["programmes"] if x["programme_id"] == "BSB")["acquisition_url"] = "https://example.com/not-official"
    fail(lambda: validate_receipt(t), "territory/authority drift")
    t = copy.deepcopy(receipt); t["sources"][0]["final_url"] = "https://example.com/not-official"
    fail(lambda: validate_receipt(t), "escaped official evidence authority")
    t = copy.deepcopy(receipt); t["programmes"][0]["source_sha256"] = "0" * 64
    fail(lambda: validate_receipt(t), "source hash binding drift")

    print({
        "status": "PASS",
        "programme_count": receipt["programme_count"],
        "huskroua_romania_scope": huskroua["romania_scope"],
        "huskroua_primary_route": huskroua["acquisition_route_kind"],
        "huskroua_official_fallback_guard": "PASS",
        "bsb_romania_scope": bsb["romania_scope"],
        "bsb_semantic_authority": "EUROPEAN_COMMISSION",
        "bsb_acquisition_authority": "KEEP_PROGRAMME_VALIDATED",
        "bsb_fit_non_authorizing": True,
        "open_call_widening_guard": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
