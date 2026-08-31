#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
REGISTRY = INGEST / "interreg_applicant_partner_fit_registry.json"
TERRITORIAL_REGISTRY = INGEST / "interreg_territorial_fit_registry.json"
sys.path.insert(0, str(INGEST))

import interreg_applicant_partner_fit as fit  # noqa: E402

EXPECTED_IDS = {
    "INTERREG-ROBG-2021-2027",
    "INTERREG-ROHU-2021-2027",
    "INTERREG-RORS-2021-2027",
    "INTERREG-ROUA-2021-2027",
    "INTERREG-ROMD-2021-2027",
    "INTERREG-NEXT-BSB-2021-2027",
    "INTERREG-DANUBE-2021-2027",
    "INTERREG-EUROPE-2021-2027",
}

ALLOWED_HOSTS = {
    "www.interregviarobg.eu",
    "interreg-rohu.eu",
    "romania-serbia.net",
    "ro-ua.net",
    "www.ro-ua.net",
    "ro-md.net",
    "www.ro-md.net",
    "www.blacksea-cbc.net",
    "blacksea-cbc.net",
    "interreg-danube.eu",
    "www.interregeurope.eu",
}


def by_id(result: dict) -> dict[str, dict]:
    return {row["programme_id"]: row for row in result["ranked_programme_fits"]}


def assert_non_authorizing(result: dict) -> None:
    for key in (
        "material_fact_use",
        "open_call_authorized",
        "deadline_authorized",
        "budget_authorized",
        "eligibility_authorized",
        "publish_authorized",
        "distribution_authorized",
    ):
        assert result[key] is False, (key, result[key])
    assert result["market_intelligence_only"] is True
    assert result["publication_effect"] == "NONE"
    required = {
        "exact_call_or_topic_identifier",
        "current_official_exact_call_endpoint",
        "explicit_current_official_call_status",
        "call_specific_applicant_geography_partnership_and_role_rules",
        "semantic_reconciliation",
    }
    assert required.issubset(set(result["missing_for_call_confirmation"]))
    for row in result["ranked_programme_fits"] + result["non_territorial_fits"]:
        assert row["market_intelligence_only"] is True
        assert row["eligibility_authorized"] is False
        assert row["open_call_authorized"] is False
        assert 0 <= row["market_fit_score"] <= 100
        assert required.issubset(set(row["missing_for_call_confirmation"]))


def main() -> None:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    territorial = json.loads(TERRITORIAL_REGISTRY.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["policy"]["scope"] == "PROGRAMME_APPLICANT_PARTNER_SIGNAL_ONLY"
    for key in (
        "material_fact_use",
        "open_call_authorized",
        "deadline_authorized",
        "budget_authorized",
        "eligibility_authorized",
        "publish_authorized",
        "distribution_authorized",
    ):
        assert data["policy"][key] is False
    assert {row["id"] for row in data["programmes"]} == EXPECTED_IDS
    assert {row["id"] for row in territorial["programmes"]} == EXPECTED_IDS

    for row in data["programmes"]:
        assert row["authority_class"] == "T1_OFFICIAL_PROGRAMME"
        assert row["evidence_checked_date"] == "2026-08-31"
        assert row["call_specific_applicant_rules_required"] is True
        assert set(row["supported_applicant_types"]).issubset(fit.KNOWN_TYPES)
        parsed = urlparse(row["evidence_url"])
        assert parsed.scheme == "https"
        assert parsed.hostname in ALLOWED_HOSTS, (row["id"], parsed.hostname)
        if row["supported_applicant_types"]:
            assert row["observation_state"] in {"PROGRAMME_APPLICANT_SIGNAL", "RECENT_CALL_APPLICANT_SIGNAL"}
        else:
            assert row["observation_state"] == "APPLICANT_SIGNAL_INSUFFICIENT"

    timis = fit.resolve(
        "Timiș",
        "public authority",
        run_id="regression",
        has_international_partner=True,
        observed_at="2026-08-31T00:00:00Z",
    )
    assert_non_authorizing(timis)
    rows = by_id(timis)
    assert set(rows) == {
        "INTERREG-ROHU-2021-2027",
        "INTERREG-RORS-2021-2027",
        "INTERREG-DANUBE-2021-2027",
        "INTERREG-EUROPE-2021-2027",
    }
    assert rows["INTERREG-ROHU-2021-2027"]["applicant_signal_state"] == "SUPPORTED_PROGRAMME_SIGNAL"
    assert rows["INTERREG-ROHU-2021-2027"]["market_fit_score"] == 100
    assert rows["INTERREG-DANUBE-2021-2027"]["market_fit_score"] == 100
    assert rows["INTERREG-RORS-2021-2027"]["applicant_signal_state"] == "INSUFFICIENT_EVIDENCE"
    assert rows["INTERREG-RORS-2021-2027"]["market_fit_score"] == 70

    tulcea = fit.resolve(
        "Tulcea",
        "NGO_NONPROFIT",
        run_id="regression",
        observed_at="2026-08-31T00:00:00Z",
    )
    assert_non_authorizing(tulcea)
    rows = by_id(tulcea)
    assert rows["INTERREG-ROUA-2021-2027"]["applicant_signal_state"] == "SUPPORTED_RECENT_CALL_SIGNAL"
    assert rows["INTERREG-ROUA-2021-2027"]["market_fit_score"] == 80
    assert rows["INTERREG-NEXT-BSB-2021-2027"]["market_fit_score"] == 80
    assert rows["INTERREG-DANUBE-2021-2027"]["applicant_signal_state"] == "NO_SUPPORTING_SIGNAL"
    assert rows["INTERREG-DANUBE-2021-2027"]["market_fit_score"] == 60

    valcea_company = fit.resolve(
        "Valcea",
        "company",
        run_id="regression",
        has_international_partner=True,
        observed_at="2026-08-31T00:00:00Z",
    )
    assert_non_authorizing(valcea_company)
    rows = by_id(valcea_company)
    assert set(rows) == {"INTERREG-DANUBE-2021-2027", "INTERREG-EUROPE-2021-2027"}
    assert rows["INTERREG-DANUBE-2021-2027"]["applicant_signal_state"] == "SUPPORTED_PROGRAMME_SIGNAL"
    assert rows["INTERREG-DANUBE-2021-2027"]["market_fit_score"] == 100
    assert rows["INTERREG-EUROPE-2021-2027"]["applicant_signal_state"] == "INSUFFICIENT_EVIDENCE"
    assert rows["INTERREG-EUROPE-2021-2027"]["market_fit_score"] == 70

    try:
        fit.normalize_applicant_type("mystery applicant")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown applicant type must fail closed")

    print("PASS Interreg applicant/partner market fit: 8 programmes, official signals only, deterministic ranking, zero eligibility authority")


if __name__ == "__main__":
    main()
