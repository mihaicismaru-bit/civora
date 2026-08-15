#!/usr/bin/env python3
"""Generate VÂLCEA CLAR morning/evening editions without a paid LLM API.

The generator is deterministic and fail-closed. It renders only structured
facts that passed an editorial evidence gate. If a new edition cannot pass the
publication gate, the public pointer remains on the last known good edition.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"
EDITIONS = ROOT / "editions"
SITE = ROOT / "site"
META = ROOT / "web" / "data" / "meta.json"
RECON = ROOT / "ops" / "ingest_reconciliation.json"
SOURCE_HEALTH = ROOT / "state" / "source_health.json"
POINTER = SITE / "current_edition.json"
LAST_ATTEMPT = SITE / "last_edition_attempt.json"
TZ = ZoneInfo("Europe/Bucharest")
ALLOWED_GATES = {"PASS", "PASS_DATE_ONLY", "PASS_EXPLAINER_ONLY", "PASS_WITH_CAUTION"}
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
        output.append(fact)
    output.sort(key=lambda item: (-int(item.get("priority") or 0), item["id"]))
    return output


def operational_blocks() -> list[dict]:
    blocks: list[dict] = []
    meta = load_json(META, {})
    recon = load_json(RECON, {})
    if meta:
        places = int(meta.get("place_count") or 0)
        candidates = int(meta.get("candidate_count") or 0)
        summary = recon.get("summary", {}) if recon else {}
        monitored = int(summary.get("ingest_records") or summary.get("ingest_records_total") or recon.get("ingest_records") or 0)
        review_queue = int(summary.get("review_queue") or recon.get("review_queue") or 0)
        blocks.append({
            "id": "unde-iesim-operational",
            "section": "UNDE_IEȘIM",
            "priority": 72,
            "confidence": 100,
            "headline": "Unde ieșim: ghidul public rămâne separat de candidații în verificare",
            "dek": f"{places} localuri sunt în proiecția publică verificată; candidații incompleți nu sunt promovați automat.",
            "paragraphs": [
                f"Motorul «Unde ieșim» are {places} fișe publice și {candidates} candidați ascunși în proiecția web."
                + (f" Ingestia urmărește {monitored} înregistrări." if monitored else ""),
                (f"Coada editorială are {review_queue} elemente de verificat. " if review_queue else "")
                + "Datele comerciale, juridice și de meniu nu sunt completate din presupuneri."
            ],
            "material_fact_gate": "PASS",
            "sources": [{"name": "Registrul canonic VÂLCEA CLAR — Unde ieșim", "url": "https://valceaclar.ro/unde-iesim/", "tier": "T1_INTERNAL"}],
        })

    health = load_json(SOURCE_HEALTH, {})
    if health:
        summary = health.get("summary", {})
        blocks.append({
            "id": "source-radar-operational",
            "section": "NOTA_REDACTIEI",
            "priority": 10,
            "confidence": 100,
            "headline": "Nota redacției — starea surselor",
            "dek": "Schimbările detectate de radar sunt trimise la verificare și nu modifică automat faptele materiale.",
            "paragraphs": [
                f"Radarul a verificat {summary.get('total', 0)} surse: {summary.get('pass', 0)} au trecut normal, "
                f"{summary.get('degraded', 0)} sunt degradate și {summary.get('fail', 0)} au eșuat. "
                f"Au fost detectate {summary.get('changed', 0)} schimbări semantice și {summary.get('resolution_tasks_required', 0)} sarcini de rezoluție."
            ],
            "material_fact_gate": "PASS",
            "sources": [{"name": "VÂLCEA CLAR Source Radar", "url": "https://github.com/mihaicismaru-bit/civora/tree/main/valcea-clar/state", "tier": "T1_INTERNAL"}],
        })
    return blocks


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
    lines.append("\n**Politică editorială:** această ediție este generată automat numai din fapte structurate care au trecut pragul de verificare. Dacă datele verificate sunt insuficiente, ediția este mai scurtă; sistemul nu completează golurile prin presupuneri.\n")
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
        **({"visual": item["visual"]} if item.get("visual") else {}),
    }


def pointer_is_publishable(pointer: dict) -> bool:
    return pointer.get("status") in PUBLISHABLE_STATUSES and pointer.get("publication_intent") == "publish" and bool(pointer.get("edition_id"))


def write_outputs(now: datetime, slot: str, facts: list[dict]) -> tuple[Path, Path, dict]:
    EDITIONS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    items = facts + operational_blocks()
    editorial_count = len(facts)
    publish = editorial_count >= 1
    status_note = "" if editorial_count >= 3 else "Ediție scurtă: publicăm doar informațiile care au trecut pragul de verificare."
    eid = edition_id(now, slot)
    title_slot = "dimineață" if slot == "morning" else "seară"
    payload = {
        "schema_version": "2.1",
        "edition_id": eid,
        "slot": slot,
        "title": f"VÂLCEA CLAR — Ediția de {title_slot}",
        "edition_date": now.date().isoformat(),
        "updated_local": now.isoformat(timespec="seconds"),
        "generator": "deterministic_zero_llm_v1",
        "status": "auto_approved" if publish else "auto_hold",
        "publication_intent": "publish" if publish else "hold",
        "editorial_fact_count": editorial_count,
        "items": [compact_item(item) for item in items],
        "policy": {
            "llm_required": False,
            "external_paid_api_required": False,
            "verified_facts_only": True,
            "shorter_edition_when_evidence_is_sparse": True,
            "last_known_good_fallback": True,
            "human_override_available": True,
        },
    }
    json_path = EDITIONS / f"{eid}.json"
    md_path = EDITIONS / f"{eid}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(now, slot, items, status_note), encoding="utf-8")

    attempt = {
        "schema_version": "1.0",
        "edition_id": eid,
        "slot": slot,
        "status": payload["status"],
        "publication_intent": payload["publication_intent"],
        "editorial_fact_count": editorial_count,
        "updated_local": payload["updated_local"],
    }
    LAST_ATTEMPT.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if publish:
        pointer = {
            "schema_version": "1.1",
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
                "schema_version": "1.1",
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
    sample = {"facts": [{
        "id": "x", "status": "verified", "section": "TEST", "priority": 1, "confidence": 99,
        "valid_from": "2026-08-15T00:00:00+03:00", "valid_until": "2026-08-15T23:59:59+03:00",
        "slots": ["morning"], "headline": "Test", "dek": "Test", "paragraphs": ["Test."],
        "material_fact_gate": "PASS", "sources": [{"name": "S", "url": "https://example.test", "tier": "T1"}]
    }]}
    now = datetime(2026, 8, 15, 8, 0, tzinfo=TZ)
    assert len(eligible_facts(sample, now, "morning")) == 1
    assert eligible_facts(sample, now, "evening") == []
    assert pointer_is_publishable({"edition_id": "x", "status": "auto_approved", "publication_intent": "publish"})
    assert not pointer_is_publishable({"edition_id": "x", "status": "auto_hold", "publication_intent": "hold"})
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
    registry = load_json(FACTS)
    facts = eligible_facts(registry, now, slot)
    json_path, md_path, payload = write_outputs(now, slot, facts)
    print(json.dumps({
        "status": payload["status"],
        "publication_intent": payload["publication_intent"],
        "edition_id": payload["edition_id"],
        "editorial_fact_count": payload["editorial_fact_count"],
        "json": str(json_path.relative_to(ROOT)),
        "markdown": str(md_path.relative_to(ROOT)),
        "public_pointer_preserves_last_known_good_on_hold": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
