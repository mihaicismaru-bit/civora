#!/usr/bin/env python3
from __future__ import annotations

import copy

from interreg_romania_programme_matrix import PROGRAMMES, collect, validate_receipt


def synthetic_body(spec: dict) -> bytes:
    return ("<html><body>" + " | ".join(str(x) for x in spec["anchors"]) + "</body></html>").encode()


def fake_fetch(url: str):
    spec = next(x for x in PROGRAMMES if x["url"] == url)
    return synthetic_body(spec), {
        "requested_url": url, "final_url": url, "status": 200,
        "content_type": "text/html; charset=utf-8",
    }


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
    assert huskroua["cooperation_mode"] == "CBC_NEXT_MULTILATERAL"
    assert huskroua["romania_scope"] == ["Maramures", "Satu Mare", "Suceava"]

    bsb = next(x for x in receipt["programmes"] if x["programme_id"] == "BSB")
    assert bsb["cooperation_mode"] == "TRANSNATIONAL_NEXT"
    assert bsb["romania_scope"] == ["Braila", "Buzau", "Constanta", "Galati", "Tulcea", "Vrancea"]
    assert bsb["authority_url"] == "https://keep.eu/programmes/387/2021-2027-Black-Sea-Basin/"
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
    t = copy.deepcopy(receipt); t["sources"][0]["final_url"] = "https://example.com/not-official"
    fail(lambda: validate_receipt(t), "escaped official evidence authority")
    t = copy.deepcopy(receipt); t["programmes"][0]["source_sha256"] = "0" * 64
    fail(lambda: validate_receipt(t), "source hash binding drift")

    print({
        "status": "PASS",
        "programme_count": receipt["programme_count"],
        "huskroua_romania_scope": huskroua["romania_scope"],
        "bsb_romania_scope": bsb["romania_scope"],
        "bsb_primary_authority": "KEEP_PROGRAMME_VALIDATED",
        "bsb_fit_non_authorizing": True,
        "open_call_widening_guard": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
