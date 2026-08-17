#!/usr/bin/env python3
"""Derive verified, evidence-bound Fact Kernels from durable VÂLCEA CLAR monitor state.

This is the bridge between monitor/document state and Editorial Writer v1.
It never publishes directly. It may only upsert managed Fact Kernel rows into
`editorial/facts_registry.json`; the normal writer, newsroom and quality gates
remain authoritative for publication.

v1 scope: deterministic Council Watch cluster detection for the official
Râmnicu Vâlcea adopted-HCL register. Additional monitor adapters can be added
behind the same contract.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"
COUNCIL = ROOT / "editorial" / "council_watch_rm_valcea_state.json"
DERIVER_ID = "monitor_fact_kernel_v1"
MANAGED_PREFIX = "derived-council-"
GAMBLING_RE = re.compile(r"\b(?:jocuri?\s+de\s+noroc|slot[\s-]?machine|pariuri?)\b", re.I)
ENTITY_RE = re.compile(r"\b([A-ZĂÂÎȘȚ][A-ZĂÂÎȘȚ0-9&.\- ]{1,60}?(?:S\.?R\.?L\.?|S\.?A\.?))\b")


class DerivationHold(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DerivationHold(f"missing_input:{path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def display_date(iso_date: str) -> str:
    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
    months = {
        1: "ianuarie", 2: "februarie", 3: "martie", 4: "aprilie",
        5: "mai", 6: "iunie", 7: "iulie", 8: "august",
        9: "septembrie", 10: "octombrie", 11: "noiembrie", 12: "decembrie",
    }
    return f"{parsed.day} {months[parsed.month]} {parsed.year}"


def extract_entities(rows: list[dict[str, Any]]) -> list[str]:
    entities: set[str] = set()
    for row in rows:
        title = str(row.get("title") or "")
        for match in ENTITY_RE.findall(title):
            value = re.sub(r"\s+", " ", match).strip(" -")
            if value:
                entities.add(value)
    return sorted(entities)


def derive_council_gambling_cluster(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("monitor_id") != "council-watch-rm-valcea":
        raise DerivationHold("council_monitor_identity_mismatch")
    source = state.get("source") if isinstance(state.get("source"), dict) else {}
    source_url = str(source.get("url") or "").strip()
    if source.get("tier") != "T1" or source.get("official_host_only") is not True or not source_url:
        raise DerivationHold("council_official_source_contract_missing")
    health = state.get("register_health") if isinstance(state.get("register_health"), dict) else {}
    if health.get("reachable") is not True or int(health.get("entries_parsed") or 0) < 1:
        return None

    rows = [row for row in state.get("latest_decisions") or [] if isinstance(row, dict)]
    dated = [row for row in rows if re.fullmatch(r"2026-\d{2}-\d{2}", str(row.get("decision_date") or ""))]
    if not dated:
        return None
    latest_date = max(str(row["decision_date"]) for row in dated)
    same_date = [row for row in dated if row.get("decision_date") == latest_date]
    gambling = [row for row in same_date if GAMBLING_RE.search(str(row.get("title") or ""))]

    # A cluster must be materially dominant, not a one-off monitor signal.
    if len(same_date) < 10 or len(gambling) < 8 or len(gambling) / len(same_date) < 0.5:
        return None

    observed_at = parse_dt(str(state.get("generated_at") or ""))
    decision_dt = datetime.fromisoformat(latest_date).replace(tzinfo=timezone.utc)
    if observed_at - decision_dt > timedelta(days=45):
        return None

    entities = extract_entities(gambling)
    count = len(gambling)
    total = len(same_date)
    day_label = display_date(latest_date)
    entity_text = ", ".join(entities) if entities else "operatori identificați în titlurile hotărârilor"
    headline = f"{count} din {total} de hotărâri publicate pentru {day_label} privesc autorizații pentru jocuri de noroc"
    dek = (
        f"Registrul oficial al Consiliului Local Râmnicu Vâlcea afișează {count} hotărâri cu această temă în seria din {day_label}; "
        "ele sunt tratate ca autorizații anuale, nu ca dovadă automată a tot atâtea deschideri noi."
    )

    claims = [
        {
            "id": "cluster-count",
            "role": "material_change",
            "kind": "fact",
            "text": (
                f"În cele {total} de hotărâri cu data de {day_label} din setul cel mai recent al registrului oficial, "
                f"{count} au în titlu autorizarea anuală de funcționare pentru jocuri de noroc, slot-machine sau pariuri."
            ),
            "source_urls": [source_url],
        },
        {
            "id": "meaning-not-new-openings",
            "role": "meaning",
            "kind": "documented_context",
            "text": (
                "Titlurile registrului folosesc formula de autorizație anuală de funcționare; din această evidență, singură, "
                "nu rezultă că fiecare hotărâre reprezintă deschiderea unei locații noi."
            ),
            "source_urls": [source_url],
        },
        {
            "id": "operators-in-register",
            "role": "evidence",
            "kind": "fact",
            "text": (
                f"În titlurile hotărârilor din cluster apar {len(entities)} operatori identificați: {entity_text}."
                if entities
                else "Hotărârile din cluster identifică operatorii economici în titlurile publicate în registrul oficial."
            ),
            "source_urls": [source_url],
        },
        {
            "id": "next-verification",
            "role": "next_watch",
            "kind": "reader_service",
            "text": (
                "Pentru a separa reînnoirile de eventualele puncte de lucru noi, VÂLCEA CLAR compară aceste hotărâri cu autorizările anterioare "
                "și cu documentele individuale înainte de a descrie o locație drept nou deschisă."
            ),
            "source_urls": [source_url],
        },
    ]

    valid_until = observed_at + timedelta(days=4)
    story_id = f"{MANAGED_PREFIX}gambling-{latest_date.replace('-', '')}"
    return {
        "id": story_id,
        "status": "verified",
        "section": "ADMINISTRAȚIE",
        "editorial_type": "explainer",
        "priority": 92,
        "confidence": 97,
        "valid_from": observed_at.isoformat(),
        "valid_until": valid_until.isoformat(),
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [],
        "material_fact_gate": "PASS_EXPLAINER_ONLY",
        "sources": [
            {
                "name": "Primăria Municipiului Râmnicu Vâlcea — registrul Hotărâri adoptate 2026",
                "url": source_url,
                "tier": "T1",
            }
        ],
        "fact_kernel": {
            "format_hint": "explainer",
            "headline": {"text": headline, "source_urls": [source_url]},
            "dek": {"text": dek, "source_urls": [source_url]},
            "claims": claims,
        },
        "derivation": {
            "deriver_id": DERIVER_ID,
            "monitor_id": state.get("monitor_id"),
            "source_state_generated_at": state.get("generated_at"),
            "decision_date": latest_date,
            "rows_on_date": total,
            "matching_rows": count,
            "matching_ratio": round(count / total, 4),
            "entities": entities,
            "decision_text_claims_made": False,
            "source_change_alone_used_as_story": False,
        },
    }


def derive_all() -> list[dict[str, Any]]:
    council = load_json(COUNCIL)
    candidate = derive_council_gambling_cluster(council)
    return [candidate] if candidate else []


def validate_candidate(candidate: dict[str, Any]) -> None:
    if not str(candidate.get("id") or "").startswith(MANAGED_PREFIX):
        raise DerivationHold("unmanaged_story_id")
    if candidate.get("status") != "verified":
        raise DerivationHold("derived_candidate_not_verified")
    if candidate.get("material_fact_gate") != "PASS_EXPLAINER_ONLY":
        raise DerivationHold("unexpected_material_fact_gate")
    kernel = candidate.get("fact_kernel") if isinstance(candidate.get("fact_kernel"), dict) else {}
    if kernel.get("format_hint") != "explainer" or len(kernel.get("claims") or []) < 2:
        raise DerivationHold("fact_kernel_incomplete")
    urls = {str(row.get("url") or "") for row in candidate.get("sources") or [] if isinstance(row, dict)}
    if not urls:
        raise DerivationHold("derived_source_missing")
    for block in [kernel.get("headline") or {}, kernel.get("dek") or {}, *(kernel.get("claims") or [])]:
        refs = {str(url) for url in block.get("source_urls") or []}
        if not refs or not refs.issubset(urls):
            raise DerivationHold("claim_provenance_outside_story_sources")


def apply_candidates(registry: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    result = copy.deepcopy(registry)
    facts = [row for row in result.get("facts") or [] if isinstance(row, dict)]
    by_id = {str(row.get("id") or ""): row for row in facts if row.get("id")}
    changed = 0
    for candidate in candidates:
        validate_candidate(candidate)
        story_id = candidate["id"]
        existing = by_id.get(story_id)
        if existing is not None and (existing.get("derivation") or {}).get("deriver_id") != DERIVER_ID:
            raise DerivationHold(f"refuse_overwrite_unmanaged_story:{story_id}")
        if existing != candidate:
            by_id[story_id] = candidate
            changed += 1
    # Preserve original order, append new managed rows deterministically.
    original_ids = [str(row.get("id") or "") for row in facts if row.get("id")]
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for story_id in original_ids:
        if story_id in by_id and story_id not in seen:
            output.append(by_id[story_id])
            seen.add(story_id)
    for story_id in sorted(by_id):
        if story_id not in seen:
            output.append(by_id[story_id])
            seen.add(story_id)
    result["facts"] = output
    result.setdefault("policy", {})["monitor_fact_kernel_derivation"] = DERIVER_ID
    result["policy"]["monitor_signal_alone_is_publishable"] = False
    result["policy"]["derived_kernels_require_editorial_writer_and_story_gate"] = True
    return result, changed


def self_test() -> int:
    source_url = "https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?OpenView&Count=500"
    rows: list[dict[str, Any]] = []
    operators = ["CARADUNE SRL", "SUPERBET RETAIL SA", "CELLADA SRL", "BAUM SRL", "JOLLYGAMES SRL", "PROJECT IMPEX SRL"]
    for index in range(19):
        operator = operators[index % len(operators)]
        rows.append({
            "decision_number": 304 - index,
            "decision_date": "2026-07-23",
            "title": f"acordare autorizatie anuala de functionare pentru jocuri de noroc - pariuri {operator} - adresa test",
        })
    for index in range(6):
        rows.append({
            "decision_number": 285 - index,
            "decision_date": "2026-07-23",
            "title": f"alta hotarare administrativa {index}",
        })
    sample = {
        "monitor_id": "council-watch-rm-valcea",
        "generated_at": "2026-08-17T05:00:00Z",
        "source": {"url": source_url, "tier": "T1", "official_host_only": True},
        "register_health": {"reachable": True, "entries_parsed": 304},
        "latest_decisions": rows,
    }
    story = derive_council_gambling_cluster(sample)
    assert story is not None
    assert story["derivation"]["matching_rows"] == 19
    assert story["derivation"]["rows_on_date"] == 25
    assert story["fact_kernel"]["format_hint"] == "explainer"
    assert len(story["derivation"]["entities"]) == 6
    validate_candidate(story)
    registry = {"schema_version": "1.0", "policy": {}, "facts": []}
    updated, changed = apply_candidates(registry, [story])
    assert changed == 1 and len(updated["facts"]) == 1
    updated2, changed2 = apply_candidates(updated, [story])
    assert changed2 == 0 and updated2 == updated
    weak = copy.deepcopy(sample)
    weak["latest_decisions"] = rows[:4]
    assert derive_council_gambling_cluster(weak) is None
    print("VÂLCEA CLAR monitor → Fact Kernel self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true", help="Derive and validate without modifying the registry")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    try:
        candidates = derive_all()
        for candidate in candidates:
            validate_candidate(candidate)
        registry = load_json(FACTS)
        updated, changed = apply_candidates(registry, candidates)
    except DerivationHold as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc), "derived": 0}, ensure_ascii=False))
        return 0

    if not args.check and updated != registry:
        FACTS.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "derived": len(candidates),
        "registry_updates": changed,
        "applied": not args.check,
        "ids": [row["id"] for row in candidates],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
