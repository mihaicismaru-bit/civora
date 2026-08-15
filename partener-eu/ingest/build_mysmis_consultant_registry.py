#!/usr/bin/env python3
"""Build the Consultant Workspace MySMIS evidence projection.

The projection is deliberately narrower than the public news feed. It accepts
only the direct, canonical MySMIS public-reporting snapshot persisted by the
MIPE ingestion pipeline. Search snippets, proxy copies and inferred statuses
are never projected as consultant evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
OUTPUT_PATH = ROOT / "partener-eu" / "web" / "mysmis-registry.js"
OFFICIAL_HOST = "reporting.mysmis2021.gov.ro"
DEFAULT_URL = "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_call(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    title = str(row.get("call") or "").strip()
    programme = str(row.get("programme") or "").strip()
    if not title or not programme:
        return None
    return {
        "programme": programme,
        "call": title,
        "officialStatus": str(row.get("officialStatus") or "NEPRECIZAT").strip(),
        "entities": str(row.get("entities") or "").strip(),
        "sketches": str(row.get("sketches") or "").strip(),
        "submitted": str(row.get("submitted") or "").strip(),
        "contracts": str(row.get("contracts") or "").strip(),
        "withdrawn": str(row.get("withdrawn") or "").strip(),
        "callBudgetRon": str(row.get("callBudgetRon") or "").strip(),
    }


def main() -> int:
    state = load_state()
    run = state.get("lastRun") if isinstance(state.get("lastRun"), dict) else {}
    snapshot = run.get("registrySnapshot") if isinstance(run.get("registrySnapshot"), dict) else {}

    canonical_url = str(snapshot.get("canonicalUrl") or DEFAULT_URL).strip()
    parsed = urlparse(canonical_url)
    direct_only = snapshot.get("directOnly") is True
    snapshot_ok = snapshot.get("status") == "OK"
    official = parsed.scheme == "https" and (parsed.hostname or "").lower() == OFFICIAL_HOST

    calls: list[dict] = []
    if direct_only and snapshot_ok and official:
        for row in snapshot.get("calls") or []:
            cleaned = clean_call(row)
            if cleaned:
                calls.append(cleaned)

    explicit_statuses = sorted({c["officialStatus"] for c in calls if c["officialStatus"]})
    status = "OK_DIRECT" if calls else "UNAVAILABLE_FAIL_CLOSED"
    observed_at = str(snapshot.get("observedAt") or run.get("observedAt") or "")
    validated_count = snapshot.get("validatedCallCount") if calls else None
    visible_count = len(calls)

    payload = {
        "status": status,
        "observedAt": observed_at,
        "directOnly": True,
        "source": {
            "institution": "Ministerul Investițiilor și Proiectelor Europene",
            "system": "MySMIS2021 / SMIS2021+ — raportare publică",
            "canonicalUrl": canonical_url if official else DEFAULT_URL,
            "trustClass": "T1",
            "retrieval": "CANONICAL_OFFICIAL_FETCH" if calls else "UNAVAILABLE",
        },
        "title": str(snapshot.get("title") or "Finanțări programe 2021-2027").strip(),
        "validatedCallCount": validated_count,
        "visibleRowCount": visible_count,
        "paginationText": str(snapshot.get("paginationText") or "").strip(),
        "explicitStatuses": explicit_statuses,
        "calls": calls,
        "notice": (
            "Snapshot direct din registrul public MySMIS. Statusurile sunt afișate literal și nu modifică "
            "automat statusul canonic al unui apel fără reconciliere cu ghidul și calendarul oficial."
            if calls
            else "Registrul MySMIS nu a putut fi verificat direct în ultima rulare. Modulul păstrează starea fail-closed."
        ),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    script = "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
    script += "window.PARTENER_DATA.mysmisRegistry=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    OUTPUT_PATH.write_text(script, encoding="utf-8")
    print(json.dumps({
        "status": status,
        "observedAt": observed_at,
        "visibleRowCount": visible_count,
        "validatedCallCount": validated_count,
        "canonicalUrl": payload["source"]["canonicalUrl"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
