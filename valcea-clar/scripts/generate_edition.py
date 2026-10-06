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
import re
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
PUBLICATION_HOLDS = ROOT / "editorial" / "publication_holds.json"
CURRENTNESS_OVERRIDES = ROOT / "editorial" / "currentness_overrides.json"
TZ = ZoneInfo("Europe/Bucharest")
ALLOWED_GATES = {"PASS", "PASS_DATE_ONLY", "PASS_EXPLAINER_ONLY", "PASS_WITH_CAUTION"}
ALLOWED_STATUSES = {"verified", "approved_carry_forward"}
PUBLISHABLE_STATUSES = {"auto_approved", "editor_approved"}
MIN_CONFIDENCE = 90
# Fresh local reporting must not be buried indefinitely by a high-priority
# dossier. Priority remains decisive *inside* a freshness band.
FRESHNESS_BUCKET_HOURS = (36, 96, 168)


def active_publication_holds() -> set[str]:
    """Return unreleased story IDs barred from every public projection."""
    document = load_json(PUBLICATION_HOLDS)
    held: set[str] = set()
    for row in document.get("holds") or []:
        if not isinstance(row, dict):
            continue
        story_id = str(row.get("story_id") or "").strip()
        status = str(row.get("status") or "").strip().upper()
        if story_id and row.get("public_projection") is False and status not in {"RELEASED", "CLOSED", "RESOLVED"}:
            held.add(story_id)
    return held


def currentness_archive_ids() -> set[str]:
    """Return durable story IDs that must not appear in a current edition.

    A story route may remain useful as an archive after its reader-action
    deadline has passed.  The continuous newsroom already respected this
    distinction; recap editions must use the same canonical gate instead of
    silently reintroducing archived stories as current news.
    """
    document = load_json(CURRENTNESS_OVERRIDES, {})
    archived: set[str] = set()
    for row in document.get("overrides") or []:
        if not isinstance(row, dict):
            continue
        story_id = str(row.get("story_id") or "").strip()
        if story_id and row.get("current") is False:
            archived.add(story_id)
    return archived


def currentness_ok(item: dict, now: datetime) -> tuple[bool, str | None]:
    """Apply the shared semantic and timestamp currentness contract."""
    story_id = str(item.get("id") or "").strip()
    if story_id and story_id in currentness_archive_ids():
        return False, "semantic_currentness_archive_override"

    raw = str(item.get("valid_until") or "").strip()
    if not raw:
        return True, None
    try:
        expiry = parse_dt(raw)
    except ValueError:
        return False, "invalid_valid_until"
    if now.astimezone(TZ) > expiry.astimezone(TZ):
        return False, "valid_until_expired"
    return True, None


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
    # independently scoped and can only carry the fields admitted by their
    # discovery/brief contract until they acquire a verified full fact kernel.
    combined = {fact["id"]: fact for fact in automatic.get("facts", []) if fact.get("id")}
    for fact in curated.get("facts", []):
        if fact.get("id"):
            combined[fact["id"]] = fact
    return {"facts": list(combined.values())}, len(automatic.get("facts", []))


def previously_published_ids() -> set[str]:
    """Return story IDs that have already entered a publishable edition.

    Edition slots are discovery/scheduling hints for *new* facts, not a reason
    to silently withdraw an already-published, still-valid story. The current
    registry remains authoritative for status, evidence and validity, so an ID
    found here is retained only if it still passes every other eligibility gate.
    """
    published: set[str] = set()
    if not EDITIONS.is_dir():
        return published
    for path in EDITIONS.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("publication_intent") != "publish" or payload.get("status") not in PUBLISHABLE_STATUSES:
            continue
        for row in payload.get("items") or []:
            if not isinstance(row, dict):
                continue
            story_id = str(row.get("id") or "").strip()
            if story_id:
                published.add(story_id)
    return published


def freshness_bucket(item: dict, now: datetime) -> int:
    """Group current stories by age so a live homepage behaves like a newsroom.

    The source publication/valid-from timestamp is already part of the verified
    fact contract. Future timestamps are clamped to age zero for deterministic
    manual backfills; eligibility separately prevents genuinely future facts.
    """
    started = parse_dt(str(item["valid_from"]))
    age_hours = max(0.0, (now - started).total_seconds() / 3600.0)
    for index, limit in enumerate(FRESHNESS_BUCKET_HOURS):
        if age_hours <= limit:
            return index
    return len(FRESHNESS_BUCKET_HOURS)


