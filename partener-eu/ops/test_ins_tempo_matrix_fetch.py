#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "ingest" / "ins_tempo_matrix_fetch.py"
SOURCE_PATH = Path(__file__).parents[1] / "ingest" / "ins_tempo_matrix_source.json"
spec = importlib.util.spec_from_file_location("ins_tempo_matrix_fetch", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

FIXTURE = b"""<!doctype html><html><head><title>INSSE - TEMPO-Online - FOM106D</title></head><body>
<header>INSTITUTUL NATIONAL DE STATISTICA</header>
<main><h1>TEMPO INS</h1><p>FOM106D - Castigul salarial mediu net lunar pe activitati.</p>
<p>Intrerupere serie. Ultima perioada din aceasta serie: Luna decembrie 2025.</p>
<p>Dupa aceasta perioada seria se continua cu matricea FOM106G.</p>
<p>Metadate statistice oficiale pentru interogarea matricei TEMPO.</p></main></body></html>"""


def expect_value_error(fn, *args) -> None:
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def main() -> int:
    assert mod.normalize_matrix_code("fom106g") == "FOM106G"
    expect_value_error(mod.normalize_matrix_code, "FOM-106G")
    expect_value_error(mod.normalize_matrix_code, "../FOM106G")

    canonical = mod.build_matrix_url("FOM106D")
    mod.validate_matrix_url(canonical, "FOM106D")
    expect_value_error(mod.validate_matrix_url, "http://statistici.insse.ro/tempoins/index.jsp?ind=FOM106D&lang=ro&page=tempo3")
    expect_value_error(mod.validate_matrix_url, "https://example.org/tempoins/index.jsp?ind=FOM106D&lang=ro&page=tempo3")
    expect_value_error(mod.validate_matrix_url, "https://statistici.insse.ro/shop/?ind=FOM106D&lang=ro&page=tempo3")
    expect_value_error(mod.validate_matrix_url, "https://statistici.insse.ro/tempoins/index.jsp?ind=FOM106G&lang=ro&page=tempo3", "FOM106D")

    metadata = mod.parse_metadata(FIXTURE, "FOM106D")
    assert metadata["title"].startswith("INSSE - TEMPO-Online")
    assert "FOM106G" in metadata["related_matrix_codes"]
    assert len(metadata["semantic_sha256"]) == 64

    evidence = mod.build_evidence(
        FIXTURE,
        matrix_code="FOM106D",
        requested_url=canonical,
        final_url=canonical,
        status=200,
        content_type="text/html; charset=UTF-8",
        fetched_at="2026-08-29T00:00:00+00:00",
        run_id="test",
    )
    mod.validate_evidence(evidence)
    assert evidence["source_id"] == "SRC-INS-TEMPO-MATRIX-METADATA"
    assert evidence["adapter_id"] == "INS_TEMPO_MATRIX_METADATA_V1"
    assert evidence["parser_version"] == "INS_TEMPO_MATRIX_FETCH_V1"
    assert evidence["source_family"] == "ROMANIA_INS"
    assert evidence["authority_class"] == "T1_OFFICIAL_STATISTICAL_AUTHORITY"
    assert evidence["observation_state"] == "MATRIX_METADATA_DISCOVERY"
    assert evidence["matrix_code"] == "FOM106D"
    assert evidence["raw_sha256"] == mod.sha256_bytes(FIXTURE)
    assert evidence["material_fact_use"] is False
    assert evidence["statistical_value_authorized"] is False
    assert evidence["publish_authorized"] is False
    assert evidence["requires_exact_query_provenance"] is True
    assert evidence["requires_semantic_reconcile"] is True
    required = {
        "exact_dimension_selection",
        "exact_period_selection",
        "exact_territory_or_universe",
        "official_value_payload_or_export",
        "semantic_reconciliation",
    }
    assert required.issubset(set(evidence["missing_for_statistical_value_confirmation"]))

    hostile = dict(evidence)
    hostile["statistical_value_authorized"] = True
    expect_value_error(mod.validate_evidence, hostile)

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))["source"]
    assert source["id"] == mod.SOURCE_ID
    assert source["tier"] == "T1"
    assert source["authority_scope"] == "MATRIX_METADATA_DISCOVERY"
    assert source["observation_state"] == "MATRIX_METADATA_DISCOVERY"
    assert source["adapter_required"] == mod.ADAPTER_ID
    assert source["material_fact_use"] is False
    assert source["statistical_value_authorized"] is False
    assert set(source["source_families"]) >= {"ROMANIA", "INS", "MARKET_INTELLIGENCE"}

    print("PASS INS TEMPO exact-matrix metadata acquisition is official, bounded and non-authorizing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
