from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from contracts import FactKernel
from editorial_integrity import validate_editorial_package

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "valcea-clar" / "scripts"
APAVIL_SOURCE_ID = "signal-apavil-valcea-scheduled-outages"
APAVIL_SOURCE_URL = "https://apavil.ro/?page_id=962"


def _today_bucharest() -> date:
    return datetime.now(ZoneInfo("Europe/Bucharest")).date()


def _when_text(row: dict[str, Any]) -> str:
    dates = [str(value) for value in row.get("effective_dates") or [] if str(value)]
    value = ", ".join(dates)
    time_range = row.get("time_range") if isinstance(row.get("time_range"), dict) else {}
    start = str(time_range.get("start") or "").strip()
    end = str(time_range.get("end") or "").strip()
    if start and end:
        value = f"{value}, interval {start}-{end}"
    return value


def _block(signal_id: str, reason: str) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "state": "BLOCKED",
        "reason": reason,
        "publication_authority": "NONE",
    }


def verify_signal(row: dict[str, Any], *, snapshot_sha256: str, as_of: date) -> dict[str, Any]:
    signal_id = str(row.get("signal_id") or "").strip()
    if not signal_id:
        return _block("UNKNOWN", "signal_id_missing")
    if str(row.get("source_id") or "") != APAVIL_SOURCE_ID:
        return _block(signal_id, "unexpected_source_id")
    if str(row.get("source_url") or "") != APAVIL_SOURCE_URL:
        return _block(signal_id, "unexpected_source_url")
    if str(row.get("source_tier") or "") != "T1":
        return _block(signal_id, "source_not_t1")
    if str(row.get("publication_authority") or "") != "NONE":
        return _block(signal_id, "upstream_publication_authority_not_none")
    if row.get("fact_kernel_authority") is not False:
        return _block(signal_id, "signal_adapter_authority_contract_changed")
    if row.get("current_status_claim_allowed") is not False:
        return _block(signal_id, "current_status_claim_not_fail_closed")
    if str(row.get("signal_class") or "") != "SCHEDULED_WATER_OUTAGE":
        return {
            "signal_id": signal_id,
            "state": "NO_STORY",
            "reason": "not_scheduled_water_outage",
            "publication_authority": "NONE",
        }
    if str(row.get("effective_date_status") or "") != "EXPLICIT_VISIBLE_TEXT":
        return _block(signal_id, "effective_date_not_explicit")

    dates: list[date] = []
    for value in row.get("effective_dates") or []:
        try:
            dates.append(date.fromisoformat(str(value)))
        except ValueError:
            return _block(signal_id, "invalid_effective_date")
    if not dates:
        return _block(signal_id, "effective_date_missing")
    if max(dates) < as_of:
        return {
            "signal_id": signal_id,
            "state": "NO_STORY",
            "reason": "stale_scheduled_outage",
            "publication_authority": "NONE",
        }

    geography = [str(value).strip() for value in row.get("explicit_geography") or [] if str(value).strip()]
    if not geography:
        return _block(signal_id, "explicit_geography_missing")
    title = str(row.get("title") or "").strip()
    if len(title) < 20:
        return _block(signal_id, "source_title_insufficient")
    when = _when_text(row)
    if not when:
        return _block(signal_id, "effective_window_missing")

    evidence_ids = [signal_id]
    if snapshot_sha256:
        evidence_ids.append(f"source-snapshot:{snapshot_sha256}")
    place_text = "; ".join(geography)
    claims = (
        title,
        f"Data sau intervalul programat indicat de APAVIL: {when}.",
        f"Zona menționată explicit în anunț: {place_text}.",
    )
    kernel = FactKernel(
        what=title,
        who="APAVIL S.A. Vâlcea",
        where=place_text,
        when=when,
        why_it_matters="Anunțul privește o întrerupere programată a furnizării apei potabile în zona indicată explicit de sursa oficială.",
        source="APAVIL S.A. Vâlcea — Opriri programate",
        source_url=APAVIL_SOURCE_URL,
        claims=claims,
        evidence_ids=tuple(evidence_ids),
    )
    kernel.validate()

    body = (
        f"APAVIL S.A. Vâlcea a publicat pe pagina oficială de opriri programate următorul anunț: {title} "
        f"Programarea vizibilă în sursa oficială indică {when}. Zona identificată explicit în anunț este: {place_text}.\n\n"
        "Core v2 tratează informația strict ca programare anunțată de operator. Această verificare nu afirmă că întreruperea este în desfășurare la momentul citirii și nu extinde datele, intervalul sau aria geografică dincolo de elementele explicite ale sursei."
    )
    article_package = {
        "headline": title,
        "body": body,
        "claims": [
            {"text": claim, "kernel_claim_index": index, "evidence_ids": evidence_ids}
            for index, claim in enumerate(claims)
        ],
    }
    integrity = validate_editorial_package(kernel, article_package)
    if not integrity.pass_gate:
        return _block(signal_id, "deterministic_article_integrity_failed")

    return {
        "signal_id": signal_id,
        "state": "VERIFIED_WRITTEN_SHADOW",
        "publication_authority": "NONE",
        "fact_kernel": {
            "what": kernel.what,
            "who": kernel.who,
            "where": kernel.where,
            "when": kernel.when,
            "why_it_matters": kernel.why_it_matters,
            "source": kernel.source,
            "source_url": kernel.source_url,
            "claims": list(kernel.claims),
            "evidence_ids": list(kernel.evidence_ids),
        },
        "article_package": article_package,
        "integrity": {
            "status": integrity.status,
            "fabricated_claims": integrity.fabricated_claims,
            "bound_claims": integrity.bound_claims,
            "errors": list(integrity.errors),
        },
        "current_status_claim_allowed": False,
    }


