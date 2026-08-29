#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "ingest" / "regiocentru_actions_fetch.py"
SOURCE_PATH = Path(__file__).parents[1] / "ingest" / "regiocentru_actions_source.json"
spec = importlib.util.spec_from_file_location("regiocentru_actions_fetch", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

FIXTURE = b"""<!doctype html><html><body>
<nav><a href='/'>Home</a></nav>
<main>
<a href='/actiuni/p-7-actiunea-7-3/'>P 7 - Actiunea 7.3</a>
<a href='https://www.regiocentru.ro/actiuni/p-1-actiunea-1-3-3/'>P 1 - Actiunea 1.3.3</a>
<a href='/actiuni/p-7-actiunea-7-3/'>duplicate</a>
<a href='https://example.org/actiuni/hostile/'>foreign</a>
<a href='/stiri/anunt/'>news</a>
</main></body></html>"""


def expect_value_error(fn, *args) -> None:
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def main() -> int:
    mod.validate_authority_url("https://www.regiocentru.ro/actiuni/")
    mod.validate_authority_url("https://regiocentru.ro/actiuni/p-7-actiunea-7-3/")
    expect_value_error(mod.validate_authority_url, "http://www.regiocentru.ro/actiuni/")
    expect_value_error(mod.validate_authority_url, "https://example.org/actiuni/")
    expect_value_error(mod.validate_authority_url, "https://www.regiocentru.ro/stiri/")

    rows = mod.extract_action_candidates(FIXTURE, "https://www.regiocentru.ro/actiuni/")
    assert len(rows) == 2, rows
    assert all(row["detail_url_candidate"].startswith("https://www.regiocentru.ro/actiuni/") for row in rows)
    assert [row["detail_url_candidate"] for row in rows] == sorted(row["detail_url_candidate"] for row in rows)

    evidence = mod.build_evidence(
        FIXTURE,
        requested_url="https://www.regiocentru.ro/actiuni/",
        final_url="https://www.regiocentru.ro/actiuni/",
        status=200,
        content_type="text/html",
        fetched_at="2026-08-29T00:00:00+00:00",
        run_id="test",
    )
    mod.validate_evidence(evidence)
    assert evidence["adapter_id"] == "REGIOCENTRU_ACTIONS_V1"
    assert evidence["parser_version"] == "REGIOCENTRU_ACTIONS_FETCH_V1"
    assert evidence["source_id"] == "SRC-ADR-CENTRU-PR-ACTIONS"
    assert evidence["source_family"] == "ROMANIA_ADR"
    assert evidence["programme_family"] == "PROGRAMUL_REGIUNEA_CENTRU_2021_2027"
    assert evidence["authority_class"] == "T1_MANAGING_AUTHORITY"
    assert evidence["requested_url"] == mod.DEFAULT_URL
    assert evidence["final_url"] == mod.DEFAULT_URL
    assert evidence["action_candidate_count"] == 2
    assert evidence["raw_sha256"] == mod.sha256_bytes(FIXTURE)
    assert evidence["observation_state"] == "CALL_INDEX_DISCOVERY"
    assert evidence["material_fact_use"] is False
    assert evidence["open_call_authorized"] is False
    assert evidence["publish_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["budget_authorized"] is False
    assert evidence["eligibility_authorized"] is False
    assert evidence["requires_exact_action_endpoint"] is True
    assert evidence["requires_semantic_reconcile"] is True
    assert "exact_call_or_mysmis_identifier" in evidence["missing_for_open_confirmation"]
    assert "semantic_reconciliation" in evidence["missing_for_open_confirmation"]

    hostile = dict(evidence)
    hostile["open_call_authorized"] = True
    expect_value_error(mod.validate_evidence, hostile)

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))["source"]
    assert source["id"] == mod.SOURCE_ID
    assert source["url"] == mod.DEFAULT_URL
    assert source["tier"] == "T1"
    assert source["authority_scope"] == "CALL_INDEX_DISCOVERY"
    assert source["observation_state"] == "CALL_INDEX_DISCOVERY"
    assert source["adapter_required"] == mod.ADAPTER_ID
    assert source["material_fact_use"] is False
    assert set(source["source_families"]) >= {"ROMANIA", "ADR", "CALL_REGISTRY"}

    print("PASS Regiunea Centru action-index acquisition is official, bounded and discovery-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
