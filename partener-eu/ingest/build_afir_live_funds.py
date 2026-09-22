#!/usr/bin/env python3
"""Build a structured, authoritative AFIR live-funds snapshot.

The source is AFIR's public "Contor fonduri disponibile" table. The builder
cross-checks the fetched byte fingerprint against the AFIR corpus candidate
before resolving anything. A mismatch is fail-closed source drift, never a
reason to auto-promote a material fact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from afir_ingest import fetch

ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "state" / "afir_corpus.json"
DEFAULT_OUTPUT = ROOT / "state" / "afir_live_funds.json"
COUNTER_PATH = "/finantare/contor-fonduri-disponibile"
BUCHAREST = ZoneInfo("Europe/Bucharest")


class TableParser(HTMLParser):
    """Capture table rows/cells while tolerating nested and void markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(clean_cell(" ".join(self._cell_parts)))
            self._cell_parts = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if any(self._row):
                self.rows.append(self._row)
            self._in_row = False
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            value = data.strip()
            if value:
                self._cell_parts.append(value)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def clean_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_counter_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def find_counter_item(corpus: dict[str, Any]) -> dict[str, Any]:
    for item in corpus.get("items") or []:
        if not isinstance(item, dict):
            continue
        if normalize_counter_url(str(item.get("url") or "")).endswith(COUNTER_PATH):
            return item
    raise ValueError("AFIR live-funds counter was not found in the corpus")


def parse_eur(value: str) -> str:
    raw = clean_cell(value).upper().replace("EUR", "").replace("\u00a0", " ").strip()
    raw = re.sub(r"\s+", "", raw)
    if not raw:
        raise ValueError("empty EUR value")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid EUR value: {value!r}") from exc
    return f"{amount:.2f}"


def parse_int(value: str) -> int:
    raw = re.sub(r"[^\d-]", "", clean_cell(value))
    if not raw:
        raise ValueError(f"invalid integer value: {value!r}")
    return int(raw)


def parse_local_datetime(value: str) -> tuple[str, str]:
    raw = clean_cell(value)
    parsed = dt.datetime.strptime(raw, "%d.%m.%Y %H:%M:%S").replace(tzinfo=BUCHAREST)
    return raw, parsed.isoformat()


def parse_table(html_bytes: bytes) -> list[list[str]]:
    parser = TableParser()
    parser.feed(html_bytes.decode("utf-8", "replace"))
    return parser.rows


