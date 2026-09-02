#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))

import interreg_applicant_partner_fit as fit  # noqa: E402
import interreg_romania_programme_matrix as matrix  # noqa: E402

EXPECTED_IDS = {"RO_BG", "RO_HU", "RO_RS", "RO_UA", "RO_MD", "DANUBE", "INTERREG_EUROPE"}


def fake_matrix() -> dict:
    by_url = {spec["url"]: spec for spec in matrix.PROGRAMMES}

    def fetcher(url: str):
        spec = by_url[url]
        text = "<html><body>" + " | ".join(spec["anchors"]) + "</body></html>"
        return text.encode(), {
            "requested_url": url,
            "final_url": url,
            "status": 200,
            "content_type": "text/html; charset=utf-8",
        }

    receipt, _raw = matrix.collect(
        run_id="regression-matrix",
        fetched_at="2026-09-02T08:00:00+00:00",
        fetcher=fetcher,
    )
    matrix.validate_receipt(receipt)
    return receipt


def by_id(result: dict) -> dict[str, dict]:
    return {row["programme_id"]: row for row in result["ranked_programme_fits"]}


def assert_non_authorizing(result: dict) -> None:
    assert result["schema"] == fit.SCHEMA
    assert result["market_intelligence_only"] is True
    assert result["fit_is_not_eligibility"] is True
    assert result["publication_effect"] == "NONE"
    for flag in fit.MATERIAL_FLAGS:
        assert result[flag] is False, (flag, result[flag])
    assert set(fit.MISSING_FOR_OPEN_CONFIRMATION).issubset(result["missing_for_open_confirmation"])
    for row in result["ranked_programme_fits"] + result["non_territorial_fits"]:
        assert row["market_intelligence_only"] is True
        assert row["fit_is_not_eligibility"] is True
        assert row["call_specific_applicant_rules_required"] is True
        assert 0 <= row["market_fit_score"] <= 100
        for flag in fit.MATERIAL_FLAGS:
            assert row[flag] is False, (row["programme_id"], flag, row[flag])


def main() -> None:
    registry, _hash = fit.load_registry()
    assert {row["id"] for row in registry["programmes"]} == EXPECTED_IDS
    assert {spec["id"] for spec in matrix.PROGRAMMES} == EXPECTED_IDS
    assert registry["updated_utc"] == "2026-09-02"
    for flag in fit.MATERIAL_FLAGS:
        assert registry["policy"][flag] is False

    receipt = fake_matrix()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "matrix.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")

        timis = fit.resolve(
            county="Timiș",
            applicant_type="public authority",
            has_international_partner=True,
            run_id="regression-timis",
            programme_matrix_path=path,
            fetched_at="2026-09-02T08:01:00+00:00",
        )
        assert_non_authorizing(timis)
        rows = by_id(timis)
        assert set(rows) == {"RO_HU", "RO_RS", "DANUBE", "INTERREG_EUROPE"}
        assert rows["RO_HU"]["market_fit_score"] == 100
        assert rows["RO_HU"]["applicant_signal_state"] == "SUPPORTED_PROGRAMME_SIGNAL"
        assert rows["RO_RS"]["market_fit_score"] == 70
        assert rows["RO_RS"]["applicant_signal_state"] == "INSUFFICIENT_EVIDENCE"
        assert rows["DANUBE"]["market_fit_score"] == 100
        assert rows["INTERREG_EUROPE"]["market_fit_score"] == 100

        tulcea = fit.resolve(
            county="Tulcea",
            applicant_type="NGO_NONPROFIT",
            run_id="regression-tulcea",
            programme_matrix_path=path,
            fetched_at="2026-09-02T08:02:00+00:00",
        )
        assert_non_authorizing(tulcea)
        rows = by_id(tulcea)
        assert rows["RO_UA"]["market_fit_score"] == 80
        assert rows["RO_UA"]["applicant_signal_state"] == "SUPPORTED_HISTORICAL_CALL_SIGNAL"
        assert rows["INTERREG_EUROPE"]["market_fit_score"] == 90
        assert rows["DANUBE"]["market_fit_score"] == 60

        valcea = fit.resolve(
            county="Vâlcea",
            applicant_type="company",
            has_international_partner=True,
            run_id="regression-valcea",
            programme_matrix_path=path,
            fetched_at="2026-09-02T08:03:00+00:00",
        )
        assert_non_authorizing(valcea)
        rows = by_id(valcea)
        assert set(rows) == {"DANUBE", "INTERREG_EUROPE"}
        assert rows["DANUBE"]["market_fit_score"] == 100
        assert rows["INTERREG_EUROPE"]["market_fit_score"] == 70
        assert rows["INTERREG_EUROPE"]["applicant_signal_state"] == "NO_SUPPORTING_SIGNAL"

        tampered = copy.deepcopy(timis)
        tampered["eligibility_authorized"] = True
        try:
            fit.validate_result(tampered)
        except ValueError:
            pass
        else:
            raise AssertionError("eligibility widening must fail closed")

        tampered = copy.deepcopy(timis)
        tampered["missing_for_open_confirmation"] = []
        try:
            fit.validate_result(tampered)
        except ValueError:
            pass
        else:
            raise AssertionError("weakening exact-call proof requirements must fail closed")

        tampered_matrix = copy.deepcopy(receipt)
        tampered_matrix["open_call_authorized"] = True
        bad = Path(tmp) / "bad-matrix.json"
        bad.write_text(json.dumps(tampered_matrix), encoding="utf-8")
        try:
            fit.resolve(
                county="Vâlcea",
                applicant_type="company",
                run_id="regression-bad-matrix",
                programme_matrix_path=bad,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("authorizing programme-matrix handoff must fail closed")

    try:
        fit.normalize_applicant_type("mystery applicant")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown applicant type must fail closed")

    print("PASS Interreg applicant/partner fit V2: canonical programme-matrix handoff, 7 programmes, deterministic ranking, zero eligibility authority")


if __name__ == "__main__":
    main()
