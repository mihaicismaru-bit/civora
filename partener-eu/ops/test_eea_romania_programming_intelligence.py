#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "partener-eu" / "ingest" / "eea_romania_programming_intelligence.py"
REGISTRY = ROOT / "partener-eu" / "ingest" / "eea_romania_programming_registry.json"
spec = importlib.util.spec_from_file_location("eea_programming", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
mod.REGISTRY_PATH = REGISTRY

PROGRAMMES = [
    ("Green Transition", "€ 84,000,000", "Ministry of Environment, Water and Forestry"),
    ("Clean Energy Transition", "€ 40,000,000", "The Financial Mechanism Office. Innovation Norway is appointed Fund Operator."),
    ("Local Development", "€ 93,600,000", "Romanian Social Development Fund"),
    ("Research and Innovation", "€ 45,000,000", "Executive Agency for Higher Education, Research, Development and Innovation Funding"),
    ("Green Business and Innovation", "€ 50,000,000", "The Financial Mechanism Office. Innovation Norway is appointed Fund Operator."),
    ("Culture", "€ 40,000,000", "Ministry of Culture"),
    ("Justice", "€ 51,000,000", "Ministry of Justice"),
    ("Home Affairs", "€ 43,400,000", "Ministry of Internal Affairs"),
    ("Institutional Cooperation and Capacity Building", "€ 32,000,000", "Ministry of Investments and European Projects"),
]


def fixture(*, extra_text=""):
    blocks = ["<html><body><h2>Programmes 2021-2028</h2>"]
    for index, (name, grant, operator) in enumerate(PROGRAMMES):
        blocks.extend(
            [
                f"<h4>{name}</h4>",
                f"<p>Programme grant: {grant}</p>",
                f"<p>Programme Operator: {operator}</p>",
                "<p>Donor Programme Partner(s): Example official partner</p>",
            ]
        )
        if index == 0 and extra_text:
            blocks.append(f"<p>{extra_text}</p>")
    blocks.append("</body></html>")
    return "".join(blocks).encode("utf-8")


def assert_fail(fn, contains):
    try:
        fn()
    except Exception as exc:
        if contains.lower() not in str(exc).lower():
            raise AssertionError(f"expected {contains!r} in {exc!r}") from exc
        return
    raise AssertionError("expected failure")


def main():
    registry = mod._load_registry()
    rows = mod.parse_programme_map(fixture(), registry=registry)
    assert len(rows) == 9
    clean = next(row for row in rows if row["programme_name"] == "Clean Energy Transition")
    assert clean["programme_operator"] == "The Financial Mechanism Office"
    assert clean["fund_operator"] == "Innovation Norway"
    normalized = mod.normalize_programmes(
        rows,
        authority_url=mod.SOURCE_URL,
        fetched_at="2026-08-30T17:30:00+00:00",
        raw_hash="a" * 64,
        run_id="test-run",
        registry=registry,
    )
    assert len(normalized) == 9
    assert [row["programme_name"] for row in normalized] == [row["programme"] for row in registry["programmes"]]
    assert sum(1 for row in normalized if row["fund_operator_watch_seed"]) == 2
    for row in normalized:
        assert row["source_family"] == "EEA_NORWAY"
        assert row["observation_state"] == "PROGRAMMING_PIPELINE"
        assert row["not_a_call"] is True
        assert row["material_fact_use"] is False
        assert row["open_call_authorized"] is False
        assert row["deadline_authorized"] is False
        assert row["budget_authorized"] is False
        assert row["eligibility_authorized"] is False
        assert row["publish_authorized"] is False
        assert row["distribution_authorized"] is False
        assert row["canonical_corpus_mutation"] is False
        assert row["requires_reconciliation"] is True
        assert row["publication_effect"] == "NONE"
        assert row["programme_grant_scope"] == "PROGRAMME_ALLOCATION_NOT_CALL_BUDGET"
        assert row["programme_operator"]
        assert row["operator_watch_seed"] == row["programme_operator"]
        assert set(mod.MISSING_TO_CONFIRM_CALL).issubset(set(row["missing_to_confirm_call"]))
        assert row["raw_hash"] == "a" * 64
        assert row["parser_version"] == mod.PARSER_VERSION
        assert row["run_id"] == "test-run"
        assert row["source_published_date"] == "2026-05-12"
        assert row["semantic_fingerprint"]

    open_rows = mod.normalize_programmes(
        mod.parse_programme_map(fixture(extra_text="Open call now — deadline tomorrow"), registry=registry),
        authority_url=mod.SOURCE_URL,
        fetched_at="2026-08-30T17:30:00+00:00",
        raw_hash="b" * 64,
        run_id="lexical-open-test",
        registry=registry,
    )
    assert all(row["observation_state"] == "PROGRAMMING_PIPELINE" for row in open_rows)
    assert not any(row["open_call_authorized"] for row in open_rows)

    incomplete = fixture().decode("utf-8").replace(
        "<h4>Institutional Cooperation and Capacity Building</h4><p>Programme grant: € 32,000,000</p><p>Programme Operator: Ministry of Investments and European Projects</p><p>Donor Programme Partner(s): Example official partner</p>",
        "",
    ).encode("utf-8")
    assert_fail(lambda: mod.parse_programme_map(incomplete, registry=registry), "missing expected marker")

    missing_operator = fixture().decode("utf-8").replace("<p>Programme Operator: Ministry of Justice</p>", "").encode("utf-8")
    assert_fail(lambda: mod.parse_programme_map(missing_operator, registry=registry), "grant/operator required")

    grant_drift = fixture().decode("utf-8").replace("€ 51,000,000", "€ 51,000,001").encode("utf-8")
    assert_fail(lambda: mod.parse_programme_map(grant_drift, registry=registry), "allocation drift")

    operator_drift = fixture().decode("utf-8").replace("Programme Operator: Ministry of Culture", "Programme Operator: Other Ministry").encode("utf-8")
    assert_fail(lambda: mod.parse_programme_map(operator_drift, registry=registry), "operator drift")

    fund_operator_drift = fixture().decode("utf-8").replace(
        "The Financial Mechanism Office. Innovation Norway is appointed Fund Operator.",
        "The Financial Mechanism Office. Other Operator is appointed Fund Operator.",
        1,
    ).encode("utf-8")
    assert_fail(lambda: mod.parse_programme_map(fund_operator_drift, registry=registry), "fund operator drift")

    assert_fail(
        lambda: mod.normalize_programmes(
            rows,
            authority_url="https://example.com/en/fmo/news/renewed-cooperation-romania",
            fetched_at="2026-08-30T17:30:00+00:00",
            raw_hash="c" * 64,
            run_id="bad-authority",
            registry=registry,
        ),
        "non-official",
    )
    assert_fail(
        lambda: mod.normalize_programmes(
            rows,
            authority_url="https://eeagrants.org/en/fmo/news/something-else",
            fetched_at="2026-08-30T17:30:00+00:00",
            raw_hash="d" * 64,
            run_id="bad-path",
            registry=registry,
        ),
        "unexpected Romania programme-map path",
    )
    assert_fail(
        lambda: mod.normalize_programmes(
            rows,
            authority_url=mod.SOURCE_URL,
            fetched_at="2026-08-30T17:30:00+00:00",
            raw_hash="not-a-hash",
            run_id="bad-hash",
            registry=registry,
        ),
        "sha-256",
    )

    tampered = json.loads(json.dumps(registry))
    tampered["programmes"][0]["programmeOperator"] = "Tampered operator"
    assert_fail(lambda: mod.parse_programme_map(fixture(), registry=tampered), "operator drift")

    print("PASS EEA Romania programming intelligence is live, registry-bound, provenance-complete and non-authorizing")


if __name__ == "__main__":
    main()
