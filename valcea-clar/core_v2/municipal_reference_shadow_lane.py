from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "valcea-clar" / "scripts"

SOURCE_ID = "signal-ramnicu-valcea-local-council-decision-reference"
EXPECTED_SOURCE_TIER = "T1_OFFICIAL_MUNICIPALITY_FIRST_PARTY"
EXPECTED_REFERENCE_SCOPE = "FIRST_PARTY_LOCAL_COUNCIL_ADOPTED_DECISION_REFERENCE_ONLY"
EXPECTED_SOURCE_URL_PREFIX = "https://dm.primariavl.ro/dm/2026/hotarari.nsf/"


def _today_bucharest() -> date:
    return datetime.now(ZoneInfo("Europe/Bucharest")).date()


def _to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    raise TypeError("municipal state must be dataclass or dict")


def verify_state(state_value: Any, *, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or _today_bucharest()
    state = _to_dict(state_value)

    base = {
        "schema_version": "1.0",
        "mode": "MUNICIPAL_REFERENCE_SHADOW_VERIFICATION",
        "source_id": SOURCE_ID,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "as_of_date": as_of.isoformat(),
    }

    if str(state.get("source_id") or "") != SOURCE_ID:
        return {**base, "status": "BLOCKED_SOURCE_CONTRACT", "reason": "unexpected_source_id", "rows": []}
    if str(state.get("source_tier") or "") != EXPECTED_SOURCE_TIER:
        return {**base, "status": "BLOCKED_SOURCE_CONTRACT", "reason": "unexpected_source_tier", "rows": []}
    source_url = str(state.get("source_url") or "")
    if not source_url.startswith(EXPECTED_SOURCE_URL_PREFIX):
        return {**base, "status": "BLOCKED_SOURCE_CONTRACT", "reason": "unexpected_source_url", "rows": []}
    if str(state.get("reference_scope") or "") != EXPECTED_REFERENCE_SCOPE:
        return {**base, "status": "BLOCKED_SOURCE_CONTRACT", "reason": "unexpected_reference_scope", "rows": []}
    if str(state.get("publication_authority") or "") != "NONE":
        return {**base, "status": "BLOCKED_UPSTREAM_AUTHORITY_CHANGED", "reason": "publication_authority_not_none", "rows": []}

    forbidden_authority_flags = (
        "decision_document_follow_allowed",
        "decision_document_body_fetch_allowed",
        "legal_effect_inference_allowed",
        "current_validity_inference_allowed",
        "amendment_status_inference_allowed",
        "repeal_status_inference_allowed",
        "implementation_status_inference_allowed",
        "breaking_news_promotion_allowed",
        "persistence_allowed",
        "fact_kernel_promotion_allowed",
        "writer_allowed",
        "public_projection_allowed",
    )
    for name in forbidden_authority_flags:
        if state.get(name) is not False:
            return {
                **base,
                "status": "BLOCKED_UPSTREAM_AUTHORITY_CHANGED",
                "reason": f"{name}_must_remain_false",
                "rows": [],
            }

    if str(state.get("state") or "") != "REFERENCE_READY":
        return {
            **base,
            "status": "BLOCKED_SOURCE_RECEIPT",
            "reason": str(state.get("hold_reason") or state.get("state") or "unknown_source_state"),
            "rows": [],
        }

    rows: list[dict[str, Any]] = []
    for ref in state.get("references") or []:
        if not isinstance(ref, dict):
            continue
        number = ref.get("decision_number")
        decision_date = str(ref.get("decision_date") or "")
        title_hint = str(ref.get("title_hint") or "").strip()
        evidence_sha = str(ref.get("evidence_sha256") or "").strip()
        document_url = str(ref.get("document_reference_url") or "").strip()
        row_id = f"hcl-{number}-{decision_date}" if number and decision_date else evidence_sha[:24] or "UNKNOWN"

        if not number or not decision_date or not evidence_sha or not document_url:
            rows.append({
                "reference_id": row_id,
                "state": "BLOCKED",
                "reason": "reference_evidence_incomplete",
                "publication_authority": "NONE",
            })
            continue
        if ref.get("document_reference_unfollowed") is not True:
            rows.append({
                "reference_id": row_id,
                "state": "BLOCKED",
                "reason": "reference_follow_contract_changed",
                "publication_authority": "NONE",
            })
            continue

        rows.append({
            "reference_id": row_id,
            "state": "NO_STORY",
            "reason": "reference_metadata_only_no_material_fact_body",
            "publication_authority": "NONE",
            "decision_number": int(number),
            "decision_date": decision_date,
            "title_hint": title_hint,
            "document_reference_url": document_url,
            "evidence_ids": [f"municipal-reference:{evidence_sha}"],
            "truth_note": (
                "A first-party adopted-decision reference proves only that the municipal index exposes this reference. "
                "It does not prove legal effect, current validity, implementation, money, people, or a material news fact, "
                "and therefore cannot create a FactKernel or article by itself."
            ),
        })

    no_story = sum(row.get("state") == "NO_STORY" for row in rows)
    blocked = sum(row.get("state") == "BLOCKED" for row in rows)
    return {
        **base,
        "status": "PASS_SHADOW",
        "reference_count": len(rows),
        "verified_written_shadow_count": 0,
        "no_story_count": no_story,
        "blocked_count": blocked,
        "fabricated_claim_count": 0,
        "rows": rows,
        "truth_rule": (
            "Raw HCL/register metadata is evidence of a reference only. Without separately captured first-party body evidence "
            "for a material fact, the terminal result is NO_STORY and writer authority remains false."
        ),
    }


def _live_state(*, as_of: date):
    sys.path.insert(0, str(SCRIPTS))
    adapter = importlib.import_module("ramnicu_valcea_local_council_decision_reference_adapter")
    return adapter.run_live(as_of=as_of)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Core v2 municipal decision-reference lane in shadow mode")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if bool(args.live) == bool(args.input):
        raise SystemExit("provide exactly one of --live or --input")

    as_of = _today_bucharest()
    try:
        if args.live:
            state = _live_state(as_of=as_of)
        else:
            state = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = verify_state(state, as_of=as_of)
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "MUNICIPAL_REFERENCE_SHADOW_VERIFICATION",
            "source_id": SOURCE_ID,
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "production_writer_ready": False,
            "status": "BLOCKED_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "reference_count": result.get("reference_count", 0),
        "verified_written_shadow_count": result.get("verified_written_shadow_count", 0),
        "no_story_count": result.get("no_story_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "fabricated_claim_count": result.get("fabricated_claim_count", 0),
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