def editorial_sort_key(item: dict, now: datetime) -> tuple:
    started = parse_dt(str(item["valid_from"]))
    return (
        freshness_bucket(item, now),
        -int(item.get("priority") or 0),
        -started.timestamp(),
        str(item.get("id") or ""),
    )



RECRUITMENT_SECTIONS = {"LOCURI DE MUNCĂ", "LOCURI DE MUNCA", "JOBS"}
RECRUITMENT_STRONG_MARKERS = (
    "dosarele se depun",
    "depunerea dosarelor",
    "scoate la concurs",
    "scoate la concurs",
    "recrutează",
    "recruteaza",
    "post vacant",
    "posturi vacante",
)
MAJOR_RECRUITMENT_RE = re.compile(r"\b(\d{1,3})\s+(?:de\s+)?(?:posturi|locuri)\b", re.IGNORECASE)
MAJOR_RECRUITMENT_STANDALONE_MIN_POSTS = 25
SPORT_SCHEDULE_MARKERS = (
    "meci programat",
    "partidă programată",
    "partida programată",
    "programul meciului",
    "programul oficial",
    "joacă pe",
    "joaca pe",
)
ROUTINE_EMERGENCY_BULLETIN_MARKERS = (
    "intervenții",
    "interventii",
    "misiunile pompierilor",
    "prim ajutor",
)
FAST_INCIDENT_CURRENT_MAX_HOURS = 96


def standalone_recruitment_is_material(item: dict) -> bool:
    """Fail closed on routine one-off vacancy notices in the main news stream.

    VÂLCEA CLAR may still monitor these notices and expose them through service
    products such as JOBS_ROUNDUP. A standalone news story is reserved for a
    materially larger hiring action or an explicit editorial materiality
    override. Durable routes already published remain in the archive, but the
    current-news set must not be filled with ordinary recruitment notices.
    """
    editorial = item.get("editorial_product") if isinstance(item.get("editorial_product"), dict) else {}
    product_type = str(
        editorial.get("product_type")
        or editorial.get("product")
        or item.get("editorial_product_type")
        or item.get("product_type")
        or ""
    ).strip().upper()
    if product_type in {"JOBS_ROUNDUP", "LIST_INDEX"}:
        return True

    section = str(item.get("section") or "").strip().upper()
    corpus = " ".join(
        [
            str(item.get("headline") or ""),
            str(item.get("dek") or ""),
            " ".join(str(p) for p in item.get("paragraphs") or []),
        ]
    ).casefold()
    is_recruitment = section in RECRUITMENT_SECTIONS or any(marker in corpus for marker in RECRUITMENT_STRONG_MARKERS)
    if not is_recruitment:
        return True

    explicit = str(
        item.get("standalone_materiality")
        or editorial.get("standalone_materiality")
        or ""
    ).strip().upper()
    if explicit in {"PASS", "MATERIAL", "HIGH"}:
        return True
    if item.get("major_reader_impact") is True or editorial.get("major_reader_impact") is True:
        return True

    counts = [int(match.group(1)) for match in MAJOR_RECRUITMENT_RE.finditer(corpus)]
    return bool(counts and max(counts) >= MAJOR_RECRUITMENT_STANDALONE_MIN_POSTS)


def explicit_standalone_materiality(item: dict) -> bool:
    editorial = item.get("editorial_product") if isinstance(item.get("editorial_product"), dict) else {}
    explicit = str(
        item.get("standalone_materiality")
        or editorial.get("standalone_materiality")
        or ""
    ).strip().upper()
    return (
        explicit in {"PASS", "MATERIAL", "HIGH"}
        or item.get("major_reader_impact") is True
        or editorial.get("major_reader_impact") is True
    )


