#!/usr/bin/env python3
"""Generate PARTENER.EU daily executive briefing from canonical decision products.

This is a presentation product, not a separate source of truth. It selects at
most four items that are useful today and writes a static JS payload consumed by
the homepage renderer. Raw ingestion rows never enter this product directly.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JSON = ROOT / "partener-eu" / "ingest" / "state" / "daily_brief.json"
OUT_JS = ROOT / "partener-eu" / "web" / "daily-brief-data.js"
TZ = dt.timezone(dt.timedelta(hours=3))
MONTHS_RO = ["ianuarie","februarie","martie","aprilie","mai","iunie","iulie","august","septembrie","octombrie","noiembrie","decembrie"]
NEWS_MAX_AGE_HOURS = 72
PREPARE_STATUSES = {"EXPECTED", "ANNOUNCED", "PUBLIC_CONSULTATION", "REVIEW", "PREPARE_NOW", "UPCOMING"}


def parse_date(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        x = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if x.tzinfo is None:
            x = x.replace(tzinfo=TZ)
        return x.astimezone(TZ)
    except Exception:
        pass
    text = str(value).lower()
    months = {name:i+1 for i,name in enumerate(MONTHS_RO)}
    m = re.search(r"(\d{1,2})\s+([a-zăâîșț]+)\s+(20\d{2})", text)
    if m and m.group(2) in months:
        return dt.datetime(int(m.group(3)), months[m.group(2)], int(m.group(1)), 23, 59, tzinfo=TZ)
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if m:
        return dt.datetime(int(m.group(1)),int(m.group(2)),int(m.group(3)),23,59,tzinfo=TZ)
    return None


def human_date(value: Any) -> str:
    parsed=parse_date(value)
    if not parsed:
        return str(value or "")
    raw=str(value or "")
    has_time=bool(re.search(r"T\d{2}:\d{2}|\b\d{1,2}:\d{2}\b",raw))
    base=f"{parsed.day} {MONTHS_RO[parsed.month-1]} {parsed.year}"
    return f"{base}, {parsed.strftime('%H:%M')}" if has_time else base


def clean_sentence(value: Any) -> str:
    text=re.sub(r"\s+"," ",str(value or "")).strip()
    text=re.sub(r"\bSunt confirmate:\s*open\.?", "Apelul este confirmat ca deschis.", text, flags=re.I)
    text=re.sub(r"\bopen\b", "deschis", text, flags=re.I)
    return text


def fact_row(d: dict[str, Any], *labels: str) -> dict[str, Any] | None:
    wanted = {label.lower() for label in labels}
    return next((x for x in d.get("quickFacts") or [] if str(x.get("label") or "").lower() in wanted), None)


def fact(d: dict[str, Any], *labels: str) -> str:
    row = fact_row(d, *labels)
    if row and str(row.get("value") or "").strip() not in {"", "Neconfirmat", "—"}:
        return str(row["value"])
    return ""


def confirmed_fact(d: dict[str, Any], label: str) -> dict[str, Any] | None:
    row = fact_row(d, label)
    if row and str(row.get("confidence") or "").upper() == "CONFIRMED":
        return row
    return None


def lifecycle_dates(d: dict[str, Any]) -> list[dt.datetime]:
    values: list[Any] = []
    for key in ("openFrom", "opensAt", "openAt", "deadline", "closesAt", "closeAt", "consultationDeadline", "publishedAt", "publicationDate"):
        if d.get(key) not in (None, ""):
            values.append(d[key])
    for row in d.get("quickFacts") or []:
        label = str(row.get("label") or "").lower()
        if re.search(r"termen|deschidere|depunere|consult|publicare|calendar", label):
            values.append(row.get("value"))
    return [parsed for value in values if (parsed := parse_date(value)) is not None]


def explicit_years(d: dict[str, Any]) -> list[int]:
    text = " ".join(str(d.get(key) or "") for key in ("title", "standfirst", "summary", "decisionAction"))
    return [int(match.group(1)) for match in re.finditer(r"\b(20\d{2})\b", text)]


def is_current_open(d: dict[str, Any], today: dt.datetime) -> bool:
    if str(d.get("status") or "").upper() != "OPEN":
        return False
    if str(d.get("publicationState") or "").upper() != "PUBLISHABLE":
        return False
    if not confirmed_fact(d, "Status") or not confirmed_fact(d, "Termen"):
        return False
    deadline = parse_date(confirmed_fact(d, "Termen").get("value"))
    return bool(deadline and deadline >= today)


def is_current_prepare(d: dict[str, Any], today: dt.datetime) -> bool:
    if str(d.get("status") or "").upper() not in PREPARE_STATUSES:
        return False
    if any(value.year >= today.year for value in lifecycle_dates(d)):
        return True
    return any(year >= today.year for year in explicit_years(d))


def is_current_candidate(d: dict[str, Any], today: dt.datetime) -> bool:
    status = str(d.get("status") or "").upper()
    if status == "OPEN":
        return is_current_open(d, today)
    if status in {"EXPECTED", "PUBLIC_CONSULTATION"}:
        return is_current_prepare(d, today)
    return False


def is_current_news(n: dict[str, Any], today: dt.datetime) -> bool:
    event_date = parse_date(n.get("date"))
    if event_date is None or event_date.date() > today.date():
        return False
    age_hours = max(0.0, (today - event_date).total_seconds() / 3600.0)
    return age_hours <= NEWS_MAX_AGE_HOURS


def dossier_score(d: dict[str, Any], today: dt.datetime) -> tuple[int, int]:
    status = str(d.get("status") or "")
    completeness = int((d.get("quality") or {}).get("completeness") or 0)
    deadline = parse_date(fact(d, "Termen"))
    score = 0
    if status == "OPEN": score += 80
    elif status == "EXPECTED": score += 55
    elif status == "PUBLIC_CONSULTATION": score += 48
    if deadline:
        days = (deadline.date() - today.date()).days
        if 0 <= days <= 7: score += 35
        elif 8 <= days <= 21: score += 24
        elif 22 <= days <= 45: score += 12
    score += min(20, completeness // 5)
    return score, completeness


def dossier_item(d: dict[str, Any], today: dt.datetime) -> dict[str, Any]:
    status = str(d.get("status") or "REVIEW")
    deadline_raw = fact(d, "Termen")
    deadline = human_date(deadline_raw) if deadline_raw else ""
    grant = clean_sentence(fact(d, "Grant", "Valoare proiect", "Finanțare"))
    budget = clean_sentence(fact(d, "Buget"))
    if status == "OPEN":
        tone, label = "open", "DESCHIS"
        action = "Deschide dosarul și verifică eligibilitatea, documentele și termenul intern de lucru."
    elif status == "EXPECTED":
        tone, label = "soon", "URMEAZĂ"
        action = "Pregătește profilul, documentele și parteneriatul fără a trata data estimată ca termen oficial."
    elif status == "PUBLIC_CONSULTATION":
        tone, label = "consultation", "ÎN CONSULTARE"
        action = "Analizează condițiile și pregătește observații; depunerea nu este încă deschisă."
    else:
        tone, label = "verify", "DE VERIFICAT"
        action = "Verifică necunoscutele din dosar înainte de orice decizie."
    bits = []
    if grant: bits.append(f"Finanțare: {grant}")
    elif budget: bits.append(f"Buget: {budget}")
    if deadline: bits.append(f"Termen: {deadline}")
    fallback=clean_sentence(d.get("decisionAction") or d.get("standfirst") or "")
    summary = " · ".join(bits) if bits else fallback
    return {
        "id": f"brief-dossier-{d.get('id')}", "kind":"DOSSIER", "tone":tone, "label":label,
        "programme": d.get("programme") or "PROGRAM", "title": d.get("title") or "Oportunitate de finanțare",
        "summary": summary[:260], "action": action, "dossierId": d.get("id"),
        "priority": dossier_score(d, today)[0],
    }


def news_item(n: dict[str, Any]) -> dict[str, Any]:
    kind = str(n.get("kind") or "OFFICIAL_UPDATE")
    labels = {"DEADLINE_EXTENDED":"TERMEN PRELUNGIT","CALL_OPENED":"APEL DESCHIS","GUIDE_MODIFIED":"GHID MODIFICAT","GUIDE_UPDATED_AFTER_CONSULTATION":"GHID ACTUALIZAT","GUIDE_PUBLISHED":"GHID PUBLICAT","CONSULTATION_OPENED":"CONSULTARE","CALL_CLOSED":"APEL ÎNCHIS","RESULTS_PUBLISHED":"REZULTATE","OFFICIAL_UPDATE":"ACTUALIZARE OFICIALĂ"}
    actions = n.get("actions") or []
    return {
        "id": f"brief-news-{n.get('id')}", "kind":"NEWS", "tone":"update",
        "label": labels.get(kind, "ACTUALIZARE"), "programme": n.get("programme") or "",
        "date": n.get("date"),
        "title": clean_sentence(n.get("headline") or "Actualizare relevantă"),
        "summary": clean_sentence(n.get("standfirst") or n.get("meaning") or "")[:260],
        "action": clean_sentence(actions[0] if actions else n.get("meaning") or "Verifică dosarul și sursa oficială.")[:220],
        "newsId": n.get("id"), "priority": int(n.get("utilityScore") or 60) + 25,
    }


def build_brief(payload: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    now = now.astimezone(TZ)
    candidates: list[dict[str, Any]] = []
    candidates.extend(
        news_item(n) for n in payload.get("news") or []
        if int(n.get("utilityScore") or 0) >= 60 and is_current_news(n, now)
    )
    current_dossiers=[d for d in payload.get("dossiers") or [] if is_current_candidate(d,now)]
    candidates.extend(dossier_item(d, now) for d in current_dossiers)
    candidates.sort(key=lambda x: (-int(x.get("priority") or 0), str(x.get("title") or "")))

    chosen: list[dict[str, Any]] = []
    programmes: set[str] = set()
    for item in candidates:
        programme = str(item.get("programme") or "")
        if programme in programmes and len(chosen) < 3:
            continue
        chosen.append(item);programmes.add(programme)
        if len(chosen) == 4:break
    if len(chosen) < 4:
        for item in candidates:
            if any(x["id"] == item["id"] for x in chosen):continue
            chosen.append(item)
            if len(chosen) == 4:break

    parallel = [d for d in current_dossiers if d.get("status") == "OPEN" and d.get("id") not in {x.get("dossierId") for x in chosen}]
    parallel.sort(key=lambda d: dossier_score(d, now), reverse=True)
    parallel_text = ""
    if parallel:
        names = [str(x.get("title") or "")[:65] for x in parallel[:2]]
        parallel_text = "În paralel: " + "; ".join(names) + "."

    return {
        "schemaVersion": 1,
        "asOf": now.replace(microsecond=0).isoformat(),
        "dateLabel": f"{now.day} {MONTHS_RO[now.month-1]} {now.year}",
        "title": "Ce este nou și ce trebuie făcut acum",
        "lead": "Selecție zilnică din apeluri, ghiduri și schimbări verificate. Consultările și estimările nu sunt afișate ca sesiuni deschise.",
        "items": chosen,
        "parallel": parallel_text,
        "policy": {
            "dailyGenerated": True,
            "decisionProductsOnly": True,
            "maxCards": 4,
            "rawIngestionExcluded": True,
            "expiredOpenExcluded": True,
            "undatedOpenExcluded": True,
            "provisionalOpenExcluded": True,
            "currentPrepareEvidenceRequired": True,
            "newsMaxAgeHours": NEWS_MAX_AGE_HOURS,
            "humanReadableDates": True,
        },
    }


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    now = dt.datetime.now(TZ)
    out = build_brief(payload, now)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DAILY_BRIEF=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"asOf":out["asOf"],"items":len(out["items"]),"titles":[x["title"] for x in out["items"]]}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__": raise SystemExit(main())
