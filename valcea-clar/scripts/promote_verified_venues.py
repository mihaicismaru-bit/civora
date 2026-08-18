#!/usr/bin/env python3
"""Safely promote independently verified venue identities into the public catalogue.

This is deliberately narrower than generic editorial auto-publication. A venue may
be promoted only when its own official source is healthy and the ingest record is
already marked VERIFIED_OFFICIAL + DRAFT_ELIGIBLE. Discovery-only records,
review-required records, semantic source changes and identity conflicts remain
fail-closed. Sensitive operator/ownership facts are copied only when an official
legal-entity source explicitly supports them.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import reconcile_ingest

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "ingest" / "state" / "venues.json"
HEALTH_PATH = ROOT / "ingest" / "state" / "source_health.json"
REGISTRY_PATH = ROOT / "ingest" / "source_registry.json"
ALIASES_PATH = ROOT / "ops" / "ingest_aliases.json"
PLACES_PATH = ROOT / "data" / "places.json"
SOURCES_PATH = ROOT / "data" / "sources.json"
RECEIPT_PATH = ROOT / "ops" / "venue_auto_promotion.json"

SAFE_TIERS = {"T1", "T1B"}
SAFE_VERIFICATION = "VERIFIED_OFFICIAL"
SAFE_ELIGIBILITY = "DRAFT_ELIGIBLE"
IDENTITY_SCOPES = {"ADDRESS", "CONTACT", "HOURS", "MENU", "MENU_LINK", "CUISINE", "SERVICES"}
OPERATOR_SCOPES = {"LEGAL_ENTITY", "OPERATOR", "CUI", "REGISTRY_NUMBER"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evidence_ids(item: dict[str, Any]) -> list[str]:
    return [str(row.get("sourceId")) for row in item.get("evidence", []) if row.get("sourceId")]


def source_maps(registry_doc: dict[str, Any], health_doc: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict]]:
    registry = {str(row["id"]): row for row in registry_doc.get("sources", []) if row.get("id")}
    health = {str(row["id"]): row for row in health_doc.get("sources", []) if row.get("id")}
    return registry, health


def healthy_official_sources(
    item: dict[str, Any], registry: dict[str, dict], health: dict[str, dict]
) -> list[str]:
    safe: list[str] = []
    for sid in evidence_ids(item):
        source = registry.get(sid, {})
        probe = health.get(sid, {})
        scopes = {str(value).upper() for value in source.get("authorityScopes", [])}
        if source.get("tier") not in SAFE_TIERS:
            continue
        if probe.get("health") != "OK" or probe.get("semanticHashChanged") is True:
            continue
        if not (scopes & IDENTITY_SCOPES):
            continue
        safe.append(sid)
    return safe


def can_auto_promote(
    item: dict[str, Any], registry: dict[str, dict], health: dict[str, dict]
) -> tuple[bool, str, list[str]]:
    if item.get("editorialEligibility") != SAFE_ELIGIBILITY:
        return False, "editorial_eligibility_not_auto_safe", []
    if item.get("verification") != SAFE_VERIFICATION:
        return False, "venue_identity_not_verified_official", []
    if item.get("publicationReady") is True:
        # The ingest contract intentionally keeps this false. Treating true as
        # suspicious prevents a second, less restrictive publication channel.
        return False, "unexpected_ingest_publication_ready", []
    if not (item.get("address") or {}).get("display") or not item.get("locality"):
        return False, "missing_public_identity_fields", []
    official = healthy_official_sources(item, registry, health)
    if not official:
        return False, "no_healthy_unchanged_official_identity_source", []
    return True, "verified_official_identity", official


def canonical_match(item: dict[str, Any], places: list[dict[str, Any]], aliases: dict[str, str]) -> tuple[dict | None, str | None]:
    by_id = {str(row.get("id")): row for row in places if row.get("id")}
    source_id = str(item.get("id") or "")
    target = aliases.get(source_id)
    if target and target in by_id:
        return by_id[target], "explicit_alias"
    if source_id in by_id:
        return by_id[source_id], "same_id"
    name = reconcile_ingest.normalize(item.get("name"))
    matches = [row for row in places if reconcile_ingest.normalize(row.get("name")) == name]
    if len(matches) == 1:
        return matches[0], "unique_normalized_name"
    if len(matches) > 1:
        return None, "ambiguous_normalized_name"
    return None, None


def sources_for_scope(
    official_ids: list[str], registry: dict[str, dict], wanted: set[str]
) -> list[str]:
    result: list[str] = []
    for sid in official_ids:
        scopes = {str(value).upper() for value in registry.get(sid, {}).get("authorityScopes", [])}
        if scopes & wanted:
            result.append(sid)
    return result


def safe_operator(
    item: dict[str, Any], official_ids: list[str], registry: dict[str, dict]
) -> dict[str, Any]:
    operator = item.get("operator") or {}
    supporting = sources_for_scope(official_ids, registry, OPERATOR_SCOPES)
    verification = str(operator.get("verification") or "")
    legal_name = operator.get("legalName")
    if supporting and legal_name and verification in {"VERIFIED_OFFICIAL", "VERIFIED_OFFICIAL_SITE"}:
        return {
            "legal_name": legal_name,
            "cui": operator.get("cui"),
            "registration_number": operator.get("registryNumber"),
            "public_representative": None,
            "relationship": "operator indicat de sursa oficială verificată",
            "verification_status": "verified",
            "source_ids": supporting,
        }
    return {
        "legal_name": None,
        "cui": None,
        "registration_number": None,
        "public_representative": None,
        "relationship": None,
        "verification_status": "pending",
        "source_ids": [],
    }


def canonical_type(item: dict[str, Any]) -> str:
    categories = {str(value).upper() for value in item.get("categories", [])}
    if "FAST_CASUAL" in categories:
        return "fast_casual"
    if "PUB" in categories:
        return "pub"
    if categories & {"LEISURE", "SPA", "POOL", "ATTRACTION"}:
        return "leisure"
    if "CAFE" in categories or "COFFEE" in categories:
        return "cafe"
    return "restaurant"


def public_menu(
    item: dict[str, Any], official_ids: list[str], registry: dict[str, dict]
) -> dict[str, Any]:
    menu = item.get("menu") or {}
    menu_sources = sources_for_scope(official_ids, registry, {"MENU", "MENU_LINK", "PRICE", "GRAMMAGE"})
    status = str(menu.get("status") or "")
    is_official = bool(menu_sources) and (status.startswith("OFFICIAL") or "VERIFIED_OFFICIAL" in status)
    prices: list[dict[str, Any]] = []
    checked_at = menu.get("asOf")
    if is_official and checked_at:
        for raw in menu.get("prices", []) or []:
            name = raw.get("item") or raw.get("name")
            value = raw.get("price_ron") if raw.get("price_ron") is not None else raw.get("priceRon")
            if value is None:
                value = raw.get("price")
            currency = str(raw.get("currency") or "RON").upper()
            if name and isinstance(value, (int, float)) and currency == "RON":
                prices.append({"item": str(name), "price_ron": value, "source_id": menu_sources[0]})
    return {
        "status": "verified" if is_official else "partial",
        "checked_at": checked_at if is_official else None,
        "source_ids": menu_sources if is_official else [],
        "prices_public": bool(prices),
        "sample_prices": prices[:8],
        "note": (
            "Meniu verificat în sursa oficială; sunt afișate numai prețurile structurate și datate ca RON."
            if is_official
            else "Oferta este cunoscută, dar meniul public rămâne parțial până la verificarea unei surse oficiale utilizabile."
        ),
    }


def to_public_place(
    item: dict[str, Any], target_id: str, target_slug: str, featured_order: int,
    official_ids: list[str], registry: dict[str, dict]
) -> dict[str, Any]:
    contacts = item.get("contacts") or {}
    address = item.get("address") or {}
    hours = item.get("hours") or {}
    menu = item.get("menu") or {}
    categories = [str(value).lower().replace("_", "-") for value in item.get("categories", [])]
    highlights = [str(value) for value in menu.get("highlights", []) if value]
    hours_sources = sources_for_scope(official_ids, registry, {"HOURS"})
    hours_verified = str(hours.get("status") or "") == "VERIFIED_OFFICIAL" and bool(hours_sources)
    public_menu_doc = public_menu(item, official_ids, registry)
    badges = ["Verificat oficial"]
    if hours_verified:
        badges.append("Program verificat")
    elif public_menu_doc["status"] == "verified":
        badges.append("Meniu oficial")

    last_verified = str(item.get("lastVerifiedAt") or "")[:10] or None
    summary = "; ".join(highlights[:4]) if highlights else "Local verificat printr-o sursă oficială activă."
    place = {
        "id": target_id,
        "slug": target_slug,
        "name": item.get("name"),
        "type": canonical_type(item),
        "status": "open" if str(item.get("status") or "").startswith("OPEN") else "unknown",
        "publication_status": "public",
        "verification_level": "verified_official_auto",
        "featured_order": featured_order,
        "badges": badges[:2],
        "last_verified_at": last_verified,
        "location": {
            "address": address.get("display"),
            "city": item.get("locality"),
            "county": item.get("county") or "Vâlcea",
        },
        "contact": {
            "website": contacts.get("website"),
            "phone": list(contacts.get("phones") or []),
            "email": None,
            "social": {},
        },
        "operator": safe_operator(item, official_ids, registry),
        "offer": {
            "summary": summary,
            "cuisine": categories,
            "highlights": highlights,
            "price_level": None,
            "menu": public_menu_doc,
        },
        "hours": {
            "status": "verified" if hours_verified else "needs_confirmation",
            "display": hours.get("weekly") if hours_verified else None,
            "source_ids": hours_sources if hours_verified else [],
        },
        "editorial": {
            "dek": summary,
            "story_path": None,
            "transparency_note": (
                "Fișă promovată automat numai după verificarea identității localului într-o sursă oficială sănătoasă. "
                "Operatorul, conexiunile și alte fapte sensibile rămân separate și fail-closed."
            ),
        },
        "source_ids": official_ids,
    }
    opening = item.get("opening") or {}
    opening_sources = sources_for_scope(official_ids, registry, {"OPENING"})
    if opening.get("date") and opening_sources and "CONFIRMED" in str(opening.get("status") or ""):
        place["opening"] = {
            "opened_at": opening.get("date"),
            "precision": str(opening.get("precision") or "").lower() or None,
            "display": None,
            "source_ids": opening_sources,
        }
    return place


def canonical_source(
    sid: str, registry: dict[str, dict], health: dict[str, dict]
) -> dict[str, Any]:
    source = registry[sid]
    probe = health[sid]
    scopes = [str(value).lower() for value in source.get("authorityScopes", [])]
    observed = str(probe.get("lastSuccessfulAt") or probe.get("observedAt") or "")[:10]
    name = str(source.get("name") or sid)
    publisher = name.split(" — ", 1)[0].strip() or name
    kind = "official_legal" if ({str(v).upper() for v in source.get("authorityScopes", [])} & OPERATOR_SCOPES) else "official_site"
    return {
        "id": sid,
        "name": name,
        "publisher": publisher,
        "url": source.get("url"),
        "kind": kind,
        "authority_score": 100 if source.get("tier") == "T1" else 95,
        "status": "active",
        "last_checked_at": observed,
        "supports": scopes,
    }


def build(
    state_doc: dict[str, Any], health_doc: dict[str, Any], registry_doc: dict[str, Any],
    places_doc: dict[str, Any], sources_doc: dict[str, Any], aliases_doc: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    registry, health = source_maps(registry_doc, health_doc)
    places = deepcopy(places_doc.get("places", []))
    sources = deepcopy(sources_doc.get("sources", []))
    aliases = {str(k): str(v) for k, v in aliases_doc.get("aliases", {}).items()}
    source_by_id = {str(row.get("id")): row for row in sources if row.get("id")}
    promoted: list[str] = []
    refreshed: list[str] = []
    blocked: list[dict[str, str]] = []
    next_order = max([int(row.get("featured_order") or 0) for row in places] + [0]) + 1

    for item in sorted(state_doc.get("items", []), key=lambda row: str(row.get("id") or "")):
        allowed, reason, official_ids = can_auto_promote(item, registry, health)
        if not allowed:
            if item.get("editorialEligibility") in {SAFE_ELIGIBILITY, "DRAFT_REVIEW_REQUIRED"}:
                blocked.append({"id": str(item.get("id")), "reason": reason})
            continue

        canonical, match_method = canonical_match(item, places, aliases)
        if match_method == "ambiguous_normalized_name":
            blocked.append({"id": str(item.get("id")), "reason": "ambiguous_identity_match"})
            continue
        if canonical:
            differences = reconcile_ingest.compare_records(canonical, item)
            if differences:
                blocked.append({"id": str(item.get("id")), "reason": "canonical_identity_conflict"})
                continue
            if canonical.get("publication_status") == "public":
                continue
            target_id = str(canonical["id"])
            target_slug = str(canonical.get("slug") or target_id)
            featured = int(canonical.get("featured_order") or next_order)
            replacement = to_public_place(item, target_id, target_slug, featured, official_ids, registry)
            index = places.index(canonical)
            places[index] = replacement
            refreshed.append(target_id)
        else:
            target_id = str(item["id"])
            replacement = to_public_place(item, target_id, target_id, next_order, official_ids, registry)
            places.append(replacement)
            promoted.append(target_id)
            next_order += 1

        for sid in official_ids:
            if sid not in source_by_id:
                source_by_id[sid] = canonical_source(sid, registry, health)
                sources.append(source_by_id[sid])

    changed = bool(promoted or refreshed)
    generated_at = state_doc.get("lastRun", {}).get("observedAt") or state_doc.get("generatedAt") or places_doc.get("generated_at")
    out_places = deepcopy(places_doc)
    out_sources = deepcopy(sources_doc)
    if changed:
        out_places["generated_at"] = generated_at
        out_places["places"] = places
        out_sources["generated_at"] = generated_at
        out_sources["sources"] = sources
    receipt = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "changed": changed,
        "policy": {
            "scope": "verified_venue_identity_only",
            "generic_material_facts_autopublish": False,
            "requires_verified_official": True,
            "requires_draft_eligible": True,
            "requires_healthy_unchanged_t1_or_t1b": True,
            "review_required_never_auto_promotes": True,
            "discovery_only_never_auto_promotes": True,
            "canonical_conflicts_fail_closed": True,
            "operator_identity_requires_explicit_official_legal_support": True,
        },
        "promoted_new": promoted,
        "promoted_existing_candidates": refreshed,
        "blocked": blocked,
    }
    return out_places, out_sources, receipt


def self_test() -> int:
    registry = {
        "sources": [{
            "id": "official", "name": "Test — site oficial", "url": "https://example.test/",
            "tier": "T1", "type": "OFFICIAL_WEBSITE", "status": "ACTIVE",
            "authorityScopes": ["ADDRESS", "CONTACT", "HOURS", "MENU"],
        }]
    }
    health = {"sources": [{"id": "official", "health": "OK", "observedAt": "2026-08-18T12:00:00+00:00", "semanticHashChanged": False}]}
    base = {
        "id": "test-local", "name": "Test Local", "locality": "Râmnicu Vâlcea", "county": "Vâlcea",
        "address": {"display": "Strada Test 1"}, "categories": ["RESTAURANT"], "status": "OPEN",
        "contacts": {"website": "https://example.test/", "phones": [], "social": []},
        "hours": {"status": "VERIFIED_OFFICIAL", "weekly": "10:00–22:00"},
        "menu": {"status": "OFFICIAL_MENU_AVAILABLE", "asOf": "2026-08-18", "highlights": ["meniu oficial"], "prices": []},
        "operator": {"verification": "NOT_RESEARCHED"},
        "verification": "VERIFIED_OFFICIAL", "editorialEligibility": "DRAFT_ELIGIBLE",
        "publicationReady": False, "lastVerifiedAt": "2026-08-18T12:00:00+00:00",
        "evidence": [{"sourceId": "official"}],
    }
    state = {"lastRun": {"observedAt": "2026-08-18T12:00:00+00:00"}, "items": [deepcopy(base)]}
    places, sources, receipt = build(state, health, registry, {"generated_at": "x", "places": []}, {"generated_at": "x", "sources": []}, {"aliases": {}})
    assert receipt["changed"] is True and receipt["promoted_new"] == ["test-local"]
    assert places["places"][0]["publication_status"] == "public"
    assert places["places"][0]["operator"]["verification_status"] == "pending"
    assert sources["sources"][0]["kind"] == "official_site"

    review = deepcopy(base)
    review["id"] = "review"
    review["editorialEligibility"] = "DRAFT_REVIEW_REQUIRED"
    _, _, receipt = build({"items": [review]}, health, registry, {"places": []}, {"sources": []}, {"aliases": {}})
    assert receipt["changed"] is False

    changed_health = {"sources": [{"id": "official", "health": "OK", "semanticHashChanged": True}]}
    _, _, receipt = build(state, changed_health, registry, {"places": []}, {"sources": []}, {"aliases": {}})
    assert receipt["changed"] is False

    canonical = to_public_place(base, "test-local", "test-local", 1, ["official"], {"official": registry["sources"][0]})
    canonical["location"]["address"] = "Altă adresă 99"
    _, _, receipt = build(state, health, registry, {"places": [canonical]}, {"sources": []}, {"aliases": {}})
    assert receipt["changed"] is False
    assert any(row["reason"] == "canonical_identity_conflict" for row in receipt["blocked"])
    print("Safe venue auto-promotion self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="evaluate promotion without mutating canonical files")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    state_doc = load_json(STATE_PATH)
    health_doc = load_json(HEALTH_PATH)
    registry_doc = load_json(REGISTRY_PATH)
    places_doc = load_json(PLACES_PATH)
    sources_doc = load_json(SOURCES_PATH)
    aliases_doc = load_json(ALIASES_PATH)
    out_places, out_sources, receipt = build(state_doc, health_doc, registry_doc, places_doc, sources_doc, aliases_doc)

    if not args.check:
        if receipt["changed"]:
            dump_json(PLACES_PATH, out_places)
            dump_json(SOURCES_PATH, out_sources)
        dump_json(RECEIPT_PATH, receipt)

    print(json.dumps({
        "status": "PASS",
        "changed": receipt["changed"],
        "promoted_new": receipt["promoted_new"],
        "promoted_existing_candidates": receipt["promoted_existing_candidates"],
        "blocked_count": len(receipt["blocked"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