def current_stream_materiality_ok(item: dict, now: datetime) -> bool:
    """Keep the live/current stream narrower than the durable archive.

    The archive may contain useful service notices, fixtures and dated incidents.
    The current stream must answer "what materially matters now", so routine
    schedules, operational roundups and stale one-off incidents route to their
    service/archive surfaces unless an explicit editorial materiality override
    says otherwise.
    """
    if explicit_standalone_materiality(item):
        return True
    if not standalone_recruitment_is_material(item):
        return False

    section = str(item.get("section") or "").strip().upper()
    story_id = str(item.get("id") or "").strip().lower()
    corpus = " ".join(
        [
            str(item.get("headline") or ""),
            str(item.get("dek") or ""),
            " ".join(str(p) for p in item.get("paragraphs") or []),
        ]
    ).casefold()

    # Fixtures belong to the verified Sport service surface. Results, major
    # competition changes or explicitly material sports stories remain eligible.
    if section == "SPORT" and any(marker in corpus for marker in SPORT_SCHEDULE_MARKERS):
        return False

    # Routine aggregate bulletins are source material / service intelligence,
    # not standalone headline inventory in the live newsroom.
    if section in {"URGENȚE", "SIGURANȚĂ", "EVENIMENTE"}:
        if "interven" in corpus and any(marker in corpus for marker in ROUTINE_EMERGENCY_BULLETIN_MARKERS):
            return False

    # One-off fast incidents age out of "current" without deleting their route.
    if story_id.startswith("fast-") and section in {"URGENȚE", "SIGURANȚĂ", "EVENIMENTE"}:
        try:
            age_hours = max(0.0, (now - parse_dt(str(item["valid_from"]))).total_seconds() / 3600.0)
        except (KeyError, ValueError):
            return False
        if age_hours > FAST_INCIDENT_CURRENT_MAX_HOURS:
            return False

    return True


def eligible_facts(registry: dict, now: datetime, slot: str, retained_ids: set[str] | None = None) -> list[dict]:
    output = []
    held = active_publication_holds()
    retained_ids = retained_ids or set()
    for fact in registry.get("facts", []):
        fact_id = str(fact.get("id") or "")
        if fact_id in held:
            continue
        if fact.get("status") not in ALLOWED_STATUSES:
            continue
        if int(fact.get("confidence") or 0) < MIN_CONFIDENCE:
            continue
        if fact.get("material_fact_gate") not in ALLOWED_GATES:
            continue
        # The durable archive is broader than the live current-news surface.
        # Route routine jobs, fixtures, operational bulletins and stale one-off
        # incidents away from "current" unless explicitly material.
        if not current_stream_materiality_ok(fact, now):
            continue
        # Slot membership gates first publication only. Once a story has been
        # published, keep it in the canonical set while it remains valid and
        # passes all evidence/status/hold gates. This prevents morning/evening
        # regeneration from silently deleting still-live URLs.
        if slot not in fact.get("slots", []) and fact_id not in retained_ids:
            continue
        sources = fact.get("sources") or []
        if not sources or any(not source.get("url") for source in sources):
            continue
        valid_from = parse_dt(fact["valid_from"])
        current_ok, _ = currentness_ok(fact, now)
        if valid_from > now or not current_ok:
            continue
        # Evergreen preserves the canonical article in the archive; it must not
        # keep a story in the live current-news set indefinitely. Bound evergreen
        # currentness to the first newsroom freshness band.
        if str(fact.get("publication_lifecycle") or "").strip().lower() == "evergreen":
            age_hours = max(0.0, (now - valid_from).total_seconds() / 3600.0)
            if age_hours > FRESHNESS_BUCKET_HOURS[0]:
                continue
        # Durable newsroom copy must remain true when read later. Relative time
        # words such as "azi", "mâine" or "ieri" are therefore fail-closed even
        # when the underlying fact itself is inside its validity window.
        if durable_story_temporal_violations(fact, "ro-RO"):
            continue
        output.append(fact)
    output.sort(key=lambda item: editorial_sort_key(item, now))
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
    lines.append("\n**Politică editorială:** această ediție este generată automat numai din fapte structurate care au trecut pragul de verificare. Materialele noi compuse de Editorial Writer folosesc exclusiv afirmații legate explicit de surse; materialele vechi sunt validate și păstrate fără rescriere. Un titlu, o dată și un link rămân semnal intern și nu sunt publicate ca articol până la construirea unui fact kernel complet. Copia editorială durabilă folosește date absolute, nu formulări relative de tip «azi/mâine/ieri». Dacă datele verificate sunt insuficiente, ediția este mai scurtă.\n")
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
        "valid_from": item.get("valid_from"),
        "valid_until": item.get("valid_until"),
        "lifecycle_status": item.get("lifecycle_status") or item.get("status"),
        **({"replacement_id": item["replacement_id"]} if item.get("replacement_id") else {}),
        **({"auto_generated": True, "auto_scope": item.get("auto_scope"), "brief_kind": item.get("brief_kind")} if item.get("auto_generated") else {}),
        **({"visual": item["visual"]} if item.get("visual") else {}),
        **({"factbox": item["factbox"]} if item.get("factbox") else {}),
        **({"article_sections": item["article_sections"]} if item.get("article_sections") else {}),
        **({"fact_kernel": item["fact_kernel"]} if item.get("fact_kernel") else {}),
        **({"editorial_product": item["editorial_product"]} if item.get("editorial_product") else {}),
    }


