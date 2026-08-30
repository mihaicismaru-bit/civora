#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "partener-eu" / "ingest" / "eea_romania_programming_intelligence.py"
spec = importlib.util.spec_from_file_location("eea_programming", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

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
    rows = mod.parse_programme_map(fixture())
    assert len(rows) == 9
    normalized = mod.normalize_programmes(
        rows,
        authority_url=mod.SOURCE_URL,
        fetched_at="2026-08-30T17:30:00+00:00",
        raw_hash="a" * 64,
        run_id="test-run",
    )
    assert len(normalized) == 9
    assert [row["programme_name"] for row in normalized] == list(mod.EXPECTED_PROGRAMMES)
    for row in normalized:
        assert row["source_family"] == "EEA_NORWAY"
        assert row["observation_state"] == "PROGRAMMING_PIPELINE"
        assert row["not_a_call"] is True
        assert row["material_fact_use"] is False
        assert row["open_call_authorized"] is False
        assert row["publish_authorized"] is False
        assert row["canonical_corpus_mutation"] is False
        assert row["publication_effect"] == "NONE"
        assert row["programme_grant_scope"] == "PROGRAMME_ALLOCATION_NOT_CALL_BUDGET"
        assert row["programme_operator"]
        assert row["operator_watch_seed"] == row["programme_operator"]
        assert set(mod.MISSING_TO_CONFIRM_CALL).issubset(set(row["missing_to_confirm_call"]))
        assert row["raw_hash"] == "a" * 64
        assert row["parser_version"] == mod.PARSER_VERSION
        assert row["run_id"] == "test-run"
        assert row["semantic_fingerprint"]

    # Strong lexical OPEN signals on a programming page must never upgrade the observation.
    open_rows = mod.normalize_programmes(
        mod.parse_programme_map(fixture(extra_text="Open call now — deadline tomorrow")),
        authority_url=mod.SOURCE_URL,
        fetched_at="2026-08-30T17:30:00+00:00",
        raw_hash="b" * 64,
        run_id="lexical-open-test",
    )
    assert all(row["observation_state"] == "PROGRAMMING_PIPELINE" for row in open_rows)
    assert not any(row["open_call_authorized"] for row in open_rows)

    # Missing any agreed programme makes the whole programming snapshot unusable.
    incomplete = fixture().decode("utf-8").replace(
        "<h4>Institutional Cooperation and Capacity Building</h4><p>Programme grant: € 32,000,000</p><p>Programme Operator: Ministry of Investments and European Projects</p><p>Donor Programme Partner(s): Example official partner</p>",
        "",
    ).encode("utf-8")
    assert_fail(lambda: mod.parse_programme_map(incomplete), "missing expected marker")

    # Programme grant/operator are required, but remain programme-level evidence only.
    missing_operator = fixture().decode("utf-8").replace(
        "<p>Programme Operator: Ministry of Justice</p>", ""
    ).encode("utf-8")
    assert_fail(lambda: mod.parse_programme_map(missing_operator), "grant/operator required")

    # Authority pinning is strict.
    assert_fail(
        lambda: mod.normalize_programmes(
            rows,
            authority_url="https://example.com/en/fmo/news/renewed-cooperation-romania",
            fetched_at="2026-08-30T17:30:00+00:00",
            raw_hash="c" * 64,
            run_id="bad-authority",
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
        ),
        "unexpected Romania programme-map path",
    )

    print("PASS EEA Romania 2021-2028 programming intelligence stays complete, provenance-bound and non-authorizing")


if __name__ == "__main__":
    main()
