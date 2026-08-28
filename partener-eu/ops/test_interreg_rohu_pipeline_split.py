#!/usr/bin/env python3
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
DATA_PLANE = ROOT / "partener-eu" / "ingest" / "data_plane_contract.json"
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import interreg_programming_live_fetch as live  # noqa: E402

CURRENT_ID = "SRC-INTERREG-ROHU"
PIPELINE_ID = "SRC-INTERREG-ROHU-2028-2034"
PIPELINE_PROGRAMME = "Interreg Romania-Hungary 2028-2034"
PIPELINE_URL = "https://interreg-rohu.eu/ro/programare-2027/"


def main() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    plane = json.loads(DATA_PLANE.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in registry.get("sources", [])}

    current = by_id[CURRENT_ID]
    pipeline = by_id[PIPELINE_ID]

    assert "future_programming_consultations" not in set(current.get("extract") or [])
    assert current["material_fact_use"] is True
    assert current["observation_state"] == "CURRENT_PROGRAMME"
    assert "PROGRAMMING_PIPELINE" not in set(current.get("source_families") or [])

    assert pipeline["tier"] == "T1"
    assert pipeline["url"] == PIPELINE_URL
    assert pipeline["programmes"] == [PIPELINE_PROGRAMME]
    assert set(pipeline["source_families"]) == {"INTERREG", "CBC", "PROGRAMMING_PIPELINE"}
    assert pipeline["authority_scope"] == "PROGRAMMING_FRAMEWORK"
    assert pipeline["observation_state"] == "PROGRAMMING_PIPELINE"
    assert pipeline["material_fact_use"] is False
    assert pipeline["credentials_required"] is False
    note = pipeline.get("note", "").upper()
    assert "OPEN_CALL" in note
    assert "DEADLINE" in note
    assert "BUDGET" in note
    assert "ELIGIBILITY" in note

    domains = set((plane.get("programmeDomains") or {}).get(PIPELINE_PROGRAMME) or [])
    assert domains == {"INTERREG_CBC", "PROGRAMMING_FUTURE"}

    selected_ids = {row["id"] for row in live._programming_sources(registry)}
    assert PIPELINE_ID in selected_ids
    assert CURRENT_ID not in selected_ids

    print(
        "PASS ROHU pipeline split: current programme remains call-capable only at exact-call evidence; "
        "2028-2034 programming is a dedicated non-authorizing source"
    )


if __name__ == "__main__":
    main()
