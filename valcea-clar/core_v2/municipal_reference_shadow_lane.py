from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import ssl
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from urllib.request import HTTPSHandler, Request, build_opener
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "valcea-clar" / "scripts"

SOURCE_ID = "signal-ramnicu-valcea-local-council-decision-reference"
EXPECTED_SOURCE_TIER = "T1_OFFICIAL_MUNICIPALITY_FIRST_PARTY"
EXPECTED_REFERENCE_SCOPE = "FIRST_PARTY_LOCAL_COUNCIL_ADOPTED_DECISION_REFERENCE_ONLY"
EXPECTED_SOURCE_URL_PREFIX = "https://dm.primariavl.ro/dm/2026/hotarari.nsf/"
EXPANDED_INDEX_URL = "https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?OpenView&Count=500"


def _today_bucharest() -> date:
    return datetime.now(ZoneInfo("Europe/Bucharest")).date()


def _to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    raise TypeError("municipal state must be dataclass or dict")


def _validate_expanded_index_url(url: str) -> str:
    parsed = urlsplit(str(url).strip())
    params = [(k.casefold(), v.casefold()) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != "dm.primariavl.ro"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path != "/dm/2026/hotarari.nsf/vwHotarariByAn"
        or params != [("openview", ""), ("count", "500")]
        or parsed.fragment
    ):
        raise ValueError(f"off-surface expanded municipal index refused: {url}")
    return urlunsplit(("https", "dm.primariavl.ro", parsed.path, "OpenView&Count=500", ""))


def _parse_expanded_index(
    html_text: str,
    payload: bytes,
    *,
    as_of: date,
    canonical_source_url: str,
    transport_url: str,
) -> dict[str, Any]:
    """Parse only first-party adopted-decision register metadata.

    The older reference adapter assumed that every usable reference lived inside a
    table row with a direct `$FILE` link. The live DocManager register exposes a
    reliable flat visible-text sequence even when that DOM/link assumption fails.
    We therefore reuse only the proven read-only parser from the legacy council
    monitor (`to_text`, `parse_register`, `attachment_index`). No target-date
    selection, document fetch, legal inference, persistence or publication state
    is inherited from the legacy monitor.
    """
    sys.path.insert(0, str(SCRIPTS))
    monitor = importlib.import_module("council_watch_rm_valcea")

    visible_text = monitor.to_text(html_text)
    register_rows = monitor.parse_register(visible_text)
    attachments = monitor.attachment_index(transport_url, html_text)

    references: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for row in register_rows:
        number = row.get("decision_number")
        decision_date = str(row.get("decision_date") or "")
        title = " ".join(str(row.get("title") or "").split()).strip()
        if not isinstance(number, int) or number <= 0 or not decision_date.startswith(f"{as_of.year}-"):
            continue
        key = (number, decision_date)
        if key in seen:
            continue
        seen.add(key)
        document_url = attachments.get(key)
        evidence_payload = (
            "kind=LOCAL_COUNCIL_ADOPTED_DECISION_INDEX_REFERENCE|"
            f"decision_number={number}|decision_date={decision_date}|title_hint={title}|"
            f"document_reference_url={document_url or ''}|index={canonical_source_url}|transport={transport_url}"
        )
        references.append(
            {
                "kind": "LOCAL_COUNCIL_ADOPTED_DECISION_REFERENCE",
                "decision_number": number,
                "decision_date": decision_date,
                "title_hint": title[:500],
                "document_reference_url": document_url,
                "document_reference_available": bool(document_url),
                "document_reference_unfollowed": True,
                "canonical_index_url": canonical_source_url,
                "evidence_sha256": hashlib.sha256(evidence_payload.encode("utf-8")).hexdigest(),
            }
        )

    references.sort(
        key=lambda item: (str(item["decision_date"]), int(item["decision_number"])),
        reverse=True,
    )
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "source_id": SOURCE_ID,
        "source_tier": EXPECTED_SOURCE_TIER,
        "source_url": canonical_source_url,
        "source_payload_sha256": digest,
        "reference_scope": EXPECTED_REFERENCE_SCOPE,
        "publication_authority": "NONE",
        "state": "REFERENCE_READY" if references else "HOLD",
        "hold_reason": None if references else "current_year_local_council_decision_references_missing",
        "decision_document_follow_allowed": False,
        "decision_document_body_fetch_allowed": False,
        "legal_effect_inference_allowed": False,
        "current_validity_inference_allowed": False,
        "amendment_status_inference_allowed": False,
        "repeal_status_inference_allowed": False,
        "implementation_status_inference_allowed": False,
        "breaking_news_promotion_allowed": False,
        "persistence_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "public_projection_allowed": False,
        "references": references,
        "_transport_url": transport_url,
        "_transport_parser": "legacy_text_register_parser_reused_without_authority",
        "_register_entries_parsed": len(register_rows),
        "_current_year_references": len(references),
        "_direct_attachment_references": sum(bool(row.get("document_reference_url")) for row in references),
    }


