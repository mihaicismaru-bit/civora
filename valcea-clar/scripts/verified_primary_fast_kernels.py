#!/usr/bin/env python3
"""Promote fresh first-party IPJ/ISU detail evidence into fast fact kernels.

This is the narrow bridge between CIVORA's non-authorizing evidence adapters and
its canonical fact-kernel writer.  It does not promote secondary signals, titles
alone, allegations, inferred causes or stale references.  It may promote a short
reader-facing kernel only when the same run can re-read an allow-listed county
authority detail page, bind the copy to that exact URL/content hash, find an
explicit fresh date and reconcile at least two substantive source fragments.

The resulting story still passes Editorial Writer, Editorial Integrity and the
normal Live Newsroom gate.  Source failure holds only this fast lane; it must not
stop unrelated newsroom publication.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import ipj_valcea_public_safety_detail_evidence as ipj_detail
import isu_valcea_emergency_detail_evidence as isu_detail

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "local-news-os" / "core"))
from temporal_freshness import durable_story_temporal_violations

FACTS = ROOT / "editorial" / "facts_registry.json"
STATE = ROOT / "editorial" / "verified_primary_fast_kernel_state.json"
TZ = ZoneInfo("Europe/Bucharest")
MAX_AGE_DAYS = 2
MAX_STORIES_PER_SOURCE = 4
FAST_SCOPE = "verified_primary_fast_brief"
PROMOTION_GATE = "VERIFIED_PRIMARY_MINIMUM_V1"

ROMANIAN_MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}

SOURCE_CONFIG = {
    "ipj": {
        "label": "IPJ Vâlcea",
        "section": "SIGURANȚĂ",
        "priority": 96,
        "hosts": {"vl.politiaromana.ro"},
        "required_any": {"POLICE_REPORTED_OBSERVATION"},
        "usable": {"POLICE_REPORTED_OBSERVATION", "PROCEDURAL_MEASURE", "ROAD_OR_PUBLIC_SAFETY_MEASURE"},
        "forbidden": {"ALLEGATION_OR_SUSPICION"},
        "source_name": "IPJ Vâlcea — comunicare oficială",
    },
    "isu": {
        "label": "ISU Vâlcea",
        "section": "URGENȚE",
        "priority": 97,
        "hosts": {"isuvl.igsu.ro"},
        "required_any": {"ISU_REPORTED_OBSERVATION"},
        "usable": {"ISU_REPORTED_OBSERVATION", "RESPONSE_ACTION", "REPORTED_AFFECTED_OR_CASUALTY"},
        # Causes and warnings require their own currentness/context reconciliation.
        "forbidden": {"REPORTED_CAUSE_OR_ORIGIN", "PUBLIC_PROTECTION_WARNING_OR_RESTRICTION"},
        "source_name": "ISU Vâlcea — comunicare oficială",
    },
}


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_explicit_date(value: str | None) -> date | None:
    text = " ".join(str(value or "").strip().casefold().split())
    if not text:
        return None
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(0?[1-9]|[12][0-9]|3[01])\s+([a-zăâîșşțţ]+)\s+(20\d{2})", text)
    if not match:
        return None
    month = ROMANIAN_MONTHS.get(match.group(2))
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def fresh_date(value: str | None, *, today: date) -> date | None:
    observed = parse_explicit_date(value)
    if observed is None:
        return None
    age = (today - observed).days
    if age < 0 or age > MAX_AGE_DAYS:
        return None
    return observed


def clean_title(value: str, label: str) -> str:
    text = " ".join(unquote(str(value or "")).split())
    for suffix in (f" - {label}", f" | {label}", f" – {label}", f" — {label}"):
        if text.casefold().endswith(suffix.casefold()):
            text = text[: -len(suffix)].strip()
    for prefix in (f"{label} - ", f"{label}: ", f"{label} | "):
        if text.casefold().startswith(prefix.casefold()):
            text = text[len(prefix):].strip()
    return text


def truncate_words(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (cut or text[: limit - 1]).rstrip() + "…"


def stable_story_id(source_key: str, detail_url: str) -> str:
    slug = unquote(urlsplit(detail_url).path.rstrip("/").split("/")[-1]).casefold()
    slug = re.sub(r"[^a-z0-9ăâîșşțţ-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    # Story IDs are projected through an ASCII slugger later; the URL hash is the
    # durable identity even if Romanian diacritics collapse there.
    ascii_slug = (
        slug.replace("ă", "a").replace("â", "a").replace("î", "i")
        .replace("ș", "s").replace("ş", "s").replace("ț", "t").replace("ţ", "t")
    )
    digest = hashlib.sha256(detail_url.encode("utf-8")).hexdigest()[:10]
    return f"fast-{source_key}-{(ascii_slug or 'actualizare')[:54]}-{digest}"


def field_rows(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in detail.get("field_evidence") or [] if isinstance(row, dict)]


def selected_fragments(source_key: str, detail: dict[str, Any]) -> list[dict[str, Any]]:
    config = SOURCE_CONFIG[source_key]
    usable = set(config["usable"])
    forbidden = set(config["forbidden"])
    candidates: list[dict[str, Any]] = []
    for row in field_rows(detail):
        excerpt = " ".join(str(row.get("excerpt") or "").split())
        tags = {str(tag) for tag in row.get("epistemic_tags") or []}
        if len(excerpt) < 45 or not (tags & usable) or (tags & forbidden):
            continue
        candidates.append({"excerpt": excerpt, "tags": tags, "evidence_sha256": row.get("evidence_sha256")})

    if not candidates:
        return []
    if not any(row["tags"] & set(config["required_any"]) for row in candidates):
        return []

    # Prefer the observed event first, then action/status. Keep the fast product
    # intentionally short; richer context belongs in later updates of same story.
    selected: list[dict[str, Any]] = []
    for row in candidates:
        if row["tags"] & set(config["required_any"]):
            selected.append(row)
            break
    for row in candidates:
        if row in selected:
            continue
        selected.append(row)
        if len(selected) == 3:
            break
    if len(selected) < 2:
        return []
    if sum(len(row["excerpt"]) for row in selected) < 120:
        return []
    return selected


def attributed_claim(label: str, row: dict[str, Any], source_url: str, index: int) -> dict[str, Any]:
    excerpt = row["excerpt"].strip()
    text = f"{label} precizează în comunicarea oficială: {excerpt}"
    tags = set(row["tags"])
    if index == 0:
        role = "material_change"
    elif "PROCEDURAL_MEASURE" in tags or "RESPONSE_ACTION" in tags:
        role = "consequence"
    else:
        role = "context"
    return {
        "id": f"primary-{index + 1}",
        "role": role,
        "kind": "attributed_statement",
        "attribution": label,
        "text": text,
        "source_urls": [source_url],
    }


def promote_detail(source_key: str, detail: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any] | None, str]:
    config = SOURCE_CONFIG[source_key]
    source_url = str(detail.get("detail_url") or "").strip()
    parts = urlsplit(source_url)
    if parts.scheme != "https" or (parts.hostname or "").casefold() not in config["hosts"]:
        return None, "non_first_party_detail_url"
    if not re.fullmatch(r"[0-9a-f]{64}", str(detail.get("detail_sha256") or "")):
        return None, "detail_hash_missing"
    if not re.fullmatch(r"[0-9a-f]{64}", str(detail.get("index_evidence_sha256") or "")):
        return None, "index_evidence_hash_missing"
    if "EVIDENCE_CAPTURED_NON_AUTHORIZING" not in str(detail.get("verification_state") or ""):
        return None, "detail_verification_state_invalid"

    event_date = fresh_date(detail.get("explicit_date_text"), today=now.date())
    if event_date is None:
        return None, "explicit_fresh_date_required"

    title = clean_title(str(detail.get("index_title") or detail.get("visible_title") or ""), str(config["label"]))
    if len(title) < 12:
        return None, "source_title_too_thin"
    fragments = selected_fragments(source_key, detail)
    if len(fragments) < 2:
        return None, "minimum_reconciled_primary_fragments_not_met"

    label = str(config["label"])
    headline = truncate_words(f"{label}: {title}", 140)
    date_text = event_date.strftime("%d.%m.%Y")
    dek = (
        f"Comunicarea oficială a {label} conține informații verificabile despre cazul din {date_text}. "
        "VÂLCEA CLAR publică numai elementele atribuite explicit autorității și actualizează materialul când apar date noi."
    )
    claims = [attributed_claim(label, row, source_url, index) for index, row in enumerate(fragments)]

    valid_from = datetime.combine(event_date, time(0, 0), tzinfo=TZ)
    valid_until = now + timedelta(days=14)
    story = {
        "id": stable_story_id(source_key, source_url),
        "status": "verified",
        "section": config["section"],
        "priority": config["priority"],
        "confidence": 97,
        "material_fact_gate": "PASS",
        "valid_from": valid_from.isoformat(timespec="seconds"),
        "valid_until": valid_until.isoformat(timespec="seconds"),
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [],
        "sources": [{"name": config["source_name"], "url": source_url, "tier": "T1"}],
        "auto_generated": True,
        "auto_scope": FAST_SCOPE,
        "fact_kernel": {
            "format_hint": "straight_news",
            "headline": {"text": headline, "source_urls": [source_url]},
            "dek": {"text": dek, "source_urls": [source_url]},
            "claims": claims,
        },
        "primary_source_verification": {
            "verified_at": now.isoformat(timespec="seconds"),
            "promotion_gate": PROMOTION_GATE,
            "source_family": source_key.upper(),
            "direct_first_party_detail": True,
            "fresh_explicit_date_required": True,
            "freshness_window_days": MAX_AGE_DAYS,
            "detail_sha256": detail["detail_sha256"],
            "index_evidence_sha256": detail["index_evidence_sha256"],
            "field_evidence_sha256": [row.get("evidence_sha256") for row in fragments],
            "secondary_signal_used_as_fact": False,
            "allegation_only_promotion_allowed": False,
            "title_date_only_promotion_allowed": False,
            "source_statement_presented_as_independent_verification": False,
            "continuous_story_first_update_expected": True,
        },
    }
    if durable_story_temporal_violations(story, "ro-RO"):
        return None, "generated_durable_temporal_language_violation"
    story["primary_source_verification"]["promotion_fingerprint_sha256"] = canonical_digest({
        "id": story["id"],
        "source_url": source_url,
        "detail_sha256": detail["detail_sha256"],
        "claims": claims,
    })
    return story, "promoted"


def build_from_receipt(source_key: str, receipt: dict[str, Any], *, now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if receipt.get("status") != "PASS":
        return [], [{"source": source_key, "reason": f"receipt_not_pass:{receipt.get('status')}"}]
    stories: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for detail in receipt.get("details") or []:
        if not isinstance(detail, dict):
            continue
        story, reason = promote_detail(source_key, detail, now=now)
        if story is None:
            holds.append({"source": source_key, "url": detail.get("detail_url"), "reason": reason})
            continue
        url = story["sources"][0]["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        stories.append(story)
        if len(stories) == MAX_STORIES_PER_SOURCE:
            break
    return stories, holds


def live_receipts() -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    builders: dict[str, Callable[[], dict[str, Any]]] = {
        "ipj": ipj_detail.build_live_receipt,
        "isu": isu_detail.build_live_receipt,
    }
    receipts: dict[str, dict[str, Any]] = {}
    holds: list[dict[str, str]] = []
    # The two bounded official lanes run concurrently so fast-news verification
    # does not serialize two full county-authority crawls.
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_to_key = {pool.submit(builder): key for key, builder in builders.items()}
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                receipts[key] = future.result()
            except Exception as exc:  # source-specific fail closed, newsroom continues
                holds.append({"source": key, "reason": f"source_fetch_hold:{type(exc).__name__}:{exc}"})
    return receipts, holds


def existing_source_urls(document: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for item in document.get("facts") or []:
        if not isinstance(item, dict):
            continue
        for source in item.get("sources") or []:
            if isinstance(source, dict) and str(source.get("url") or "").strip():
                urls.add(str(source["url"]).strip())
    return urls


def upsert_all(document: dict[str, Any], items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str], list[str]]:
    out = copy.deepcopy(document)
    facts = list(out.get("facts") or [])
    by_id = {str(row.get("id")): index for index, row in enumerate(facts) if isinstance(row, dict) and row.get("id")}
    occupied_urls = existing_source_urls(out)
    changed: list[str] = []
    skipped_duplicate_source: list[str] = []
    for item in items:
        story_id = str(item["id"])
        source_url = str(item["sources"][0]["url"])
        existing_index = by_id.get(story_id)
        if existing_index is None and source_url in occupied_urls:
            skipped_duplicate_source.append(story_id)
            continue
        if existing_index is None:
            facts.append(item)
            by_id[story_id] = len(facts) - 1
            occupied_urls.add(source_url)
            changed.append(story_id)
        elif facts[existing_index] != item:
            facts[existing_index] = item
            changed.append(story_id)
    out["facts"] = facts
    return out, changed, skipped_duplicate_source


def self_test() -> None:
    now = datetime(2026, 9, 2, 15, 0, tzinfo=TZ)
    ipj_url = "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/test-atv-123"
    good_ipj = {
        "index_title": "Doi conducători de ATV depistați în trafic",
        "visible_title": "Doi conducători de ATV depistați în trafic",
        "detail_url": ipj_url,
        "detail_sha256": "a" * 64,
        "index_evidence_sha256": "b" * 64,
        "explicit_date_text": "2 septembrie 2026",
        "verification_state": "POLICE_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
        "field_evidence": [
            {"excerpt": "Polițiștii au depistat un conducător de ATV în timpul verificărilor rutiere efectuate în localitate.", "epistemic_tags": ["POLICE_REPORTED_OBSERVATION", "ROAD_OR_PUBLIC_SAFETY_MEASURE"], "evidence_sha256": "c" * 64},
            {"excerpt": "În cauză a fost întocmit dosar penal, iar cercetările continuă potrivit comunicării poliției.", "epistemic_tags": ["PROCEDURAL_MEASURE"], "evidence_sha256": "d" * 64},
        ],
    }
    story, reason = promote_detail("ipj", good_ipj, now=now)
    assert reason == "promoted" and story is not None
    assert story["auto_scope"] == FAST_SCOPE
    assert story["fact_kernel"]["format_hint"] == "straight_news"
    assert len(story["fact_kernel"]["claims"]) == 2
    assert all(claim["kind"] == "attributed_statement" for claim in story["fact_kernel"]["claims"])
    assert not durable_story_temporal_violations(story, "ro-RO")

    allegation_only = copy.deepcopy(good_ipj)
    allegation_only["detail_url"] += "-allegation"
    allegation_only["field_evidence"] = [
        {"excerpt": "Persoana ar fi comis o faptă, potrivit suspiciunilor menționate în documentul aflat în lucru.", "epistemic_tags": ["ALLEGATION_OR_SUSPICION"], "evidence_sha256": "e" * 64},
        {"excerpt": "Cercetările continuă în dosarul penal deschis pentru clarificarea împrejurărilor menționate.", "epistemic_tags": ["PROCEDURAL_MEASURE"], "evidence_sha256": "f" * 64},
    ]
    assert promote_detail("ipj", allegation_only, now=now)[0] is None

    old = copy.deepcopy(good_ipj)
    old["detail_url"] += "-old"
    old["explicit_date_text"] = "28 august 2026"
    assert promote_detail("ipj", old, now=now)[1] == "explicit_fresh_date_required"

    isu_url = "https://isuvl.igsu.ro/stiri-locale/incendiu-test-456"
    good_isu = {
        "index_title": "Incendiu la o locuință din Râmnicu Vâlcea",
        "visible_title": "Incendiu la o locuință din Râmnicu Vâlcea",
        "detail_url": isu_url,
        "detail_sha256": "1" * 64,
        "index_evidence_sha256": "2" * 64,
        "explicit_date_text": "02.09.2026",
        "verification_state": "ISU_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
        "field_evidence": [
            {"excerpt": "Echipajele operative au constatat că incendiul se manifesta la nivelul podului unei locuințe.", "epistemic_tags": ["ISU_REPORTED_OBSERVATION"], "evidence_sha256": "3" * 64},
            {"excerpt": "Pompierii au intervenit pentru localizarea și lichidarea incendiului și au acordat primul ajutor la fața locului.", "epistemic_tags": ["RESPONSE_ACTION"], "evidence_sha256": "4" * 64},
        ],
    }
    isu_story, isu_reason = promote_detail("isu", good_isu, now=now)
    assert isu_reason == "promoted" and isu_story is not None
    assert isu_story["section"] == "URGENȚE"
    assert not durable_story_temporal_violations(isu_story, "ro-RO")

    doc, changed, duplicates = upsert_all({"facts": []}, [story, isu_story])
    assert set(changed) == {story["id"], isu_story["id"]} and not duplicates
    doc2, changed2, duplicates2 = upsert_all(doc, [story, isu_story])
    assert not changed2 and not duplicates2 and doc2 == doc
    other = copy.deepcopy(story)
    other["id"] += "-duplicate"
    _, changed3, duplicates3 = upsert_all(doc, [other])
    assert not changed3 and duplicates3 == [other["id"]]
    print("VÂLCEA CLAR verified-primary fast kernels self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote fresh first-party emergency/public-safety evidence into fact kernels")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    now = datetime.now(TZ).replace(microsecond=0)
    receipts, source_holds = live_receipts()
    candidates: list[dict[str, Any]] = []
    promotion_holds: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for source_key in ("ipj", "isu"):
        receipt = receipts.get(source_key)
        if not receipt:
            source_counts[source_key] = 0
            continue
        stories, holds = build_from_receipt(source_key, receipt, now=now)
        candidates.extend(stories)
        promotion_holds.extend(holds)
        source_counts[source_key] = len(stories)

    document = json.loads(FACTS.read_text(encoding="utf-8"))
    updated, changed_ids, duplicate_source_ids = upsert_all(document, candidates)
    if args.apply and changed_ids:
        FACTS.write_text(json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    state = {
        "schema_version": "1.0",
        "generated_at": now.isoformat(timespec="seconds"),
        "promotion_gate": PROMOTION_GATE,
        "publication_authority": "FACT_KERNEL_INPUT_ONLY_NORMAL_NEWSROOM_GATE_REQUIRED",
        "source_counts": source_counts,
        "candidate_count": len(candidates),
        "changed_story_ids": changed_ids,
        "duplicate_source_story_ids": duplicate_source_ids,
        "source_holds": source_holds,
        "promotion_holds": promotion_holds[:40],
        "policy": {
            "secondary_signal_is_fact": False,
            "title_date_only_is_article": False,
            "allegation_only_fast_promotion": False,
            "official_source_statement_is_independent_verification": False,
            "source_specific_failure_blocks_unrelated_newsroom": False,
            "continuous_story_first": True,
        },
    }
    if args.apply:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = "UPDATED" if args.apply and changed_ids else "UNCHANGED" if not changed_ids else "DRY_RUN"
    print(json.dumps({"status": status, **state}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