def pointer_is_publishable(pointer: dict) -> bool:
    return pointer.get("status") in PUBLISHABLE_STATUSES and pointer.get("publication_intent") == "publish" and bool(pointer.get("edition_id"))


def write_outputs(now: datetime, slot: str, facts: list[dict], auto_registry_count: int) -> tuple[Path, Path, dict]:
    EDITIONS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    items = facts
    editorial_count = len(items)
    included_auto = sum(1 for fact in items if fact.get("auto_generated"))
    writer_composed = sum(1 for fact in items if (fact.get("editorial_product") or {}).get("writer_mode") == "FACT_KERNEL_COMPOSED")
    publish = editorial_count >= 1
    status_note = "" if editorial_count >= 3 else "Ediție scurtă: publicăm doar informațiile care au trecut pragul de verificare."
    eid = edition_id(now, slot)
    title_slot = "dimineață" if slot == "morning" else "seară"
    payload = {
        "schema_version": "2.8",
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
            "primary_source_auto_scope": "radar_only_until_full_fact_kernel",
            "article_body_material_facts_autopublish": False,
            "shorter_edition_when_evidence_is_sparse": True,
            "last_known_good_fallback": True,
            "published_story_retention_until_ineligible": True,
            "semantic_currentness_overrides_apply_to_editions": True,
            "archived_routes_are_not_current_news": True,
            "slot_gate_applies_to_first_publication_only": True,
            "human_override_available": True,
            "internal_operational_telemetry_public": False,
            "ranking_policy": "freshness_bucket_then_priority_then_publication_time",
            "freshness_bucket_hours": list(FRESHNESS_BUCKET_HOURS),
            "durable_temporal_language_contract": TEMPORAL_CONTRACT,
            "relative_time_words_in_durable_copy": False,
        },
    }
    json_path = EDITIONS / f"{eid}.json"
    md_path = EDITIONS / f"{eid}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(now, slot, items, status_note), encoding="utf-8")

    attempt = {
        "schema_version": "1.3",
        "edition_id": eid,
        "slot": slot,
        "status": payload["status"],
        "publication_intent": payload["publication_intent"],
        "editorial_fact_count": editorial_count,
        "editorial_writer_composed_count": writer_composed,
        "auto_facts_included": included_auto,
        "updated_local": payload["updated_local"],
        "ranking_policy": payload["policy"]["ranking_policy"],
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
            "selection_reason": "freshest_publishable_verified_edition",
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
    return json_path, md_path, payload


def self_test() -> int:
    sample_fact = {
        "id": "x", "status": "verified", "section": "TEST", "priority": 1, "confidence": 99,
        "valid_from": "2026-08-15T00:00:00+03:00", "valid_until": "2026-08-15T23:59:59+03:00",
        "slots": ["morning"], "headline": "Program verificat pentru 15 august 2026",
        "dek": "Programul pentru 15 august 2026 este confirmat de sursa oficială.",
        "paragraphs": ["Informația este formulată cu dată absolută pentru a rămâne corectă în arhivă."],
        "material_fact_gate": "PASS", "sources": [{"name": "S", "url": "https://example.test", "tier": "T1"}]
    }
    sample = {"facts": [sample_fact]}
    now = datetime(2026, 8, 15, 8, 0, tzinfo=TZ)
    eligible = eligible_facts(sample, now, "morning")
    assert len(eligible) == 1
    assert eligible_facts(sample, now, "evening") == []
    assert [row["id"] for row in eligible_facts(sample, now, "evening", retained_ids={"x"})] == ["x"]
    routine_recruitment = {
        "facts": [{
            **sample_fact,
            "id": "routine-recruitment",
            "section": "LOCURI DE MUNCĂ",
            "headline": "Comuna X caută șofer; dosarele se depun până pe 16 octombrie",
            "dek": "Primăria a publicat un singur post vacant și calendarul concursului.",
            "paragraphs": ["Dosarele se depun până la termenul indicat de instituție, conform anunțului oficial publicat."],
        }]
    }
    assert eligible_facts(routine_recruitment, now, "morning") == []

    major_recruitment = {
        "facts": [{
            **sample_fact,
            "id": "major-recruitment",
            "section": "LOCURI DE MUNCĂ",
            "headline": "Instituția scoate la concurs 57 de posturi",
            "dek": "Campania de recrutare include 57 de posturi și are un calendar public verificat.",
            "paragraphs": ["Dosarele se depun în perioada anunțată oficial pentru cele 57 de posturi disponibile."],
        }]
    }
    assert [row["id"] for row in eligible_facts(major_recruitment, now, "morning")] == ["major-recruitment"]

    jobs_roundup = {
        "facts": [{
            **sample_fact,
            "id": "jobs-roundup",
            "section": "LOCURI DE MUNCĂ",
            "headline": "Locuri de muncă verificate în Vâlcea: termenele săptămânii",
            "dek": "Un roundup verificat grupează mai multe oportunități și termene active.",
            "paragraphs": ["Lista reunește anunțuri verificate și termenele lor, fără a transforma fiecare post într-o știre separată."],
            "editorial_product": {"product_type": "JOBS_ROUNDUP"},
        }]
    }
    assert [row["id"] for row in eligible_facts(jobs_roundup, now, "morning")] == ["jobs-roundup"]

    medium_recruitment = {
        "facts": [{
            **sample_fact,
            "id": "medium-recruitment",
            "section": "LOCURI DE MUNCĂ",
            "headline": "Compania caută 11 zidari în Vâlcea",
            "dek": "Oferta verificată cuprinde 11 posturi și un termen activ de candidatură.",
            "paragraphs": ["Anunțul oficial listează 11 locuri de muncă, care rămân utile într-un roundup de servicii."],
        }]
    }
    assert eligible_facts(medium_recruitment, now, "morning") == []

    sport_fixture = {
        "facts": [{
            **sample_fact,
            "id": "sport-fixture",
            "section": "SPORT",
            "headline": "SCM Vâlcea: meci programat pe 18 august 2026, de la 18:00",
            "dek": "Programul oficial confirmă ora partidei, care aparține suprafeței de servicii Sport.",
            "paragraphs": ["Programul oficial al clubului confirmă data și ora meciului fără o schimbare editorială materială suplimentară."],
        }]
    }
    assert eligible_facts(sport_fixture, now, "morning") == []

    emergency_roundup = {
        "facts": [{
            **sample_fact,
            "id": "emergency-roundup",
            "section": "URGENȚE",
            "headline": "ISU Vâlcea: 35 de intervenții, dintre care 24 de prim ajutor",
            "dek": "Buletinul zilnic agregă intervențiile fără un incident singular cu miză materială suplimentară.",
            "paragraphs": ["ISU raportează intervenții de rutină și misiuni de prim ajutor în bilanțul operațional al zilei."],
        }]
    }
    assert eligible_facts(emergency_roundup, now, "morning") == []

    stale_fast_incident = {
        "facts": [{
            **sample_fact,
            "id": "fast-isu-stale-incident",
            "section": "URGENȚE",
            "valid_from": "2026-08-10T08:00:00+03:00",
            "valid_until": "2026-08-31T23:59:59+03:00",
            "headline": "Incendiu verificat la o gospodărie din Vâlcea",
            "dek": "Incidentul rămâne arhivă verificată, dar nu ocupă suprafața curentă după patru zile fără follow-up.",
            "paragraphs": ["Intervenția a fost confirmată oficial, fără un follow-up material care să o mențină în fluxul curent."],
        }]
    }
    assert eligible_facts(stale_fast_incident, datetime(2026, 8, 15, 8, 0, tzinfo=TZ), "morning", retained_ids={"fast-isu-stale-incident"}) == []

    material_sport_override = {
        "facts": [{
            **sample_fact,
            "id": "material-sport",
            "section": "SPORT",
            "headline": "Finala județeană își schimbă stadionul și ora de start",
            "dek": "Schimbarea oficială afectează accesul publicului și este marcată explicit drept materială.",
            "paragraphs": ["Organizatorul a schimbat oficial stadionul și ora, iar publicul trebuie să își ajusteze deplasarea."],
            "standalone_materiality": "MATERIAL",
        }]
    }
    assert [row["id"] for row in eligible_facts(material_sport_override, now, "morning")] == ["material-sport"]

    title_only = {"facts": [{**sample_fact, "id": "title-only", "material_fact_gate": "PASS_TITLE_DATE_ONLY"}]}
    assert eligible_facts(title_only, now, "morning") == []
    relative = {"facts": [{**sample_fact, "id": "relative", "headline": "Azi are loc programul verificat"}]}
    assert eligible_facts(relative, now, "morning") == []
    assert all(item.get("id") not in {"unde-iesim-operational", "source-radar-operational"} for item in eligible)
    held_fact = {"facts": [{**sample_fact, "id": "olanesti-bridge-monitor"}]}
    assert eligible_facts(held_fact, now, "morning") == []
    semantically_archived = {
        "facts": [{
            **sample_fact,
            "id": "costesti-iluminat-public-achizitie-20260928",
            "valid_until": "2026-12-31T23:59:59+02:00",
        }]
    }
    assert eligible_facts(semantically_archived, now, "morning", retained_ids={"costesti-iluminat-public-achizitie-20260928"}) == []
    assert currentness_ok(
        {"id": "apavil-joburi-fara-experienta-20260818", "valid_until": "2026-12-31T23:59:59+02:00"},
        datetime(2026, 9, 30, 5, 30, tzinfo=TZ),
    ) == (False, "semantic_currentness_archive_override")
    assert currentness_ok(
        {"id": "expired", "valid_until": "2026-09-29T23:59:00+03:00"},
        datetime(2026, 9, 30, 5, 30, tzinfo=TZ),
    ) == (False, "valid_until_expired")

    sample_kernel = {
        "format_hint": "service_news",
        "headline": {"text": sample_fact["headline"], "source_urls": ["https://example.test"]},
        "dek": {"text": sample_fact["dek"], "source_urls": ["https://example.test"]},
        "claims": [{"id": "c1", "role": "reader_service", "kind": "fact", "text": sample_fact["paragraphs"][0], "source_urls": ["https://example.test"]}],
    }
    projected = compact_item({**sample_fact, "fact_kernel": sample_kernel})
    assert projected.get("fact_kernel") == sample_kernel

    # Freshness is intentionally stronger than legacy priority across bands.
    ranking_now = datetime(2026, 8, 26, 22, 30, tzinfo=TZ)
    recent = {
        **sample_fact,
        "id": "recent",
        "priority": 84,
        "valid_from": "2026-08-26T15:00:00+03:00",
        "valid_until": "2026-08-29T15:00:00+03:00",
        "slots": ["evening"],
        "headline": "Informare verificată publicată la 26 august 2026",
    }
    older = {
        **sample_fact,
        "id": "older",
        "priority": 100,
        "valid_from": "2026-08-21T10:00:00+03:00",
        "valid_until": "2026-08-30T10:00:00+03:00",
        "slots": ["evening"],
        "headline": "Dosar verificat publicat la 21 august 2026",
    }
    ranked = eligible_facts({"facts": [older, recent]}, ranking_now, "evening")
    assert [row["id"] for row in ranked] == ["recent", "older"]
    assert freshness_bucket(recent, ranking_now) == 0
    assert freshness_bucket(older, ranking_now) == 2

    evergreen_old = {
        **older,
        "id": "evergreen-old",
        "publication_lifecycle": "evergreen",
        "valid_until": "2099-12-31T23:59:59+03:00",
    }
    assert eligible_facts({"facts": [evergreen_old]}, ranking_now, "evening") == []

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
    retained_ids = previously_published_ids()
    facts = eligible_facts(registry, now, slot, retained_ids=retained_ids)
    json_path, md_path, payload = write_outputs(now, slot, facts, auto_registry_count)
    print(json.dumps({
        "status": payload["status"],
        "publication_intent": payload["publication_intent"],
        "edition_id": payload["edition_id"],
        "editorial_fact_count": payload["editorial_fact_count"],
        "editorial_writer_composed_count": payload["editorial_writer_composed_count"],
        "auto_fact_registry_count": payload["auto_fact_registry_count"],
        "auto_facts_included": payload["auto_facts_included"],
        "retained_published_story_ids": len(retained_ids),
        "json": str(json_path.relative_to(ROOT)),
        "markdown": str(md_path.relative_to(ROOT)),
        "public_pointer_preserves_last_known_good_on_hold": True,
        "published_story_retention_until_ineligible": True,
        "public_items_are_editorial_only": True,
        "ranking_policy": payload["policy"]["ranking_policy"],
        "durable_temporal_language_contract": TEMPORAL_CONTRACT,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