def verify_state(state_value: Any, *, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or _today_bucharest()
    state = _to_dict(state_value)

    base = {
        "schema_version": "1.2",
        "mode": "MUNICIPAL_REFERENCE_SHADOW_VERIFICATION",
        "source_id": SOURCE_ID,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "as_of_date": as_of.isoformat(),
        "transport_url": state.get("_transport_url"),
        "transport_parser": state.get("_transport_parser"),
        "register_entries_parsed": int(state.get("_register_entries_parsed") or 0),
        "direct_attachment_references": int(state.get("_direct_attachment_references") or 0),
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
        document_url = str(ref.get("document_reference_url") or "").strip() or None
        row_id = f"hcl-{number}-{decision_date}" if number and decision_date else evidence_sha[:24] or "UNKNOWN"

        if not number or not decision_date or not evidence_sha:
            rows.append({
                "reference_id": row_id,
                "state": "BLOCKED",
                "reason": "reference_evidence_incomplete",
                "publication_authority": "NONE",
            })
            continue
        if document_url and ref.get("document_reference_unfollowed") is not True:
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
            "document_reference_available": bool(document_url),
            "evidence_ids": [f"municipal-reference:{evidence_sha}"],
            "truth_note": (
                "A first-party adopted-decision index reference proves only that the official register exposes the numbered/date-labeled reference. "
                "It does not prove legal effect, current validity, implementation, money, people, or a material news fact. "
                "Missing direct attachment linkage is retained as missing rather than guessed, and no FactKernel or article is created."
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


def _live_state(*, as_of: date) -> dict[str, Any]:
    sys.path.insert(0, str(SCRIPTS))
    adapter = importlib.import_module("ramnicu_valcea_local_council_decision_reference_adapter")
    transport_url = _validate_expanded_index_url(EXPANDED_INDEX_URL)
    opener = build_opener(adapter.NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        transport_url,
        headers={"User-Agent": adapter.USER_AGENT, "Accept": "text/html,*/*;q=0.8", "Cache-Control": "no-cache"},
    )
    with opener.open(request, timeout=adapter.TIMEOUT_SECONDS) as response:
        final_url = _validate_expanded_index_url(response.geturl())
        if final_url != transport_url:
            raise ValueError("expanded municipal index drift after fetch")
        content_type = str(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML municipal index refused: {content_type or 'unknown'}")
        payload = response.read(adapter.MAX_RESPONSE_BYTES + 1)
        if len(payload) > adapter.MAX_RESPONSE_BYTES:
            raise ValueError("expanded municipal index exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="replace")
    return _parse_expanded_index(
        text,
        payload,
        as_of=as_of,
        canonical_source_url=adapter.SOURCE_URL,
        transport_url=transport_url,
    )


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
            "schema_version": "1.2",
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
        "register_entries_parsed": result.get("register_entries_parsed", 0),
        "direct_attachment_references": result.get("direct_attachment_references", 0),
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