def verify_document(document: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or _today_bucharest()
    if str(document.get("source_id") or "") != APAVIL_SOURCE_ID:
        return {
            "schema_version": "1.0",
            "mode": "APAVIL_SHADOW_VERIFICATION",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_SOURCE_CONTRACT",
            "rows": [],
        }
    snapshot_sha256 = str(document.get("source_content_sha256") or "")
    rows = [
        verify_signal(row, snapshot_sha256=snapshot_sha256, as_of=as_of)
        for row in document.get("signals") or []
        if isinstance(row, dict)
    ]
    verified = sum(row.get("state") == "VERIFIED_WRITTEN_SHADOW" for row in rows)
    no_story = sum(row.get("state") == "NO_STORY" for row in rows)
    blocked = sum(row.get("state") == "BLOCKED" for row in rows)
    return {
        "schema_version": "1.0",
        "mode": "APAVIL_SHADOW_VERIFICATION",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "source_snapshot_sha256": snapshot_sha256 or None,
        "as_of_date": as_of.isoformat(),
        "signal_count": len(rows),
        "verified_written_shadow_count": verified,
        "no_story_count": no_story,
        "blocked_count": blocked,
        "rows": rows,
        "truth_rule": "Only explicit first-party APAVIL index metadata is promoted; scheduled does not mean currently interrupted.",
    }


def _live_document() -> dict[str, Any]:
    sys.path.insert(0, str(SCRIPTS))
    adapter = importlib.import_module("apavil_valcea_signal_adapter")
    html_text, final_url, sha = adapter.fetch_html()
    return adapter.build_document(html_text, final_url=final_url, content_sha256=sha)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the first bounded Core v2 source->kernel->writer shadow lane")
    parser.add_argument("--input")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if bool(args.input) == bool(args.live):
        raise SystemExit("provide exactly one of --input or --live")
    try:
        if args.live:
            document = _live_document()
        else:
            document = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = verify_document(document)
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "APAVIL_SHADOW_VERIFICATION",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "BLOCKED_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status", "PASS_SHADOW"),
        "signal_count": result.get("signal_count", 0),
        "verified_written_shadow_count": result.get("verified_written_shadow_count", 0),
        "no_story_count": result.get("no_story_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
