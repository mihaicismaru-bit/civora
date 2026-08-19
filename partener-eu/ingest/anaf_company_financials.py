#!/usr/bin/env python3
"""PARTENER.EU — official ANAF company financial statement lookup.

Queries the public ANAF balance-sheet service by CUI and year and emits a
canonical, replay-friendly JSON envelope. The upstream payload is preserved so
new ANAF indicators do not get silently discarded.

Usage:
    python partener-eu/ingest/anaf_company_financials.py --cui 9293117 --years 2024,2023
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://webservicesp.anaf.ro/bilant"
UA = "PARTENER.EU-CIVORA-ANAF-Financials/1.0 (+https://partener.eu)"
MAX_RESPONSE_BYTES = 4_000_000


def normalize_cui(value: str | int) -> str:
    text = str(value).strip().upper()
    if text.startswith("RO"):
        text = text[2:]
    text = re.sub(r"[\s._-]", "", text)
    if not text.isdigit() or not (2 <= len(text) <= 10):
        raise ValueError("CUI invalid: sunt acceptate 2-10 cifre, optional prefix RO")
    return text


def _request_json(url: str, timeout: float, attempts: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
            },
        )
        try:
            with urllib.request.urlopen(
                req, timeout=timeout, context=ssl.create_default_context()
            ) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("Raspuns ANAF peste limita de siguranta")
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace").strip()
                if not text:
                    raise ValueError("Raspuns ANAF gol")
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    raise ValueError("Raspuns ANAF neasteptat: radacina nu este obiect JSON")
                return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == attempts:
                break
        time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError(f"Interogare ANAF esuata: {type(last_error).__name__}: {last_error}")


def _number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        number = float(text)
        return int(number) if number.is_integer() else number
    except ValueError:
        return None


def canonicalize(payload: dict[str, Any], requested_cui: str, requested_year: int) -> dict[str, Any]:
    indicators: list[dict[str, Any]] = []
    for raw in payload.get("i") or []:
        if not isinstance(raw, dict):
            continue
        indicators.append(
            {
                "code": str(raw.get("indicator", "")).strip(),
                "value": _number(raw.get("val_indicator")),
                "label": str(raw.get("val_den_indicator", "")).strip(),
            }
        )

    returned_cui = str(payload.get("cui", requested_cui)).strip()
    year = payload.get("an", requested_year)
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = requested_year

    return {
        "source": "ANAF_PUBLIC_BALANCE_SHEET",
        "sourceUrl": f"{BASE_URL}?{urllib.parse.urlencode({'an': requested_year, 'cui': requested_cui})}",
        "requested": {"cui": requested_cui, "year": requested_year},
        "available": bool(indicators or payload.get("deni")),
        "entity": {
            "cui": returned_cui,
            "name": str(payload.get("deni", "")).strip(),
            "caen": payload.get("caen"),
            "caenName": str(payload.get("den_caen", "")).strip(),
        },
        "year": year,
        "indicators": indicators,
        "raw": payload,
    }


def fetch_year(cui: str, year: int, timeout: float = 20.0, attempts: int = 3) -> dict[str, Any]:
    url = f"{BASE_URL}?{urllib.parse.urlencode({'an': int(year), 'cui': cui})}"
    payload = _request_json(url, timeout=timeout, attempts=attempts)
    return canonicalize(payload, cui, int(year))


def fetch_series(
    cui_value: str | int,
    years: list[int],
    timeout: float = 20.0,
    attempts: int = 3,
    pace_seconds: float = 1.0,
) -> dict[str, Any]:
    cui = normalize_cui(cui_value)
    statements: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, year in enumerate(years):
        if index and pace_seconds > 0:
            time.sleep(pace_seconds)
        try:
            statement = fetch_year(cui, int(year), timeout=timeout, attempts=attempts)
            if statement["available"]:
                statements.append(statement)
            else:
                errors.append({"year": int(year), "error": "NO_DATA"})
        except Exception as exc:  # preserve partial series if one year is unavailable
            errors.append({"year": int(year), "error": f"{type(exc).__name__}: {exc}"})

    return {
        "schemaVersion": "1.0",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cui": cui,
        "status": "OK" if statements else "UNAVAILABLE",
        "statementCount": len(statements),
        "statements": statements,
        "errors": errors,
        "policy": {
            "sourceAuthority": "ANAF",
            "noSyntheticValues": True,
            "partialSeriesAllowed": True,
        },
    }


def parse_years(text: str | None) -> list[int]:
    if text:
        years = [int(piece.strip()) for piece in text.split(",") if piece.strip()]
        if not years:
            raise ValueError("Lista de ani este goala")
        return years
    current = dt.datetime.now().year
    return list(range(current - 1, current - 6, -1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Interogheaza bilanturile publice ANAF dupa CUI")
    parser.add_argument("--cui", required=True)
    parser.add_argument("--years", help="Ani separati prin virgula; implicit ultimii 5 ani incheiati")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--pace", type=float, default=1.0)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    try:
        result = fetch_series(
            args.cui,
            parse_years(args.years),
            timeout=args.timeout,
            attempts=max(1, args.attempts),
            pace_seconds=max(0.0, args.pace),
        )
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
