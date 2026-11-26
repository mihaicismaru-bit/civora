#!/usr/bin/env python3
"""Synchronize derived counters, homepage IDs and generated JS after overlays."""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo
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
        # An offset-free ISO clock is not proof of an official timezone.
        # Never guess UTC for a deadline used to authorize current OPEN.
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        pass
    months = {"ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12}
    normalized = fold(raw)
    match = re.search(r"\b(\d{1,2})\s+(" + "|".join(months) + r")\s+(20\d{2})\b", normalized)
    if not match:
        return None
    day, month, year = int(match.group(1)), months[match.group(2)], int(match.group(3))
    tail = normalized[match.end():]
    # Match the public static renderer: an exact dot clock must not fall
    # through to end-of-day, and distinct second-level cutoffs must not collide.
    timed = re.match(
        r"^\s*,?\s*(?:(?:la\s+)?ora\s*|la\s+)?(\d{1,2})[:.](\d{2})(?::(\d{2}))?\b",
        tail,
    )
    if timed:
        hour, minute, second = int(timed.group(1)), int(timed.group(2)), int(timed.group(3) or 0)
    elif re.match(r"^\s*,?\s*(?:(?:la\s+)?ora\b|(?:la\s+)?\d{1,2}[:.])", tail):
        return None
    else:
        hour, minute, second = 23, 59, 59
    # ZoneInfo defaults to fold=0: this silently chooses one of two
    # autumn clock readings and even accepts the missing spring 03:xx hour.
    # A local cutoff without an explicit offset must be unambiguous and real,
    # matching build_public_static_pages.bucharest_datetime_utc.
    try:
        naive = dt.datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
    ro_tz = ZoneInfo("Europe/Bucharest")
    early = naive.replace(tzinfo=ro_tz, fold=0)
    late = naive.replace(tzinfo=ro_tz, fold=1)
    if early.utcoffset() != late.utcoffset():
        return None
    utc = early.astimezone(dt.timezone.utc)
    if utc.astimezone(ro_tz).replace(tzinfo=None) != naive:
        return None
    return utc


def has_exact_open_clock(value: Any) -> bool:
    """Only an explicitly timed and timezone-grounded deadline can admit OPEN.

    ISO timestamps need a real offset; a Romanian calendar date needs an
    explicit local hour. A date-only or zoneless competing claim is review,
    never invented end-of-day evidence. Mirrors the public renderer gate.
    """
    raw = str(value or "").strip()
    if re.fullmatch(
        r"20\d{2}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})",
        raw, flags=re.I,
    ):
        return True
    normalized = fold(raw)
    months = (
        r"ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|"
        r"septembrie|octombrie|noiembrie|decembrie"
    )
    match = re.search(r"\b\d{1,2}\s+(?:" + months + r")\s+20\d{2}\b(.*)", normalized)
    return bool(match and re.match(
        r"^\s*,?\s*(?:(?:la\s+)?ora\s*|la\s+)?\d{1,2}[:.]\d{2}(?::\d{2})?\b",
        match.group(1),
    ))


def current_open(dossier: dict[str, Any], clock: dt.datetime) -> bool:
    """Fail closed at the derived-home projection, not merely at render time."""
    if dossier.get("status") != "OPEN" or dossier.get("publicationState") != "PUBLISHABLE":
        return False
    # DR-12 is an umbrella with independently accepting components. AFIR
    # confirmed "alte sectoare" exhausted on 11 Nov while zootehnic has
    # its own counter. Never present the generic dossier as an exact OPEN.
    # This is a render/projection REVIEW hold, not an official CLOSED claim.
    if str(dossier.get("id") or "") == "afir-dr12-2026":
        return False
    rows = dossier.get("quickFacts") or []
    status_rows = [r for r in rows if fold(r.get("label")) == "status"]
    deadline_rows = [r for r in rows if fold(r.get("label")) == "termen"]
    if len(status_rows) != 1 or len(deadline_rows) != 1:
        return False
    status, deadline = status_rows[0], deadline_rows[0]
    if str(status.get("confidence") or "").upper() != "CONFIRMED":
        return False
    if fold(status.get("value")) not in {"open", "deschis"}:
        return False
    if str(deadline.get("confidence") or "").upper() != "CONFIRMED":
        return False
    if not has_exact_open_clock(deadline.get("value")):
        return False
    closes = parse_date(deadline.get("value"))
    if closes is None or closes <= clock:
        return False

    # A future opening or contradictory observed opening is never OPEN.
    opening_rows = [r for r in rows if fold(r.get("label")) == "deschidere"]
    if len(opening_rows) > 1:
        return False
    if opening_rows and str(opening_rows[0].get("confidence") or "").upper() != "CONFIRMED":
        return False
    openings = [
        dossier[k] for k in ("openFrom", "opensAt", "openAt")
        if dossier.get(k) not in (None, "")
    ]
    if opening_rows:
        openings.append(opening_rows[0].get("value"))
    observed_openings = []
    for value in openings:
        if not has_exact_open_clock(value):
            return False
        parsed = parse_date(value)
        if parsed is None or parsed > clock:
            return False
        observed_openings.append(parsed)
    if observed_openings and any(x != observed_openings[0] for x in observed_openings):
        return False

    # Do not select a favorable cutoff from contradictory source projections.
    for key in ("deadline", "closesAt", "closeAt"):
        if dossier.get(key) not in (None, ""):
            value = dossier[key]
            if not has_exact_open_clock(value) or parse_date(value) != closes:
                return False
    return True


def refresh_quality_pass(payload: dict[str, Any], dossiers: list[dict[str, Any]]) -> None:
    """Refresh quality counters after authoritative overlays add/replace dossiers.

    finalize_decision_products computes these counters before the AFIR/STEP
    authoritative overlays run.  The overlays already carry complete executive
    summaries and the strict applicant-list policy, so the derived counters must
    be recomputed from the final projection rather than left stale.
    """
    quality = payload.setdefault("qualityPass", {})
    quality["executiveSummaryCoverage"] = sum(1 for row in dossiers if row.get("executiveSummary"))
    quality["strictApplicantListCoverage"] = sum(
        1
        for row in dossiers
        if (row.get("quality") or {}).get("applicantListPolicy") == "GUIDE_EXPLICIT_ONLY"
    )


def main(*, as_of: dt.datetime | None = None) -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    dossiers = payload.get("dossiers") or []
    # Preserve generatedAt as source provenance, never as the present-tense
    # clock that authorizes current OPEN cards in the derived projection.
    clock = as_of or dt.datetime.now(dt.timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("Derived projection evaluation clock must be timezone-aware")

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
    refresh_quality_pass(payload, dossiers)
    payload.setdefault("home", {})["openDossierIds"] = [row["id"] for row in open_rows[:8]]
    priority_prepare = {"afir-dr31-2026-2027": 0}
    prepare_rows.sort(key=lambda row: (priority_prepare.get(str(row.get("id")), 1), -int((row.get("quality") or {}).get("completeness") or 0)))
    payload["home"]["prepareDossierIds"] = [row["id"] for row in prepare_rows[:8]]
    payload["home"]["changeNewsIds"] = [row["id"] for row in (payload.get("news") or [])[:8]]
    payload.setdefault("policy", {})["derivedProjectionSynchronized"] = True

    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "open": [row["id"] for row in open_rows],
        "dossiers": len(dossiers),
        "executiveSummaryCoverage": payload["qualityPass"]["executiveSummaryCoverage"],
        "strictApplicantListCoverage": payload["qualityPass"]["strictApplicantListCoverage"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
