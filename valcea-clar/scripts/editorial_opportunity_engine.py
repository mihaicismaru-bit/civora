#!/usr/bin/env python3
"""Materialize non-breaking editorial opportunities from VÂLCEA CLAR durable knowledge.

This engine does NOT publish. It converts verified archives, durable monitors and
recovered leads into a ranked queue of explainers, timelines, status checks,
permit follow-ups, project trackers and structured lists.

Core rule: the date of the underlying fact is not a global publication gate. A
document from last month or last year can support a new article today when its
date is explicit. Any statement about present status must be reverified with
current evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EDITORIAL = ROOT / "editorial"
POLICY = EDITORIAL / "editorial_product_policy.json"
MONITOR_REGISTRY = EDITORIAL / "monitor_registry.json"
MONITOR_STATE = EDITORIAL / "monitor_state.json"
INFRA_REGISTRY = EDITORIAL / "infrastructure_monitor_registry.json"
MARKET_REGISTRY = EDITORIAL / "market_intelligence_registry.json"
FACT_KERNELS = EDITORIAL / "fact_kernel_registry.json"
FACTS = EDITORIAL / "facts_registry.json"
NEWS_SOURCES = EDITORIAL / "news_sources.json"
MANUAL_SOURCES = EDITORIAL / "manual_watch_sources.json"
DEFAULT_OUTPUT = EDITORIAL / "editorial_opportunity_queue.json"
PUBLICATION_AUTHORITY = "NONE"


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_id(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return "opp-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def state_by_id() -> dict[str, dict[str, Any]]:
    doc = load(MONITOR_STATE, {}) or {}
    return {str(row.get("id") or ""): row for row in doc.get("monitors") or [] if isinstance(row, dict)}


def source_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    news = load(NEWS_SOURCES, {}) or {}
    manual = load(MANUAL_SOURCES, {}) or {}
    return (
        {str(row.get("id") or ""): row for row in news.get("sources") or [] if isinstance(row, dict)},
        {str(row.get("id") or ""): row for row in manual.get("sources") or [] if isinstance(row, dict)},
    )


def source_descriptors(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    news, manual = source_indexes()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding in monitor.get("source_bindings") or []:
        if not isinstance(binding, dict):
            continue
        sid = str(binding.get("id") or "")
        ref_type = str(binding.get("ref_type") or "url")
        resolved = binding
        if ref_type == "news_source_id" and sid in news:
            resolved = {**news[sid], **binding}
        elif ref_type == "manual_watch_source_id" and sid in manual:
            resolved = {**manual[sid], **binding}
        key = f"{ref_type}:{sid}:{resolved.get('url')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "id": sid or None,
            "ref_type": ref_type,
            "publisher": resolved.get("publisher") or resolved.get("name"),
            "url": resolved.get("url"),
            "tier": resolved.get("tier") or resolved.get("source_class"),
            "source_status": resolved.get("status"),
        })
    return rows


def monitor_family(mon: dict[str, Any]) -> str:
    mid = str(mon.get("id") or "").casefold()
    section = str(mon.get("section") or "").casefold()
    text = " ".join([mid, str(mon.get("label") or ""), str(mon.get("purpose") or ""), section]).casefold()

    # Specific domain families must be decided before generic words such as
    # "hotărâre" or "consiliu" that commonly occur inside urbanism monitors.
    if ("real-estate" in mid or "imobiliar" in text or section == "imobiliare") and "market" in mid:
        return "real_estate_market"
    if (
        "permit" in mid
        or "urbanism" in text
        or "autoriza" in text
        or "constru" in text
        or "development" in mid
        or (("real-estate" in mid or section == "imobiliare") and "market" not in mid)
    ):
        return "real_estate_development"
    if "infrastruct" in text or "a1" in mid or "dn73" in text or "drum de mare vitez" in text:
        return "infrastructure"
    if "job" in mid or "recrut" in text or "posturi" in text or "piața munc" in text or "piata munc" in text:
        return "jobs"
    if "firm" in text or "business" in text or "onrc" in text:
        return "business"
    if "spital" in text or "sănăt" in text or "sanat" in text:
        return "health"
    if "council" in mid or "consili" in text or "hotăr" in text or "hotar" in text:
        return "council"
    return "general"


def base_score(mon: dict[str, Any], state: dict[str, Any], family: str) -> int:
    score = int(mon.get("priority") or 70)
    if state.get("attention") == "REVIEW_REQUIRED":
        score += 6
    if state.get("changed_sources"):
        score += 12
    if mon.get("recovered_leads"):
        score += 6
    if family == "council":
        score += 10
    if family.startswith("real_estate"):
        score += 9
    if family == "infrastructure":
        score += 9
    return min(score, 100)


def next_stage(requires_current: bool, archive_verified: bool = False) -> str:
    if requires_current:
        return "CURRENT_PRIMARY_EVIDENCE_COLLECTION"
    if archive_verified:
        return "FACT_KERNEL_REUSE_OR_DERIVATION"
    return "DOCUMENT_EXTRACTION_AND_FACT_KERNEL"


def add_opportunity(
    out: list[dict[str, Any]],
    *,
    mon: dict[str, Any],
    state: dict[str, Any],
    product_type: str,
    lane: str,
    requires_current: bool,
    evidence_hint: str,
    score_adjust: int = 0,
    lead: dict[str, Any] | None = None,
) -> None:
    family = monitor_family(mon)
    subject_id = str((lead or {}).get("id") or mon.get("id") or "")
    label = str((lead or {}).get("label") or mon.get("label") or subject_id)
    score = max(1, min(100, base_score(mon, state, family) + score_adjust))
    verification_status = str((lead or {}).get("verification_status") or "")
    if lead:
        why = (
            f"Lead durabil deschis ({verification_status or 'NEEDS_REVIEW'}); {product_type} poate folosi documentarea istorică "
            "drept baseline fără a pretinde că faptul inițial s-a produs astăzi."
        )
    elif state.get("changed_sources"):
        why = f"Surse monitorizate s-au schimbat; {product_type} poate explica starea sau efectul după reverificarea faptelor curente."
    else:
        why = f"Monitor activ cu documente/registre reutilizabile; {product_type} este eligibil independent de data inițială a faptelor."

    out.append({
        "id": stable_id(str(mon.get("id")), subject_id, product_type),
        "publication_authority": PUBLICATION_AUTHORITY,
        "public_projection": False,
        "lane": lane,
        "product_type": product_type,
        "writer_format": "service_news" if product_type in {"ACTIVE_PERMITS_INDEX", "PROJECT_TRACKER", "LIST_INDEX", "JOBS_ROUNDUP"} else "explainer",
        "section": mon.get("section"),
        "priority_score": score,
        "monitor_id": mon.get("id"),
        "monitor_ids": [mon.get("id")],
        "monitor_family": family,
        "subject_id": subject_id,
        "subject_label": label,
        "fact_recency_required": False,
        "current_status_verification_required": requires_current,
        "why_now": why,
        "evidence_hint": evidence_hint,
        "evidence_status": "CURRENT_REVERIFY_REQUIRED" if requires_current else "DOCUMENTARY_BASELINE_AVAILABLE",
        "next_stage": next_stage(requires_current),
        "source_bindings": source_descriptors(mon),
        "lead_verification_status": verification_status or None,
        "normal_story_ready_gate_required": True,
    })


def monitor_opportunities(mon: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    family = monitor_family(mon)
    leads = [row for row in mon.get("recovered_leads") or [] if isinstance(row, dict)]

    if family == "council":
        add_opportunity(out, mon=mon, state=state, product_type="DECISION_DIGEST", lane="knowledge", requires_current=False, score_adjust=3, evidence_hint="Group adopted decisions by topic, public money, beneficiaries and practical effect using official decision registers.")
        add_opportunity(out, mon=mon, state=state, product_type="MONEY_TRACE", lane="knowledge", requires_current=True, score_adjust=2, evidence_hint="Start from approved amounts/decisions, then verify procurement, contracts, payments or implementation status as of publication.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="WHAT_HAPPENED_NEXT", lane="monitor", requires_current=True, score_adjust=4, lead=lead, evidence_hint="Reopen the older decision/funding record and verify subsequent implementation, contracts, payments or outcomes.")

    elif family == "real_estate_development":
        add_opportunity(out, mon=mon, state=state, product_type="ACTIVE_PERMITS_INDEX", lane="service", requires_current=True, score_adjust=5, evidence_hint="Parse official permit/urbanism registers and publish only rows whose current legal/administrative status can be established from primary evidence.")
        add_opportunity(out, mon=mon, state=state, product_type="PROJECT_TRACKER", lane="monitor", requires_current=True, score_adjust=3, evidence_hint="Maintain intention → PUZ/PUD → permit → beneficiary/developer → builder → site → completion timeline per project.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="PERMIT_FOLLOWUP", lane="monitor", requires_current=True, score_adjust=6, lead=lead, evidence_hint="Use the historic urbanism/permit chain as baseline, then verify later permits, works, amendments, completion, abandonment or litigation.")

    elif family == "real_estate_market":
        add_opportunity(out, mon=mon, state=state, product_type="LIST_INDEX", lane="knowledge", requires_current=False, score_adjust=3, evidence_hint="Build dated inventories of public-property, cadastral or market records without presenting older periods as current market facts.")
        add_opportunity(out, mon=mon, state=state, product_type="STATUS_CHECK", lane="monitor", requires_current=True, score_adjust=2, evidence_hint="Revisit material market/property signals and establish current ownership/operator/status from documentary evidence.")

    elif family == "infrastructure":
        add_opportunity(out, mon=mon, state=state, product_type="TIMELINE", lane="knowledge", requires_current=False, score_adjust=3, evidence_hint="Build a dated timeline from approvals, contracts, authorizations and documented milestones.")
        add_opportunity(out, mon=mon, state=state, product_type="PROJECT_TRACKER", lane="monitor", requires_current=True, score_adjust=5, evidence_hint="Verify current stage against the latest official source while retaining older milestones as dated context.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="STATUS_CHECK", lane="monitor", requires_current=True, score_adjust=5, lead=lead, evidence_hint="Establish what changed since the last verified milestone; old approvals remain context, present status needs a current source.")

    elif family == "jobs":
        add_opportunity(out, mon=mon, state=state, product_type="JOBS_ROUNDUP", lane="service", requires_current=True, score_adjust=4, evidence_hint="Aggregate currently open verified vacancies; commercial boards remain discovery-only unless directly attributable.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="STATUS_CHECK", lane="monitor", requires_current=True, score_adjust=2, lead=lead, evidence_hint="Verify whether the older recruitment item remains open, closed, corrected or resulted.")

    elif family == "business":
        add_opportunity(out, mon=mon, state=state, product_type="LIST_INDEX", lane="knowledge", requires_current=False, score_adjust=3, evidence_hint="Build verified company lists from official/open datasets with explicit reporting periods.")
        add_opportunity(out, mon=mon, state=state, product_type="MONEY_TRACE", lane="knowledge", requires_current=True, score_adjust=2, evidence_hint="Connect official company identity, financial and public-contract records; current legal/ownership status must be reverified.")

    elif family == "health":
        add_opportunity(out, mon=mon, state=state, product_type="STATUS_CHECK", lane="monitor", requires_current=True, score_adjust=2, evidence_hint="Revisit projects, services or recruitments using old documents as baseline and current institutional evidence for present status.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="WHAT_HAPPENED_NEXT", lane="monitor", requires_current=True, score_adjust=3, lead=lead, evidence_hint="Treat the recovered project/recruitment note as a question, not a fact; establish the current result from primary evidence.")

    else:
        add_opportunity(out, mon=mon, state=state, product_type="EXPLAINER", lane="knowledge", requires_current=False, evidence_hint="Use verified dated documents to explain the subject without inventing a fresh event hook.")
    return out


def archive_opportunities() -> list[dict[str, Any]]:
    kernels = load(FACT_KERNELS, {}) or {}
    facts = load(FACTS, {}) or {}
    published_ids = {str(row.get("id") or "") for row in facts.get("facts") or [] if isinstance(row, dict)}
    out: list[dict[str, Any]] = []
    for row in kernels.get("facts") or []:
        if not isinstance(row, dict) or row.get("status") != "verified":
            continue
        story_id = str(row.get("id") or "")
        sources = [src for src in row.get("sources") or [] if isinstance(src, dict) and src.get("url")]
        out.append({
            "id": stable_id("archive", story_id, "REUSE"),
            "publication_authority": PUBLICATION_AUTHORITY,
            "public_projection": False,
            "lane": "knowledge",
            "product_type": "ARCHIVE_REUSE",
            "writer_format": "explainer",
            "section": row.get("section"),
            "priority_score": min(100, int(row.get("priority") or 70) + 8),
            "monitor_id": None,
            "monitor_ids": [],
            "monitor_family": "verified_archive",
            "subject_id": story_id,
            "subject_label": row.get("headline") or story_id,
            "fact_recency_required": False,
            "current_status_verification_required": False,
            "why_now": "Fact kernel verificat disponibil pentru reutilizare editorială; poate susține un alt unghi, listă sau timeline fără un eveniment nou.",
            "evidence_hint": "Reuse only claims already proven by the kernel unless a new verification stage adds current facts.",
            "evidence_status": "VERIFIED_ARCHIVE_AVAILABLE",
            "next_stage": next_stage(False, archive_verified=True),
            "source_bindings": [{"publisher": src.get("name"), "url": src.get("url"), "tier": src.get("tier")} for src in sources],
            "already_in_facts_registry": story_id in published_ids,
            "normal_story_ready_gate_required": True,
        })
    return out


def merge_sources(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in a + b:
        key = f"{row.get('id')}|{row.get('url')}|{row.get('publisher')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def dedupe(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Subject-level follow-ups can be recovered by more than one monitor. Keep a
    # single editorial task, merge source coverage and retain the highest score.
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in opportunities:
        key = (str(row.get("subject_id") or ""), str(row.get("product_type") or ""))
        current = merged.get(key)
        if current is None:
            merged[key] = row
            continue
        winner, loser = (row, current) if int(row.get("priority_score") or 0) > int(current.get("priority_score") or 0) else (current, row)
        winner = json.loads(json.dumps(winner, ensure_ascii=False))
        winner["monitor_ids"] = sorted({str(x) for x in (current.get("monitor_ids") or []) + (row.get("monitor_ids") or []) if x})
        winner["source_bindings"] = merge_sources(current.get("source_bindings") or [], row.get("source_bindings") or [])
        winner["duplicate_monitor_sources_merged"] = True
        merged[key] = winner
    return list(merged.values())


def build() -> dict[str, Any]:
    policy = load(POLICY, {}) or {}
    state_map = state_by_id()
    docs = [load(MONITOR_REGISTRY, {}) or {}, load(INFRA_REGISTRY, {}) or {}, load(MARKET_REGISTRY, {}) or {}]
    monitors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        for mon in doc.get("monitors") or []:
            if not isinstance(mon, dict):
                continue
            mid = str(mon.get("id") or "")
            if mid and mid not in seen:
                seen.add(mid)
                monitors.append(mon)

    raw: list[dict[str, Any]] = []
    for mon in monitors:
        raw.extend(monitor_opportunities(mon, state_map.get(str(mon.get("id") or ""), {})))
    raw.extend(archive_opportunities())
    ranked = sorted(dedupe(raw), key=lambda row: (-int(row.get("priority_score") or 0), str(row.get("id") or "")))

    lane_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for row in ranked:
        lane_counts[row["lane"]] = lane_counts.get(row["lane"], 0) + 1
        product_counts[row["product_type"]] = product_counts.get(row["product_type"], 0) + 1
        family_counts[row["monitor_family"]] = family_counts.get(row["monitor_family"], 0) + 1

    return {
        "schema_version": "1.1",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR Editorial Opportunity Queue",
        "generated_at": now_utc(),
        "publication_authority": PUBLICATION_AUTHORITY,
        "public_projection": False,
        "publication_model": policy.get("publication_model") or "continuous_publication_multi_product",
        "monitor_count": len(monitors),
        "opportunity_count": len(ranked),
        "lane_counts": lane_counts,
        "product_counts": product_counts,
        "family_counts": family_counts,
        "policy": {
            "opportunity_is_not_story": True,
            "opportunity_may_publish_directly": False,
            "age_of_fact_is_not_global_rejection_reason": True,
            "current_status_claim_requires_current_evidence": True,
            "normal_story_ready_gate_required": True,
            "breaking_lane_remains_independent": True,
        },
        "opportunities": ranked,
    }


def semantic(doc: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(doc, ensure_ascii=False))
    clone.pop("generated_at", None)
    return clone


def self_test() -> int:
    council = {"id": "council-watch-test", "label": "Council Watch", "section": "ADMINISTRAȚIE", "priority": 90, "purpose": "hotărâri consiliu", "source_bindings": [], "recovered_leads": [{"id": "old-decision", "label": "Hotărâre veche", "verification_status": "REVERIFY_FOR_FOLLOWUP"}]}
    assert monitor_family(council) == "council"
    kinds = {row["product_type"] for row in monitor_opportunities(council, {})}
    assert {"DECISION_DIGEST", "MONEY_TRACE", "WHAT_HAPPENED_NEXT"}.issubset(kinds)

    permits = {"id": "construction-permits-active-projects-watch", "label": "Autorizații construire", "section": "IMOBILIARE", "priority": 91, "purpose": "hotărâri urbanism autorizații construire", "source_bindings": [], "recovered_leads": [{"id": "permit-2025", "label": "Autorizație 2025", "verification_status": "REVERIFY"}]}
    assert monitor_family(permits) == "real_estate_development"
    rows = monitor_opportunities(permits, {})
    kinds = {row["product_type"] for row in rows}
    assert {"ACTIVE_PERMITS_INDEX", "PROJECT_TRACKER", "PERMIT_FOLLOWUP"}.issubset(kinds)
    assert next(row for row in rows if row["product_type"] == "PERMIT_FOLLOWUP")["fact_recency_required"] is False

    market = {"id": "real-estate-market-watch", "label": "Real Estate Market Watch", "section": "IMOBILIARE", "priority": 82, "purpose": "piață imobiliară", "source_bindings": []}
    assert monitor_family(market) == "real_estate_market"
    print("VÂLCEA CLAR Editorial Opportunity Engine self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    doc = build()
    if args.check:
        assert doc["publication_authority"] == "NONE"
        assert doc["opportunity_count"] >= 1
        assert all(row.get("fact_recency_required") is False for row in doc["opportunities"])
        print(json.dumps({"status": "PASS", "opportunities": doc["opportunity_count"], "lanes": doc["lane_counts"], "families": doc["family_counts"]}, ensure_ascii=False))
        return 0
    output = Path(args.output)
    previous = load(output, {}) or {}
    if previous and semantic(previous) == semantic(doc):
        print("VÂLCEA CLAR Editorial Opportunity Engine: NO_SEMANTIC_CHANGE")
        return 0
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "UPDATED", "opportunities": doc["opportunity_count"], "lanes": doc["lane_counts"], "products": doc["product_counts"], "families": doc["family_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
