#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse
import sys

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_territorial_fit_registry.json"
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import interreg_territorial_fit as fit  # noqa: E402

EXPECTED = {
    "INTERREG-ROBG-2021-2027": {"Mehedinți", "Dolj", "Olt", "Teleorman", "Giurgiu", "Călărași", "Constanța"},
    "INTERREG-ROHU-2021-2027": {"Arad", "Bihor", "Satu Mare", "Timiș"},
    "INTERREG-RORS-2021-2027": {"Timiș", "Caraș-Severin", "Mehedinți"},
    "INTERREG-ROUA-2021-2027": {"Satu Mare", "Maramureș", "Suceava", "Botoșani", "Tulcea"},
    "INTERREG-ROMD-2021-2027": {"Botoșani", "Iași", "Vaslui", "Galați"},
    "INTERREG-HUSKROUA-2021-2027": {"Maramureș", "Satu Mare", "Suceava"},
    "INTERREG-NEXT-BSB-2021-2027": {"Brăila", "Buzău", "Constanța", "Galați", "Tulcea", "Vrancea"},
    "INTERREG-DANUBE-2021-2027": {"ALL_ROMANIA"},
    "INTERREG-EUROPE-2021-2027": {"ALL_ROMANIA"},
}

ALLOWED_HOSTS = {
    "www.interregviarobg.eu",
    "interreg-rohu.eu",
    "romania-serbia.net",
    "www.ro-ua.net",
    "ro-md.net",
    "next.huskroua-cbc.eu",
    "projects.research-and-innovation.ec.europa.eu",
    "interreg-danube.eu",
    "www.interregeurope.eu",
}


def fit_ids(county: str) -> set[str]:
    result = fit.resolve(county, run_id="regression", observed_at="2026-08-31T00:00:00Z")
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
    assert result["publication_effect"] == "NONE"
    assert len(result["registry_sha256"]) == 64
    for row in result["fits"] + result["non_fits"]:
        assert row["observation_state"] == "TERRITORIAL_PROGRAMME_FIT"
        assert row["eligibility_authorized"] is False
        assert row["open_call_authorized"] is False
        missing = set(row["missing_for_call_confirmation"])
        assert {
            "exact_call_or_topic_identifier",
            "current_official_exact_call_endpoint",
            "explicit_current_official_call_status",
            "call_specific_applicant_and_geography_eligibility",
            "semantic_reconciliation",
        }.issubset(missing)
    return {row["programme_id"] for row in result["fits"]}


def main() -> None:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["policy"]["scope"] == "PROGRAMME_TERRITORIAL_FIT_ONLY"
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

    rows = data["programmes"]
    assert len(rows) == 9
    assert {row["id"] for row in rows} == set(EXPECTED)
    assert len({row["source_id"] for row in rows}) == 9

    for row in rows:
        assert set(row["eligible_territories_romania"]) == EXPECTED[row["id"]]
        assert row["authority_class"] == "T1_OFFICIAL_PROGRAMME"
        assert row["observation_state"] == "TERRITORIAL_PROGRAMME_FIT"
        assert row["evidence_checked_date"] == "2026-08-31"
        parsed = urlparse(row["evidence_url"])
        assert parsed.scheme == "https"
        assert parsed.hostname in ALLOWED_HOSTS, (row["id"], parsed.hostname)
        if row["romania_scope"] == "NATIONAL_ROMANIA":
            assert row["eligible_territories_romania"] == ["ALL_ROMANIA"]
        else:
            assert row["romania_scope"] == "SUBNATIONAL_COUNTIES"
            assert "ALL_ROMANIA" not in row["eligible_territories_romania"]

    national = {"INTERREG-DANUBE-2021-2027", "INTERREG-EUROPE-2021-2027"}
    assert fit_ids("Vâlcea") == national
    assert fit_ids("Valcea") == national
    assert fit_ids("Cluj") == national
    assert fit_ids("Timiș") == national | {"INTERREG-ROHU-2021-2027", "INTERREG-RORS-2021-2027"}
    assert fit_ids("Timis") == national | {"INTERREG-ROHU-2021-2027", "INTERREG-RORS-2021-2027"}
    assert fit_ids("Constanța") == national | {"INTERREG-ROBG-2021-2027", "INTERREG-NEXT-BSB-2021-2027"}
    assert fit_ids("Galați") == national | {"INTERREG-ROMD-2021-2027", "INTERREG-NEXT-BSB-2021-2027"}
    assert fit_ids("Tulcea") == national | {"INTERREG-ROUA-2021-2027", "INTERREG-NEXT-BSB-2021-2027"}
    assert fit_ids("Maramureș") == national | {"INTERREG-ROUA-2021-2027", "INTERREG-HUSKROUA-2021-2027"}
    assert fit_ids("Maramures") == national | {"INTERREG-ROUA-2021-2027", "INTERREG-HUSKROUA-2021-2027"}

    try:
        fit.resolve("", run_id="regression")
    except ValueError:
        pass
    else:
        raise AssertionError("empty county must fail closed")

    print("PASS Interreg territorial-fit registry: 9 official programmes, deterministic Romania geography fit, zero material authorization")


if __name__ == "__main__":
    main()
