#!/usr/bin/env python3
"""Reconcile AFIR public-energy calls from exact post-launch T1 evidence.

This is a bounded fail-closed reconciliation lane for the two 2026
Modernisation Fund calls for public entities. A calendar or pre-launch page can
never authorize OPEN. OPEN requires the exact AFIR post-launch page, a successful
fresh fetch, a content hash, and explicit "sunt în derulare" semantics.

On transport failure the last successful OPEN receipt may be reused only inside
the four-hour freshness window. Outside that window the public status is
demoted to REVIEW. After the announced deadline OPEN is impossible.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import ssl
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"
RECEIPT = ROOT / "partener-eu" / "ingest" / "state" / "afir_energy_postlaunch_resolution.json"

SOURCE_URL = "https://www.afir.ro/comunicate/depunere-in-curs-a-proiectelor-in-energie-a-entitatilor-publice/"
PARSER_VERSION = "afir-energy-postlaunch-v1"
RO = dt.timezone(dt.timedelta(hours=3))
OPEN_AT = dt.datetime(2026, 9, 28, 10, 0, tzinfo=RO)
CLOSE_AT = dt.datetime(2026, 11, 20, 23, 59, tzinfo=RO)
MAX_EVIDENCE_AGE = dt.timedelta(hours=4)
TARGETS = {
    "afir-fm-public-autoconsum-2026",
    "afir-fm-public-storage-2026",
}
UA = "Mozilla/5.0 (compatible; PARTENER.EU-AFIR-PostLaunch/1.0; +https://partener.eu)"


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", html.unescape(data or "")).strip()
        if value:
            self.parts.append(value)


def iso(value: Any) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def norm(value: Any) -> str:
    import unicodedata
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(ch)
    ).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def fetch_exact(url: str = SOURCE_URL, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.6",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        },
    )
    last_error = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
                raw = response.read()
                final_url = response.geturl()
                status = getattr(response, "status", 200)
            if status != 200 or final_url.rstrip("/") != url.rstrip("/"):
                raise RuntimeError(f"unexpected AFIR response: status={status} final_url={final_url}")
            parser = TextParser()
            parser.feed(raw.decode("utf-8", "replace"))
            text = " ".join(parser.parts)
            return {
                "url": final_url,
                "status": status,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "text": text,
                "bytes": len(raw),
            }
        except Exception as exc:
            last_error = str(exc)
            if attempt < 3:
                time.sleep(float(attempt))
    raise RuntimeError(last_error or "AFIR fetch failed")


def explicit_open_semantics(text: str) -> bool:
    signal = norm(text)
    return (
        "sesiunile pentru energie sunt in derulare" in signal
        and "28 septembrie 2026" in signal
        and "20 noiembrie 2026" in signal
        and ("500 milioane" in signal or "500 000 000" in signal)
        and ("150 milioane" in signal or "150 000 000" in signal)
    )


def load_receipt(path: Path = RECEIPT) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def resolve(
    *,
    now: dt.datetime | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_exact,
    last_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc).astimezone(RO)
    now_utc = now.astimezone(dt.timezone.utc)
    run_id = "afir-energy-" + now_utc.strftime("%Y%m%dT%H%M%SZ")

    if now < OPEN_AT:
        return {
            "schemaVersion": 1,
            "runId": run_id,
            "status": "UPCOMING",
            "publishable": True,
            "reason": "BEFORE_OFFICIAL_OPEN_AT",
            "observedAt": now_utc.isoformat(),
            "parserVersion": PARSER_VERSION,
            "canonicalUrl": SOURCE_URL,
        }
    if now > CLOSE_AT:
        return {
            "schemaVersion": 1,
            "runId": run_id,
            "status": "REVIEW",
            "publishable": True,
            "reason": "ANNOUNCED_DEADLINE_PASSED",
            "observedAt": now_utc.isoformat(),
            "parserVersion": PARSER_VERSION,
            "canonicalUrl": SOURCE_URL,
        }

    try:
        fetched = fetcher(SOURCE_URL)
        if not fetched.get("sha256") or not explicit_open_semantics(fetched.get("text") or ""):
            raise RuntimeError("AFIR exact page does not contain required post-launch OPEN semantics")
        return {
            "schemaVersion": 1,
            "runId": run_id,
            "status": "OPEN",
            "publishable": True,
            "reason": "FRESH_EXACT_T1_POST_LAUNCH_CONFIRMATION",
            "observedAt": now_utc.isoformat(),
            "fetchedAt": now_utc.isoformat(),
            "parserVersion": PARSER_VERSION,
            "canonicalUrl": SOURCE_URL,
            "sha256": fetched["sha256"],
            "bytes": fetched.get("bytes"),
            "httpStatus": fetched.get("status"),
            "evidenceMode": "LIVE_CURRENT",
            "opensAt": OPEN_AT.isoformat(),
            "closesAt": CLOSE_AT.isoformat(),
        }
    except Exception as exc:
        last = last_receipt or {}
        last_seen = iso(last.get("fetchedAt") or last.get("observedAt"))
        if (
            last.get("status") == "OPEN"
            and last.get("sha256")
            and last_seen is not None
            and dt.timedelta(0) <= (now_utc - last_seen) <= MAX_EVIDENCE_AGE
        ):
            reused = dict(last)
            reused.update({
                "schemaVersion": 1,
                "runId": run_id,
                "status": "OPEN",
                "publishable": True,
                "reason": "CURRENT_LKG_WITHIN_FRESHNESS_WINDOW",
                "observedAt": now_utc.isoformat(),
                "parserVersion": PARSER_VERSION,
                "canonicalUrl": SOURCE_URL,
                "evidenceMode": "LKG_CURRENT",
                "fetchError": str(exc)[:300],
            })
            return reused
        return {
            "schemaVersion": 1,
            "runId": run_id,
            "status": "REVIEW",
            "publishable": True,
            "reason": "NO_CURRENT_POST_LAUNCH_T1_EVIDENCE",
            "observedAt": now_utc.isoformat(),
            "parserVersion": PARSER_VERSION,
            "canonicalUrl": SOURCE_URL,
            "fetchError": str(exc)[:300],
        }


def set_fact(dossier: dict[str, Any], label: str, value: str, confidence: str) -> None:
    for row in dossier.get("quickFacts") or []:
        if row.get("label") == label:
            row["value"] = value
            row["confidence"] = confidence
            return


def set_section(dossier: dict[str, Any], title: str, items: list[str]) -> None:
    for section in dossier.get("sections") or []:
        if section.get("title") == title:
            section["items"] = items
            section["empty"] = False
            return


def apply_resolution(payload: dict[str, Any], resolution: dict[str, Any]) -> int:
    status = resolution["status"]
    changed = 0
    for dossier in payload.get("dossiers") or []:
        if dossier.get("id") not in TARGETS:
            continue
        changed += 1
        if status == "OPEN":
            dossier["status"] = "OPEN"
            dossier["statusLabel"] = "DESCHIS"
            dossier["decision"] = "ACT NOW"
            dossier["decisionLabel"] = "ACȚIONEAZĂ ACUM"
            dossier["decisionAction"] = (
                "Apelul este deschis și confirmat post-lansare de AFIR. Verifică ultima versiune "
                "a documentelor și depune până la 20 noiembrie 2026, ora 23:59."
            )
            set_fact(dossier, "Status", "DESCHIS", "CONFIRMED")
            set_fact(dossier, "Deschidere", "28 septembrie 2026, 10:00 — confirmată post-lansare", "CONFIRMED")
            summary = dossier.get("executiveSummary") or {}
            summary["status"] = "OPEN"
            summary["opens"] = "2026-09-28T10:00:00+03:00 — OPEN confirmat post-lansare"
            dossier["executiveSummary"] = summary
            quality = dossier.setdefault("quality", {})
            quality["blockedFactClasses"] = [
                item for item in (quality.get("blockedFactClasses") or [])
                if item != "open_status"
            ]
            quality["failClosed"] = True
            quality["postLaunchOpenEvidence"] = True
            quality["postLaunchEvidenceFreshnessHours"] = 4
            construction = dossier.setdefault("dossierConstruction", {})
            construction["level"] = "DOSAR OPEN VERIFICAT"
            construction["missing"] = [
                item for item in (construction.get("missing") or [])
                if item != "open_status"
            ]
            construction["nextPass"] = "MONITOR_FRESH_OPEN_EVIDENCE_AND_DEADLINE"
            set_section(dossier, "Decizia rapidă", [
                dossier["decisionAction"],
                "OPEN este autorizat numai cât dovada T1 post-lansare rămâne curentă; calendarul singur nu autorizează OPEN.",
            ])
            set_section(dossier, "Ce trebuie făcut acum", [
                "Confirmă categoria de solicitant și dreptul de a aplica.",
                "Închide configurația tehnică și bugetul în limitele ghidului.",
                "Depune prin sistemul AFIR cât timp sesiunea este confirmată OPEN și înainte de termen.",
                "Monitorizează clarificările și modificările oficiale AFIR.",
            ])
            set_section(dossier, "Ce nu este confirmat", [
                "Probabilitatea de aprobare nu este inferată din statusul OPEN sau din ordinea depunerii.",
            ])
        elif status == "UPCOMING":
            dossier["status"] = "UPCOMING"
            dossier["statusLabel"] = "ÎN PREGĂTIRE"
        else:
            dossier["status"] = "REVIEW"
            dossier["statusLabel"] = "ÎN VERIFICARE"
            dossier["decision"] = "VERIFY"
            dossier["decisionLabel"] = "VERIFICĂ STAREA"
            dossier["decisionAction"] = (
                "Dovada T1 post-lansare nu este curentă. Nu presupune că apelul este OPEN; "
                "reverifică sursa oficială AFIR înainte de depunere."
            )
            set_fact(dossier, "Status", "ÎN VERIFICARE", "FAIL_CLOSED")
            quality = dossier.setdefault("quality", {})
            blocked = list(quality.get("blockedFactClasses") or [])
            if "open_status" not in blocked:
                blocked.append("open_status")
            quality["blockedFactClasses"] = blocked
            quality["failClosed"] = True
            quality["postLaunchOpenEvidence"] = False
            set_section(dossier, "Decizia rapidă", [
                dossier["decisionAction"],
                "Simplul calendar sau o pagină pre-lansare nu autorizează OPEN.",
            ])

        evidence_source = {
            "label": "AFIR — depunere în curs proiecte energie pentru entități publice",
            "url": SOURCE_URL,
            "tier": "T1",
            "observedAt": resolution.get("fetchedAt") or resolution.get("observedAt"),
            "supports": ["status", "opening", "deadline", "source_event"],
        }
        if resolution.get("sha256"):
            evidence_source["sha256"] = resolution["sha256"]
        sources = [
            row for row in (dossier.get("sources") or [])
            if str(row.get("url") or "").rstrip("/") != SOURCE_URL.rstrip("/")
        ]
        if resolution.get("sha256"):
            sources.insert(0, evidence_source)
        dossier["sources"] = sources
        dossier["canonicalLinks"] = list(dict.fromkeys(
            [row.get("url") for row in sources if row.get("url")]
        ))
        dossier["updatedAt"] = resolution.get("fetchedAt") or resolution.get("observedAt")

        timeline = [
            row for row in (dossier.get("timeline") or [])
            if row.get("kind") != "OPEN_CONFIRMED"
        ]
        if status == "OPEN":
            timeline.append({
                "date": "2026-09-29T10:15:00+03:00",
                "kind": "OPEN_CONFIRMED",
                "text": "AFIR confirmă post-lansare că sesiunile sunt în derulare.",
            })
        dossier["timeline"] = timeline

    payload.setdefault("policy", {})["afirEnergyPostLaunchEvidenceGate"] = True
    payload["policy"]["scheduledLaunchNeverAutoPromotedToOpen"] = True
    payload.setdefault("qualityPass", {})["afirEnergyPostLaunchResolution"] = {
        "status": resolution["status"],
        "reason": resolution["reason"],
        "runId": resolution["runId"],
        "canonicalUrl": SOURCE_URL,
        "sha256": resolution.get("sha256"),
        "evidenceMode": resolution.get("evidenceMode"),
    }

    if status == "OPEN":
        news = [
            row for row in (payload.get("news") or [])
            if row.get("id") != "news-afir-energy-public-open-2026-09-29"
        ]
        news.insert(0, {
            "id": "news-afir-energy-public-open-2026-09-29",
            "kind": "CALL_OPENED",
            "programme": "AFIR / Fondul pentru Modernizare",
            "date": "2026-09-29T10:15:00+03:00",
            "headline": "AFIR confirmă că cele două sesiuni pentru energie ale entităților publice sunt în derulare",
            "standfirst": "Depunerea este deschisă pentru cele două apeluri, cu termen 20 noiembrie 2026, ora 23:59.",
            "meaning": "Entitățile publice eligibile pot trece de la pregătire la depunere, pe documentația oficială curentă.",
            "audience": ["entități publice eligibile conform ghidurilor AFIR"],
            "confirmed": [
                "OPEN confirmat post-lansare de AFIR.",
                "Termen: 20 noiembrie 2026, ora 23:59.",
                "Alocări: 500 milioane EUR + 150 milioane EUR.",
            ],
            "notConfirmed": ["Probabilitatea de aprobare nu este inferată."],
            "actions": ["Verifică eligibilitatea.", "Folosește ghidul și anexele curente.", "Depune înainte de termen."],
            "dossierId": "afir-fm-public-autoconsum-2026",
            "source": {"label": "AFIR — depunere în curs", "url": SOURCE_URL, "tier": "T1"},
            "utilityScore": 100,
        })
        payload["news"] = news
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="ISO datetime override for deterministic replay")
    args = parser.parse_args()
    now = iso(args.now).astimezone(RO) if args.now and iso(args.now) else None
    last = load_receipt()
    resolution = resolve(now=now, last_receipt=last)

    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    changed = apply_resolution(payload, resolution)
    if changed != len(TARGETS):
        raise RuntimeError(f"expected {len(TARGETS)} AFIR energy dossiers, found {changed}")

    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    RECEIPT.write_text(json.dumps(resolution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resolution, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