def parse_rows(table_rows: list[list[Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_row in table_rows:
        if not isinstance(raw_row, list):
            continue
        cells = [clean_cell(cell) for cell in raw_row]
        if len(cells) < 9 or not re.fullmatch(r"DR-\d{1,3}", cells[0].upper()):
            continue
        code = cells[0].upper()
        sector = cells[1]
        key = (code, sector.casefold())
        if key in seen:
            raise ValueError(f"duplicate AFIR counter row: {code} / {sector}")
        seen.add(key)
        opens_local, opens_iso = parse_local_datetime(cells[3])
        closes_local, closes_iso = parse_local_datetime(cells[4])
        parsed.append(
            {
                "interventionCode": code,
                "sector": sector,
                "sessionAllocationEur": parse_eur(cells[2]),
                "opensAtLocal": opens_local,
                "opensAtIso": opens_iso,
                "closesAtLocal": closes_local,
                "closesAtIso": closes_iso,
                "submissionCeilingEur": parse_eur(cells[5]),
                "submittedPublicValueEur": parse_eur(cells[6]),
                "submittedProjectCount": parse_int(cells[7]),
                "availableFundsEur": parse_eur(cells[8]),
            }
        )
    if not parsed:
        raise ValueError("No structured DR rows were parsed from the AFIR live-funds table")
    parsed.sort(key=lambda row: (row["interventionCode"], row["sector"].casefold()))
    return parsed


def decimal_total(rows: list[dict[str, Any]], field: str) -> str:
    total = sum((Decimal(row[field]) for row in rows), Decimal("0"))
    return f"{total:.2f}"


def canonical_digest(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_source_bytes(url: str, fixture: Path | None) -> tuple[bytes, str | None, int | None]:
    if fixture is not None:
        return fixture.read_bytes(), None, 200
    response = fetch(url)
    if not response.get("ok"):
        raise RuntimeError(
            f"AFIR counter fetch failed: status={response.get('status')} error={response.get('error')}"
        )
    return response["data"], response.get("content_type"), response.get("status")


def build_snapshot(corpus: dict[str, Any], fixture: Path | None = None) -> dict[str, Any]:
    item = find_counter_item(corpus)
    canonical_url = str(item.get("url") or "").strip()
    corpus_fingerprint = clean_cell(item.get("sha256"))
    if not re.fullmatch(r"[0-9a-f]{64}", corpus_fingerprint):
        raise ValueError("AFIR counter corpus fingerprint is missing or invalid")

    data, content_type, http_status = load_source_bytes(canonical_url, fixture)
    source_fingerprint = hashlib.sha256(data).hexdigest()
    observed_at = item.get("observedAt")
    generated_at = corpus.get("generatedAt") or corpus.get("lastSuccessfulAt") or observed_at
    fingerprint_matches = source_fingerprint == corpus_fingerprint

    rows: list[dict[str, Any]] = []
    parse_error = None
    try:
        rows = parse_rows(parse_table(data))
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    status = "PASS" if fingerprint_matches and rows and not parse_error else (
        "DEGRADED_SOURCE_DRIFT" if not fingerprint_matches else "FAIL_PARSE"
    )
    codes = sorted({row["interventionCode"] for row in rows})
    snapshot_fingerprint = canonical_digest(rows) if rows else None
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "source": "AFIR",
        "status": status,
        "canonicalUrl": canonical_url,
        "corpusFingerprint": corpus_fingerprint,
        "sourceFingerprint": source_fingerprint,
        "sourceFingerprintMatchesCorpus": fingerprint_matches,
        "snapshotFingerprint": snapshot_fingerprint,
        "sourceObservedAt": observed_at,
        "generatedAt": generated_at,
        "httpStatus": http_status,
        "contentType": content_type,
        "currency": "EUR",
        "policy": {
            "sourceTier": "T1",
            "purpose": "dedicated-live-available-funds-snapshot",
            "publishableDedicatedSnapshot": status == "PASS",
            "autoPromoteIntoDossierBudget": False,
            "callStatusInferenceAllowed": False,
            "eligibilityInferenceAllowed": False,
            "scoringInferenceAllowed": False,
            "sourceDrift": "fail-closed-require-next-corpus-observation",
        },
        "summary": {
            "rowCount": len(rows),
            "interventionCount": len(codes),
            "interventions": codes,
            "sessionAllocationTotalEur": decimal_total(rows, "sessionAllocationEur") if rows else None,
            "submissionCeilingTotalEur": decimal_total(rows, "submissionCeilingEur") if rows else None,
            "submittedPublicValueTotalEur": decimal_total(rows, "submittedPublicValueEur") if rows else None,
            "availableFundsTotalEur": decimal_total(rows, "availableFundsEur") if rows else None,
            "submittedProjectCount": sum(row["submittedProjectCount"] for row in rows),
        },
        "rows": rows,
        "provenance": {
            "authority": "AFIR",
            "evidenceType": "OFFICIAL_LIVE_COUNTER",
            "corpusFingerprint": corpus_fingerprint,
            "sourceFingerprint": source_fingerprint,
            "snapshotFingerprint": snapshot_fingerprint,
            "sourceObservedAt": observed_at,
            "materialFactBoundary": "snapshot-only-no-cross-field-inference",
        },
    }
    if parse_error:
        payload["parseError"] = parse_error
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(encoded, encoding="utf-8")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--html-fixture", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = build_snapshot(load_json(args.corpus), args.html_fixture)
    write_json(args.output, snapshot)
    print(json.dumps({"status": snapshot["status"], **snapshot["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0 if snapshot["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
