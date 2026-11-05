#!/usr/bin/env python3
"""Fail-closed, read-only replay of the AFIR solar 3/2026 aggregate observation.

This checks the staged observation's internal contract; it does NOT replace
raw workbook SHA verification, session equivalence or publication review.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
OBSERVATION = ROOT / "partener-eu/validation/afir-solar-3-2026-aggregate-observation.json"
DOCUMENTS = {
    "Selectate": (
        "https://stportalafirprod.blob.core.windows.net/media/media/45pgvsbh/raport-final-de-selectie-solar-peste-1mw-selectate.xlsx",
        "eb520dcc4979e2de5b216b1cb528ffa6b48bce0e849fe44e3ec7e0f07027cd74",
        60, 89033526,
    ),
    "Nefinanțate": (
        "https://stportalafirprod.blob.core.windows.net/media/media/ftab3hsy/raport-final-de-selectie-solar-peste-1mw-nefinantate.xlsx",
        "44231f161ba5f816b44d2d9e164c03f48f749d791e7e87f760d65e5806759bec",
        10, 14212709,
    ),
}


def iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.utcoffset() is not None, "Missing source timestamp timezone"
    return parsed


def verify(receipt: dict) -> None:
    assert receipt["schema"] == "PARTENER_AFIR_SOLAR_3_2026_AGGREGATE_OBSERVATION_V1"
    assert receipt["status"] == "AGGREGATES_VERIFIED_PENDING_SESSION_IDENTITY_AND_CANONICAL_RECONCILIATION"
    assert receipt["source_family"] == "AFIR"
    assert receipt["programme"] == "FONDUL_MODERNIZARE_ENERGIE_SOLAR"
    assert receipt["authority_class"] == "OFFICIAL_AFIR_REPORT_INDEX_DELEGATED_DOCUMENT"
    assert receipt["index_session_identifier"] == "ENERGIE / 3 / 2026"
    assert receipt["workbook_internal_session_identifier"] == "FM - 06/26 - 14.08.2026"
    assert receipt["document_binding_state"] == "SOURCE_INDEX_DELEGATED_XLSX_CATEGORY_AND_PERIOD_VERIFIED"
    assert receipt["document_binding_scope"] == "REPORT_DOCUMENT_ONLY_NOT_CALL_IDENTIFIER_EQUIVALENCE"
    # These identities are NOT independently established as equivalent.
    assert receipt["session_identity_reconciliation"] == "REQUIRED"
    assert receipt["index_session_identifier"] != receipt["workbook_internal_session_identifier"]
    assert receipt["official_publication_date"] == "2026-11-03"
    assert receipt["report_period"] == "15.06.2026–14.08.2026"
    assert receipt["official_index_url"] == "https://www.afir.ro/rapoarte/rapoarte-feadr/selectie/"
    assert receipt["official_notice_url"] == "https://www.afir.ro/info-la-zi/raport-final-de-selectie-schema-de-energie-solar-peste-1-mw/"
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["official_index_sha256"])
    assert receipt["run_id"] == "42036605252" and receipt["raw_artifact_id"] == 13419065989
    assert receipt["raw_artifact_url"].endswith("/actions/runs/42036605252/artifacts/13419065989")
    assert receipt["parser_version"] and receipt["raw_acquisition_parser_version"]
    assert iso_utc(receipt["fetched_at"])
    assert receipt["observation_state"] == "SELECTION_RESULTS_AGGREGATE_RECONCILIATION_PENDING"
    assert receipt["open_call_authorized"] is False
    assert receipt["publish_authorized"] is False
    assert receipt["material_fact_use"] is False
    assert receipt["publication_effect"] == "NONE"
    assert receipt["replay"] and receipt["rollback"]

    docs = receipt["source_documents"]
    assert set(docs) == set(DOCUMENTS)
    for category, (url, digest, count, amount) in DOCUMENTS.items():
        doc = docs[category]
        assert doc["source_url"] == url and urlsplit(url).hostname == "stportalafirprod.blob.core.windows.net"
        assert doc["sha256"] == digest and re.fullmatch(r"[0-9a-f]{64}", doc["sha256"])
        assert 0 < doc["bytes"] <= 25_000_000
        assert iso_utc(doc["fetched_at"])
        assert doc["count"] == count and int(doc["total_public_eur"]) == amount
        assert doc["worksheet_title"].startswith("Lista proiectelor ")
    a = receipt["aggregates"]
    assert a["selected_projects"] == docs["Selectate"]["count"]
    assert a["unfinanced_projects"] == docs["Nefinanțate"]["count"]
    assert a["submitted_projects"] == a["selected_projects"] + a["unfinanced_projects"]
    assert a["selected_public_value_eur"] == int(docs["Selectate"]["total_public_eur"])
    assert a["unfinanced_public_value_eur"] == int(docs["Nefinanțate"]["total_public_eur"])
    assert a["submitted_public_value_eur"] == a["selected_public_value_eur"] + a["unfinanced_public_value_eur"]
    assert a["unfinanced_group_label"] == "Proiecte neeligibile"
    assert a["session_allocation_eur"] == 120000000
    controls = receipt["controls"]
    assert all(controls[k] is True for k in (
        "manifest_hashes_rechecked", "worksheet_serial_counts_verified",
        "cross_report_metadata_equal", "submitted_equals_selected_plus_unfinanced",
        "submitted_value_equals_selected_plus_unfinanced",
        "individual_beneficiary_rows_excluded",
        "official_index_delegation_and_sheet_period_verified",
        "workbook_selection_categories_verified",
    ))
    assert "beneficiaries" not in receipt and "rows" not in receipt


def main() -> int:
    original = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    verify(original)
    # Adversarial replay: no identity shortcut, unauthorized publication,
    # changed source URL/hash, or fabricated count may pass silently.
    mutations = [
        ("session_identity_reconciliation", "CONFIRMED"),
        ("document_binding_state", "CALL_ALIAS_CONFIRMED"),
        ("document_binding_scope", "OPEN_CALL"),
        ("open_call_authorized", True),
        ("publish_authorized", True),
        ("material_fact_use", True),
        ("publication_effect", "PUBLIC"),
        ("index_session_identifier", "FM - 06/26 - 14.08.2026"),
        ("observation_state", "OPEN_CALL"),
    ]
    denied = 0
    for key, value in mutations:
        candidate = copy.deepcopy(original)
        candidate[key] = value
        try:
            verify(candidate)
        except AssertionError:
            denied += 1
        else:
            raise AssertionError(f"Unsafe aggregate mutation admitted: {key}")
    for category, key, value in (
        ("Selectate", "count", 61),
        ("Nefinanțate", "source_url", "https://example.org/untrusted.xlsx"),
        ("Selectate", "sha256", "0" * 64),
    ):
        candidate = copy.deepcopy(original)
        candidate["source_documents"][category][key] = value
        try:
            verify(candidate)
        except AssertionError:
            denied += 1
        else:
            raise AssertionError(f"Unsafe source-document mutation admitted: {category}.{key}")
    print(json.dumps({"status": "PASS", "negative_replays_rejected": denied,
                      "submitted": 70, "selected": 60, "unfinanced": 10,
                      "publication_effect": "NONE"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
