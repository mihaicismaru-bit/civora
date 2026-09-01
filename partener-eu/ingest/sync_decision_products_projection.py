#!/usr/bin/env python3
"""Synchronize derived counters, homepage IDs and generated JS after overlays."""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"


def fold(value: Any) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(ch)).lower()


def fact(dossier: dict[str, Any], label: str) -> dict[str, Any] | None:
    wanted = fold(label)
    return next((row for row in dossier.get("quickFacts") or [] if fold(row.get("label")) == wanted), None)


def parse_date(value: Any) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw or any(token in fold(raw) for token in ("neconfirmat", "necunoscut", "unknown")):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        pass
    months = {"ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12}
    match = re.search(r"\b(\d{1,2})\s+(" + "|".join(months) + r")\s+(20\d{2})(?:\D+(\d{1,2}):(\d{2}))?", fold(raw))
    if not match:
        return None
    day, month, year = int(match.group(1)), months[match.group(2)], int(match.group(3))
    hour, minute = int(match.group(4) or 23), int(match.group(5) or 59)
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone(dt.timedelta(hours=3))).astimezone(dt.timezone.utc)


def current_open(dossier: dict[str, Any], clock: dt.datetime) -> bool:
    if dossier.get("status") != "OPEN" or dossier.get("publicationState") != "PUBLISHABLE":
        return False
    status = fact(dossier, "Status")
    deadline = fact(dossier, "Termen")
    if not status or status.get("confidence") != "CONFIRMED" or not deadline or deadline.get("confidence") != "CONFIRMED":
        return False
    closes = parse_date(deadline.get("value"))
    return closes is not None and closes >= clock


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    dossiers = payload.get("dossiers") or []
    clock = parse_date(payload.get("generatedAt")) or dt.datetime.now(dt.timezone.utc)

    for dossier in dossiers:
        completeness = int((dossier.get("quality") or {}).get("completeness") or 0)
        row = fact(dossier, "Completitudine critică")
        if row:
            row.update({"value": f"{completeness}%", "confidence": "SYSTEM"})

    rank = {"OPEN": 0, "PUBLIC_CONSULTATION": 1, "EXPECTED": 2, "REVIEW": 3, "CLOSED": 9}
    dossiers.sort(key=lambda row: (rank.get(str(row.get("status")), 5), -int((row.get("quality") or {}).get("completeness") or 0), str(row.get("title") or "")))
    open_rows = [row for row in dossiers if current_open(row, clock)]
    prepare_rows = [row for row in dossiers if row.get("status") in {"PUBLIC_CONSULTATION", "EXPECTED", "ANNOUNCED", "REVIEW", "PREPARE_NOW", "UPCOMING"}]
    complete = sum(1 for row in dossiers if (row.get("quality") or {}).get("dossierLevel") == "DOSAR COMPLET")
    advanced = sum(1 for row in dossiers if (row.get("quality") or {}).get("dossierLevel") == "DOSAR AVANSAT")
    construction = sum(1 for row in dossiers if (row.get("quality") or {}).get("dossierLevel") == "DOSAR ÎN CONSTRUCȚIE")
    identification = sum(1 for row in dossiers if (row.get("quality") or {}).get("dossierLevel") == "DOSAR DE IDENTIFICARE")
    payload["dossiers"] = dossiers
    payload.setdefault("summary", {}).update({
        "dossierCount": len(dossiers),
        "openCount": len(open_rows),
        "prepareCount": len(prepare_rows),
        "newsCount": len(payload.get("news") or []),
        "highCompletenessCount": sum(1 for row in dossiers if int((row.get("quality") or {}).get("completeness") or 0) >= 70),
        "completeDossierCount": complete,
        "advancedDossierCount": advanced,
        "constructionDossierCount": construction,
        "identificationDossierCount": identification,
    })
    payload.setdefault("home", {})["openDossierIds"] = [row["id"] for row in open_rows[:8]]
    priority_prepare = {"afir-dr31-2026-2027": 0}
    prepare_rows.sort(key=lambda row: (priority_prepare.get(str(row.get("id")), 1), -int((row.get("quality") or {}).get("completeness") or 0)))
    payload["home"]["prepareDossierIds"] = [row["id"] for row in prepare_rows[:8]]
    payload["home"]["changeNewsIds"] = [row["id"] for row in (payload.get("news") or [])[:8]]
    payload.setdefault("policy", {})["derivedProjectionSynchronized"] = True

    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"ok": True, "open": [row["id"] for row in open_rows], "dossiers": len(dossiers)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
