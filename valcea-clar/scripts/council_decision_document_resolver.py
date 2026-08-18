#!/usr/bin/env python3
"""Resolve full official DocManager documents for adopted HCL articles.

This is the generic companion to the gambling-only Council Fact Kernel resolver.
It uses the exact parsed HCL table row to recover a Lotus document UNID, follows
only same-host/same-document HTML `$FILE` children, and accepts a document only
when operative `Art.` clauses are present.  It never executes JavaScript and
never crosses the municipality's official DocManager host.

Output enriches `council_watch_rm_valcea_state.json`; it does not publish.  The
stable one-HCL-one-article engine consumes this evidence on its next pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

import council_docmanager_embedded_resolver as embedded
import council_docmanager_row_resolver as rows
import council_watch_rm_valcea as council

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "editorial" / "council_watch_rm_valcea_state.json"
OUTPUT = ROOT / "editorial" / "council_decision_document_corpus.json"
RESOLVER_ID = "council_decision_document_resolver_v1"
MAX_TEXT = 90000
MAX_CHILDREN = 8


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def document_identity_ok(text: str, number: int, day: str, *, exact_unid_route: bool) -> tuple[bool, str]:
    articles = council.operative_articles(text)
    if not articles:
        return False, "NO_OPERATIVE_ARTICLES"
    folded = text.casefold()
    number_patterns = (
        rf"\bhot[ăaâ]r(?:â|a)rea\s+(?:nr\.?\s*)?{number}\b",
        rf"\bhotarirea\s+(?:nr\.?\s*)?{number}\b",
        rf"\bnr\.?\s*{number}\s*/\s*2026\b",
    )
    number_seen = any(re.search(pattern, folded, re.I) for pattern in number_patterns)
    if number_seen:
        return True, "PASS_NUMBER_PLUS_OPERATIVE_ARTICLES"
    # The structural row resolver has already tied the OpenDocument URL to the
    # exact decision number/date and embedded extraction enforces the same UNID.
    # Under that exact route, operative articles are sufficient without fuzzy
    # title matching.
    if exact_unid_route:
        return True, "PASS_EXACT_ROW_UNID_PLUS_OPERATIVE_ARTICLES"
    return False, "DECISION_IDENTITY_NOT_CONFIRMED"


def extract_document(row: dict[str, Any], candidate_url: str) -> dict[str, Any]:
    number = int(row.get("decision_number") or 0)
    day = str(row.get("decision_date") or "")
    initial = council.fetch(candidate_url, timeout=22)
    record: dict[str, Any] = {
        "decision_number": number,
        "decision_date": day,
        "registered_title": row.get("title"),
        "candidate_url": candidate_url,
        "candidate_http_status": initial.get("status"),
        "candidate_error": initial.get("error"),
        "resolved": False,
    }
    if not initial.get("ok"):
        record["reason"] = "CANDIDATE_UNREACHABLE"
        return record

    page_url = str(initial.get("url") or candidate_url)
    base_unid = embedded._document_unid(page_url)
    candidates: list[tuple[str, dict[str, Any], bool]] = [(page_url, initial, bool(base_unid))]

    for link in embedded.embedded_attachment_links(page_url, str(initial.get("body") or ""))[:MAX_CHILDREN]:
        child_url = str(link.get("url") or "")
        if not child_url:
            continue
        child = council.fetch(child_url, timeout=22)
        if child.get("ok"):
            candidates.append((str(child.get("url") or child_url), child, True))

    # Some document pages expose normal anchors in addition to embedded viewer
    # metadata. `structural_parse_links` applies the same canonical-host guard.
    for link in embedded.structural_parse_links(page_url, str(initial.get("body") or ""))[:MAX_CHILDREN]:
        child_url = str(link.get("url") or "")
        low = urllib.parse.unquote(child_url).lower()
        if not child_url or "$file" not in low or not low.endswith((".htm", ".html")):
            continue
        if any(url == child_url for url, _result, _exact in candidates):
            continue
        child = council.fetch(child_url, timeout=22)
        if child.get("ok"):
            candidates.append((str(child.get("url") or child_url), child, True))

    seen_reasons: list[str] = []
    for url, result, exact in candidates:
        text = council.to_text(str(result.get("body") or ""))
        ok, reason = document_identity_ok(text, number, day, exact_unid_route=exact)
        seen_reasons.append(reason)
        if not ok:
            continue
        articles = council.operative_articles(text)
        record.update({
            "resolved": True,
            "reason": reason,
            "official_html_url": url,
            "http_status": result.get("status"),
            "source_sha256": result.get("sha256"),
            "document_unid": embedded._document_unid(url),
            "operative_articles": articles,
            "vote_snippets": council.snippets(r"\bvot(?:uri|ul|at|uri)?\b|unanimit|abțin|abtin|împotriv|impotriv", text, limit=8),
            "money_snippets": council.snippets(r"\b(?:lei|RON|euro|EUR)\b", text, limit=16, radius=420),
            "procurement_snippets": council.snippets(r"achizi|contract|atribu|concesi|închiri|inchiri|licita", text, limit=14, radius=420),
            "project_snippets": council.snippets(r"proiect|finanț|finant|PNRR|POR|PR Sud|SMIS|fonduri", text, limit=14, radius=420),
            "entity_snippets": council.snippets(r"\b(?:S\.A\.|S\.R\.L\.|SA\b|SRL\b|UAT\b|ETA\b|CET\b|Consiliul Județean|Consiliul Judetean)\b", text, limit=16, radius=420),
            "document_text": text[:MAX_TEXT],
            "document_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
        return record

    record["reason"] = "NO_GENERIC_OFFICIAL_DOCUMENT_MATCH"
    record["attempt_reasons"] = seen_reasons
    record["candidate_child_count"] = max(0, len(candidates) - 1)
    return record


def build(*, live: bool, apply: bool) -> dict[str, Any]:
    state = load(STATE, {}) or {}
    target = state.get("target_meeting") if isinstance(state.get("target_meeting"), dict) else {}
    meeting_date = str(target.get("date") or "").strip()
    requested = [
        dict(row) for row in state.get("target_decisions") or []
        if isinstance(row, dict) and str(row.get("decision_date") or "") == meeting_date
    ]
    if not meeting_date or not requested:
        raise SystemExit("target meeting decisions unavailable")

    embedded.install()
    register_url = str((state.get("source") or {}).get("url") or council.ADOPTED_VIEW)
    register = council.fetch(register_url, timeout=22) if live else {"ok": False, "error": "OFFLINE"}
    mapping: dict[int, str] = {}
    if register.get("ok"):
        mapping = rows.structural_decision_attachments(
            str(register.get("url") or register_url),
            str(register.get("body") or ""),
            requested,
        )

    documents: list[dict[str, Any]] = []
    for row in requested:
        number = int(row.get("decision_number") or 0)
        candidate = mapping.get(number)
        if not candidate:
            documents.append({
                "decision_number": number,
                "decision_date": row.get("decision_date"),
                "registered_title": row.get("title"),
                "resolved": False,
                "reason": "ROW_DOCUMENT_URL_NOT_RESOLVED",
            })
            continue
        documents.append(extract_document(row, candidate))

    by_number = {int(row["decision_number"]): row for row in documents}
    if apply:
        changed = False
        enriched = []
        for row in state.get("target_decisions") or []:
            if not isinstance(row, dict):
                enriched.append(row)
                continue
            number = int(row.get("decision_number") or 0)
            doc = by_number.get(number)
            if not doc or not doc.get("resolved"):
                enriched.append(row)
                continue
            updated = dict(row)
            for key in (
                "official_html_url", "http_status", "source_sha256", "operative_articles",
                "vote_snippets", "money_snippets", "procurement_snippets", "project_snippets", "entity_snippets",
            ):
                updated[key] = doc.get(key)
            updated["document_health"] = "OK_GENERIC_RESOLVER"
            updated["document_resolver"] = RESOLVER_ID
            updated["document_text_sha256"] = doc.get("document_text_sha256")
            enriched.append(updated)
            changed = changed or updated != row
        state["target_decisions"] = enriched
        state.setdefault("policy", {})["generic_hcl_document_resolver"] = RESOLVER_ID
        if changed:
            write(STATE, state)

    corpus = {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR official HCL document corpus",
        "resolver_id": RESOLVER_ID,
        "meeting_date": meeting_date,
        "mode": "LIVE" if live else "OFFLINE",
        "register_url": register_url,
        "register_reachable": bool(register.get("ok")),
        "register_error": register.get("error"),
        "requested": len(requested),
        "row_urls_resolved": len(mapping),
        "documents_resolved": sum(1 for row in documents if row.get("resolved")),
        "documents": documents,
        "policy": {
            "official_host_only": True,
            "exact_hcl_row_unid_required": True,
            "same_document_attachment_only": True,
            "operative_articles_required": True,
            "javascript_executed": False,
            "publication_authority": "NONE",
        },
    }
    if apply:
        write(OUTPUT, corpus)
    return corpus


def self_test() -> int:
    text = "CONSILIUL LOCAL HOTĂRÂREA NR. 306 Art. 1. Se aprobă măsura. Art. 2. Primarul duce la îndeplinire."
    ok, reason = document_identity_ok(text, 306, "2026-08-14", exact_unid_route=False)
    assert ok and reason == "PASS_NUMBER_PLUS_OPERATIVE_ARTICLES"
    ok, reason = document_identity_ok("Art. 1. Se aprobă măsura.", 306, "2026-08-14", exact_unid_route=True)
    assert ok and reason == "PASS_EXACT_ROW_UNID_PLUS_OPERATIVE_ARTICLES"
    ok, _ = document_identity_ok("Titlu fără articole", 306, "2026-08-14", exact_unid_route=True)
    assert not ok
    print("VÂLCEA CLAR generic HCL document resolver self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    result = build(live=args.live, apply=args.apply)
    print(json.dumps({
        "status": "PASS",
        "meeting_date": result["meeting_date"],
        "requested": result["requested"],
        "row_urls_resolved": result["row_urls_resolved"],
        "documents_resolved": result["documents_resolved"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
