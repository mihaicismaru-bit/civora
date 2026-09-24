#!/usr/bin/env python3
"""Regression gate for late-September 2026 authoritative AFIR coverage."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
RO = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime.now(dt.timezone.utc).astimezone(RO)

payload = json.loads(DATA.read_text(encoding="utf-8"))
rows = {row.get("id"): row for row in payload.get("dossiers") or []}

required = {
    "afir-dr21-consultation-2026",
    "afir-fm-public-autoconsum-2026",
    "afir-fm-public-storage-2026",
}
missing = required - set(rows)
assert not missing, f"missing authoritative AFIR September dossiers: {sorted(missing)}"
assert payload.get("policy", {}).get("afirSeptember2026OfficialCoverage") is True
assert payload.get("policy", {}).get("scheduledLaunchNeverAutoPromotedToOpen") is True


def fact(dossier, label):
    for item in dossier.get("quickFacts") or []:
        if item.get("label") == label:
            return item
    raise AssertionError(f"missing {label} in {dossier.get('id')}")


def validate_common(dossier):
    assert dossier.get("publicationState") == "PUBLISHABLE", dossier.get("id")
    assert dossier.get("status") != "OPEN", f"scheduled/consultative AFIR signal auto-promoted to OPEN: {dossier.get('id')}"
    quality = dossier.get("quality") or {}
    assert quality.get("failClosed") is True
    assert quality.get("applicantEvidenceAuthorized") is True
    assert quality.get("afirSeptember2026Coverage") is True
    assert len(dossier.get("sections") or []) >= 10
    assert len(dossier.get("sources") or []) >= 2
    for source in dossier.get("sources") or []:
        assert str(source.get("url") or "").startswith("https://www.afir.ro/"), source
        assert source.get("tier") == "T1", source
        assert source.get("observedAt"), source


dr21 = rows["afir-dr21-consultation-2026"]
validate_common(dr21)
assert dr21.get("code") == "DR-21"
assert dr21.get("status") in {"PUBLIC_CONSULTATION", "REVIEW"}
if NOW <= dt.datetime(2026, 9, 29, 23, 59, tzinfo=RO):
    assert dr21.get("status") == "PUBLIC_CONSULTATION"
assert fact(dr21, "Termen")["value"].startswith("29 septembrie 2026")
assert fact(dr21, "Grant")["value"] == "maximum 50.000 EUR/beneficiar"
assert fact(dr21, "Buget")["confidence"] == "UNKNOWN"
assert "beneficiaries" in set(dr21["quality"]["verifiedFactClasses"])
assert "budget" in set(dr21["quality"]["blockedFactClasses"])
assert any("consultare-publica-privind-finantarea-investitiilor-dr-21" in src["url"] for src in dr21["sources"])

for dossier_id, expected_budget, guide_token in (
    ("afir-fm-public-autoconsum-2026", "500.000.000 EUR", "producere-energie-pentru-autoconsum-beneficiari-publici"),
    ("afir-fm-public-storage-2026", "150.000.000 EUR", "stocare-energie-beneficiari-publici"),
):
    dossier = rows[dossier_id]
    validate_common(dossier)
    assert dossier.get("status") in {"UPCOMING", "REVIEW"}
    if NOW < dt.datetime(2026, 9, 28, 10, 0, tzinfo=RO):
        assert dossier.get("status") == "UPCOMING"
    assert fact(dossier, "Buget")["value"] == expected_budget
    assert fact(dossier, "Termen")["value"] == "20 noiembrie 2026, 23:59"
    assert fact(dossier, "Contribuție proprie")["value"].startswith("0%")
    assert "open_status" in set(dossier["quality"]["blockedFactClasses"])
    assert "status" in set(dossier["quality"]["verifiedFactClasses"])
    assert any(guide_token in src["url"] for src in dossier["sources"])
    assert any("informatii-sesiune-energie-regenerabila-solicitanti-publici" in src["url"] for src in dossier["sources"])

news = {row.get("id"): row for row in payload.get("news") or []}
assert "news-afir-dr21-consultation-2026-09-18" in news
assert "news-afir-energy-public-upcoming-2026-09-22" in news
assert news["news-afir-energy-public-upcoming-2026-09-22"].get("kind") == "SESSION_ANNOUNCED"

print(json.dumps({
    "status": "PASS",
    "dossiers": sorted(required),
    "dr21": dr21.get("status"),
    "energy": [rows["afir-fm-public-autoconsum-2026"].get("status"), rows["afir-fm-public-storage-2026"].get("status")],
    "failClosedOpenPromotion": True,
}, ensure_ascii=False))
