#!/usr/bin/env python3
"""Build the Consultant Workspace MySMIS evidence projection.

The projection is deliberately narrower than the public news feed. It accepts
only a direct, canonical MySMIS public-reporting snapshot persisted by the MIPE
ingestion pipeline. Search snippets, proxy copies and inferred statuses are
never projected as consultant evidence.

Two durable input layouts are supported because the MIPE runtime evolved:

* current layout: a directly verified MIPE/MySMIS item whose
  ``registrySnapshot`` is a mapping keyed by deterministic row identifiers;
* legacy layout: ``lastRun.registrySnapshot`` with an explicit ``calls`` list.

Both paths are fail-closed and require the canonical reporting host.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
OUTPUT_PATH = ROOT / "partener-eu" / "web" / "mysmis-registry.js"
OFFICIAL_HOST = "reporting.mysmis2021.gov.ro"
DEFAULT_URL = "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def official_reporting_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == OFFICIAL_HOST


def clean_call(row: dict[str, Any]) -> dict[str, str] | None:
    if not isinstance(row, dict):
        return None
    title = str(row.get("call") or "").strip()
    programme = str(row.get("programme") or "").strip()
    if not title or not programme:
        return None
    return {
        "programme": programme,
        "call": title,
        "officialStatus": str(row.get("officialStatus") or row.get("status") or "NEPRECIZAT").strip(),
        "entities": str(row.get("entities") or "").strip(),
        "sketches": str(row.get("sketches") or row.get("drafts") or "").strip(),
        "submitted": str(row.get("submitted") or "").strip(),
        "contracts": str(row.get("contracts") or "").strip(),
        "withdrawn": str(row.get("withdrawn") or "").strip(),
        "callBudgetRon": str(row.get("callBudgetRon") or "").strip(),
    }


def current_item_snapshot(state: dict[str, Any]) -> dict[str, Any] | None:
    for item in state.get("items") or []:
        if not isinstance(item, dict):
            continue
        canonical_url = str(item.get("url") or "").strip()
        if not official_reporting_url(canonical_url):
            continue
        verification = str(item.get("verification") or "")
        transport = str(item.get("retrievalTransport") or "")
        directly_verified = verification == "CANONICAL_OFFICIAL_FETCH" or transport.startswith("direct")
        snapshot = item.get("registrySnapshot")
        if not directly_verified or not isinstance(snapshot, dict) or not snapshot:
            continue
        rows = list(snapshot.values())
        return {
            "status": "OK",
            "directOnly": True,
            "canonicalUrl": canonical_url,
            "observedAt": str(item.get("observedAt") or item.get("date") or ""),
            "title": "Finanțări programe 2021-2027",
            "validatedCallCount": item.get("validatedCallCount"),
            "paginationText": str(item.get("paginationText") or ""),
            "explicitStatuses": item.get("explicitStatuses") or [],
            "calls": rows,
            "sourceItemId": str(item.get("id") or ""),
        }
    return None


def legacy_run_snapshot(state: dict[str, Any]) -> dict[str, Any] | None:
    run = state.get("lastRun") if isinstance(state.get("lastRun"), dict) else {}
    snapshot = run.get("registrySnapshot") if isinstance(run.get("registrySnapshot"), dict) else None
    if not snapshot:
        return None
    canonical_url = str(snapshot.get("canonicalUrl") or DEFAULT_URL).strip()
    if snapshot.get("status") != "OK" or snapshot.get("directOnly") is not True or not official_reporting_url(canonical_url):
        return None
    calls = snapshot.get("calls")
    if not isinstance(calls, list) or not calls:
        return None
    return {
        **snapshot,
        "canonicalUrl": canonical_url,
        "observedAt": str(snapshot.get("observedAt") or run.get("observedAt") or ""),
    }


def extract_snapshot(state: dict[str, Any]) -> dict[str, Any] | None:
    return current_item_snapshot(state) or legacy_run_snapshot(state)


def main() -> int:
    state = load_state()
    snapshot = extract_snapshot(state) or {}

    canonical_url = str(snapshot.get("canonicalUrl") or DEFAULT_URL).strip()
    direct_only = snapshot.get("directOnly") is True
    snapshot_ok = snapshot.get("status") == "OK"
    official = official_reporting_url(canonical_url)

    calls: list[dict[str, str]] = []
    if direct_only and snapshot_ok and official:
        for row in snapshot.get("calls") or []:
            cleaned = clean_call(row)
            if cleaned:
                calls.append(cleaned)

    calls.sort(key=lambda row: (row["programme"].casefold(), row["call"].casefold()))
    explicit_statuses = sorted(
        {c["officialStatus"] for c in calls if c["officialStatus"]},
        key=str.casefold,
    )
    status = "OK_DIRECT" if calls else "UNAVAILABLE_FAIL_CLOSED"
    observed_at = str(snapshot.get("observedAt") or "")
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
