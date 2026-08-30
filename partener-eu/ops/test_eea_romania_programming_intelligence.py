#!/usr/bin/env python3
"""Regression tests for Romania EEA/Norway 2021-2028 official programming intelligence."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "eea_romania_programming_intelligence.py"
REGISTRY_PATH = ROOT / "partener-eu" / "ingest" / "eea_romania_programming_registry.json"

spec = importlib.util.spec_from_file_location("eea_romania_programming_intelligence", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

OBSERVED_AT = "2026-08-30T16:52:37Z"
RUN_ID = "test-eea-romania-programming"


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def expect_failure(registry: dict, needle: str) -> None:
    try:
        module.normalize_registry(registry, observed_at=OBSERVED_AT, run_id=RUN_ID)
    except ValueError as exc:
        if needle.lower() not in str(exc).lower():
            raise AssertionError(f"expected {needle!r} in {exc!r}") from exc
    else:
        raise AssertionError(f"expected failure containing {needle!r}")


def test_happy_path() -> None:
    output = module.normalize_registry(load_registry(), observed_at=OBSERVED_AT, run_id=RUN_ID)
    assert output["recordCount"] == 9
    assert len(output["records"]) == 9
    assert output["programmeFamily"] == "EEA_NORWAY"
    assert output["observationState"] == "PROGRAMMING_PIPELINE"
    assert output["publicationEffect"] == "NONE"
    assert output["materialFactUse"] is False
    assert output["openCallAuthorized"] is False
    assert output["publishAuthorized"] is False
    assert output["distributionAuthorized"] is False
    assert len(output["sourcePayloadSha256"]) == 64

    required_missing = {
        "CURRENT_OFFICIAL_OPERATOR_OR_CALL_ENDPOINT",
        "EXACT_CALL_OR_TOPIC_IDENTIFIER",
        "CURRENT_OFFICIAL_CALL_STATUS",
        "SEMANTIC_RECONCILIATION",
    }
    names = set()
    for record in output["records"]:
        names.add(record["programme"])
        assert record["authorityClass"] == "T1_EEA_OFFICIAL_FMO"
        assert record["observationState"] == "PROGRAMMING_PIPELINE"
        assert record["watchPurpose"] == "OFFICIAL_OPERATOR_SOURCE_DISCOVERY"
        assert record["sourceUrl"] == module.EXPECTED_SOURCE_URL
        assert record["observedAt"] == OBSERVED_AT
        assert record["fetchedAt"] == OBSERVED_AT
        assert record["parserVersion"] == module.PARSER_VERSION
        assert record["runId"] == RUN_ID
        assert record["sourcePayloadSha256"] == output["sourcePayloadSha256"]
        assert len(record["semanticFingerprint"]) == 64
        for flag in (
            "materialFactUse",
            "openCallAuthorized",
            "deadlineAuthorized",
            "budgetAuthorized",
            "eligibilityAuthorized",
            "publishAuthorized",
            "distributionAuthorized",
        ):
            assert record[flag] is False
        assert required_missing.issubset(set(record["missingToBecomeConfirmedCall"]))
        for forbidden in ("status", "deadline", "budget", "eligibility", "callIdentifier", "topicIdentifier"):
            assert forbidden not in record
    assert len(names) == 9
    by_name = {record["programme"]: record for record in output["records"]}
    assert by_name["Green Transition"]["programmeOperator"] == "Ministry of Environment, Water and Forestry"
    assert by_name["Clean Energy Transition"]["programmeOperator"] == "The Financial Mechanism Office"
    assert by_name["Clean Energy Transition"]["fundOperator"] == "Innovation Norway"
    assert by_name["Local Development"]["programmeOperator"] == "Romanian Social Development Fund"
    assert by_name["Research and Innovation"]["programmeOperator"] == "Executive Agency for Higher Education, Research, Development and Innovation Funding"
    assert by_name["Green Business and Innovation"]["programmeOperator"] == "The Financial Mechanism Office"
    assert by_name["Green Business and Innovation"]["fundOperator"] == "Innovation Norway"
    assert by_name["Culture"]["programmeOperator"] == "Ministry of Culture"
    assert by_name["Justice"]["programmeOperator"] == "Ministry of Justice"
    assert by_name["Home Affairs"]["programmeOperator"] == "Ministry of Internal Affairs"
    assert by_name["Institutional Cooperation and Capacity Building"]["programmeOperator"] == "Ministry of Investments and European Projects"


def test_determinism() -> None:
    registry = load_registry()
    first = module.normalize_registry(registry, observed_at=OBSERVED_AT, run_id=RUN_ID)
    second = module.normalize_registry(copy.deepcopy(registry), observed_at=OBSERVED_AT, run_id=RUN_ID)
    assert first == second


def test_duplicate_programme_rejected() -> None:
    registry = load_registry()
    registry["programmes"][1]["programme"] = registry["programmes"][0]["programme"]
    expect_failure(registry, "duplicate programme")


def test_source_url_drift_rejected() -> None:
    registry = load_registry()
    registry["source"]["sourceUrl"] = "https://example.com/en/fmo/news/renewed-cooperation-romania"
    expect_failure(registry, "sourceUrl drift")


def test_source_date_drift_rejected() -> None:
    registry = load_registry()
    registry["source"]["publishedDate"] = "2026-05-13"
    expect_failure(registry, "publishedDate drift")


def test_observation_state_drift_rejected() -> None:
    registry = load_registry()
    registry["source"]["observationState"] = "OPEN_CALL"
    expect_failure(registry, "observationState drift")


def test_snapshot_drift_rejected() -> None:
    registry = load_registry()
    registry["programmes"][0]["programmeOperator"] = "Unexpected Operator"
    expect_failure(registry, "official programming snapshot drift")


def test_forbidden_material_field_rejected() -> None:
    registry = load_registry()
    registry["programmes"][0]["budget"] = "€61,815,000"
    expect_failure(registry, "forbidden call/material fields")


def test_empty_operator_rejected() -> None:
    registry = load_registry()
    registry["programmes"][0]["programmeOperator"] = ""
    expect_failure(registry, "requires programmeId, programme and programmeOperator")


def test_cli_is_deterministic() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / "out.json"
        command = [
            sys.executable,
            str(MODULE_PATH),
            "--registry",
            str(REGISTRY_PATH),
            "--observed-at",
            OBSERVED_AT,
            "--run-id",
            RUN_ID,
            "--output",
            str(output_path),
        ]
        subprocess.run(command, check=True, cwd=ROOT)
        first = output_path.read_text(encoding="utf-8")
        subprocess.run(command, check=True, cwd=ROOT)
        second = output_path.read_text(encoding="utf-8")
        assert first == second
        parsed = json.loads(first)
        assert parsed["recordCount"] == 9
        assert parsed["publicationEffect"] == "NONE"


def main() -> int:
    tests = [
        test_happy_path,
        test_determinism,
        test_duplicate_programme_rejected,
        test_source_url_drift_rejected,
        test_source_date_drift_rejected,
        test_observation_state_drift_rejected,
        test_snapshot_drift_rejected,
        test_forbidden_material_field_rejected,
        test_empty_operator_rejected,
        test_cli_is_deterministic,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} EEA Romania programming-intelligence regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
