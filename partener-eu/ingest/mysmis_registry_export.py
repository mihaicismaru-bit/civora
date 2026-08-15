#!/usr/bin/env python3
"""Project the latest direct MySMIS registry snapshot into structured data.

The source snapshot is produced by ``mipe_discovery_ingest.py`` through a
TLS-verified request to the official MySMIS reporting host. This exporter never
changes call status semantics: strings such as FINALIZAT are preserved exactly
as published and are not converted to PARTENER.EU OPEN/CLOSED states.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MIPE_STATE = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
OUT_JSON = ROOT / "partener-eu" / "ingest" / "state" / "mysmis_registry.json"
OUT_JS = ROOT / "partener-eu" / "web" / "mysmis-registry.js"
SOURCE_URL = "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"


def load() -> dict[str, Any]:
    if not MIPE_STATE.exists():
        raise SystemExit("MIPE state missing")
    return json.loads(MIPE_STATE.read_text(encoding="utf-8"))


def main() -> int:
    state = load()
    item = next(
        (
            row
            for row in state.get("items", [])
            if isinstance(row, dict)
            and row.get("url") == SOURCE_URL
            and row.get("verification") == "CANONICAL_OFFICIAL_FETCH"
        ),
        None,
    )
    if not item:
        # Fail closed and preserve the previous export. A run without a direct
        # canonical MySMIS snapshot cannot replace trusted registry data.
        print(json.dumps({"status": "NO_DIRECT_MYSMIS_SNAPSHOT_PRESERVED"}, ensure_ascii=False))
        return 0

    snapshot = item.get("registrySnapshot") or {}
    if not isinstance(snapshot, dict) or not snapshot:
        raise SystemExit("Direct MySMIS item has no registrySnapshot")

    calls: list[dict[str, Any]] = []
    for source_id, row in snapshot.items():
        if not isinstance(row, dict):
            continue
        canonical_key = hashlib.sha256(
            f"{row.get('programme', '')}\n{row.get('call', '')}".encode("utf-8")
        ).hexdigest()[:20]
        # Keep both IDs: source_id is the historical snapshot identity; the
        # recomputed key makes integrity verification deterministic.
        calls.append(
            {
                "id": source_id,
                "integrityId": canonical_key,
                "programme": row.get("programme", ""),
                "callType": row.get("type", ""),
                "call": row.get("call", ""),
                "officialStatus": row.get("status", ""),
                "entities": row.get("entities", ""),
                "drafts": row.get("drafts", ""),
                "submitted": row.get("submitted", ""),
                "contracts": row.get("contracts", ""),
                "withdrawn": row.get("withdrawn", ""),
                "callBudgetRon": row.get("callBudgetRon", ""),
                "totalProjectBudgetRon": row.get("totalProjectBudgetRon", ""),
                "submittedGrantBudgetRon": row.get("submittedGrantBudgetRon", ""),
            }
        )

    calls.sort(key=lambda row: (row["programme"], row["call"]))
    payload = {
        "schema": "CIVORA_MYSMIS_REGISTRY_V1",
        "source": {
            "institution": "MySMIS 2021-2027 / MIPE",
            "canonicalUrl": SOURCE_URL,
            "trustClass": "T1",
            "verification": "CANONICAL_OFFICIAL_FETCH",
            "observedAt": item.get("observedAt"),
            "dateLabel": item.get("dateLabel"),
        },
        "validatedCallCount": item.get("validatedCallCount"),
        "visibleRowCount": len(calls),
        "explicitStatuses": item.get("explicitStatuses") or [],
        "calls": calls,
        "contentHash": hashlib.sha256(
            json.dumps(calls, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "notice": (
            "Snapshot direct al tabelului vizibil MySMIS. Statusurile sunt "
            "păstrate literal; lipsa unei linii nu dovedește inexistența apelului."
        ),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        "window.PARTENER_DATA.mysmisRegistry="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "EXPORTED",
                "visibleRowCount": len(calls),
                "validatedCallCount": payload["validatedCallCount"],
                "contentHash": payload["contentHash"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
