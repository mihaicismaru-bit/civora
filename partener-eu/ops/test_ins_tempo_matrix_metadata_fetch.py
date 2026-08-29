#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "ingest" / "ins_tempo_matrix_metadata_fetch.py"
SOURCE_PATH = Path(__file__).parents[1] / "ingest" / "ins_tempo_matrix_metadata_source.json"
spec = importlib.util.spec_from_file_location("ins_tempo_matrix_metadata_fetch", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

FIXTURE = b"""<!doctype html><html><head><title>TEMPO Online</title></head><body>
<main>
<h1>FOM106D - Castigul salarial mediu net lunar pe activitati ale economiei nationale</h1>
<p>Periodicitate: Lunar.</p>
<p>Sursa datelor: Cercetarea statistica lunara asupra castigurilor salariale.</p>
<p>Ultima perioada din aceasta serie: Luna decembrie 2025. Dupa aceasta perioada seria se continua cu matricea FOM106G.</p>
</main>
</body></html>"""


def expect_value_error(fn, *args) -> None:
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def main() -> int:
    mod.validate_authority_url(mod.DEFAULT_URL)
    expect_value_error(mod.validate_authority_url, "http://statistici.insse.ro/tempoins/index.jsp?ind=FOM106D")
    expect_value_error(mod.validate_authority_url, "https://example.org/tempoins/index.jsp?ind=FOM106D")
    expect_value_error(mod.validate_authority_url, "https://statistici.insse.ro/shop/index.jsp?ind=FOM106D")
    assert mod.matrix_code_from_url(mod.DEFAULT_URL) == "FOM106D"
    assert mod.matrix_code_from_url("https://statistici.insse.ro/tempoins/index.jsp?page=tempo2") is None

    metadata = mod.extract_matrix_metadata(FIXTURE, mod.DEFAULT_URL)
    assert metadata["matrix_code"] == "FOM106D"
    assert metadata["matrix_title"] and "Castigul salarial" in metadata["matrix_title"]
    assert metadata["periodicity"] and metadata["periodicity"].lower().startswith("lunar")
    assert metadata["data_source_note"] and "Cercetarea statistica" in metadata["data_source_note"]
    assert metadata["last_period_note"] == "Luna decembrie 2025"
    assert metadata["continuation_matrix_code"] == "FOM106G"

    evidence = mod.build_evidence(
        FIXTURE,
        requested_url=mod.DEFAULT_URL,
        final_url=mod.DEFAULT_URL,
        status=200,
        content_type="text/html",
        fetched_at="2026-08-29T00:00:00+00:00",
        run_id="test",
    )
    mod.validate_evidence(evidence)
    assert evidence["adapter_id"] == "INS_TEMPO_MATRIX_METADATA_V1"
    assert evidence["parser_version"] == "INS_TEMPO_MATRIX_METADATA_FETCH_V1"
    assert evidence["source_id"] == "SRC-INS-TEMPO-MATRIX-METADATA"
    assert evidence["source_family"] == "ROMANIA_INS"
    assert evidence["programme_family"] == "STATISTICAL_INTELLIGENCE"
    assert evidence["authority_class"] == "T1_OFFICIAL_STATISTICAL_DATABASE"
    assert evidence["observation_state"] == "MATRIX_METADATA_DISCOVERY"
    assert evidence["raw_sha256"] == mod.sha256_bytes(FIXTURE)
    assert evidence["material_fact_use"] is False
    assert evidence["statistical_value_authorized"] is False
    assert evidence["publish_authorized"] is False
    assert evidence["requires_exact_matrix_query"] is True
    assert evidence["requires_semantic_reconcile"] is True
    required = {
        "exact_matrix_code",
        "exact_dimension_and_value_selections",
        "exact_period",
        "exact_territory_or_universe",
        "official_query_or_export_response",
        "semantic_reconciliation",
    }
    assert required.issubset(set(evidence["missing_for_statistical_value_confirmation"]))

    hostile = dict(evidence)
    hostile["statistical_value_authorized"] = True
    expect_value_error(mod.validate_evidence, hostile)

    mismatched = dict(evidence)
    mismatched["matrix_code"] = "POP107D"
    expect_value_error(mod.validate_evidence, mismatched)

    no_code = b"<html><body>Unrelated official page</body></html>"
    expect_value_error(mod.extract_matrix_metadata, no_code, mod.DEFAULT_URL)

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))["source"]
    assert source["id"] == mod.SOURCE_ID
    assert source["url"] == mod.DEFAULT_URL
    assert source["tier"] == "T1"
    assert source["authority_scope"] == "MATRIX_METADATA_DISCOVERY"
    assert source["observation_state"] == mod.OBSERVATION_STATE
    assert source["adapter_required"] == mod.ADAPTER_ID
    assert source["material_fact_use"] is False
    assert set(source["source_families"]) >= {"ROMANIA", "INS", "STATISTICAL_INTELLIGENCE"}

    print("PASS INS TEMPO exact-matrix metadata acquisition is official, bounded and non-authorizing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
