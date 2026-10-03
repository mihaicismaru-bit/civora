from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "valcea-clar" / "scripts"
MAX_SOURCE_AGE_DAYS = 7
ALLOWED_SIGNAL_CLASSES = {
    "ROAD_CLOSURE_NOTICE",
    "ROAD_RESTRICTION_NOTICE",
    "ROADWORKS_NOTICE",
    "ROAD_INFRASTRUCTURE_UPDATE",
    "HOLD",
}


def _today_bucharest() -> date:
    return datetime.now(ZoneInfo("Europe/Bucharest")).date()


def _adapter():
    sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("cj_valcea_roadworks_signal_adapter")


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None


def evaluate_signal(signal: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    """Truth-gate one official CJ road signal without promoting it to a FactKernel."""
    base = {
        "signal_id": signal.get("signal_id"),
        "source_id": signal.get("source_id"),
        "article_url": signal.get("article_url"),
        "title": signal.get("title"),
        "signal_class": signal.get("signal_class"),
        "route_refs": list(signal.get("route_refs") or []),
        "publication_date": signal.get("publication_date"),
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
    }

    if (
        signal.get("publication_authority") != "NONE"
        or signal.get("public_projection") is not False
        or signal.get("auto_publication") is not False
        or signal.get("persistence_allowed") is not False
        or signal.get("fact_kernel_authority") is not False
    ):
        return {**base, "state": "BLOCKED", "reason": "source_contract_authority_violation"}

    signal_class = str(signal.get("signal_class") or "")
    if signal_class not in ALLOWED_SIGNAL_CLASSES:
        return {**base, "state": "BLOCKED", "reason": "unknown_signal_class"}

    if signal_class == "HOLD":
        return {**base, "state": "NO_STORY", "reason": str(signal.get("lifecycle") or "source_adapter_hold")}

    publication_date = _parse_date(signal.get("publication_date"))
    if publication_date is None:
        return {**base, "state": "BLOCKED", "reason": "publication_date_unverified"}
    if publication_date > as_of:
        return {**base, "state": "BLOCKED", "reason": "future_publication_date_anomaly"}
    age_days = (as_of - publication_date).days
    base["source_age_days"] = age_days

    if not str(signal.get("publication_date_status") or "").startswith("URL_PATH_AND_"):
        return {**base, "state": "BLOCKED", "reason": "publication_date_not_confirmed_by_first_party_article"}
    if not base["route_refs"]:
        return {**base, "state": "BLOCKED", "reason": "explicit_county_road_reference_missing"}
    if age_days > MAX_SOURCE_AGE_DAYS:
        return {**base, "state": "NO_STORY", "reason": "stale_source_article_for_live_news_pilot"}

    excerpt = str(signal.get("summary_excerpt") or "").strip()
    if not excerpt:
        return {**base, "state": "BLOCKED", "reason": "official_article_body_excerpt_missing"}

    if signal_class in {"ROAD_CLOSURE_NOTICE", "ROAD_RESTRICTION_NOTICE"}:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "current_operational_status_recheck_required",
            "evidence_status": "FIRST_PARTY_ARTICLE_BODY_PRESENT",
            "material_fact_status": "UNADJUDICATED",
            "current_status_claim_allowed": False,
        }

    return {
        **base,
        "state": "BLOCKED",
        "reason": "material_fact_extraction_required",
        "evidence_status": "FIRST_PARTY_ARTICLE_BODY_PRESENT",
        "material_fact_status": "UNADJUDICATED",
        "current_status_claim_allowed": False,
    }


def verify_document(document: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    policy = document.get("policy") or {}
    if any(
        (
            policy.get("publication_authority") != "NONE",
            policy.get("signal_only") is not True,
            policy.get("public_projection") is not False,
            policy.get("auto_publication") is not False,
            policy.get("persistence_allowed") is not False,
            policy.get("fact_kernel_authority") is not False,
            policy.get("current_status_claim_allowed") is not False,
        )
    ):
        return {
            "schema_version": "1.0",
            "mode": "CJ_ROAD_SHADOW",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "status": "BLOCKED_SOURCE_CONTRACT",
            "reason": "legacy_adapter_policy_not_fail_closed",
            "rows": [],
        }

    signals = [row for row in document.get("signals") or [] if isinstance(row, dict)]
    rows = [evaluate_signal(signal, as_of=as_of) for signal in signals]
    fetch_holds = list(document.get("fetch_holds") or [])
    no_story = sum(row.get("state") == "NO_STORY" for row in rows)
    blocked = sum(row.get("state") == "BLOCKED" for row in rows) + len(fetch_holds)
    fresh_material_candidates = sum(
        row.get("reason") in {"material_fact_extraction_required", "current_operational_status_recheck_required"}
        for row in rows
    )
    return {
        "schema_version": "1.0",
        "mode": "CJ_ROAD_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "status": "PASS_SHADOW",
        "source_id": document.get("source_id"),
        "discovered_article_count": int(document.get("discovered_article_count") or 0),
        "signal_count": len(signals),
        "fetch_hold_count": len(fetch_holds),
        "no_story_count": no_story,
        "blocked_count": blocked,
        "fresh_material_candidate_count": fresh_material_candidates,
        "verified_written_shadow_count": 0,
        "fabricated_claim_count": 0,
        "rows": rows,
        "fetch_holds": fetch_holds,
        "truth_rule": (
            "Official CJ road article bodies are source evidence only. Fresh works/update signals require separate material-fact extraction; "
            "closure/restriction signals additionally require a current operational-status recheck. No signal can create a FactKernel or article here."
        ),
    }


def collect_live(*, as_of: date | None = None, article_limit: int = 16) -> dict[str, Any]:
    as_of = as_of or _today_bucharest()
    adapter = _adapter()
    document = adapter.build_live_document(article_limit=article_limit)
    return verify_document(document, as_of=as_of)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CJ Vâlcea road signals in read-only Core v2 shadow mode")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--article-limit", type=int, default=16)
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("only --live read-only shadow collection is supported")
    try:
        result = collect_live(article_limit=max(1, min(args.article_limit, 16)))
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "CJ_ROAD_SHADOW",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "status": "BLOCKED_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "discovered_article_count": result.get("discovered_article_count", 0),
        "signal_count": result.get("signal_count", 0),
        "fetch_hold_count": result.get("fetch_hold_count", 0),
        "fresh_material_candidate_count": result.get("fresh_material_candidate_count", 0),
        "no_story_count": result.get("no_story_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "verified_written_shadow_count": 0,
        "fabricated_claim_count": 0,
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
