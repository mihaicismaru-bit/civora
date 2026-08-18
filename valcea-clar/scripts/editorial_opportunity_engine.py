#!/usr/bin/env python3
"""Materialize non-breaking editorial opportunities from VÂLCEA CLAR durable knowledge.

This engine does NOT publish. It turns verified archives, durable monitors and
recovered leads into a ranked queue of possible editorial products such as
explainers, timelines, status checks, permit follow-ups and structured lists.

Core rule: age of the underlying fact is not a global rejection condition.
A document from last month or last year can be the basis of a new article today,
provided its date is explicit and any claim about present status is reverified.
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


def source_descriptors(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source in monitor.get("source_bindings") or []:
        if not isinstance(source, dict):
            continue
        rows.append({
            "id": source.get("id"),
            "ref_type": source.get("ref_type") or "url",
            "publisher": source.get("publisher"),
            "url": source.get("url"),
            "tier": source.get("tier") or source.get("source_class"),
        })
    return rows


def monitor_family(mon: dict[str, Any]) -> str:
    mid = str(mon.get("id") or "")
    text = " ".join([
        mid,
        str(mon.get("label") or ""),
        str(mon.get("purpose") or ""),
        str(mon.get("section") or ""),
    ]).casefold()
    if "council" in mid or "consili" in text or "hotăr" in text or "hotar" in text:
        return "council"
    if "permit" in mid or "urbanism" in text or "imobiliar" in text or "real-estate" in mid or "constru" in text:
        return "real_estate"
    if "infrastruct" in text or "a1" in mid or "dn73" in text or "drum" in text:
        return "infrastructure"
    if "job" in mid or "recrut" in text or "posturi" in text or "munc" in text:
        return "jobs"
    if "firm" in text or "business" in text or "onrc" in text:
        return "business"
    if "spital" in text or "sănăt" in text or "sanat" in text:
        return "health"
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
    if family == "real_estate":
        score += 9
    if family == "infrastructure":
        score += 9
    return min(score, 100)


def why_now(mon: dict[str, Any], state: dict[str, Any], product_type: str, lead: dict[str, Any] | None = None) -> str:
    if lead:
        status = str(lead.get("verification_status") or "NEEDS_REVIEW")
        return f"Lead durabil deschis ({status}); produsul {product_type} poate transforma documentarea existentă într-un material util fără a pretinde că faptul inițial s-a produs astăzi."
    if state.get("changed_sources"):
        return f"Surse monitorizate s-au schimbat; {product_type} poate explica starea sau efectul, după reverificarea faptelor curente."
    return f"Monitor activ cu documente/registre reutilizabile; {product_type} este eligibil editorial independent de data inițială a faptelor."


def add_opportunity(
    out: list[dict[str, Any]],
    *,
    mon: dict[str, Any],
    state: dict[str, Any],
    product_type: str,
    lane: str,
    requires_current: bool,
    score_adjust: int = 0,
    lead: dict[str, Any] | None = None,
    evidence_hint: str,
) -> None:
    family = monitor_family(mon)
    subject_id = str((lead or {}).get("id") or mon.get("id") or "")
    label = str((lead or {}).get("label") or mon.get("label") or subject_id)
    score = max(1, min(100, base_score(mon, state, family) + score_adjust))
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
        "monitor_family": family,
        "subject_id": subject_id,
        "subject_label": label,
        "fact_recency_required": False,
        "current_status_verification_required": requires_current,
        "why_now": why_now(mon, state, product_type, lead),
        "evidence_hint": evidence_hint,
        "source_bindings": source_descriptors(mon),
        "lead_verification_status": (lead or {}).get("verification_status"),
        "normal_story_ready_gate_required": True,
    })


def monitor_opportunities(mon: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    family = monitor_family(mon)
    leads = [row for row in mon.get("recovered_leads") or [] if isinstance(row, dict)]

    if family == "council":
        add_opportunity(out, mon=mon, state=state, product_type="DECISION_DIGEST", lane="knowledge", requires_current=False, score_adjust=3, evidence_hint="Use adopted decisions and official meeting/decision registers; group by topic, money, beneficiaries and practical effect.")
        add_opportunity(out, mon=mon, state=state, product_type="MONEY_TRACE", lane="knowledge", requires_current=True, score_adjust=2, evidence_hint="Start from approved amounts/decisions, then verify procurement, contracts, payments or implementation status as of publication.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="WHAT_HAPPENED_NEXT", lane="monitor", requires_current=True, score_adjust=4, lead=lead, evidence_hint="Reopen the older decision or funding record and verify subsequent implementation, contracts, payments or outcomes.")

    elif family == "real_estate":
        add_opportunity(out, mon=mon, state=state, product_type="ACTIVE_PERMITS_INDEX", lane="service", requires_current=True, score_adjust=5, evidence_hint="Parse official permit/urbanism registers, calculate legal/declared validity where documented, and publish only rows whose status can be established from primary evidence.")
        add_opportunity(out, mon=mon, state=state, product_type="PROJECT_TRACKER", lane="monitor", requires_current=True, score_adjust=3, evidence_hint="Maintain intention → PUZ/PUD → permit → developer → builder → site → completion timeline per project.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="PERMIT_FOLLOWUP", lane="monitor", requires_current=True, score_adjust=6, lead=lead, evidence_hint="Use the historic urbanism/permit chain as baseline, then verify what exists now: later permits, works, amendments, completion, abandonment or litigation.")

    elif family == "infrastructure":
        add_opportunity(out, mon=mon, state=state, product_type="TIMELINE", lane="knowledge", requires_current=False, score_adjust=3, evidence_hint="Build a dated timeline from approvals, contracts, authorizations and documented milestones.")
        add_opportunity(out, mon=mon, state=state, product_type="PROJECT_TRACKER", lane="monitor", requires_current=True, score_adjust=5, evidence_hint="Verify current stage against the latest official source, while retaining older milestones as dated context.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="STATUS_CHECK", lane="monitor", requires_current=True, score_adjust=5, lead=lead, evidence_hint="Ask what has changed since the last verified milestone; old approvals remain valid context but present status needs a current source.")

    elif family == "jobs":
        add_opportunity(out, mon=mon, state=state, product_type="JOBS_ROUNDUP", lane="service", requires_current=True, score_adjust=4, evidence_hint="Aggregate currently open verified vacancies; commercial boards are discovery-only unless the listing itself is the attributable source.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="STATUS_CHECK", lane="monitor", requires_current=True, score_adjust=2, lead=lead, evidence_hint="Verify whether the older recruitment item remains open, closed, corrected or resulted.")

    elif family == "business":
        add_opportunity(out, mon=mon, state=state, product_type="LIST_INDEX", lane="knowledge", requires_current=False, score_adjust=3, evidence_hint="Build verified company lists from official/open datasets with period labels; avoid presenting stale financial periods as current performance.")
        add_opportunity(out, mon=mon, state=state, product_type="MONEY_TRACE", lane="knowledge", requires_current=True, score_adjust=2, evidence_hint="Connect official company identity and financial/public-contract records, verifying any current legal or ownership status at publication time.")

    elif family == "health":
        add_opportunity(out, mon=mon, state=state, product_type="STATUS_CHECK", lane="monitor", requires_current=True, score_adjust=2, evidence_hint="Revisit projects, services or recruitments using old documents as baseline and current institutional evidence for present status.")
        for lead in leads:
            add_opportunity(out, mon=mon, state=state, product_type="WHAT_HAPPENED_NEXT", lane="monitor", requires_current=True, score_adjust=3, lead=lead, evidence_hint="Use the recovered project/recruitment lead as a question, not a fact; establish the current result from primary evidence.")

    else:
        add_opportunity(out, mon=mon, state=state, product_type="EXPLAINER", lane="knowledge", requires_current=False, evidence_hint="Use already verified dated documents to explain the subject without inventing a fresh event hook.")

    return out


def archive_opportunities() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    kernels = load(FACT_KERNELS, {}) or {}
    facts = load(FACTS, {}) or {}
    published_ids = {str(row.get("id") or "") for row in facts.get("facts") or [] if isinstance(row, dict)}
    for row in kernels.get("facts") or []:
        if not isinstance(row, dict) or row.get("status") != "verified":
            continue
        story_id = str(row.get("id") or "")
        source_urls = [src.get("url") for src in row.get("sources") or [] if isinstance(src, dict) and src.get("url")]
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
            "monitor_family": "verified_archive",
            "subject_id": story_id,
            "subject_label": row.get("headline") or story_id,
            "fact_recency_required": False,
            "current_status_verification_required": False,
            "why_now": "Fact kernel verificat disponibil pentru reutilizare editorială; poate susține un alt unghi, o listă, un timeline sau context fără un eveniment nou.",
            "evidence_hint": "Reuse only claims already proven by the kernel unless a new verification stage adds current facts.",
            "source_bindings": [{"url": url} for url in source_urls],
            "already_in_facts_registry": story_id in published_ids,
            "normal_story_ready_gate_required": True,
        })
    return out


def build() -> dict[str, Any]:
    policy = load(POLICY, {}) or {}
    state_map = state_by_id()
    monitor_docs = [
        load(MONITOR_REGISTRY, {}) or {},
        load(INFRA_REGISTRY, {}) or {},
        load(MARKET_REGISTRY, {}) or {},
    ]
    monitors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in monitor_docs:
        for mon in doc.get("monitors") or []:
            if not isinstance(mon, dict):
                continue
            mid = str(mon.get("id") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            monitors.append(mon)

    opportunities: list[dict[str, Any]] = []
    for mon in monitors:
        opportunities.extend(monitor_opportunities(mon, state_map.get(str(mon.get("id") or ""), {})))
    opportunities.extend(archive_opportunities())

    deduped = {str(row["id"]): row for row in opportunities}
    ranked = sorted(deduped.values(), key=lambda row: (-int(row.get("priority_score") or 0), str(row.get("id") or "")))
    lane_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}
    for row in ranked:
        lane_counts[row["lane"]] = lane_counts.get(row["lane"], 0) + 1
        product_counts[row["product_type"]] = product_counts.get(row["product_type"], 0) + 1

    return {
        "schema_version": "1.0",
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
    council = {
        "id": "council-watch-test", "label": "Council Watch", "section": "ADMINISTRAȚIE", "priority": 90,
        "purpose": "hotărâri consiliu", "source_bindings": [{"id": "hcl", "url": "https://example.test/hcl", "tier": "T1"}],
        "recovered_leads": [{"id": "old-decision", "label": "Hotărâre veche", "verification_status": "REVERIFY_FOR_FOLLOWUP"}],
    }
    rows = monitor_opportunities(council, {"attention": "REVIEW_REQUIRED"})
    kinds = {row["product_type"] for row in rows}
    assert {"DECISION_DIGEST", "MONEY_TRACE", "WHAT_HAPPENED_NEXT"}.issubset(kinds)
    assert all(row["fact_recency_required"] is False for row in rows)

    permits = {
        "id": "construction-permits-active-projects-watch", "label": "Autorizații construire", "section": "IMOBILIARE", "priority": 91,
        "purpose": "autorizații construire urbanism proiecte imobiliare", "source_bindings": [],
        "recovered_leads": [{"id": "permit-2025", "label": "Autorizație 2025", "verification_status": "REVERIFY"}],
    }
    rows = monitor_opportunities(permits, {})
    kinds = {row["product_type"] for row in rows}
    assert {"ACTIVE_PERMITS_INDEX", "PROJECT_TRACKER", "PERMIT_FOLLOWUP"}.issubset(kinds)
    assert next(row for row in rows if row["product_type"] == "PERMIT_FOLLOWUP")["current_status_verification_required"] is True
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
        assert all(row.get("fact_recency_required") is False for row in doc["opportunities"] if row.get("lane") != "breaking")
        print(json.dumps({"status": "PASS", "opportunities": doc["opportunity_count"], "lanes": doc["lane_counts"]}, ensure_ascii=False))
        return 0
    output = Path(args.output)
    previous = load(output, {}) or {}
    if previous and semantic(previous) == semantic(doc):
        print("VÂLCEA CLAR Editorial Opportunity Engine: NO_SEMANTIC_CHANGE")
        return 0
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "UPDATED", "opportunities": doc["opportunity_count"], "lanes": doc["lane_counts"], "products": doc["product_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
