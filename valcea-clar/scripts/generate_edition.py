#!/usr/bin/env python3
"""Generate VÂLCEA CLAR morning/evening editions without a paid LLM API.

The generator is deterministic and fail-closed. It renders only structured
facts that passed an editorial evidence gate. Curated facts are first routed
through the VÂLCEA CLAR Editorial Writer, which either composes a new story from
claim-level provenance or validates legacy approved copy without rewriting it.
It then merges those products with narrowly scoped automatic facts discovered
from primary sources. If a new edition cannot pass the publication gate, the
public pointer remains on the last known good edition.

Public edition items are strictly reader-facing editorial facts. Operational
telemetry (source health, ingest queues, hidden candidates) stays in its
backend state files and is never rendered as news.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import editorial_writer

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "local-news-os" / "core"))
from temporal_freshness import CONTRACT as TEMPORAL_CONTRACT, durable_story_temporal_violations

FACTS = ROOT / "editorial" / "facts_registry.json"
AUTO_FACTS = ROOT / "editorial" / "auto_facts.json"
EDITIONS = ROOT / "editions"
SITE = ROOT / "site"
POINTER = SITE / "current_edition.json"
LAST_ATTEMPT = SITE / "last_edition_attempt.json"
TZ = ZoneInfo("Europe/Bucharest")
ALLOWED_GATES = {"PASS", "PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY", "PASS_EXPLAINER_ONLY", "PASS_WITH_CAUTION"}
ALLOWED_STATUSES = {"verified", "approved_carry_forward"}
PUBLISHABLE_STATUSES = {"auto_approved", "editor_approved"}
MIN_CONFIDENCE = 90


def load_json(path: Path, default=None):
    if not path.is_file():
        if default is not None:
            return default
        raise SystemExit(f"Missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)


def choose_slot(now: datetime, requested: str) -> str:
    if requested != "auto":
        return requested
    return "morning" if now.hour < 15 else "evening"


def merged_registry() -> tuple[dict, int]:
    # This call is the activation point for Editorial Writer v1. It fails closed
    # if the manual contract itself is invalid. Individual malformed fact kernels
    # are converted to editorial_hold and therefore cannot enter eligible_facts.
    curated = editorial_writer.materialize_curated_registry(write_output=True)
    automatic = load_json(AUTO_FACTS, {"facts": []})
    # Curated/editorial products win on id collisions. Automatic facts remain
    # independently scoped and can only carry title/date/source data admitted by
    # their discovery gate until they acquire a verified full fact kernel.
    combined = {fact["id"]: fact for fact in automatic.get("facts", []) if fact.get("id")}
    for fact in curated.get("facts", []):
        if fact.get("id"):
            combined[fact["id"]] = fact
    return {"facts": list(combined.values())}, len(automatic.get("facts", []))


def eligible_facts(registry: dict, now: datetime, slot: str) -> list[dict]:
    output = []
    for fact in registry.get("facts", []):
        if fact.get("status") not in ALLOWED_STATUSES:
            continue
        if int(fact.get("confidence") or 0) < MIN_CONFIDENCE:
            continue
        if fact.get("material_fact_gate") not in ALLOWED_GATES:
            continue
        if slot not in fact.get("slots", []):
            continue
        sources = fact.get("sources") or []
        if not sources or any(not source.get("url") for source in sources):
            continue
        if not (parse_dt(fact["valid_from"]) <= now <= parse_dt(fact["valid_until"])):
            continue
        # Durable newsroom copy must remain true when read later. Relative time
        # words such as "azi", "mâine" or "ieri" are therefore fail-closed even
        # when the underlying fact itself is inside its validity window.
        if durable_story_temporal_violations(fact, "ro-RO"):
            continue
        output.append(fact)
    output.sort(key=lambda item: (-int(item.get("priority") or 0), item["id"]))
    return output


def edition_id(now: datetime, slot: str) -> str:
    return f"{now.date().isoformat()}-{slot}"


def render_markdown(now: datetime, slot: str, items: list[dict], status_note: str) -> str:
    label = "dimineață" if slot == "morning" else "seară"
    lines = [f"# VÂLCEA CLAR — Ediția de {label}\n\n", f"**Actualizată automat la {now.strftime('%d.%m.%Y · %H:%M')} · Europe/Bucharest**\n\n"]
    if status_note:
        lines.append(f"> {status_note}\n\n")
    for index, item in enumerate(items, 1):
        lines.append(f"## {index}. {item['headline']}\n\n")
        if str(item.get("dek") or "").strip():
            lines.append(f"**{str(item['dek']).strip()}**\n\n")
        for paragraph in item.get("paragraphs", []):
            if paragraph:
                lines.append(str(paragraph).strip() + "\n\n")
    lines.append("---\n\n## Sursele ediției\n\n")
    seen = set()
    for item in items:
        for source in item.get("sources", []):
            key = (source.get("name"), source.get("url"))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {source.get('name')} — {source.get('url')}\n")
    lines.append("\n**Politică editorială:** această ediție este generată automat numai din fapte structurate care au trecut pragul de verificare. Materialele noi compuse de Editorial Writer folosesc exclusiv afirmații legate explicit de surse; materialele vechi sunt validate și păstrate fără rescriere. Pentru fluxul automat din surse primare, sistemul poate admite numai titlul, data publicării și linkul sursei până când există un fact kernel complet. Copia editorială durabilă folosește date absolute, nu formulări relative de tip «azi/mâine/ieri». Dacă datele verificate sunt insuficiente, ediția este mai scurtă.\n")
    return "".join(lines)


def compact_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "section": item["section"],
        "priority": item["priority"],
        "headline": item["headline"],
        "dek": item.get("dek", ""),
        "paragraphs": item.get("paragraphs", []),
        "confidence": item["confidence"],
        "material_fact_gate": item["material_fact_gate"],
        "sources": item.get("sources", []),
        **({"auto_generated": True, "auto_scope": item.get("auto_scope")} if item.get("auto_generated") else {}),
        **({"visual": item["visual"]} if item.get("visual") else {}),
        **({"factbox": item["factbox"]} if item.get("factbox") else {}),
        **({"article_sections": item["article_sections"]} if item.get("article_sections") else {}),
        **({"editorial_product": item["editorial_product"]} if item.get("editorial_product") else {}),
    }


def pointer_is_publishable(pointer: dict) -> bool:
    return pointer.get("status") in PUBLISHABLE_STATUSES and pointer.get("publication_intent") == "publish" and bool(pointer.get("edition_id"))


def write_outputs(now: datetime, slot: str, facts: list[dict], auto_registry_count: int) -> tuple[Path, Path, dict]:
    EDITIONS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    # LOCAL NEWS OS contract: public edition items are editorial facts only.
    # Backend health/queue telemetry remains in its dedicated state files.
    items = facts
    editorial_count = len(items)
    included_auto = sum(1 for fact in items if fact.get("auto_generated"))
    writer_composed = sum(1 for fact in items if (fact.get("editorial_product") or {}).get("writer_mode") == "FACT_KERNEL_COMPOSED")
    publish = editorial_count >= 1
    status_note = "" if editorial_count >= 3 else "Ediție scurtă: publicăm doar informațiile care au trecut pragul de verificare."
    eid = edition_id(now, slot)
    title_slot = "dimineață" if slot == "morning" else "seară"
    payload = {
        "schema_version": "2.5",
        "edition_id": eid,
        "slot": slot,
        "title": f"VÂLCEA CLAR — Ediția de {title_slot}",
        "edition_date": now.date().isoformat(),
        "updated_local": now.isoformat(timespec="seconds"),
        "generator": "deterministic_zero_llm_v2+manual_journalism_v1",
        "status": "auto_approved" if publish else "auto_hold",
        "publication_intent": "publish" if publish else "hold",
        "editorial_fact_count": editorial_count,
        "editorial_writer_composed_count": writer_composed,
        "auto_fact_registry_count": auto_registry_count,
        "auto_facts_included": included_auto,
        "items": [compact_item(item) for item in items],
        "policy": {
            "llm_required": False,
            "external_paid_api_required": False,
            "verified_facts_only": True,
            "editorial_writer": editorial_writer.WRITER_ID,
            "new_kernel_claim_level_provenance_required": True,
            "legacy_copy_rewritten": False,
            "primary_source_auto_scope": "title_date_source_only",
            "article_body_material_facts_autopublish": False,
            "shorter_edition_when_evidence_is_sparse": True,
            "last_known_good_fallback": True,
            "human_override_available": True,
            "internal_operational_telemetry_public": False,
            "durable_temporal_language_contract": TEMPORAL_CONTRACT,
            "relative_time_words_in_durable_copy": False,
        },
    }
    json_path = EDITIONS / f"{eid}.json"
    md_path = EDITIONS / f"{eid}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(now, slot, items, status_note), encoding="utf-8")

    attempt = {
        "schema_version": "1.2",
        "edition_id": eid,
        "slot": slot,
        "status": payload["status"],
        "publication_intent": payload["publication_intent"],
        "editorial_fact_count": editorial_count,
        "editorial_writer_composed_count": writer_composed,
        "auto_facts_included": included_auto,
        "updated_local": payload["updated_local"],
    }
    LAST_ATTEMPT.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if publish:
        pointer = {
            "schema_version": "1.2",
            "edition_id": eid,
            "slot": slot,
            "status": payload["status"],
            "publication_intent": payload["publication_intent"],
            "updated_local": payload["updated_local"],
            "json_source": f"editions/{json_path.name}",
            "markdown_source": f"editions/{md_path.name}",
            "path": "/editia-de-dimineata/" if slot == "morning" else "/editia-de-seara/",
            "homepage_role": "primary_lead",
            "selection_reason": "latest_publishable_verified_edition",
        }
        POINTER.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        previous = load_json(POINTER, {})
        if not pointer_is_publishable(previous):
            hold_pointer = {
                "schema_version": "1.2",
                "edition_id": eid,
                "slot": slot,
                "status": payload["status"],
                "publication_intent": "hold",
                "updated_local": payload["updated_local"],
                "json_source": f"editions/{json_path.name}",
                "markdown_source": f"editions/{md_path.name}",
                "path": "/editia-curenta/",
                "homepage_role": "hidden",
                "selection_reason": "no_publishable_edition_exists",
            }
            POINTER.write_text(json.dumps(hold_pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Otherwise preserve the last-known-good public pointer unchanged.
    return json_path, md_path, payload


def self_test() -> int:
    sample_fact = {
        "id": "x", "status": "verified", "section": "TEST", "priority": 1, "confidence": 99,
        "valid_from": "2026-08-15T00:00:00+03:00", "valid_until": "2026-08-15T23:59:59+03:00",
        "slots": ["morning"], "headline": "Program verificat pentru 15 august 2026",
        "dek": "Programul pentru 15 august 2026 este confirmat de sursa oficială.",
        "paragraphs": ["Informația este formulată cu dată absolută pentru a rămâne corectă în arhivă."],
        "material_fact_gate": "PASS_TITLE_DATE_ONLY", "sources": [{"name": "S", "url": "https://example.test", "tier": "T1"}]
    }
    sample = {"facts": [sample_fact]}
    now = datetime(2026, 8, 15, 8, 0, tzinfo=TZ)
    eligible = eligible_facts(sample, now, "morning")
    assert len(eligible) == 1
    assert eligible_facts(sample, now, "evening") == []
    relative = {"facts": [{**sample_fact, "id": "relative", "headline": "Azi are loc programul verificat"}]}
    assert eligible_facts(relative, now, "morning") == []
    assert all(item.get("id") not in {"unde-iesim-operational", "source-radar-operational"} for item in eligible)
    assert pointer_is_publishable({"edition_id": "x", "status": "auto_approved", "publication_intent": "publish"})
    assert not pointer_is_publishable({"edition_id": "x", "status": "auto_hold", "publication_intent": "hold"})
    editorial_writer.self_test()
    print("Autonomous edition generator self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=["auto", "morning", "evening"], default="auto")
    parser.add_argument("--date", help="YYYY-MM-DD; mainly for deterministic tests/manual backfills")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    now = datetime.now(TZ)
    if args.date:
        parsed_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        now = datetime.combine(parsed_date, now.timetz()).astimezone(TZ)
    slot = choose_slot(now, args.slot)
    registry, auto_registry_count = merged_registry()
    facts = eligible_facts(registry, now, slot)
    json_path, md_path, payload = write_outputs(now, slot, facts, auto_registry_count)
    print(json.dumps({
        "status": payload["status"],
        "publication_intent": payload["publication_intent"],
        "edition_id": payload["edition_id"],
        "editorial_fact_count": payload["editorial_fact_count"],
        "editorial_writer_composed_count": payload["editorial_writer_composed_count"],
        "auto_fact_registry_count": payload["auto_fact_registry_count"],
        "auto_facts_included": payload["auto_facts_included"],
        "json": str(json_path.relative_to(ROOT)),
        "markdown": str(md_path.relative_to(ROOT)),
        "public_pointer_preserves_last_known_good_on_hold": True,
        "public_items_are_editorial_only": True,
        "durable_temporal_language_contract": TEMPORAL_CONTRACT,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
